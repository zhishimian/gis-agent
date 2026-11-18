import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from gis_agent.runtime.paths import import_root

SPATIAL_EXTS = {".tif", ".tiff", ".img", ".vrt", ".asc", ".gpkg", ".shp", ".geojson", ".fgb"}


def _clean_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "item"):
        try:
            scalar = value.item()
            if isinstance(scalar, float) and (math.isnan(scalar) or math.isinf(scalar)):
                return None
            return scalar
        except Exception:
            return str(value)
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _crs_metadata(crs_obj: Any) -> tuple[str, str, str]:
    if crs_obj is None:
        return "", "", ""
    from pyproj import CRS

    crs = CRS.from_user_input(crs_obj)
    authority = crs.to_authority()
    authid = f"{authority[0]}:{authority[1]}" if authority else crs.to_string()
    unit = crs.axis_info[0].unit_name if crs.axis_info else ""
    return authid, crs.name or "", unit


def _parse_uri(source: str) -> tuple[str, str | None]:
    if "|layername=" in source:
        raw_path, rest = source.split("|layername=", 1)
        return raw_path, rest.split("|", 1)[0]
    return source, None


def _inspect_vector_pyogrio(source: str) -> dict[str, Any]:
    import pyogrio
    import shapely

    raw_path, layer_name = _parse_uri(source)
    if layer_name is None and not source.upper().startswith("NETCDF:"):
        layers = pyogrio.list_layers(raw_path)
        if len(layers) > 1:
            return {
                "kind": "container",
                "source": source,
                "layers": [
                    {
                        "name": str(row[0]),
                        "geometry_type": str(row[1]) if row[1] is not None else "NoGeometry",
                        "source": f"{raw_path}|layername={row[0]}",
                        "provider": "ogr",
                    }
                    for row in layers
                ],
            }

    info = pyogrio.read_info(raw_path, layer=layer_name)
    authid, crs_desc, units = _crs_metadata(info.get("crs"))
    fields = [
        {"name": str(name), "type": str(dtype)}
        for name, dtype in zip(info.get("fields", ()), info.get("dtypes", ()))
    ]
    sample_df = pyogrio.read_dataframe(raw_path, layer=layer_name, max_features=3, read_geometry=False)
    samples = [
        {col: _clean_scalar(row[col]) for col in sample_df.columns}
        for _, row in sample_df.iterrows()
    ]

    geom_type = info.get("geometry_type") or "NoGeometry"
    has_z = "Z" in str(geom_type)
    clean_geom_type = str(geom_type).replace(" Z", "").replace("ZM", "").strip()
    total_bounds = info.get("total_bounds")
    extent = [float(x) if x is not None and math.isfinite(x) else 0.0 for x in total_bounds] if total_bounds is not None else []

    geom_check: dict[str, int] = {"sampled": 0, "empty": 0, "invalid": 0}
    if clean_geom_type != "NoGeometry" and (info.get("features") or 0) != 0:
        geom_df = pyogrio.read_dataframe(raw_path, layer=layer_name, columns=[], max_features=200)
        geoms = geom_df.geometry.to_numpy()
        geom_check["sampled"] = int(len(geoms))
        null_or_empty = [g is None or shapely.is_empty(g) for g in geoms]
        geom_check["empty"] = int(sum(null_or_empty))
        valid_candidates = [g for g, empty in zip(geoms, null_or_empty) if not empty]
        if valid_candidates:
            geom_check["invalid"] = int(sum(not bool(v) for v in shapely.is_valid(valid_candidates)))

    return {
        "kind": "vector",
        "source": source,
        "feature_count": int(info.get("features", len(sample_df))),
        "geometry_type": clean_geom_type,
        "has_z": has_z,
        "fields": fields,
        "samples": samples,
        "geometry_sample_check": geom_check,
        "crs": authid,
        "crs_description": crs_desc,
        "units": units,
        "extent": extent,
    }


