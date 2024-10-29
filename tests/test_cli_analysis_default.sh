#!bin/bash

# Test script for stimulus CLI applications

set -e  # Exit immediately if a command exits with a non-zero status

# Set up paths
TEST_DIR=$(pwd)
MODEL_LOC=$TEST_DIR/test_model/dnatofloat_model.py
WEIGHT_LOC=$TEST_DIR/test_output/test_with_split-shuffle-model.safetensors
METRICS_LOC=$TEST_DIR/test_output/test_with_split-shuffle-metrics.csv
EXPERIMENTAL_CONFIG_LOC=$TEST_DIR/test_output/test_with_split-shuffled-experiment.json
EXPERIMENTAL_MODEL_CONFIG_LOC=$TEST_DIR/test_output/test_with_split-shuffle-config.json
DATA_LOC=$TEST_DIR/test_output/test_with_split-shuffle.csv

stimulus-analysis-default -m $MODEL_LOC -w $WEIGHT_LOC -d $DATA_LOC -ec $EXPERIMENTAL_CONFIG_LOC -mc $EXPERIMENTAL_MODEL_CONFIG_LOC -me $METRICS_LOC -o .