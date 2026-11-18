---
name: gis-spatial-statistics
description: Run spatial autocorrelation (Moran I, LISA, Getis-Ord Gi*), spatial weights construction with island audits, Kriging/IDW geostatistical interpolation, variogram inspection, and spatial/group block cross-validation without holdout leakage. Automatically routes between Tier B libraries (esda, libpysal, pykrige, scikit-learn) and Tier A SciPy/NumPy fallbacks based on runtime_capabilities. Skip for deterministic vector overlays or basic descriptive summary counts.
compatibility: Core path works in any GeoPython interpreter with numpy and scipy; Tier B enriches with esda, libpysal, pykrige, mapclassify, and scikit-learn.
---

# Spatial statistics, interpolation, and blocked validation

Inspect spatial weights and variogram assumptions, prevent holdout leakage via spatial blocking, and route cleanly between Tier B geostatistical packages and Tier A SciPy/NumPy implementations.

## Dual-Environment Routing (`runtime_capabilities`)

Check `runtime_capabilities["tier_b_available"]` before importing optional stats libraries:
- **Tier B (`esda`, `libpysal`, `pykrige`, `scikit-learn`, `mapclassify`)**: Prefer `libpysal.weights` (`Queen`/`KNN`, verify `w.islands`), `esda.Moran`/`G_Local`, `pykrige.ok.OrdinaryKriging` with explicit variogram checks, and `sklearn.model_selection.GroupKFold`.
- **Tier A Core Fallback (`scipy`, `numpy`)**: When Tier B packages are missing (e.g. desktop QGIS Python), compute exact row-standardized K-NN Global Moran's I via `scipy.spatial.cKDTree`, Ordinary Kriging via `scipy.spatial.distance.cdist` + `numpy.linalg.solve` (or bounded-neighbor IDW), and NumPy rectangular spatial block CV ([spatial_stats_examples.py](scripts/spatial_stats_examples.py)).

## Workflow & Guardrails

1. **Metric distance & weights checks**: Project observations to an appropriate metric CRS before bandwidth/Kriging distances; inspect isolated units (`islands`) and explicitly justify row-standardized (`"r"`) vs binary (`"b"`) weights.
2. **Prevent spatial/selection leakage**: Lock train / tune / untouched evaluation roles before tuning variograms, neighbor counts, or outlier filters. Use spatial/site/time blocks (`spatial_block_folds`) when nearby samples exhibit spatial autocorrelation.
3. **Cost & coverage reporting**: Estimate `M * N` matrix size and `O(N^3)` Kriging factorization cost before global prediction; apply neighbor bounds or tiled evaluation on large grids and report valid prediction coverage alongside RMSE/R2.

## References & Runnable Assets

- Weights, variograms, Tier A/B fallbacks, and leakage checks: [spatial stats](references/spatial-stats.md).
- Dual-tier Moran's I, Ordinary Kriging, and spatial-block script: [spatial_stats_examples.py](scripts/spatial_stats_examples.py).
- Synthetic selection-leakage demo: [validation_split.py](../gis-verification/scripts/validation_split.py).
