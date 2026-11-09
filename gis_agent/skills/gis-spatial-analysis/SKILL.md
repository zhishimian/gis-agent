---
name: gis-spatial-analysis
description: Build multi-step GIS analyses with tested I/O, staged Python and network examples. Consult before custom routing, spatial allocation or costly raster/vector workflows. Skip metadata questions and schema-sufficient single operations. Use gis-verification for evidence and gis-cartography for map output.
compatibility: Requires GeoPandas/Shapely or QGIS Python; the parallel-edge example also needs NetworkX. Processing examples use this checkout's run_processing helper; other hosts must expose the checkout on PYTHONPATH.
---

# Spatial analysis

For an independent standard operation, use an available QGIS tool when its schema covers the task. Reuse an exact algorithm already found. Processing scripts suit batches and shared intermediates; PyQGIS exposes GIS objects; GeoPandas/Shapely suit tabular joins and geometry operations. Pick the route with enough semantics and little setup.

For nontrivial work, prefer a relevant tested pattern before rebuilding environment-specific I/O or graph algorithms. Read only the resource needed:

- Actual backend, GDB/layer paths, Unicode/nulls: [data I/O](references/data-io.md), with [io_roundtrip.py](scripts/io_roundtrip.py).
- Costly prefixes and volatile exports: [staged Python](references/staged-python.md), with [staged_compute.py](scripts/staged_compute.py).
- Routing, service areas or network siting: [network guide](references/networks.md); run [network_cases.py](scripts/network_cases.py) for N1-N6.

- Planning overlays, joins, raster/elevation work, data flow or routing: [patterns](references/patterns.md).
- Interpolation splits, image alignment, catchments, DEM masks or expensive stages: [terrain and imagery](references/terrain-imagery.md).
- A complete Processing chain: [reproject_clip.py](scripts/reproject_clip.py).
- A lossless match ledger and optional field ratio: [spatial_join.py](scripts/spatial_join.py).
- Parallel road alternatives and a tested graph example: [parallel_edges.py](scripts/parallel_edges.py).
- Processing initialization and structured results: [shared execution reference](../../integrations/qgis/execution.md).
- Geometry/API errors: [gotchas](references/gotchas.md).

Before propagating a new formula, spatial assignment or approximation, use gis-verification to choose sufficient evidence. It does not require a second implementation of the analysis. Load gis-cartography only for a map deliverable.
Examples can be run, imported, copied or adapted. Their matching and calculation choices stay explicit; they do not choose business policy. User requests and map labels may remain in the user's language.
