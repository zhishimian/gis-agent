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
            "valid_ratio": overview.get("valid_ratio"),
            "raw_min": overview.get("raw_min"),
            "raw_max": overview.get("raw_max"),
        }
    if kind == "container":
        return {"kind": "container", "layer_count": len(info.get("layers") or [])}
    return {"kind": kind or "unknown"}


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
                item["spatial"] = extract_vital_signs(path_str)
            except Exception:
                pass
        return outputs

    if launcher is not None and launcher.is_file():
        env = dict(os.environ)
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
                        if isinstance(vitals.get(path_str), dict):
                            item["spatial"] = vitals[path_str]
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
            except Exception:
                pass
        return {"vitals": vitals}
    return inspect_single(argv[0])


if __name__ == "__main__":
    output = main(sys.argv[1:])
    text = json.dumps(output, ensure_ascii=False, default=str)
    if result_path := os.environ.get("GIS_AGENT_RESULT_PATH"):
        Path(result_path).write_text(text, encoding="utf-8")
    print(text)
