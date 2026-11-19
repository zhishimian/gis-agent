# Scientific cartographic color theory and palette atlas

Color on a publication map is a precision encoding channel, never arbitrary decoration. Choose palettes from perceptual lightness/chroma geometry rather than default rainbow ramps.

## Generalizable color principles

1. **60-30-10 luminance and chroma budget & surface-vs-marker contrast**:
   - **60% quiet canvas & context**: Background ocean/land (`#ffffff`, `#faf8f4`, `#f0f0f0`, `#e5e5e5`, `#e8f1f8`) at high lightness (`L*` 90-99) and near-zero chroma so the eye rests.
   - **30% core thematic surface**: Low-chroma (`C*` 20-45) editorial sequential/diverging ramps (`nordic_snow`, `slate_teal`, `muted_ochre`, `sage_forest`, `oslo`, `batlow`) conveying regional structure cleanly without oversaturation.
   - **10% high-salience focal markers**: Small overlaid focal points (`marker_mid` `#e8b44c`, `marker_high` `#d96f32`, `marker_extreme` `#9e2234`) MUST carry fine white edge halos (`edgecolor="#ffffff"`) so points pop softly off colored fills; secondary point tiers (e.g. auxiliary stations) recede with smaller markers and lower alpha (`0.35-0.45`).
2. **Perceptual uniformity, skewed normalization & continuous colorbar rule**:
   - **Continuous vs. discrete (>5 rule) & `build_perceptual_norm`**: Continuous rasters/fields MUST render via `add_continuous_colorbar`—reserve discrete swatch legends strictly for `<= 5` explicit classes. On right-skewed fields (snowfall, precipitation, emissions), pass `build_perceptual_norm(values)` alongside `nordic_snow`/`slate_teal`/`oslo` and paint exact `0` separately (`#f7f7f7`) so broad mid-range zones read in rich mid-tones instead of washing out pale.
   - **Ordered rates/magnitudes (`sequential`)**: Lightness `L*` MUST change monotonically (light = low on white canvas, or dark-to-light intentionally) so differences in value match perceived contrast.
   - **Signed changes/thresholds (`diverging`)**: Use symmetric ramps pivoting through a pale neutral center (`#f5f5f5`, `#f7f7f7`, `#ece9b4`) paired with explicit `TwoSlopeNorm(vmin, vcenter, vmax)`.
   - **Unordered categories (`qualitative`)**: Match hue separation rather than lightness order; cap at `<= 8` classes (aggregate long tails into `"Other"` `#cccccc` rather than introducing 15 rainbow hues).
   - **Coupled `(x, y)` layers (`bivariate`)**: Cross two orthogonal light-to-saturated hues from a shared neutral corner (`#e8e8e8` or `#f2efe9`) so top-right `(High, High)` reads as darkest/richest intersection.
3. **Zero, NoData, and out-of-scope isolation**:
   - Never collapse `0` into `NoData` or white canvas. Encode missing/masked pixels explicitly with `GEO_COLORS["nodata_gray"]` (`#d9d9d9`) + optional `///` hatch, keep valid zero distinct (`#f7f7f7` or sequence floor), and style excluded territories `#f0f0f0` with `0.35pt` `#b8b8b8` borders.
4. **CVD & grayscale safety + redundant encoding**:
   - Avoid pure red-green pairs (`#ff0000` vs `#00ff00`). Prefer Okabe-Ito, Crameri (`batlow`, `vik`, `roma`), Paul Tol (`tol_sunset`, `tol_muted`, `tol_iridescent`) or CARTOColors. Pair key distinctions with stroke weight, marker shape or hatching where print grayscale fidelity matters.
5. **Overplotting & stroke discipline**:
   - Dense points/tracks (`n > 1000`): reduce marker opacity (`alpha=0.22-0.45`) or aggregate into hex/grid counts. Dense administrative polygons: use hairline `#ffffff` or `#d0d0d0` edges (`0.25-0.45pt`) so borders never darken small units.
