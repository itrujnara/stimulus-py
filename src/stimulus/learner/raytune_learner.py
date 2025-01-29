"""Ray Tune wrapper and trainable model classes for hyperparameter optimization."""

import datetime
import logging
import os
import random
from typing import Any, Optional, TypedDict

import numpy as np
import torch
from ray import cluster_resources, train, tune
from ray.tune import Trainable, schedulers
from safetensors.torch import load_model as safe_load_model
from safetensors.torch import save_model as safe_save_model
from torch import nn, optim
from torch.utils.data import DataLoader, Dataset

from stimulus.data.handlertorch import TorchDataset
from stimulus.learner.predict import PredictWrapper
from stimulus.utils.generic_utils import set_general_seeds
from stimulus.utils.yaml_model_schema import YamlRayConfigLoader


class CheckpointDict(TypedDict):
    """Dictionary type for checkpoint data."""

    checkpoint_dir: str


class TuneWrapper:
    """Wrapper class for Ray Tune hyperparameter optimization."""

    def __init__(
        self,
        config_path: str,
        model_class: nn.Module,
        data_path: str,
        experiment_object: object,
        ray_results_dir: Optional[str] = None,
        tune_run_name: Optional[str] = None,
        *,  # Force debug to be keyword-only
        debug: bool = False,
    ) -> None:
        """Initialize the TuneWrapper with the paths to the config, model, and data."""
        self.config = YamlRayConfigLoader(config_path).get_config()

        # set all general seeds: python, numpy and torch.
        set_general_seeds(self.config["seed"])

        self.config["model"] = model_class
        self.config["experiment"] = experiment_object

        # add the ray method for number generation to the config
        self.config["ray_worker_seed"] = tune.randint(0, 1000)

        # add the data path to the config
        if not os.path.exists(data_path):
            raise ValueError("Data path does not exist. Given path:" + data_path)
        self.config["data_path"] = os.path.abspath(data_path)

        # build the tune config
        self.config["tune"]["tune_params"]["scheduler"] = getattr(schedulers, self.config["tune"]["scheduler"]["name"])(
            **self.config["tune"]["scheduler"]["params"],
        )
        self.tune_config = tune.TuneConfig(**self.config["tune"]["tune_params"])

        # build the run config
        self.checkpoint_config = train.CheckpointConfig(checkpoint_at_end=True)
        if tune_run_name is None:
            tune_run_name = "TuneModel_" + datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        self.run_config = train.RunConfig(
            name=tune_run_name,
            storage_path=ray_results_dir,
            checkpoint_config=self.checkpoint_config,
            **self.config["tune"]["run_params"],
        )

        # Set up tune_run path
        if ray_results_dir is None:
            ray_results_dir = os.environ.get("HOME", "")
        self.config["tune_run_path"] = os.path.join(ray_results_dir, tune_run_name)

        # Set debug flag
        self.config["_debug"] = debug

        self.tuner = self.tuner_initialization()

    def tuner_initialization(self) -> tune.Tuner:
        """Prepare the tuner with the configs."""
        # Get available resources from Ray cluster
        cluster_res = cluster_resources()
        logging.info(f"CLUSTER resources   ->  {cluster_res}")

        # Check per-trial resources
        self.gpu_per_trial = self._check_per_trial_resources("gpu_per_trial", cluster_res, "GPU")
        self.cpu_per_trial = self._check_per_trial_resources("cpu_per_trial", cluster_res, "CPU")

        logging.info(f"PER_TRIAL resources ->  GPU: {self.gpu_per_trial} CPU: {self.cpu_per_trial}")

        # Configure trainable with resources and data
        trainable = tune.with_resources(TuneModel, resources={"cpu": self.cpu_per_trial, "gpu": self.gpu_per_trial})
        trainable = tune.with_parameters(
            trainable,
            training=TorchDataset(self.config["data_path"], self.config["experiment"], split=0),
            validation=TorchDataset(self.config["data_path"], self.config["experiment"], split=1),
        )

        return tune.Tuner(trainable, tune_config=self.tune_config, param_space=self.config, run_config=self.run_config)

    def tune(self) -> None:
        """Run the tuning process."""
        self.tuner.fit()

    def _check_per_trial_resources(
        self,
        resource_key: str,
        cluster_max_resources: dict[str, float],
        resource_type: str,
    ) -> float:
        """Check requested per-trial resources against available cluster resources.

        This function validates and adjusts the requested per-trial resource allocation based on the
        available cluster resources. It handles three cases:
        1. Resource request is within cluster limits - uses requested amount
        2. Resource request exceeds cluster limits - warns and uses maximum available
        3. No resource request specified - calculates reasonable default based on cluster capacity

        Args:
            resource_key: Key in config for the resource (e.g. "gpu_per_trial")
            cluster_max_resources: Dictionary of maximum available cluster resources
            resource_type: Type of resource being checked ("GPU" or "CPU")

        Returns:
            float: Number of resources to allocate per trial

        Note:
            For GPUs, returns 0.0 if no GPUs are available in the cluster.
        """
        if resource_type == "GPU" and resource_type not in cluster_max_resources:
            return 0.0

        per_trial_resource: float = 0.0

        # Check if resource is specified in config and within limits
        if (
            resource_key in self.config["tune"]
            and self.config["tune"][resource_key] <= cluster_max_resources[resource_type]
        ):
            per_trial_resource = float(self.config["tune"][resource_key])

        # Warn if requested resources exceed available
        elif (
            resource_key in self.config["tune"]
            and self.config["tune"][resource_key] > cluster_max_resources[resource_type]
        ):
            logging.warning(
                f"\n\n####   WARNING  - {resource_type} per trial are more than what is available. "
                f"{resource_type} per trial: {self.config['tune'][resource_key]} "
                f"available: {cluster_max_resources[resource_type]} "
                "overwriting value to max available",
            )
            per_trial_resource = float(cluster_max_resources[resource_type])

        # Set default if not specified
        elif resource_key not in self.config["tune"]:
            if cluster_max_resources[resource_type] == 0.0:
                per_trial_resource = 0.0
            else:
                per_trial_resource = float(
                    max(
                        1,
                        (cluster_max_resources[resource_type] // self.config["tune"]["tune_params"]["num_samples"]),
                    ),
                )

        return per_trial_resource


class TuneModel(Trainable):
    """Trainable model class for Ray Tune."""

    def setup(self, config: dict[Any, Any]) -> None:
        """Get the model, loss function(s), optimizer, train and test data from the config."""
        # set the seeds the second time, first in TuneWrapper initialization. This will make all important seed worker specific.
        set_general_seeds(self.config["ray_worker_seed"])

        # Initialize model with the config params
        self.model = config["model"](**config["model_params"])

        # Add data path
        self.data_path = config["data_path"]

        # Get the loss function(s) from the config model params
        # Note that the loss function(s) are stored in a dictionary,
        # where the keys are the key of loss_params in the yaml config file and the values are the loss functions associated to such keys.
        self.loss_dict = config["loss_params"]
        for key, loss_fn in self.loss_dict.items():
            try:
                self.loss_dict[key] = getattr(nn, loss_fn)()
            except AttributeError as err:
                raise ValueError(
                    f"Invalid loss function: {loss_fn}, check PyTorch for documentation on available loss functions",
                ) from err

        # get the optimizer parameters
        optimizer_lr = config["optimizer_params"]["lr"]

        # get the optimizer from PyTorch
        self.optimizer = getattr(optim, config["optimizer_params"]["method"])(self.model.parameters(), lr=optimizer_lr)

        # get step size from the config
        self.step_size = config["tune"]["step_size"]

        # use dataloader on training/validation data
        self.batch_size = config["data_params"]["batch_size"]
        training: Dataset = config["training"]
        validation: Dataset = config["validation"]
        self.training = DataLoader(
            training,
            batch_size=self.batch_size,
            shuffle=True,
        )  # TODO need to check the reproducibility of this shuffling
        self.validation = DataLoader(validation, batch_size=self.batch_size, shuffle=True)

        # debug section, first create a dedicated directory for each worker inside Ray_results/<tune_model_run_specific_dir> location
        debug_dir = os.path.join(
            config["tune_run_path"],
            "debug",
            ("worker_with_seed_" + str(self.config["ray_worker_seed"])),
        )
        if config["_debug"]:
            # creating a special directory for it one that is worker/trial/experiment specific
            os.makedirs(debug_dir)
            seed_filename = os.path.join(debug_dir, "seeds.txt")

            # save the initialized model weights
            self.export_model(export_dir=debug_dir)

            # save the seeds
            with open(seed_filename, "a") as seed_f:
                # you can not retrieve the actual seed once it set, or the current seed neither for python, numpy nor torch. so we select five numbers randomly. If that is the first draw of numbers they are always the same.
                python_values = random.sample(range(100), 5)
                numpy_values = list(np.random.randint(0, 100, size=5))
                torch_values = torch.randint(0, 100, (5,)).tolist()
                seed_f.write(
                    f"python drawn numbers : {python_values}\nnumpy drawn numbers : {numpy_values}\ntorch drawn numbers : {torch_values}\n",
                )

    def step(self) -> dict:
        """For each batch in the training data, calculate the loss and update the model parameters.

        This calculation is performed based on the model's batch function.
        At the end, return the objective metric(s) for the tuning process.
        """
        for _step_size in range(self.step_size):
            for x, y, _meta in self.training:
                # the loss dict could be unpacked with ** and the function declaration handle it differently like **kwargs. to be decided, personally find this more clean and understable.
                self.model.batch(x=x, y=y, optimizer=self.optimizer, **self.loss_dict)
        return self.objective()

    def objective(self) -> dict[str, float]:
        """Compute the objective metric(s) for the tuning process."""
        metrics = [
            "loss",
            "rocauc",
            "prauc",
            "mcc",
            "f1score",
            "precision",
            "recall",
            "spearmanr",
        ]  # TODO maybe we report only a subset of metrics, given certain criteria (eg. if classification or regression)
        predict_val = PredictWrapper(self.model, self.validation, loss_dict=self.loss_dict)
        predict_train = PredictWrapper(self.model, self.training, loss_dict=self.loss_dict)
        return {
            **{"val_" + metric: value for metric, value in predict_val.compute_metrics(metrics).items()},
            **{"train_" + metric: value for metric, value in predict_train.compute_metrics(metrics).items()},
        }

    def export_model(self, export_dir: str | None = None) -> None:  # type: ignore[override]
        """Export model to safetensors format."""
        if export_dir is None:
            return
        safe_save_model(self.model, os.path.join(export_dir, "model.safetensors"))

    def load_checkpoint(self, checkpoint: dict[Any, Any] | None) -> None:
        """Load model and optimizer state from checkpoint."""
        if checkpoint is None:
            return
        checkpoint_dir = checkpoint["checkpoint_dir"]
        self.model = safe_load_model(self.model, os.path.join(checkpoint_dir, "model.safetensors"))
        self.optimizer.load_state_dict(torch.load(os.path.join(checkpoint_dir, "optimizer.pt")))

    def save_checkpoint(self, checkpoint_dir: str) -> dict[Any, Any]:
        """Save model and optimizer state to checkpoint."""
        safe_save_model(self.model, os.path.join(checkpoint_dir, "model.safetensors"))
        torch.save(self.optimizer.state_dict(), os.path.join(checkpoint_dir, "optimizer.pt"))
        return {"checkpoint_dir": checkpoint_dir}
