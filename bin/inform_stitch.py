from aicsimageio import AICSImage
import os
import numpy as np
import dask.array as da
from matplotlib import pyplot as plt
import re
from tifffile import TiffWriter
import tifffile
from skimage.transform import resize
from skimage.measure import label, regionprops
from skimage.morphology import closing, square

from xml.etree import ElementTree as ET
import argparse


def main():
    parser = argparse.ArgumentParser(
        description="Stitch a folder of inform unmixed stuff."
    )
    parser.add_argument('fpath', help="Path to folder of images")
    parser.add_argument('--outdir', default='.', help="Output directory for stitched OME-TIFF (default: current directory)")
    parser.add_argument('--roi_finder', action='store_true',
                        help="Detect individual tissue regions and write one OME-TIFF per ROI instead of a single stitched image")
    parser.add_argument('--roi_scale', type=int, default=8,
                        help="Downscale factor for the occupancy map used in ROI detection (default: 8)")
    args = parser.parse_args()

    fpath = args.fpath.rstrip('/')
    outDir = args.outdir

    label_prefix = os.path.basename(fpath)

    print(fpath)

    all_flist = os.listdir(fpath)
    flist = [f for f in all_flist if 'component_data' in f]
    print(f'There are {len(flist)} tiles', flush=True)
    tif_filepaths = get_tif_files(fpath)

    reg0 = r"(.*)_\[([0-9]+),([0-9]+)\]_component_data\.tif"

    m = re.match(reg0, os.path.split(tif_filepaths[5])[-1])
    print(m.group(1))  # image label
    label = m.group(1)
    print(f'Slide label is {label}', flush=True)

    pixelScale = 0.4962808

    cpt = 0
    imBoxes = []

    for idx, f in enumerate(tif_filepaths):
        # Find X Values list
        m = re.match(reg0, os.path.split(f)[-1])
        if m:
            xVal = int(int(m.group(2)) / pixelScale)
            yVal = int(int(m.group(3)) / pixelScale)
        else:
            raise ValueError(f"Filename did not match expected pattern: {f}")

        # Parse region
        img_path = os.path.join(fpath, f)
        img = AICSImage(img_path)
        z, c, t, x, y = img.shape
        imBoxes.append([xVal, yVal, xVal + x, yVal + y])

        if idx == 0:
            # If first image, open using tifffile to read channel names
            imgData = tifffile.TiffFile(img_path)
            imgData_s0 = imgData.series[0]
            names = [(ET.fromstring(page.description).find('Name').text) for page in imgData_s0]
            colors = [(ET.fromstring(page.description).find('Color').text) for page in imgData_s0]

    new_colors = []
    for cl in colors:
        cl = str.split(cl, ',')
        a = 1
        r = int(cl[0])
        g = int(cl[1])
        b = int(cl[2])
        RGBint = int.from_bytes([r, g, b, a], byteorder="big", signed=True)
        new_colors.append(RGBint)

    print(new_colors)
    xvals = [x[0] for x in imBoxes]
    yvals = [x[1] for x in imBoxes]
    x_end_vals = [x[2] for x in imBoxes]
    y_end_vals = [x[3] for x in imBoxes]

    im_xmin = min(xvals)
    im_ymin = min(yvals)
    im_xmax = max(x_end_vals)
    im_ymax = max(y_end_vals)

    final_dimensions = (im_xmax - im_xmin, im_ymax - im_ymin)
    print(final_dimensions)
    full_height = final_dimensions[0] + 1000
    full_width = final_dimensions[1] + 1000
    stitched_image = da.zeros((1, int(c), 1, full_height, full_width))
    stitched_image = stitched_image.rechunk((1, int(c), 1,
                                             int(full_height / 10),
                                             int(full_width / 10)))
    print(stitched_image.shape)
    stitched_image = stitched_image.rechunk(block_size_limit=1e7)

    report = []
    boxes_once_placed = []
    image_in_box = []

    thisImage = sorted(tif_filepaths)
    for idx, f in enumerate(thisImage):
        impath = os.path.join(fpath, f)

        m = re.match(reg0, os.path.split(f)[-1])

        if m:
            xVal = round(int(m.group(2)) / pixelScale)
            yVal = round(int(m.group(3)) / pixelScale)
        else:
            raise ValueError(f"Filename did not match expected pattern: {f}")

        # Parse region
        img_path = os.path.join(fpath, f)
        img = AICSImage(img_path)
        z, c, t, h, w = img.shape

        im_data = img.get_image_data()
        im_data = np.swapaxes(im_data, 3, 4)

        xStart = xVal - im_xmin
        yStart = yVal - im_ymin

        xStart, yStart = adjust_position(xStart, yStart, boxes_once_placed)

        xEnd = xStart + w
        yEnd = yStart + h

        report.append([f, xStart, yStart])
        xc, yc = xStart + w / 2, yStart + w / 2

        boxes_once_placed.append([xStart, yStart, xEnd, yEnd])
        image_in_box.append(f)

        stitched_image[:, :, :, xStart:xEnd, yStart:yEnd] = im_data
        roiShape = stitched_image[:, :, :, xStart:xEnd, yStart:yEnd].shape

        stitched_image[:, :, :, xStart:xEnd, yStart:yEnd] = im_data[:, :, :, 0:roiShape[3], 0:roiShape[4]]

    print("DONE")

    print(im_xmin)
    print(im_ymin)

    full_image = stitched_image.compute()  # materialize the full stitched dask array

    tiff_options = dict(
        tile=(512, 512),
        compression='zlib',
        metadata={
            'axes': 'TCZYX',
            'PhysicalSizeX': pixelScale,
            'PhysicalSizeY': pixelScale,
            'Channel': {'Name': names, 'Color': new_colors}
        }
    )

    if args.roi_finder:
        crops = find_rois(full_image, scale_by=args.roi_scale)
        print(f'ROI finder detected {len(crops)} tissue region(s)', flush=True)
        for idx, crop in enumerate(crops):
            outPath = os.path.join(outDir, f'{label_prefix}_{label}_roi_{idx}.ome.tif')
            write_pyramid(crop, outPath, tiff_options)
    else:
        outPath = os.path.join(outDir, f'{label_prefix}_{label}.ome.tif')
        write_pyramid(full_image, outPath, tiff_options)


