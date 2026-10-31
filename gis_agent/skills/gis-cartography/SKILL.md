---
name: gis-cartography
description: Design, render, revise and export thematic maps or scientific geographic figures with Matplotlib, GeoPandas and Rasterio. Use for requested map images, choropleths, raster/vector overlays or multi-panel figures. Skip data-only analysis and numeric verification; use gis-spatial-analysis and gis-verification for those. Review images for actual defects without repeating established analysis.
compatibility: Requires the checkout's plotting helpers plus Matplotlib, GeoPandas and Rasterio in GIS Python. Other hosts must expose the checkout on PYTHONPATH.
---

# Thematic cartography

Choose content, visual encoding and layout around the reader's geographic question. Reuse completed analysis, actual layers, fields, units and CRS. Execute free Python through the configured GIS interpreter; Matplotlib Agg needs no QgsApplication or Qt.
Keep uncertain georeferencing or incomplete analytical coverage explicit in the delivery; do not promote a diagnostic candidate to a verified map. Reuse unchanged analytical intermediates and fix display defects without repeating expensive analysis.
Keep the map focused on geography. Add only necessary titles, legends, units, scale bars, direction cues and place labels. By default, put formulas, CRS/method explanations and technical reports outside the figure; avoid stacked subtitles and explanatory panels. User titles and labels may use any supported language.

Read only what is needed:

- Vector overlay: [vector_map.py](scripts/vector_map.py).
- Continuous or classified values: [choropleth.py](scripts/choropleth.py).
- Raster, vector, inset and statistics: [raster_composite.py](scripts/raster_composite.py).
- Environment, inputs, outputs and runnable settings: [API](references/api.md).
- Encoding and layout choices: [design](references/design.md).
- Fonts, projection and raster failures: [gotchas](references/gotchas.md).
- Image feedback and stopping: [review](references/review.md).

Use arbitrary Figure/Axes/Artists; examples are editable starting points. Complete required figures before polishing details. Inspect the current whole image, crop only uncertain details, and fix observed displacement, occlusion, encoding or clipping defects together. Stop when no remaining defect changes task interpretation.
Deliver PNG/SVG/PDF and rerunnable code. For uncertain analytical results consult gis-verification; image appearance alone cannot establish data correctness.
