# 路线图、架构演进与贡献指南 (`CONTRIBUTION_AND_NEXT_STEPS.md`)

欢迎参与 **OpenGIS-Agent** 的开源共建！无论你擅长空间分析算法、科研与竞赛专题制图、前端可视化（React / MapLibre）、桌面插件开发（PyQGIS / ArcGIS Pro / Tauri），还是 AI Agent 评测基准构建，这份文档都会向你清晰交代：**我们现在做到了哪一步、底层架构是怎么分工的、接下来最需要攻克的四大主攻方向，以及如何在本地配置环境并跑通开发构建。**

---

## 一、当前架构底座与技术栈全景（`v9.1` 现状）

OpenGIS-Agent 的核心设计哲学是 **“一核三环、多端同源”**——把大模型推理编排、确定性地理空间计算和人机交互界面彻底解耦，确保核心能力只需沉淀一次，就能在多种交付形态下复用：

1. **Ring 1｜确定性地理原语与领域知识包（纯 Python，零状态机 / 零 UI 依赖）**
   - `gis_agent/runtime/`：统一包路径定位（`paths.py`）、带进程树回收的隔离脚本执行器（`runner.py`）、新建矢量/栅格零轮次客观体检探针（`inspect_fast.py`，自动提取 CRS、要素数、像元量纲、NoData 与空几何告警）。
   - `gis_agent/integrations/`：可组合出版级制图原语（`plotting/primitives.py`：含多点线流贝塞尔弧线 `add_flow_arcs`、双节矢量比例图例 `add_size_legend`、经纬网、指北针与比例尺）、自动化 5 项版面卫生与字号层级诊断（`plotting/runtime.py`）、随仓开源印刷字体（`Source Serif 4` 与 `LXGW WenKai Lite`）以及可选桌面 `qgis_process` 客户端。
   - `gis_agent/skills/`：7 套全英文、渐进式披露的模块化地理空间技能包（含 `v9.0.6` 零新依赖网络分析四件套：Trimmed-TIN 等值服务区面、`scipy.optimize.milp` 工业级设施选址与 Huff 引力模型、点/线/面障碍与 Top-K 最近设施、边状态图转弯限制与延误）。
2. **Ring 2｜无头会话引擎与人机协议（纯 Python 状态机，零 GUI 框架依赖）**
   - `gis_agent/core/` & `gis_agent/persistence/`：轻量确定性状态机（`AgentLoopRunner` + SQLite 检查点 `SqliteCheckpointer`）、90% 高水位上下文摘要压缩（`ContextManager`）、跨会话长期记忆（`MemoryStore`）、原子配对消息存储（`SessionStore`）与回执追溯（`ExecutionHistory`）。
   - **9 个静态工具协议**：始终保持工具 Schema 前缀稳定，实测将多轮长任务的大模型 Prompt KV-Cache 命中率维持在 **95.7%～97.3%**。
   - **人机协作契约**：通过 `EventCallback`（含 `plan_updated`、`artifact_published`、`interaction_required`）、`WorkspaceContext`（空间上下文与图上批注回传）与 `Conversation.request_stop()`（0.2 秒协作式中止子进程树并保持会话原子闭合）对外暴露标准接口。
3. **Ring 3｜本地空间引擎服务与多端交互壳层**
   - **本地空间后端（`gis_agent/server/`，Python FastAPI + Uvicorn + SSE）**：仅绑定 `127.0.0.1` 回环地址并启用 `X-OpenGIS-Token` 鉴权与路径沙箱；提供大矢量视口裁剪与 Douglas-Peucker 自适应抽稀、栅格 `WarpedVRT` 动态透明 PNG 渲染、矢量+栅格同点 `Identify` 物理值查询、分页属性表与统计断点，以及成图版本与 SVG 语义 `<g id>` 图层解析。
   - **前端工作台（`frontend/`，React 19 + TypeScript + Tailwind CSS + Zustand + MapLibre GL JS）**：负责双栏人机交互、地图画布联动、三档过程审批卡片与成图红框批注精修。
   - **原生桌面壳（`desktop/`，Tauri v2 / Rust `< 300` 行）**：仅负责拉起并守护随包便携 Python Sidecar 进程、绑定 Windows Job Object（`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` 确保主窗口关闭时零残留后台 Python 进程）、提供系统原生文件夹选择与真实绝对路径文件拖放。**99% 的界面与业务逻辑均在 TypeScript/React 与 Python 中完成，无需手写复杂 Rust 业务代码或使用 Qt Designer。**

