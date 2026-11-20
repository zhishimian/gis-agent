"""Viewport-adaptive vector GeoJSON, WarpedVRT raster PNG preview, spatial Identify & attribute paging."""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import io
import math
from pathlib import Path
from threading import RLock
from typing import Any

from gis_agent.runtime.inspect_fast import _clean_scalar, _inspect_raster_rasterio, _inspect_vector_pyogrio

RASTER_CACHE_MAX_BYTES = 64 * 1024 * 1024


def _split_uri(raw_path: str) -> tuple[Path, str | None]:
    if "|layername=" in raw_path:
        raw, layer = raw_path.split("|layername=", 1)
        return Path(raw).expanduser().resolve(), layer.split("|", 1)[0]
    return Path(raw_path).expanduser().resolve(), None


def _to_wgs84_bounds(crs_str: str | None, extent: list[float]) -> list[float] | None:
    if not extent or len(extent) != 4 or any(not math.isfinite(v) for v in extent):
        return None
    if not crs_str or crs_str.upper() in {"EPSG:4326", "OGC:CRS84", "CRS:84"}:
        return [float(v) for v in extent]
    from pyproj import CRS, Transformer

    try:
        src = CRS.from_user_input(crs_str)
        if src.is_geographic and src.to_epsg() == 4326:
            return [float(v) for v in extent]
        transformer = Transformer.from_crs(src, "EPSG:4326", always_xy=True)
        w, s, e, n = transformer.transform_bounds(*extent, densify_pts=21)
        if all(math.isfinite(v) for v in (w, s, e, n)):
            return [round(float(w), 6), round(float(s), 6), round(float(e), 6), round(float(n), 6)]
    except Exception:
        return None
    return None


