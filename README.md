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

