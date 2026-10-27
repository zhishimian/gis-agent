# 项目交接

## 当前实现

V7.1 已按 `docs/v7.1-langgraph.md` 迁移。根目录的 Python 入口为 `main.py`，实现位于 `gis_agent/`。配置在 `config.py`，组件组装在 `application.py`，交互在 `cli.py`，提示词在 `prompts/`。

运行时通过环境变量或项目 `.env` 设置 `GIS_AGENT_QGIS_DIR`。两个 QGIS 启动器可分别配置。相对记录路径按项目目录解析。模型客户端默认重试三次，并关闭环境代理读取。

## 执行与恢复

- LangGraph 在每批工具完成后保存并暂停，驱动自动续跑同一个图。`recursion_limit=16` 限制单段执行，任务总响应次数保持开放。
- Session 保存事实记录，SQLite 检查点保存执行状态。恢复时核对 Session 校验值。记录与检查点不一致时停止自动重放，保留已有 GIS 文件供检查。
- `read_record()` 供图恢复读取原记录；`load()` 继续检查完整工具批次。两者的使用场景需要保持区分。
- `inspect_data.py` 由 QGIS 自带 Python 独立执行，路径从工具模块定位。该脚本保持独立，不导入 Agent 包。
- 每个会话创建独立 Registry，并绑定自己的 Plan 和 Session。记忆工具参数校验失败也进入本轮失败记录，结束前需要解决或报告阻碍。

## 本地验证

执行 `python -m pytest tests -k "not live" -v -p no:cacheprovider`。当前 12 项本地检查通过，真实 API 检查单独执行。测试覆盖 39 次模型响应、SQLite 重启续跑、复核状态恢复和中断工具的重复执行防护。

真实 QGIS 目录搜索、动态工具物化、缓冲运算、几何有效性和面积检查已通过。测试目录位于 `outputs/v71_migration_checks/`。数据、既有会话和记忆记录保持原位。
