<div align="center">

# 🌍 OpenGIS-Agent

**A Verifiable Geospatial Coding & Publication-Grade Cartography Agent**

[![Version](https://img.shields.io/badge/version-v9.0.5-1c60a6.svg)](pyproject.toml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)](pyproject.toml)
[![QGIS & GeoPandas](https://img.shields.io/badge/backends-GeoPandas%20%7C%20Rasterio%20%7C%20PyQGIS-589632.svg)](gis_agent/skills/gis-data-io-and-staging/SKILL.md)
[![MCP Ready](https://img.shields.io/badge/MCP-STDIO%20Server-0d585f.svg)](gis_agent/adapters/harness_mcp.py)

[简体中文](README.md) | **English**

[Cartography Showcase](#-cartography-showcase) • [Architecture](#-architecture) • [Quickstart](#-quickstart) • [Roadmap & Contributing](CONTRIBUTION_AND_NEXT_STEPS.md)

</div>

---

## 🎨 Cartography Showcase

OpenGIS-Agent autonomously plans map projections, perceptual color ramps, layer z-ordering, and publication typography—delivering `300 dpi` figures alongside **editable `<text>` layered SVGs** ready for Illustrator / Inkscape / Figma refinement.

### 1. Publication Multi-Panel Scientific Composite
*Asymmetric 62/38 GridSpec composite in bundled SIL OFL `Source Serif 4` print typography linking seamless `0–800 in` snowfall surfaces (`build_perceptual_norm`), Amtrak exposure tiers with broken-line-free national border z-ordering, integer graticules, state rankings, and latitudinal exposure profiles (`5.90 MB` editable SVG).*

![CONUS Seasonal Snowfall and Amtrak Winter Exposure Scientific Composite](assets/showcase_conus_scientific_composite.png)

### 2. Standard Study-Area Locator Map
*Map-first research locator featuring uncolored-yet-bordered neighbor context, bundled SIL OFL `Source Serif 4` print typography, compact circular globe inset, centered framed legend, bespoke compass star + lower-zone cartographic scalebar, and integer 4-sided graticules (`8.51 MB` editable SVG).*

![Rondônia Study Area Locator Map](assets/showcase_rondonia_study_area.png)

---

## ✨ Architecture

Rather than wrapping GIS software into hundreds of brittle JSON endpoints, OpenGIS-Agent runs a lightweight pure-Python state machine (`AgentLoopRunner` + SQLite checkpointing) with `9` KV-cache-friendly static tool schemas and `7` modular geospatial Skills (`gis_agent/skills/`). Every newly generated vector or raster artifact triggers zero-turn objective inspection (`inspect_fast` for CRS, NoData, and empty-geometry triage), executes seamlessly across standalone `uv` geospatial libraries (`GeoPandas`, `Rasterio`, `SciPy`, `Cartopy`) or optional desktop `PyQGIS`, and composes publication maps backed by automated layout and typography hygiene checks (`gis_agent/integrations/plotting/`).

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
# Optional: enable desktop QGIS / PyQGIS processing algorithms
# GIS_AGENT_QGIS_DIR=E:/exe/qgis
```

### 3. Run OpenGIS-Agent

```powershell
# Interactive CLI (supports session resume, status inspection & history audit)
uv run python main.py --session my-gis-task

# Standard STDIO MCP Server (for Claude Code / Codex / Cursor / Antigravity)
uv run gis-agent-mcp
```

---

## 🧭 Roadmap & Contributing

Contributions across domain Skills, cartographic primitives, QGIS / Desktop UI plugins, and open GeoAI benchmarks are welcome—see **[CONTRIBUTION_AND_NEXT_STEPS.md](CONTRIBUTION_AND_NEXT_STEPS.md)** for the full roadmap and guide.
