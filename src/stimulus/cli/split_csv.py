#!/usr/bin/env python3
"""CLI module for splitting CSV data files."""

import argparse
from typing import Optional

from stimulus.data.csv import DatasetProcessor, SplitManager
from stimulus.data.experiments import SplitLoader


def get_args() -> argparse.Namespace:
    """Get the arguments when using from the commandline."""
    parser = argparse.ArgumentParser(description="Split a CSV data file.")
    parser.add_argument(
        "-c",
        "--csv",
        type=str,
        required=True,
        metavar="FILE",
        help="The file path for the csv containing all data",
    )
    parser.add_argument(
        "-y",
        "--yaml",
        type=str,
        required=True,
        metavar="FILE",
        help="The YAML config file that hold all parameter info",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        required=True,
        metavar="FILE",
        help="The output file path to write the noised csv",
    )
    parser.add_argument(
        "-f",
        "--force",
        type=bool,
        required=False,
        default=False,
        help="Overwrite the split column if it already exists in the csv",
    )
    parser.add_argument(
        "-s",
        "--seed",
        type=int,
        required=False,
        default=None,
        help="Seed for the random number generator",
    )

    return parser.parse_args()


def main(data_csv: str, config_yaml: str, out_path: str, *, force: bool = False, seed: Optional[int] = None) -> None:
    """Connect CSV and YAML configuration and handle sanity checks.

    Args:
        data_csv: Path to input CSV file.
        config_json: Path to config YAML file.
        out_path: Path to output split CSV.
        force: Overwrite the split column if it already exists in the CSV.
    """
    # create a DatasetProcessor object from the config and the csv
    processor = DatasetProcessor(config_path=config_yaml, csv_path=data_csv)

    # create a split manager from the config
    split_config = processor.dataset_manager.config.split
    split_loader = SplitLoader(seed=seed)
    split_loader.initialize_splitter_from_config(split_config)
    split_manager = SplitManager(split_loader)

    # apply the split method to the data
    processor.add_split(split_manager=split_manager, force=force)

    # save the modified csv
    processor.save(out_path)


def run() -> None:
    """Run the CSV splitting script."""
    args = get_args()
    main(args.csv, args.json, args.output, force=args.force, seed=args.seed)


if __name__ == "__main__":
    run()
