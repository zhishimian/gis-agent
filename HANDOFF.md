# 项目交接

## 当前实现：V7 收官

在V7.8提交3054e0c基础上完成单Agent优化，未回退版本。入口仍为main.py，application组装能力，LangGraph执行model/tools/finish。默认验证与制图委派、候选修正链及强制二次复核已经移除。旧Session、输出和评测材料保留。

专业方法分为gis-spatial-analysis、gis-verification和gis-cartography。分析Skill负责执行路线、数据流及真实接口故障，验证Skill负责关键风险取证，两者只有三份短参考，共用integrations/qgis/execution.md。System从YAML头生成name、description和绝对路径短索引，正文及参考用read_file按需加载。没有自动加载器；两项V7.9.1实测均只读了共享执行参考，未读取Skill正文，不能据此声称专业Skill已产生收益。制图维持V7.9.0。

Context将动态运行数据放在历史后方。Schema按名称稳定排序，单独控制Schema预算；被移出可调用集合的算法需重新搜索。保留原始消息、完整工具批次、外置结果及摘要来源保护。DeepSeek的reasoning_content按现有协议保留。本次真实出图小任务输入缓存命中率97.46%；成本归因仍需同条件对照。

新增edit_file唯一替换和可选文件哈希核对，search_text返回行号及可供read_file继续读取的字符位置。目录列表分页并提供绝对路径。文本读取哈希来自同一批字节，编辑保留CRLF。QGIS检索默认三项，精确ID优先；算法重建主键/FID等警告进入工具说明。布局算法支持顶层project_path工程上下文。

inspect_data兼容单source并支持sources批量接入；每个数据单独报告状态。summarize_fields提供空值、唯一值、数值统计、稳定键和可选几何检查。check_spatial_relation测量外键归属与指定谓词，不自动选择业务归属规则。属性统计允许无CRS表格，空间测量要求两层具有相同有效CRS。

run_python_script继续使用独立QGIS Python，保留快照、退出码、日志和哈希。脚本可向环境变量GIS_AGENT_RESULT_PATH指定的文件写JSON，工具返回result；stdout只作日志，不要求末行格式。结构化结果存在时成功响应省略重复stdout，完整日志仍可回读。退出失败或JSON无效时ok保持false。

静态制图使用Matplotlib Agg、GeoPandas和Rasterio。旧render_map、cartography_runtime、两个固定例程及原执行说明已删除。新integrations/plotting/runtime只提供configure_plotting、export_figure和MapPanel，不规定图型、颜色或布局。Agent使用run_python_script自由编写代码，不初始化Qt/Layout。交付PNG、SVG、PDF及脚本，不新建QGZ布局、QPT或制图QML。

Cartography Skill包含短入口、references/api、design、gotchas、review和三个可执行例程。默认图面只放必需地图元素。说明段落、技术报告和验证记录放图外。导出version=2返回实际路径、预览、地图范围和警告；manifest保存文件、字体、库路径与版本及Artist层序。导出警告也保留在stderr。开放脚本不使用旧模板缓存。

run_python_script将目标脚本和arguments写入本次日志目录的JSON，由script_entry还原argv。含竖线、引号、空格、中文和shell符号的参数已通过实际批处理启动器验证。工作目录仍是脚本目录。项目根路径通过GIS_AGENT_PROJECT_ROOT提供并加入sys.path；MPLBACKEND=Agg。分析初始化见integrations/qgis/execution.md。

finish_task保留四种状态，增加artifacts和unresolved。成果支持文件或数据集目录。completed检查路径和未完成计划，不再要求独立角色。只读问答可以answer；未知事项和执行阻碍如实报告。程序检查和语义正确性分别表达。

## 环境与恢复

- Agent解释器：D:/ac/envs/gis-agent/python.exe。专业依赖由QGIS自带Python承载，Agent环境不导入qgis。
- QGIS目录通过GIS_AGENT_QGIS_DIR配置，启动器可分别设置。记录目录相对项目解析。
- 2026-10-30通过现有QGIS Python实际导入确认：Matplotlib 3.10.8、GeoPandas 1.0.1、Rasterio 1.4.3、Pandas 2.3.0、NumPy 2.4.3可用。这是本机已安装状态。V7.9.0已验证代表性GeoPackage多层读写、坐标转换、栅格NoData/旋转/重投影、矢栅叠加、中文和PNG/SVG/PDF导出。其他机器仍需检测。可先复用同一GIS执行环境，无需为这些库立即增设解释器。
- 同日进一步核对：Agent Conda未安装上述地理/绘图库。QGIS Python的GeoPandas、Rasterio和Pandas来自用户级Python312目录；Rasterio报告GDAL 3.9.3，Pyogrio报告3.12.3。V7.9.0的代表性I/O检查通过，全量驱动兼容和发布环境仍需验收。固定制图依赖在integrations/plotting/requirements.txt；本次未安装、搬迁或升级包，用户级来源仍需在发布时明确管理。matplotlib-scalebar、matplotlib-map-utils、Cartopy、mapclassify、adjustText均未发现。
- 另一个候选环境D:/ac/envs/gis-benchmark/python.exe为Python 3.11.17。2026-10-30实际导入Matplotlib 3.11.2、GeoPandas 1.2.0、Rasterio 1.4.4、mapclassify 2.10.0、NumPy 2.4.6、Pandas 3.0.6、Shapely 2.2.0、PyProj 3.7.2成功，模块均来自该环境目录。Rasterio/Pyogrio报告GDAL 3.10.3/3.12.4；未发现qgis或osgeo模块。未运行制图或I/O验收，未将它切换为项目默认后端。
- 模型支持DeepSeek、OpenAI及兼容Chat Completions的服务，切换时核对地址、模型、窗口、tokenizer和视觉预算。SDK默认重试三次，trust_env=False。
- 字体经QGISConfig.font_files或GIS_AGENT_FONT_FILES配置；Windows默认显式加载雅黑和Arial，不复制字体文件。
- read_image保留整图、裁剪、内容哈希与图片快照。图片只进入下一次模型请求；重绘后需读取当前版本。限制为8MiB、边长8192、1600万像素。
- 每批工具提交SQLite并自动续跑。recursion_limit=16只约束单段，任务无固定总响应上限。
- V7.9.0检查点version=790。旧版待续跑检查点明确拒绝自动重放，保留记录并用新会话接续已有成果。Session与检查点哈希不一致也停止重放。
- Session保存事实，SQLite保存执行状态。started但未确认结束的工具不自动重复执行。read_record供恢复检查，load验证完整工具批次。
- .memory和sessions属于本机记录。长期记忆和窗口摘要继续可选，未扩展自动记忆策略。

## 本地验证

2026-10-30：V7.9.0完整离线29项通过，收费live项1项排除。增加旋转栅格、重投影和警告传递检查后，相关6项再次通过。日志在outputs/v790_migration_20261030_01/offline-tests.txt及offline-final.txt。真实Agent验收只启动一次，见文末。

PowerShell命令：

```powershell
& 'D:\ac\envs\gis-agent\python.exe' -B -m pytest tests -k "not live" -v -p no:cacheprovider
```

覆盖：稳定请求前缀、结果资产篡改、局部编辑冲突和CRLF、真实SDK离线请求格式、结构化JSON与失败状态、批量数据和属性表、稳定键/空间归属、同一个Agent完成QGIS缓冲和只读问答、固定SEGMENTS=32的500米缓冲精度、FID警告，以及新制图入口、真实库I/O、字体、层序、三种格式、NoData、旋转栅格、重投影和错误退出。模型调用由固定响应或本地MockTransport隔离，GIS运算使用真实QGIS。

