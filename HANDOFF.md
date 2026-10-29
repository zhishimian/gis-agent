# 项目交接

## 当前实现

V7.7 已按 `docs/v7.7-review-efficiency.md` 修复复核开销。简单任务按需规划，主任务保留输入和轻量输出检查，默认交由独立验证核验业务重点。QGIS 适配器验证输出参数后创建父目录，已有文件保护保留。验证提示与分析搜索要求分离，检查范围及输出篇幅按任务收敛。

验证业务状态提供近期可引用证据目录，checks 优先接受实际调用 ID 的 evidence_ids，兼容旧 evidence_indices。结果规范化回原有消息序号，既有交付条件继续生效。错误引用返回可用证据；失败工具、未完成调用、脚本和日志版本继续核对。模型看到精简复核视图，完整结果及资产保留，投影核对资产哈希。

V7.6 制图核心已接入。application 组装独立 cartographer；主任务提供 cartograph_task 和 read_cartography，子任务按需读取十条规则。字体经 QGISConfig.font_files 或 GIS_AGENT_FONT_FILES 配置，Windows默认加载本机雅黑和Arial。依赖仍由QGIS自带Python承载。

cartography_runtime.py 独立运行，负责字体、布局、导出和候选整理。两个示例接收设计JSON，run_python_script现可显式传arguments。普通PNG使用布局渲染到QImage后保存，本机检查没有再出现PNG驱动更新警告。PNG＋QGZ为基础交付，QML/QPT随输出保存。

制图结束要求当前manifest、全部outputs、实际脚本/日志版本，以及渲染后crop=None的整图读取。输入、知识素材、例程和字体保留指纹。stage_candidate只接收新目录，复制后重开工程并重新导出、生成清单；父任务随后读取新预览并沿用V7.5复核。纯视觉意见经新brief.visual_feedback传递。

V7.5 已按 `docs/v7.5-review-repair.md` 应用。根目录的 Python 入口为 `main.py`，实现位于 `gis_agent/`。配置在 `config.py`，组件组装在 `application.py`，交互在 `cli.py`，提示词在 `prompts/`。

运行时通过环境变量或项目 `.env` 设置 `GIS_AGENT_QGIS_DIR`。两个 QGIS 启动器可分别配置。相对记录路径按项目目录解析。模型客户端默认重试三次，并关闭环境代理读取。

默认主任务与图片均使用 DeepSeek。通过 `GIS_AGENT_PROVIDER` 选择 DeepSeek、OpenAI 或兼容 Chat Completions 的服务。切换时同步核对模型、地址、密钥变量名、窗口与 tokenizer。其他供应商启用视觉时需要显式设置图片预算。

`read_image` 支持可选 `crop=[left, top, right, bottom]`，坐标相对于本次输入图片，右下边界不包含。裁剪输出为 PNG，记录源图哈希、尺寸与区域。使用整图快照路径裁剪可保持版本一致。Pillow 已安装，依赖已进入 `environment.yml`。

`agents/subtasks.py` 管理同步委派，`tools/verification.py` 提供 verify_task、read_verification 和子任务结果工具。application 的 AgentFactory 为父子任务创建独立可变状态，共用 GIS 提示词放在 gis.j2。子任务 completed 表示复核结束，检查是否通过由每项 PASS、FAIL、UNKNOWN 表达。

验证 Agent 阅读完整要求后自选少量重难点，用 define_checks 登记判定条件、方法和覆盖范围。方案从 Session 重建，结束时逐项回报已登记 ID。证据绑定真实工具记录、完整结果资产、脚本快照与日志版本；缓存回读保护证据文件。map_notes 只保存简要地图观察和图片引用。验证委派配置签名已升级为 4，旧配置的委派使用新 task_id 和 candidate_id。

`agents/delivery.py` 组合现有 SubtaskRunner。review_delivery 登记候选并委派重点复核，read_delivery 只读已有记录和文件。修正版自动带入未解决项，并将 repairs 说明传给子任务。completion_check 从本轮实际调用重建候选，交付前核对文件与证据；结果用 selected_risks 标明实际检查范围。候选文件位于当前输出目录的 candidates/<candidate_id>/，修正保留旧版本。

## 执行与恢复

