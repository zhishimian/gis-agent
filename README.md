<div align="center">

# 🌍 OpenGIS-Agent

**可验证的地理空间代码生成与出版级制图 Agent**

[![Version](https://img.shields.io/badge/version-v9.0.5-1c60a6.svg)](pyproject.toml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)](pyproject.toml)
[![QGIS & GeoPandas](https://img.shields.io/badge/backends-GeoPandas%20%7C%20Rasterio%20%7C%20PyQGIS-589632.svg)](gis_agent/skills/gis-data-io-and-staging/SKILL.md)
[![MCP Ready](https://img.shields.io/badge/MCP-STDIO%20Server-0d585f.svg)](gis_agent/adapters/harness_mcp.py)

**简体中文** | [English](README.en.md)

[制图展示](#-制图展示) • [架构简介](#-架构简介) • [快速开始](#-快速开始) • [路线图与贡献](CONTRIBUTION_AND_NEXT_STEPS.md)

</div>

---

## 🎨 制图展示

OpenGIS-Agent 自动规划空间投影、感知色带、图层压盖与印刷级排版，同时输出 `300 dpi` 成图与**保留可编辑 `<text>` 图层的矢量 SVG**（可直接导入 Illustrator / Inkscape / Figma 精修）。

### 1. 科研多联复合图
*62/38 非对称拼版，采用随仓开源字体 `Source Serif 4`，整合 `0–800 in` 连续降雪色带、Amtrak 站点冬季暴露分级、国界顶层压盖、整数经纬网与联动统计副图（`5.90 MB` 可编辑 SVG）。*

![2024–2025 美国本土降雪与铁路冬季暴露科研复合图](assets/showcase_conus_scientific_composite.png)

### 2. 标准研究区位图
*地图优先的标准研究区位图，包含无染色完整邻区衬底、随仓 `Source Serif 4` 印刷排版、圆形地球仪区位小图、居中线框图例、罗盘星指北针、偏下比例尺与四边整数经纬刻度（`8.51 MB` 可编辑 SVG）。*

![巴西朗多尼亚研究区位图](assets/showcase_rondonia_study_area.png)

---

## ✨ 架构简介

OpenGIS-Agent 摒弃臃肿的框架封装与上百个碎片化工具接口，采用轻量纯 Python 状态机（`AgentLoopRunner` + SQLite 断点持久化），通过 9 个 KV-Cache 友好的静态工具与 7 个模块化地理空间技能（`gis_agent/skills/`）驱动开放式空间脚本执行；新建矢量与栅格产物会自动附带零轮次客观体检（`inspect_fast`，即时暴露坐标系、NoData 与空结果异常），并支持独立 `uv` 空间栈（GeoPandas / Rasterio / SciPy / Cartopy）与桌面 PyQGIS / Processing 双环境平滑切换，配合可组合制图原语与自动化版面卫生质检（`gis_agent/integrations/plotting/`）稳定输出可复现、可二次编辑的分析与制图成果。

---

## 🚀 快速开始

### 1. 使用 `uv` 安装

```powershell
# 基础核心 + CLI + 测试环境
uv sync --extra cli --extra dev

# 完整独立地理空间分析与出版级制图依赖（无需安装桌面 QGIS）
uv sync --extra cli --extra dev --extra geo
```

### 2. 配置 `.env`

在仓库根目录创建 `.env`：

```env
DEEPSEEK_API_KEY=your_api_key_here
# 可选：接入本地桌面 QGIS / PyQGIS 处理算法
# GIS_AGENT_QGIS_DIR=E:/exe/qgis
```

### 3. 运行 OpenGIS-Agent

```powershell
# 交互式 CLI（支持会话恢复、状态查看与历史审计）
uv run python main.py --session my-gis-task

# 标准 STDIO MCP 服务（适配 Claude Code / Codex / Cursor / Antigravity）
uv run gis-agent-mcp
```

---

## 🧭 路线图与贡献

欢迎参与空间 Skills、制图原语、QGIS / 桌面端插件与 GeoAI 评测基准建设，详见 **[CONTRIBUTION_AND_NEXT_STEPS.md](CONTRIBUTION_AND_NEXT_STEPS.md)**。