> **关于安装包体积与构建产物的约定**：
> 打包生成的 Windows 一键安装包（`~164 MB`）与绿色便携包（`~258 MB`）内含完整的独立 Python 3.12 + GDAL / GeoPandas / Rasterio / SciPy / Cartopy 空间计算栈，属于构建产物（已在 `.gitignore` 中忽略，**严禁直接提交进 Git 仓库**）。在当前开发阶段，协作者拉取源码后直接运行 `opengis studio` 即可在浏览器使用完全相同的界面，或运行 `pwsh -File scripts/build_desktop.ps1` 在本地一键编译出 `.exe` 安装包；正式里程碑版本发布时再由维护者统一上传至 GitHub Releases。

---

## 二、接下来我们要做什么？（四大主攻方向与待认领任务）

接下来的版本演进聚焦四件事：**把空间分析做深、把专题制图做精、把 AI 操控的可视化与人机交互做顺、把 4～5 种开箱即用的交付形态做透，并用硬核 Benchmark 持续检验。**

### 方向一：狠抓地理空间分析能力（Spatial Analysis & Domain Skills）
目标：让 Agent 面对复杂科研建模与全国 GIS 技能大赛综合题时，算得准、口径严、物理量守恒、边界情况不翻车。
- [ ] **网络分析与城市交通深水区**：在现有网络分析四件套基础上，补充多模式联运（步行+公交/地铁 GTFS 时空可达性）、OD 矩阵大规模向量化加速、路网拓扑自动缝合与悬挂点诊断工具脚本。
- [ ] **遥感影像与时序物候分析（`gis-raster-and-imagery`）**：补充多光谱云掩膜（QA 波段解析）、非尺度不变指数（SAVI/EVI）反射率自动定标校验、变化检测转移矩阵与分带统计面积守恒核查脚本。
- [ ] **水文地形与灾害风险建模（`gis-terrain-and-hydrology`）**：完善无洼地 DEM 填洼、汇水累积量阈值自适应河网提取、SCS-CN 产流估算、洪水淹没体积平衡与子流域划分参考实现。
- [ ] **空间统计与地理加权回归（`gis-spatial-statistics`）**：补齐空间自相关（全局/局部 Moran's I、LISA 聚类图标准分类）、MGWR / GWR 诊断指标与空间插值交叉验证（Kriging / IDW RMSE 对比）。

### 方向二：狠抓出版级制图与复杂流图表达（Publication Cartography）
目标：彻底告别“AI 默认糙图”，让零提示生成的每一张专题图都具备期刊出版级版式与可导入 Illustrator / Figma 二次精修的干净矢量结构。
- [ ] **多点—线—流（OD / Flow Map）进阶精修**：
  - 优化高密度区域（如长三角/珠三角城市群）的贝塞尔弧线曲率自适应避让与双向不对称流线分层；
  - 完善复合图例（节点分级气泡 + 流强分级线宽）在多种长宽比画布下的紧凑排版；
  - 为 `add_flow_arcs` 支持直接传入内部分割断点或自动识别完整区间边界。
- [ ] **高密度中文注记智能分层与防碰撞**：建立“主中心城市大字号粗体 + 次级节点小字号细体 + 密集区自动牵引线（Leader Lines）+ 重点要素优先保留”的确定性排布原语，消除县市级密集标签重叠。
- [ ] **多向地形晕渲（Multi-Azimuth Hillshade）与美丽底图衬底**：提供纯 NumPy 多光源柔和地形晕渲叠加原语，以及标准邻省/邻国消色衬底、海岸线水体分层渲染模板。
- [ ] **更严格的自动化视觉质检（`layout_diagnostics`）**：在现有 5 项版面卫生检查（堆叠副标题、白底贴片框、双刻度重叠、出界裁切文字、四边留白比）之上，引入图例与主图要素碰撞检测、色彩对比度检查与 SVG 图层语义完整性断言。

