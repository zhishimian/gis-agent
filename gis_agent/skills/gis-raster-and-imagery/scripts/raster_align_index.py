from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import from_bounds, from_origin
from rasterio.warp import reproject, transform_bounds
from shapely.geometry import box


def run_demo() -> dict[str, Any]:
    """Demonstrate reference-grid snapping, resampling separation, SAVI DN scaling, and zonal stats."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ref_crs = "EPSG:32650"
        ref_transform = from_origin(500000.0, 3500100.0, 10.0, 10.0)
        ref_shape = (6, 6)

        # Build a coarse shifted source raster in a distinct CRS covering the full target UTM tile.
        src_crs = "EPSG:4326"
        min_lon, min_lat, max_lon, max_lat = transform_bounds(
            ref_crs, src_crs, 499990.0, 3500030.0, 500070.0, 3500110.0
        )
        src_transform = from_bounds(min_lon, min_lat, max_lon, max_lat, 4, 4)
        src_nir_dn = np.array(
            [
                [3000, 3200, 3400, 3600],
                [2800, -9999, 3500, 3700],
                [2600, 2900, 3800, 4000],
                [2500, 2700, 3900, 4100],
            ],
            dtype=np.float32,
        )
        src_red_dn = np.array(
            [
                [1000, 1100, 1200, 1300],
                [900, -9999, 1250, 1350],
                [850, 950, 1400, 1450],
                [800, 900, 1500, 1550],
            ],
            dtype=np.float32,
        )
        src_class = np.array(
            [
                [1, 1, 2, 2],
                [1, 0, 2, 2],
                [3, 3, 2, 4],
                [3, 3, 4, 4],
            ],
            dtype=np.uint8,
        )

        # Snap continuous bands using bilinear interpolation while preserving nodata=-9999.0.
        nir_aligned = np.full(ref_shape, -9999.0, dtype=np.float32)
        red_aligned = np.full(ref_shape, -9999.0, dtype=np.float32)
        class_aligned = np.zeros(ref_shape, dtype=np.uint8)

        reproject(
            source=src_nir_dn,
            destination=nir_aligned,
            src_transform=src_transform,
            src_crs=src_crs,
            src_nodata=-9999.0,
            dst_transform=ref_transform,
            dst_crs=ref_crs,
            dst_nodata=-9999.0,
            resampling=Resampling.bilinear,
        )
        reproject(
            source=src_red_dn,
            destination=red_aligned,
            src_transform=src_transform,
            src_crs=src_crs,
            src_nodata=-9999.0,
            dst_transform=ref_transform,
            dst_crs=ref_crs,
            dst_nodata=-9999.0,
            resampling=Resampling.bilinear,
        )
        # Snap categorical land-cover classes strictly using nearest-neighbor resampling.
        reproject(
            source=src_class,
            destination=class_aligned,
            src_transform=src_transform,
            src_crs=src_crs,
            src_nodata=0,
            dst_transform=ref_transform,
            dst_crs=ref_crs,
            dst_nodata=0,
            resampling=Resampling.nearest,
        )

        # Compare SAVI computed on reflectance [0, 1] vs raw 0..10000 DN on valid sample pixels.
        valid = (nir_aligned != -9999.0) & (red_aligned != -9999.0) & np.isfinite(nir_aligned) & np.isfinite(red_aligned)
        nir_ref = nir_aligned[valid] / 10000.0
        red_ref = red_aligned[valid] / 10000.0
        nir_raw = nir_aligned[valid]
        red_raw = red_aligned[valid]

        ndvi_ref = (nir_ref - red_ref) / (nir_ref + red_ref)
        ndvi_raw = (nir_raw - red_raw) / (nir_raw + red_raw)
        savi_ref = 1.5 * (nir_ref - red_ref) / (nir_ref + red_ref + 0.5)
        savi_raw = 1.5 * (nir_raw - red_raw) / (nir_raw + red_raw + 0.5)

        # Write snapped GeoTIFF and compute fast Tier-A zonal means via rasterize + np.bincount.
        out_tif = root / "savi_snapped.tif"
        savi_grid = np.full(ref_shape, -9999.0, dtype=np.float32)
        savi_grid[valid] = savi_ref.astype(np.float32)
        with rasterio.open(
            out_tif,
            "w",
            driver="GTiff",
            height=ref_shape[0],
            width=ref_shape[1],
            count=1,
            dtype="float32",
            crs=ref_crs,
            transform=ref_transform,
            nodata=-9999.0,
        ) as dst:
            dst.write(savi_grid, 1)

        zones = [
            (box(500000.0, 3500070.0, 500030.0, 3500100.0), 1),
            (box(500030.0, 3500040.0, 500060.0, 3500070.0), 2),
        ]
        zone_ids = rasterize(zones, out_shape=ref_shape, transform=ref_transform, fill=0, dtype="int32")
        mask = valid & (zone_ids > 0)
        counts = np.bincount(zone_ids[mask], minlength=3)
        sums = np.bincount(zone_ids[mask], weights=savi_grid[mask], minlength=3)
        zonal_means = {
            f"zone_{zid}": (round(float(sums[zid] / counts[zid]), 6) if counts[zid] > 0 else None)
            for zid in (1, 2)
        }

        return {
            "ok": True,
            "ref_shape": list(ref_shape),
            "valid_pixels": int(valid.sum()),
            "class_unique": sorted(int(v) for v in np.unique(class_aligned)),
            "ndvi_invariant_diff": float(np.max(np.abs(ndvi_ref - ndvi_raw))) if valid.any() else None,
            "savi_mean_scaled_reflectance": round(float(np.mean(savi_ref)), 6) if valid.any() else None,
            "savi_mean_unscaled_dn": round(float(np.mean(savi_raw)), 6) if valid.any() else None,
            "zonal_savi_means": zonal_means,
        }


if __name__ == "__main__":
    payload = run_demo()
    text = json.dumps(payload, ensure_ascii=False)
    if result_path := os.environ.get("GIS_AGENT_RESULT_PATH"):
        Path(result_path).write_text(text, encoding="utf-8")
    print(text)