def _inspect_raster_rasterio(source: str) -> dict[str, Any]:
    import numpy as np
    import rasterio

    with rasterio.open(source) as dataset:
        if dataset.count == 0 and dataset.subdatasets:
            return {
                "kind": "container",
                "source": source,
                "layers": [
                    {"name": sub.split(":")[-1], "source": sub, "provider": "gdal"}
                    for sub in dataset.subdatasets
                ],
            }
        authid, crs_desc, units = _crs_metadata(dataset.crs)
        out_h = max(1, min(dataset.height, 256))
        out_w = max(1, min(dataset.width, 256))
        bands = []
        for idx in range(1, dataset.count + 1):
            sample = dataset.read(idx, out_shape=(out_h, out_w), masked=True)
            total_px = sample.size
            compressed = sample.compressed()
            finite = compressed[np.isfinite(compressed)] if compressed.size else compressed
            scale = float(dataset.scales[idx - 1]) if dataset.scales else 1.0
            offset = float(dataset.offsets[idx - 1]) if dataset.offsets else 0.0
            overview = {
                "valid_ratio": round(float(finite.size / total_px), 4) if total_px else 0.0,
                "raw_min": float(finite.min()) if finite.size else None,
                "raw_max": float(finite.max()) if finite.size else None,
            }
            bands.append(
                {
                    "band": idx,
                    "dtype": str(dataset.dtypes[idx - 1]),
                    "colorinterp": dataset.colorinterp[idx - 1].name if idx <= len(dataset.colorinterp) else "undefined",
                    "nodata": _clean_scalar(dataset.nodatavals[idx - 1]),
                    "scale": scale,
                    "offset": offset,
                    "unit": dataset.units[idx - 1] or None,
                    "overview_sample": overview,
                }
            )
        bounds = dataset.bounds
        return {
            "kind": "raster",
            "source": source,
            "width": dataset.width,
            "height": dataset.height,
            "pixel_size": [abs(float(dataset.res[0])), abs(float(dataset.res[1]))],
            "bands": bands,
            "crs": authid,
            "crs_description": crs_desc,
            "units": units,
            "extent": [float(bounds.left), float(bounds.bottom), float(bounds.right), float(bounds.top)],
        }


def inspect_single(source: str) -> dict[str, Any]:
    raw_path, _ = _parse_uri(source)
    raster_exts = {".tif", ".tiff", ".img", ".asc", ".bil", ".vrt", ".nc", ".hdf", ".jp2", ".png", ".jpg"}
    suffix = Path(raw_path).suffix.lower() if not source.upper().startswith(("NETCDF:", "HDF")) else ".nc"

    try:
        import pyogrio  # noqa: F401
        import rasterio  # noqa: F401
    except ImportError:
        from gis_agent.integrations.qgis.inspect_data import inspect_data as qgis_inspect

        return qgis_inspect(source)

    errors = []
    order = (_inspect_raster_rasterio, _inspect_vector_pyogrio) if suffix in raster_exts else (_inspect_vector_pyogrio, _inspect_raster_rasterio)
    for reader in order:
        try:
            return reader(source)
        except Exception as error:
            errors.append(str(error))

    try:
        from qgis.core import QgsApplication
        from gis_agent.integrations.qgis.inspect_data import inspect_data as qgis_inspect

        app = QgsApplication([], False)
        app.initQgis()
        try:
            return qgis_inspect(source)
        finally:
            app.exitQgis()
    except Exception:
        pass
    raise ValueError(f"无法读取矢量或栅格数据：{source}（{'; '.join(errors[:2])}）")


