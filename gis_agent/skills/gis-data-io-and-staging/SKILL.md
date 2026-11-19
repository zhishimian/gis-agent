---
name: gis-data-io-and-staging
description: Read, validate, and export multi-layer GIS containers (GPKG, FileGDB, Shapefile, GeoTIFF, Parquet/DuckDB) and split costly or volatile spatial workflows into resumable staged files. Use when formats, container layers, leading-zero business keys, large multi-GB tables, backend errors, or intermediate stage persistence affect execution. Skip for single-file metadata reads already answered by inspect_data or trivial single-step native QGIS algorithms.
compatibility: Requires GeoPython (geopandas, pyogrio, rasterio, numpy) in a configured interpreter; QGIS Processing or Tier B duckdb optional.
---

# GIS data I/O and staged execution

Pick the concrete driver, inspect actual layers and attributes before downstream merges, and isolate expensive upstream stages from volatile downstream formatting or failure recovery.

## Quick Decision & Environment Routing

1. **Inspection**: Verify layers with `pyogrio.list_layers(path)` (GeoPandas) or `path.gpkg|layername=actual` (QGIS URI). Never assume filename == layer name or infer layer existence from `.gdb` directory paths.
2. **Large table pushdown**:
   - **Tier A (`pyogrio` / GeoPandas)**: Push spatial/attribute filters into the read call (`read_file(path, layer=..., bbox=..., where=..., columns=..., engine="pyogrio")`).
   - **Tier B (`duckdb` in `runtime_capabilities`)**: Use DuckDB `ST_Read()` or Parquet scans for multi-GB joins/aggregations before writing compact GPKG results.
3. **Staging split & complexity gating**: Before launching full-dataset operations on large or dense inputs (`> 5,000` features or `> 10 MB`), validate logic and runtime on a tiny slice (`< 10s`) rather than risking blind full-scale timeouts. Split costly steps at a stable boundary -> write self-contained closed `GPKG` / `GeoTIFF` / `NPY` / `JSON` -> always reopen outputs and verify schema/shape/finite values instead of assuming file existence implies validity.

## Core Guardrails

- Persist explicit string business IDs (`object_key`) rather than relying on GPKG `fid` (which drivers may omit or regenerate across exports) or Float64 integers (precision loss & stripped leading zeros).
- Keep output generation isolated from protected inputs; never pass another tool's external `PROJ_LIB` into standalone GeoPython wheels; never use `os._exit(0)` to hide cleanup tracebacks.
- Inspect execution logs and past script snapshots via `execution_history` before fixing broken tail stages.

## References & Runnable Assets

- Backend differences, FileGDB/Shapefile caveats, and roundtrip probe: [data I/O](references/data-io.md) + [io_roundtrip.py](scripts/io_roundtrip.py).
- Incremental prepare/summarize JSON pattern and local repair: [staged Python](references/staged-python.md) + [staged_compute.py](scripts/staged_compute.py).
- Common runtime tracebacks, schema drift, and PyQGIS scope traps: [execution gotchas](references/gotchas.md).
- Shared QGIS Processing entrypoint boilerplate: [QGIS execution guide](../../integrations/qgis/execution.md).