### 方向三：地理 AI 智能体操控的可视化与人机交互（AI-Driven Visualization & HIL）
目标：把“AI 盲跑 10 分钟、自己瞎改 8 轮脚本”变成“人机协同指哪打哪、1～2 轮精准定稿”。
- [ ] **画布与 Agent 的双向深度操控**：
  - 支持 Agent 通过结构化指令主动控制前端画布（如自动高亮异常要素、飞掠聚焦到问题区域、自动切换对比波段）；
  - 增强前端画布对大容量数据（十万级要素 `.gpkg` / 大幅面多波段 `.tif`）的分级加载、字段直方图交互筛选与点击属性行反选地图定位。
- [ ] **图上红框批注（Figure Critique）与局部参数微调面板**：
  - 在 `FigureWorkbench` 红框归一化批注（`figure_annotations`）基础上，支持直接点击识别 SVG 语义图层（`<g id="flow_arcs">`、`<g id="size_legend">`、`<g id="scalebar">`）；
  - 提供常用制图参数（色带切换、分级方法 Quantile/Jenks、线宽范围、图例位置）的快捷微调控件，提交后驱动 Agent 仅用 `edit_file` 秒级重出图。
- [ ] **三档执行策略体验打磨**：完善 `auto`（全自动推进）、`plan_first`（体检后先弹方案与口径确认卡）、`step_review`（关键阶段与首版出图后自动挂起审阅）在各类复杂任务中的提示词与 UI 衔接。

### 方向四：5 种开箱即用的交付形态与生态挂载（Multi-Endpoint Delivery）
目标：同一套 `gis_agent` 核心与 `gis_agent/server/` 服务，按用户习惯提供 5 种即开即用的使用途径：
1. **原生桌面应用（`OpenGIS Studio.exe` / 便携包）** *(已落地 v9.1，持续打磨启动速度、自动更新、安装包瘦身与 macOS `.dmg` 跨平台构建)*
2. **本地浏览器工作台（`opengis studio`）** *(已落地 v9.1，与桌面端 100% 共用 `frontend/` 代码)*
3. **极简命令行交互终端（`opengis`）** *(已落地，支持跨目录凭据复用、命名会话管理与结构化选项展示)*
4. **STDIO MCP 服务（`gis-agent-mcp`）** *(已落地，供 Claude Code / Codex / Cursor / Antigravity 零配置调用内环工具与 Skills)*
5. **专业 GIS 软件原生薄壳插件（v9.2 重点招募共建！）**：
   - [ ] **QGIS 停靠面板插件（`< 500 KB` 纯 PyQt 薄客户端）**：**绝不在 QGIS 内置 Python 中重复安装大模型与重型科学计算库**，而是作为轻量客户端连接本地 `opengis-server`，把 QGIS 当前选中图层/选中要素 FID/视口范围实时同步给 `WorkspaceContext`，并在收到 `artifact_published` 时自动将生成图层挂载进 `QgsProject.instance()` 画布！
   - [ ] **ArcGIS Pro 停靠面板插件 / TCP 桥接适配**：对接轻量 `.esriAddinX` TCP 桥（如 `127.0.0.1:5876` 长度前缀 JSON 协议）或 `WebView2 DockPane`，在不破坏 9 静态工具 KV-Cache 架构的前提下，扩展可选的 `gis_agent/integrations/arcgis/` 算子后端。

### 方向五：GeoAgentBench 基准测试与显著性评测（Evaluation & Benchmarks）
目标：拒绝“凭感觉优化”，每一次 Skill、Prompt 或制图原语改动都要有客观评测数据支撑。
- [ ] **全国大学生 GIS 技能大赛真题库与行业盲测集建设**：扩充 `benchmarks/geoagentbench/`，收录历届竞赛空间分析与制图综合题、真实科研复现题，配套零答案泄露的沙箱评测脚本。
- [ ] **确定性物理与拓扑不变量断言（`metamorphic_checks.py`）**：完善面积/总量守恒、三角不等式、CRS 一致性、图层非空率、版面卫生 5 项全绿率以及单题 Token 成本/耗时账本对比。

---

## 三、本地开发环境配置与构建指南

