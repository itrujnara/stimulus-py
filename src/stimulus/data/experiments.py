"""Loaders serve as interfaces between the CSV master class and custom methods.

Mainly, three types of custom methods are supported:
- Encoders: methods for encoding data before it is fed into the model
- Data transformers: methods for transforming data (i.e. augmenting, noising...)
- Splitters: methods for splitting data into train, validation and test sets

Loaders are built from an input config YAML file which format is described in the documentation, you can find an example here: tests/test_data/dna_experiment/dna_experiment_config_template.yaml
"""

import inspect
from collections import defaultdict
from typing import Any

from stimulus.data.encoding import encoders as encoders
from stimulus.data.splitters import splitters as splitters
from stimulus.data.transform import data_transformation_generators as data_transformation_generators
from stimulus.utils import yaml_data


class EncoderLoader:
    """Class for loading encoders from a config file."""

    def __init__(self, seed: float = None) -> None:
        self.seed = seed

    def initialize_column_encoders_from_config(self, column_config: yaml_data.YamlColumns) -> None:
        """Build the loader from a config dictionary.

        Args:
            config (yaml_data.YamlSubConfigDict): Configuration dictionary containing field names (column_name) and their encoder specifications.
        """
        for field in column_config:
            encoder = self.get_encoder(field.encoder[0].name, field.encoder[0].params)
            self.set_encoder_as_attribute(field.column_name, encoder)

    def get_function_encode_all(self, field_name: str) -> Any:
        """Gets the encoding function for a specific field.

        Args:
            field_name (str): The field name to get the encoder for

        Returns:
            Any: The encode_all function for the specified field
        """
        return getattr(self, field_name).encode_all

    def get_encoder(self, encoder_name: str, encoder_params: dict = None) -> Any:
        """Gets an encoder object from the encoders module and initializes it with the given parametersß.

        Args:
            encoder_name (str): The name of the encoder to get
            encoder_params (dict): The parameters for the encoder

        Returns:
            Any: The encoder function for the specified field and parameters
        """
        try:
            return getattr(encoders, encoder_name)(**encoder_params)
        except AttributeError:
            print(f"Encoder '{encoder_name}' not found in the encoders module.")
            print(
                f"Available encoders: {[name for name, obj in encoders.__dict__.items() if isinstance(obj, type) and name not in ('ABC', 'Any')]}"
            )
            raise

        except TypeError:
            if encoder_params is None:
                return getattr(encoders, encoder_name)()
            print(f"Encoder '{encoder_name}' has incorrect parameters: {encoder_params}")
            print(f"Expected parameters for '{encoder_name}': {inspect.signature(getattr(encoders, encoder_name))}")
            raise

    def set_encoder_as_attribute(self, field_name: str, encoder: encoders.AbstractEncoder) -> None:
        """Sets the encoder as an attribute of the loader.

        Args:
            field_name (str): The name of the field to set the encoder for
            encoder (encoders.AbstractEncoder): The encoder to set
        """
        setattr(self, field_name, encoder)


class TransformLoader:
    """Class for loading transformations from a config file."""

    def __init__(self, seed: float = None) -> None:
        self.seed = seed

    def get_data_transformer(self, transformation_name: str, transformation_params: dict = None) -> Any:
        """Gets a transformer object from the transformers module.

        Args:
            transformation_name (str): The name of the transformer to get

        Returns:
            Any: The transformer function for the specified transformation
        """
        try:
            return getattr(data_transformation_generators, transformation_name)(**transformation_params)
        except AttributeError:
            print(f"Transformer '{transformation_name}' not found in the transformers module.")
            print(
                f"Available transformers: {[name for name, obj in data_transformation_generators.__dict__.items() if isinstance(obj, type) and name not in ('ABC', 'Any')]}"
            )
            raise

        except TypeError:
            if transformation_params is None:
                return getattr(data_transformation_generators, transformation_name)()
            print(f"Transformer '{transformation_name}' has incorrect parameters: {transformation_params}")
            print(
                f"Expected parameters for '{transformation_name}': {inspect.signature(getattr(data_transformation_generators, transformation_name))}"
            )
            raise

    def set_data_transformer_as_attribute(self, field_name: str, data_transformer: Any) -> None:
        """Sets the data transformer as an attribute of the loader.

        Args:
            field_name (str): The name of the field to set the data transformer for
            data_transformer (Any): The data transformer to set
        """
        # check if the field already exists, if it does not, initialize it to an empty dict
        if not hasattr(self, field_name):
            setattr(self, field_name, {data_transformer.__class__.__name__: data_transformer})
        else:
            self.field_name[data_transformer.__class__.__name__] = data_transformer

    def initialize_column_data_transformers_from_config(self, transform_config: yaml_data.YamlTransform) -> None:
        """Build the loader from a config dictionary.

        Args:
            config (yaml_data.YamlSubConfigDict): Configuration dictionary containing transforms configurations.

        Example:
            Given a YAML config like:
            ```yaml
            transforms:
              transformation_name: noise
              columns:
                - column_name: age
                  transformations:
                    - name: GaussianNoise
                      params:
                        std: 0.1
                - column_name: fare
                  transformations:
                    - name: GaussianNoise
                      params:
                        std: 0.1
            ```

            The loader will:
            1. Iterate through each column (age, fare)
            2. For each transformation in the column:
               - Get the transformer (GaussianNoise) with its params (std=0.1)
               - Set it as an attribute on the loader using the column name as key
        """
        for column in transform_config.columns:
            col_name = column.column_name
            for transform_spec in column.transformations:
                transformer = self.get_data_transformer(transform_spec.name, transform_spec.params)
                self.set_data_transformer_as_attribute(col_name, transformer)


class SplitLoader:
    """Class for loading splitters from a config file."""

    def __init__(self, seed: float = None) -> None:
        self.seed = seed

    def get_function_split(self) -> Any:
        """Gets the function for splitting the data.

        Args:
            split_method (str): Name of the split method to use

        Returns:
            Any: The split function for the specified method

        Raises:
            AttributeError: If splitter hasn't been initialized using initialize_splitter_from_config()
        """
        if not hasattr(self, "split"):
            # Raise a more specific error and chain it to the original AttributeError
            try:
                self.split
            except AttributeError as e:
                raise AttributeError(
                    "Splitter not initialized. Please call initialize_splitter_from_config() or set_splitter_as_attribute() "
                    "before attempting to get split function.",
                ) from e
        return self.split.get_split_indexes

    def get_splitter(self, splitter_name: str, splitter_params: dict = None) -> Any:
        """Gets a splitter object from the splitters module.

        Args:
            splitter_name (str): The name of the splitter to get

        Returns:
            Any: The splitter function for the specified splitter
        """
        try:
            return getattr(splitters, splitter_name)(**splitter_params)
        except TypeError:
            if splitter_params is None:
                return getattr(splitters, splitter_name)()
            print(f"Splitter '{splitter_name}' has incorrect parameters: {splitter_params}")
            print(f"Expected parameters for '{splitter_name}': {inspect.signature(getattr(splitters, splitter_name))}")
            raise

    def set_splitter_as_attribute(self, splitter: Any) -> None:
        """Sets the splitter as an attribute of the loader.

        Args:
            field_name (str): The name of the field to set the splitter for
            splitter (Any): The splitter to set
        """
        self.split = splitter

    def initialize_splitter_from_config(self, split_config: yaml_data.YamlSplit) -> None:
        """Build the loader from a config dictionary.

        Args:
            config (dict): Configuration dictionary containing split configurations.
        """
        splitter = self.get_splitter(split_config.split_method, split_config.params)
        self.set_splitter_as_attribute(splitter)
