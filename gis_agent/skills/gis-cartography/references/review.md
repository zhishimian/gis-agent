# Visual evidence and stopping

Reuse established analysis evidence. Check only new display transforms and encodings unless a defect exposes an analytical gap.

1. Read actual layer/field/CRS/extent facts. For overlays compare a known anchor; for rasters inspect transform, NoData and resampling.
   Check the analytical source's confidence and mask before plotting. A centered image can still be ungeoreferenced. Mask finite NoData sentinels before profiles, color limits and smoothing. A conditioned DEM can differ from the engineering surface. Use the [shared terrain reference](../../gis-spatial-analysis/references/terrain-imagery.md) when those facts are uncertain.
2. Verify that mapping, classes, units and legend share the same semantics. Keep zero distinct from missing; comparable panels share the necessary norm/extent.
3. Inspect the current whole PNG/preview with an available image reader. Check expected objects, position, layer visibility, useful extent, legibility and unnecessary formulas/technical text. Inspect dense labels against points and links; correct coordinates and high zorder alone cannot establish visibility.
4. Crop only an uncertain legend, dense region or label. Fix related observed defects together. Stop when remaining differences do not affect interpretation or the requested quality.

Prioritize spatial/encoding errors, missing or occluded objects, wrong legends, clipped text, then meaningful spacing. Repeated cosmetic edits without new evidence add no confidence.
The manifest proves recorded file/environment/Artist facts; it does not associate every artist with the correct geographic source. SVG/PDF need format checks; review their same-Figure PNG preview without claiming the image reader opened the vector file. Static images and rerunnable code do not provide an editable native QGIS layout.
For a requested format or DPI, inspect the actual exported file metadata. Reuse the same Figure for compatible formats. Keep failed or uncertain analytical branches identifiable in the outside-the-map delivery notes; visual polish cannot remove those limitations.
