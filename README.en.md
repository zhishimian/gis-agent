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

Run `opengis` in a data folder to inspect layers, analyze spatial data, and draw maps using natural language. Each folder keeps its own sessions and outputs.

![OpenGIS terminal with the pixel globe and sessions grouped under a workspace folder](assets/opengis-terminal.png)

## 🚀 Quickstart

### Install and launch

Install Git and [uv](https://docs.astral.sh/uv/getting-started/installation/), then run these commands in Windows PowerShell or a macOS terminal.

```sh
git clone https://github.com/zhishimian/OpenGIS-Agent.git
cd OpenGIS-Agent
uv tool install --python 3.12 ".[cli,geo]"
uv tool update-shell
```

Reopen your terminal, go to your data folder, and run `opengis`. On first launch, the terminal displays the model and API host and prompts for a masked API key. The default provider is DeepSeek. Press Enter to skip and use `/key` to connect later.

Keys are scoped to the provider and endpoint and stored in macOS Keychain, Windows Credential Manager, or Linux Secret Service. Other folders can reuse the same credentials. If the system store is unavailable, the key lasts for the current process. Automation can also read credentials from environment variables or a workspace `.env` file.

### Try a task

Type this at the `❯` prompt to try the agent without any data files.

> Calculate the great-circle distance from Shanghai (31.23° N, 121.47° E) to Beijing (39.90° N, 116.40° E). Give the answer in kilometers.

For your own data, use paths relative to the workspace. For example, ask the agent to read `schools.geojson`, report its CRS and feature count, label each point by its `name` field, and export a PNG map.

### Manage workspaces and sessions

| Where | Command | Purpose |
| --- | --- | --- |
| Terminal | `opengis --folder "../City analysis"` | Open a specific data folder |
| Agent | `/new schools` | Create a named session in this folder |
| Agent | `/resume` or `/resume schools` | List this folder’s sessions or continue one by name |
| Agent | `/status` | Show the model, workspace path, and output directory |
| Agent | `/help`, `/exit` | List shortcuts or exit |

Sessions default to `sessions/` and results to `outputs/<session>/` inside the workspace. Different folders can reuse the same session name.

### Develop from source

```sh
uv sync --extra cli --extra geo --extra dev
uv run --no-sync opengis
```

External clients can launch `gis-agent-mcp` as a STDIO MCP server. From the checkout, use `uv run --no-sync gis-agent-mcp`.

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

## 🧭 Roadmap & Contributing

Contributions across domain Skills, cartographic primitives, QGIS / Desktop UI plugins, and open GeoAI benchmarks are welcome—see **[CONTRIBUTION_AND_NEXT_STEPS.md](CONTRIBUTION_AND_NEXT_STEPS.md)** for the full roadmap and guide.
