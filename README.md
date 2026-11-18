# GIS-Agent V9.0

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
- `harness_mcp.py`：面向外部通用 Coding Agent（Claude Code / Codex / Cursor）暴露的精简静态 GIS 工具集。
- `stubs.py`：QGIS 插件端（`QgsTask` + 停靠面板）与独立桌面端事件流骨架。

记录保存在 `sessions/`，成果保存在 `outputs/`。输入数据保持原样。三个 Skills 按需读取：

- [空间分析](gis_agent/skills/gis-spatial-analysis/SKILL.md)：执行路线、数据流、栅格、水文、路网与 API 方法。
- [专业核查](gis_agent/skills/gis-verification/SKILL.md)：针对实际主张取得必要证据。
- [专题制图](gis_agent/skills/gis-cartography/SKILL.md)：自由 Python 制图和图像回看。

## 静态工具协议与快速探针

- **静态 Schema（KV Cache 友好）**：检索 `search_qgis_tools` 返回算法参数契约，执行统一走 `run_qgis_algorithm(algorithm_id, parameters, project_path)`，运行时动态校验必填键与未知参数，不再向请求注入动态工具列表。
- **头信息与概览抽样探针**：`inspect_data` 优先通过 `pyogrio` / `rasterio` 毫秒级读取矢量图层目录、CRS 单位、栅格波段 `dtype` / `colorinterp` / `nodata` / `scale` / `offset` 与 `256×256` 概览值域，必要时回退 PyQGIS。
- **执行器安全回执**：子进程超时整树回收（`taskkill /F /T`）、首尾双向保留错误堆栈、递归扫描子目录新增产物、写入目录边界拦截、`finish_task` 零字节产物拦截，以及 JSON 原子替换 Windows 瞬时句柄重试。
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
python -B -m pytest tests -k "not live" -v -p no:cacheprovider
```

本地离线测试无需 HuggingFace `tokenizers` 缓存；若配置 `GIS_AGENT_QGIS_DIR` 则运行全部真实 QGIS 集成测试。带 `live` 的测试会连接真实模型，需单独授权运行。

重构设计见 [V9.0 重构设计](docs/v9.0-refactoring-design.md)，总体蓝图见 [V9 总体改造方针与落地蓝图](V9_总体改造方针与落地蓝图.md)，行业调研见 [主流 GIS Agent 与制图方案深度调研报告](主流GIS_Agent与制图方案深度调研报告.md)，开发交接见 [HANDOFF](HANDOFF.md)。
