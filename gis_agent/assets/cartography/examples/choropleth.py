"""设计JSON必需：brief、output_dir、crs、breaks、colors。
可选：title、legend_title、size_mm、label_field、label_size_pt、details。
"""
import json
import math
import sys
from pathlib import Path

settings = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
sys.path.insert(0, settings.get("runtime_dir", str(Path(__file__).resolve().parents[3] / "integrations" / "qgis")))

from cartography_runtime import create_layout, export_layout, initialize_qgis, load_vector, prepare_map
from qgis.core import (
    QgsExpression, QgsFeatureRequest, QgsFillSymbol, QgsProject,
    QgsRuleBasedRenderer, QgsVariantUtils,
)


def render(design_path: str) -> dict:
    design, brief, output = prepare_map(design_path, __file__)
    title = design.get("title", brief["question"])
    app, fonts = initialize_qgis(design.get("font_files"), title + "图例无数据0123456789−°")
    project = QgsProject.instance()
    try:
        source = brief["inputs"][0]
        layer = load_vector(source)
        field = source["field"]
        if layer.fields().indexFromName(field) < 0:
            raise ValueError(f"字段不存在：{field}")
        values = [
            float(feature[field]) for feature in layer.getFeatures(
                QgsFeatureRequest().setSubsetOfAttributes([field], layer.fields()).setFlags(QgsFeatureRequest.NoGeometry)
            ) if not QgsVariantUtils.isNull(feature[field])
        ]
        breaks, colors = design["breaks"], design["colors"]
        if not values or any(not math.isfinite(value) for value in values):
            raise ValueError("专题字段缺少有效有限数值。")
        if len(breaks) < 2 or len(colors) != len(breaks) - 1 or any(a >= b for a, b in zip(breaks, breaks[1:])):
            raise ValueError("分类边界需严格递增，颜色数量需等于区间数量。")
        if min(values) < breaks[0] or max(values) > breaks[-1]:
            raise ValueError("分类边界没有覆盖全部有效值。")
        renderer = QgsRuleBasedRenderer(QgsRuleBasedRenderer.Rule(None))
        name = QgsExpression.quotedColumnRef(field)
        for index, (low, high, color) in enumerate(zip(breaks, breaks[1:], colors)):
            symbol = QgsFillSymbol.createSimple({
                "color": color, "outline_color": design.get("border_color", "#ffffff"),
                "outline_width": str(design.get("border_mm", 0.2)), "outline_width_unit": "MM",
            })
            expression = f"{name} {'>=' if index == 0 else '>'} {low} AND {name} <= {high}"
            rule = QgsRuleBasedRenderer.Rule(symbol)
            rule.setFilterExpression(expression)
            rule.setLabel(f"{low:g} – {high:g} {source.get('unit', '')}".strip())
            renderer.rootRule().appendChild(rule)
        missing = QgsRuleBasedRenderer.Rule(QgsFillSymbol.createSimple({"color": "#dddddd", "outline_color": "#ffffff"}))
        missing.setFilterExpression(f"{name} IS NULL")
        missing.setLabel("无数据")
        renderer.rootRule().appendChild(missing)
        layer.setRenderer(renderer)
        project.addMapLayer(layer)
        if design.get("label_field"):
            from cartography_runtime import set_labels
            set_labels(layer, design["label_field"], fonts["primary_family"], design.get("label_size_pt", 10))
        layout = create_layout(project, [layer], design, title, fonts["primary_family"])
        return export_layout(
            project, layout, output, fonts=fonts,
            inputs=[design_path, __file__, design["brief"], *(item["source"].split("|")[0] for item in brief["inputs"])],
            formats=brief.get("medium", {}).get("format", ["png", "qgz"]), details=design.get("details"),
        )
    finally:
        project.clear()
        app.exitQgis()


if __name__ == "__main__":
    print(json.dumps(render(sys.argv[1]), ensure_ascii=False))

