import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from qgis.PyQt.QtCore import QRectF, QT_VERSION_STR
from qgis.PyQt.QtGui import QFont, QFontDatabase, QRawFont
from qgis.core import (
    Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsLayoutExporter, QgsLayoutItemLabel, QgsLayoutItemLegend, QgsLayoutItemMap,
    QgsLayoutItemScaleBar, QgsLayoutPoint, QgsLayoutSize, QgsPrintLayout,
    QgsPalLayerSettings, QgsProject, QgsReadWriteContext, QgsRectangle,
    QgsScaleBarSettings, QgsTextBufferSettings, QgsTextFormat, QgsVectorLayer, QgsVectorLayerSimpleLabeling,
)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def initialize_qgis(
    font_files: list[str], sample: str = "地图0123456789 −°",
) -> tuple[QgsApplication, dict[str, Any]]:
    app = QgsApplication([], False)
    app.initQgis()
    if not font_files:
        raise ValueError("请通过 GIS_AGENT_FONT_FILES 配置本机字体文件。")
    families = []
    files = []
    for value in font_files:
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"字体文件不存在：{path}")
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            raise ValueError(f"字体加载失败：{path}")
        families.extend(QFontDatabase.applicationFontFamilies(font_id))
        files.append({"path": str(path), "sha256": digest(path)})
    font = QFont(families[0], 10)
    raw = QRawFont.fromFont(font)
    missing = sorted({char for char in sample if not char.isspace() and not raw.supportsCharacter(char)})
    if missing:
        raise ValueError(f"字体 {families[0]} 缺少字符：{''.join(missing)}")
    app.setFont(font)
    return app, {"primary_family": families[0], "families": families, "files": files}


