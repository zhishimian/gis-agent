import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
from matplotlib import font_manager
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.text import Text


@dataclass(frozen=True)
class MapPanel:
    name: str
    axes: Axes
    crs: str


def configure_plotting(font_files: list[str | Path] | None = None) -> dict[str, Any]:
    matplotlib.use("Agg")
    if font_files is None:
        configured = os.environ.get("GIS_AGENT_FONT_FILES")
        font_files = configured.split(";") if configured else [
            path for path in (Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/arial.ttf")) if path.is_file()
        ]
    paths = [Path(path).expanduser().resolve() for path in font_files]
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"配置字体不存在：{path}")
        font_manager.fontManager.addfont(str(path))
    names = [font_manager.FontProperties(fname=str(path)).get_name() for path in paths]
    matplotlib.rcParams.update({
        "font.family": names or ["DejaVu Sans"], "axes.unicode_minus": False,
        "pdf.fonttype": 42, "svg.fonttype": "path",
    })
    return {"backend": matplotlib.get_backend(), "fonts": [str(path) for path in paths], "families": names}


def _fingerprints(paths: list[Path]) -> list[dict[str, str]]:
    files: set[Path] = set()
    for path in paths:
        path = path.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"登记文件不存在：{path}")
        if path.is_dir():
            files.update(item for item in path.rglob("*") if item.is_file())
        else:
            files.add(path)
        if path.suffix.lower() == ".shp":
            files.update(item for item in path.parent.glob(path.stem + ".*") if item.is_file())
    records = []
    for path in sorted(files):
        with path.open("rb") as stream:
            records.append({"path": str(path), "sha256": hashlib.file_digest(stream, "sha256").hexdigest()})
    return records


def export_figure(
    figure: Figure, output_dir: str | Path, *, formats: tuple[str, ...] = ("png",),
    dpi: int = 300, inputs: tuple[str | Path, ...] = (), map_panels: tuple[MapPanel, ...] = (),
) -> dict[str, Any]:
    if not formats or set(formats) - {"png", "svg", "pdf"}:
        raise ValueError("formats仅支持非空的png、svg、pdf集合。")
    if not math.isfinite(dpi) or dpi <= 0:
        raise ValueError("dpi必须为正数。")
    width, height = map(float, figure.get_size_inches())
    if any(not math.isfinite(value) or value <= 0 for value in (width, height)):
        raise ValueError("画布尺寸必须有限且大于零。")
    for panel in map_panels:
        if panel.axes.figure is not figure or not panel.crs or not panel.axes.has_data():
            raise ValueError(f"地图面板需要属于当前Figure，含实际图元并声明显示CRS：{panel.name}")
        if any(not math.isfinite(value) for value in (*panel.axes.get_xlim(), *panel.axes.get_ylim())):
            raise ValueError(f"地图范围存在非有限数值：{panel.name}")
    fonts = sorted({Path(font_manager.findfont(text.get_fontproperties()))
                    for text in figure.findobj(Text) if text.get_visible() and text.get_text()})
    sources = _fingerprints([Path(path) for path in inputs])
    output_dir = Path(output_dir).expanduser().resolve()
    targets = [output_dir / f"map.{format}" for format in dict.fromkeys(formats)]
    targets += [output_dir / "preview.png", output_dir / "manifest.json"]
    if any(Path(item["path"]) in targets for item in sources):
        raise ValueError("导出路径与输入文件重合。")
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    preview = output_dir / "preview.png"
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        figure.canvas.draw()
        for format in dict.fromkeys(formats):
            path = output_dir / f"map.{format}"
            figure.savefig(path, format=format, dpi=dpi, bbox_inches=None)
            files[format] = str(path)
        figure.savefig(preview, format="png", dpi=min(160, 1800 / max(width, height)), bbox_inches=None)
    notices = list(dict.fromkeys(str(item.message) for item in captured))
    for notice in notices:
        print(notice, file=sys.stderr)
    if preview.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("预览超过8MiB，请简化预览内容或缩小画布。")
    panels = [{"name": panel.name, "crs": panel.crs,
               "extent": [panel.axes.get_xlim()[0], panel.axes.get_ylim()[0], panel.axes.get_xlim()[1], panel.axes.get_ylim()[1]],
               "aspect": panel.axes.get_aspect(),
               "artists": [{"type": type(artist).__name__, "zorder": artist.get_zorder(), "visible": artist.get_visible()}
                           for artist in panel.axes.get_children()]}
              for panel in map_panels]
    environment = {"python": sys.version, "executable": sys.executable, "prefix": sys.prefix,
                   "backend": matplotlib.get_backend(), "fonts": _fingerprints(fonts), "libraries": {}}
    for name in ("matplotlib", "geopandas", "rasterio", "pandas", "numpy", "shapely", "pyproj", "pyogrio"):
        spec = importlib.util.find_spec(name)
        environment["libraries"][name] = {"version": importlib.metadata.version(name), "path": spec.origin if spec else None}
    manifest = output_dir / "manifest.json"
    result = {"version": 2, "ok": True, "files": files, "preview": str(preview), "manifest": str(manifest),
              "artifacts": list(files.values()), "figure": {"width_mm": width * 25.4, "height_mm": height * 25.4, "dpi": dpi},
              "map_panels": [{key: value for key, value in panel.items() if key != "artists"} for panel in panels],
              "warnings": notices}
    manifest.write_text(json.dumps({**result, "map_panels": panels, "environment": environment, "inputs": sources,
                                   "implementation": _fingerprints([Path(__file__)]),
                                   "outputs": _fingerprints([Path(path) for path in [*files.values(), str(preview)]])},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
    if destination := os.environ.get("GIS_AGENT_RESULT_PATH"):
        Path(destination).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result