6. **Cross-panel color linkage**:
   - Composite figures MUST lock identical hex colors, `cmap` and `norm` bounds across main map, inset zoom, marginal longitude/latitude profiles, ranked bars and legends.
7. **Synthesizing custom domain ramps**:
   - When presets need domain tailoring (e.g., snow accumulation vs. burn scar vs. urban canopy): anchor light neutral `L*` ~92-95, hold hue within a <= 60 deg analogous arc (sequential) or opposite hue family through off-white (diverging), keep dark tip >= `L*` 20 so black borders stay legible, or call `build_bivariate_palette(c00, c10, c01, c11, n)` in `primitives.py`.

---

## Curated palette atlas (primitives.py)

All palettes below are built into `gis_agent.integrations.plotting.primitives` and degrade automatically to Matplotlib `LinearSegmentedColormap`/`ListedColormap` when optional packages are absent. Never pass `jet`, `rainbow`, `hsv`, `gist_rainbow`, `nipy_spectral`, `prism` or `flag`.

### Basemap and neutral figure-ground tokens (`GEO_COLORS`)

| Token | Hex | Recommended role |
| :--- | :--- | :--- |
| `land_muted` / `land_warm` | `#f0f0f0` / `#f3f1ec` | Out-of-scope landmass / warm editorial canvas land |
| `land_context` | `#e5e5e5` | Surrounding non-study states, continents or grey context |
| `ocean_soft` / `ocean_clean` | `#e8f1f8` / `#f4f8fb` | Soft pale-blue ocean, strait, or locator globe water |
| `water_accent` | `#7eb6d9` | Major focal rivers, lakes or coastal inlet channels |
| `border_muted` / `border_subtle` | `#b8b8b8` / `#d0d0d0` | `0.3-0.45pt` country boundaries / internal sub-unit hairlines |
| `border_study` | `#333333` | `0.9-1.2pt` focal study region outline |
| `nodata_gray` / `zero_neutral` | `#d9d9d9` / `#f7f7f7` | Missing observations (hatch `///`) vs. valid exact zero |
| `text_primary` / `text_secondary` | `#1f2328` / `#57606a` | Soft-ink titles/labels vs. graticule ticks & notes |
| `highlight_accent` / `highlight_gold` | `#d64541` / `#e6ab02` | Crisp focal callout / study-area inset rectangle |
| `marker_low` / `marker_mid` | `#e6e6e6` / `#e8b44c` | Minimal-impact / moderate focal point markers (pair with white edge) |
| `marker_high` / `marker_extreme` | `#d96f32` / `#9e2234` | High / extreme focal point markers (restrained wine-amber over muted fields) |

### Sequential palettes (`get_scientific_cmap("sequential", name)`)

