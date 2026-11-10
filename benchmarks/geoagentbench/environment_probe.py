import importlib
import importlib.util
import json
import sys
from pathlib import Path
from osgeo import gdal

target = Path(sys.argv[1])
if '--original' not in sys.argv:
    sys.path.insert(0, str(target / 'environment/python'))
modules = ['numpy','pandas','scipy','sklearn','geopandas','rasterio','shapely','networkx','matplotlib',
           'pykrige','netCDF4','cftime','xarray','mapclassify','rasterstats','osmnx','libpysal','esda',
           'hdbscan','numba','statsmodels','mgwr','spglm','spreg','affine','simplejson','tqdm','joblib','patsy']
result = {'python':sys.version,'executable':sys.executable,'gdal':gdal.VersionInfo('--version'),'modules':{}}
for name in modules:
    try:
        module=importlib.import_module(name)
        result['modules'][name]={'ok':True,'version':getattr(module,'__version__','unknown'),'file':getattr(module,'__file__',None)}
    except Exception as e:
        result['modules'][name]={'ok':False,'error':str(e)}
(target / ('environment/original-probe.json' if '--original' in sys.argv else 'environment/probe.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v.get('version',v.get('error')) for k,v in result['modules'].items()},ensure_ascii=True))
