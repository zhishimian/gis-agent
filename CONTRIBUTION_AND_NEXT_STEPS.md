# 项目路线图与贡献指南 (`CONTRIBUTION_AND_NEXT_STEPS.md`)

欢迎来到 **OpenGIS-Agent**！无论你平时做空间分析、科研制图、GIS 插件开发，还是关注 AI Agent 与前端可视化，都欢迎参与到项目的共建中。这份文档用最直白的方式说明：**我们的核心目标是什么、目前仓库各个分支的进展、整体结构是怎么设计的，以及接下来最需要大家一起发力的五个方向。**

---

## 一、项目目标与当前进展

### 1. 我们的目标
我们的目标是打造**最好用、最专业的开源 GIS Agent**：
- 在**地理空间分析能力**上做到扎实可靠，算得准、过程可复现；
- 在**出版级制图出图**上做到美观规范，摆脱 AI 默认画图的粗糙感；
- 在**可视化与人机协作**上做到丝滑顺手，让人和 Agent 能围绕同一张地图高效配合；
- 在**交付形态**上做到开箱即用，支持独立桌面软件（`.exe`）、网页工作台、命令行终端、AI 编程工具插件（Claude Code / Codex）以及传统 GIS 软件插件（QGIS / ArcGIS Pro）等多种使用方式。

### 2. 当前分支说明
本仓库目前维护两个主要分支（本文档在两个分支间同步共享）：
- **主分支（`main`）**：已完成 `v9.0` 阶段（当前 `v9.0.6`），提供稳定的命令行交互终端（`opengis`）、7 套地理信息技能包（Skills）、开源网络分析工具集、出版级制图组件与 MCP 服务。
- **开发分支（`feature/v9.1-studio`）**：正在推进 `v9.1` 阶段的可视化工作台（**OpenGIS Studio** 独立桌面端 `.exe` 与网页端）及人机交互闭环，待迭代成熟后合入主分支。

### 3. 整体结构（三层解耦设计）
为了让同一套核心能力可以导出成各种形态供大家使用，项目在结构上分成了清晰的三层：
1. **底层：GIS 分析与制图工具库（`gis_agent/runtime/`、`integrations/`、`skills/`）**  
   包含空间数据快速检查、可组合的出版级制图排版组件（随仓开源字体、比例尺、指北针、流图弧线、复合图例、版面质量检查，同时输出 `300 dpi` PNG 与可编辑 `<text>` 的矢量 SVG），以及 7 套按领域整理的 GIS 技能与参考脚本。
2. **中间层：Agent 核心调度引擎（`gis_agent/core/`、`persistence/`、`agent.py`、`application.py`）**  
   负责多轮对话记忆、任务分步规划、Python / PyQGIS 脚本隔离执行、SQLite 断点保存，以及运行中随时暂停/恢复。这一层不绑死任何界面，任何前端或插件都可以直接调用它。
3. **外层：多端交互界面与插件（`gis_agent/adapters/`、`server/`、`frontend/`、`desktop/`）**  
   在核心引擎外面接上不同的“壳”：包括 `opengis` 命令行终端、基于 FastAPI + React + MapLibre GL 的可视化地图工作台（以及 Tauri 封装的 `.exe` 桌面壳），以及面向外部 IDE 和桌面 GIS 软件的插件接口。

---

## 二、接下来我们要做什么？（五大主攻方向）

### 方向一：持续扩充地理空间分析能力
我们目前已经梳理了 7 个基础技能模块（数据读写与整理、矢量与路网分析、栅格与遥感影像、地形与水文分析、空间统计、专题制图、结果验证）。接下来欢迎大家继续往里补充更扎实、覆盖面更广的 GIS 分析能力：
- **丰富各领域的标准分析工作流与参考脚本**：例如城市交通与多模式可达性、选址优化、遥感指数计算与变化检测、流域水文与洪水淹没模拟、空间自相关与地理加权回归（GWR）、空间插值、时空轨迹及三维/街景分析等；
- **沉淀常见易错点与数据检查规则**：把投影转换、单位换算、NoData 处理、拓扑修复、面积/总量守恒检查等实战经验写进对应的 Skill 参考文档和脚本里，提升 Agent 一次性算对的成功率。

### 方向二：打磨出版级专题制图
制图是 GIS 成果最重要的门面。我们希望狠抓各类专题图的成图质量，不只局限于某一种图，而是全面解决实际制图中的高频痛点：
- **攻克核心版面与视觉难题**：包括**密集文字标注与符号的遮挡避让、整体版面布局与留白平衡、图例/比例尺/指北针/经纬网的协调排布、多子图复合排版、色彩搭配与主次视觉层次、复杂点线流图（OD Flow）以及地形晕渲底图衬托**等；
- **制图类 PR 的对比验证约定**：如果你修改或优化了 `gis-cartography` 中的 Skill 文档、提示词或默认制图脚本/原语（`gis_agent/integrations/plotting/`），**请使用相同的提示词（Prompt）测试生成 3～5 张不同场景的地图，并在提交 PR 时附上修改前后的对比图（Before / After）**，方便直观评估改进效果。