def prepare_map(design_path: str, script_path: str) -> tuple[dict, dict, Path]:
    path = Path(design_path).resolve()
    design = json.loads(path.read_text(encoding="utf-8"))
    brief_path = Path(design["brief"]).resolve()
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    output = Path(design["output_dir"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    for source, relative in (
        (brief_path, "brief.json"), (path, "design.json"),
        (Path(script_path).resolve(), "scripts/render.py"),
    ):
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source != target:
            shutil.copy2(source, target)
    return design, brief, output


def load_vector(item: dict) -> QgsVectorLayer:
    source = item["source"]
    if item.get("layer") and "|layername=" not in source:
        source += "|layername=" + item["layer"]
    layer = QgsVectorLayer(source, item.get("name", item.get("layer", Path(item["source"]).stem)), "ogr")
    if not layer.isValid() or not layer.crs().isValid():
        raise ValueError(f"图层或 CRS 无效：{source}")
    return layer


def set_labels(layer: QgsVectorLayer, field: str, family: str, size: float) -> None:
    if layer.fields().indexFromName(field) < 0:
        raise ValueError(f"标注字段不存在：{field}")
    raw = QRawFont.fromFont(QFont(family))
    characters = {char for feature in layer.getFeatures() for char in str(feature[field]) if not char.isspace()}
    missing = sorted(char for char in characters if not raw.supportsCharacter(char))
    if missing:
        raise ValueError(f"标注字体缺少字符：{''.join(missing)}")
    text = QgsTextFormat()
    text.setFont(QFont(family))
    text.setSize(size)
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(0.4)
    text.setBuffer(buffer)
    settings = QgsPalLayerSettings()
    settings.fieldName = field
    settings.setFormat(text)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)


def create_layout(
    project: QgsProject, layers: list, design: dict, title: str, family: str,
) -> QgsPrintLayout:
    crs = QgsCoordinateReferenceSystem(design["crs"])
    if not crs.isValid():
        raise ValueError("设计中的显示 CRS 无效。")
    project.setCrs(crs)
    project.setEllipsoid("WGS84")
    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName("cartography")
    width, height = design.get("size_mm", [297, 210])
    if width < 160 or height < 110:
        raise ValueError("此示例需要至少 160×110 mm 的页面，请调整示例版面。")
    layout.pageCollection().pages()[0].setPageSize(QgsLayoutSize(width, height))
    project.layoutManager().addLayout(layout)
    heading = QgsLayoutItemLabel(layout)
    heading.setId("title")
    heading.setText(title)
    text = QgsTextFormat()
    text.setFont(QFont(family))
    text.setSize(design.get("title_size_pt", 16))
    heading.setTextFormat(text)
    layout.addLayoutItem(heading)
    heading.attemptMove(QgsLayoutPoint(10, 5))
    heading.attemptResize(QgsLayoutSize(width - 20, 20))
    map_item = QgsLayoutItemMap(layout)
    map_item.setId("map_main")
    layout.addLayoutItem(map_item)
    map_item.attemptMove(QgsLayoutPoint(10, 30))
    map_item.attemptResize(QgsLayoutSize((width - 20) * 0.70, height - 45))
    map_item.setCrs(crs)
    map_item.setLayers(layers)
    map_item.setKeepLayerSet(True)
    extent = QgsRectangle()
    for layer in layers:
        extent.combineExtentWith(QgsCoordinateTransform(layer.crs(), crs, project).transformBoundingBox(layer.extent()))
    if "extent" in design:
        extent = QgsRectangle(*design["extent"])
    if extent.isEmpty():
        raise ValueError("地图范围为空。")
    extent.scale(1.05)
    map_item.zoomToExtent(extent)
    legend = QgsLayoutItemLegend(layout)
    legend.setId("legend")
    legend.setTitle(design.get("legend_title", "图例"))
    legend.setLinkedMap(map_item)
    legend.setAutoUpdateModel(False)
    legend.model().rootGroup().clear()
    for layer in layers:
        legend.model().rootGroup().addLayer(layer)
    layout.addLayoutItem(legend)
    legend.attemptMove(QgsLayoutPoint((width - 20) * 0.70 + 20, 30))
    legend.attemptResize(QgsLayoutSize((width - 20) * 0.30 - 10, height - 45))
    scale = QgsLayoutItemScaleBar(layout)
    scale.setId("scale")
    scale.setStyle("Single Box")
    scale.setLinkedMap(map_item)
    scale.applyDefaultSize()
    scale.setSegmentSizeMode(QgsScaleBarSettings.SegmentSizeFitWidth)
    scale.setMinimumBarWidth(40)
    scale.setMaximumBarWidth(60)
    layout.addLayoutItem(scale)
    scale.attemptMove(QgsLayoutPoint(14, height - 27))
    layout.setReferenceMap(map_item)
    return layout


def export_layout(
    project: QgsProject, layout: QgsPrintLayout, output_dir: Path, *,
    inputs: list[str], fonts: dict, formats: list[str] | None = None,
    details: list[dict] | None = None, provenance: dict | None = None,
) -> dict:
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    formats = formats if formats is not None else ["png", "qgz"]
    if set(formats) - {"png", "qgz", "pdf", "svg"}:
        raise ValueError("此例程支持 png、qgz、pdf、svg。其他格式需要单独实现。")
    files = {
        "brief": "brief.json", "design": "design.json", "script": "scripts/render.py",
        "preview": "preview.png", "project": "project.qgz", "layout": "layout.qpt",
    }
    styles = {}
    for index, layer in enumerate(project.mapLayers().values()):
        if not layer.isValid():
            raise ValueError(f"无效图层：{layer.name()}")
        path = output_dir / "styles" / f"layer_{index}.qml"
        path.parent.mkdir(parents=True, exist_ok=True)
        message, ok = layer.saveNamedStyle(str(path))
        if not ok:
            raise ValueError(message)
        styles[layer.id()] = str(path.relative_to(output_dir))
    files["styles"] = styles
    project.setFilePathStorage(Qgis.FilePathType.Absolute)
    if not project.write(str(output_dir / files["project"])):
        raise ValueError("QGIS 工程保存失败。")
    if not layout.saveAsTemplate(str(output_dir / files["layout"]), QgsReadWriteContext()):
        raise ValueError("布局模板保存失败。")
    exporter = QgsLayoutExporter(layout)
    page = layout.pageCollection().pages()[0].pageSize()
    preview_dpi = 1800 * 25.4 / max(page.width(), page.height())
    image = exporter.renderPageToImage(0, dpi=preview_dpi)
    if image.isNull() or not image.save(str(output_dir / files["preview"]), "PNG"):
        raise ValueError("预览导出失败。")
    results = {"preview": 0}
    if "png" in formats:
        files["png"] = "map.png"
        image = exporter.renderPageToImage(0, dpi=300)
        if image.isNull() or not image.save(str(output_dir / files["png"]), "PNG"):
            raise ValueError("PNG 导出失败。")
        results["png"] = 0
    for kind, settings_type, method in (
        ("pdf", QgsLayoutExporter.PdfExportSettings, exporter.exportToPdf),
        ("svg", QgsLayoutExporter.SvgExportSettings, exporter.exportToSvg),
    ):
        if kind in formats:
            settings = settings_type()
            settings.dpi = 300
            settings.textRenderFormat = Qgis.TextRenderFormat.AlwaysText
            files[kind] = "map." + kind
            result = method(str(output_dir / files[kind]), settings)
            results[kind] = int(result)
            if result != QgsLayoutExporter.Success:
                raise ValueError(f"{kind} 导出失败：{exporter.errorMessage()}")
    regions = []
    for index, detail in enumerate(details or []):
        relative = f"detail_{index}.png"
        image = exporter.renderRegionToImage(QRectF(*detail["region_mm"]), dpi=detail.get("dpi", 300))
        if image.isNull() or image.width() * image.height() > 16_000_000 or max(image.width(), image.height()) > 8192:
            raise ValueError("局部图为空或尺寸过大。")
        if not image.save(str(output_dir / relative), "PNG") or (output_dir / relative).stat().st_size > 8 * 1024 * 1024:
            raise ValueError("局部图保存失败或超过 8 MiB。")
        regions.append({**detail, "path": relative})
    files["details"] = regions
    paths = [value for value in files.values() if isinstance(value, str)] + list(styles.values())
    paths += [item["path"] for item in regions]
    input_paths = sorted({Path(value).expanduser().resolve() for value in [
        *inputs, __file__, *(item["path"] for item in fonts["files"]),
    ]})
    if any(path.is_relative_to(output_dir) for path in input_paths):
        raise ValueError("冻结 inputs 与当前 outputs 必须分开。")
    for layer in project.mapLayers().values():
        source = Path(layer.source().split("|")[0]).resolve()
        if not source.is_file() or (source not in input_paths and not source.is_relative_to(output_dir)):
            raise ValueError(f"请登记本地数据依赖：{source}")
        if source.is_relative_to(output_dir) and str(source.relative_to(output_dir)) not in paths:
            paths.append(str(source.relative_to(output_dir)))
    maps = [item for item in layout.items() if isinstance(item, QgsLayoutItemMap)]
    manifest = {
        "version": 1, "files": files,
        "inputs": [{"path": str(path), "sha256": digest(path)} for path in input_paths],
        "outputs": [{"path": value, "sha256": digest(output_dir / value)} for value in sorted(set(paths))],
        "environment": {"qgis": Qgis.QGIS_VERSION, "qt": QT_VERSION_STR, "fonts": fonts},
        "layout": {"name": layout.name(), "size_mm": [page.width(), page.height()]},
        "maps": [
            {"id": item.id(), "crs": item.crs().authid(), "scale": item.scale(),
             "extent": [item.extent().xMinimum(), item.extent().yMinimum(), item.extent().xMaximum(), item.extent().yMaximum()]}
            for item in maps
        ],
        "layers": [{"id": layer.id(), "name": layer.name(), "source": layer.source(),
                    "renderer": layer.renderer().type()} for layer in project.mapLayers().values()],
        "export_results": results, "provenance": provenance or {},
    }
    path = output_dir / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True, "manifest": str(path), "manifest_sha256": digest(path),
        "artifacts": [str(output_dir / value) for value in sorted(set(paths))] + [str(path)],
    }


