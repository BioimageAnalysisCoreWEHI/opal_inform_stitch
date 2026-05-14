from aicsimageio import AICSImage
import os
import numpy as np
#from pyclesperanto_prototype import imshow
#import pyclesperanto_prototype as cle
import dask.array as da
import numpy as np
from matplotlib import pyplot as plt
import re
from tifffile import TiffWriter
import tifffile
from skimage.transform import resize

from xml.etree import ElementTree as ET
import argparse


def main():
    parser = argparse.ArgumentParser(
        description="Stitch a folder of inform unmixed stuff."
    )
    parser.add_argument('fpath', help="Path to folder of images")
    args = parser.parse_args()


    fpath = args.fpath
    outDir = '/vast/scratch/users/mckay.m/stitches/'
    
    label_prefix = str.split(fpath,'/')[-2]
    
    
    print(fpath)

    flist = os.listdir(fpath)

    
    all_flist = os.listdir(fpath)
    flist = [f for f in all_flist if 'component_data' in f]
    print(f'There are {len(flist)} tiles',flush=True)
    tif_filepaths = flist
    tif_filepaths = get_tif_files(fpath)

    reg0 = r"(.*)_\[([0-9]+),([0-9]+)\]_component_data\.tif"
    
    m = re.match(reg0,os.path.split(tif_filepaths[5])[-1])
    print(m.group(1)) #image label
    label = m.group(1)
    print(f'Slide label is {label}',flush=True)

    temp = np.zeros(500)
    pixelScale = 0.4962808
        
    
    cpt = 0
    imBoxes = []

    for idx,f in enumerate(tif_filepaths):
        #Find X Values list
        m = re.match(reg0,os.path.split(f)[-1])
        #print(os.path.split(f)[-1])
        if m:     
            xVal = int(int(m.group(2))/pixelScale)
            yVal = int(int(m.group(3))/pixelScale)
        else:
            sfahuias
        
        #Parse region
        img_path = os.path.join(fpath,f)
        img = AICSImage(img_path)   
        z,c,t,x,y = img.shape
        imBoxes.append([xVal,yVal,xVal+x,yVal+y])

        if (idx==0):
            #If first image, open using tiffffile to read channel names
            imgData = tifffile.TiffFile(img_path)
            imgData_s0 = imgData.series[0]
            names = [(ET.fromstring(page.description).find('Name').text) for page in imgData_s0]
            colors = [(ET.fromstring(page.description).find('Color').text) for page in imgData_s0]
        
        

    new_colors = []
    for cl in colors:
        cl = str.split(cl,',')
        a = 1
        r = int(cl[0])
        g = int(cl[1])
        b = int(cl[2])
        RGBint = int.from_bytes([r,g,b,a],byteorder="big", signed=True)   
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
    stitched_image = da.zeros((1,int(c),1,full_height,full_width))
    stitched_image = stitched_image.rechunk((1,int(c),1,
                                            int(full_height/10),
                                            int(full_width/10)))
    print(stitched_image.shape)
    stitched_image = stitched_image.rechunk(block_size_limit=1e7)

    
    report = []

    boxes_once_placed = []
    image_in_box = []

    thisImage = sorted(tif_filepaths)
    for idx,f in enumerate(thisImage):
        impath = os.path.join(fpath,f)
        
        m = re.match(reg0,os.path.split(f)[-1])
        
        if m:
            xVal = round(int(m.group(2))/pixelScale)
            yVal = round(int(m.group(3))/pixelScale)
        else:
            asfhujkasfhaskkhlfaj
                
        #Parse region
        img_path = os.path.join(fpath,f)
        img = AICSImage(img_path)
        z,c,t,h,w = img.shape

        im_data = img.get_image_data()    
        im_data = np.swapaxes(im_data,3,4)
            
        xStart = xVal - im_xmin 
        yStart = yVal - im_ymin

        xStart, yStart = adjust_position(xStart, yStart, boxes_once_placed)

        xEnd = xStart + w
        yEnd = yStart + h  
        
        report.append([f,xStart,yStart])
        xc, yc = xStart + w/2, yStart + w/2  

        boxes_once_placed.append([xStart,yStart,xEnd,yEnd])
        image_in_box.append(f)

        stitched_image[:,:,:,xStart:xEnd,yStart:yEnd] = im_data
        roiShape = stitched_image[:,:,:,xStart:xEnd,yStart:yEnd].shape

        stitched_image[:,:,:,xStart:xEnd,yStart:yEnd] = im_data[:,:,:,0:roiShape[3],0:roiShape[4]]
        
    print("DONE")

    full_image = stitched_image

    print(im_xmin)
    print(im_ymin)

    im_to_write = stitched_image.compute()  # materialize before resize

    subFig1 = resize(im_to_write, (
        im_to_write.shape[0],
        im_to_write.shape[1],
        im_to_write.shape[2],
        im_to_write.shape[3] // 4,  # integer division
        im_to_write.shape[4] // 4
    ))

    subFig2 = resize(subFig1, (
        subFig1.shape[0],
        subFig1.shape[1],
        subFig1.shape[2],
        subFig1.shape[3] // 4,
        subFig1.shape[4] // 4
    ))

    outPath = f'/vast/scratch/users/mckay.m/stitches/{label_prefix}_{label}.ome.tif'
    os.makedirs(os.path.dirname(outPath), exist_ok=True)  # Add this line
    with TiffWriter(outPath, bigtiff=True) as tif:
        
        options = dict(tile=(512, 512),compression='zlib',
                       metadata={'axes': 'TCZYX',
                                 'PhysicalSizeX':pixelScale,
                                 'PhysicalSizeY':pixelScale,
                                 'Channel':{'Name':names,'Color':new_colors}                          
                                }                               
                      )

        print('writing file %s' % outPath,flush=True)
        tif.write(im_to_write, subifds=2, **options)
        # save pyramid levels to the two subifds
        print("Pyramid resolution 1",flush=True)
        tif.write(subFig1, subfiletype=1, **options)
        print("Pyramid resolution 2",flush=True)
        tif.write(subFig2, subfiletype=1, **options)
    

    




def get_tif_files(directory):
    tif_files = []

    for dirpath, dirnames, filenames in os.walk(directory):
        reg0 = r"(.*)_\[([0-9]+),([0-9]+)\]_component_data\.tif"
        for filename in [f for f in filenames if f.endswith(".tif") and re.match(reg0,f)]:
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
        for j in range(i+1, len(boxes)):
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