### 方向三：地理 AI 可视化与双向人机协同
我们做可视化工作台和交互功能，**并不是写死只能用某一种固定的红框批注或单一控件**，而是希望实现**“人通过 Agent 快速操控软件”与“人用 GIS 界面顺手调整并反馈给 Agent”的双向闭环**：
- **让 Agent 替人干繁琐的操作**：用户可以用自然语言让 Agent 自动加载数据、清洗转换、配置图层样式、聚焦到目标区域或批量生成图表，省去在多层菜单里翻找工具的时间；
- **让人在界面上的操作能实时喂回给 Agent**：对于人眼和鼠标更擅长的事（比如在地图上浏览缩放、点选特定要素、框选研究范围、开关图层、手动微调分级断点/配色、或者在生成的图件上标记需要调整的局部位置），用户在界面上操作后，**系统能把这些状态和意图自动同步给 Agent，让 Agent 明确知道用户改了什么、接下来该怎么接力调整代码或重跑分析**。欢迎大家围绕这个理念探索更自然、更通用的 GIS 人机交互方式。

### 方向四：打造多种开箱即用的应用与插件形态
为了让不同背景的用户都能拿到手就用，我们计划将同一套内核导出为以下 5 种简洁易用的交付形式：
1. **独立桌面应用（`.exe` 一键安装包 / 绿色便携包）**：内置独立 Python 空间运行环境，用户无需配置复杂的 GIS 环境，双击即可打开可视化地图工作台（目前已在 `feature/v9.1-studio` 落地原型，持续打磨体验与安装包体积）。
2. **本地网页工作台（`opengis studio`）**：与桌面应用共用同一套 React + MapLibre 前端界面，一行命令即可在本地浏览器打开交互画布。
3. **命令行交互终端（`opengis`）**：轻量、快速的终端对话工具，支持系统凭据库保存密钥与多文件夹会话管理。
4. **Claude Code / Codex 等 AI 编程工具插件**：面向 Claude Code、Codex、Cursor 等主流 AI Coding Harness 制作原生插件包与技能扩展，让习惯在 AI 编辑器里工作的开发者可以直接调用整套 GIS 分析与制图能力。
5. **QGIS / ArcGIS Pro 桌面 GIS 插件**：在 QGIS（PyQt 停靠面板）和 ArcGIS Pro 中提供原生轻量插件，把软件里当前打开的图层、选中的要素和画布范围直接连入 Agent，并将 Agent 生成的结果自动加载回软件画布。
- *此外*：项目同时保留标准 **MCP 服务接口（`gis-agent-mcp`）**，支持与各类支持 MCP 协议的客户端或外部工具服务灵活连接。

### 方向五：扩充空间分析与制图评测集（Benchmark）
要狠抓空间分析和制图能力，离不开扎实、客观的测试集（`benchmarks/geoagentbench/`）：
- **扩充专题制图测试题库**：收集覆盖区位图、分级统计图、多点线流图、多波段遥感图、地形水文图、多联科研复合图等不同难度和版式要求的制图测试题目；
- **引入竞赛真题与主流 GIS Agent Benchmark**：结合**全国大学生 GIS 技能大赛历届真题**以及国内外主流的 **GIS / GeoAI Agent Benchmark** 开展系统化评测与对比；
- **欢迎贡献高质量实测案例**：非常欢迎大家提交带有**“明确题目与操作步骤 + 明确输入数据 + 明确预期结果或核验标准”**的完整测试题，用真实任务检验和推动 Agent 能力的提升。

---

## 三、本地开发环境配置与运行

### 1. 基础命令行与空间分析开发（`main` 与 `feature/v9.1-studio` 通用）
安装 Git 和 [uv](https://docs.astral.sh/uv/)，拉取代码并同步 Python 环境：

```powershell
git clone https://github.com/zhishimian/OpenGIS-Agent.git
cd OpenGIS-Agent

# 安装核心、命令行与完整开源空间分析/制图依赖
uv sync --extra cli --extra geo --extra dev

# 启动命令行交互终端
uv run --no-sync opengis
```

### 2. 可视化工作台与桌面端开发（`feature/v9.1-studio` 分支）
如果需要参与可视化前端或桌面 `.exe` 开发，请切换到 `feature/v9.1-studio` 分支（需额外安装 Node.js / `pnpm`；若需本地打包 `.exe` 则需安装 Rust `1.90+`）：

```powershell
git checkout feature/v9.1-studio

# 1) 同步包含 Studio 本地服务的 Python 依赖
uv sync --extra cli --extra geo --extra studio --extra dev

# 2) 安装前端依赖并编译静态页面
pnpm --dir frontend install
pnpm --dir frontend run build:sync

# 3) 启动本地浏览器版 Studio 工作台
uv run --no-sync opengis studio --folder "你的数据目录"

# 4) （可选）本地一键编译 Windows .exe 安装包与便携包（产物输出在 dist/ 目录）
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_desktop.ps1 -UseChinaMirror
```

> **关于安装包构建产物的说明**：打包生成的 `.exe` 安装包（一百多 MB，内含独立 Python 空间库）属于编译产物，已在 `.gitignore` 中忽略，不直接放进代码仓库；开发阶段由开发者在本地按需构建，正式发版时统一上传至 GitHub Releases。

---

## 四、提交 Pull Request 简要清单

1. **运行离线测试确保无回归**：
   ```powershell
   uv run --no-sync pytest tests/ -m "not slow and not live" -q
   uv run --no-sync pytest benchmarks/geoagentbench/test_runner.py -q
   ```
2. **制图与 Skill 修改验证**：
   - 修改 `gis_agent/skills/` 下文件时，请保持英文编写（仓库配有自动化链接与格式检查单测）；
   - 修改制图 Skill 或默认绘图原语时，请在 PR 描述中附上 **同提示词下 3～5 张图的修改前后对比效果**。
3. **保持仓库干净**：请勿提交 `.env` 密钥、`sessions/`、`outputs/`、`node_modules/` 或 `dist/` 下的打包二进制文件。
