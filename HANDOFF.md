# 项目交接

## 当前实现

V7.4 已按 `docs/v7.4-evidence-review.md` 应用。根目录的 Python 入口为 `main.py`，实现位于 `gis_agent/`。配置在 `config.py`，组件组装在 `application.py`，交互在 `cli.py`，提示词在 `prompts/`。

运行时通过环境变量或项目 `.env` 设置 `GIS_AGENT_QGIS_DIR`。两个 QGIS 启动器可分别配置。相对记录路径按项目目录解析。模型客户端默认重试三次，并关闭环境代理读取。

默认主任务与图片均使用 DeepSeek。通过 `GIS_AGENT_PROVIDER` 选择 DeepSeek、OpenAI 或兼容 Chat Completions 的服务。切换时同步核对模型、地址、密钥变量名、窗口与 tokenizer。其他供应商启用视觉时需要显式设置图片预算。

`read_image` 支持可选 `crop=[left, top, right, bottom]`，坐标相对于本次输入图片，右下边界不包含。裁剪输出为 PNG，记录源图哈希、尺寸与区域。使用整图快照路径裁剪可保持版本一致。Pillow 已安装，依赖已进入 `environment.yml`。

`agents/subtasks.py` 管理同步委派，`tools/verification.py` 提供 verify_task、read_verification 和子任务结果工具。application 的 AgentFactory 为父子任务创建独立可变状态，共用 GIS 提示词放在 gis.j2。子任务 completed 表示复核结束，检查是否通过由每项 PASS、FAIL、UNKNOWN 表达。

验证 Agent 阅读完整要求后自选少量重难点，用 define_checks 登记判定条件、方法和覆盖范围。方案从 Session 重建，结束时逐项回报已登记 ID。证据绑定真实工具记录、完整结果资产、脚本快照与日志版本；缓存回读保护证据文件。map_notes 只保存简要地图观察和图片引用。委派配置签名已升级为 2，旧配置的委派使用新 task_id。

## 执行与恢复

- LangGraph 在每批工具完成后保存并暂停，驱动自动续跑同一个图。`recursion_limit=16` 限制单段执行，任务总响应次数保持开放。
- Session 保存事实记录，SQLite 检查点保存执行状态。恢复时核对 Session 校验值。记录与检查点不一致时停止自动重放，保留已有 GIS 文件供检查。
- `read_record()` 供图恢复读取原记录；`load()` 继续检查完整工具批次。两者的使用场景需要保持区分。
- `inspect_data.py` 由 QGIS 自带 Python 独立执行，路径从工具模块定位。该脚本保持独立，不导入 Agent 包。
- 每个会话创建独立 Registry，并绑定自己的 Plan 和 Session。记忆工具参数校验失败也进入本轮失败记录，结束前需要解决或报告阻碍。
- 子任务使用独立 Session、ContextManager、Plan 和 SQLite。委派消息来源为 delegation，子任务关闭记忆维护和完成后的再次复核。主任务保留原有复核流程。
- 同一 task_id 绑定用户原话、文件指纹与配置签名。文件指纹覆盖显式提交的清单，新增依赖需补齐后新建委派。完成结果回读时校验记录和产物；检查期间输入变化会返回 stale 和 blocked。

## 本地验证

执行 `python -m pytest tests -k "not live" -v -p no:cacheprovider`。当前 12 项本地检查通过，真实 API 检查单独执行。测试覆盖 39 次模型响应、SQLite 重启续跑、复核状态恢复和中断工具的重复执行防护。

真实 QGIS 目录搜索、动态工具物化、缓冲运算、几何有效性和面积检查已通过。测试目录位于 `outputs/v71_migration_checks/`。数据、既有会话和记忆记录保持原位。

V7.2 的整图与裁剪像素、PNG/JPEG/WebP、无效区域、快照复用与篡改检测已通过本地检查。真实 SDK 经本地模拟 HTTP 接口检查三个供应商的请求格式，实际应用与 LangGraph 的图片读取、复核、结束流程通过。未调用收费模型 API，视觉识别效果尚未实测。

V7.3 的实际入口、SDK 和父子流程通过 21 次本地固定响应检查，覆盖状态隔离、证据与产物路径校验、结果复用、恢复、输入变化和截断处理。原有 12 项本地测试通过。全程未调用实际模型，GIS 复核质量尚未实测。

V7.4 的实际入口、SDK 与父子流程通过 9 次固定响应检查，检查脚本由真实 QGIS Python 执行。覆盖登记完整性、证据来源、外置结果哈希、脚本与日志版本、地图备注、缓存失效，以及执行期间脚本改写或删除。原有 12 项本地测试通过。未调用实际模型，临时数据与记录随检查结束清理。

## 后续设计参考

- 本地 Wenyi 的 `agents/review_actions.py` 校验复核结论引用的证据是否已实际取得。`pipeline/autofix_plan.py` 保存修改前后哈希，`autofix_publish.py` 在写回前核对当前内容。这些设计可用于成果复核和安全修正。
- learn-claude-code 的 `s16_workflow_runtime/code.py` 按调用内容生成稳定键，并从 journal 复用结果。GIS 步骤复用需要进一步绑定输入数据身份、算法版本、参数与产物依赖。
- `s17_goal_loop/code.py` 的独立判断器只读取对话记录。GIS 复核需要向判断器提供实际产物证据；图件检查还需要图像输入能力。

## 模型与图像接入调研

2026-10-27 核对官方文档和本地源码：

- 当前 `deepseek-flash` 支持图像输入。OpenAI 的图像输入能力按模型区分。参考：[DeepSeek](https://api-docs.deepseek.com/guides/vision/)、[OpenAI](https://developers.openai.com/api/docs/guides/images-vision)。
- 当前适配器使用 Chat Completions。Session 保存带哈希的图片快照引用，预算和发送共用请求投影；只发送最近一批新读取的图片，模型回答后需要再次读取才能重看。附加图像消息不写回 Session，保持来源序号稳定，base64 不参与文本计数。
- 本地 `E:\vscode\wenyi\wenyi` 有 API 供应商适配，其文本生成接口返回字符串。复用时需要保留本项目的工具调用、图像消息、usage 和结束状态。
- 用户要求将真实任务小评测放到 V7 收尾。

## V7 后续需求

V7.5 已细化为详细设计，代码仅在文档中，基于 V7.4 扩展。独立验证 Agent 阅读完整要求后，自选少量重难点取证，通常先选 1～2 项。修正版只自动带入未解决的重点项，按改动补查风险。review_delivery 登记候选，completion_check 在交付前核对当前文件与证据。交付记录用 selected_risks 标明实际复核范围。文档原型通过重点筛选、修正闭环、版本保护和原有 12 项本地测试，未调用实际模型。

V7.6 与 V7.7 保持粗略需求，方向为制图子 Agent、局部回退原型。

参考本地 learn-claude-code 的 `s06_subagent/code.py`：同步委派、独立消息列表、限定工具集合和简短结果返回。该实现共享进程与文件系统。项目规划中保留子任务完整记录，并通过父子标识关联；验证与制图共用执行机制，分别配置职责和工具。
