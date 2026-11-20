<div align="center">

# 🌍 OpenGIS-Agent

**可验证的地理空间代码生成与出版级制图 Agent**

[![Version](https://img.shields.io/badge/version-v9.1.0-1c60a6.svg)](pyproject.toml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)](pyproject.toml)
[![QGIS & GeoPandas](https://img.shields.io/badge/backends-GeoPandas%20%7C%20Rasterio%20%7C%20PyQGIS-589632.svg)](gis_agent/skills/gis-data-io-and-staging/SKILL.md)
[![Studio Desktop](https://img.shields.io/badge/Desktop-OpenGIS%20Studio%20v9.1-0ea5e9.svg)](scripts/build_desktop.ps1)
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

### 方式一：OpenGIS Studio 桌面工作台（推荐）

面向希望开箱即用开展**地图画布联动 + 方案审批 + 成图圈注精修**的用户，支持两种零门槛使用方式：
- **Windows 一键桌面安装包 / 绿色便携包**（无需预装 Python / Git / QGIS）：使用源码构建命令 `pwsh -File scripts/build_desktop.ps1` 可产出 `OpenGIS-Studio-9.1.0-x64-setup.exe`（NSIS 免管理员安装）与 `OpenGIS-Studio-9.1.0-x64-portable.zip`。
- **同源本地浏览器工作台**（安装 `[cli,geo,studio]` 后直连同款界面）：

```sh
uv tool install --python 3.12 ".[cli,geo,studio]"
opengis studio --folder "../城市分析"
```

Studio 内置离线可用 MapLibre 空间画布（大矢量视口抽稀、栅格 `WarpedVRT` 透明叠图、`Identify` 点查、手绘 AOI/点选 FID 绑定）、三档过程审批（`auto` / `plan_first` / `step_review`）、运行中随时「停止并纠偏」以及成图画廊红框圈注局部改图闭环。

### 方式二：安装并启动命令行终端

先安装 Git 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)，然后在 Windows PowerShell 或 macOS 终端中运行以下命令安装全局 CLI 工具（或直接切入任意数据文件夹运行 `opengis`）：

```sh
git clone https://github.com/zhishimian/OpenGIS-Agent.git
cd OpenGIS-Agent
uv tool install --python 3.12 ".[cli,geo]"
uv tool update-shell
```

重新打开终端，进入自己的数据文件夹，输入 `opengis`。首次启动会显示模型及服务地址，并提示隐藏输入 API Key，默认使用 DeepSeek。按 Enter 可跳过，之后用 `/key` 连接。

![OpenGIS 终端界面：左侧为像素地球，右侧显示工作文件夹及其会话](assets/opengis-terminal.png)

密钥按服务商和 API 地址保存在 macOS 钥匙串、Windows 凭据管理器或 Linux Secret Service 中，同一服务可跨文件夹复用；系统凭据库不可用时仅用于当前进程。自动化脚本或本地接入桌面 QGIS 仍可通过环境变量或工作文件夹 `.env` 配置：

```env
DEEPSEEK_API_KEY=your_api_key_here
# 可选：接入本地桌面 QGIS / PyQGIS 处理算法
# GIS_AGENT_QGIS_DIR=E:/exe/qgis
```

### 试一个任务

在 `❯` 后输入下面这句话即可试用，无需准备数据文件：

> 计算上海（北纬 31.23°，东经 121.47°）到北京（北纬 39.90°，东经 116.40°）的大圆距离，用千米回答。

处理自己的数据时，可以直接输入相对路径，例如「读取 schools.geojson，告诉我坐标系和要素数量，再按 name 字段标注各点，导出 PNG 地图」。

### 管理工作文件夹和会话

| 在哪里输入 | 命令 | 用途 |
| --- | --- | --- |
| 系统终端 | `opengis --folder "../城市分析"` | 打开指定的数据文件夹 |
| Agent 内 | `/new schools`（或中文会话名） | 在此文件夹新建命名会话 |
| Agent 内 | `/resume` 或 `/resume schools` | 列出此文件夹的会话，或继续指定会话 |
| Agent 内 | `/status` | 查看当前模型、工作文件夹和成果目录 |
| Agent 内 | `/help`、`/exit` | 查看快捷键、退出 |

记录默认保存在工作文件夹的 `sessions/`，成果写入 `outputs/<会话名>/`。不同文件夹可以使用相同的会话名（注：Windows 下若需调用桌面 QGIS / Shapefile 等 C++ 底层驱动，建议使用英文/数字命名会话与工作目录）。

### 从源码开发与 MCP 服务

```sh
uv sync --extra cli --extra geo --extra dev
uv run --no-sync opengis
```

外部客户端（Claude Code / Codex / Cursor / Antigravity）可将 `gis-agent-mcp` 配置为 STDIO MCP 服务；源码环境使用 `uv run --no-sync gis-agent-mcp` 启动。

---

## 🧭 路线图与贡献

欢迎参与空间 Skills、制图原语、QGIS / 桌面端插件与 GeoAI 评测基准建设，详见 **[CONTRIBUTION_AND_NEXT_STEPS.md](CONTRIBUTION_AND_NEXT_STEPS.md)**。
