# Plotting gotchas

- GIS libraries live in the configured GIS interpreter; another Python can lack them. Some installations use user-level packages. Check real environment paths when moving machines.
- GeoPandas uses path plus layer, not a QGIS pipe URI. set_crs labels coordinates; to_crs transforms them.
- Higher zorder draws above lower layers. Filled backgrounds can hide the subject. facecolor="none" is transparent; Python None can select a default fill.
- A metric CRS still has projection scale error. Longitude/latitude and Web Mercator distances need appropriate interpretation; an upward arrow may indicate grid north.
- scheme requires mapclassify, which may be absent. Use explicit task thresholds/BoundaryNorm or verify the dependency before using it.
- Keep zero, NoData and NaN separate. Locate nonfinite values; boundaries must cover the maximum and remain strictly increasing.
- Rasterio bounds are left,bottom,right,top. imshow extent is left,right,bottom,top; use plotting_extent. out_shape needs a scaled transform. Use WarpedVRT for rotated grids instead of stretching a bounding box.
- Bilinear resampling mixes categories; use nearest for categorical rasters. A display histogram is not a source-pixel inventory.
- Register fonts each process and inspect missing-glyph warnings. A font file alone does not prove every character is available.
- AnchoredSizeBar.txt_label is a TextArea. Neither set_fontsize nor set_text_props is available in the tested environment. Use fontproperties on the scale bar or edit its Text child; see the [API example](api.md). Silently skipping a nonexistent method does not confirm a style change.
- Keep explicit fig/ax, export that figure, and close it. Do not initialize QGIS/Qt for Matplotlib.
- A file can exist after a failed run; retain the failure rather than accepting partial stdout. Re-read the current image after edits.
- In GIS-Agent an image is visible only to the immediately following model request. Use the preview when the full PNG exceeds reader limits.