原有长任务超过30次响应、SQLite恢复、版本保护、工具中断不重放、Memory和摘要来源检查继续通过。上述pytest检查未调用收费API。另已完成下述一次真实模型任务，未运行整卷。2026-10-31更正：V7.9.0的M30采用os._exit(0)绕过收尾，未证实修复生命周期；原始Session及脚本保留。V7.9.1的实际定位与处理见文末。

## 历史材料与后续

- docs/v7.8-comprehensive-audit.md审计的是V7.8；112轮制图逐项记录和请求重建在outputs/v78_audit_20261029。历史源码指纹不能作为V7.9当前指纹使用。
- 首次缓冲47次响应、约0.788251元；V7.7复测21次、约0.224885元。两轮SEGMENTS为32/5，面积近似误差为0.0402%/1.6368%，后续对照需固定精度。记录在两个buffer500实验目录。
- 整卷outputs/bpm_v77_paired_20261029_01在首次独立验证前因402中断；粗批63/100，分析59/80，验证后分数缺失。不能把相同A/B保护快照当成前后对照。
- 已知业务风险：人均指标方向、Processing重建FID、空间连接多重匹配、网络顶点吸附和直线回退。参考解析自身也有路网未解和人口总量偏差，继续按原始题意与数据核查。
- 固定精度500米缓冲加一幅地图已实测，记录见下节。下一轮先处理本次已暴露的执行问题，再按相同提示复测。
- V8.0工作树仍为后续设计。子Agent和RAG的重新引入需要真实检出率、并行收益或知识漏检证据。
- docs/v7.9.0-cartography-design.md保留迁移前设计。已按本版范围实施，当前接口和验收以源码及本交接记录为准。

## V7.9真实缓冲和出图测试

2026-10-29：outputs/buffer500_map_v79_20261029_1e780d。真实DeepSeek Flash，关闭记忆，沿用原始点数据副本，SEGMENTS=32，新增PNG与QGZ。112次响应，输入7430736、输出63205、总7493941 token，缓存命中7242240，未命中188496；按当时空闲价格估算0.5861608元，耗时554.31秒。API全部200，工具24次返回失败。未修改源码或测试，原始输入哈希未变。

最终缓冲有效且保留id，边界顶点半径500m，面积近似误差0.040154685%。PNG中文和点面层序正常，QGZ最终重开渲染通过。性能目标未达成，主要耗在自定义布局与工程重开排错。本轮增加了出图，不能与历史纯缓冲总费用作同条件结论。

旧版轨迹：自定义布局曾使用addLayoutItem、attemptMove、attemptResize和zoomToExtent。QGraphicsItem的setRect/setPos曾让导出PNG正常、QGZ重开地图框为0、范围为NaN；project.read成功和导出返回码不足以证明布局可用。独立核对应包含重开后的尺寸、有限范围和实际渲染。这类Layout方法已退出当前实现，历史文件保留。

旧问题：含竖线的图层URI被Windows批处理解释，V7.9.0已通过JSON参数修复。历史模型脚本还出现Processing初始化遗漏、小写参数键、猜图层名、多处布局API错误。run_python_script的工作目录是脚本目录，独立脚本导入项目运行时需给出准确路径。现成Skill和例程已提供，模型本轮仍先写大型自定义脚本。comparison.md、responses.md、failures.json保留成本与失败明细。

## V7.9.0唯一一次真实验收

2026-10-30：outputs/buffer500_map_v790_20261030_01。相同原始点数据SHA为b90696f6045f7be0cd59a3710085af8b50f9a6d02dcc8d068b4c379931d731e8。DeepSeek Flash、记忆关闭，500米缓冲SEGMENTS=32，加PNG标题/图例/比例尺，不要求QGZ。33次响应，输入617056、输出11674、总628730 token，命中562688、未命中54368；19时空闲价估算0.11231776元，105.16秒。仅这一次收费任务，期间源码哈希未变。

独立检查通过：EPSG:32650，1个有效MultiPolygon、id及输入属性保留，外环128段、所有顶点半径约500米，面积误差0.040154685%。实际PNG为2160×1980，已查看点面位置/层序/中文/图例，像素核对点居中、圆形比例与比例尺。输入和manifest哈希一致，无布局工程产物。

绘图阶段M19～25为7次响应、约0.02393484元，无绘图API失败。总计5次工具失败来自Processing路径、PyQGIS分析收尾访问冲突、两次MultiPolygon外环访问及一次带unresolved的completed。2026-10-31更正：最终分析返回0依赖os._exit(0)，正常清理未修复。数据与图件的独立验收结论仍有效。费用仍高于0.1元，分析核查与收尾往返有优化空间；一次通过不证明稳定性。旧测试额外要求QGZ，成本比较需注明交付范围变化。

完整记录从comparison.md进入：responses.md逐轮用量、failures.json、sessions/buffer500_map.json及同名.assets/.calls.jsonl、agent_outputs/buffer500_map/python_logs、independent_check.json和manifest.json。后续不要覆盖这些文件，也不要自动重跑run_once.py。

## V7.9.1执行入口与实测

独立标准算法通常直接调用，批量及复杂逻辑保留自由Python。精确ID搜索只返回该算法；Schema不再混入不支持的CLI参数写法，未知键返回实际允许参数。脚本工具说明给出共享参考绝对路径，保留Windows JSON传参。字段样本是前五条；关系检查只覆盖当前source，无法发现已丢失的源ID。finish_task的unresolved只表示影响用户要求的未完成或未知事项。

run_processing(job)在独立QGIS Python内初始化、调用Processing、清理及写结构化结果。图层、迭代器、writer留在job局部，仅返回普通JSON。异常清除已退出栈帧中的局部对象后重新抛出，保留原traceback及非零退出。项目源码没有os._exit实现，也未新增模型工具。纯GeoPandas/绘图脚本不初始化QGIS。

离线最小复现：全局图层读取和缓冲均在exitQgis返回后发生3221225477；同一操作放进局部job正常返回0。助手正常重复运行、真实业务异常和JSON序列化异常通过。这里只定位了一个已复现原因；任意全局引用、第三方插件和其他原生问题仍需单独诊断。

2026-10-31：完整免费离线34项通过、live项1项排除；最终相关5项通过。两项真实DeepSeek Flash任务各启动一次，记忆关闭、直连、SDK保留3次错误重试，运行期间源码及输入哈希未变。500米缓冲SEGMENTS=32通过独立验收，12次响应、116228 token、约0.0396688元、1次工具失败；尚未达到6～8次响应。建筑/服务区微任务通过独立真值验收，24次响应、470181 token、约0.11072232元、2次工具失败。两项均无原生崩溃，无强制退出。费用按当日空闲价格和usage估算，未读取账单。

记录入口：outputs/v791_20261031_01/report.md。两个Session、资产、逐次usage、错误、脚本快照、完整日志及独立检查均保留。micro_truth在模型运行前固定于评测进程中，运行完成后才写文件，未传给Agent。没有严格文件访问沙箱，因此仍按开发微任务解释。

主要剩余问题是过度编写核查代码和Skill未被采用。缓冲先得到数据后又修正外环访问；微任务额外做FID检查及跨引擎复算。后续优先压缩这些无效往返。两项任务不能证明复杂未知任务的稳定性，不追加收费复测。

## V7.9.1.1 Skills资产

