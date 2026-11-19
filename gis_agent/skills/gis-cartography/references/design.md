# Spatial composition, typography scale and design decisions

Apply cartographic architecture intentionally: keep everyday maps clean and map-first, align every element to a strict grid, and size text so every word reads crisply even in compressed screenshots.

## 1. Even-integer 4-tier typography & font pairing

Never mix 6+ arbitrary fractional font sizes (e.g., `6.1 / 6.6 / 7.3 pt`) on giant `> 12 in` sheets. Keep the figure compact (`7.5-9.5 in` wide) or scale proportionally via `apply_publication_theme(..., fig_width=...)`, using **at most 4 even-integer tiers** from one cohesive font stack:

| Tier | Role | Ratio to figure height | Baseline on `~8.5 in` sheet | Rules |
| :--- | :--- | :---: | :---: | :--- |
| **T1** | Main map title (optional; omit on locator maps) | `3.8-4.8%` | `16 pt` Bold | Single concise phrase only; NEVER add a second subtitle line |
| **T2** | Panel tag `(a)`, legend title, major place name | `2.8-3.5%` | `14 pt` Bold | Clear focal anchor; at most 1-2 anchor sizes |
| **T3** | Legend items, axis labels, callout names | `2.3-2.8%` | `12 pt` Regular | Italicize hydrography/straits cleanly |
| **T4** | DMS graticule ticks, scalebar numbers | `1.8-2.3%` | `10 pt` Regular | **Hard floor `>= 10 pt` and `>= 1.7%` of height** |

- **`font_style="serif"`** (default `Source Serif 4` + `Times New Roman` + `STSong`/`SimSun` + bundled `LXGW WenKai Lite`) & **`font_style="kaiti"`** (`Source Serif 4` + `LXGW WenKai Lite` + `STKaiti`/`KaiTi`, plus `"fangsong"`): Recommended bundled open-source atlas typography preventing fallback to sans-serif.
- **`font_style="sans"`** (`Segoe UI` + `Microsoft YaHei` + `LXGW WenKai Lite` fallback): Optional contemporary UI/screen style when minimal sans-serif presentation is explicitly desired.

## 2. Text economy, layer order & canvas budgets

- **Zero subtitles, no unrequested insets & keep text off map geography**: NEVER place a stacked smaller/lighter subtitle beneath a title (and omit in-canvas titles cleanly on locator maps if appropriate). Do NOT invent extra statistical charts OR unrequested regional zoom panels unless asked; keep standalone thematic maps to ONE crisp `~8.5-9.0 in` map frame. Avoid cluttering mapped thematic land with explanatory prose or dense labels—put legends, colorbars and titles cleanly outside the map frame or in unoccupied ocean/border margins. Match prompt language, keep legend headers strictly `Variable (unit)`, and keep total non-tick words `<= 25-35`.
- **Lower-zone scalebar & quiet-corner chrome**: Always place scalebars in the **lower zone** (`lower left`, `lower right`, or `lower center` over ocean/quiet margin—never upper corners over land), pair with `find_quiet_corner` + `add_scalebar_and_north(..., scale_style="cartographic", north_style="compass_star")`, and keep all elements strictly inside border spines (`frame_overflow_warning == False`).
- **Canvas area budgets**:
  - Standard single map / study-area locator: **75-85%** primary map geography, **10-18%** inset/legend/scalebar, **<= 12%** total text footprint.
  - Requested composite figure: **58-65%** focal map, **35-42%** aligned statistical companion panels.
- **Strict layer `zorder` & stroke-weight discipline**: Background land/ocean (`0-1`) -> thematic raster/choropleth (`2`) -> lakes/hydro (`3`, `0.4-0.6pt`) -> internal sub-unit borders (`4`, `0.3-0.45pt` `#b8b8b8`) -> overlaid subject points/roads (`5-6`, modest `s=12-20` with `edgecolor="white"`) -> **primary national / study-area boundary (`8`, `1.0-1.2pt` `#2b3440`, ABOVE dots so boundaries stay crisp and continuous)** -> callouts & chrome (`10+`).
- **Projection choice**: Global `EqualEarth` / `Robinson` (no Web Mercator polar blowup); regional equal-area `AlbersEqualArea` (`EPSG:5070` CONUS) / national Lambert/LAEA; local engineering `UTM`.

