import json
from pathlib import Path

from gis_agent.runtime.probe import probe_launcher
from gis_agent.tools.qgis_python import inspect_data, run_python_script


def test_fast_inspect_raster_byte_rgb_and_scaled_dn(qgis_dir: Path, tmp_path: Path) -> None:
    launcher = qgis_dir / "bin/python-qgis-ltr.bat"
    setup = tmp_path / "make_rasters.py"
    rgb_path = tmp_path / "rgb_display.tif"
    dn_path = tmp_path / "scaled_dn.tif"
    gpkg_path = tmp_path / "multi.gpkg"
    setup.write_text(
        f"""import numpy as np, rasterio, geopandas as gpd
from rasterio.transform import from_origin
from rasterio.enums import ColorInterp
from shapely.geometry import Point, Polygon

rgb = np.full((20, 30), 128, dtype='uint8')
with rasterio.open({str(rgb_path)!r}, 'w', driver='GTiff', width=30, height=20, count=3,
                   dtype='uint8', crs='EPSG:32650', transform=from_origin(500000, 3500000, 10, 10)) as dst:
    dst.colorinterp = [ColorInterp.red, ColorInterp.green, ColorInterp.blue]
    for b in (1, 2, 3):
        dst.write(rgb, b)

dn = np.linspace(1000, 8000, 600, dtype='int16').reshape(20, 30)
dn[0, 1] = -9999
with rasterio.open({str(dn_path)!r}, 'w', driver='GTiff', width=30, height=20, count=1,
                   dtype='int16', crs='EPSG:32650', transform=from_origin(500000, 3500000, 30, 30), nodata=-9999) as dst:
    dst.scales = (0.0001,)
    dst.offsets = (0.0,)
    dst.units = ('reflectance',)
    dst.write(dn, 1)

gpd.GeoDataFrame({{'id': [1]}}, geometry=[Point(500010, 3499990)], crs='EPSG:32650').to_file({str(gpkg_path)!r}, layer='pts')
bowtie = Polygon([(0, 0), (10, 10), (10, 0), (0, 10), (0, 0)])
gpd.GeoDataFrame({{'id': [1]}}, geometry=[bowtie], crs='EPSG:32650').to_file({str(gpkg_path)!r}, layer='invalid_poly')
""",
        encoding="utf-8",
    )
    assert run_python_script(launcher, tmp_path / "logs", str(setup))["ok"]

    batch = inspect_data(launcher, tmp_path / "logs", sources=[str(rgb_path), str(dn_path), str(gpkg_path)])
    assert batch["ok"], batch
    rgb_info, dn_info, container_info = batch["data"]["datasets"]

    assert rgb_info["kind"] == "raster"
    assert [b["dtype"] for b in rgb_info["bands"]] == ["uint8", "uint8", "uint8"]
    assert [b["colorinterp"] for b in rgb_info["bands"]] == ["red", "green", "blue"]
    assert rgb_info["units"] == "metre"

    assert dn_info["kind"] == "raster"
    band = dn_info["bands"][0]
    assert band["dtype"] == "int16" and band["nodata"] == -9999
    assert band["scale"] == 0.0001 and band["unit"] == "reflectance"
    assert band["overview_sample"]["raw_min"] == 1000.0 and band["overview_sample"]["raw_max"] == 8000.0
    assert 0.99 < band["overview_sample"]["valid_ratio"] < 1.0

    assert container_info["kind"] == "container"
    assert {layer["name"] for layer in container_info["layers"]} == {"pts", "invalid_poly"}

    poly_uri = f"{gpkg_path}|layername=invalid_poly"
    poly_info = inspect_data(launcher, tmp_path / "logs", source=poly_uri)
    assert poly_info["ok"], poly_info
    assert poly_info["data"]["geometry_sample_check"]["invalid"] == 1
    assert poly_info["data"]["units"] == "metre"


def test_probe_launcher_reports_packages(qgis_dir: Path) -> None:
    info = probe_launcher(qgis_dir / "bin/python-qgis-ltr.bat")
    assert info["has_qgis"] is True
    assert "geopandas" in info["packages"] and "rasterio" in info["packages"]