def _extract_vital_summary(info: dict[str, Any]) -> dict[str, Any]:
    kind = info.get("kind")
    if kind == "vector":
        geom_check = info.get("geometry_sample_check") or {}
        return {
            "kind": "vector",
            "crs": info.get("crs") or "",
            "units": info.get("units") or "",
            "feature_count": info.get("feature_count"),
            "geometry_type": info.get("geometry_type") or "",
            "invalid_sample_count": geom_check.get("invalid", 0),
            "empty_sample_count": geom_check.get("empty", 0),
        }
    if kind == "raster":
        bands = info.get("bands") or []
        b0 = bands[0] if bands else {}
        overview = b0.get("overview_sample") or {}
        return {
            "kind": "raster",
            "crs": info.get("crs") or "",
            "units": info.get("units") or "",
            "shape": [info.get("height"), info.get("width")],
            "band_count": len(bands),
            "dtype": b0.get("dtype"),
            "nodata": b0.get("nodata"),
            "scale": b0.get("scale", 1.0),
            "valid_ratio": overview.get("valid_ratio"),
            "raw_min": overview.get("raw_min"),
            "raw_max": overview.get("raw_max"),
        }
    if kind == "container":
        return {"kind": "container", "layer_count": len(info.get("layers") or [])}
    return {"kind": kind or "unknown"}


def detect_spatial_anomalies(spatial: dict[str, Any]) -> list[dict[str, str]]:
    """Classify objective spatial vital signs into notice / warning / fatal signals without business verdicts."""
    kind = spatial.get("kind")
    if kind == "corrupt" or spatial.get("error"):
        return [{
            "level": "fatal",
            "code": "CORRUPT_OR_UNREADABLE",
            "message": f"空间文件读取失败或文件头损坏：{spatial.get('error', '')}".rstrip("："),
        }]

    anomalies: list[dict[str, str]] = []
    crs = (spatial.get("crs") or "").strip()
    if kind == "vector":
        fc = spatial.get("feature_count")
        inv = int(spatial.get("invalid_sample_count") or 0)
        emp = int(spatial.get("empty_sample_count") or 0)
        if not crs:
            anomalies.append({
                "level": "warning",
                "code": "MISSING_CRS",
                "message": "输出矢量缺失坐标系（CRS 为空）。",
            })
        if fc == 0:
            anomalies.append({
                "level": "warning",
                "code": "ZERO_FEATURES",
                "message": "输出矢量要素数为 0；请核实是预期空集还是过滤/坐标系错配所致。",
            })
        elif isinstance(fc, int) and fc > 0 and (inv > 0 or emp > 0):
            if inv + emp >= min(fc, 200):
                anomalies.append({
                    "level": "warning",
                    "code": "ALL_INVALID_OR_EMPTY",
                    "message": f"抽检几何全部为空或无效（empty={emp}, invalid={inv}）。",
                })
            else:
                anomalies.append({
                    "level": "notice",
                    "code": "PARTIAL_INVALID_GEOMETRY",
                    "message": f"前200要素抽检发现无效或空几何（invalid={inv}, empty={emp}）。",
                })
    elif kind == "raster":
        vr = spatial.get("valid_ratio")
        dtype = str(spatial.get("dtype") or "").lower()
        rmin = spatial.get("raw_min")
        rmax = spatial.get("raw_max")
        shape = spatial.get("shape") or []
        scale = spatial.get("scale")
        pixels = (shape[0] or 0) * (shape[1] or 0) if len(shape) == 2 else 0
        if not crs:
            anomalies.append({
                "level": "warning",
                "code": "MISSING_CRS",
                "message": "输出栅格缺失坐标系（CRS 为空）。",
            })
        if vr == 0.0:
            anomalies.append({
                "level": "warning",
                "code": "ALL_NODATA_RASTER",
                "message": "输出栅格概览有效像元占比为 0.0（全 NoData）。",
            })
        elif rmin is not None and rmax is not None and rmin == rmax and pixels > 1 and "float" in dtype:
            anomalies.append({
                "level": "warning",
                "code": "CONSTANT_RASTER_SURFACE",
                "message": f"浮点栅格概览像元全为常数值 {rmin}；请核实是否计算退化或符合平坦预期。",
            })
        if "int" in dtype and rmax is not None and rmax > 100 and (scale is None or scale == 1.0):
            anomalies.append({
                "level": "notice",
                "code": "UNSCALED_HIGH_DN",
                "message": f"整型栅格极值 {rmax} 且 scale=1.0；计算 SAVI/EVI 等含加性常数光谱指数时请核对定标。",
            })
    return anomalies