| Name | Engine | Core stops (low -> high) | Best geographic domains |
| :--- | :--- | :--- | :--- |
| `batlow` | Crameri | `#011959` `#124761` `#2c665d` `#627941` `#a58b2c` `#e69858` `#fdb1ab` `#faccfa` | Default continuous geophysical/climate field (CVD-safe rainbow alternative) |
| `lajolla` | Crameri | `#191900` `#3c2614` `#783932` `#c04d49` `#e17750` `#eaa253` `#f5d369` `#fffecb` | Heatwave, LST, wildfire, drought exposure (use `_r` for light-low) |
| `oslo` | Crameri | `#010101` `#0f2133` `#194169` `#3364a1` `#6b8ec8` `#97a9c9` `#c7ccd3` `#ffffff` | Bathymetry, snow cover, precipitation (use `_r` on white canvas) |
| `lapaz` | Crameri | `#1a0c64` `#253681` `#305c98` `#487da3` `#7398a0` `#a5a795` `#e4c9b2` `#fef2f3` | Deep ocean to continental shelf / accessibility surfaces |
| `bilbao` | Crameri | `#4c0001` `#7d2e34` `#9d5754` `#a5745b` `#ad9061` `#bbb287` `#cbcac1` `#ffffff` | Aridity, soil erosion, desert dust, deforestation intensity (`_r` light-low) |
| `acton` | Crameri | `#260d40` `#443766` `#625c88` `#8e648e` `#c26b94` `#d995b8` `#e6c5de` `#f0eafa` | Urban density, population exposure, nightlights (`_r` light-low) |
| `hawaii` | Crameri | `#8c0273` `#933252` `#985638` `#9c7e20` `#94ae30` `#74ce79` `#61e6ca` `#b3f2fd` | Circular/gradient coastal biodiversity, species richness |
| `turku` | Crameri | `#000000` `#2c2c27` `#53523e` `#797750` `#af9c68` `#dba886` `#f9bfb7` `#ffe6e6` | Geological bedrock, ruggedness, warm grayscale print (`_r` light-low) |
| `carto_teal` | CARTO | `#d1eeea` `#a8dbd9` `#85c4c9` `#68abb8` `#4f90a6` `#3b738f` `#2a5674` | Freshwater storage, transit access, healthcare/socioeconomic choropleths |
| `carto_mint` | CARTO | `#e4f1e1` `#b4d9cc` `#89c0b6` `#63a6a0` `#448c8a` `#287274` `#0d585f` | Greening, NDVI, forest carbon, urban cooling patches |
| `carto_oryel` | CARTO | `#ecda9a` `#efc47e` `#f3ad6a` `#f7945d` `#f97b57` `#f66356` `#ee4d5a` | Solar potential, wildfire risk, per-capita emissions hotspots |
| `carto_peach` | CARTO | `#fde0c5` `#facba6` `#f8b58b` `#f59e72` `#f2855d` `#ef6a4c` `#eb4a40` | Heat stress, economic burden, disease incidence |
| `carto_burg` | CARTO | `#ffc6c4` `#f4a3a8` `#e38191` `#cc607d` `#ad466c` `#8b3058` `#672044` | Poverty rate, demographic vulnerability, mortality intensity |
| `carto_brwnyl` | CARTO | `#ede5cf` `#e0c2a2` `#d39c83` `#c1766f` `#a65461` `#813753` `#541f3f` | Soil organic carbon, cropland expansion, archaeological density |
| `carto_bluyl` | CARTO | `#f7feae` `#b7e6a5` `#7ccba2` `#46aea0` `#089099` `#00718b` `#045275` | Flood depth, runoff, wetland connectivity |
| `carto_emrld` | CARTO | `#d3f2a3` `#97e196` `#6cc08b` `#4c9b82` `#217a79` `#105965` `#074050` | Canopy height, ecological intactness, primary productivity |
| `carto_sunsetdark` | CARTO | `#fcde9c` `#faa476` `#f0746e` `#e34f6f` `#dc3977` `#b9257a` `#7c1d6f` | Extreme heat, CO2 intensity, seismic energy release |
| `tol_iridescent` | Paul Tol | `#fefbe9` `#ddecbf` `#a8d8dc` `#7eb2e4` `#9b8ac4` `#906388` `#46353a` | High-resolution smooth continuous gradients with linear `L*` |
| `hypsometric` | Carto relief | `#d8e6cf` `#e7ecd1` `#f3eac2` `#e4cfa0` `#cca97f` `#b68e74` `#d6cfc7` `#f5f5f5` | Regional DEM / watershed elevation backdrop under overlays |
| `bathymetry` | Marine | `#ebf5fb` `#c6e2f2` `#99cae6` `#6baddb` `#408bc9` `#2466a8` `#13427d` `#09244d` | Ocean depth, sea-level / tsunami travel-time marine contours |
| `nordic_snow` | Editorial | `#cfe1ef` `#a9c8e0` `#7fa6ca` `#5682ad` `#36648f` `#23507a` `#163a5b` `#0c2338` | Low-chroma ice-blue continuous snowfall, precip & glacier surfaces |
| `slate_teal` | Editorial | `#dceae8` `#b2d1ce` `#85b5b2` `#5c9593` `#3d7474` `#275658` `#163a3d` | Low-chroma moisture, groundwater, urban transit access surfaces |
| `muted_ochre` | Editorial | `#f2eadc` `#e0cca9` `#c8ab7c` `#ae8b57` `#8f6b3c` `#6e4f28` `#4d3519` | Editorial bare earth, erosion, aridity and dryland indices |
| `sage_forest` | Editorial | `#e5ece2` `#c3d5bc` `#9bbb93` `#739d6c` `#4f7e4b` `#335e32` `#1e4020` | Restrained forest canopy, green patches and parkland cover |

