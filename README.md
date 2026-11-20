# opal_inform_stitch

Nextflow pipeline for stitching Opal/inForm images from Vectra Polaris in parallel.

Each subdirectory under `--base_dir` is processed as an independent SLURM job, allowing all slides to be stitched concurrently.

## Requirements

- [Nextflow](https://www.nextflow.io/) ≥ 24.04.2
- conda or mamba (for environment management)

## Input structure

```
base_dir/
    slide_A/
        SlideA_[x,y]_component_data.tif
        ...
    slide_B/
        SlideB_[x,y]_component_data.tif
        ...
```

Each subdirectory must contain `component_data` TIFF tiles exported from inForm.

## Usage

```bash
nextflow run main.nf \
    --base_dir /path/to/slides \
    --outdir /path/to/output \
    -profile conda,large
```

## Profiles

| Profile  | Memory per job | Target nodes        | Use case                   |
|----------|----------------|---------------------|----------------------------|
| `small`  | 96 GB          | sml (113 GB)        | Small slides / test runs   |
| `medium` | 240 GB         | med/il (491 GB)     | Medium slides              |
| `large`  | 960 GB         | lrg (1498 GB)       | Full-size Vectra Polaris   |

Combine with a container/environment profile (`conda`, `mamba`, `singularity`, `apptainer`):

```bash
-profile conda,large
```

## Container (Apptainer)

`containers/opal_inform_stitch.def` builds an Apptainer image with the Python environment of the stitching and
channel-renaming scripts (Python 3.11.18, aicsimageio 4.14.0, tifffile 2022.4.8, numpy 1.26.4, dask 2024.11.2,
scikit-image 0.20.0; full package list in `containers/environment.lock.txt`). The image also contains the scripts, in
`/opt/opal_inform_stitch/bin/` and `/opt/opal_inform_stitch/original_scripts/`.

Build (no root needed on most HPC systems), from the repository root:

```bash
apptainer build --fakeroot opal_inform_stitch.sif containers/opal_inform_stitch.def
```

Run the pipeline in the image with `-profile apptainer` (or `singularity`) and `--container`:

```bash
nextflow run main.nf \
    -profile apptainer,large \
    --container /path/to/opal_inform_stitch.sif \
    --base_dir /path/to/slides \
    --outdir /path/to/output
```

Test (2026-11-20): one slide of 511 inForm component tiles (8 channels) was stitched in the image with
`original_scripts/inform_stitch.py` and with the pipeline (`bin/inform_stitch.py`, `-profile apptainer`). The two
stitched images (44,717 × 39,617 pixels, 3 pyramid levels) are pixel-identical. `original_scripts/fix_ome_tiff.py`
was then run on the stitched image in the image.

## Scripts as run (`original_scripts/`)

The pipeline (`bin/inform_stitch.py`) is adapted from the scripts in `original_scripts/`, which are the scripts used to
stitch and prepare the OPAL images:

| Script | What it does |
|--------|--------------|
| `inform_stitch.py` | Stitches the inForm component tiles of one slide: each tile is placed at its stage position (from the `[x,y]` in the file name, µm ÷ 0.4962808), without registration or blending, and later tiles overwrite earlier ones where they overlap. Each tile is transposed, so the stitched image has the scanner x axis along its rows. Writes a pyramidal OME-TIFF (zlib, 512 × 512 tiles) to a fixed output folder (`outDir`, edit before use) |
| `stitch_file.sh`, `batch_submit.sh` | Slurm submission of `inform_stitch.py`, one job per slide folder |
| `fix_ome_tiff.py` | Renames the Opal channels to their markers (`CHANNEL_MAPPING`), converts float64 to float32, and rewrites each image with 4 extra pyramid levels (deflate, 512 × 512 tiles) into `_fixed/`. The rewritten OME-XML has no pixel size. Run on whole folders, or one file with `--file` |
| `StitchHALO_wRoiFinder.ipynb` | Notebook version with tissue-region detection |

Run the original scripts in the image:

```bash
apptainer exec -B /path/to/data opal_inform_stitch.sif \
    python /opt/opal_inform_stitch/original_scripts/inform_stitch.py "/path/to/slides/<slide folder>/"
apptainer exec -B /path/to/data opal_inform_stitch.sif \
    python /opt/opal_inform_stitch/original_scripts/fix_ome_tiff.py /path/to/stitched --file /path/to/stitched/<image>.ome.tif
```

## Output

Stitched pyramidal OME-TIFF files are written to `--outdir`:

```
outdir/
    <sample>_<label>.ome.tif
    pipeline_info/
        execution_timeline_*.html
        execution_report_*.html
        execution_trace_*.txt
```

## Parameters

| Parameter           | Required | Default  | Description                                          |
|---------------------|----------|----------|------------------------------------------------------|
| `--base_dir`        | Yes      | —        | Directory containing one subdirectory per slide      |
| `--outdir`          | Yes      | —        | Output directory for stitched OME-TIFFs              |
| `--publish_dir_mode`| No       | `copy`   | Nextflow publishDir mode                             |
| `--roi_finder`      | No       | `false`  | Write one OME-TIFF per detected tissue region         |
| `--roi_scale`       | No       | `8`      | Downsample factor for tissue-region detection        |
| `--container`       | With `-profile apptainer`/`singularity` | — | Path to `opal_inform_stitch.sif` |

