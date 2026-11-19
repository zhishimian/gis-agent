<div align="center">

# 🌍 OpenGIS-Agent

**A Verifiable Geospatial Coding & Publication-Grade Cartography Agent**

[![Version](https://img.shields.io/badge/version-v9.0.5-1c60a6.svg)](pyproject.toml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)](pyproject.toml)
[![uv](https://img.shields.io/badge/env-uv%20managed-de5fe9.svg)](https://docs.astral.sh/uv/)
[![QGIS & GeoPandas](https://img.shields.io/badge/backends-GeoPandas%20%7C%20Rasterio%20%7C%20PyQGIS-589632.svg)](gis_agent/skills/gis-data-io-and-staging/SKILL.md)
[![MCP Ready](https://img.shields.io/badge/MCP-STDIO%20Server-0d585f.svg)](gis_agent/adapters/harness_mcp.py)
[![Bundled Fonts](https://img.shields.io/badge/fonts-Source%20Serif%204%20%2B%20LXGW%20WenKai%20Lite%20(OFL)-8f6b3c.svg)](gis_agent/integrations/plotting/fonts/OFL-LICENSE.txt)

*Built as a lightweight, framework-free spatial Code Agent with static KV-cache-friendly tool schemas, zero-turn objective spatial vitals, dual-environment (standalone Python + PyQGIS) graceful fallback, and editable publication cartography.*

[Showcase Gallery](#-cartography-showcase) • [Architecture](#-core-architecture) • [Cartography Engine](#-publication-cartography-engine) • [Quickstart](#-quickstart) • [Roadmap & Contributing](CONTRIBUTION_AND_NEXT_STEPS.md)

</div>

---

## 🎨 Cartography Showcase

OpenGIS-Agent autonomously plans visual hierarchy, projection selection, skewed perceptual normalization, layer z-ordering, and non-overlapping typography—delivering both **multi-panel scientific composites** and **clean study-area locator maps** as `300 dpi` PNGs alongside **editable `<text>` layered SVGs** for Illustrator / Inkscape / Figma refinement.

### 1. Publication Multi-Panel Scientific Composite
*Asymmetric 62/38 GridSpec composite linking spatial snowfall surfaces (`nordic_snow` + `build_perceptual_norm`), Amtrak exposure tiers with broken-line-free national border z-ordering, continuous gradient legend, state rankings, and latitudinal exposure profiles (`6.51 MB` editable SVG).*

![CONUS Seasonal Snowfall and Amtrak Winter Exposure Scientific Composite](assets/showcase_conus_scientific_composite.png)

### 2. Standard Study-Area Locator Map
*Map-first research locator featuring uncolored-yet-bordered neighbor context, bundled SIL OFL `Source Serif 4` print typography, compact circular globe inset, bespoke compass star + lower-zone cartographic scalebar, and crisp 4-sided DMS coordinates (`8.14 MB` editable SVG).*

![Rondônia Study Area Locator Map](assets/showcase_rondonia_study_area.png)

---

## ✨ Core Architecture

OpenGIS-Agent avoids brittle 100-tool JSON wrappers and heavy orchestration frameworks. Instead, a **pure-Python state machine** (`AgentLoopRunner` + SQLite checkpointing in `gis_agent/persistence/`) pairs open-ended Python spatial scripting with a **compact static tool surface** (`9` cache-friendly schemas) and **seven modular domain Skills**:

- **Static KV-Cache-Friendly Protocols**: Fixed top-level tool schemas keep multi-turn prompt prefixes cached across long analytical & cartographic workflows (`search_qgis_tools`, `run_qgis_algorithm`, `run_python_script`, `inspect_data`, `summarize_fields`, `check_spatial_relation`, `read_image`, etc.).
- **Zero-Turn Objective Spatial Vitals (`inspect_fast`)**: Newly created vector and raster files automatically emit objective metadata (CRS units, feature/pixel dimensions, `dtype`, `nodata`, valid ratio, value extrema, and sample invalid geometries) plus tiered `notice` / `warning` / `fatal` anomaly signals—catching silent `-9999` leaks, empty outputs, and projection mismatches on the exact turn they occur.
- **Dual-Environment Spatial Execution (`runtime_capabilities`)**: Runs out-of-the-box in a standalone `uv` environment (`GeoPandas`, `Rasterio`, `PyOGRIO`, `SciPy`, `NetworkX`, `DuckDB`, `PyKrige`, `libpysal`, `esda`, `Cartopy`) and seamlessly detects optional desktop QGIS Processing / PyQGIS (`GIS_AGENT_QGIS_DIR`), falling back cleanly between Tier-B libraries and pure NumPy/SciPy/Matplotlib Tier-A implementations.
- **Process-Isolated Execution & Verification Gate**: Windows/POSIX subprocess isolation with timeout tree cleanup, cross-platform atomic JSON writes, `needs_input` / `blocked` honest abstention checkpoints, and reproducible invariant checks.

### Seven Modular Geospatial Skills (`gis_agent/skills/`)

| Skill | Domain Scope | Spec |
| :--- | :--- | :--- |
| **`gis-data-io-and-staging`** | Multi-layer GPKG/GDB/Parquet/GeoTIFF I/O, `pyogrio`/DuckDB pushdown, resumable staged artifacts | [SKILL.md](gis_agent/skills/gis-data-io-and-staging/SKILL.md) |
| **`gis-vector-and-network`** | Source/analysis/delivery CRS separation, spatial join key audits, tile-halo chunking, directed road routing | [SKILL.md](gis_agent/skills/gis-vector-and-network/SKILL.md) |
| **`gis-raster-and-imagery`** | Radiometric DN vs. reflectance scaling, `WarpedVRT` grid alignment, windowed streaming, NetCDF/HDF | [SKILL.md](gis_agent/skills/gis-raster-and-imagery/SKILL.md) |
| **`gis-terrain-and-hydrology`** | Bare-earth DEM vs. DSM separation, sink conditioning, D8 flow routing, catchment & flood volume checks | [SKILL.md](gis_agent/skills/gis-terrain-and-hydrology/SKILL.md) |
| **`gis-spatial-statistics`** | Moran's I / LISA, spatial weights, Ordinary Kriging / IDW, spatial block CV (`esda`/`pykrige` or SciPy) | [SKILL.md](gis_agent/skills/gis-spatial-statistics/SKILL.md) |
| **`gis-verification`** | Metamorphic & conservation checks, boundary counterexamples, anomaly triage, honest abstention | [SKILL.md](gis_agent/skills/gis-verification/SKILL.md) |
| **`gis-cartography`** | Composable primitives, scientific palettes, typography ladder, layout/hygiene QA, layered SVG export | [SKILL.md](gis_agent/skills/gis-cartography/SKILL.md) |

---

## 🗺 Publication Cartography Engine

Located in [`gis_agent/integrations/plotting/`](gis_agent/integrations/plotting/):

- **Composable Map Primitives ([`primitives.py`](gis_agent/integrations/plotting/primitives.py))**:
  - `apply_publication_theme`: 4-tier even-integer font ladder (`10 / 12 / 14 / 16 pt`, scaled proportionally to figure width) paired with bundled SIL OFL 1.1 [`Source Serif 4` + `LXGW WenKai Lite`](gis_agent/integrations/plotting/fonts/OFL-LICENSE.txt) (`font_style="serif"` / `"kaiti"` / `"fangsong"` / `"sans"`).
  - Curated Scientific Palettes & Perceptual Normalization: Crameri (`batlow`, `vik`, `roma`, `lajolla`, `oslo`), CARTOColors, Paul Tol, Okabe–Ito, editorial muted ramps (`nordic_snow`, `slate_teal`, `muted_ochre`, `sage_forest`), bivariate matrices (`build_bivariate_palette`, `bivariate_classify`), explicit rainbow/jet bans (`BANNED_CMAPS`), and skewed-distribution `build_perceptual_norm`.
  - Modular Chrome & Containers: `add_continuous_colorbar` (with isolated `0` / hatched `NoData` swatches), `add_clean_legend`, `add_bivariate_legend`, `add_graticule_frame` (4-sided DMS ticks replacing raw projected meters), `add_scalebar_and_north` (segmented/ticked lower-zone scalebar + 8-facet compass star / sleek needle), `add_locator_inset` (`"circle"` or `"rect"`), `add_leader_callouts` (halo-only `adjustText`), `find_quiet_corner`, and `attach_marginal_profiles`.
- **Automated Quality & Hygiene Diagnostics ([`runtime.py`](gis_agent/integrations/plotting/runtime.py))**:
  - `export_figure(..., formats=("png", "svg"))` embeds `svg.fonttype="none"` (true editable `<text>` nodes + semantic `gid` layer groups) and attaches quantitative self-audit checks: `margin_whitespace_ratio`, `typography` (even-tier & minimum legibility floor checks), and `hygiene` (`subtitle_detected_warning`, `callout_box_warning`, `duplicate_axis_ticks_warning`, `clipped_text_warning`, `frame_overflow_warning`).

---

## 🚀 Quickstart

### 1. Install with `uv`

```powershell
# Minimal core + CLI + test runner
uv sync --extra cli --extra dev

# Standalone full geospatial analysis & publication cartography stack (no desktop QGIS required)
uv sync --extra cli --extra dev --extra geo
```

### 2. Configure `.env`

Create `.env` in the repository root:

```env
DEEPSEEK_API_KEY=your_api_key_here
# Optional: enable desktop PyQGIS / Processing algorithms alongside standalone Python
# GIS_AGENT_QGIS_DIR=E:/exe/qgis
```

### 3. Run OpenGIS-Agent

Three adapter entrypoints live in [`gis_agent/adapters/`](gis_agent/adapters/):

```powershell
# Interactive CLI session (supports resume, waiting inspection & history audit)
uv run python main.py --session my-gis-task
uv run gis-agent waiting --session my-gis-task
uv run gis-agent history --session my-gis-task

# Standard STDIO MCP Server for Claude Code / Codex / Cursor / Antigravity
uv run gis-agent-mcp
# or: python -m gis_agent.adapters.harness_mcp
```

Frontend & QGIS plugin integration contracts (`FrontendBridge`, `WorkspaceContext`, event streaming, and thread-safe cancellation) are exposed via [`gis_agent/adapters/stubs.py`](gis_agent/adapters/stubs.py).

---

## 🧪 Verification & Benchmarks

All core tools, spatial skills, cartographic primitives, and benchmark runners are covered by offline pytest suites (`benchmarks/geoagentbench/` houses the isolated blind evaluation harness):

```powershell
# Fast offline unit & benchmark-runner tests (seconds)
uv run pytest tests/ -m "not slow and not live" -q
uv run pytest benchmarks/geoagentbench/test_runner.py -q

# Full non-live suite (includes heavy spatial & real desktop QGIS checks when configured)
uv run pytest tests/ -k "not live" -q
```

---

## 🧭 Roadmap & Contributing

We welcome contributions across spatial Skills, cartographic primitives, QGIS / Desktop UI plugins, and open GeoAI evaluation benchmarks! See **[CONTRIBUTION_AND_NEXT_STEPS.md](CONTRIBUTION_AND_NEXT_STEPS.md)** for the full three-track roadmap and contributor guide.