def find_rois(full_image, scale_by=8):
    """
    Detect spatially distinct tissue regions in a stitched image and return
    a list of cropped numpy arrays, one per region.

    Strategy:
      1. Build a binary occupancy map at 1/scale_by resolution.
      2. Morphological closing fills tiny gaps between adjacent tiles.
      3. Connected-component labelling identifies each tissue section.
      4. Each labelled region's bounding box is scaled back to full resolution
         and used to crop the full stitched image.
    """
    # Collapse to 2-D occupancy map using the first channel, first z/t
    # full_image shape: (1, C, 1, H, W)
    occupancy = full_image[0, 0, 0, :, :]  # (H, W)

    h, w = occupancy.shape
    small = np.zeros((h // scale_by, w // scale_by), dtype=np.uint8)

    # Mark every pixel that has any signal
    small_occ = (occupancy[::scale_by, ::scale_by] > 0).astype(np.uint8)
    small[:small_occ.shape[0], :small_occ.shape[1]] = small_occ

    closed = closing(small, square(3))
    labelled = label(closed)
    regions = regionprops(labelled)

    print(f'Occupancy map shape: {small.shape}, regions found: {len(regions)}', flush=True)

    crops = []
    for r in regions:
        # bbox is (min_row, min_col, max_row, max_col) i.e. (y0, x0, y1, x1)
        y0, x0, y1, x1 = r.bbox
        # Scale back to full resolution
        y0 = y0 * scale_by
        x0 = x0 * scale_by
        y1 = min(y1 * scale_by, full_image.shape[3])
        x1 = min(x1 * scale_by, full_image.shape[4])
        print(f'  ROI bbox (full res): y={y0}:{y1}, x={x0}:{x1}', flush=True)
        crops.append(full_image[:, :, :, y0:y1, x0:x1])

    return crops


def write_pyramid(im_to_write, outPath, tiff_options):
    """Write a numpy array as a 3-level pyramidal OME-TIFF."""
    subFig1 = resize(im_to_write, (
        im_to_write.shape[0],
        im_to_write.shape[1],
        im_to_write.shape[2],
        im_to_write.shape[3] // 4,
        im_to_write.shape[4] // 4
    ))
    subFig2 = resize(subFig1, (
        subFig1.shape[0],
        subFig1.shape[1],
        subFig1.shape[2],
        subFig1.shape[3] // 4,
        subFig1.shape[4] // 4
    ))

    os.makedirs(os.path.dirname(os.path.abspath(outPath)), exist_ok=True)
    print(f'Writing file {outPath}', flush=True)
    with TiffWriter(outPath, bigtiff=True) as tif:
        tif.write(im_to_write, subifds=2, **tiff_options)
        print('  Pyramid resolution 1', flush=True)
        tif.write(subFig1, subfiletype=1, **tiff_options)
        print('  Pyramid resolution 2', flush=True)
        tif.write(subFig2, subfiletype=1, **tiff_options)


def get_tif_files(directory):
    tif_files = []

    for dirpath, dirnames, filenames in os.walk(directory):
        reg0 = r"(.*)_\[([0-9]+),([0-9]+)\]_component_data\.tif"
        for filename in [f for f in filenames if f.endswith(".tif") and re.match(reg0, f)]:
            if not dirpath.endswith("images"):
                tif_files.append(os.path.join(dirpath, filename))
            else:
                pass

    return tif_files


def is_overlapping(A, B):
    return not (A[0] > B[2] or A[2] < B[0] or A[1] > B[3] or A[3] < B[1])


def find_overlaps(boxes):
    overlaps = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if is_overlapping(boxes[i], boxes[j]):
                overlaps.append((i, j))
    return overlaps


def adjust_position(xStart, yStart, boxes_once_placed, max_gap=1):
    for box in boxes_once_placed:
        # Check horizontal gap
        if abs(box[2] - xStart) <= max_gap:
            xStart = box[2]

        # Check vertical gap
        if abs(box[3] - yStart) <= max_gap:
            yStart = box[3]

    return xStart, yStart


if __name__ == "__main__":
    main()