三个Skill的metadata、正文、参考和脚本说明统一为英文。description按实际任务说明使用范围；中文用户请求与标题仍可使用。共享execution.md为唯一Processing入口，继续复用run_processing。Agent循环、System、工具、Context及运行时未修改。

分析Skill新增reproject_clip.py及spatial_join.py。前者演示同一job的多步Processing；后者输出原对象层和全部匹配关系，不选择归属赢家，可按调用者指定字段计算比值。空/重复键及空几何需先明确策略，不能自动当作正常未匹配。

验证Skill新增geometry_facts.py和identity_audit.py。前者遍历全部相关部件/孔洞，对选定样本做明确CRS的平面测量；经纬度默认仅报类型/拓扑。后者检查两版本键覆盖与实际基数，不判定空间归属。两个脚本均接收JSON设置文件，写GIS_AGENT_RESULT_PATH；也可导入组合。它们没有注册为新Agent工具。

已确认的复用坑：精确边界点经过CRS往返会受浮点误差影响；容差或吸附须由任务明确。数据集FID、行序与稳定业务键分开。大整数ID的匹配关系不得经浮点转换。顶点距离与整条边界距离分开，不能用局部事实宣称通用几何证明。

2026-10-31免费离线完整验收40项通过、1个live项排除。三个制图例程保留绘图逻辑，完成英文说明并通过回归。没有新增依赖或收费模型测试。18个中英文用例只做适用性审阅，实际自然触发和收益留到V7.9.2，不能把静态检查当作触发率。记录见docs/v7.9.1.1-skills-refinement.md及outputs/v7911_skills_20261031_01。

## V7.9.2真实试题材料

2026-10-31整理timu暂存的6个顶层压缩包及5个嵌套包，读得10套不同题意的全国赛试卷；金砖包未找到正式题面。材料在outputs/v792_exam_20261031_01，catalog.md为总览，selection.md为选题理由，sources.md记录必要澄清。原包和原始解压材料保留，参考成果放在受试输入之外。

可复制的正式题面为paper/exam.md，数据为paper/input，输出约定paper/results。选出土地利用更新、垃圾场筛选及人口、建筑高程/DTM、小学人口、步行择校/覆盖率、可达性组图6题，形成三条分支。输入14个逻辑数据集、52个数据文件，约8.97 MB。三个XLS已等值导出CSV并逐值核对；其他数据逐字节复制。

关键原始数据问题：土地利用含23个无效几何，保持原样并允许工作副本必要修复；屋顶栅格水平单位为US survey foot，但高程单位未标注，题面固定按原高程数值计算。原题对选址可行组合、重复影响人口、道路接入和覆盖率的口径已公开写入题面。详细变更见sources.md。输入完整性结果为package_check.json，不是题目求解或评分结果。

本轮没有启动GIS-Agent、收费API或自动评分，没有运行整卷。后续只交paper/exam.md及paper/input，不附review或materials。人工批改要点在review/manual-review.md。尚无正式完成时长、模型费用或成绩记录。

## V7.9.2一次真实组合测试

2026-10-31：outputs/v792_live_20261031_01。基于V7.9.1.1冻结工作区，原六题只替换工作和输出路径。DeepSeek Flash、记忆关闭、直连、SDK重试3次。一个新Session连续运行，无人工业务干预、重启或恢复。14:06至14:15，520.84秒，86次响应、98次工具调用，Agent正常提交completed。源码、输入副本及原卷输入的结束哈希均未变。不要再次启动该目录run_once.py。

usage为输入5714137、命中5548672、未命中165465、输出62757、总5776894 Token。思考21677已包含在输出。按当日空闲价估算0.52746644元，未读取账单。14次工具失败含3次运行未创建脚本、11次退出1；没有原生访问冲突。主要使用GeoPandas、Rasterio和NetworkX，本轮没有实际验证Processing助手路径。

六题主要成果均有交付。只读检查21个数据/图片/表格文件均可读，17个GPKG图层无无效几何。78个BuildingBM和两版303个BM完整无重复，99个前导零键保留；输出DTM元信息与原网格一致。正式双面板PNG为3500×1720，已人工查看。没有全面独立重算或评分，不能将completed解释为整卷专业正确。

三个Skill的metadata已在真实System暴露。M60读verification及cartography正文，M63读cartography的api和gotchas；spatial-analysis正文、四个新增分析/验证脚本及execution.md均未读取。制图脚本采用configure_plotting和AnchoredSizeBar，未用export_figure或三个完整示例。本轮无对照组，无法定量归因Skill收益。

可复用问题：GPKG回读的FID不能假设仍是普通字段；任务4曾把0基行索引用作1基学区编号，任务5连续发生上游字段及merge重名错误，后由Agent自行修复。还发现选址使用舍入距离比较阈值、DSM最大值提前舍入；对答案的实际影响仍待人工批改。网络最短性没有独立证明。后续先批改，再决定修改，不覆盖本轮原始成果。

记录入口report.md、responses.md、skills-usage.md、tasks-review.md。完整Session为sessions/exam.json，原始usage为exam.calls.jsonl，同名assets保存工具与图像；requests保存实际模型请求，python_logs保存每次脚本快照和原生日志。只读检查见outputs-inventory.json、read-only-checks.json，产物指纹见output_hashes.json。启动和后处理脚本均留在本轮outputs目录，应用与Skills未作本轮优化。

## V7.9.2后续自审批改

用户随后要求实际批改和完整长报告。新增outputs/v792_live_20261031_01/evaluation-report.md及grading目录，未追加模型API。自拟100分细则按15/20/20/10/25/10分配，本次约95分：15/20/18/10/23/9。分数未经官方或盲评认证，含主观制图评价，不能与不同试卷历史分数直接比较。

免费复核确认：选址44个候选的原精度判断、可行组合及人口均一致，提前舍入未改变本卷答案；任务4全部303对象及人口正确。土地利用面覆盖和用途正确，23个几何差异仅为make_valid产生的无面积线状残留。78栋基本高度和DTM建筑内外修正通过；BuildingBM=2127的自身高度应为46.83，成果46.82，源于DSM最大值提前舍入，单位沿用原高程。

路网通过QGIS原始道路图独立核对303个对象，发现9处距离偏长，最大10.059818米。另一个保留最短平行边的诊断与QGIS结果最大差约2.1e-9米，定位原脚本无设施边分支的简单Graph.add_edge覆盖短边。学校选择、等级与覆盖率本卷均未因此改变。路线长度与字段一致无法证明路线最短。网络结果及原因在grading/network-checks.json和network-diagnosis.json。

这次只新增批改脚本、证据与报告，原184个Agent输出文件未改。上节“未全面重算或评分”描述的是最初运行复盘阶段；后续判断以本节及evaluation-report.md为准。下一步优先处理静默精度与平行边知识，先保留本轮原始成果，不擅自修正历史脚本或数据。

## V7.9.2 Skills定向修订

2026-10-31：根据组合题已确认错误修订三个Skill及相关测试。记录在docs/v7.9.2-skills-targeted-refinement.md，免费验收材料在outputs/v792_skills_refinement_20261031_01。未启动模型任务、收费API或竞赛复测。应用层、加载器、System、执行器和制图运行时未改，七个既有Skill脚本及历史成果保留。

分析description补充叠加、栅格高程、路网可达性等业务与规划触发。三个Skill采用标准顶层compatibility；skill_index仍只返回name/description/path，不需要修改加载器。本机skill-creator旧quick_validate白名单漏了compatibility，拒绝结果保留；项目标准字段、索引和引用测试通过，不为旧外部校验器回退字段位置。

