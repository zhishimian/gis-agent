import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


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
)


def probe_current_python() -> dict[str, Any]:
    packages: dict[str, str] = {}
    module_map = {"scikit-learn": "sklearn"}
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
    root = str(Path(__file__).resolve().parents[2])
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
