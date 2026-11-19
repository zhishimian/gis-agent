import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import re
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from time import perf_counter

import matplotlib
from matplotlib import colors as mcolors
from matplotlib import font_manager
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.legend import Legend
from matplotlib.text import Annotation, Text
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class MapPanel:
    name: str
    axes: Axes
    crs: str


_BUNDLED_FONTS_DIR = Path(__file__).resolve().parent / "fonts"

_DEFAULT_FONT_FILES: dict[str, tuple[str, ...]] = {
    "serif": (
        str(_BUNDLED_FONTS_DIR / "SourceSerif4-Regular.ttf"),
        str(_BUNDLED_FONTS_DIR / "SourceSerif4-Bold.ttf"),
        str(_BUNDLED_FONTS_DIR / "SourceSerif4-It.ttf"),
        "C:/Windows/Fonts/times.ttf",
        "C:/Windows/Fonts/timesbd.ttf",
        "C:/Windows/Fonts/timesi.ttf",
        "C:/Windows/Fonts/timesbi.ttf",
        "C:/Windows/Fonts/STSONG.TTF",
        "C:/Windows/Fonts/simsun.ttc",
        str(_BUNDLED_FONTS_DIR / "LXGWWenKaiLite-Regular.ttf"),
        str(_BUNDLED_FONTS_DIR / "LXGWWenKaiLite-Medium.ttf"),
    ),
    "kaiti": (
        str(_BUNDLED_FONTS_DIR / "SourceSerif4-Regular.ttf"),
        str(_BUNDLED_FONTS_DIR / "SourceSerif4-Bold.ttf"),
        str(_BUNDLED_FONTS_DIR / "SourceSerif4-It.ttf"),
        str(_BUNDLED_FONTS_DIR / "LXGWWenKaiLite-Regular.ttf"),
        str(_BUNDLED_FONTS_DIR / "LXGWWenKaiLite-Medium.ttf"),
        "C:/Windows/Fonts/times.ttf",
        "C:/Windows/Fonts/timesbd.ttf",
        "C:/Windows/Fonts/timesi.ttf",
        "C:/Windows/Fonts/timesbi.ttf",
        "C:/Windows/Fonts/STKAITI.TTF",
        "C:/Windows/Fonts/simkai.ttf",
        "C:/Windows/Fonts/STSONG.TTF",
    ),
    "fangsong": (
        str(_BUNDLED_FONTS_DIR / "SourceSerif4-Regular.ttf"),
        str(_BUNDLED_FONTS_DIR / "SourceSerif4-Bold.ttf"),
        str(_BUNDLED_FONTS_DIR / "SourceSerif4-It.ttf"),
        "C:/Windows/Fonts/times.ttf",
        "C:/Windows/Fonts/timesbd.ttf",
        "C:/Windows/Fonts/timesi.ttf",
        "C:/Windows/Fonts/timesbi.ttf",
        "C:/Windows/Fonts/STFANGSO.TTF",
        "C:/Windows/Fonts/simfang.ttf",
        str(_BUNDLED_FONTS_DIR / "LXGWWenKaiLite-Regular.ttf"),
        str(_BUNDLED_FONTS_DIR / "LXGWWenKaiLite-Medium.ttf"),
    ),
    "sans": (
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/segoeuii.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/ariali.ttf",
        str(_BUNDLED_FONTS_DIR / "LXGWWenKaiLite-Regular.ttf"),
        str(_BUNDLED_FONTS_DIR / "LXGWWenKaiLite-Medium.ttf"),
    ),
}


def default_font_paths(font_style: str = "serif") -> list[Path]:
    style = font_style.strip().lower()
    if style not in _DEFAULT_FONT_FILES:
        raise ValueError(f"不支持的 font_style '{font_style}'；可选 'serif'、'kaiti'、'fangsong' 或 'sans'。")
    return [Path(p) for p in _DEFAULT_FONT_FILES[style] if Path(p).is_file()]


