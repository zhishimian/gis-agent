import importlib
import json
import os
import sys
from pathlib import Path


def main() -> None:
    from qgis.core import Qgis
    from osgeo import gdal
    import pyproj
    import shapely

    versions = {'python': sys.version, 'qgis': Qgis.QGIS_VERSION, 'gdal': gdal.VersionInfo(),
                'proj': pyproj.proj_version_str, 'geos': shapely.geos_version_string}
    for name in ('numpy', 'geopandas', 'rasterio', 'pandas', 'networkx'):
        versions[name] = importlib.import_module(name).__version__
    paths = {str(Path(sys.executable).resolve())}
    paths.update(str(Path(module.__file__).resolve()) for name, module in list(sys.modules.items())
                 if getattr(module, '__file__', None) and name.split('.')[0] in {
                     'qgis', 'osgeo', 'pyproj', 'shapely', 'numpy', 'geopandas', 'rasterio', 'pandas', 'networkx'})
    Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps({'versions': versions, 'files': sorted(paths)}), encoding='utf-8')


if __name__ == '__main__':
    main()
