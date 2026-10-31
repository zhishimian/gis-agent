# GIS-Agent V7

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

## 输出预算与验证

DeepSeek 默认 `max_tokens=393216`。配置入口为 `GIS_AGENT_MAX_OUTPUT_TOKENS`。输入预算同时为输出和协议留出空间。其他供应商的上限需按实际模型显式配置。上限只限制最大生成量；费用按实际用量计算。

截断响应原件保留在 Session。其整批工具调用均拒绝执行。达到模型上限仍会明确停止。V7 收官只完成免费离线验证；提高预算后的真实任务表现尚未测量。

```powershell
python -B -m pytest tests -k "not live" -v -p no:cacheprovider
```

本地离线运行需已有 tokenizer 缓存和可用 QGIS。设置 `HF_HUB_OFFLINE=1` 可禁止 tokenizer 下载。带 `live` 的测试会连接真实模型，需单独授权运行。

收官结果、已知限制和历史实验入口见 [V7 收官](docs/v7-finalization.md) 与 [HANDOFF](HANDOFF.md)。[V8 候选](docs/v8-candidates.md) 尚未实施。
