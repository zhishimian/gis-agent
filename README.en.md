<div align="center">

# 🌍 OpenGIS-Agent

**A Verifiable Geospatial Coding, Publication-Grade Cartography & Human-in-the-Loop Visual Agent**

[![Version](https://img.shields.io/badge/version-v9.1.0-1c60a6.svg)](pyproject.toml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)](pyproject.toml)
[![QGIS & GeoPandas](https://img.shields.io/badge/backends-GeoPandas%20%7C%20Rasterio%20%7C%20PyQGIS-589632.svg)](gis_agent/skills/gis-data-io-and-staging/SKILL.md)
[![Studio Desktop](https://img.shields.io/badge/Studio-React%20%2B%20MapLibre%20%2B%20Tauri-0ea5e9.svg)](CONTRIBUTION_AND_NEXT_STEPS.md)
[![MCP Ready](https://img.shields.io/badge/MCP-STDIO%20Server-0d585f.svg)](gis_agent/adapters/harness_mcp.py)

[简体中文](README.md) | **English**

[Cartography Showcase](#-cartography-showcase) • [Architecture](#-architecture) • [Quickstart & Setup](#-quickstart--setup) • [Roadmap & Contributing (中文详版)](CONTRIBUTION_AND_NEXT_STEPS.md)

</div>

---

## 🎨 Cartography Showcase

OpenGIS-Agent autonomously plans map projections, perceptual color ramps, layer z-ordering, and publication typography—delivering `300 dpi` figures alongside **editable `<text>` and semantic `<g id>` layered SVGs** ready for Illustrator / Inkscape / Figma refinement.

### 1. Publication Multi-Panel Scientific Composite
*Asymmetric 62/38 GridSpec composite in bundled SIL OFL `Source Serif 4` print typography linking seamless `0–800 in` snowfall surfaces (`build_perceptual_norm`), Amtrak exposure tiers with broken-line-free national border z-ordering, integer graticules, state rankings, and latitudinal exposure profiles (`5.90 MB` editable SVG).*

![CONUS Seasonal Snowfall and Amtrak Winter Exposure Scientific Composite](assets/showcase_conus_scientific_composite.png)

### 2. Standard Study-Area Locator Map
*Map-first research locator featuring uncolored-yet-bordered neighbor context, bundled SIL OFL `Source Serif 4` print typography, compact circular globe inset, centered framed legend, bespoke compass star + lower-zone cartographic scalebar, and integer 4-sided graticules (`8.51 MB` editable SVG).*

![Rondônia Study Area Locator Map](assets/showcase_rondonia_study_area.png)

---

## ✨ Architecture

OpenGIS-Agent follows a **"One Core, Three Rings, Multi-Endpoint"** decoupled architecture:
- **Ring 1 (Deterministic Geospatial Primitives & 7 Domain Skills)**: Zero-turn spatial vitals (`inspect_fast` for CRS, NoData, and empty-geometry triage), dual execution across standalone `uv` geospatial libraries (`GeoPandas`, `Rasterio`, `SciPy`, `Cartopy`, including a zero-extra-dependency Network Analysis 4-piece suite) or optional desktop `PyQGIS`, and composable publication cartography primitives with 5-point layout hygiene checks (`gis_agent/integrations/plotting/`).
- **Ring 2 (Headless State Machine & 9 Static Tools)**: Pure-Python `AgentLoopRunner` + SQLite checkpointing with `9` KV-cache-friendly static tool schemas (**96%+** cache hit rate), streaming `EventCallback`, spatial `WorkspaceContext`, and `< 0.2s` collaborative process-tree cancellation (`request_stop()`).
- **Ring 3 (Local Spatial Engine Server & OpenGIS Studio)**: A loopback **Python FastAPI + SSE** backend (`gis_agent/server/`) serving viewport-simplified vectors, `WarpedVRT` transparent raster previews, unified vector/raster `Identify`, and SVG layer inspection; paired with a **React 19 + TypeScript + MapLibre GL JS** frontend (`frontend/`) that runs identically in a local browser (`opengis studio`) or inside a thin **Tauri v2 (Rust `< 300` lines)** native desktop shell (`desktop/`).

---

## 🚀 Quickstart & Setup

### 1. Developer Setup from Source

Install Git, [uv](https://docs.astral.sh/uv/getting-started/installation/), and [Node.js](https://nodejs.org/) (with `pnpm`), then clone and initialize the branch:

```powershell
git clone https://github.com/zhishimian/OpenGIS-Agent.git
cd OpenGIS-Agent
git checkout feature/v9.1-studio

# 1) Sync Python core, CLI, standalone geospatial stack, and Studio server dependencies
uv sync --extra cli --extra geo --extra studio --extra dev

# 2) Install React + MapLibre frontend dependencies and sync the static build into gis_agent/server/static/
pnpm --dir frontend install
pnpm --dir frontend run build:sync
```

Launch in any of the 4 modes:

| Delivery Mode | Command | Use Case |
| :--- | :--- | :--- |
| **① Local Visual Workbench (`opengis studio`)** | `uv run --no-sync opengis studio --folder "path/to/data"` | Full two-pane browser workbench (MapLibre canvas, Identify, AOI/FID context chips, plan approval, figure red-box annotations) |
| **② Interactive CLI Terminal (`opengis`)** | `uv run --no-sync opengis --folder "path/to/data"` | Lightweight terminal chat, session management, and batch workflows |
| **③ STDIO MCP Server (`gis-agent-mcp`)** | `uv run --no-sync gis-agent-mcp --project "path/to/data"` | Mount Ring 1 tools & Skills in Claude Code / Codex / Cursor / Antigravity |
| **④ Build Standalone Desktop Installer (`.exe` / `.zip`)** | `pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_desktop.ps1` | Locally build `OpenGIS-Studio-9.1.0-x64-setup.exe` and portable `.zip` (requires Rust `1.90+`) |

> **Note on Binary Artifacts**: The packaged `.exe` installer (`~164 MB`) and portable `.zip` (`~258 MB`) embed a complete standalone Python 3.12 spatial runtime and are gitignored (`dist/`) to keep the repository lightweight. During active development, build them locally via `scripts/build_desktop.ps1` or run `opengis studio` directly.

### 2. Global CLI Install & Credentials

```powershell
uv tool install --python 3.12 ".[cli,geo,studio]"
uv tool update-shell
```

Run `opengis` or `opengis studio` inside any data folder. On first launch, API keys are stored securely in Windows Credential Manager, macOS Keychain, or Linux Secret Service (or configured via `.env` with `DEEPSEEK_API_KEY` and optional `GIS_AGENT_QGIS_DIR`).

![OpenGIS terminal with the pixel globe and sessions grouped under a workspace folder](assets/opengis-terminal.png)

---

## 🧭 Roadmap & Contributing

See **[CONTRIBUTION_AND_NEXT_STEPS.md](CONTRIBUTION_AND_NEXT_STEPS.md)** (detailed Chinese roadmap & contribution guide) for our next milestones across spatial analysis Skills, flow-map & high-density labeling cartography, AI-controlled visualization & figure critique loops, 5-endpoint delivery (including thin QGIS / ArcGIS Pro plugins), and GeoAgentBench evaluation.
