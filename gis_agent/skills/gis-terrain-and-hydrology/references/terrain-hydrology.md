# Terrain surfaces, NoData, and hydrology

## Surface semantics and engineering vs conditioned DEMs

- Distinguish bare-earth **DEM** (terrain surface) from **DSM** (canopy/roof top) and **nDSM / object height** (`DSM - DEM`). Maximum DSM elevation and height above building base are distinct quantities.
- Keep original engineering terrain separate from hydrologically conditioned (sink-filled / breached) DEMs. Sink filling alters pit depths, local slopes, and reservoir storage; use the unconditioned DEM for earthwork, profiles, and slope unless the task explicitly specifies conditioned terrain, and log fill-depth statistics (`max_fill`, modified cell percentage).
- Inspect `dtype`, `nodata`, vertical units, and finite sentinel values before derivatives. Finite-difference slopes require all contributing stencil neighbors to be valid; never leave `-9999` or edge padding unmasked where it creates synthetic vertical cliffs.

## D8 flow direction encoding and catchment boundaries

Different tools encode D8 neighbor directions incompatibly — always check metadata and raster unique codes before writing downstream scripts:
- **GRASS `r.watershed`**: `1 = NE`, `2 = N`, `3 = NW`, `4 = W`, `5 = SW`, `6 = S`, `7 = SE`, `8 = E` (counterclockwise from NE; negative values indicate watershed boundary spillover leaving the region).
- **ESRI / TauDEM / RichDEM D8**: powers of two `1 = E`, `2 = SE`, `4 = S`, `8 = SW`, `16 = W`, `32 = NW`, `64 = N`, `128 = NE`.

Catchment semantics must also match the question:
- **Complete upstream contributing area** at nested outlets (`upper` flows into `lower`) produces overlapping catchments where `upper_mask` is a subset of `lower_mask`.
- **Simultaneous multi-seed catchment partitioning** stops tracing when encountering another outlet seed, producing non-overlapping inter-outlet partitions whose downstream area is smaller than total flow accumulation.
- Account explicitly for **self-cell counting** (`acc >= 1` vs `0`) and metric grid cell area (`dx * dy`) in projected CRS.

## Reservoir storage and flood connectivity

Flood or reservoir storage volume below a water level `H` cannot be computed by `dem <= H` alone unless disconnected low topographic pockets behind ridges are impossible or excluded. Trace connected inundation from the dam/channel seed cell, mask invalid/NoData cells, and integrate `sum(max(0, H - dem[connected]) * cell_area)`.

## Runnable counterexamples and bilinear checks

For bilinear sampling near borders or invalid cells, bounds-check indices and mask stencils whenever any required nonzero-weight neighbor is invalid; do not silently clamp out-of-bounds indices. Run [terrain_counterexamples.py](../scripts/terrain_counterexamples.py) and [hydrology_routing.py](../scripts/hydrology_routing.py) in either Tier A or Tier B Python. See also [validation_split.py](../../gis-verification/scripts/validation_split.py).
