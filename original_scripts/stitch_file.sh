#!/bin/bash
#SBATCH --job-name=stitching
#SBATCH --time=36:00:00
#SBATCH --output=stitching_%j.log
#SBATCH --error=stitching_%j.err
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=12
#SBATCH --mem=960G
#SBATCH --mail-type=END
#SBATCH --mail-user=mckay.m@wehi.edu.au
#SBATCH --partition=regular


module load miniconda3
conda activate /vast/projects/BAC_shared/conda_envs/yolo_env

dir=$1
export TMPDIR=/vast/scratch/users/$USER/temp
mkdir -p $TMPDIR
python inform_stitch.py "$dir"
