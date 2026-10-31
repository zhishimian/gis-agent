# Task-dependent visual decisions

| Situation | Decision and library controls | Check |
| --- | --- | --- |
| Rate, total or category | Choropleth for justified rates/densities; area-proportional markers for totals; stable categorical colors. | Field meaning, denominator and units. |
| Continuous data needs classes | Compare task thresholds and the distribution; use BoundaryNorm and class counts. | Range endpoints, missing/empty classes and outliers. |
| Magnitude, signed difference or missing data | Sequential cmap for ordered magnitude; TwoSlopeNorm only with a meaningful center; separate missing symbol. | Zero and missing stay distinct. |
| Competing background | Explicit zorder, alpha and linewidth preserve the subject. | Points/roads remain visible above filled areas. |
| Dense points | Point area, edges and a useful inset help discrimination. | Required objects remain represented; small areas are legible. |
| Crowded labels | Select necessary names; use annotate, fontsize and modest halos. | Collision, clipping and obscured geography. |
| Legend or colorbar | Derive Patch/Line2D/ScalarMappable from the actual mapping. | Categories, units and interval labels agree. |
| Limited page area | Let extent and information needs determine figsize/GridSpec. | Final output size and reading order. |
| Overview plus detail | Use inset axes and a locator; share encoding when comparable. | Location and scale relationship are clear. |
| Multiple times/products | Share needed CRS, extent, norm and category mapping. | Differences reflect data; disclose independent stretching. |

Use professional references as decisions, not copied layouts. [NPS park maps](https://www.nps.gov/maps/web/tools/park-tiles/index.html) prioritize visitor destinations over quiet roads/buildings. Retain the facilities and labels the user's question needs. [Dynamic World comparisons](https://www.nature.com/articles/s41597-022-01307-4/figures/8) use consistent category colors and comparable panels; dates, resolutions and class definitions still need alignment. [ColorBrewer](https://colorbrewer2.org/) helps choose semantic palettes and test class counts; it cannot choose a business threshold.

A reference image can inform hierarchy and spacing. Match the current task's scale, reader and data first. Use map elements only when useful. Put formulas, CRS/method details and diagnostics outside the figure unless the task needs them on the map. Avoid a main title plus redundant panel titles and stacked subtitles. In dense areas, select or move labels, use a useful inset or a modest halo, and check the image: a higher text zorder can hide the points or links underneath it.
