# Contributing & Roadmap (`CONTRIBUTION_AND_NEXT_STEPS.md`)

Thank you for checking out **OpenGIS-Agent**! Whether you are a GIS analyst, cartographer, PyQGIS developer, or AI-agent researcher, this document outlines our **three strategic next-step directions** and how to contribute cleanly.

---

## Roadmap: Next Steps (3 Strategic Directions)

### 1. Three-Endpoint Delivery & Visual Spatial Canvas
Right now, OpenGIS-Agent delivers a fast CLI (`cli.py`), a zero-dependency STDIO MCP server (`gis-agent-mcp` for Claude Code / Codex / Cursor), and frontend bridge contracts (`gis_agent/adapters/stubs.py`). Next, we want to bring **interactive spatial feedback** directly to human analysts without rebuilding bloated GIS menus:
- **Zero-Config QGIS Dockable Plugin (`< 500 KB`)**: A pure-Python PyQt dockable panel inside desktop QGIS that streams `EventCallback` progress, auto-mounts intermediate vector/raster outputs into `QgsProject`, and injects the user's current active layers, selected feature IDs, or viewport extent (`WorkspaceContext`) straight into the conversation.
- **Standalone Desktop Studio (`OpenGIS-Agent Studio`)**: A minimal two-pane workspace (~30% chat + stage cards / ~70% dual-view MapLibre + Figure Gallery canvas) with four high-leverage interactions:
  1. Live viewport-sampled vector & `WarpedVRT` raster overlay toggles;
  2. Point **Identify** probe reading native raster pixel values & vector attributes;
  3. **Box-select / Feature-select** spatial prompt injection (`[bbox: ...]` / `[FID: ...]`);
  4. **Map Gallery** visual diffing & click-to-revise loops on generated PNG/SVG maps.
- **Expanded MCP & IDE Harness Integrations**: Resource URIs for live map previews, progress notifications, and project-scoped workspace permissions across Claude Code, Codex, Cursor, and Antigravity.

### 2. Multi-Engine Cartography & Human-in-the-Loop Vector Refinement
Building on our V9.0.5 composable primitives (`primitives.py`), bundled SIL OFL typography (`Source Serif 4` & `LXGW WenKai Lite`), editable `<text>` SVG export, and automated 5-point layout/hygiene diagnostics, next milestones include:
- **Multi-Directional Terrain Hillshading & Relief**: Built-in pure-NumPy multi-azimuth soft hillshading for DEM backdrops beneath transparent thematic overlays.
- **QGIS `.qpt` Print Layout Export & Multi-Backend Rendering**: Native PyQGIS `.qpt` layout export alongside Matplotlib/Cartopy static print figures and interactive MapLibre GL / Kepler.gl HTML web maps.
- **Richer Curated Font & Layer Bundles**: Clean semantic `<g id="...">` SVG layer hierarchies tailored for 1-click post-processing in Adobe Illustrator, Inkscape, and Figma, plus additional open-source CJK/serif/sans print font packs.
- **Automated Visual Self-Critique Benchmarks**: Quantitative aesthetic & legibility checks (overlap detection, contrast ratios, label placement density, and SVG byte-size budgets).

### 3. Open GeoAI Evaluation & Community Domain Skill Ecosystem
OpenGIS-Agent separates orchestration from domain wisdom through seven lightweight, file-based Skills (`gis_agent/skills/*/SKILL.md`). We are expanding both evaluation rigor and domain breadth:
- **Reproducible Open Evaluation (`benchmarks/geoagentbench/`)**: Isolated worker sandboxes, shared token/cost ledgers, deterministic spatial vitals (`inspect_fast`), and objective physical/topological invariant checks (`metamorphic_checks.py`, allocation conservation, exact boundary verification) across real GIS workflows without leaking answers into the workspace.
- **New Community Domain Skills**:
  - **Remote Sensing & SAR**: Cloud masking, Sentinel-2/Landsat surface reflectance composites, SAR backscatter calibration, change detection, and time-series phenology.
  - **Urban & Mobility Analytics**: Isochrones, GTFS transit accessibility, street-network centrality, and 3D building morphology.
  - **Hydrology & Flood Risk**: Sub-catchment delineation, SCS-CN / HEC-RAS pre-processing, flood inundation volume balances.
  - **Conservation Ecology & 3D / LiDAR**: Habitat connectivity, corridor resistance modeling, and LAS/LAZ point-cloud DSM/CHM workflows.

---

## How to Contribute

### 1. Local Development Setup (`uv`)
OpenGIS-Agent uses [uv](https://docs.astral.sh/uv/) and `pyproject.toml` + `uv.lock` for reproducible environments:

```powershell
# Clone repository
git clone https://github.com/zhishimian/gis-agent.git
cd gis-agent

# Install core + CLI + dev + full standalone geospatial & cartography stack
uv sync --extra cli --extra dev --extra geo
```

Copy `.env.example` or create a local `.env` with your OpenAI-compatible / DeepSeek API key (`DEEPSEEK_API_KEY=...`, never committed). Optionally set `GIS_AGENT_QGIS_DIR` if you want to run PyQGIS integration tests against desktop QGIS.

### 2. Adding a Cartographic Primitive or Domain Skill
- **New Cartographic Primitive**:
  1. Add a composable Axes/Figure-level function in `gis_agent/integrations/plotting/primitives.py` (never lock users into a rigid whole-figure template; attach semantic `gid="..."` tags for SVG layer editing; ensure pure-Matplotlib fallback when optional Tier-B libraries are missing).
  2. Export it in `gis_agent/integrations/plotting/__init__.py`.
  3. Document its signature & visual usage concisely in `gis_agent/skills/gis-cartography/references/api.md` (keep all Skill files 100% English).
  4. Add unit tests under `tests/test_skills_and_cartography.py` verifying PNG/SVG output, typography/hygiene diagnostics, and Tier-A fallback.
- **New Domain Skill**:
  1. Create `gis_agent/skills/<skill-name>/SKILL.md` with YAML frontmatter (`name`, `description`, `compatibility`) plus focused `references/` and minimal offline executable `scripts/`.
  2. Keep `SKILL.md` short, high-signal, and completely free of hardcoded benchmark answers or non-English prose.
  3. Add structural & offline script tests in `tests/`.

### 3. Pre-PR Verification Checklist
Run the fast test suite during development and the full non-live suite before opening a Pull Request:

```powershell
# Fast offline unit & benchmark-runner tests (seconds)
uv run pytest tests/ -m "not slow and not live" -q
uv run pytest benchmarks/geoagentbench/test_runner.py -q

# Full non-live suite (includes heavy spatial & desktop QGIS checks if GIS_AGENT_QGIS_DIR is set)
uv run pytest tests/ -k "not live" -q
```

Pull Requests should:
- Pass all fast offline tests with zero skipped assertions or warnings in modified areas;
- Avoid committing secrets, `.env`, `sessions/`, `outputs/`, local paths, or proprietary datasets;
- Include rendered preview images when changing cartographic primitives or styling defaults.