新增parallel_edges.py与precision_example.py，均为无竞赛数据的最小可执行例子。前者展示简单Graph覆盖平行边使代价9而正确代价5；后者展示Float32提前舍入使差值10.24变10.23及阈值误判。最小边合并只适用于可互换、可加代价和已正确接入的图模型；真实道路仍需完整拓扑与状态建模。

本轮离线执行还更正一个历史判断：Matplotlib 3.10.8的TextArea既没有set_fontsize，也没有set_text_props。旧M68使用hasattr后跳过调用，成功出图无法证明字体修改生效。现参考采用AnchoredSizeBar的FontProperties，或获取实际Text子对象改字体；真实渲染断言通过。历史Session和报告未重写，本轮报告解释差异。

初轮18通过、2失败均保留：本轮错误字体示例和旧链接测试未处理章节锚点。修复后完整相关20项通过，65.86秒；24条中英文适用性仅做静态审阅。尚未证明自然触发率、模型正确率或Token收益改善。下一步观察实现前自然读取、按需资源采用及主张对应证据，不把Skill读取次数当成果。

## 第十二、十四届后续选题查看

2026-10-31仅看题选题，未运行Agent。两个新原包题面在outputs/exam12_14_review_20261031，selection.md给出建议。按场次为四套；第十二下午包含40分土壤侵蚀和60分住宅三维。推荐先第十四上午动物分布/环境综合，再第十四下午DEM/水库/成本道路/土方作为进阶。正式PDF副本为papers/14-am.pdf和14-pm.pdf，解析文本D07/D08，原压缩包保留。

第十四上午关键输入是两份文本及DEM、土地覆盖和影像，包内~$xlsx为临时锁文件。文本按GB18030读取可保留度分秒符号；原始文本未改。第十四下午原卷survey_point.shp实际为Measurement_point.shp，高程文本拼写与题面也有差异；运行前按原数据明确路径映射。影像粗匹配、插值留出评价、U形坝址及水文算法可用性仍需正式测试前检查，本轮未解题或调用收费API。

## V7.9.3第十四届双场实测

2026-10-31：outputs/v793_exam_20261031_01。两份完整原卷和9页图片转为忠实题面，原数据逐场隔离。基于当前工作区冻结，DeepSeek Flash、记忆关闭、直连、max_tokens8192。上午和下午各正式启动一次，没有重开或续跑。不要再次启动该目录run_once.py。

两场均以length进入blocked，截断工具调用没有执行。上午114次响应、15870275 token、1328.73秒、估算1.26134252元，最后写工作文档截断。下午59次响应、3694512 token、4368.29秒、估算0.51506968元，最后拟写最终坝址/库容脚本截断。合计173次、19564787 token、1.77641220元。金额按当日官方空闲价与usage估算，思考已计入输出。终止时输入239549/113254，均低于900000请求预算；应区分上下文预算与单次输出预算。

下午包含一次组织者运行保护取消：单个GDAL插值子进程运行44分40秒后中止，原Session收到真实非零码并自行恢复。没有新增业务提示、代写脚本或修复答案。该场不能省略运行干预限定，记录见afternoon/organizer-actions.jsonl。原脚本约595万点的线性插值已产出，全点IDW约26分钟只有文件头。现有run_python_script缺少超时/取消和进度接口，长工具调用会阻塞Agent。后续Agent自行降低点数、修复数组和GDAL接口、增加TIN缓存，最终生成县域DEM和水文中间成果。

上午有大部分分析数据和8张图，但影像仅以无可靠对应的居中平移继续地类更新，降雨选型使用了同一10%留出集。下午DEM的116个有效测量点RMSE独立复核为2.3941125米，另84点无有效栅格值；候选坝同时播种的分区与完整上游面积混用，填洼表面用于工程剖面，诊断图混入NoData。最终坝址、库容、道路、土方及300dpi TIFF均未交付。不要将中间候选计数或拟写但未执行的代码当作结果。

三个Skill索引在两场System均可见。上午M6读分析Skill、M64/65读制图正文/API；验证Skill未读。下午三个正文均未读，只读共享执行参考并在探查中使用run_processing。自然读取和具体收益仍需同题对照，不能用本轮与V7.9.2不同试题的成本差推断版本提升。

入口为report.md、responses.md、skills-usage.md、tasks-review.md及各场review.md。每场保留完整Session、assets、calls.jsonl、requests、checkpoints.sqlite、脚本快照和原生日志。最终final-integrity.json通过：84个冻结文件无变化，220个输入及509个Agent产物在组织者只读复核后未变；应用、Prompt、Skills和执行器未修改。下一轮先处理单次输出截断恢复、长作业边界与中间结果复用，再完善关键专业证据。


## V7 收官与预算配置

2026-10-31：按用户最终决定，DeepSeek默认max_tokens从8192改为模型官方上限393216。配置入口仍为GIS_AGENT_MAX_OUTPUT_TOKENS；其他供应商需要核对各自模型。AppConfig默认输入预算同步变为638976，协议余量16384。旧测试的900000输入预算属于历史配置。达到模型自身上限仍会length；整批截断调用拒绝执行，原始响应和usage保留。本版没有自动重生成，也没有收费复测。

三个Skills补充插值评价隔离、配准可信度、完整汇水区/分区/淹没区语义、工程地形与水文表面、NoData邻域、计算量和缓存失效。新反例validation_split.py、terrain_counterexamples.py只使用合成数据。不能将离线正确性或description修改称为自然触发率、模型正确率或成本收益。

合并前免费离线50项通过、1个live项排除；针对性7项通过。1b5a8cc收拢有效成果后，main快进合并成功，无冲突。合并后再次完整免费回归50项通过、1项排除，110.44秒。未推送远端。日志和最终分支指针在outputs/v7_finalization_20261031，693个历史产物和18项原包/题面哈希未变。收官入口docs/v7-finalization.md，V8候选为docs/v8-candidates.md。原生长作业取消/进度、工作流依赖及人工介入本轮仅记录候选。旧实验、试题、Session和大量产物继续本地保留。V7可以冻结为开发基线，实际模型收益及发布环境仍未验收。

## V8 架构研究

2026-10-31：基于 main 的 5d82e58 完成 docs/v8-architecture-research.md 和 docs/v8-implementation-plan.md。仅研究与设计，应用、Prompt、Skills、配置和测试未改；没有模型 API 调用。原始探针和轨迹统计在 outputs/v8_research_20261031。docs/ 仍被 Git 忽略，后续提交文档时需单独检查。

推荐先记录真实执行，再将昂贵或需要编辑的阶段转为显式轻量 DAG。确定性阶段批量执行，不为每个节点请求模型。V8 先做独立内核和 CLI，正式 QGIS 插件放到 V9。任意 Python 隐式依赖、活动数据库和未固定外部数据不自动缓存。Session、Checkpoint 与业务步骤保持各自职责，通过版本和完成回执关联。

本机 LangGraph 1.2.18 的 SQLite 中断恢复探针通过。恢复会重新进入中断节点，节点内应避免昂贵计算和重复副作用。同一轮独立节点可完成，但独立分支的后继会等到 resume。需要先登记局部人工请求并推进 ready 工作，再进入全局等待。现有 drive 自动续跑静态检查点的逻辑需要识别真实人工中断。

QGIS 3.44.9 的 .model3 使用 XML/variant。模型编辑器局部重跑依赖上次执行上下文；QgsProcessingModelInitialRunConfig 没有 Python 绑定。序列化独立探针发生原生访问冲突，未完成往返验证，原因未定位。后续模型适配须单独验收，不据此扩大推断现有 Processing 运行时的可靠性。

