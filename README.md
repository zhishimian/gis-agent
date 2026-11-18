# GIS-Agent V9.0.3

单 Agent GIS 助手。纯 Python 状态机（`AgentLoopRunner`）与标准库 SQLite 检查点（`SqliteCheckpointer`）管理模型与工具往返，核心运行时零 `langgraph` / `tokenizers` 依赖。支持独立 Python（`uv` 锁定环境）与 QGIS Processing / PyQGIS 双后端执行空间计算，Matplotlib、GeoPandas、Rasterio 负责静态制图。

## 环境与三端入口

项目依赖由 [pyproject.toml](pyproject.toml) 与 [uv.lock](uv.lock) 分组声明，同时兼容历史 Conda 环境 [environment.yml](environment.yml)：

```powershell
# 最小核心 + CLI + 测试环境
uv sync --extra cli --extra dev

# 独立全功能地理计算环境（无需预装桌面 QGIS）
uv sync --extra cli --extra vision --extra geo
```

在本机 `.env` 中配置 `DEEPSEEK_API_KEY`；若需调用 `qgis:*` / `native:*` / `gdal:*` 算法，配置 `GIS_AGENT_QGIS_DIR`（未配置时自动降级为纯 Python 独立模式）。入口为：

```powershell
python main.py
```

三端适配层位于 `gis_agent/adapters/`：
- `cli.py`：终端交互与离线会话查询入口。
- `harness_mcp.py`：面向外部通用 Coding Agent（Claude Code / Codex / Cursor）的标准 STDIO MCP 服务端（`python -m gis_agent.adapters.harness_mcp` 或 `gis-agent-mcp`），零内部循环依赖，直接暴露内环空间探针、QGIS 算法网关与专业 Skills。
- `stubs.py`：QGIS 插件端与独立桌面端边界协议（`WorkspaceContext` 画布上下文注入、`EventCallback` 实时产物事件流、`Conversation.request_stop()` 线程安全子进程树中断）。

记录保存在 `sessions/`，成果保存在 `outputs/`。输入数据保持原样。七大领域 Skills 按需读取（单工具可解任务不强读）：

- [I/O 与阶段执行](gis_agent/skills/gis-data-io-and-staging/SKILL.md)：多图层容器读写、`pyogrio`/DuckDB 下推过滤、业务键保留与稳定阶段文件拆解。
- [矢量与路网](gis_agent/skills/gis-vector-and-network/SKILL.md)：源/分析/交付 CRS 分离、多重连接与分块晕区叠加、Primal MultiDiGraph 有向路网可达与选址。
- [栅格与影像](gis_agent/skills/gis-raster-and-imagery/SKILL.md)：辐射定标（NDVI vs SAVI/EVI 量纲）、参考网格对齐重采样、`block_windows` 分窗流式计算、Zonal Stats 与配准可信度。
- [地形与水文](gis_agent/skills/gis-terrain-and-hydrology/SKILL.md)：DEM/DSM/物体高度分离、工程地形 vs 填洼水文表面、GRASS/ESRI D8 流向编码差异、嵌套流域 vs 子区切分及连通蓄水量。
- [空间统计与插值](gis_agent/skills/gis-spatial-statistics/SKILL.md)：全局 Moran's I、Kriging 变异函数与空间块交叉验证（支持 `esda`/`libpysal`/`pykrige` Tier B 与 `scipy`/`numpy` Tier A 双路由降级）。
- [专业核查](gis_agent/skills/gis-verification/SKILL.md)：外部性质/蜕变不变量取证（守恒、置换不变性、边界对照）、异常信号分诊与诚实拒答边界。
- [专题制图](gis_agent/skills/gis-cartography/SKILL.md)：自由 Python 制图和图像回看。

## 静态工具协议、运行能力注入与快速探针

- **静态 Schema（KV Cache 友好）**：检索 `search_qgis_tools` 返回算法参数契约，执行统一走 `run_qgis_algorithm(algorithm_id, parameters, project_path)`，运行时动态校验必填键与未知参数，并在尾部动态状态注入缓存的 `runtime_capabilities`（`has_qgis` / `tier_b_available`）与连续失败退避信号 `stagnation_alert`。
- **分层异常信号与非对称终结门控**：`inspect_fast` 为新空间产物按 `notice`/`warning`/`fatal` 三级挂载客观异常（如 `ZERO_FEATURES`、`MISSING_CRS`、`ALL_NODATA_RASTER`、`CORRUPT_OR_UNREADABLE`），`finish_task(status="completed")` 仅硬拦截致命损坏并允许对预期内告警通过 `acknowledged_anomalies` 或独立核查后放行；对 `blocked`/`needs_input` 零阻力放行诚实认错。
- **快速探针与自动空间体征**：`inspect_data` 与 `run_python_script`/`run_qgis_algorithm` 自动为新产出文件附带轻量级客观体征 `outputs[].spatial` / `spatial_vitals`（CRS 单位、要素数/像元网格、`dtype`、`nodata`、`valid_ratio`、极值与无效几何抽样数），零额外模型轮次即可核对异常。
- **执行器安全回执**：子进程超时整树回收（`taskkill /F /T`）、首尾双向保留错误堆栈、递归扫描子目录新增产物、写入目录边界拦截、`finish_task` 零字节产物拦截、Plain Python 隔离外部冲突 `PROJ_LIB`/`GDAL_DATA` 环境变量，以及 JSON 原子替换 Windows 瞬时句柄重试。
- `execution_history` 按需查当前 Session 的真实参数、脚本快照、结果和错误。历史 0 调用的 V8.1 `local_replay` 模块已归档至 `archive/v8_replay/`。

## 等待用户与继续

Agent 缺少必要信息时可用 `needs_input` 提问。CLI 会展示问题及保留成果，输入回答即可在同一 Session 继续。输入 `exit` 或在提示处结束输入会保存等待；再次使用同一 `--session` 打开会显示原问题。等待时输入 `cancel` 可取消任务并保留成果。运行中的原生计算不支持内存级暂停。

```powershell
python main.py --session my-task chat
python main.py --session my-task waiting
```

`waiting` 只读查看已有问题，无需模型 Key 或启动 QGIS。完成状态包括 `completed`、`partial`、`needs_input`、`blocked`、`cancelled`；`answer` 用于普通问答。

## 输出预算与验证

DeepSeek 默认 `max_tokens=393216`。配置入口为 `GIS_AGENT_MAX_OUTPUT_TOKENS`。输入预算同时为输出和协议留出空间。截断响应原件保留在 Session，其整批工具调用均拒绝执行。

```powershell
# 日常快速本地检查（秒级，跳过外部 QGIS 与 live API）
python -B -m pytest tests benchmarks/geoagentbench/test_runner.py -m "not slow and not live" -v -p no:cacheprovider

# 全量离线验证（含全部真实 QGIS 集成测试与独立 uv 运行环境验证）
python -B -m pytest tests benchmarks/geoagentbench/test_runner.py -k "not live" -v -p no:cacheprovider
```

本地离线测试无需 HuggingFace `tokenizers` 缓存；若配置 `GIS_AGENT_QGIS_DIR` 则运行全部真实 QGIS 集成测试。带 `live` 的测试会连接真实模型，需单独授权运行。

重构设计见 [V9.0 重构设计](docs/v9.0-refactoring-design.md)，总体蓝图见 [V9 总体改造方针与落地蓝图](V9_总体改造方针与落地蓝图.md)，行业调研见 [主流 GIS Agent 与制图方案深度调研报告](主流GIS_Agent与制图方案深度调研报告.md)，开发交接见 [HANDOFF](HANDOFF.md)。
