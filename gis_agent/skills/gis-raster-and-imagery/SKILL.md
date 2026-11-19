---
name: gis-raster-and-imagery
description: Inspect radiometric scaling and display vs physical rasters, align multi-source grids, compute NDVI/SAVI/EVI spectral indices, stream windowed raster blocks, aggregate zonal statistics, read NetCDF/HDF subdatasets, and audit image georeferencing credibility. Use whenever combining rasters of differing grids/CRS, handling DN vs reflectance indices, or testing alignment quality. Skip for single-file metadata summaries already given by inspect_data.
compatibility: Requires GeoPython (rasterio, numpy, shapely, geopandas); Tier B rasterstats and netCDF4 optional with Rasterio/GDAL Tier A fallbacks.
---

# Raster alignment, spectral indices, and imagery

Check radiometric calibration and alignment before band math, match resampling rules to data semantics, and never treat unverified visual overlays as true georeferencing.

## Workflow & Guardrails

1. **Inspect metadata & vital signs**: Read `outputs[].spatial` / `inspect_data` for `dtype`, `colorinterp`, `scale`, `offset`, `nodata`, and `valid_ratio`. Never interpret `uint8` RGB composites (`0..255`) as physical elevation or calibrated reflectance.
2. **Scale-invariant vs unit-/scale-sensitive formulas**:
   - Pure dimensionless ratios without additive terms cancel uniform positive multiplicative scaling factors when offsets are zero.
   - Any formula containing additive constants, physical thresholds, or absolute unit conversions depends directly on calibrated physical units and magnitude (`dtype`, `scale`, `offset`). Inspect value magnitude first; apply documented sensor calibration, explicitly disclose scaling/unit assumptions (or pause for confirmation when ambiguous), and cross-check spatial patterns with a scale-free metric (full spectral index formulas and examples live in [raster imagery](references/raster-imagery.md)).
3. **Reference-grid snapping**: Never stack misaligned rasters by slice indexing. Align onto a common grid with `rasterio.warp.reproject` (or `gdal:warpreproject`) using `Resampling.nearest` for categorical classes and `Resampling.bilinear`/`cubic` for continuous values, carrying explicit `src_nodata`/`dst_nodata`.
4. **Zonal stats & multidimensional data**: Stream big rasters with `block_windows(1)`. Use `rasterstats.zonal_stats` / `netCDF4` when in `runtime_capabilities["tier_b_available"]` (Tier B), or vectorized `rasterio.features.rasterize` + `np.bincount` / GDAL `NETCDF:` subdatasets cleanly in Tier A.
5. **Georeferencing credibility**: Visual center/extent matching cannot verify alignment; separate GCPs from independent checkpoints and keep unverified alignments `UNKNOWN`.

## References & Runnable Assets

- Full imagery/scaling/alignment/registration guide: [raster imagery](references/raster-imagery.md).
- Working grid snapping, SAVI DN scaling, and Tier A zonal example: [raster_align_index.py](scripts/raster_align_index.py).
- Split/checkpoint leakage demonstration: [validation_split.py](../gis-verification/scripts/validation_split.py).