## V8.0 / V8.1 设计再审视

2026-11-01：新增 docs/v8.0-execution-history-design.md 和 docs/v8.1-autonomous-repair-design.md。两份是下一轮实施入口。旧研究保留，当前范围收紧为执行历史与自主局部修复。尚未实施 V8、调用模型 API 或重跑竞赛题。设计过程在 feature/v8-workflow，main 保持 5d82e58。

V8.0 先从 Session 派生执行视图，再自动补小型文件回执与一个 execution_history 查询。V8.1 用可选 local_replay 一次提交明确修复范围，继续当前对话，按需形成小型依赖子图。暂不新增工作流 SQLite 或常驻 WorkflowRunner，不要求普通操作 prepare/finish，也不要求逐步专业 PASS。旧普通文件缺少历史内容指纹时，只能明确采用当前文件，不能称为已验证历史缓存。

首个编码任务是 persistence/executions.py 的只读 rows：先准确配对现有调用、工具结果与资产，不改 Agent。后续才接自动记录。Typer 当前为单命令模式，增加 history 后需要保留原 chat 启动兼容。免费静态探针六项通过，记录在 outputs/v80_v81_design_20261101/static-probes.json；它们只验证现有基础，未证明新接口、自然修复率或 Token 收益。

## V8.0 执行历史已实施

2026-11-01：四个切片提交 c7014b0、04df1f5、43c869a、9baa4c7，均在 feature/v8-workflow。实施报告为 docs/v8.0-execution-history-implementation.md。main 保持 5d82e58，没有推送。Session、LangGraph 790 恢复、Context 和自由 Python 语义保留；未实现 local_replay。

AgentFactory 注入 ExecutionHistory，自动记录真实调用边界。关键 Session 写失败仍抛出；辅助回执写失败只告警，不阻断工具。execution_history 支持 detail、script、stderr 等受限分页查询。CLI history 无需模型 Key 或 QGIS，原无子命令聊天和显式 chat 均可用。资源范围为当前 Session 资产和配置输出目录的 python_logs，归档 CLI 需要正确的 --project/--output-dir。

完整免费回归68项通过、1项live排除，123.66秒；补强真实GPKG属性/几何一致性后单项复查通过。父测试进程禁真实网络，未调用收费API或竞赛复测。千条小回执默认查询中位数124.93ms、p95 196.46ms，新Schema 235 token。默认按Session候选筛选、核验返回项；status筛选会核验全部相关回执，成本更高。证据在 outputs/v80_execution_history_20261101。

旧数据没有历史指纹时不能证明版本未变。Python快照只作记录，实际原路径代码身份仍标not_proven。只有started或孤立回执不自动修补Session或重放。下一步应先实现受控小流程的局部修订，避免把历史查询称为已具备自动修复或缓存。

## V8.1 局部修复已实施

2026-11-01：feature/v8-workflow 完成五个切片，提交 f502ec8、2813997、6a38c77、ba8125d、af61034；3c2f6e2 补强受控Python输出继承及环境身份。main 仍为5d82e58，未合并或推送。正式报告为docs/v8.1-implementation-report.md。

唯一新增行动工具local_replay可选使用。core/replay.py组成真实小型依赖闭包，保留旧输出，封存明确本地输入，冻结补丁或候选Python及辅助文件。受控Python读job JSON，普通run_python_script语义不变。当前受控QGIS范围为native的reprojectlayer/buffer/intersection/clip/dissolve/fixgeometries，其他算法继续自由工具或Python路径。GPKG活动日志、外部栅格附属文件、数据库和未知副作用不自动复用。

关键修复记录写失败不能发布成功；V8.0普通历史仍为辅助失败告警。新Checkpoint版本810，旧790保留原严格恢复。只恢复单独local_replay根调用，核对Session、原调用、计划、检查点和输出版本后使用graph.update_state(as_node='tools')。意图存在但缺少完成记录时保留unknown，不因文件存在重跑。代码和环境声明仍基于可信本机，不能恢复任意Python内存或穷举隐藏依赖。

最终免费回归95 passed、1 live deselected，251.10秒。真实子进程崩溃、SQLite重开、QGIS参数修复与独立完整重算、Python补丁、受控前缀继承、缓存及原执行路径均通过。证据为outputs/v81_implementation_20261101。Schema增加383 token。小任务冷修复9.60秒、暖修复5.68秒、完整重算5.65秒、缓存1.72秒；环境哈希开销明显，不能笼统称局部重算更快。

最后仅进行A/B两项真实DeepSeek Flash测试，输出临时限8192，SDK重试0，累计1.50元软件阈值。A12次、B6次响应，168648 token，空闲价usage估算0.07029904元；高峰价核算0.14059808元，未查账单。A修正500米缓冲及相交，B修正字段键并保留中间文件，两项独立核查通过。两项均未使用execution_history/local_replay，自主采用新接口及Token净收益仍未证实。A仍有一次未提供Schema调用和一次核查脚本API错误。真实测试后未再修改功能或追加实验。


## V8.1 第十三届下午场诊断复盘

2026-11-02：复盘见docs/v81-exam13-diagnostic-review.md，免费证据在outputs/v81_exam13_diagnostic_20261102。只读调查与微型反例，无收费调用，未改产品运行文件、Skills或历史成果。

实际请求中三个Skill描述与历史/重放工具均可见，两个分析相关Skill未展开不能归为注册失效。FileGDB能力须按实际API后端验证，osgeo.ogr可创建不能推定pyogrio可写。SciPy COO转CSR默认累加重复节点对，maximum转置不能恢复最小道路代价。面层plot传marker仍画面，星号图例需核对实际几何。考试生成的Jenks函数已用三值反例确认边界错误；它未进入生产制图例程，历史分数没有因本次复盘修改。

## V8.3 详细设计

2026-11-02：设计入口为docs/v8.3-design.md。本轮仅研究和免费微型验证，未实施产品功能。研究证据在outputs/v83_design_research_20261102；final-checks.json确认95个产品及测试文件内容未变。分支仍为feature/v8-workflow，HEAD为2c20dbd，main为5d82e58。

当前QGIS Python内pyogrio 0.12.1的微型OpenFileGDB写入、重读通过，包含中文、空值及字符串长ID。历史写入失败仍需按实际调用后端和完整Schema定位，不能泛化为当前环境不支持写GDB。QGIS 3.44.9最短路探针返回60米道路成本，未包含两端共50米接入；设施可达性需明确接入与道路成本口径。

Session工具消息保存execution_id，但现有模型投影会过滤该字段。V8.3建议在现有末尾动态状态中提供最多3条近期计算引用，保持Session哈希和工具返回语义。普通阶段保存不自动取得受控缓存资格，local_replay继续使用原契约。本轮未证明新描述的模型采用率或Token收益。

## V8.3 已实施

2026-11-02：实施报告为docs/v8.3-implementation-report.md。功能提交4900722位于feature/v8-workflow，main保持5d82e58。新增阶段化Python、真实I/O探针、N1～N6网络模式、分配残差和Jenks分类资产；Context仅在模型视图末尾提供最多3条真实执行引用，历史摘要增加有界输出引用和目录事实。普通工具语义及V8.1受控安全边界保持。

jenkspy 0.4.1以已核对SHA的CP312 Windows wheel、--no-deps安装到QGIS Python的Lib/site-packages，固定于绘图requirements。没有升级GDAL/NumPy或搬迁用户级GIS包。路网输入要求可信端点拓扑；未节点化同层交叉拒绝，层级相交不自动通行。浮点分类不能静默吞掉超过2^53的原始整数精度。