def extract_vital_signs(source: str) -> dict[str, Any]:
    return _extract_vital_summary(inspect_single(source))


def attach_spatial_vitals(
    outputs: list[dict[str, Any]],
    launcher: Path | None = None,
    *,
    max_files: int = 3,
) -> list[dict[str, Any]]:
    targets: list[tuple[dict[str, Any], str]] = []
    for item in outputs:
        raw_path = item.get("path")
        if not isinstance(raw_path, str):
            continue
        if item.get("empty") or item.get("exists") is False:
            continue
        p = Path(raw_path)
        if p.suffix.lower() not in SPATIAL_EXTS or not p.is_file() or p.stat().st_size == 0:
            continue
        targets.append((item, str(p)))
        if len(targets) >= max_files:
            break
    if not targets:
        return outputs

    # Host Python with pyogrio + rasterio extracts vitals in-process (~20-60ms) with zero subprocess cost.
    if importlib.util.find_spec("pyogrio") is not None and importlib.util.find_spec("rasterio") is not None:
        for item, path_str in targets:
            try:
                summary = extract_vital_signs(path_str)
            except ImportError:
                summary = None
            except Exception as err:
                summary = {"kind": "corrupt", "error": str(err)[:240]}
            if isinstance(summary, dict):
                item["spatial"] = summary
                anoms = detect_spatial_anomalies(summary)
                if anoms:
                    item["anomalies"] = anoms
        return outputs

    if launcher is not None and launcher.is_file():
        env = dict(os.environ)
        if launcher.suffix.lower() not in {".bat", ".cmd"}:
            for var in ("PROJ_LIB", "PROJ_DATA", "GDAL_DATA"):
                env.pop(var, None)
        root = str(import_root())
        env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        try:
            proc = subprocess.run(
                [str(launcher), "-B", str(Path(__file__).resolve()), "--vitals", *(p for _, p in targets)],
                capture_output=True,
                encoding="utf-8",
                timeout=10,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if proc.returncode == 0:
                lines = [line.strip() for line in proc.stdout.splitlines() if line.strip().startswith("{")]
                if lines:
                    vitals = json.loads(lines[-1]).get("vitals") or {}
                    for item, path_str in targets:
                        summary = vitals.get(path_str)
                        if isinstance(summary, dict):
                            item["spatial"] = summary
                            anoms = detect_spatial_anomalies(summary)
                            if anoms:
                                item["anomalies"] = anoms
        except Exception:
            pass
    return outputs


def main(argv: list[str]) -> dict[str, Any]:
    if argv[0] == "--batch":
        datasets = []
        for source in argv[1:]:
            try:
                datasets.append({"ok": True, **inspect_single(source)})
            except Exception as error:
                datasets.append({"ok": False, "source": source, "error": str(error)})
        return {"datasets": datasets}
    if argv[0] == "--vitals":
        vitals: dict[str, Any] = {}
        for source in argv[1:]:
            try:
                vitals[source] = extract_vital_signs(source)
            except Exception as error:
                vitals[source] = {"kind": "corrupt", "error": str(error)[:240]}
        return {"vitals": vitals}
    return inspect_single(argv[0])


if __name__ == "__main__":
    output = main(sys.argv[1:])
    text = json.dumps(output, ensure_ascii=False, default=str)
    if result_path := os.environ.get("GIS_AGENT_RESULT_PATH"):
        Path(result_path).write_text(text, encoding="utf-8")
    print(text)