### Diverging palettes (`get_scientific_cmap("diverging", name)`)

| Name | Engine | Ends & center (`low -> center -> high`) | Best geographic anomalies |
| :--- | :--- | :--- | :--- |
| `vik` | Crameri | `#001261` `#4b90b3` -> `#e4ebf0`/`#ebd3c5` -> `#ca8258` `#590008` | Cold/warm temperature, sea-level or pressure anomalies |
| `roma` | Crameri | `#7e1700` `#be9d3e` -> `#d2de98`/`#9be2d5` -> `#46accc` `#033198` | Elevation-vs-depth, drought/wetness balance, Moran's I |
| `bam` | Crameri | `#65024b` `#da93c8` -> `#f3dded`/`#ebf1df` -> `#a3c67d` `#0d4c00` | Forest loss vs. greening gain (`dNDVI` / `dSAVI`) |
| `broc` | Crameri | `#2c1a4c` `#6f92b3` -> `#c4d2e0`/`#e4e4c8` -> `#aeae73` `#262600` | Residual errors, hydrology surplus/deficit |
| `cork` | Crameri | `#2c194c` `#688db0` -> `#c0cfde`/`#c8dbc8` -> `#71a071` `#0f2903` | Vegetation-moisture anomaly, land-use transition net balance |
| `tol_sunset` | Paul Tol | `#364b9a` `#6ea6cd` -> `#eaeccc` -> `#fdb366` `#a50026` | Heat island delta, emissions per-capita divergence, Z-scores |
| `tol_burd` | Paul Tol | `#2166ac` `#92c5de` -> `#f7f7f7` -> `#f4a582` `#b2182b` | Sharp cooling vs. warming anomaly with bright neutral zero |
| `carto_geyser` | CARTO | `#008080` `#b4c8a8` -> `#f6edbd` -> `#de8a5a` `#ca562c` | Soft editorial wet/dry or ecological gain/stress divergence |
| `carto_armyrose` | CARTO | `#798234` `#d0d3a2` -> `#fdfbe4` -> `#df91a3` `#d46780` | Low-glare urban density change or policy comparison |
| `carto_tealrose` | CARTO | `#009392` `#b1c7b3` -> `#f1eac8` -> `#d98994` `#d0587e` | Urban growth vs. decline, demographic migration flow |
| `carto_earth` | CARTO | `#a16928` `#d6bd8d` -> `#edeac2` -> `#79a7ac` `#2887a1` | Soil moisture / watershed aridity vs. humidity balance |
| `carto_temps` | CARTO | `#009392` `#9ccb86` -> `#e9e29c` -> `#e88471` `#cf597e` | Temperature sensitivity, crop yield anomalies |

### Qualitative and journal palettes (`get_palette(name, n=...)`)