完整免费集合106 passed、1 live排除；后续边界9项通过。真实模型共29次响应，空闲价usage估算0.19761904元，高峰保守0.39523808元。自然修复主动查历史并保留前段成功；受控重放在明确指定工具的独立诊断中首次执行、父修订复用均成功，不能称为自然采用证明。

证据在outputs/v83_implementation_20261102。实际收费Session只在live-final/；live/是未收费的准备材料。网络自然任务因测试器160000字节单请求上限停止，分析CSV正确但未完成制图。phase-stop-audit确认停止与费用、时间或未知usage无关；未重跑该题。后续独立任务沿用同一累计账本。不要把这次部分完成归因为资金耗尽，也不要用Skill阅读次数替代结果改善。

## V8.4 等待与协同

2026-11-03：报告docs/v8.4-implementation-report.md，证据outputs/v84_implementation_20261103。finish_task复用needs_input，新增明确question/reason与partial；业务等待完成当前图轮次到END，不能把图END当作整个任务已成功。Conversation从真实工具结果派生request_id，用户回答以in_reply_to/reply_id关联原Session，保留已发现算法、计划、历史和成果。没有新增Agent工具、工作流数据库或Checkpoint版本。

CLI同Session重开会展示原问题；直接回答继续，exit/提示处EOF保留等待，cancel明确取消并保留成果。waiting命令无需模型Key/QGIS。原生计算中途不支持任意暂停。单Session仍需单写者。取消写入及已保存回答的窄恢复核对旧前缀哈希与问题ID，其他历史冲突不放行。

完整免费回归120 passed、1 live排除，288.14秒；固定回复配合真实QGIS及独立进程验证暂停、保存、补充和继续。自然模型行为未测，本轮没有新增收费授权，实际API调用0。future-natural仅是待授权材料，不能把协议测试表述成真实模型已会主动识别能力边界。

## 新 Benchmark 材料入口

2026-11-09：整理报告为outputs/benchmark_materials_20261109/README.md。timu暂存下GeoBenchX和gis-benchmarks/GABench对应两套基准；Data.zip是GeoBenchX配套输入。GeoBenchX共202题，其中120道可解GIS题、79道原工具条件下拒绝题、3道常识题。GeoAgentBench共53题，参考文件为49张PNG和1份CSV，另有3项CHECK规则。

GABench原工作区有大量修改，保留原状。50个LFS指针的对象已下载、按SHA校验并放到独立supplement/GABench目录；逐题真实输入路径见geoagentbench-index-organizer.json。下载时Git配置的127.0.0.1:18081未监听，仅本次命令关闭代理后成功，全局配置未改。原目录的指针仍在，后续须按映射准备完整输入。GeoBenchX解压根为extracted/GeoBenchX_package/Data；巴西二级行政区Shapefile缺少CRS。原评估包含工具序列比对，不能直接用原工具名匹配衡量自由Python解法。组织者索引、参考链和参考成果不能进入解题上下文。本轮模型调用0。

## GeoAgentBench 53题 V0 基线

2026-11-10：测试程序在`benchmarks/geoagentbench/`，报告及全部实验记录在`outputs/gab_v0_20261110_01/report.md`。产品冻结于main的694ebe27，实验分支为feature/geoagentbench-v0；产品、Skills及Prompt未改。百炼deepseek-v4.1-flash-1017正式收到2601次响应。53题独立运行，7题仅因传输异常沿原Session恢复，未新开整题替换成果。最终运行状态42完成、9保护停止、1超时、1存储异常；专业复核36正确、10部分、1失败、5待定、1基础设施异常。标签与正常运行结束分开。

正式usage估算49.831036元，加试跑与连接探针共52.2455652元；未知usage保留预留后保守累计60.7185712元，低于用户授权100元。未核对账单。缓存输入按百炼高峰0.2元/百万计算，不能套用直连DeepSeek价格。SDK重试关闭，显式传输重试及预留逐次留痕。

重要实验限制：Python隔离器曾禁止枚举项目父目录，真实脚本cwd下FileFinder无法导入gis_agent。日志有70次相关失败返回、涉及39题。全部收费结束后才通过小型复现确认并修正测试器；原成果保留且未收费重跑。测试必须从真实脚本目录验证项目助手导入，同时核对参考读取和网络仍被拒绝。下一轮要先统一修正后的测试器再解释V1增益，不能把消除隔离错误的收益归为产品改进。

原CHECK也需独立审查：42题官方true与线段穿建筑三角面的事实冲突；53题隐藏文件名条件不在题面；38题参考用全局OLS替代GWR。33题规定输入distances.pkl已含旅行时间，属于题库自身的信息泄漏风险。reviews.json保留逐题证据，不能将原CHECK、文件存在或工具步骤一致直接作为专业正确率。当前5项待定需方法或业务语义复核；本轮没有实施V1或第二轮模型实验。


## V9.0 环境解耦、三端骨架与执行协议重构

2026-11-18：设计文档为`docs/v9.0-refactoring-design.md`，总体蓝图为`V9_总体改造方针与落地蓝图.md`，行业调研为`主流GIS_Agent与制图方案深度调研报告.md`。重构分支为`feature/v9`（基于`d541c8a`切出），`main`与`feature/geoagentbench-v0`原样保留。按约定本轮仅落地Slice 1～3基础架构工程，不修改制图子系统与`gis-cartography` Skill，不构建重型前端，不调用收费模型API。

- **Slice 1（静态工具协议与执行器安全回执）**：将2601轮实测0调用的V8.1 `local_replay`及配套模块归档至`archive/v8_replay/`。取消动态`qgis_*`工具Schema注入，统一收敛为`search_qgis_tools`检索参数说明 + `run_qgis_algorithm(algorithm_id, parameters, project_path)`静态执行工具，运行时由算法目录动态校验必填项、未知键并附带FID重建等风险提示，保持请求前缀稳定以保护KV Cache。`persistence/json.py`的原子替换新增Windows瞬时`PermissionError`指数退避重试；`runtime/runner.py`新增进程树超时回收（`taskkill /F /T`）、首尾双向保留（前1500字符+后3500字符）错误日志截断及输出目录递归`os.walk`新增文件发现；文件写入工具增加受控工作根边界校验；`finish_task`增加0字节空文件拦截。
- **Slice 2（快速数据头与概览抽样探针）**：新增`gis_agent/runtime/inspect_fast.py`与`probe.py`，`inspect_data`优先经`pyogrio`与`rasterio`直接读取矢量图层目录、要素计数、CRS单位、前200要素几何有效性抽样，以及栅格波段`dtype`、`colorinterp`、`nodata`、`scale`、`offset`、`unit`和`256×256`降采样概览值域，未命中快速路径时回退PyQGIS。
- **Slice 3（`uv`环境管理、纯Python状态循环与三端适配骨架）**：新增`pyproject.toml`与`uv.lock`，按最小核心、`cli`、`vision`、`geo`、`dev`分组声明依赖。新增`gis_agent/core/loop.py`（`AgentLoopRunner`）与`gis_agent/persistence/checkpoints.py`（`SqliteCheckpointer`），移除`gis_agent/`内全部`langgraph`与`tokenizers`硬依赖及`Pillow`顶层硬导入，支持带窄窗口核对的断点对齐（仅当Session末尾工具批次消息完整闭合且旧前缀一致时对齐检查点，不自动重放未闭合副作用工具）。`GIS_AGENT_QGIS_DIR`改为可选配置；新增`gis_agent/adapters/{cli.py, harness_mcp.py, stubs.py}`三端入口骨架。

