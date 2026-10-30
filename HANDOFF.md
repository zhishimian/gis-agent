# 项目交接

## 当前实现：V7.9

在V7.8提交3054e0c基础上完成单Agent优化，未回退版本。入口仍为main.py，application组装能力，LangGraph执行model/tools/finish。默认验证与制图委派、候选修正链及强制二次复核已经移除。旧Session、输出和评测材料保留。

专业方法在gis_agent/skills/gis-verification和gis-cartography。System只给短索引，正文及参考用read_file按需加载。验证关注实际样本、单位、稳定身份和高传播风险；制图先完成全部草稿，按真实缺陷继续修正。没有新增Skill框架或大型RAG。

Context将动态运行数据放在历史后方。Schema按名称稳定排序，单独控制Schema预算；被移出可调用集合的算法需重新搜索。保留原始消息、完整工具批次、外置结果及摘要来源保护。DeepSeek的reasoning_content按现有协议保留。本次真实出图小任务输入缓存命中率97.46%；成本归因仍需同条件对照。

新增edit_file唯一替换和可选文件哈希核对，search_text返回行号及可供read_file继续读取的字符位置。目录列表分页并提供绝对路径。文本读取哈希来自同一批字节，编辑保留CRLF。QGIS检索默认三项，精确ID优先；算法重建主键/FID等警告进入工具说明。布局算法支持顶层project_path工程上下文。

inspect_data兼容单source并支持sources批量接入；每个数据单独报告状态。summarize_fields提供空值、唯一值、数值统计、稳定键和可选几何检查。check_spatial_relation测量外键归属与指定谓词，不自动选择业务归属规则。属性统计允许无CRS表格，空间测量要求两层具有相同有效CRS。

run_python_script继续使用独立QGIS Python，保留快照、退出码、日志和哈希。脚本可向环境变量GIS_AGENT_RESULT_PATH指定的文件写JSON，工具返回result；stdout只作日志，不要求末行格式。结构化结果存在时成功响应省略重复stdout，完整日志仍可回读。退出失败或JSON无效时ok保持false。

render_map复用分级设色和设施例程，自动使用配置字体和运行时。cartography_runtime提供set_map_layers、export_layout、export_project及write_result。图层按从上到下排列，主题放在背景上方；结构化结果提供maps.layers_top_first、files、preview与artifacts。工程重开导出使用独立空目录，避免覆盖源工程或混入旧图件。

render_map仅复用输入、字体、设计、例程、运行时和产物哈希仍一致的结果；变化后重新渲染。Windows字体路径先规范化再比较，避免WINDOWS/Windows引起缓存误失效。Shapefile指纹包含必要旁文件；目录型数据可导出，当前渲染复用对目录输入保守地重新执行。

finish_task保留四种状态，增加artifacts和unresolved。成果支持文件或数据集目录。completed检查路径和未完成计划，不再要求独立角色。只读问答可以answer；未知事项和执行阻碍如实报告。程序检查和语义正确性分别表达。

## 环境与恢复

- Agent解释器：D:/ac/envs/gis-agent/python.exe。专业依赖由QGIS自带Python承载，Agent环境不导入qgis。
- QGIS目录通过GIS_AGENT_QGIS_DIR配置，启动器可分别设置。记录目录相对项目解析。
- 2026-10-30通过现有QGIS Python实际导入确认：Matplotlib 3.10.8、GeoPandas 1.0.1、Rasterio 1.4.3、Pandas 2.3.0、NumPy 2.4.3可用。这是本机已安装状态，其他机器需检测；尚未据此验证绘图质量或跨库运算兼容性。可先复用同一GIS执行环境，无需为这些库立即增设解释器。
- 同日进一步核对：Agent Conda未安装上述地理/绘图库。QGIS Python的GeoPandas、Rasterio和Pandas来自用户级Python312目录；Rasterio报告GDAL 3.9.3，Pyogrio报告3.12.3。基础导入成功不代表完整I/O兼容或可直接发布。matplotlib-scalebar、matplotlib-map-utils、Cartopy、mapclassify、adjustText均未发现。
- 另一个候选环境D:/ac/envs/gis-benchmark/python.exe为Python 3.11.17。2026-10-30实际导入Matplotlib 3.11.2、GeoPandas 1.2.0、Rasterio 1.4.4、mapclassify 2.10.0、NumPy 2.4.6、Pandas 3.0.6、Shapely 2.2.0、PyProj 3.7.2成功，模块均来自该环境目录。Rasterio/Pyogrio报告GDAL 3.10.3/3.12.4；未发现qgis或osgeo模块。未运行制图或I/O验收，未将它切换为项目默认后端。
- 模型支持DeepSeek、OpenAI及兼容Chat Completions的服务，切换时核对地址、模型、窗口、tokenizer和视觉预算。SDK默认重试三次，trust_env=False。
- 字体经QGISConfig.font_files或GIS_AGENT_FONT_FILES配置；Windows默认显式加载雅黑和Arial，不复制字体文件。
- read_image保留整图、裁剪、内容哈希与图片快照。图片只进入下一次模型请求；重绘后需读取当前版本。限制为8MiB、边长8192、1600万像素。
- 每批工具提交SQLite并自动续跑。recursion_limit=16只约束单段，任务无固定总响应上限。
- V7.9检查点version=79。旧版待续跑检查点明确拒绝自动重放，保留记录并用新会话接续已有成果。Session与检查点哈希不一致也停止重放。
- Session保存事实，SQLite保存执行状态。started但未确认结束的工具不自动重复执行。read_record供恢复检查，load验证完整工具批次。
- .memory和sessions属于本机记录。长期记忆和窗口摘要继续可选，未扩展自动记忆策略。