- LangGraph 在每批工具完成后保存并暂停，驱动自动续跑同一个图。`recursion_limit=16` 限制单段执行，任务总响应次数保持开放。
- Session 保存事实记录，SQLite 检查点保存执行状态。恢复时核对 Session 校验值。记录与检查点不一致时停止自动重放，保留已有 GIS 文件供检查。
- `read_record()` 供图恢复读取原记录；`load()` 继续检查完整工具批次。两者的使用场景需要保持区分。
- `inspect_data.py` 由 QGIS 自带 Python 独立执行，路径从工具模块定位。该脚本保持独立，不导入 Agent 包。
- 每个会话创建独立 Registry，并绑定自己的 Plan 和 Session。记忆工具参数校验失败也进入本轮失败记录，结束前需要解决或报告阻碍。
- 子任务使用独立 Session、ContextManager、Plan 和 SQLite。委派消息来源为 delegation，子任务关闭记忆维护和完成后的再次复核。主任务保留原有复核流程。
- 正式交付核对本轮最近一次 review_delivery 候选。多次分题复核没有自动汇总为整卷覆盖的机制；整卷一次交付时，末次候选需要包含完整交付成果。验证在主任务调用时同步执行，逐步或分阶段触发仍由主 Agent 决定。
- 同一 task_id 绑定用户原话、文件指纹与配置签名。文件指纹覆盖显式提交的清单，新增依赖需补齐后新建委派。完成结果回读时校验记录和产物；检查期间输入变化会返回 stale 和 blocked。

## 本地验证

执行 `python -m pytest tests -k "not live" -v -p no:cacheprovider`。当前 24 项本地检查通过，真实 API 检查单独执行。测试覆盖 39 次模型响应、SQLite 重启续跑、复核状态恢复和中断工具的重复执行防护，以及 V7.7 的证据兼容与交付流程。

真实 QGIS 目录搜索、动态工具物化、缓冲运算、几何有效性和面积检查已通过。测试目录位于 `outputs/v71_migration_checks/`。数据、既有会话和记忆记录保持原位。

V7.2 的整图与裁剪像素、PNG/JPEG/WebP、无效区域、快照复用与篡改检测已通过本地检查。真实 SDK 经本地模拟 HTTP 接口检查三个供应商的请求格式，实际应用与 LangGraph 的图片读取、复核、结束流程通过。未调用收费模型 API，视觉识别效果尚未实测。

V7.3 的实际入口、SDK 和父子流程通过 21 次本地固定响应检查，覆盖状态隔离、证据与产物路径校验、结果复用、恢复、输入变化和截断处理。原有 12 项本地测试通过。全程未调用实际模型，GIS 复核质量尚未实测。

V7.4 的实际入口、SDK 与父子流程通过 9 次固定响应检查，检查脚本由真实 QGIS Python 执行。覆盖登记完整性、证据来源、外置结果哈希、脚本与日志版本、地图备注、缓存失效，以及执行期间脚本改写或删除。原有 12 项本地测试通过。未调用实际模型，临时数据与记录随检查结束清理。

V7.5 核心检查使用 12 次固定子任务响应，真实入口与 SDK 检查使用 21 次固定响应。分析和复查脚本由 QGIS Python 执行，覆盖错误发现、修正、未解决项继承、交付拦截、版本复用、重开会话回读和普通问答。原有 12 项本地测试通过。未调用实际模型，临时数据与记录随检查结束清理。

V7.6 通过语法、素材和提示词检查，真实QGIS分级设色/NoData、设施图及候选重开导出可运行，原有12项本地检查通过。制图结束检查确认仅裁剪读取会失败，读取当前整图后成功。主入口已组装新工具，未发起模型调用。记录位于 outputs/v76_local_20261028_191255/。本轮未新增测试文件，真实模型闭环、视觉质量、双时相任务与对照实验待后续验收。

2026-10-28 单点 500 米缓冲真实 API 小测试通过，使用当前 deepseek-flash、QGIS native:buffer 和现有独立复核。输入 EPSG:32650，输出半径 500 米、id 保留、几何有效；独立检查的面积近似误差为 0.0402%。完整任务 223.51 秒、父子任务共 47 次模型响应，复核开销偏大。过程出现输出目录未创建、生成脚本误用 PyQGIS 接口和复核证据引用错误，均由 Agent 自行修正。记录在 outputs/buffer500_smoke_20261028_8b218c/report.json。测试记录与产物独立存放，关闭长期记忆写入；未修改运行源码。此结果仅验证简单数据任务，制图和视觉闭环仍待实测。

