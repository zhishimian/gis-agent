# Raster alignment, spectral scaling, and imagery

## Inspection, radiometric scaling, and display composites

Inspect band `dtype`, `colorinterp`, `scale`, `offset`, `unit`, `nodata`, and overview min/max/valid-ratio (via `outputs[].spatial` or `inspect_data`) before computing derivatives or indices:
- Apply documented sensor `scale` and `offset` metadata first when present.
- Distinguish three- or four-band `uint8` display composites (`0..255` RGB + alpha) from calibrated physical elevation or reflectance rasters; never report display-quantized brightness gradients as metric elevation or physical radiance.
- **Scale-invariant vs non-scale-invariant indices**: Normalized ratios without additive terms (`NDVI = (NIR - Red) / (NIR + Red)`, `NDWI`) cancel shared positive multiplicative scale factors when band offsets are zero. By contrast, indices with dimensionless additive constants — such as **SAVI** `(1 + L) * (NIR - Red) / (NIR + Red + L)` (`L = 0.5`) or **EVI** — assume `[0, 1]` surface reflectance and are NOT scale-invariant on raw `0..10000` integer DN (`L = 0.5` vanishes by 4 orders of magnitude). Check scale metadata and document reflectance normalization (`DN / 10000.0`) explicitly.

## Reference-grid snapping and resampling

Never stack rasters with mismatched transforms, pixel sizes, or CRS by array slicing alone. Align every secondary layer onto the chosen reference grid via `rasterio.warp.reproject` (or `gdal:warpreproject`):
- Use `Resampling.nearest` strictly for discrete/categorical classes (`land_cover`, `zone_id`, masks) so class integers are never blended into nonexistent codes.
- Use `Resampling.bilinear` or `Resampling.cubic` for continuous reflectance/elevation fields, specifying explicit `src_nodata` and `dst_nodata`.
- For large rasters, stream windows with `dataset.block_windows(1)` (writing tile by tile with identical window offsets after alignment) to avoid loading multi-GB bands into RAM.

## Zonal statistics and multi-dimensional datasets

- **Tier B (`rasterstats`, `netCDF4`, `xarray`)**: when present in `runtime_capabilities`, `rasterstats.zonal_stats` handles touching/all-touched polygon options concisely and `netCDF4`/`xarray` reads CF time/level dimensions directly.
- **Tier A fallback (`rasterio` + `numpy`)**: rasterize vector zone IDs onto the snapped raster grid with `rasterio.features.rasterize(..., dtype="int32")` and compute fast vectorized zone counts/sums via `np.bincount(zone_ids[valid], weights=band[valid])` — avoiding slow Python polygon loops. For `.nc`/`.hdf`, inspect subdatasets (`NETCDF:"file.nc":var`) through GDAL/Rasterio.

## Georeferencing credibility and checkpoints

A CRS label or affine transform is a location hypothesis. Matching centers or forcing equal extents without correspondence points proves nothing. Separate fitting control points (GCPs) from independent evaluation checkpoints; record residuals in pixels and ground units alongside spatial coverage. Unverified visual alignments must stay marked `UNKNOWN`, and dependent zonal updates conditional. See [validation_split.py](../../gis-verification/scripts/validation_split.py) and [raster_align_index.py](../scripts/raster_align_index.py).
