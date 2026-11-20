#!/usr/bin/env python3
"""
fix_ome_tiff.py
---------------
Rewrites OME-TIFF files with corrected channel names and pyramid levels.
Reads all *.ome.tif files from a directory supplied on the command line and
writes corrected copies into a _fixed/ subdirectory of that directory.

Usage:
    python fix_ome_tiff.py /path/to/image_dir [--dry-run]
    python fix_ome_tiff.py /path/to/image_dir --file /path/to/single.ome.tif
"""

import argparse
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import tifffile
from tifffile import TiffWriter

# ---------------------------------------------------------------------------
# Per-project configuration — edit here if channel names differ across runs
# ---------------------------------------------------------------------------

GLOB_PATTERN = "*.ome.tif"

CHANNEL_MAPPING = {
    "Opal 480": "CCL19",
    "Opal 520": "MS4A1",
    "Opal 570": "CXCL12",
    "Opal 620": "PDGFRA",
    "Opal 690": "PLA2G2A",
    "Opal 780": "CK19"
}

# Override channel names in output order (set to None to derive from file + mapping)
DESIRED_NAMES = None

WRITE_PYRAMIDS = True
N_PYRAMID_LEVELS = 4
CONVERT_TO_FLOAT32 = True  # float64 -> float32 for QuPath compatibility

# ---------------------------------------------------------------------------


def parse_axes(series):
    """
    Return (n_channels, height, width, c_axis_index) from a tifffile series,
    using the axes string so we are robust to any dimension ordering.

    tifffile may report axes such as:
      'CYX'   — the normal case
      'YXC'   — channels-last (interleaved)
      'CZYX'  — with a Z dimension
      'QYX'   — malformed / unexpected first axis used as channel surrogate
      'IYX'   — series of pages read as I (image) axis

    We look for C first; if absent we treat the first non-spatial axis as C.
    Returns None for n_channels when the image is genuinely single-channel.
    """
    axes = series.axes          # e.g. 'CYX'
    shape = series.shape        # matching tuple

    def idx(letter):
        return axes.index(letter) if letter in axes else None

    y_i = idx('Y')
    x_i = idx('X')

    if y_i is None or x_i is None:
        raise ValueError(
            f"Cannot identify spatial axes in series with axes='{axes}' shape={shape}. "
            "Expected at least Y and X axes."
        )

    height = shape[y_i]
    width  = shape[x_i]

    # Identify channel axis
    c_i = idx('C')

    if c_i is None:
        # No explicit C axis — any remaining axis is treated as channels
        spatial = {y_i, x_i}
        other = [i for i in range(len(axes)) if i not in spatial]
        if other:
            c_i = other[0]
        # else: genuinely 2-D single-channel image

    n_channels = shape[c_i] if c_i is not None else 1

    return n_channels, height, width, c_i


def build_ome_xml(width, height, n_channels, dtype, ch_names):
    """Build a minimal OME-XML string for a CYX image."""
    dtype_map = {
        "uint8": "uint8", "uint16": "uint16", "int16": "int16",
        "uint32": "uint32", "int32": "int32",
        "float32": "float", "float64": "double",
    }
    pixel_type = dtype_map.get(str(dtype), "float")

    channels = "".join(
        f'<Channel ID="Channel:0:{i}" Name="{name}" SamplesPerPixel="1"/>'
        for i, name in enumerate(ch_names)
    )
    tiffdata = "".join(
        f'<TiffData FirstC="{i}" FirstT="0" FirstZ="0" IFD="{i}" PlaneCount="1"/>'
        for i in range(n_channels)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://www.openmicroscopy.org/Schemas/OME/2016-06 '
        'http://www.openmicroscopy.org/Schemas/OME/2016-06/ome.xsd">'
        '<Image ID="Image:0">'
        f'<Pixels DimensionOrder="XYCZT" ID="Pixels:0" Type="{pixel_type}" '
        f'SizeX="{width}" SizeY="{height}" SizeC="{n_channels}" SizeT="1" SizeZ="1" '
        f'BigEndian="false" Interleaved="false">'
        f'{channels}{tiffdata}'
        '</Pixels></Image></OME>'
    )