本地离线全量回归通过（`tests/`与`benchmarks/geoagentbench/test_runner.py`），收费`live`项排除，实际收费API调用为0。Slice 4小样本线上消融实验待后续按需授权启动。


## V9.0 方案 A 实测与 V9.0.1 双环边界收口

2026-11-18（续）：授权启动方案 A（GABench 6道痛点题`04,09,12,25,32,49` + GeoBenchX 3道未见盲测题），共用SQLite原子账本（上限15元），9题加探针实估合计`6.0233`元，KV Cache命中率`93.6%～95.3%`，报告见`outputs/v9_plan_a_20261118/report.md`。GABench 6题由V0的`1正确/3部分/1超时失败/1存储崩溃`提升至`3正确/3部分/0失败/0崩溃`（第49题全程0报错完成，第25题补齐图件且像元误差0，第09题900s超时回收后自主改写56瓦片无损分块算出`47.57%`对标参考值`47.93%`）；GeoBenchX盲测中缺数据题`TASK_138450` 14轮0幻觉返回`blocked`，积雪Amtrak题`TASK_883928`独立复算531站及前五州零误差。

随后按`docs/v9.0.1-interface-refinement-design.md`完成V9.0.1收口（0收费调用）：
1. 新增`gis_agent/runtime/paths.py`统一`package_dir()`、`import_root()`与`package_resource()`，消除源码目录层级`parents[2]`硬编码，兼容虚拟环境、QGIS插件目录及冻结打包。
2. `runtime/runner.py`、`integrations/qgis/client.py`、`agent.py`与`application.py`打通线程安全`cancel_event`。执行器以最长 0.2 秒的等待步长检查停止信号，随后回收进程树，闭合会话消息和检查点。`open_conversation`支持显式`api_key`、`on_event`、`extra_tools`、`workspace_context`参数。`tool_finished`事件携带`outputs`。
3. `adapters/harness_mcp.py`落地纯标准库JSON-RPC 2.0 STDIO MCP服务端（支持行分隔与`Content-Length`帧，注册`gis-agent-mcp`入口并新增`list_gis_skills`）。
4. 根据实测反馈将`run_python_script`单次`timeout_sec`收紧为默认`180s`、上限`600s`，并在`terrain-imagery.md`补充含加性常数光谱指数（如SAVI）的定标量纲提示。

2026-11-18 离线复验：在项目 Conda 环境运行 `python -B -m pytest tests benchmarks/geoagentbench/test_runner.py -k "not live" -q -p no:cacheprovider`，119 项通过，1 项被筛除。停止用例补测确认派生进程已退出，当轮 1.105 秒内返回，同一会话可继续使用。0.2 秒是轮询等待步长，进程树回收本身的耗时未单独计量。用项目现有 QGIS 配置启动独立 MCP 进程，`list_gis_skills`、`probe_gis_environment` 和 `inspect_data` 均返回成功，正确读取含 1 个点的 GeoJSON。运行空间数据工具时，`--project` 指向的新目录需要配好 GIS Python，可通过 `GIS_AGENT_QGIS_DIR` 或 `GIS_AGENT_PYTHON` 指定。


## V9.0.2 独立 `uv` 运行环境与 90% 上下文自适应压缩

2026-11-18（续）：补齐 Carbon 蓝图第 8、9 两项底座尾巴（0 收费调用）：
1. **按模型可用输入窗口 90% 触发主动压缩**：借鉴 `learn-claude-code` 上下文水位设计并在 `ContextConfig` 新增 `compact_ratio: float = 0.90`（支持 `GIS_AGENT_COMPACT_RATIO` 覆写）。`ContextManager.prepare` 在超过 `int(request_token_limit * compact_ratio)` 且存在可折叠旧工具批次时提前触发摘要压缩，不再与固定 `10k/100k` 魔数绑定；低于 90% 时保持前缀不变以保护 KV Cache。
2. **脱离 Conda 的独立 `uv` 运行验证**：更新测试套件中 5 处残留 `langgraph` 校验器导入改用 `SqliteCheckpointer`/`MemoryCheckpointer`，将 `.venv/` 加入 `.gitignore`；实机执行 `uv sync --extra cli --extra dev --extra geo` 在独立 `.venv` 装齐 42 个完整科学计算包并全量脱离 Conda 运行 `tests/` 与 `benchmarks/geoagentbench/test_runner.py`（`-k "not live"`），**122 项全部通过**（`152.83s`），含无桌面 QGIS 条件下用独立 GeoPython 完成 `inspect_data` 与 `export_figure` 成图验收。

## V9.0.2 空间 Skills 拆分升级、自动体征注入与测试集收口

2026-11-18（续）：设计文档为`docs/v9.0.2-spatial-skills-and-test-consolidation-design.md`（0 收费调用，未改动`gis-verification`与`gis-cartography`核心策略及绘图运行时）：
1. **零轮次自动空间体征与运行能力发现**：
   - `gis_agent/runtime/inspect_fast.py`新增`attach_spatial_vitals`与`--vitals`跨解释器探针，接入`run_python_script`（新产物项附带可选`outputs[].spatial`）和`run_qgis_algorithm`（附带可选`spatial_vitals`，保持既有`outputs`端口映射字典兼容性），每次最多摘要前 3 个空间文件（CRS/单位、要素数或像元网格、`dtype`、`nodata`、`valid_ratio`、极值与无效几何抽样数），不做业务结论判定。
   - `gis_agent/runtime/probe.py`新增缓存式`runtime_capabilities(launcher, has_qgis_process)`，`agent.py`与`application.py`将其写入末尾动态`business`字段以保护前缀 KV Cache；同时在`qgis_python.py`中为非`.bat`/`.cmd`的独立 Python 解释器剔除宿主机残留`PROJ_LIB`/`PROJ_DATA`/`GDAL_DATA`变量，避免外部 PostGIS/PROJ 数据库污染内置轮子坐标系解析。
2. **7 领域 Skills 拆分与双环境路由**：
   - 原单一`gis-spatial-analysis`拆分为 5 个垂直 Skill，与保留的`gis-verification`、`gis-cartography`合计 **7 个 Skills**：`gis-data-io-and-staging`（多图层 I/O、`pyogrio`/DuckDB 下推与分阶段持久化）、`gis-vector-and-network`（CRS 分离、多重连接、Halo 瓦片分块与有向图路网可达/选址）、`gis-raster-and-imagery`（网格对齐、NDVI/SAVI 定标量纲、分窗 Zonal Stats 与配准可信度，附`raster_align_index.py`）、`gis-terrain-and-hydrology`（DEM/DSM 分离、GRASS/ESRI D8 编码、Kahn 拓扑汇流与连通淹没容积，附`hydrology_routing.py`）和`gis-spatial-statistics`（Tier B `esda`/`libpysal`/`pykrige`/`sklearn` 与 Tier A `scipy`/`numpy` 双路由降级及空间块交叉验证，附`spatial_stats_examples.py`）。全部跨引用路径、26 条`tests/fixtures/skills_applicability.json`用例均同步更新并在`.venv`（Tier B）及桌面 QGIS（Tier A）实测通过。
