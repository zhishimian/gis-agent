"""Read-only output inventory in the real QGIS interpreter, no reference algorithms."""
import csv
import json
import sys
from pathlib import Path
import numpy as np
from osgeo import gdal, ogr
from PIL import Image

gdal.UseExceptions()
work = Path(sys.argv[1]).resolve()
rows=[]
for p in sorted((work/'output').rglob('*')):
    if not p.is_file() or 'python_logs' in p.parts or 'repairs' in p.parts or p.suffix.lower() not in {'.tif','.tiff','.gpkg','.geojson','.shp','.csv','.json','.npy','.png','.jpg'}:
        continue
    r={'path':p.relative_to(work).as_posix(),'bytes':p.stat().st_size}
    try:
        suffix=p.suffix.lower()
        if suffix in {'.tif','.tiff'}:
            ds=gdal.Open(str(p));band=ds.GetRasterBand(1)
            # Statistics from downsampled pixels are labeled as samples.
            a=band.ReadAsArray(buf_xsize=min(ds.RasterXSize,512),buf_ysize=min(ds.RasterYSize,512)).astype(float)
            nd=band.GetNoDataValue();valid=np.isfinite(a)
            if nd is not None:valid &= a!=nd
            vals=a[valid]
            r.update(type='raster',shape=[ds.RasterYSize,ds.RasterXSize],bands=ds.RasterCount,
                     transform=ds.GetGeoTransform(),crs=ds.GetProjection(),nodata=nd,
                     sample_valid=int(valid.sum()),sample_min=float(vals.min()) if vals.size else None,
                     sample_max=float(vals.max()) if vals.size else None,sample_mean=float(vals.mean()) if vals.size else None)
            ds=None
        elif suffix in {'.gpkg','.geojson','.shp'}:
            ds=ogr.Open(str(p),0)
            if ds is None:raise ValueError('OGR could not read vector')
            layers=[]
            for layer in ds:
                d=layer.GetLayerDefn();sr=layer.GetSpatialRef()
                layers.append({'name':layer.GetName(),'count':layer.GetFeatureCount(),
                    'geometry':ogr.GeometryTypeToName(layer.GetGeomType()),'crs':sr.ExportToWkt() if sr else None,
                    'fields':[d.GetFieldDefn(i).GetName() for i in range(d.GetFieldCount())]})
            r.update(type='vector',layers=layers);ds=None
        elif suffix=='.csv':
            with p.open(encoding='utf-8-sig',newline='') as f:
                reader=csv.DictReader(f);records=[];count=0
                for record in reader:
                    count+=1
                    if len(records)<5:records.append(record)
            r.update(type='table',count=count,columns=reader.fieldnames,sample=records)
        elif suffix=='.json' and p.stat().st_size<1024*1024:
            r.update(type='json',content=json.loads(p.read_text(encoding='utf-8-sig')))
        elif suffix=='.npy':
            a=np.load(p,allow_pickle=False,mmap_mode='r');r.update(type='array',shape=a.shape,dtype=str(a.dtype))
        elif suffix in {'.png','.jpg'}:
            with Image.open(p) as im:r.update(type='image',size=im.size,format=im.format);im.verify()
        r['readable']=True
    except Exception as error:r.update(readable=False,error=str(error))
    rows.append(r)
(work/'evaluation').mkdir(exist_ok=True)
(work/'evaluation/inventory.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2,default=str,allow_nan=True),encoding='utf-8')