def read_channel(series, c_i, c, out_dtype, src_dtype):
    """
    Extract a single 2-D plane for channel index c from a series.

    Handles two layouts:
      - one page per channel  → series.levels[0].pages[c]
      - channels in a non-page axis (e.g. interleaved YXC) → asarray()[..., c]
    """
    level0 = series.levels[0]

    # Fast path: one IFD page per channel (most common for CYX OME-TIFFs)
    if len(level0.pages) >= (c + 1):
        data = level0.pages[c].asarray()
        # If the page itself is 3-D (e.g. it holds all channels), fall through
        if data.ndim == 2:
            if out_dtype != src_dtype:
                data = data.astype(out_dtype)
            return data

    # Fallback: load the full volume and index into the channel axis
    volume = level0.asarray()   # shape matches series.shape / series.axes
    axes = series.axes

    if c_i is not None and c_i < volume.ndim:
        data = np.take(volume, c, axis=c_i)
    else:
        # Single-channel image
        data = volume.squeeze()

    if data.ndim != 2:
        raise ValueError(
            f"Expected a 2-D plane for channel {c} but got shape {data.shape}. "
            f"Series axes='{axes}', shape={series.shape}."
        )

    if out_dtype != src_dtype:
        data = data.astype(out_dtype)
    return data


def rewrite_ome_tiff(
    src_path,
    dst_path,
    channel_mapping,
    channel_names_override=None,
    write_pyramids=True,
    n_levels=4,
    convert_to_float32=True,
    dry_run=False,
):
    """
    Rewrite a single OME-TIFF with corrected channel names and pyramids.
    Processes one channel at a time to keep memory usage low.
    """
    with tifffile.TiffFile(src_path) as tif:
        series0 = tif.series[0]
        shape    = series0.shape
        axes     = series0.axes
        src_dtype = series0.dtype

        # ── Robust dimension parsing ──────────────────────────────────────
        try:
            n_channels, height, width, c_i = parse_axes(series0)
        except ValueError as exc:
            raise RuntimeError(
                f"Could not parse image dimensions for {src_path.name}:\n  {exc}"
            ) from exc

        print(f"  axes={axes!r}  raw shape={shape}")
        print(f"  Parsed → channels={n_channels}  width={width}  height={height}")

        # Sanity check: warn loudly if dimensions look suspicious
        if n_channels > 100:
            print(
                f"  [WARNING] {n_channels} channels detected — this is almost certainly "
                "a mis-parsed dimension order.  Check that the file is a valid OME-TIFF "
                "and that tifffile can read its series correctly."
            )
        if width < 64 or height < 64:
            print(
                f"  [WARNING] Spatial dimensions look very small ({width}×{height}px). "
                "The axes may be transposed."
            )

        # ── Channel names ─────────────────────────────────────────────────
        if channel_names_override and len(channel_names_override) == n_channels:
            ch_names = list(channel_names_override)
        else:
            ch_names = []
            ome_xml = tif.ome_metadata
            if ome_xml:
                root = ET.fromstring(ome_xml)
                ns = ""
                if "}" in root.tag:
                    ns = root.tag.split("}")[0] + "}"
                ch_names = [
                    ch.get("Name", f"Channel {i+1}")
                    for i, ch in enumerate(root.iter(f"{ns}Channel"))
                ]
            if len(ch_names) != n_channels:
                ch_names = [f"Channel {i+1}" for i in range(n_channels)]
            ch_names = [channel_mapping.get(n, n) for n in ch_names]

        out_dtype = np.float32 if (convert_to_float32 and src_dtype == np.float64) else src_dtype

        print(f"  dtype: {src_dtype} -> {out_dtype}")
        print(f"  Channel names: {ch_names}")

        if dry_run:
            print("  [DRY RUN] Skipping write.")
            return ch_names

        ome_description = build_ome_xml(width, height, n_channels, out_dtype, ch_names)

        with TiffWriter(dst_path, bigtiff=True) as tw:
            for c in range(n_channels):
                print(f"    [{c+1}/{n_channels}] {ch_names[c]} ... ", end="", flush=True)

                data = read_channel(series0, c_i, c, out_dtype, src_dtype)

                tw.write(
                    data,
                    tile=(512, 512),
                    compression="deflate",
                    description=ome_description if c == 0 else None,
                    subifds=n_levels if write_pyramids else None,
                    software="tifffile.py",
                )

                if write_pyramids:
                    level_data = data
                    for _ in range(n_levels):
                        h, w = level_data.shape
                        h2, w2 = h // 2, w // 2
                        level_data = (
                            level_data[: h2 * 2, : w2 * 2]
                            .reshape(h2, 2, w2, 2)
                            .mean(axis=(1, 3))
                            .astype(out_dtype)
                        )
                        tw.write(level_data, tile=(512, 512), compression="deflate", subfiletype=1)

                del data
                print("done")

    return ch_names


