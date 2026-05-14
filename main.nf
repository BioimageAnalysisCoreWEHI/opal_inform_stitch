nextflow.enable.dsl = 2

process STITCH_SAMPLE {
    tag "${sample_name}"
    label 'process_stitch'

    conda "${projectDir}/bin/environment.yml"

    publishDir "${params.outdir}", mode: params.publish_dir_mode

    input:
    tuple val(sample_name), val(sample_dir)

    output:
    path "*.ome.tif", emit: stitched

    script:
    """
    set -euo pipefail

    python "${projectDir}/bin/inform_stitch.py" \
        "${sample_dir}" \
        --outdir . \
        2>&1 | tee stitch_${sample_name}.log
    """
}

workflow {
    if (!params.base_dir) {
        error "Missing required parameter: --base_dir"
    }
    if (!params.outdir) {
        error "Missing required parameter: --outdir"
    }

    def baseDir = file(params.base_dir)
    if (!baseDir.exists() || !baseDir.isDirectory()) {
        error "base_dir does not exist or is not a directory: ${params.base_dir}"
    }

    // Discover all subdirectories under base_dir
    Channel
        .fromPath("${params.base_dir}/*/", type: 'dir')
        .ifEmpty { error "No subdirectories found in ${params.base_dir}" }
        .map { dir -> tuple(dir.name, dir.toString()) }
        .set { sample_dirs }

    STITCH_SAMPLE(sample_dirs)
}
