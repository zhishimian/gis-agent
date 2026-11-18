# GIS data I/O

GeoPandas is a dataframe API. `pyogrio`, `Fiona`, and `osgeo.ogr` are distinct vector backends, and drivers belong to the actual imported backend/interpreter. An `osgeo` capability check does not establish that `pyogrio` writes the same schema.

| Address | Use |
| --- | --- |
| `/data/store.gdb` or `/data/store.gpkg` | Physical container; register this in `export_figure` inputs |
| `read_file(path, layer="actual", engine="pyogrio")` | Explicit vector layer/backend; enumerate `list_layers` first |
| `path.gpkg\|layername=actual` | QGIS URI for compatible QGIS tools, not a filesystem path |
| `/data/image.tif` | Rasterio or GDAL raster API; inspect masks/grid/bands |

## Layering, schemas, and large-table pushdown

- `store.gdb/objects` is not a physical layer file; directory existence does not prove a layer exists.
- OpenFileGDB vector write support does not imply raster writing. Shapefile has sidecars, DBF encoding limits, and 10-char column truncation; document any field mapping when Shapefile is explicitly requested.
- Null integers may coerce to float. Persist business IDs explicitly as strings to preserve leading zeros and 64-bit identifiers beyond exact `Float64` integer precision.
- For large vector inputs:
  - **Tier A (`pyogrio` / GeoPandas)**: push spatial, attribute, and column filters into the reader (`gpd.read_file(path, layer="...", bbox=roi_bounds, where="pop > 0", columns=["id", "pop"], engine="pyogrio")`) instead of loading millions of rows into RAM.
  - **Tier B (`duckdb` spatial)**: when `duckdb` is present in `runtime_capabilities`, use `INSTALL spatial; LOAD spatial;` (or offline preinstalled spatial extension) + `ST_Read()` / GeoParquet scans for multi-GB analytical aggregations before materializing a filtered GPKG/GeoParquet output.

## Roundtrip probe and verification

Run [io_roundtrip.py](../scripts/io_roundtrip.py) with settings `{"output_dir":"/work/unused_probe"}` before a difficult format export. It writes tiny GPKG/FileGDB/GeoTIFF through the actual backend and reopens Unicode fields, nulls, string/numeric IDs, geometry/CRS, array/mask/transform. OGR independently opens vector layers. Tracebacks remain nonzero.

Reopen final outputs and compare required fields, counts, and geometry. Separate costly analysis into closed GPKG/GeoTIFF before final export. See [staged Python](staged-python.md).
