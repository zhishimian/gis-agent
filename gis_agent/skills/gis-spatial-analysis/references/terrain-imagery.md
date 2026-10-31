# Interpolation, imagery and terrain

## Interpolation and evaluation

Choose sample roles before model selection. Fit on training observations; tune methods, neighborhood size and parameters with training-only cross-validation or a separate validation set. Keep the final evaluation observations isolated from fitting, tuning, cleaning thresholds and method selection. Record stable sample IDs, split seed, units and valid-prediction coverage. Repeatedly selecting the lowest error on the final holdout turns it into validation data.

If the task provides only a training split and a final holdout, do tuning within training. After evaluation, a full-data map can be produced if requested, but its fit and the held-out score describe different models. Spatially adjacent observations or repeated site measurements can leak information across random splits; use spatial/site/time blocks when the prediction question requires them. Do not silently replace the requested split protocol.

The executable [validation split counterexample](../../gis-verification/scripts/validation_split.py) shows why choosing a method from final test errors invalidates an untouched-test claim. It is synthetic arithmetic, with no interpolation algorithm or contest inputs.

## Image registration credibility

A CRS label or transform is a hypothesis about location. Check sidecars, sensor metadata and reference rasters before changing it. Matching centers or forcing equal extents supplies no geographic correspondence, even if the overlay looks plausible.

Use reliable, spatially distributed correspondences to estimate an appropriate transform. Check residuals in pixels and ground units, independent checkpoints and edge/interior coverage. Separate fitting control points from check points. A low fit residual can hide an overfit warp. Automatic features need spatial consistency and outlier rejection; repeated texture can yield plausible false matches.

Keep an unverified alignment as a diagnostic candidate. Describe its evidence as UNKNOWN and keep dependent class updates, zonal statistics and maps conditional. Continue independent work where possible. Reprojection resamples known coordinates; it cannot recover unknown georeferencing.

## Catchments and terrain surfaces

Define whether a requested basin means the complete upstream contributing area at one outlet, a nonoverlapping subbasin partition, or the water-level-connected inundation region. Nested outlets have overlapping complete catchments. Simultaneously seeding every outlet and stopping propagation at the next outlet produces inter-outlet partitions. Check a nested pair against accumulation, accounting for cell area, self-cell counting, masks and D8 versus multiple-flow routing.

Reservoir storage requires the task's water level, connected inundated region and terrain elevations. Complete catchment area alone cannot determine storage. Natural inflow/junction counts also require an explicit network definition.

Keep original terrain and hydrologically conditioned surfaces separate. Filling/breaching may substantially alter profiles, slopes and storage. Record modification depths and coverage. Use the original or explicitly required engineering surface for cross sections and earthwork. Use conditioned terrain for routing only where its assumptions apply.

## NoData and grid edges

Read the real mask, finite values, transform, vertical units and pixel-center convention. A finite sentinel is still invalid. For a finite-difference slope require the needed neighbors to be valid. Outlet boundary rules are separate from the elevation assigned to invalid cells; a low sentinel must not create artificial cliffs.

For bilinear sampling, check raster bounds before indexing and inspect all contributors with nonzero weights. If a required contributor is invalid, return a missing observation or use an explicitly justified alternative. Silently clamping an outside sample or renormalizing a masked stencil changes the method. Report excluded checkpoints alongside RMSE. Mask invalid values before smoothing and plotting.

Run [terrain_counterexamples.py](../scripts/terrain_counterexamples.py) without arguments through the GIS interpreter. It demonstrates nested catchments, masked interpolation and cost/cache facts. It is a small synthetic example, with no DEM reconstruction or hydrological engine.

## Work estimates and reusable intermediates

Estimate source count, target cells, neighborhood size, array bytes and major temporary arrays before launching dense processing. All-point interpolation can require roughly source_count * target_cells distance evaluations; bounded-neighbor methods reduce that work but change the estimator. Contour densification can dominate both triangulation and memory. Use a representative tile/timing sample and an I/O smoke check before a long run; extrapolation is only an estimate.

Preserve task-required resolution and algorithm semantics when reducing cost. Consider indexed neighborhoods, windowed queries and chunked targets where appropriate. Record the selected radius/k, extrapolation policy and grid. Chunking queries alone does not bound the size of a global triangulation.

Persist an expensive successful stage before optional exports or downstream work. A reusable cache needs input fingerprints, selected layers/fields, CRS/grid, method parameters and implementation version. For multi-file datasets include relevant sidecars. Existence alone does not establish cache validity. Reopen the output and check shape, dtype, transform, mask and finite coverage; reject incomplete files. Write a completed artifact/manifest only after success. Changing an input or parameter invalidates its dependent results; unchanged verified stages can be reused. Keep this local to the task script.
