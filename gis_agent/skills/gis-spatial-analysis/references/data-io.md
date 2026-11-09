# GIS data I/O

GeoPandas is a dataframe API. pyogrio, Fiona and osgeo.ogr are distinct vector
backends. Drivers belong to the actual imported backend/interpreter; an osgeo
capability check does not establish that pyogrio writes the same schema.

| Address | Use |
| --- | --- |
| `/data/store.gdb` or `/data/store.gpkg` | Physical container; register this in export_figure inputs |
| `read_file(path, layer="actual", engine="pyogrio")` | Explicit vector layer/backend; enumerate list_layers first |
| `path.gpkg\|layername=actual` | QGIS URI for compatible QGIS tools, not a filesystem path |
| `/data/image.tif` | Rasterio or GDAL raster API; inspect masks/grid/bands |

`store.gdb/objects` is not a physical layer file. Directory existence does not
prove a layer exists. OpenFileGDB vector write support does not imply raster
writing. Shapefile has sidecars, encoding and short-field limits; document any
field mapping. Null integers may become floats. Persist business IDs explicitly;
strings preserve leading zeros and IDs beyond exact Float64 integer precision.

Run [io_roundtrip.py](../scripts/io_roundtrip.py) with settings
`{"output_dir":"/work/unused_probe"}` before a difficult format export. It writes
tiny GPKG/FileGDB/GeoTIFF through the actual backend and reopens Unicode fields,
nulls, string/numeric IDs, geometry/CRS, array/mask/transform. OGR independently
opens vector layers. It tests this sample only, with explicit backend/driver/
dataset/layer/phase errors. Tracebacks remain nonzero. It does not probe arbitrary
schemas, databases or Shapefile.

Reopen final outputs and compare required fields, counts and geometry. Separate
costly analysis into GPKG/GeoTIFF before final export. Prefer a working mature
backend to a custom writer. See [staged Python](staged-python.md).