3. **测试集收口与快慢分层**：
   - 将原零散版本测试文件合并收敛为 4 个域模块（`test_core_loop.py`、`test_runtime_and_tools.py`、`test_skills_and_cartography.py`、`test_adapters.py`）配合`benchmarks/geoagentbench/test_runner.py`（共 127 项：126 离线 + 1 live）。在`pyproject.toml`与`tests/conftest.py`注册`slow`/`live`标记。
   - 本机`.venv`验证：快速层`-m "not slow and not live"`通过 **81 passed, 46 deselected**（`27.05s`）；`tests/`全部 4 个域模块共 115 项（含全部真实 QGIS 集成测试）与新增 V9.0.2 单测/Skill 示例全数通过；`benchmarks/geoagentbench/test_runner.py`单独重跑 10 项全数通过（`6.86s`，此前全量并跑时第 162 行曾偶发一次 Windows `worker.lock` 并发写锁竞争`PermissionError`）。

## V9.0.3 分层异常信号、非对称门控、防停滞与 `gis-verification` 升级

2026-11-18（续）：结合 CCF-A 顶会研究（*CRITIC* ICLR'24、*AgentAbstain* NeurIPS'26 Oral、*Coding Agents Don't Know When to Act* ETH SRI、*HALLMARK* / 验证器误报研究、*RepairAgent* ICSE、*GeMTest/Testora* 蜕变测试）与 Codex 审核意见完成开发，设计文档见`docs/v9.0.3-verification-and-abstention-design.md`（`gis-cartography`留待 V9.0.4 专题改动；0 收费模型调用）：
1. **分层异常信号器（不把症状当通用失败判定）**：
   - `gis_agent/runtime/inspect_fast.py`新增`detect_spatial_anomalies(spatial)`，在`attach_spatial_vitals`与`run_qgis_algorithm`挂载三级客观信号：`L1 notice`（`UNSCALED_HIGH_DN`、`PARTIAL_INVALID_GEOMETRY`）、`L2 warning`（`ZERO_FEATURES`、`MISSING_CRS`、`ALL_INVALID_OR_EMPTY`、`ALL_NODATA_RASTER`、`CONSTANT_RASTER_SURFACE`）与`L3 fatal`（`CORRUPT_OR_UNREADABLE`）；健康产物零额外 token。
2. **Confirm-Once 非对称终结门控与防停滞循环监测**：
   - `gis_agent/tools/planning.py`为`finish_task`新增可选参数`acknowledged_anomalies`与`evidence`；`gis_agent/agent.py`的`accept_finish`对`completed`仅硬拦截致命损坏（`fatal`）及最近失败未重跑产物，对未核实 L2 告警温和打回提醒一次，经模型修复、独立读回核查或传`acknowledged_anomalies`确认后立即放行，彻底消除对合法空筛选/局部网格的误杀；对`blocked`/`needs_input`允许首轮只读探查后零写入直接诚实上报。
   - `agent.py`新增无检查点Schema变更的即时防停滞统计`_stagnation_alert`，通过动态尾部`business["stagnation_alert"]`在连续同类失败 >= 2 次注入`warn`、>= 5 次注入`escalate`止损提示（成功执行即清除），并同步更新`gis_agent/prompts/system.j2`。
3. **`gis-verification` Skill 与蜕变不变量取证升级**：
   - 保留原有 5 个验证脚本与`checks.md`锚点，升级`SKILL.md`并新增`references/metamorphic-and-abstention.md`与双环境脚本`scripts/metamorphic_checks.py`（守恒残差、行序置换不变性、尺度缩放不变性、`intersects`/`within`/`covered_by`边界差集对照），已在 `.venv`（Tier B）与 `E:\exe\qgis`（Tier A）实测同值通过。
4. **离线回归验证（`.venv` + 桌面 QGIS）**：
   - `tests/`快速分层`-m "not slow and not live"`：**74 passed, 46 deselected**（`24.91s`）。
   - `tests/`全量离线`-k "not live"`：**119 passed, 1 deselected**（`170.32s`，含全部桌面 QGIS 集成与新增 V9.0.3 机制/Skill 单测）。
   - `benchmarks/geoagentbench/test_runner.py`：**10 passed**（`6.70s`，此前串联跑时第 162 行曾偶发一次既有 Windows `worker.lock` 竞争 `PermissionError`）。


## V9.0.4 技能泛化、主动合议澄清、空转收敛与评测运行器 `.venv` 独立适配

2026-11-19：基于 V9.0.3 组合 1（`.venv` 独立模式 15 题：9 题 GABench + 6 题 GeoBenchX 盲测，总峰值结算 `14.1748` 元）实测复盘，完成 V9.0.4 设计（`docs/v9.0.4-generalization-abstention-and-efficiency-design.md`）与代码实施（保持 `gis-cartography` 冻结，0 付费线上测试）：
1. **事件驱动 `gis-verification` 触发与三分支主动合议**：
   - `gis_agent/prompts/system.j2` 与 `gis_agent/tools/planning.py` 增设与 `gis-cartography` 对等的 `gis-verification` 调用引导，将首轮只读侦察后的路线明确为三分支（合法近似直接完成并披露、局部/粗粒度代理或口径分歧优先调 `needs_input` 发起带选项的合议澄清、主体彻底缺失再调 `blocked`）；`gis-verification/SKILL.md` 与 `metamorphic-and-abstention.md` 补充正反成对判例以防误拒。
   - `gis_agent/agent.py` 新增 `_has_spatial_anomalies`，仅在工具返回空间异常或 `finish_task` 被计划/异常门控拦截时附带单行 `verification_hint`（常态零额外 token）。
2. **空间 Skills 泛化与大几何复杂度门控**：
   - `gis-raster-and-imagery/SKILL.md` 将加性常数指数表述抽象为通用物理量纲与标度核查原则；`gis-vector-and-network/SKILL.md` 与 `gis-data-io-and-staging/SKILL.md` 补充大要素/复杂多边形先做 `<10s` 小样本基准测速再切换 Tile+Halo 分块或栅格化的规则。
3. **超时跨文件名归并与成功态原地空转感知**：
   - `gis_agent/tools/qgis_python.py` 将 `run_python_script` 默认 `timeout_sec` 收紧至 `120s`（上限 `600s`）；`agent.py` 在 `_failure_signature` 中将 `timed_out=True`/`status=='timed_out'` 统一归并为 `<tool>:TIMEOUT`（解决切换脚本名连踩超时不触发告警的盲区）。
   - `agent.py` 新增 `_spinning_alert`，检测同脚本连续 `>=4` 次纯样式微调或 `read_image >=5` 次重复审图并在末尾动态 `business["efficiency_hint"]` 中温和提示收敛（严格保持 KV Cache 前缀不变）。
4. **评测运行器 `.venv` 独立模式与无轮次硬切刀对齐**：
   - `benchmarks/geoagentbench/`（`common.py`、`child_entry.py`、`worker.py`、`run.py`）与 `benchmarks/geobenchx_pilot.py` 完善 `--standalone` 隔离沙箱（授权 `.venv` `sys.prefix` 与 `-c probe_current_python` 探针并剥离宿主机 `PROJ_LIB`/`GDAL_DATA`），同时移除 `max_calls=50/80` 硬轮次切刀（`max_calls=None`），改为 `task_budget_cny=4.0` 元峰值预算与墙钟护栏主导控制。
5. **离线回归验证（`.venv` + 桌面 QGIS，最后一次源码编辑后）**：
   - `tests/` 快速分层 `-m "not slow and not live"`：**78 passed, 46 deselected**（`34.04s`）。
   - `tests/` 全量离线 `-k "not live"`：**123 passed, 1 deselected**（`180.83s`，含全部桌面 QGIS 集成与 V9.0.4 新增机制单测）。
   - `benchmarks/geoagentbench/test_runner.py`：**11 passed**（`7.64s`）。