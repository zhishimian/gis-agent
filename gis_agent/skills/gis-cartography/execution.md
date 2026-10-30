# QGIS执行与设计

运行时位于本文件的 `../../integrations/qgis/cartography_runtime.py`。所有PyQGIS工作由run_python_script的独立QGIS Python执行。
通用脚本初始化QgsApplication([], False)，调用initQgis；需要Processing时加入prefixPath()/python/plugins并调用Processing.initialize。
计算放在main局部函数中，返回后清理工程并调用exitQgis。保留真实异常，不使用os._exit绕过失败。
普通输出用print。结构化结果写入环境变量GIS_AGENT_RESULT_PATH指向的UTF-8 JSON文件，stdout内容不影响结果解析。

## 现成制图入口

先写brief.json：

```json
{"question":"哪些区域覆盖率较低？","inputs":[{"source":"<绝对数据路径>","field":"coverage","unit":"%"}],"medium":{"format":["png","qgz"]}}
```

再写design.json，调用render_map(design_path, template)。

- 公共字段：brief绝对路径、output_dir独立输出目录、crs，例如EPSG:32650。
- choropleth：brief.inputs[0]是面；design另含breaks严格递增且覆盖全部有效值，colors数量等于区间数。
- facilities：brief.inputs依次是区域面、设施点；可用marker_mm、marker_color、label_field。
- 可选：title、legend_title、size_mm、extent、label_size_pt、details。
- details例：[{"name":"密集区","region_mm":[10,30,60,50],"dpi":300}]。区域为页面毫米坐标x/y/宽/高。

字体和运行时路径由环境及项目入口提供，默认不必写进设计。特殊字体由用户配置GIS_AGENT_FONT_FILES。
输出包括PNG、预览、QGZ、QML、QPT和程序生成的manifest。result.files保存相对文件名，result.preview及artifacts给出完整路径。
同一设计需修改时用edit_file，只改必要参数。相同输入设计重复调用render_map可复用仍有效的现有结果。

## 自定义布局与工程重开

按需阅读cartography_runtime中的initialize_qgis、set_map_layers、create_layout和export_layout签名。
initialize_qgis()显式加载配置字体；export_layout自动写结构化结果并返回实际图层顺序。
定制版面直接编写PyQGIS脚本。用export_project(project_path, output_dir, layout_name, formats)重开既有工程并导出；目标目录与源工程目录分开。
整图预览与最终输出分开保存。read_image限制8MiB、边长8192、1600万像素；超限时从布局导出较小预览或局部。