## 3. Five composable cartographic archetypes (Intent-driven)

1. **Standard Study-Area / Multi-Scale Locator Map (Default)**: Crisp 4-sided DMS ticks (`add_graticule_frame`, zero metric tick overlap), **mandatory surrounding non-study states/countries on `ax_main` (`#efeeea` fill + `#c4c0b8` muted borders—never float the study area on blank white)**, clear layered thematic fills/lines (`zorder`), concise single-language noun legend outside/below the locator, lower-zone cartographic scalebar + compass-star north arrow, and a **compact country/neighbor-cropped circular or rectangular locator (`add_locator_inset(..., shape="circle" or compact rect)` centered on host country with a clean dashed focus rectangle; do NOT draw cross-axes connector lines)**.
2. **Clean Standalone Thematic Map (Default)**: Single `~8.5-9.0 in` focal map (NO unrequested zoom insets) pairing `nordic_snow`/`slate_teal`/`batlow` + `build_perceptual_norm(values)` + isolated `0`/`NoData` `#d9d9d9` via `add_continuous_colorbar`, modest white-haloed thematic points (`zorder` BELOW national boundary `8`), minimal callouts placed off the thematic landmass into empty ocean/outer margins (`add_leader_callouts`, NO white `bbox` cards), and lower-zone quiet-ocean `cartographic` scalebar + `compass_star`.
3. **Global / Regional Map + Ocean-Whitespace Micro-Legend**: Uses natural ocean space (South Pacific / Gulf) for borderless legend or bivariate square so exterior margins remain `<= 12%`.
4. **Map + Aligned Marginal Profiles** *(only when spatial gradients are requested)*: `attach_marginal_profiles(fig, ratio=0.19, pad=0.03)` sharing exact `xlim`/`ylim` and category hues.
5. **Asymmetric 60/40 Multi-Scale or Ranked Composite** *(only when multi-panel comparison/ranking is requested)*: Focal map left + color-linked horizontal rank bars or shared-norm small multiples right on unified `GridSpec`.

## 4. Task-dependent encoding rules

For requested Fisher-Jenks classification, use [shared classification encoding](api.md#fisher-jenks); class labels, color counts, class counts and legend intervals must agree without silent log/quantile swaps.

| Situation | Decision and library controls | Check |
| :--- | :--- | :--- |
| Rate, total or category | Choropleth for rates/densities; proportional markers for totals; stable qualitative hues. | Denominator, normalization and units. |
| Continuous field vs. classes | Default to `add_continuous_colorbar`; discrete `BoundaryNorm` swatches ONLY for `<= 5` explicit classes. | No `>5`-box segmented strips for continuous surfaces. |
| Zero vs. missing vs. signed delta | Sequential cmap for magnitude; `TwoSlopeNorm` for anomalies; isolate `NoData` (`#d9d9d9`, hatch). | Zero (`#f7f7f7`) never merges with water/NoData. |
| Surface + point overlay | Keep surface low-chroma; keep focal points compact with `edgecolor="white"` halos; mute auxiliary points. | Dense point clusters remain legible without blobbing. |
| Callouts & chrome placement | Locate via `find_quiet_corner`; draw callouts via `add_leader_callouts` (halo-only, NO white `bbox` cards). | Zero overlap, zero pills covering thematic cells, zero clipping. |
| Dense vectors (> 5,000 rows) | Never plot row-by-row (`itertuples`); simplify large polygon/line sets and use `rasterized=True` where needed. | Script runs `<= 15 s`, SVG `<= 8 MB`, leaving QA time. |

Deliver final figures as high-resolution PNG plus editable layered SVG (`svg.fonttype="none"`, `rasterized=True` on heavy rasters, semantic `gid` layers) so human editors can refine text/placement effortlessly.