| Name | Colors | Exact hex list |
| :--- | :--- | :--- |
| `okabe_ito` | 8 | `#0072B2`, `#D55E00`, `#009E73`, `#CC79A7`, `#E69F00`, `#56B4E9`, `#F0E442`, `#000000` |
| `tol_muted` | 9 | `#332288`, `#88CCEE`, `#44AA99`, `#117733`, `#999933`, `#DDCC77`, `#CC6677`, `#882255`, `#AA4499` |
| `tol_bright` | 7 | `#4477AA`, `#EE6677`, `#228833`, `#CCBB44`, `#66CCEE`, `#AA3377`, `#BBBBBB` |
| `npg` (*Nature*) | 10 | `#E64B35`, `#4DBBD5`, `#00A087`, `#3C5488`, `#F39B7F`, `#8491B4`, `#91D1C2`, `#DC0000`, `#7E6148`, `#B09C85` |
| `lancet` | 9 | `#00468B`, `#ED0000`, `#42B540`, `#0099B4`, `#925E9F`, `#FDAF91`, `#AD002A`, `#ADB6B6`, `#1B1919` |
| `aaas` (*Science*) | 10 | `#3B4992`, `#EE0000`, `#008B45`, `#631879`, `#008280`, `#BB0021`, `#5F559B`, `#A20056`, `#808180`, `#1B1919` |
| `jco` | 10 | `#0073C2`, `#EFC000`, `#868686`, `#CD534C`, `#7AA6DC`, `#003C67`, `#8F7700`, `#3B3B3B`, `#A73030`, `#4A6990` |
| `carto_safe` | 11 | `#88CCEE`, `#CC6677`, `#DDCC77`, `#117733`, `#332288`, `#AA4499`, `#44AA99`, `#999933`, `#661100`, `#6699CC`, `#888888` |
| `carto_prism` | 12 | `#5F4690`, `#1D6996`, `#38A6A5`, `#0F8554`, `#73AF48`, `#EDAD08`, `#E17C05`, `#CC503E`, `#94346E`, `#6F4070`, `#994E95`, `#666666` |
| `morandi_geo` | 8 | `#6B8E8E`, `#C89B7B`, `#8FA3B8`, `#D4B483`, `#A4849C`, `#7D9B76`, `#B87A7A`, `#9E9A90` |
| `landcover_soft` | 7 | `#4D8C57`, `#A3C585`, `#DFC98A`, `#C77A62`, `#6CA6CD`, `#8B7D7B`, `#D9D9D9` |

### Bivariate corner matrices (`get_bivariate_palette(name)`)

Matrix indexing convention: `matrix[y_bin][x_bin]`, where `row 0` is low Y, `col 0` is low X, and `(y_bin=n-1, x_bin=n-1)` is the `(High, High)` convergence corner. Use `build_bivariate_palette(c00, c10, c01, c11, n)` to generate any `2x2` to `9x9` variant.

- `stevens_pinkblue` (3x3):
  - Row 0 (low Y): `#e8e8e8`, `#ace4e4`, `#5ac8c8`
  - Row 1 (mid Y): `#dfb0d6`, `#a5add3`, `#5698b9`
  - Row 2 (high Y): `#be64ac`, `#8c62aa`, `#3b4994`
- `stevens_bluered` (3x3):
  - Row 0: `#e8e8e8`, `#e4acac`, `#c85a5a` | Row 1: `#b0d5df`, `#ad9ea5`, `#985356` | Row 2: `#64acbe`, `#627f8c`, `#574249`
- `stevens_greenblue` (3x3):
  - Row 0: `#e8e8e8`, `#b5c0da`, `#6c83b5` | Row 1: `#b8d6be`, `#90b2b3`, `#567994` | Row 2: `#73ae80`, `#5a9178`, `#2a5a5b`
- `stevens_purplegold` (3x3):
  - Row 0: `#e8e8e8`, `#e4d9ac`, `#c8b35a` | Row 1: `#cbb8d7`, `#c8ada0`, `#af8e53` | Row 2: `#9972af`, `#976b82`, `#804d36`
- `teal_terracotta` (3x3, warm editorial paper):
  - Row 0: `#f2efe9`, `#a3d3cf`, `#2b8b8c` | Row 1: `#eab8a3`, `#9b9d9c`, `#2d6d78` | Row 2: `#d6684f`, `#8a5a54`, `#3b3746`
- `bivariate_5x5_ocean_amber` (5x5): Bilinear blend from `#f2f2f2` (`0,0`) to `#1e78b4` (`X` max), `#e66101` (`Y` max), `#2b1c47` (`High, High`).