### 1. 基础环境要求
- **Python 核心与空间栈**：Python `3.11+`（推荐 `3.12`）+ 包管理器 **[uv](https://docs.astral.sh/uv/)**。
- **前端工作台开发（修改 `frontend/` 时需要）**：**Node.js `20+`** + **pnpm `9+`**。
- **原生桌面端编译（仅在修改 `desktop/` 或本地打包 `.exe` 时需要）**：**Rust (`rustup` stable `1.90+`)** + Windows 10/11 SDK 与 VS C++ Build Tools（含 WebView2 Runtime）。
- **桌面 QGIS（可选）**：若本机装有 QGIS，可在设置页或 `.env` 中配置 `GIS_AGENT_QGIS_DIR=E:/exe/qgis` 解锁 PyQGIS / Processing 算法；未安装 QGIS 时，内置开源空间栈同样可独立完成 95% 以上任务。

### 2. 拉取代码与安装开发环境

```powershell
# 1. 克隆仓库并切换到 v9.1 开发分支
git clone https://github.com/zhishimian/OpenGIS-Agent.git
cd OpenGIS-Agent
git checkout feature/v9.1-studio

# 2. 同步 Python 核心、CLI、开源空间计算栈、Studio 服务端与测试依赖
uv sync --extra cli --extra geo --extra studio --extra dev

# 3. 安装前端依赖并编译静态产物到 gis_agent/server/static/
pnpm --dir frontend install
pnpm --dir frontend run build:sync
```

### 3. 三种本地运行与调试方式

- **方式 A：直接启动本地浏览器版 Studio（最轻量，无需编译 Rust）**
  ```powershell
  uv run --no-sync opengis studio --folder "你的数据文件夹路径"
  ```
  前后端联调时，可在一侧运行 `uv run --no-sync opengis-server --port 8765 --allow-bootstrap`，另一侧运行 `pnpm --dir frontend dev`（访问 `http://127.0.0.1:5173` 支持热更新）。

- **方式 B：启动极简命令行终端或 MCP 服务**
  ```powershell
  uv run --no-sync opengis --folder "你的数据文件夹路径"
  uv run --no-sync gis-agent-mcp --project "你的数据文件夹路径"
  ```

- **方式 C：本地一键构建 Windows 桌面安装包（`.exe`）与便携包（`.zip`）**
  ```powershell
  # 自动编译前端 -> 组装并裁剪独立便携 Python 3.12 空间运行时 -> 编译 Tauri + NSIS 安装包
  pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_desktop.ps1 -UseChinaMirror
  ```
  构建完成后，产物位于本地 `dist/OpenGIS-Studio-9.1.0-x64-setup.exe` 与 `dist/OpenGIS-Studio-9.1.0-x64-portable.zip`。

---

## 四、贡献规范与提交 PR 检查清单

1. **严守模块边界与语言约定**：
   - 新增制图原语请放入 `gis_agent/integrations/plotting/primitives.py` 并在 `__init__.py` 导出，附上语义 `gid="..."` 以支持 SVG 图层解析，同时将简洁签名更新到 `gis_agent/skills/gis-cartography/references/api.md`（注意 `api.md` 必须保持 `< 5 KB` 首屏可读）。
   - **`gis_agent/skills/` 下所有 `.md` 与 `.py` 文件必须保持 100% 纯英文**（由离线单测严格校验全英文与相对链接锚点有效性）。
   - 保持核心 9 个静态工具稳定，不在 `Agent` 主循环中随意堆砌新工具Schema。
2. **提交前必跑离线回归测试**：
   ```powershell
   # 快速离线单元测试（含服务端、HIL 检查点、空间预览、Skills 审计）
   uv run --no-sync pytest tests/ -m "not slow and not live" -q

   # 评测运行器与成本账本单测
   uv run --no-sync pytest benchmarks/geoagentbench/test_runner.py -q

   # 若修改了前端代码，确保 TypeScript 类型检查与构建零报错
   pnpm --dir frontend run build:sync
   ```
3. **Commit 与文件卫生**：
   - Commit Message 请遵循 **Conventional Commits** 规范（如 `feat(cartography): ...`、`fix(server): ...`、`docs: ...`）。
   - **切勿提交** `.env`、真实 API Key、`sessions/`、`outputs/`、`dist/`、`node_modules/`、`desktop/src-tauri/target/` 或百兆级二进制安装包。