def configure_plotting(
    font_files: list[str | Path] | None = None,
    *,
    font_style: str | None = None,
    svg_editable_text: bool = True,
) -> dict[str, Any]:
    matplotlib.use("Agg")
    resolved_style = (font_style or "serif").strip().lower()
    if font_files is not None:
        paths = [Path(path).expanduser().resolve() for path in font_files]
    elif font_style is not None:
        paths = [path.expanduser().resolve() for path in default_font_paths(resolved_style)]
    else:
        configured = os.environ.get("GIS_AGENT_FONT_FILES")
        if configured:
            paths = [Path(item).expanduser().resolve() for item in configured.split(";") if item.strip()]
        else:
            paths = [path.expanduser().resolve() for path in default_font_paths(resolved_style)]
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"配置字体不存在：{path}")
        font_manager.fontManager.addfont(str(path))
    names = list(dict.fromkeys(font_manager.FontProperties(fname=str(path)).get_name() for path in paths))
    matplotlib.rcParams.update({
        "font.family": names or ["DejaVu Sans"],
        "axes.unicode_minus": False,
        "pdf.fonttype": 42,
        "svg.fonttype": "none" if svg_editable_text else "path",
    })
    return {
        "backend": matplotlib.get_backend(),
        "fonts": [str(path) for path in paths],
        "families": names,
        "font_style": resolved_style,
        "svg_editable_text": bool(svg_editable_text),
    }


def _fingerprints(paths: list[Path]) -> list[dict[str, str]]:
    files: set[Path] = set()
    for path in paths:
        path = path.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"登记文件不存在：{path}。inputs需物理文件或目录，图层名请单独说明，不能使用GDB/layer或QGIS URI。")
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


def _compute_layout_diagnostics(preview_path: Path, threshold: float = 0.18) -> dict[str, Any]:
    """扫描导出预览图四边纯画布留白占比，辅助 1~2 轮精准收敛。"""
    with Image.open(preview_path) as image:
        arr = np.asarray(image.convert("RGB"), dtype=np.int16)
    height, width = arr.shape[:2]
    if height == 0 or width == 0:
        return {
            "margin_whitespace_ratio": {"top": 0.0, "bottom": 0.0, "left": 0.0, "right": 0.0},
            "excessive_edges": [],
            "excessive_margin_warning": False,
            "threshold": threshold,
        }
    corners = np.vstack([arr[0, 0], arr[0, -1], arr[-1, 0], arr[-1, -1]])
    bg = np.median(corners, axis=0)
    non_bg = np.max(np.abs(arr - bg), axis=2) > 6
    if not np.any(non_bg):
        margins = {"top": 0.5, "bottom": 0.5, "left": 0.5, "right": 0.5}
    else:
        row_has = np.any(non_bg, axis=1)
        col_has = np.any(non_bg, axis=0)
        top_idx = int(np.argmax(row_has))
        bottom_idx = int(height - 1 - np.argmax(row_has[::-1]))
        left_idx = int(np.argmax(col_has))
        right_idx = int(width - 1 - np.argmax(col_has[::-1]))
        margins = {
            "top": round(top_idx / height, 4),
            "bottom": round((height - 1 - bottom_idx) / height, 4),
            "left": round(left_idx / width, 4),
            "right": round((width - 1 - right_idx) / width, 4),
        }
    excessive_edges = [edge for edge, ratio in margins.items() if ratio > threshold]
    return {
        "margin_whitespace_ratio": margins,
        "excessive_edges": excessive_edges,
        "excessive_margin_warning": bool(excessive_edges),
        "threshold": threshold,
    }


def _compute_typography_diagnostics(figure: Figure, height_inches: float) -> dict[str, Any]:
    """统计画面可见文字的字阶分布与可读性（检测过小字号、碎裂字阶与非偶数字号）。"""
    fig_height_pt = max(float(height_inches) * 72.0, 1e-6)
    sizes: set[float] = set()
    for txt in figure.findobj(Text):
        if not txt.get_visible() or not txt.get_text().strip():
            continue
        ax_parent = getattr(txt, "axes", None)
        if ax_parent is not None and not ax_parent.get_visible():
            continue
        size_val = round(float(txt.get_fontsize()), 1)
        if math.isfinite(size_val) and size_val > 0:
            sizes.add(size_val)
    sorted_sizes = sorted(sizes)
    if not sorted_sizes:
        return {
            "font_sizes_pt": [],
            "tier_count": 0,
            "min_font_pt": None,
            "max_font_pt": None,
            "min_font_height_ratio": None,
            "non_even_font_sizes": [],
            "small_text_warning": False,
            "fragmented_font_tiers_warning": False,
            "non_even_font_warning": False,
        }
    min_pt = sorted_sizes[0]
    max_pt = sorted_sizes[-1]
    min_ratio = round(min_pt / fig_height_pt, 4)
    non_even = [s for s in sorted_sizes if abs(s - round(s / 2.0) * 2.0) > 0.25]
    return {
        "font_sizes_pt": sorted_sizes,
        "tier_count": len(sorted_sizes),
        "min_font_pt": min_pt,
        "max_font_pt": max_pt,
        "min_font_height_ratio": min_ratio,
        "non_even_font_sizes": non_even,
        "small_text_warning": bool(min_pt < 9.5 or min_ratio < 0.017),
        "fragmented_font_tiers_warning": bool(len(sorted_sizes) > 5),
        "non_even_font_warning": bool(non_even),
    }


