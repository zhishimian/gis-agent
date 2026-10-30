"""简报inputs依次为区域面和设施点；设计JSON必需：brief、output_dir、crs。
可选：title、legend_title、size_mm、marker_mm、marker_color、label_field、details。
"""
import json
import sys
from pathlib import Path

settings = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
sys.path.insert(0, settings.get("runtime_dir", str(Path(__file__).resolve().parents[3] / "integrations" / "qgis")))

from cartography_runtime import create_layout, export_layout, initialize_qgis, load_vector, prepare_map, set_labels
from qgis.core import QgsFillSymbol, QgsMarkerSymbol, QgsProject, QgsSingleSymbolRenderer, QgsWkbTypes


def render(design_path: str) -> dict:
    design, brief, output = prepare_map(design_path, __file__)
    title = design.get("title", brief["question"])
    app, fonts = initialize_qgis(design.get("font_files"), title + "图例0123456789−°")
    project = QgsProject.instance()
    try:
        areas, points = [load_vector(item) for item in brief["inputs"][:2]]
        if QgsWkbTypes.geometryType(points.wkbType()) != 0 or QgsWkbTypes.geometryType(areas.wkbType()) != 2:
            raise ValueError("设施示例需要区域面和设施点。")
        areas.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({
            "color": design.get("area_color", "#eeeeee"), "outline_color": "#bbbbbb", "outline_width": "0.15",
        })))
        points.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({
            "name": "circle", "color": design.get("marker_color", "#555555"),
            "size": str(design.get("marker_mm", 2.4)), "size_unit": "MM",
            "outline_color": "#ffffff", "outline_width": "0.2", "outline_width_unit": "MM",
        })))
        project.addMapLayer(areas)
        project.addMapLayer(points)
        if design.get("label_field"):
            set_labels(points, design["label_field"], fonts["primary_family"], design.get("label_size_pt", 10))
        layout = create_layout(project, [points, areas], design, title, fonts["primary_family"])
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

