#!/bin/bash


BASE_DIR=$1

# Iterate over each subdirectory
for dir in "$BASE_DIR"/*/; do
    # Ensure it's a directory
    if [ -d "$dir" ]; then
        echo "Processing directory: $dir"
        sbatch stitch_file.sh "$dir"
    fi
done