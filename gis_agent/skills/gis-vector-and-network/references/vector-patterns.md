# Vector patterns and chunked overlays

## CRS split and routes

Use the supplied schema for a standard standalone algorithm. Batch chains with reusable intermediates can use QGIS Processing or Python GeoPandas/Shapely; avoid probing an environment already described in `runtime_capabilities`.

`set_crs` assigns a metadata label; `to_crs` transforms coordinates. Record source, analysis, and requested delivery CRS separately. Matching the unit name (e.g. `metre` in Web Mercator `EPSG:3857`) does not guarantee low area or length distortion; prefer a local UTM or equal-area CRS for metric measurements, then reproject only for final delivery when requested.

## Geometry, keys, and join cardinality

- `Polygon` exposes `exterior` and `interiors`; `MultiPolygon` exposes `geoms`. Always recurse through `Multi*` and `GeometryCollection` rather than silently taking the largest part unless the task specifies largest-part selection.
- `QgsGeometry` vs `constGet()`: use `isMultipart()`/`asMultiPolygon()` on `QgsGeometry`, or work in Shapely cleanly. Run `shapely.make_valid` only when repairing invalid source topology and record repaired counts.
- Preserve an explicit business key before operations that reset or regenerate `fid`s. After writing an intermediate layer, inspect actual layer names and column schemas (`pyogrio.list_layers`, `df.columns`) before merging:

```python
import geopandas as gpd

layers = gpd.list_layers(intermediate)
left = gpd.read_file(intermediate, layer=actual_layer, engine="pyogrio")
reference = zones[["zone_key", "name"]].rename(columns={"name": "zone_name"})
joined = left.merge(reference, on="zone_key", how="left", validate="many_to_one")
```

- A spatial join is a relation (`0`, `1`, or `many` matches per object). Choose `intersects` (includes boundary contact), `within` (excludes boundary), or `covered_by` (includes boundary) explicitly. Do not treat arbitrary first match or largest intersection as winner without a domain rule.

## Tile-halo chunking for large vector overlays

When polygon overlay (`intersection`, `union`, `clip`, distance-based `sjoin`) exceeds comfortable RAM (`> 500k` vertices or multi-region extents):
1. Partition the analysis extent into regular tiles `T_i` using a Spatial Index (`STRtree` or `sindex`).
2. Extract candidate geometries inside `T_i` expanded by a **Halo buffer** equal to the maximum interaction radius (or `0` for strict topological `clip` inside tile bounds), execute the overlay/query per tile, clip outputs strictly to unbuffered `T_i`, and deduplicate any split boundary objects by business key + dissolve if unified parts are required.

## Formulas, precision, and executable examples

Write target quantities and units before choosing numerator/denominator. Distinguish counts, densities, and weights, and keep zero denominators separate from null inputs. Consult [numerical precision](../../gis-verification/references/checks.md#numerical-precision).

- [reproject_clip.py](../scripts/reproject_clip.py): Processing reprojection + clip with settings JSON, failing cleanly on existing target outputs.
- [spatial_join.py](../scripts/spatial_join.py): GeoPandas `features.gpkg` (`match_count`) + `matches.csv` preserving multiplicity and verifying unique business keys and explicit `analysis_crs`.
