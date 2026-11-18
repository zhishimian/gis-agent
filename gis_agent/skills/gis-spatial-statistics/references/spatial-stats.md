# Spatial statistics, interpolation, and validation

## Dual-environment routing (`runtime_capabilities`)

Check `tier_b_available` in `runtime_capabilities` before selecting libraries:
- **Tier B (`esda`, `libpysal`, `pykrige`, `scikit-learn`, `mapclassify`)**:
  - Spatial weights & autocorrelation: build `libpysal.weights.Queen.from_dataframe(gdf)` or `KNN.from_dataframe(gdf, k=...)`, always inspect `w.islands` (disconnected units) before row standardization `w.transform = "r"`, then run `esda.Moran`, `esda.Moran_Local` (LISA), or `esda.G_Local` (Getis-Ord Gi*).
  - Geostatistics: use `pykrige.ok.OrdinaryKriging` or `UniversalKriging` in a projected metric CRS; inspect empirical vs fitted variogram (`variogram_model`, `sill`, `range`, `nugget`) rather than blindly accepting defaults.
  - Classification & ML validation: `mapclassify` for Fisher-Jenks/quantiles and `sklearn.model_selection.GroupKFold` for spatial/site/time blocked cross-validation.
- **Tier A Fallbacks (QGIS core: `scipy`, `numpy`, `pandas`, `geopandas`, `shapely`)**:
  - When Tier B packages are absent (e.g., QGIS desktop Python environment), do NOT fail with `ImportError`. Use `scipy.spatial.cKDTree` sparse K-NN weights for exact matrix Moran's I + permutation Z-score, `scipy.spatial.distance.cdist` + `numpy.linalg.solve` for Ordinary Kriging (or inverse-distance weighting with explicit power and neighbor cap), and pure `numpy` coordinate-grid blocking for spatial cross-validation. See [spatial_stats_examples.py](../scripts/spatial_stats_examples.py).

## Validation protocol and preventing spatial leakage

1. Assign sample roles (`train` / `tune` / `final_holdout`) before any cleaning threshold, variogram tuning, or model comparison.
2. Repeatedly choosing the model/hyperparameter with lowest error on the final holdout leaks holdout information into selection. Tune exclusively within training folds using **spatial, site, or time blocks** when neighboring observations correlate spatially.
3. Report stable sample IDs, split protocol/seed, units, excluded/masked observation counts, and valid prediction coverage alongside RMSE/MAE/R2. Do not estimate global interpolation cost blindly: for `M` targets x `N` observations, naive global kriging/IDW requires `O(M*N)` distances or `O(N^3)` factorization; bound neighbor radii or tile query points cleanly. See [validation_split.py](../../gis-verification/scripts/validation_split.py).