def main():
    parser = argparse.ArgumentParser(description="Fix OME-TIFF channel names and pyramids.")
    parser.add_argument("image_dir", type=Path, help="Directory containing *.ome.tif files")
    parser.add_argument("--dry-run", action="store_true", help="Preview only — no files are written")
    parser.add_argument("--file", type=Path, default=None, help="Process a single file only (used by SLURM array jobs)")
    args = parser.parse_args()

    image_dir: Path = args.image_dir.resolve()
    dry_run: bool = args.dry_run

    if not image_dir.is_dir():
        raise SystemExit(f"ERROR: '{image_dir}' is not a directory or does not exist.")

    output_dir = image_dir / "_fixed"
    if not dry_run:
        output_dir.mkdir(exist_ok=True)

    # Single-file mode (used by SLURM array jobs) vs full directory mode
    if args.file:
        tiff_files = [args.file.resolve()]
    else:
        tiff_files = sorted(image_dir.glob(GLOB_PATTERN))

    print(f"\nDirectory : {image_dir}")
    print(f"Output    : {output_dir}")
    print(f"Files     : {len(tiff_files)}")
    if not tiff_files:
        print("No files matched — exiting.")
        return

    for f in tiff_files:
        print(f"  {f.name}")

    print()
    total_start = time.time()

    for i, tiff_path in enumerate(tiff_files):
        dst = output_dir / tiff_path.name
        if not dry_run and dst.exists():
            print(f"[SKIP] {tiff_path.name} — already exists in _fixed/")
            continue

        print(f"[{i+1}/{len(tiff_files)}] {tiff_path.name}")
        t0 = time.time()
        try:
            rewrite_ome_tiff(
                tiff_path,
                dst,
                CHANNEL_MAPPING,
                channel_names_override=DESIRED_NAMES,
                write_pyramids=WRITE_PYRAMIDS,
                n_levels=N_PYRAMID_LEVELS,
                convert_to_float32=CONVERT_TO_FLOAT32,
                dry_run=dry_run,
            )
            elapsed = time.time() - t0
            print(f"  -> {dst.name}  ({elapsed:.0f}s)\n")
        except Exception as e:
            import traceback
            print(f"  [ERROR] {e}")
            traceback.print_exc()
            if not dry_run and dst.exists():
                dst.unlink()
            print()

    total_elapsed = time.time() - total_start
    print(f"\nFinished in {total_elapsed / 60:.1f} min.")
    if not dry_run:
        print(f"Fixed files are in: {output_dir}")
        print("Add images from _fixed/ to a NEW QuPath project.")


if __name__ == "__main__":
    main()