## 本地验证

2026-10-29：修改前离线基线24项通过。迁移旧协议测试并加入真实失败点后，当前离线26项通过，真实API项1项未运行。

PowerShell命令：

```powershell
& 'D:\ac\envs\gis-agent\python.exe' -B -m pytest tests -k "not live" -v -p no:cacheprovider
```

覆盖：稳定请求前缀、结果资产篡改、局部编辑冲突和CRLF、真实SDK离线请求格式、结构化JSON与失败状态、批量数据和属性表、稳定键/空间归属、同一个Agent完成QGIS缓冲和只读问答、固定SEGMENTS=32的500米缓冲精度、FID警告、图层顺序、工程上下文导出、有效渲染复用/失效、工程重开、NoData及设计变更。模型调用由固定响应或本地MockTransport隔离，GIS运算使用真实QGIS。

原有长任务超过30次响应、SQLite恢复、版本保护、工具中断不重放、Memory和摘要来源检查继续通过。未调用收费模型API，未运行整卷。缓存实际命中、模型自主使用Skill和端到端成本仍待真实小任务验收。历史复杂PyQGIS脚本退出崩溃的唯一根因尚未定位；新例程本机检查正常，原生失败继续保留真实状态。

## 历史材料与后续

- docs/v7.8-comprehensive-audit.md审计的是V7.8；112轮制图逐项记录和请求重建在outputs/v78_audit_20261029。历史源码指纹不能作为V7.9当前指纹使用。
- 首次缓冲47次响应、约0.788251元；V7.7复测21次、约0.224885元。两轮SEGMENTS为32/5，面积近似误差为0.0402%/1.6368%，后续对照需固定精度。记录在两个buffer500实验目录。
- 整卷outputs/bpm_v77_paired_20261029_01在首次独立验证前因402中断；粗批63/100，分析59/80，验证后分数缺失。不能把相同A/B保护快照当成前后对照。
- 已知业务风险：人均指标方向、Processing重建FID、空间连接多重匹配、网络顶点吸附和直线回退。参考解析自身也有路网未解和人口总量偏差，继续按原始题意与数据核查。
- 固定精度500米缓冲加一幅地图已实测，记录见下节。下一轮先处理本次已暴露的执行问题，再按相同提示复测。
- V8.0工作树仍为后续设计。子Agent和RAG的重新引入需要真实检出率、并行收益或知识漏检证据。
- docs/v7.9.0-cartography-design.md已完成迁移设计，尚未实施。方案保留统一GIS解释器和run_python_script，开放Matplotlib自由构图，退出默认PyQGIS Layout与QGZ布局交付。具体模块、Skill草案、兼容门槛和对照计划见该文档。

## V7.9真实缓冲和出图测试

2026-10-29：outputs/buffer500_map_v79_20261029_1e780d。真实DeepSeek Flash，关闭记忆，沿用原始点数据副本，SEGMENTS=32，新增PNG与QGZ。112次响应，输入7430736、输出63205、总7493941 token，缓存命中7242240，未命中188496；按当时空闲价格估算0.5861608元，耗时554.31秒。API全部200，工具24次返回失败。未修改源码或测试，原始输入哈希未变。

最终缓冲有效且保留id，边界顶点半径500m，面积近似误差0.040154685%。PNG中文和点面层序正常，QGZ最终重开渲染通过。性能目标未达成，主要耗在自定义布局与工程重开排错。本轮增加了出图，不能与历史纯缓冲总费用作同条件结论。

复用约束：自定义布局使用addLayoutItem、attemptMove、attemptResize和zoomToExtent。QGraphicsItem的setRect/setPos曾让导出PNG正常、QGZ重开地图框为0、范围为NaN；project.read成功和导出返回码不足以证明布局可用。独立核对应包含重开后的尺寸、有限范围和实际渲染。优先复用已有布局方法。

待处理：含竖线的图层URI传入Windows批处理启动器会被shell解释；模型脚本还出现Processing初始化遗漏、小写参数键、猜图层名、多处布局API错误。run_python_script的工作目录是脚本目录，独立脚本导入项目运行时需给出准确路径。现成Skill和例程已提供，模型本轮仍先写大型自定义脚本。comparison.md、responses.md、failures.json保留成本与失败明细。