def _json_safe_row(row_dict: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for k, v in row_dict.items():
        if v is None:
            cleaned[str(k)] = None
        elif hasattr(v, "isoformat"):
            cleaned[str(k)] = v.isoformat()
        elif isinstance(v, (bytes, bytearray)):
            cleaned[str(k)] = f"<{len(v)} bytes>"
        else:
            cleaned[str(k)] = _clean_scalar(v)
    return cleaned


class SpatialService:
    """Stateless-disk, cached viewport vector/raster engine powered by pyogrio & rasterio."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._raster_cache: OrderedDict[str, tuple[int, dict[str, Any]]] = OrderedDict()
        self._raster_cache_bytes = 0

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._raster_cache.get(key)
            if entry is None:
                return None
            self._raster_cache.move_to_end(key)
            return entry[1]

    def _cache_put(self, key: str, size_bytes: int, value: dict[str, Any]) -> None:
        if size_bytes > RASTER_CACHE_MAX_BYTES:
            return
        with self._lock:
            if key in self._raster_cache:
                old_sz, _ = self._raster_cache.pop(key)
                self._raster_cache_bytes -= old_sz
            while self._raster_cache and (self._raster_cache_bytes + size_bytes > RASTER_CACHE_MAX_BYTES):
                _, (ev_sz, _) = self._raster_cache.popitem(last=False)
                self._raster_cache_bytes -= ev_sz
            self._raster_cache[key] = (size_bytes, value)
            self._raster_cache_bytes += size_bytes

    def get_layer_meta(self, authorized_uri: str) -> dict[str, Any]:
        file_path, _layer = _split_uri(authorized_uri)
        ext = file_path.suffix.lower()
        if ext in {".tif", ".tiff", ".img", ".vrt", ".asc", ".nc"}:
            info = _inspect_raster_rasterio(authorized_uri)
            if info.get("kind") == "raster":
                info["bbox_wgs84"] = _to_wgs84_bounds(info.get("crs"), info.get("extent", []))
            return info

        info = _inspect_vector_pyogrio(authorized_uri)
        if info.get("kind") == "container":
            for layer_entry in info.get("layers", []):
                try:
                    sub_meta = _inspect_vector_pyogrio(layer_entry["source"])
                    layer_entry["feature_count"] = sub_meta.get("feature_count")
                    layer_entry["crs"] = sub_meta.get("crs")
                    layer_entry["bbox_wgs84"] = _to_wgs84_bounds(sub_meta.get("crs"), sub_meta.get("extent", []))
                except Exception:
                    pass
            return info

        info["bbox_wgs84"] = _to_wgs84_bounds(info.get("crs"), info.get("extent", []))
        return info

    def get_vector_geojson(
        self,
        authorized_uri: str,
        *,
        bbox: tuple[float, float, float, float] | None = None,
        zoom: float | None = None,
        max_features: int = 5000,
        simplify_tol: float | None = None,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        import json
        import pyogrio
        from pyproj import CRS, Transformer

        file_path, layer_name = _split_uri(authorized_uri)
        info = pyogrio.read_info(str(file_path), layer=layer_name)
        total_features = int(info.get("features") or 0)
        raw_crs = info.get("crs")
        src_crs = CRS.from_user_input(raw_crs) if raw_crs else None
        geom_type = str(info.get("geometry_type") or "Unknown")
        raw_fields = info.get("fields")
        all_fields = [str(f) for f in raw_fields] if raw_fields is not None else []
        use_fields = [f for f in fields if f in all_fields] if fields is not None else all_fields[:24]

        query_bbox = None
        if bbox is not None:
            if src_crs is not None and not (src_crs.is_geographic and src_crs.to_epsg() == 4326):
                tr = Transformer.from_crs("EPSG:4326", src_crs, always_xy=True)
                query_bbox = tr.transform_bounds(*bbox, densify_pts=12)
            else:
                query_bbox = bbox

        limit = max(100, min(int(max_features), 20000))
        read_limit = limit if (total_features > limit or query_bbox is not None) else None
        gdf = pyogrio.read_dataframe(
            str(file_path),
            layer=layer_name,
            columns=use_fields,
            bbox=query_bbox,
            max_features=read_limit + 1 if read_limit is not None else None,
            fid_as_index=True,
        )
        truncated = read_limit is not None and len(gdf) > read_limit
        if truncated:
            gdf = gdf.iloc[:read_limit]

        if gdf.crs is not None:
            if not (gdf.crs.is_geographic and gdf.crs.to_epsg() == 4326):
                gdf = gdf.to_crs("EPSG:4326")

        effective_tol = simplify_tol
        if effective_tol is None and zoom is not None and (total_features > 1500 or len(gdf) > 1500):
            deg_per_px = 360.0 / (256.0 * (2.0 ** max(0.0, min(float(zoom), 20.0))))
            effective_tol = max(deg_per_px * 1.1, 1e-5)

        if effective_tol and effective_tol > 0 and "Point" not in geom_type:
            simplified = gdf.geometry.simplify(effective_tol, preserve_topology=True)
            gdf = gdf.assign(geometry=simplified)

        gdf = gdf[~gdf.geometry.isna() & ~gdf.geometry.is_empty].copy()
        gdf["_fid"] = gdf.index.astype(int)
        for col in list(gdf.columns):
            if col == gdf.geometry.name or col == "_fid":
                continue
            if gdf[col].dtype == object or str(gdf[col].dtype).startswith("datetime"):
                gdf[col] = gdf[col].map(lambda v: _clean_scalar(v.isoformat() if hasattr(v, "isoformat") else v))

        geojson_obj = json.loads(gdf.to_json(drop_id=True)) if len(gdf) else {"type": "FeatureCollection", "features": []}
        raw_tb = info.get("total_bounds")
        fallback_tb = [float(x) for x in raw_tb] if raw_tb is not None else []
        bounds = (
            [float(x) for x in gdf.total_bounds]
            if len(gdf)
            else _to_wgs84_bounds(src_crs.to_string() if src_crs else None, fallback_tb)
        )
        geojson_obj["meta"] = {
            "path": str(file_path),
            "layer": layer_name,
            "crs": src_crs.to_string() if src_crs else "",
            "geometry_type": geom_type,
            "fields": all_fields,
            "total_features": total_features,
            "returned_features": len(geojson_obj.get("features", [])),
            "truncated": bool(truncated or (total_features > len(gdf) and query_bbox is not None)),
            "simplified_tol_deg": float(effective_tol) if effective_tol else 0.0,
            "bbox_wgs84": bounds,
        }
        return geojson_obj

    def get_raster_preview(
        self,
        authorized_uri: str,
        *,
        bbox: tuple[float, float, float, float] | None = None,
        width: int = 1024,
        height: int = 1024,
        band: int = 1,
        colormap: str = "viridis",
        p_low: float = 2.0,
        p_high: float = 98.0,
    ) -> dict[str, Any]:
        import matplotlib
        import numpy as np
        from PIL import Image
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.vrt import WarpedVRT
        from rasterio.windows import bounds as window_bounds
        from rasterio.windows import from_bounds

        file_path, _ = _split_uri(authorized_uri)
        st = file_path.stat() if file_path.is_file() else None
        sig = f"{authorized_uri}|{st.st_mtime_ns if st else 0}|{st.st_size if st else 0}|{bbox}|{width}x{height}|{band}|{colormap}|{p_low}-{p_high}"
        cache_key = hashlib.sha256(sig.encode("utf-8")).hexdigest()
        if cached := self._cache_get(cache_key):
            return cached

        max_w = max(64, min(int(width), 1024))
        max_h = max(64, min(int(height), 1024))

        from contextlib import nullcontext

        with rasterio.open(authorized_uri) as src:
            band_count = int(src.count)
            use_vrt = src.crs is not None
            ds_ctx = WarpedVRT(src, crs="EPSG:4326", resampling=Resampling.bilinear) if use_vrt else nullcontext(src)
            with ds_ctx as ds:
                ds_bounds = tuple(float(v) for v in ds.bounds)
                if bbox is not None:
                    req_w = max(bbox[0], ds_bounds[0])
                    req_s = max(bbox[1], ds_bounds[1])
                    req_e = min(bbox[2], ds_bounds[2])
                    req_n = min(bbox[3], ds_bounds[3])
                    if req_w >= req_e or req_s >= req_n:
                        blank = io.BytesIO()
                        Image.new("RGBA", (2, 2), (0, 0, 0, 0)).save(blank, format="PNG")
                        return {
                            "png_bytes": blank.getvalue(),
                            "bounds_wgs84": list(ds_bounds),
                            "band": band,
                            "band_count": band_count,
                            "stats": {"min": None, "max": None, "vmin": None, "vmax": None},
                        }
                    win = from_bounds(req_w, req_s, req_e, req_n, ds.transform)
                else:
                    win = rasterio.windows.Window(0, 0, ds.width, ds.height)

                win = win.round_offsets(op="floor").round_lengths(op="ceil")
                exact_bounds = [round(float(v), 6) for v in window_bounds(win, ds.transform)]
                win_w = max(1, int(win.width))
                win_h = max(1, int(win.height))
                scale = min(max_w / win_w, max_h / win_h, 1.0)
                out_w = max(2, int(round(win_w * scale)))
                out_h = max(2, int(round(win_h * scale)))

                if band == 0 and ds.count >= 3:
                    arr = ds.read([1, 2, 3], window=win, out_shape=(3, out_h, out_w), masked=True)
                    rgb_u8 = np.zeros((out_h, out_w, 4), dtype=np.uint8)
                    valid = ~np.any(np.ma.getmaskarray(arr), axis=0)
                    for idx in range(3):
                        ch = arr[idx].astype(np.float64)
                        vals = ch[valid & np.isfinite(ch.data)].compressed() if hasattr(ch, "compressed") else ch.data[valid]
                        if vals.size:
                            lo, hi = np.percentile(vals, [p_low, p_high])
                            if hi <= lo:
                                hi = lo + 1.0
                            scaled = np.clip((ch.data - lo) / (hi - lo), 0.0, 1.0) * 255.0
                            rgb_u8[:, :, idx] = np.where(valid, scaled.astype(np.uint8), 0)
                    rgb_u8[:, :, 3] = np.where(valid, 255, 0).astype(np.uint8)
                    stats = {"min": None, "max": None, "vmin": None, "vmax": None, "mode": "rgb"}
                    rgba_u8 = rgb_u8
                else:
                    b_idx = max(1, min(int(band), ds.count))
                    arr = ds.read(b_idx, window=win, out_shape=(out_h, out_w), masked=True)
                    mask = np.ma.getmaskarray(arr) | ~np.isfinite(arr.data)
                    valid = ~mask
                    raw_vals = arr.data[valid].astype(np.float64)
                    if raw_vals.size == 0:
                        rgba_u8 = np.zeros((out_h, out_w, 4), dtype=np.uint8)
                        stats = {"min": None, "max": None, "vmin": None, "vmax": None, "mode": "single"}
                    else:
                        dmin = float(np.min(raw_vals))
                        dmax = float(np.max(raw_vals))
                        lo = float(np.percentile(raw_vals, p_low))
                        hi = float(np.percentile(raw_vals, p_high))
                        if not math.isfinite(hi - lo) or hi <= lo:
                            lo, hi = dmin, dmax
                        span = (hi - lo) if hi > lo else 1.0
                        norm = np.clip((np.where(valid, arr.data.astype(np.float64), lo) - lo) / span, 0.0, 1.0)
                        cmap_name = colormap if colormap in matplotlib.colormaps else "viridis"
                        cmap = matplotlib.colormaps[cmap_name]
                        rgba = cmap(norm)
                        rgba[:, :, 3] = np.where(valid, 1.0, 0.0)
                        rgba_u8 = np.clip(rgba * 255.0, 0, 255).astype(np.uint8)
                        stats = {
                            "min": round(dmin, 6),
                            "max": round(dmax, 6),
                            "vmin": round(lo, 6),
                            "vmax": round(hi, 6),
                            "mode": "single",
                        }

        buf = io.BytesIO()
        Image.fromarray(rgba_u8, mode="RGBA").save(buf, format="PNG")
        payload = {
            "png_bytes": buf.getvalue(),
            "bounds_wgs84": exact_bounds,
            "band": band,
            "band_count": band_count,
            "stats": stats,
        }
        self._cache_put(cache_key, len(payload["png_bytes"]), payload)
        return payload

    def identify(
        self,
        *,
        lon: float,
        lat: float,
        layers: list[dict[str, Any]],
        tolerance_m: float | None = None,
        zoom: float = 10.0,
    ) -> dict[str, Any]:
        import math as _math
        import numpy as np
        import pyogrio
        from pyproj import CRS, Transformer
        import rasterio
        from shapely.geometry import Point

        if tolerance_m is None:
            meters_per_px = 156543.03 * max(_math.cos(_math.radians(lat)), 0.1) / (2.0 ** max(0.0, min(zoom, 20.0)))
            tolerance_m = max(10.0, meters_per_px * 12.0)

        results: list[dict[str, Any]] = []
        for entry in layers:
            uri = str(entry["resolved_uri"])
            ltype = str(entry.get("type") or "auto")
            file_path, layer_name = _split_uri(uri)
            if ltype == "auto":
                ltype = "raster" if file_path.suffix.lower() in {".tif", ".tiff", ".img", ".vrt", ".asc"} else "vector"

            if ltype == "vector":
                info = pyogrio.read_info(str(file_path), layer=layer_name)
                raw_crs = info.get("crs")
                src_crs = CRS.from_user_input(raw_crs) if raw_crs else None
                if src_crs is not None and not (src_crs.is_geographic and src_crs.to_epsg() == 4326):
                    tr = Transformer.from_crs("EPSG:4326", src_crs, always_xy=True)
                    qx, qy = tr.transform(lon, lat)
                else:
                    qx, qy = lon, lat
                is_deg = src_crs is None or src_crs.is_geographic
                tol_units = (tolerance_m / 111_320.0) if is_deg else tolerance_m
                q_bbox = (qx - tol_units, qy - tol_units, qx + tol_units, qy + tol_units)
                gdf = pyogrio.read_dataframe(str(file_path), layer=layer_name, bbox=q_bbox, max_features=50, fid_as_index=True)
                hits: list[dict[str, Any]] = []
                if len(gdf):
                    pt = Point(qx, qy)
                    distances = gdf.geometry.distance(pt)
                    gdf = gdf.assign(_dist=distances).sort_values("_dist")
                    for fid, row in gdf.iterrows():
                        dist = float(row["_dist"])
                        if dist <= tol_units or dist == 0.0:
                            props = {c: row[c] for c in gdf.columns if c not in {gdf.geometry.name, "_dist"}}
                            hits.append({
                                "fid": int(fid),
                                "distance": round(dist * 111_320.0 if is_deg else dist, 2),
                                "properties": _json_safe_row(props),
                            })
                        if len(hits) >= 5:
                            break
                results.append({"path": uri, "type": "vector", "hits": hits})
            elif ltype == "raster":
                with rasterio.open(uri) as ds:
                    if ds.crs is not None:
                        tr = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True)
                        qx, qy = tr.transform(lon, lat)
                    else:
                        qx, qy = lon, lat
                    left, bottom, right, top = ds.bounds
                    if not (left <= qx <= right and bottom <= qy <= top):
                        results.append({"path": uri, "type": "raster", "inside": False, "bands": []})
                        continue
                    sample = next(ds.sample([(qx, qy)]))
                    band_hits: list[dict[str, Any]] = []
                    for idx in range(1, ds.count + 1):
                        raw_v = float(sample[idx - 1])
                        nodata = ds.nodatavals[idx - 1]
                        is_nd = (not math.isfinite(raw_v)) or (nodata is not None and math.isclose(raw_v, float(nodata), rel_tol=1e-7, abs_tol=1e-12))
                        scale = float(ds.scales[idx - 1]) if ds.scales else 1.0
                        offset = float(ds.offsets[idx - 1]) if ds.offsets else 0.0
                        phys = None if is_nd else (raw_v * scale + offset)
                        band_hits.append({
                            "band": idx,
                            "raw_value": None if is_nd else _clean_scalar(raw_v),
                            "physical_value": None if phys is None else round(float(phys), 6),
                            "unit": ds.units[idx - 1] or None,
                            "is_nodata": bool(is_nd),
                        })
                    results.append({"path": uri, "type": "raster", "inside": True, "bands": band_hits})

        return {"lon": lon, "lat": lat, "tolerance_m": round(tolerance_m, 2), "results": results}

    def get_attributes(
        self,
        authorized_uri: str,
        *,
        page: int = 1,
        page_size: int = 100,
        sort_by: str | None = None,
        order: str = "asc",
        query: str | None = None,
        stats_field: str | None = None,
    ) -> dict[str, Any]:
        import numpy as np
        import pandas as pd
        import pyogrio

        file_path, layer_name = _split_uri(authorized_uri)
        info = pyogrio.read_info(str(file_path), layer=layer_name)
        raw_fields = info.get("fields")
        all_fields = [str(f) for f in raw_fields] if raw_fields is not None else []
        gdf = pyogrio.read_dataframe(str(file_path), layer=layer_name, fid_as_index=True)
        if gdf.crs is not None and not (gdf.crs.is_geographic and gdf.crs.to_epsg() == 4326):
            gdf = gdf.to_crs("EPSG:4326")

        df = pd.DataFrame(gdf.drop(columns=[gdf.geometry.name], errors="ignore"))
        df["_fid"] = gdf.index.astype(int)
        if len(gdf) and gdf.geometry.name in gdf.columns:
            b = gdf.geometry.bounds
            df["_bbox_wgs84"] = [
                [round(float(r.minx), 6), round(float(r.miny), 6), round(float(r.maxx), 6), round(float(r.maxy), 6)]
                if all(math.isfinite(x) for x in (r.minx, r.miny, r.maxx, r.maxy))
                else None
                for r in b.itertuples(index=False)
            ]
        else:
            df["_bbox_wgs84"] = None

        stats_summary: dict[str, Any] | None = None
        if stats_field and stats_field in df.columns:
            series = pd.to_numeric(df[stats_field], errors="coerce").dropna()
            if len(series):
                vals = series.to_numpy(dtype=float)
                vmin, vmax = float(vals.min()), float(vals.max())
                q_breaks = [float(x) for x in np.quantile(vals, [0.0, 0.2, 0.4, 0.6, 0.8, 1.0])]
                eq_breaks = [float(x) for x in np.linspace(vmin, vmax, 6)]
                hist_counts, hist_edges = np.histogram(vals, bins=12)
                stats_summary = {
                    "field": stats_field,
                    "count": int(len(vals)),
                    "min": vmin,
                    "max": vmax,
                    "mean": float(vals.mean()),
                    "median": float(np.median(vals)),
                    "quantile_breaks": q_breaks,
                    "equal_interval_breaks": eq_breaks,
                    "histogram": [
                        {"start": float(hist_edges[i]), "end": float(hist_edges[i + 1]), "count": int(hist_counts[i])}
                        for i in range(len(hist_counts))
                    ],
                }

        if query and query.strip():
            q = query.strip().lower()
            text_cols = [c for c in all_fields if c in df.columns]
            if text_cols:
                mask = df[text_cols].astype(str).apply(lambda col: col.str.lower().str.contains(q, regex=False)).any(axis=1)
                df = df[mask]

        if sort_by and sort_by in df.columns:
            df = df.sort_values(by=sort_by, ascending=(order.lower() != "desc"), kind="mergesort")

        total = int(len(df))
        page = max(1, int(page))
        page_size = max(10, min(int(page_size), 500))
        start = (page - 1) * page_size
        slice_df = df.iloc[start : start + page_size]

        rows: list[dict[str, Any]] = []
        for rec in slice_df.to_dict(orient="records"):
            bbox_val = rec.pop("_bbox_wgs84", None)
            fid_val = int(rec.pop("_fid"))
            safe = _json_safe_row(rec)
            safe["_fid"] = fid_val
            safe["_bbox_wgs84"] = bbox_val
            rows.append(safe)

        return {
            "fields": all_fields,
            "page": page,
            "page_size": page_size,
            "total": total,
            "rows": rows,
            "stats": stats_summary,
        }
