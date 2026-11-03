# GIS-Agent V8.4

单 Agent GIS 助手。LangGraph 管理模型与工具往返。QGIS Processing 和独立 QGIS Python 执行空间计算。Matplotlib、GeoPandas、Rasterio 负责静态制图。

## 使用

Agent 环境依赖见 [environment.yml](environment.yml)。GIS 库安装在独立的 QGIS Python 环境。制图库版本见 [requirements.txt](gis_agent/integrations/plotting/requirements.txt)。运行前核对实际包位置；Conda 和 QGIS Python 的依赖独立管理。

在本机 `.env` 中配置 `DEEPSEEK_API_KEY` 和 `GIS_AGENT_QGIS_DIR`。该文件不提交。也可用环境变量配置供应商、模型和执行路径。入口为：

```powershell
python main.py
```

记录保存在 `sessions/`，成果保存在 `outputs/`。输入数据保持原样。三个 Skills 按需读取：

- [空间分析](gis_agent/skills/gis-spatial-analysis/SKILL.md)：执行路线、数据流、栅格、水文、路网与 API 方法。
- [专业核查](gis_agent/skills/gis-verification/SKILL.md)：针对实际主张取得必要证据。
- [专题制图](gis_agent/skills/gis-cartography/SKILL.md)：自由 Python 制图和图像回看。

复杂任务可参考空间分析 Skill 内的阶段化 Python、I/O 和路网示例。昂贵计算可保存中间成果，再单独完成后段和格式导出。普通小修改仍可直接编辑执行。

`execution_history` 按需查当前 Session 的真实参数、脚本快照、结果和错误。`local_replay` 为依赖明确的局部修订保留版本和复用成果；它不恢复 Python 内存，也不自动推断隐藏依赖。Fisher-Jenks 示例需要在实际 QGIS Python 中安装固定的 jenkspy 版本，见上述制图依赖清单。

## 等待用户与继续

Agent 缺少必要信息时可用 `needs_input` 提问。CLI 会展示问题及保留成果，输入回答即可在同一 Session 继续。输入 `exit` 或在提示处结束输入会保存等待；再次使用同一 `--session` 打开会显示原问题。等待时输入 `cancel` 可取消任务并保留成果。运行中的原生计算不支持内存级暂停。

```powershell
python main.py --session my-task chat
python main.py --session my-task waiting
```

`waiting` 只读查看已有问题，无需模型 Key 或启动 QGIS。完成状态包括 `completed`、`partial`、`needs_input`、`blocked`、`cancelled`；`answer` 用于普通问答。部分完成会列出未完成要求。能力边界及证据见 [V8.4 实施报告](docs/v8.4-implementation-report.md)。

## 输出预算与验证

DeepSeek 默认 `max_tokens=393216`。配置入口为 `GIS_AGENT_MAX_OUTPUT_TOKENS`。输入预算同时为输出和协议留出空间。其他供应商的上限需按实际模型显式配置。上限只限制最大生成量；费用按实际用量计算。

截断响应原件保留在 Session。其整批工具调用均拒绝执行。达到模型上限仍会明确停止。V7 收官只完成免费离线验证；提高预算后的真实任务表现尚未测量。

```powershell
python -B -m pytest tests -k "not live" -v -p no:cacheprovider
```

本地离线运行需已有 tokenizer 缓存和可用 QGIS。设置 `HF_HUB_OFFLINE=1` 可禁止 tokenizer 下载。带 `live` 的测试会连接真实模型，需单独授权运行。

当前交付与证据见 [V8.4 实施报告](docs/v8.4-implementation-report.md)。专业资产及历史/重放背景见 [V8.3 实施报告](docs/v8.3-implementation-report.md)。开发交接见 [HANDOFF](HANDOFF.md)。