def _collect_inactive_tick_ids(figure: Figure) -> set[int]:
    """收集未被 Matplotlib 实际绘制的坐标轴刻度文本（含 axison=False 与视口外 out-of-range ticks）。"""
    inactive: set[int] = set()
    for ax in figure.axes:
        ax_drawn = bool(ax.get_visible() and getattr(ax, "axison", True))
        for axis, lim in ((ax.xaxis, ax.get_xlim()), (ax.yaxis, ax.get_ylim())):
            vmin, vmax = min(float(lim[0]), float(lim[1])), max(float(lim[0]), float(lim[1]))
            axis_drawn = bool(ax_drawn and axis.get_visible())
            ticks_locs = list(zip(axis.get_major_ticks(), axis.get_majorticklocs())) + list(
                zip(axis.get_minor_ticks(), axis.get_minorticklocs())
            )
            if not axis_drawn:
                inactive.add(id(axis.label))
                inactive.add(id(axis.offsetText))
            for tick, loc in ticks_locs:
                in_view = math.isfinite(float(loc)) and (vmin - 1e-9 <= float(loc) <= vmax + 1e-9)
                if (not axis_drawn) or (not in_view):
                    inactive.add(id(tick.label1))
                    inactive.add(id(tick.label2))
    return inactive


def _compute_cartography_hygiene_diagnostics(
    figure: Figure,
    map_panels: tuple[MapPanel, ...],
) -> dict[str, Any]:
    """检测 AI 制图常见硬伤：堆叠副标题、白底贴片标注框、双刻度重叠与出界裁切文字。"""
    inactive_ids = _collect_inactive_tick_ids(figure)

    # 1. 堆叠副标题检测（figure.texts 顶部成对出现主标题 + 更小/更浅副标题）
    top_texts: list[tuple[float, float, Text]] = []
    inv_fig = figure.transFigure.inverted()
    for txt in figure.texts:
        if not txt.get_visible() or not txt.get_text().strip():
            continue
        try:
            disp_xy = txt.get_transform().transform(txt.get_position())
            fx, fy = inv_fig.transform(disp_xy)
        except Exception:
            continue
        if fy >= 0.78:
            top_texts.append((float(fx), float(fy), txt))

    subtitle_candidates: list[str] = []
    for i in range(len(top_texts)):
        for j in range(i + 1, len(top_texts)):
            fx1, fy1, t1 = top_texts[i]
            fx2, fy2, t2 = top_texts[j]
            if fy1 >= fy2:
                tx_top, ty_top, top_t = fx1, fy1, t1
                tx_low, ty_low, low_t = fx2, fy2, t2
            else:
                tx_top, ty_top, top_t = fx2, fy2, t2
                tx_low, ty_low, low_t = fx1, fy1, t1
            if not (0.008 <= abs(ty_top - ty_low) <= 0.14 and abs(tx_top - tx_low) <= 0.18):
                continue
            fs_top = float(top_t.get_fontsize())
            fs_low = float(low_t.get_fontsize())
            try:
                r1, g1, b1 = mcolors.to_rgba(top_t.get_color())[:3]
                r2, g2, b2 = mcolors.to_rgba(low_t.get_color())[:3]
                lum_top = 0.299 * r1 + 0.587 * g1 + 0.114 * b1
                lum_low = 0.299 * r2 + 0.587 * g2 + 0.114 * b2
            except Exception:
                lum_top, lum_low = 0.0, 0.0
            str_top = top_t.get_text().strip()
            str_low = low_t.get_text().strip()
            if (fs_low < fs_top) or (lum_low > lum_top + 0.10) or (len(str_top) >= 12 and len(str_low) >= 12):
                cand = str_low[:60]
                if cand not in subtitle_candidates:
                    subtitle_candidates.append(cand)

    # 2. 实心白底/带框标注检测
    skip_gids = {"legend", "colorbar", "bivariate_legend"}
    check_axes = (
        [p.axes for p in map_panels if p.axes.get_visible()]
        if map_panels
        else [ax for ax in figure.axes if ax.get_visible()]
    )
    boxed_annotations: list[str] = []
    for ax in check_axes:
        if ax.get_gid() in skip_gids:
            continue
        for ann in ax.findobj(Annotation):
            if getattr(ann, "axes", None) is not ax:
                continue
            if not ann.get_visible() or not ann.get_text().strip():
                continue
            bp = ann.get_bbox_patch()
            if bp is None:
                continue
            fc = bp.get_facecolor()
            if fc is not None and len(fc) >= 4 and float(fc[3]) > 0.15:
                boxed_annotations.append(ann.get_text().strip()[:60])
                if len(boxed_annotations) >= 10:
                    break

    # 3. 坐标轴双刻度重叠检测（原始数字/1e6 刻度 与 °E/W/N/S 手写经纬度共存）
    tick_axes = (
        [p.axes for p in map_panels if p.axes.get_visible()]
        if map_panels
        else [ax for ax in figure.axes if ax.get_visible() and ax.get_gid() not in {"locator_inset", *skip_gids}]
    )
    duplicate_tick_axes: list[str] = []
    for idx, ax in enumerate(tick_axes):
        if not getattr(ax, "axison", True):
            continue
        x_num = 0
        y_num = 0
        off_x = ""
        off_y = ""
        if ax.xaxis.get_visible():
            try:
                off_x = ax.xaxis.get_major_formatter().get_offset().strip()
            except Exception:
                off_x = ""
            x_num = sum(
                1 for lbl in ax.get_xticklabels()
                if id(lbl) not in inactive_ids and lbl.get_visible()
                and re.fullmatch(r"-?\d+(?:\.\d+)?", lbl.get_text().strip())
            )
        if ax.yaxis.get_visible():
            try:
                off_y = ax.yaxis.get_major_formatter().get_offset().strip()
            except Exception:
                off_y = ""
            y_num = sum(
                1 for lbl in ax.get_yticklabels()
                if id(lbl) not in inactive_ids and lbl.get_visible()
                and re.fullmatch(r"-?\d+(?:\.\d+)?", lbl.get_text().strip())
            )
        has_numeric = bool(off_x or off_y or x_num >= 2 or y_num >= 2)
        has_deg = any(
            t.get_visible() and re.search(r"°\s*[EWNS]", t.get_text())
            for t in ax.texts
        )
        if has_numeric and has_deg:
            duplicate_tick_axes.append(str(ax.get_gid() or f"axes_{idx}"))

    # 4. 画布边界出界文字/图例裁切检测 与 主图内边框溢界检测
    clipped_texts: list[str] = []
    frame_overflow_texts: list[str] = []
    try:
        renderer = figure.canvas.get_renderer()
        fig_bbox = figure.bbox
        tol = 3.0

        def _is_clipped(bb) -> bool:
            if bb is None or bb.width <= 0 or bb.height <= 0:
                return False
            return bool(
                bb.x0 < fig_bbox.x0 - tol
                or bb.x1 > fig_bbox.x1 + tol
                or bb.y0 < fig_bbox.y0 - tol
                or bb.y1 > fig_bbox.y1 + tol
            )

        for leg in figure.findobj(Legend):
            if not leg.get_visible():
                continue
            ax_parent = getattr(leg, "axes", None)
            if ax_parent is not None and not ax_parent.get_visible():
                continue
            try:
                if _is_clipped(leg.get_window_extent(renderer)):
                    title_txt = leg.get_title().get_text().strip() if leg.get_title() else ""
                    clipped_texts.append((title_txt or "legend")[:60])
            except Exception:
                pass

        for txt in figure.findobj(Text):
            if len(clipped_texts) >= 10:
                break
            if id(txt) in inactive_ids:
                continue
            content = txt.get_text().strip()
            if not txt.get_visible() or not content:
                continue
            ax_parent = getattr(txt, "axes", None)
            if ax_parent is not None:
                if not ax_parent.get_visible():
                    continue
                if not getattr(ax_parent, "axison", True) and txt not in ax_parent.texts and txt is not ax_parent.title:
                    continue
            try:
                bb = txt.get_window_extent(renderer)
            except Exception:
                continue
            if _is_clipped(bb):
                clipped_texts.append(content[:60])

        # 5. 地图主框溢界检测（检测内部指北针/比例尺/标注是否撞穿或超出主图边框）
        for panel in map_panels:
            ax = panel.axes
            if not ax.get_visible():
                continue
            try:
                ax_bbox = ax.get_window_extent(renderer)
            except Exception:
                continue
            exterior_ids: set[int] = {
                id(ax.title),
                id(getattr(ax, "_left_title", None)),
                id(getattr(ax, "_right_title", None)),
                id(ax.xaxis.label),
                id(ax.yaxis.label),
                id(ax.xaxis.offsetText),
                id(ax.yaxis.offsetText),
            }
            for axis in (ax.xaxis, ax.yaxis):
                for tick in (*axis.get_major_ticks(), *axis.get_minor_ticks()):
                    exterior_ids.add(id(tick.label1))
                    exterior_ids.add(id(tick.label2))
            for leg in ax.findobj(Legend):
                if getattr(leg, "axes", None) is not ax or not leg.get_visible():
                    continue
                try:
                    lbb = leg.get_window_extent(renderer)
                    lcx, lcy = 0.5 * (lbb.x0 + lbb.x1), 0.5 * (lbb.y0 + lbb.y1)
                    if not ax_bbox.contains(lcx, lcy):
                        for t in leg.findobj(Text):
                            exterior_ids.add(id(t))
                except Exception:
                    pass

            for txt in ax.findobj(Text):
                if getattr(txt, "axes", None) is not ax:
                    continue
                if id(txt) in inactive_ids or id(txt) in exterior_ids:
                    continue
                content = txt.get_text().strip()
                if not txt.get_visible() or not content:
                    continue
                if txt.get_gid() in {"graticule_labels", "graticule_ticks"}:
                    continue
                try:
                    bb = txt.get_window_extent(renderer)
                except Exception:
                    continue
                if bb.width <= 0 or bb.height <= 0:
                    continue
                if content == "0°" or re.search(r"°\s*[EWNS]$", content):
                    tcx, tcy = 0.5 * (bb.x0 + bb.x1), 0.5 * (bb.y0 + bb.y1)
                    if not ax_bbox.contains(tcx, tcy):
                        continue
                if (
                    bb.x0 < ax_bbox.x0 + 1.0
                    or bb.x1 > ax_bbox.x1 - 1.0
                    or bb.y0 < ax_bbox.y0 + 1.0
                    or bb.y1 > ax_bbox.y1 - 1.0
                ):
                    frame_overflow_texts.append(content[:60])
    except Exception:
        pass

    clipped_texts = list(dict.fromkeys(clipped_texts))[:10]
    frame_overflow_texts = list(dict.fromkeys(frame_overflow_texts))[:10]
    return {
        "subtitle_detected_warning": bool(subtitle_candidates),
        "subtitle_candidates": subtitle_candidates[:5],
        "callout_box_warning": bool(boxed_annotations),
        "boxed_annotations": boxed_annotations[:10],
        "duplicate_axis_ticks_warning": bool(duplicate_tick_axes),
        "duplicate_tick_axes": duplicate_tick_axes[:5],
        "clipped_text_warning": bool(clipped_texts),
        "clipped_texts": clipped_texts,
        "frame_overflow_warning": bool(frame_overflow_texts),
        "frame_overflow_texts": frame_overflow_texts,
    }


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
    measured = perf_counter()
    sources = _fingerprints([Path(path) for path in inputs])
    timings = {'input_fingerprint_ms': (perf_counter() - measured) * 1000}
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
        measured = perf_counter()
        figure.canvas.draw()
        timings['draw_ms'] = (perf_counter() - measured) * 1000
        measured_hyg = perf_counter()
        hygiene_diag = _compute_cartography_hygiene_diagnostics(figure, map_panels)
        hygiene_ms = (perf_counter() - measured_hyg) * 1000
        measured = perf_counter()
        for format in dict.fromkeys(formats):
            path = output_dir / f"map.{format}"
            figure.savefig(path, format=format, dpi=dpi, bbox_inches=None)
            files[format] = str(path)
        timings['save_ms'] = (perf_counter() - measured) * 1000
        measured = perf_counter()
        figure.savefig(preview, format="png", dpi=min(160, 1800 / max(width, height)), bbox_inches=None)
        timings['preview_ms'] = (perf_counter() - measured) * 1000
    notices = list(dict.fromkeys(str(item.message) for item in captured))
    for notice in notices:
        print(notice, file=sys.stderr)
    if preview.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("预览超过8MiB，请简化预览内容或缩小画布。")
    measured = perf_counter()
    layout_diagnostics = _compute_layout_diagnostics(preview)
    layout_diagnostics["typography"] = _compute_typography_diagnostics(figure, height)
    layout_diagnostics["hygiene"] = hygiene_diag
    timings["diagnostics_ms"] = (perf_counter() - measured) * 1000 + hygiene_ms
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
              "layout_diagnostics": layout_diagnostics,
              "warnings": notices, "metrics": timings}
    manifest.write_text(json.dumps({**result, "map_panels": panels, "environment": environment, "inputs": sources,
                                   "implementation": _fingerprints([Path(__file__)]),
                                   "outputs": _fingerprints([Path(path) for path in [*files.values(), str(preview)]])},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
    if destination := os.environ.get("GIS_AGENT_RESULT_PATH"):
        Path(destination).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result
