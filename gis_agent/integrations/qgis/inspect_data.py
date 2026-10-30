import json
import os
import sys
from pathlib import Path
from typing import Any

from qgis.core import (
    QgsApplication,
    QgsFeatureRequest,
    QgsProviderRegistry,
    QgsRasterLayer,
    QgsUnitTypes,
    QgsVariantUtils,
    QgsVectorLayer,
    QgsWkbTypes,
)


def inspect_data(source: str) -> dict[str, Any]:
    sublayers = QgsProviderRegistry.instance().querySublayers(source)
    if len(sublayers) > 1:
        return {
            "kind": "container",
            "source": source,
            "layers": [
                {"name": layer.name(), "source": layer.uri(), "provider": layer.providerKey()}
                for layer in sublayers
            ],
        }

    name = Path(source.split("|")[0]).stem
    layer = QgsVectorLayer(source, name, "ogr")
    if layer.isValid():
        request = QgsFeatureRequest().setLimit(3).setFlags(QgsFeatureRequest.NoGeometry)
        result = {
            "kind": "vector",
            "source": source,
            "feature_count": layer.featureCount(),
            "geometry_type": QgsWkbTypes.displayString(layer.wkbType()),
            "fields": [
                {"name": field.name(), "type": field.typeName()}
                for field in layer.fields()
            ],
            "samples": [
                {
                    field.name(): None if QgsVariantUtils.isNull(feature[index]) else feature[index]
                    for index, field in enumerate(layer.fields())
                }
                for feature in layer.getFeatures(request)
            ],
        }
    else:
        layer = QgsRasterLayer(source, name)
        if not layer.isValid():
            raise ValueError(f"无法读取矢量或栅格数据：{source}")
        provider = layer.dataProvider()
        result = {
            "kind": "raster",
            "source": source,
            "width": layer.width(),
            "height": layer.height(),
            "pixel_size": [layer.rasterUnitsPerPixelX(), layer.rasterUnitsPerPixelY()],
            "bands": [
                {
                    "band": band,
                    "data_type": int(provider.dataType(band)),
                    "nodata": (
                        provider.sourceNoDataValue(band)
                        if provider.sourceHasNoDataValue(band)
                        else None
                    ),
                }
                for band in range(1, layer.bandCount() + 1)
            ],
        }

    crs = layer.crs()
    extent = layer.extent()
    return {
        **result,
        "crs": crs.authid(),
        "crs_description": crs.description(),
        "units": QgsUnitTypes.toString(crs.mapUnits()),
        "extent": [extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()],
    }


if __name__ == "__main__":
    application = QgsApplication([], False)
    application.initQgis()
    try:
        if sys.argv[1] == "--batch":
            datasets = []
            for source in sys.argv[2:]:
                try:
                    datasets.append({"ok": True, **inspect_data(source)})
                except ValueError as error:
                    datasets.append({"ok": False, "source": source, "error": str(error)})
            result = {"datasets": datasets}
        else:
            result = inspect_data(sys.argv[1])
        text = json.dumps(result, ensure_ascii=False, default=str)
        if os.environ.get("GIS_AGENT_RESULT_PATH"):
            Path(os.environ["GIS_AGENT_RESULT_PATH"]).write_text(text, encoding="utf-8")
        print(text)
    finally:
        application.exitQgis()
