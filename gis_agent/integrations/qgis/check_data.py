import json
import math
import os
import sys
from collections import Counter
from pathlib import Path

from qgis.core import QgsApplication, QgsFeatureRequest, QgsVariantUtils, QgsVectorLayer


def load_layer(source: str) -> QgsVectorLayer:
    layer = QgsVectorLayer(source, "data", "ogr")
    if not layer.isValid():
        raise ValueError(f"矢量数据无效：{source}")
    return layer


def require_fields(layer: QgsVectorLayer, fields: list[str]) -> None:
    missing = [name for name in fields if layer.fields().indexFromName(name) < 0]
    if missing:
        raise ValueError(f"字段不存在：{missing}；实际字段：{layer.fields().names()}")


def value_of(value):
    if QgsVariantUtils.isNull(value):
        return None
    return value if isinstance(value, (str, int, float, bool)) else str(value)


def summarize_fields(source: str, fields: list[str], key: str | None = None, check_geometry: bool = False) -> dict:
    layer = load_layer(source)
    names = list(dict.fromkeys([*fields, *([key] if key else [])]))
    require_fields(layer, names)
    values = {name: [] for name in names}
    samples = []
    geometries = {"empty": 0, "invalid": 0}
    request = QgsFeatureRequest().setSubsetOfAttributes(names, layer.fields())
    if not check_geometry:
        request.setFlags(QgsFeatureRequest.NoGeometry)
    for feature in layer.getFeatures(request):
        row = {name: value_of(feature[name]) for name in names}
        if len(samples) < 5:
            samples.append({name: str(value) if isinstance(value, float) and not math.isfinite(value) else value for name, value in row.items()})
        for name, value in row.items():
            values[name].append(value)
        if check_geometry:
            geometry = feature.geometry()
            geometries["empty"] += geometry.isNull() or geometry.isEmpty()
            if not geometry.isNull() and not geometry.isEmpty():
                geometries["invalid"] += not geometry.isGeosValid()
    statistics = {}
    for name, items in values.items():
        valid = [value for value in items if value is not None]
        numeric = [value for value in valid if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)]
        statistics[name] = {"null": len(items) - len(valid), "unique": len(set(valid)),
                            "nonfinite": sum(isinstance(v, float) and not math.isfinite(v) for v in valid)}
        if numeric:
            statistics[name].update(min=min(numeric), max=max(numeric), sum=math.fsum(numeric))
    result = {"ok": True, "source": source, "crs": layer.crs().authid(),
              "count": layer.featureCount(), "fields": statistics, "samples": samples}
    if key:
        counts = Counter(value for value in values[key] if value is not None)
        result["key"] = {"field": key, "null": statistics[key]["null"],
                         "duplicate_rows": sum(count - 1 for count in counts.values()),
                         "examples": [value for value, count in counts.items() if count > 1][:5]}
    if check_geometry:
        result["geometry"] = geometries
    return result


def check_spatial_relation(source: str, reference: str, foreign_key: str, reference_key: str, relation: str = "intersects") -> dict:
    if relation not in {"intersects", "within", "contains", "touches"}:
        raise ValueError("relation 需要使用 intersects、within、contains 或 touches。")
    left, right = load_layer(source), load_layer(reference)
    require_fields(left, [foreign_key])
    require_fields(right, [reference_key])
    if not left.crs().isValid() or not right.crs().isValid() or left.crs() != right.crs():
        raise ValueError("两层需要相同的有效CRS，请先核对坐标系并显式重投影。")
    objects = {}
    for feature in right.getFeatures():
        key = value_of(feature[reference_key])
        if key is None or key in objects:
            raise ValueError("参照键存在空值或重复，请先核对稳定身份和一对多关系。")
        objects[key] = feature.geometry()
    counts = {"checked": 0, "missing_key": 0, "empty_geometry": 0, "violations": 0}
    examples = []
    for feature in left.getFeatures():
        key, geometry = value_of(feature[foreign_key]), feature.geometry()
        if key not in objects:
            problem = "missing_key"
        elif geometry.isNull() or geometry.isEmpty() or objects[key].isNull() or objects[key].isEmpty():
            problem = "empty_geometry"
        else:
            counts["checked"] += 1
            problem = "violations" if not getattr(geometry, relation)(objects[key]) else None
        if problem:
            counts[problem] += 1
            if len(examples) < 5:
                examples.append({"feature_id": feature.id(), "foreign_key": key, "problem": problem})
    return {"ok": True, "source": source, "reference": reference, "relation": relation,
            "crs": left.crs().authid(), "count": left.featureCount(), **counts, "examples": examples}


def main(parameters: dict) -> dict:
    mode = parameters.pop("mode")
    return {"fields": summarize_fields, "relations": check_spatial_relation}[mode](**parameters)


if __name__ == "__main__":
    application = QgsApplication([], False)
    application.initQgis()
    try:
        result = main(json.loads(sys.argv[1]))
        text = json.dumps(result, ensure_ascii=False, allow_nan=False)
        Path(os.environ["GIS_AGENT_RESULT_PATH"]).write_text(text, encoding="utf-8")
        print(text)
    finally:
        application.exitQgis()