def stage_candidate(manifest_path: str, destination: str) -> dict:
    source_manifest = Path(manifest_path).resolve()
    source = source_manifest.parent
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    for row in [*manifest["inputs"], *manifest["outputs"]]:
        path = Path(row["path"]) if Path(row["path"]).is_absolute() else source / row["path"]
        if not path.is_file() or digest(path) != row["sha256"]:
            raise ValueError(f"源候选文件已变化：{path}")
    for row in manifest["environment"]["fonts"]["files"]:
        if digest(Path(row["path"])) != row["sha256"]:
            raise ValueError(f"源候选字体版本已变化：{row['path']}")
    target = Path(destination).resolve()
    target.mkdir(parents=True, exist_ok=False)
    for row in manifest["outputs"]:
        relative = Path(row["path"])
        if relative.is_absolute() or not (source / relative).resolve().is_relative_to(source) or not (target / relative).resolve().is_relative_to(target):
            raise ValueError("产物路径超出候选目录。")
        (target / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target / relative)
    design_path = target / manifest["files"]["design"]
    design = json.loads(design_path.read_text(encoding="utf-8"))
    if "output_dir" in design:
        design["output_dir"] = str(target)
        design_path.write_text(json.dumps(design, ensure_ascii=False, indent=2), encoding="utf-8")
    app, fonts = initialize_qgis([item["path"] for item in manifest["environment"]["fonts"]["files"]])
    project = QgsProject.instance()
    try:
        if not project.read(str(target / manifest["files"]["project"])):
            raise ValueError("候选工程重开失败。")
        for layer in project.mapLayers().values():
            base, separator, options = layer.source().partition("|")
            path = Path(base).resolve()
            if path.is_relative_to(source):
                layer.setDataSource(str(target / path.relative_to(source)) + separator + options, layer.name(), layer.providerType())
                message, ok = layer.loadNamedStyle(str(target / manifest["files"]["styles"][layer.id()]))
                if not ok:
                    raise ValueError(message)
            if not layer.isValid():
                raise ValueError(f"候选图层无效：{layer.name()}")
        layout = project.layoutManager().layoutByName(manifest["layout"]["name"])
        if layout is None:
            raise ValueError("候选工程缺少布局。")
        result = export_layout(
            project, layout, target, inputs=[str(source_manifest), *(row["path"] for row in manifest["inputs"])],
            fonts=fonts, formats=[kind for kind in ("png", "pdf", "svg") if kind in manifest["files"]],
            details=manifest["files"].get("details"),
            provenance={"source_manifest": str(source_manifest), "source_manifest_sha256": digest(source_manifest),
                        "source_task_id": source.name},
        )
        return result
    finally:
        project.clear()
        app.exitQgis()

