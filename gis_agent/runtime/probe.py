from functools import lru_cache
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from gis_agent.runtime.paths import import_root


CANDIDATE_PACKAGES = (
    "geopandas",
    "pyogrio",
    "rasterio",
    "shapely",
    "pyproj",
    "numpy",
    "scipy",
    "pandas",
    "matplotlib",
    "mapclassify",
    "rasterstats",
    "networkx",
    "scikit-learn",
    "pykrige",
    "libpysal",
    "esda",
    "duckdb",
    "netCDF4",
    "cartopy",
    "cmcrameri",
    "matplotlib-scalebar",
    "adjustText",
)


def probe_current_python() -> dict[str, Any]:
    packages: dict[str, str] = {}
    module_map = {
        "scikit-learn": "sklearn",
        "matplotlib-scalebar": "matplotlib_scalebar",
    }
    for dist_name in CANDIDATE_PACKAGES:
        mod_name = module_map.get(dist_name, dist_name)
        if importlib.util.find_spec(mod_name) is not None:
            try:
                packages[dist_name] = importlib.metadata.version(dist_name)
            except importlib.metadata.PackageNotFoundError:
                packages[dist_name] = "installed"
    has_qgis = importlib.util.find_spec("qgis") is not None
    has_osgeo = importlib.util.find_spec("osgeo") is not None
    return {
        "executable": sys.executable,
        "version": sys.version.split()[0],
        "has_qgis": has_qgis,
        "has_gdal_osgeo": has_osgeo,
        "packages": packages,
    }


def probe_launcher(launcher: Path, timeout_sec: int = 15) -> dict[str, Any]:
    if launcher.resolve() == Path(sys.executable).resolve():
        return probe_current_python()
    code = (
        "import json; "
        "from gis_agent.runtime.probe import probe_current_python; "
        "print(json.dumps(probe_current_python()))"
    )
    env = dict(os.environ)
    root = str(import_root())
    env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    proc = subprocess.run(
        [str(launcher), "-c", code],
        capture_output=True,
        encoding="utf-8",
        timeout=timeout_sec,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if proc.returncode != 0:
        return {"executable": str(launcher), "ok": False, "error": proc.stderr[-500:]}
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip().startswith("{")]
    return json.loads(lines[-1]) if lines else {"executable": str(launcher), "ok": False}


TIER_B_PACKAGES = (
    "duckdb",
    "esda",
    "libpysal",
    "mapclassify",
    "netCDF4",
    "pykrige",
    "rasterstats",
    "scikit-learn",
)

CARTOGRAPHY_PACKAGES = (
    "adjustText",
    "cartopy",
    "cmcrameri",
    "matplotlib-scalebar",
)


@lru_cache(maxsize=16)
def _cached_runtime_capabilities(launcher_str: str, has_qgis_process: bool) -> dict[str, Any]:
    probe = probe_launcher(Path(launcher_str))
    packages = probe.get("packages") or {}
    has_qgis = bool(has_qgis_process or probe.get("has_qgis"))
    tier_b = [pkg for pkg in TIER_B_PACKAGES if pkg in packages]
    cartography = [pkg for pkg in CARTOGRAPHY_PACKAGES if pkg in packages]
    if has_qgis and tier_b:
        mode = "dual"
    elif tier_b:
        mode = "tier_b"
    elif has_qgis:
        mode = "tier_a_qgis"
    else:
        mode = "core_only"
    return {
        "mode": mode,
        "has_qgis": has_qgis,
        "tier_b_available": tier_b,
        "cartography_available": cartography,
    }


def runtime_capabilities(launcher: Path, *, has_qgis_process: bool = False) -> dict[str, Any]:
    if not launcher.is_file():
        return {
            "mode": "qgis_only" if has_qgis_process else "minimal",
            "has_qgis": has_qgis_process,
            "tier_b_available": [],
            "cartography_available": [],
        }
    return dict(_cached_runtime_capabilities(str(launcher.expanduser().resolve()), has_qgis_process))