该测试费用已在同目录 cost-review.md 逐条复盘，response_breakdown.json 保存 47 次响应的参数、结果、usage 和判定。按当晚官方空闲价复算约 0.788251 元，其中验证约 0.530145 元。主自检四次执行均返回失败，最终验证脚本用 os._exit(0) 跳过常规退出，退出异常根因尚未确定。“自行修正”仅说明最终交付完成。验证中为定位证据发生 19 次会话回读，分布在 10 次模型响应中；数值消息序号的引用方式与过长复核返回，是后续降低开销的重点。

V7.7 修复阶段新增收费模型调用为 0。本地 24 项通过，包括真实 QGIS 新目录输出、正常清理退出，固定响应的父子交付与缓存回读，以及失败证据和产物变更拦截。原复核结果的模型投影由 10349 字符缩至 2937 字符，完整三项结论可读，原始记录未变。检查位于 outputs/v77_local_checks/。

随后按用户授权同题复测，输入及原题完全相同、记忆继续关闭。主 Agent 7 次、验证 14 次，共 21 次响应；输入 250360 token、输出 13984 token，总 264344，按当晚空闲价估算 0.224885 元，耗时 108.76 秒。较原记录 token 减少 75.52%、估算费用减少 71.47%，仍未达到 0.1 元目标。记录在 outputs/buffer500_retest_v77_20261028_63b7c5/comparison.md。主任务第 3 次完成缓冲，无计划与自检脚本；证据 ID 一次提交通过，会话编号回读为 0。验证仍有两次执行失败，并因错误假设 mapUnits()==1 表示米而增加核验，通用检查与生命周期问题继续保留。本次 SEGMENTS=5，圆面积近似误差 1.6368%；上次为 32、0.0402%，参数精度差异已记录。

2026-10-29 整卷单次执行在首次独立验证前因 API 402 余额不足中断。主 Agent 57 次、制图 156 次、验证 0 次，总 20886296 token，按当次空闲价估算 19.238735 元。两份保护快照内容相同，不能作为验证前后对照。用户选择粗批后，分析题为 59/80，全卷中断成果为 63/100。记录在 outputs/bpm_v77_paired_20261029_01/evaluation/report.md，运行源码未改。

本轮发现两个可复用约束：Processing 输出可能重新生成 fid，跨图层回写需核对稳定标识和实际几何归属；制图结束检查只解析 stdout 最后一行纯 JSON，脚本打印 RESULT 前缀时，即使渲染、脚本哈希和 manifest 已对应，也会被拒绝。制图第三批累计 112 次响应，既有反复改图，也有 API/退出错误和交付失败；十条设计规则没有限制迭代次数。

小火苗参考解析第 33 页明确说明路网分析未求解成功。该部分评分继续依据题面和独立复算，不能把参考解析当成已完成的路网标准答案。

整卷主 Agent 实际搜索工具 17 次，直接调用具体 qgis_* 工具 0 次，执行脚本 21 次。脚本内复用了 Processing 算法，但仍偏离 qgis_tools.txt 中“找到适用算法后直接调用具体工具”的要求。当前仅有提示词约束，没有程序拦截；检索次数不能证明直接工具优先已落实。

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

V7.6 已按 `docs/v7.6-cartography-agent.md` 落地核心实现。真实模型闭环和六条件先导实验按用户要求暂缓。工作树任务调整为下一阶段 V8.0，详细设计在 `docs/v8.0-workflow-tree.md`，尚未实施：保留现有 LangGraph 循环，增加 GIS 步骤登记、封存、分支继承和依赖失效检查。修正追加到当前 Session，沿用检查点与记录一致性约束。纯视觉观察继续使用 map_notes，现有 ready 仅覆盖已登记重点检查。

参考本地 learn-claude-code 的 `s06_subagent/code.py`：同步委派、独立消息列表、限定工具集合和简短结果返回。该实现共享进程与文件系统。项目规划中保留子任务完整记录，并通过父子标识关联；验证与制图共用执行机制，分别配置职责和工具。
