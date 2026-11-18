"""Probe the actual GeoPandas/pyogrio backend with tiny NEW GIS files.

Requires GeoPandas, pyogrio, Rasterio, NumPy and osgeo in GIS Python. CLI:
python io_roundtrip.py settings.json; settings: {"output_dir":"unused/path"}.
Produces GPKG, FileGDB, GeoTIFF and facts.json; never overwrites an existing
directory. Checks Unicode, string and numeric 64-bit IDs, nulls, geometry, CRS,
pixels, mask and transform. This proves only this sample in this process.
Failure raises with backend/driver/dataset/layer/phase and original exception.
Do not translate a QGIS URI into a fabricated physical path.
"""
import json
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import rasterio
from osgeo import gdal, ogr
from rasterio.transform import from_origin
from shapely.geometry import Point


def probe(output_dir):
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=False)
    data = gpd.GeoDataFrame({'business_id': ['0007', '9007199254740993'],
        'numeric_id': np.array([2**40, 2**40+1], dtype='int64'),
        '\u540d\u79f0': ['\u7532', '\u4e59'], 'amount': [1.25, None]},
        geometry=[Point(500000, 4400000), Point(500001, 4400001)], crs='EPSG:32650')
    facts = {'backend': 'pyogrio', 'python': sys.executable, 'pyogrio': pyogrio.__version__,
             'pyogrio_gdal': pyogrio.__gdal_version__, 'osgeo_gdal': gdal.VersionInfo(),
             'outputs': {}, 'vectors': {}}
    for driver, suffix in [('GPKG', '.gpkg'), ('OpenFileGDB', '.gdb')]:
        path, layer, phase = root / ('tiny' + suffix), 'objects', 'write'
        try:
            data.to_file(path, layer=layer, driver=driver, engine='pyogrio', index=False)
            phase = 'readback'
            read = gpd.read_file(path, layer=layer, engine='pyogrio')
            if (len(read) != 2 or read.crs != data.crs or
                read.business_id.tolist() != data.business_id.tolist() or
                read.numeric_id.tolist() != data.numeric_id.tolist() or
                read['\u540d\u79f0'].tolist() != ['\u7532', '\u4e59'] or read.amount.isna().sum() != 1 or
                not all(a.equals(b) for a, b in zip(read.geometry, data.geometry))):
                raise ValueError('Readback differs in identity, fields, nulls, geometry or CRS')
            phase = 'OGR independent open'
            ds = ogr.Open(str(path), 0)
            if ds is None or ds.GetLayerByName(layer).GetFeatureCount() != 2:
                raise ValueError('OGR cannot reopen expected layer')
            ds = None
            facts['vectors'][driver] = {'count': len(read), 'columns': list(read.columns),
                'dtypes': {k: str(v) for k, v in read.dtypes.items()}, 'layers': pyogrio.list_layers(path).tolist()}
            facts['outputs'][driver] = str(path)
        except Exception as error:
            raise RuntimeError(f'backend=pyogrio driver={driver} dataset={path} layer={layer} phase={phase}: {error}') from error
    path = root / 'tiny.tif'
    array = np.array([[1., -9999.], [0., 3.]], dtype='float32')
    transform = from_origin(500000, 4400000, 5, 5)
    with rasterio.open(path, 'w', driver='GTiff', width=2, height=2, count=1,
                       dtype=array.dtype, crs=data.crs, transform=transform, nodata=-9999.) as dst:
        dst.write(array, 1)
    with rasterio.open(path) as src:
        assert np.array_equal(src.read(1), array) and src.transform == transform and src.crs == data.crs
        assert src.nodata == -9999. and src.read_masks(1).tolist() == [[255, 0], [255, 255]]
    facts['outputs']['raster'] = str(path)
    (root / 'facts.json').write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding='utf-8')
    return facts


if __name__ == '__main__':
    result = probe(**json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
    text = json.dumps(result, ensure_ascii=False, allow_nan=False)
    if os.environ.get('GIS_AGENT_RESULT_PATH'):
        Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(text, encoding='utf-8')
    print(text)
