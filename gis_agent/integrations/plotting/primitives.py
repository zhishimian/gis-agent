"""出版级轻量可组合地理制图原语与科学色彩体系。

设计原则：
1. 零硬编码整图模板：所有原语均为独立的 Axes / Figure 级可拼装组件，不锁死任意 GridSpec 自由度。
2. 双环境平滑降级：可选依赖 cartopy / cmcrameri / matplotlib_scalebar / adjustText 均采用延迟导入，
   在缺乏外部扩展的桌面 QGIS Python（Tier A）下 100% 回退到纯 Matplotlib + GeoPandas 实现，不抛 ImportError。
3. 反默认（Anti-Slop）保护：显式禁用 jet / rainbow / hsv 等失真或色盲不友好默认色带，
   并提供图底分离中性 Token、双变量色彩矩阵、结构化引出标注与边际剖面容器。
"""
from __future__ import annotations

import math
from typing import Any, Sequence

import matplotlib
from matplotlib import colors as mcolors
from matplotlib import patheffects as path_effects
from matplotlib import ticker as mticker
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpecFromSubplotSpec, SubplotSpec
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Ellipse, FancyBboxPatch, Patch, Rectangle
from matplotlib.path import Path as MplPath
import numpy as np

# ---------------------------------------------------------------------------
# 1. 图底分离与语义中性色 Token（顶刊实证提炼）
# ---------------------------------------------------------------------------
GEO_COLORS: dict[str, str] = {
    "land_muted": "#f0f0f0",
    "land_warm": "#f3f1ec",
    "land_context": "#e5e5e5",
    "ocean_soft": "#e8f1f8",
    "ocean_clean": "#f4f8fb",
    "water_accent": "#7eb6d9",
    "border_muted": "#b8b8b8",
    "border_subtle": "#d0d0d0",
    "border_study": "#333333",
    "nodata_gray": "#d9d9d9",
    "zero_neutral": "#f7f7f7",
    "text_primary": "#1f2328",
    "text_secondary": "#57606a",
    "grid_muted": "#cccccc",
    "highlight_accent": "#d64541",
    "highlight_gold": "#e6ab02",
    "marker_low": "#e6e6e6",
    "marker_mid": "#e8b44c",
    "marker_high": "#d96f32",
    "marker_extreme": "#9e2234",
}

# 禁用失真/高饱和伪彩默认色带（Anti-Slop Guard）
BANNED_CMAPS: frozenset[str] = frozenset({
    "jet",
    "jet_r",
    "rainbow",
    "rainbow_r",
    "hsv",
    "hsv_r",
    "gist_rainbow",
    "gist_rainbow_r",
    "nipy_spectral",
    "nipy_spectral_r",
    "prism",
    "flag",
})

# ---------------------------------------------------------------------------
# 2. 精选科学色带库（Crameri + CARTOColors + Paul Tol + 期刊定性 + 双变量矩阵）
# ---------------------------------------------------------------------------
_CRAMERI_SEQUENTIAL_STOPS: dict[str, list[str]] = {
    "batlow": ["#011959", "#124761", "#2c665d", "#627941", "#a58b2c", "#e69858", "#fdb1ab", "#faccfa"],
    "lajolla": ["#191900", "#3c2614", "#783932", "#c04d49", "#e17750", "#eaa253", "#f5d369", "#fffecb"],
    "oslo": ["#010101", "#0f2133", "#194169", "#3364a1", "#6b8ec8", "#97a9c9", "#c7ccd3", "#ffffff"],
    "lapaz": ["#1a0c64", "#253681", "#305c98", "#487da3", "#7398a0", "#a5a795", "#e4c9b2", "#fef2f3"],
    "bilbao": ["#4c0001", "#7d2e34", "#9d5754", "#a5745b", "#ad9061", "#bbb287", "#cbcac1", "#ffffff"],
    "acton": ["#260d40", "#443766", "#625c88", "#8e648e", "#c26b94", "#d995b8", "#e6c5de", "#f0eafa"],
    "hawaii": ["#8c0273", "#933252", "#985638", "#9c7e20", "#94ae30", "#74ce79", "#61e6ca", "#b3f2fd"],
    "turku": ["#000000", "#2c2c27", "#53523e", "#797750", "#af9c68", "#dba886", "#f9bfb7", "#ffe6e6"],
}

SEQUENTIAL_PALETTES: dict[str, list[str]] = {
    **_CRAMERI_SEQUENTIAL_STOPS,
    "carto_teal": ["#d1eeea", "#a8dbd9", "#85c4c9", "#68abb8", "#4f90a6", "#3b738f", "#2a5674"],
    "carto_mint": ["#e4f1e1", "#b4d9cc", "#89c0b6", "#63a6a0", "#448c8a", "#287274", "#0d585f"],
    "carto_oryel": ["#ecda9a", "#efc47e", "#f3ad6a", "#f7945d", "#f97b57", "#f66356", "#ee4d5a"],
    "carto_peach": ["#fde0c5", "#facba6", "#f8b58b", "#f59e72", "#f2855d", "#ef6a4c", "#eb4a40"],
    "carto_burg": ["#ffc6c4", "#f4a3a8", "#e38191", "#cc607d", "#ad466c", "#8b3058", "#672044"],
    "carto_brwnyl": ["#ede5cf", "#e0c2a2", "#d39c83", "#c1766f", "#a65461", "#813753", "#541f3f"],
    "carto_bluyl": ["#f7feae", "#b7e6a5", "#7ccba2", "#46aea0", "#089099", "#00718b", "#045275"],
    "carto_emrld": ["#d3f2a3", "#97e196", "#6cc08b", "#4c9b82", "#217a79", "#105965", "#074050"],
    "carto_sunsetdark": ["#fcde9c", "#faa476", "#f0746e", "#e34f6f", "#dc3977", "#b9257a", "#7c1d6f"],
    "tol_iridescent": [
        "#fefbe9", "#fcf7d5", "#f5f3c1", "#eaf0b5", "#ddecbf", "#d0e7ca",
        "#c2e3d2", "#b5ddd8", "#a8d8dc", "#9bd2e1", "#8dcbe4", "#81c4e7",
        "#7bbce7", "#7eb2e4", "#88a5dd", "#9398d2", "#9b8ac4", "#9d7db2",
        "#9a709e", "#906388", "#805770", "#684957", "#46353a",
    ],
    "hypsometric": ["#d8e6cf", "#e7ecd1", "#f3eac2", "#e4cfa0", "#cca97f", "#b68e74", "#d6cfc7", "#f5f5f5"],
    "bathymetry": ["#ebf5fb", "#c6e2f2", "#99cae6", "#6baddb", "#408bc9", "#2466a8", "#13427d", "#09244d"],
    "nordic_snow": ["#cfe1ef", "#a9c8e0", "#7fa6ca", "#5682ad", "#36648f", "#23507a", "#163a5b", "#0c2338"],
    "slate_teal": ["#dceae8", "#b2d1ce", "#85b5b2", "#5c9593", "#3d7474", "#275658", "#163a3d"],
    "muted_ochre": ["#f2eadc", "#e0cca9", "#c8ab7c", "#ae8b57", "#8f6b3c", "#6e4f28", "#4d3519"],
    "sage_forest": ["#e5ece2", "#c3d5bc", "#9bbb93", "#739d6c", "#4f7e4b", "#335e32", "#1e4020"],
}

_CRAMERI_DIVERGING_STOPS: dict[str, list[str]] = {
    "vik": ["#001261", "#034a85", "#4b90b3", "#bdd6e3", "#e7c6b2", "#ca8258", "#9c3709", "#590008"],
    "roma": ["#7e1700", "#a05f1b", "#be9d3e", "#d2de98", "#9be2d5", "#46accc", "#2471b4", "#033198"],
    "bam": ["#65024b", "#ac4993", "#da93c8", "#f3dded", "#ebf1df", "#a3c67d", "#538735", "#0d4c00"],
    "broc": ["#2c1a4c", "#2a5183", "#6f92b3", "#c4d2e0", "#e4e4c8", "#aeae73", "#646434", "#262600"],
    "cork": ["#2c194c", "#2a5284", "#688db0", "#c0cfde", "#c8dbc8", "#71a071", "#266a25", "#0f2903"],
}

DIVERGING_PALETTES: dict[str, list[str]] = {
    **_CRAMERI_DIVERGING_STOPS,
    "tol_sunset": ["#364b9a", "#4a7bb7", "#6ea6cd", "#98cae1", "#c2e4ef", "#eaeccc", "#feda8b", "#fdb366", "#f67e4b", "#dd3d2d", "#a50026"],
    "tol_burd": ["#2166ac", "#4393c3", "#92c5de", "#d1e5f0", "#f7f7f7", "#fddbc7", "#f4a582", "#d6604d", "#b2182b"],
    "carto_geyser": ["#008080", "#70a494", "#b4c8a8", "#f6edbd", "#edbb8a", "#de8a5a", "#ca562c"],
    "carto_armyrose": ["#798234", "#a3ad62", "#d0d3a2", "#fdfbe4", "#f0c6c3", "#df91a3", "#d46780"],
    "carto_tealrose": ["#009392", "#72aaa1", "#b1c7b3", "#f1eac8", "#e5b9ad", "#d98994", "#d0587e"],
    "carto_earth": ["#a16928", "#bd925a", "#d6bd8d", "#edeac2", "#b5c8b8", "#79a7ac", "#2887a1"],
    "carto_temps": ["#009392", "#39b185", "#9ccb86", "#e9e29c", "#eeb479", "#e88471", "#cf597e"],
}

QUALITATIVE_PALETTES: dict[str, list[str]] = {
    "okabe_ito": ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#F0E442", "#000000"],
    "tol_muted": ["#332288", "#88CCEE", "#44AA99", "#117733", "#999933", "#DDCC77", "#CC6677", "#882255", "#AA4499"],
    "tol_bright": ["#4477AA", "#EE6677", "#228833", "#CCBB44", "#66CCEE", "#AA3377", "#BBBBBB"],
    "npg": ["#E64B35", "#4DBBD5", "#00A087", "#3C5488", "#F39B7F", "#8491B4", "#91D1C2", "#DC0000", "#7E6148", "#B09C85"],
    "lancet": ["#00468B", "#ED0000", "#42B540", "#0099B4", "#925E9F", "#FDAF91", "#AD002A", "#ADB6B6", "#1B1919"],
    "aaas": ["#3B4992", "#EE0000", "#008B45", "#631879", "#008280", "#BB0021", "#5F559B", "#A20056", "#808180", "#1B1919"],
    "jco": ["#0073C2", "#EFC000", "#868686", "#CD534C", "#7AA6DC", "#003C67", "#8F7700", "#3B3B3B", "#A73030", "#4A6990"],
    "carto_safe": ["#88CCEE", "#CC6677", "#DDCC77", "#117733", "#332288", "#AA4499", "#44AA99", "#999933", "#661100", "#6699CC", "#888888"],
    "carto_prism": ["#5F4690", "#1D6996", "#38A6A5", "#0F8554", "#73AF48", "#EDAD08", "#E17C05", "#CC503E", "#94346E", "#6F4070", "#994E95", "#666666"],
    "morandi_geo": ["#6B8E8E", "#C89B7B", "#8FA3B8", "#D4B483", "#A4849C", "#7D9B76", "#B87A7A", "#9E9A90"],
    "landcover_soft": ["#4D8C57", "#A3C585", "#DFC98A", "#C77A62", "#6CA6CD", "#8B7D7B", "#D9D9D9"],
}


def build_bivariate_palette(
    c00: str = "#e8e8e8",
    c10: str = "#5ac8c8",
    c01: str = "#be64ac",
    c11: str = "#3b4994",
    n: int = 3,
) -> list[list[str]]:
    """按四角色彩进行双线性插值，生成 n×n 双变量二维 hex 矩阵（row 0=低Y，col 0=低X）。"""
    if n < 2 or n > 9:
        raise ValueError("双变量矩阵维度 n 必须在 [2, 9] 之间。")
    rgb00 = np.asarray(mcolors.to_rgb(c00), dtype=float)
    rgb10 = np.asarray(mcolors.to_rgb(c10), dtype=float)
    rgb01 = np.asarray(mcolors.to_rgb(c01), dtype=float)
    rgb11 = np.asarray(mcolors.to_rgb(c11), dtype=float)
    grid: list[list[str]] = []
    for row in range(n):
        v = row / (n - 1)
        row_colors: list[str] = []
        for col in range(n):
            u = col / (n - 1)
            rgb = (
                (1 - u) * (1 - v) * rgb00
                + u * (1 - v) * rgb10
                + (1 - u) * v * rgb01
                + u * v * rgb11
            )
            row_colors.append(mcolors.to_hex(np.clip(rgb, 0.0, 1.0)))
        grid.append(row_colors)
    return grid


BIVARIATE_PALETTES: dict[str, list[list[str]]] = {
    "stevens_pinkblue": [
        ["#e8e8e8", "#ace4e4", "#5ac8c8"],
        ["#dfb0d6", "#a5add3", "#5698b9"],
        ["#be64ac", "#8c62aa", "#3b4994"],
    ],
    "stevens_bluered": [
        ["#e8e8e8", "#e4acac", "#c85a5a"],
        ["#b0d5df", "#ad9ea5", "#985356"],
        ["#64acbe", "#627f8c", "#574249"],
    ],
    "stevens_greenblue": [
        ["#e8e8e8", "#b5c0da", "#6c83b5"],
        ["#b8d6be", "#90b2b3", "#567994"],
        ["#73ae80", "#5a9178", "#2a5a5b"],
    ],
    "stevens_purplegold": [
        ["#e8e8e8", "#e4d9ac", "#c8b35a"],
        ["#cbb8d7", "#c8ada0", "#af8e53"],
        ["#9972af", "#976b82", "#804d36"],
    ],
    "teal_terracotta": [
        ["#f2efe9", "#a3d3cf", "#2b8b8c"],
        ["#eab8a3", "#9b9d9c", "#2d6d78"],
        ["#d6684f", "#8a5a54", "#3b3746"],
    ],
    "bivariate_5x5_ocean_amber": build_bivariate_palette("#f2f2f2", "#1e78b4", "#e66101", "#2b1c47", n=5),
}

_CRAMERI_NAMES: frozenset[str] = frozenset(_CRAMERI_SEQUENTIAL_STOPS) | frozenset(_CRAMERI_DIVERGING_STOPS)


def list_palettes() -> dict[str, list[str]]:
    """返回内置所有类别下的全部可选色带名称。"""
    return {
        "sequential": sorted(SEQUENTIAL_PALETTES),
        "diverging": sorted(DIVERGING_PALETTES),
        "qualitative": sorted(QUALITATIVE_PALETTES),
        "bivariate": sorted(BIVARIATE_PALETTES),
    }


def _check_banned_cmap(name: str) -> None:
    cleaned = name.strip().lower()
    base = cleaned[:-2] if cleaned.endswith("_r") else cleaned
    if cleaned in BANNED_CMAPS or base in BANNED_CMAPS:
        raise ValueError(
            f"禁用失真/伪彩默认色带 '{name}'（感知非线性且对色觉障碍者不友好）。"
            "请改用 'batlow'、'vik'、'roma'、'carto_teal'、'tol_sunset' 或 'viridis' 等科学色带。"
        )


def _lookup_crameri_cmap(base_name: str):
    try:
        import cmcrameri.cm as cmc_cm
    except ImportError:
        return None
    cmap = getattr(cmc_cm, base_name, None)
    if cmap is None and hasattr(cmc_cm, "cmaps"):
        cmap = cmc_cm.cmaps.get(base_name)
    return cmap


def get_scientific_cmap(
    kind: str = "sequential",
    name: str | None = None,
    *,
    n: int | None = None,
    reverse: bool = False,
    nodata_color: str | None = GEO_COLORS["nodata_gray"],
):
    """获取经过科学感知校正的 Colormap，禁用 jet/rainbow 并内置 Tier A 回退。"""
    kind_norm = kind.strip().lower()
    if kind_norm not in {"sequential", "diverging", "qualitative", "categorical"}:
        raise ValueError(f"不支持的色带类型 '{kind}'；仅支持 sequential、diverging、qualitative。")

    defaults = {
        "sequential": "batlow",
        "diverging": "vik",
        "qualitative": "okabe_ito",
        "categorical": "okabe_ito",
    }
    raw_name = (name or defaults[kind_norm]).strip()
    _check_banned_cmap(raw_name)

    want_reverse = bool(reverse)
    base_name = raw_name
    if base_name.endswith("_r"):
        want_reverse = not want_reverse
        base_name = base_name[:-2]
    key = base_name.lower()

    cmap = None
    if key in _CRAMERI_NAMES or (
        key not in SEQUENTIAL_PALETTES
        and key not in DIVERGING_PALETTES
        and key not in QUALITATIVE_PALETTES
    ):
        cmap = _lookup_crameri_cmap(key)

    if cmap is None:
        if key in QUALITATIVE_PALETTES:
            colors = list(QUALITATIVE_PALETTES[key])
            if want_reverse:
                colors = colors[::-1]
            cmap = mcolors.ListedColormap(colors, name=raw_name)
        elif key in SEQUENTIAL_PALETTES:
            stops = list(SEQUENTIAL_PALETTES[key])
            if want_reverse:
                stops = stops[::-1]
            cmap = mcolors.LinearSegmentedColormap.from_list(raw_name, stops, N=256)
        elif key in DIVERGING_PALETTES:
            stops = list(DIVERGING_PALETTES[key])
            if want_reverse:
                stops = stops[::-1]
            cmap = mcolors.LinearSegmentedColormap.from_list(raw_name, stops, N=256)
        else:
            try:
                cmap = matplotlib.colormaps[raw_name]
                if reverse:
                    cmap = cmap.reversed()
            except KeyError as exc:
                raise ValueError(f"未知的科学色带名称：'{raw_name}'。可用色带见 list_palettes()。") from exc
            want_reverse = False

    if want_reverse and cmap is not None and key not in QUALITATIVE_PALETTES:
        if hasattr(cmap, "reversed"):
            cmap = cmap.reversed()

    if n is not None:
        if n <= 0:
            raise ValueError("离散分级数 n 必须为正整数。")
        if key in QUALITATIVE_PALETTES:
            colors = list(QUALITATIVE_PALETTES[key])
            if reverse ^ raw_name.endswith("_r"):
                colors = colors[::-1]
            sampled = [colors[i % len(colors)] for i in range(n)]
            cmap = mcolors.ListedColormap(sampled, name=f"{raw_name}_{n}")
        else:
            cmap = cmap.resampled(n)

    if hasattr(cmap, "with_extremes") and nodata_color is not None:
        cmap = cmap.with_extremes(bad=nodata_color)
    else:
        if hasattr(cmap, "copy"):
            cmap = cmap.copy()
        if nodata_color is not None:
            cmap.set_bad(nodata_color)
    return cmap


def get_palette(name: str = "okabe_ito", n: int | None = None) -> list[str]:
    """按名称返回可直接索引的 hex 色列表（支持定性色板与任意连续/发散色带采样）。"""
    _check_banned_cmap(name)
    key = name.strip().lower()
    if key in QUALITATIVE_PALETTES:
        colors = list(QUALITATIVE_PALETTES[key])
        if n is None:
            return colors
        if n <= 0:
            raise ValueError("n 必须为正整数。")
        return [colors[i % len(colors)] for i in range(n)]
    count = n or 7
    if count <= 0:
        raise ValueError("n 必须为正整数。")
    kind = "diverging" if key in DIVERGING_PALETTES or key in _CRAMERI_DIVERGING_STOPS else "sequential"
    cmap = get_scientific_cmap(kind, name=name)
    if count == 1:
        return [mcolors.to_hex(cmap(0.5))]
    return [mcolors.to_hex(cmap(i / (count - 1))) for i in range(count)]


def get_bivariate_palette(name: str = "stevens_pinkblue") -> list[list[str]]:
    """返回预设 n×n 双变量二维 hex 矩阵（row 0=低Y，col 0=低X）。"""
    key = name.strip().lower()
    if key not in BIVARIATE_PALETTES:
        raise ValueError(f"未知双变量色卡 '{name}'；可选：{sorted(BIVARIATE_PALETTES)}")
    return [list(row) for row in BIVARIATE_PALETTES[key]]


def bivariate_classify(
    x: Sequence[float] | np.ndarray,
    y: Sequence[float] | np.ndarray,
    *,
    bins: int = 3,
    method: str = "quantile",
) -> dict[str, Any]:
    """将双变量数值 (x, y) 同步分箱到 [0, bins-1]×[0, bins-1]，非有限值安全标为 -1。"""
    if bins < 2 or bins > 9:
        raise ValueError("bins 必须在 [2, 9] 之间。")
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    if x_arr.shape != y_arr.shape or x_arr.ndim != 1:
        raise ValueError("x 与 y 必须是等长一维序列。")
    valid = np.isfinite(x_arr) & np.isfinite(y_arr)
    x_bin = np.full(x_arr.shape, -1, dtype=int)
    y_bin = np.full(y_arr.shape, -1, dtype=int)
    pair_index = np.full(x_arr.shape, -1, dtype=int)

    def _edges(vals: np.ndarray) -> np.ndarray:
        if method == "equal":
            edges = np.linspace(float(vals.min()), float(vals.max()), bins + 1)
        elif method == "quantile":
            edges = np.quantile(vals, np.linspace(0.0, 1.0, bins + 1))
        else:
            raise ValueError("method 仅支持 'quantile' 或 'equal'。")
        for idx in range(1, len(edges)):
            if edges[idx] <= edges[idx - 1]:
                edges[idx] = edges[idx - 1] + 1e-12
        return edges

    if not np.any(valid):
        return {
            "x_bin": x_bin,
            "y_bin": y_bin,
            "pair_index": pair_index,
            "x_breaks": [],
            "y_breaks": [],
            "bins": bins,
        }

    x_edges = _edges(x_arr[valid])
    y_edges = _edges(y_arr[valid])
    xv = np.clip(np.digitize(x_arr[valid], x_edges[1:-1], right=True), 0, bins - 1)
    yv = np.clip(np.digitize(y_arr[valid], y_edges[1:-1], right=True), 0, bins - 1)
    x_bin[valid] = xv
    y_bin[valid] = yv
    pair_index[valid] = yv * bins + xv
    return {
        "x_bin": x_bin,
        "y_bin": y_bin,
        "pair_index": pair_index,
        "x_breaks": [float(v) for v in x_edges],
        "y_breaks": [float(v) for v in y_edges],
        "bins": bins,
    }


def _snap_even(val: float, minimum: int = 10) -> int:
    snapped = int(round(float(val) / 2.0) * 2)
    return max(int(minimum), snapped)


def _resolve_pt(explicit: float | None, rc_key: str, fallback: float) -> float:
    if explicit is not None:
        return float(explicit)
    raw = matplotlib.rcParams.get(rc_key, fallback)
    try:
        val = float(raw)
        if math.isfinite(val) and val > 0:
            return val
    except (TypeError, ValueError):
        pass
    return float(fallback)


# ---------------------------------------------------------------------------
# 3. 六大可组合制图原语
# ---------------------------------------------------------------------------
def apply_publication_theme(
    style: str = "light_geo",
    font_scale: float = 1.0,
    *,
    fig_width: float | None = None,
    font_style: str | None = None,
) -> dict[str, Any]:
    """应用出版级微排版基线（4 档偶数大字阶；默认保留既有字体栈，可选 serif/sans 切换）。"""
    if font_scale <= 0 or not math.isfinite(font_scale):
        raise ValueError("font_scale 必须为正数。")
    if fig_width is not None and (fig_width <= 0 or not math.isfinite(fig_width)):
        raise ValueError("fig_width 必须为正数。")
    themes = {
        "light_geo": {
            "figure.facecolor": "#ffffff",
            "axes.facecolor": "#ffffff",
            "axes.edgecolor": "#4a4a4a",
            "axes.labelcolor": GEO_COLORS["text_primary"],
            "text.color": GEO_COLORS["text_primary"],
            "xtick.color": "#4a4a4a",
            "ytick.color": "#4a4a4a",
            "axes.spines.top": True,
            "axes.spines.right": True,
        },
        "editorial_warm": {
            "figure.facecolor": "#faf8f4",
            "axes.facecolor": "#faf8f4",
            "axes.edgecolor": "#524c44",
            "axes.labelcolor": "#22201d",
            "text.color": "#22201d",
            "xtick.color": "#524c44",
            "ytick.color": "#524c44",
            "axes.spines.top": True,
            "axes.spines.right": True,
        },
        "minimal_white": {
            "figure.facecolor": "#ffffff",
            "axes.facecolor": "#ffffff",
            "axes.edgecolor": "#7a7a7a",
            "axes.labelcolor": GEO_COLORS["text_primary"],
            "text.color": GEO_COLORS["text_primary"],
            "xtick.color": "#57606a",
            "ytick.color": "#57606a",
            "axes.spines.top": False,
            "axes.spines.right": False,
        },
    }
    if style not in themes:
        raise ValueError(f"未知主题 '{style}'；可选：{sorted(themes)}")

    if font_style is not None:
        from gis_agent.integrations.plotting.runtime import configure_plotting

        configure_plotting(font_style=font_style)

    width_factor = max(1.0, float(fig_width) / 8.5) if fig_width is not None else 1.0
    scale = float(font_scale) * width_factor
    t4 = _snap_even(10.0 * scale, 10)
    t3 = _snap_even(12.0 * scale, 12)
    t2 = _snap_even(14.0 * scale, 14)
    t1 = _snap_even(16.0 * scale, 16)
    sizes = {
        "T1": t1,
        "T2": t2,
        "T3": t3,
        "T4": t4,
        "title": t1,
        "panel_label": t2,
        "axis": t3,
        "legend": t3,
        "legend_title": t2,
        "tick": t4,
        "base": t3,
        "note": t4,
    }
    params = {
        **themes[style],
        "font.size": t3,
        "axes.titlesize": t1,
        "axes.titleweight": "bold",
        "axes.labelsize": t3,
        "xtick.labelsize": t4,
        "ytick.labelsize": t4,
        "legend.fontsize": t3,
        "legend.title_fontsize": t2,
        "axes.linewidth": 0.65,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.major.size": 3.2,
        "ytick.major.size": 3.2,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "axes.grid": False,
        "legend.frameon": False,
        "savefig.dpi": 300,
    }
    matplotlib.rcParams.update(params)
    return {"style": style, "fonts": sizes, "colors": dict(GEO_COLORS)}


def _format_dms(value: float, *, is_lon: bool, dms: bool) -> str:
    hemi = ("E" if value >= 0 else "W") if is_lon else ("N" if value >= 0 else "S")
    if abs(value) < 1e-9 or (not is_lon and abs(value) < 1e-9):
        return "0°"
    if not dms:
        return f"{abs(value):.4g}°{hemi}"
    total_sec = round(abs(value) * 3600.0)
    deg = total_sec // 3600
    rem = total_sec % 3600
    minutes = rem // 60
    sec = rem % 60
    if sec:
        return f"{deg}°{minutes}'{sec}\"{hemi}"
    if minutes:
        return f"{deg}°{minutes}'{hemi}"
    return f"{deg}°{hemi}"


def _looks_geographic_crs(crs: Any, xlim: tuple[float, float], ylim: tuple[float, float]) -> bool:
    if crs is not None:
        try:
            import pyproj

            parsed = crs if isinstance(crs, pyproj.CRS) else pyproj.CRS.from_user_input(crs)
            return bool(parsed.is_geographic)
        except Exception:
            pass
        text = str(crs).upper()
        if "4326" in text or "4269" in text or "GEOG" in text:
            return True
        return False
    return -180.5 <= xlim[0] <= xlim[1] <= 180.5 and -90.5 <= ylim[0] <= ylim[1] <= 90.5


def add_graticule_frame(
    ax: Axes,
    *,
    crs: Any = None,
    style: str = "ticks_only",
    dms: bool = True,
    step: float | tuple[float, float] | None = None,
    labelsize: float | None = None,
    color: str = GEO_COLORS["text_secondary"],
    grid_alpha: float = 0.38,
    zorder: int = 2,
) -> Any:
    """为普通 Axes 或 Cartopy GeoAxes 渲染克制的度分经纬框线或极简无框底板。"""
    if style not in {"ticks_only", "minimal_grid", "clean_borderless"}:
        raise ValueError(f"不支持的 graticule style '{style}'。")
    tick_pt = _resolve_pt(labelsize, "xtick.labelsize", 10.0)
    is_geo = hasattr(ax, "gridlines") and hasattr(ax, "projection")

    if style == "clean_borderless":
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
        return None

    if is_geo:
        if "geo" in ax.spines:
            ax.spines["geo"].set_visible(True)
            ax.spines["geo"].set_linewidth(0.6)
            ax.spines["geo"].set_edgecolor("#4a4a4a")
        lw = 0.35 if style == "minimal_grid" else 0.0
        alpha = grid_alpha if style == "minimal_grid" else 0.0
        try:
            gl = ax.gridlines(
                draw_labels=True,
                dms=dms,
                x_inline=False,
                y_inline=False,
                linewidth=lw,
                color="#b8b8b8",
                alpha=alpha,
                linestyle="--",
                zorder=zorder,
            )
            gl.top_labels = False
            gl.right_labels = False
            gl.left_labels = True
            gl.bottom_labels = True
            gl.xlabel_style = {"size": tick_pt, "color": color}
            gl.ylabel_style = {"size": tick_pt, "color": color}
            if step is not None:
                sx, sy = step if isinstance(step, (tuple, list)) else (step, step)
                gl.xlocator = mticker.MultipleLocator(sx)
                gl.ylocator = mticker.MultipleLocator(sy)
            return gl
        except Exception:
            if style == "minimal_grid":
                return ax.gridlines(draw_labels=False, linewidth=0.35, color="#b8b8b8", alpha=grid_alpha, linestyle="--", zorder=zorder)
            return None

    # 普通 Matplotlib Axes
    for sp in ax.spines.values():
        sp.set_visible(True)
        sp.set_linewidth(0.6)
        sp.set_edgecolor("#4a4a4a")

    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    is_geog = _looks_geographic_crs(crs, xlim, ylim)
    if step is not None:
        sx, sy = step if isinstance(step, (tuple, list)) else (step, step)
        ax.xaxis.set_major_locator(mticker.MultipleLocator(sx))
        ax.yaxis.set_major_locator(mticker.MultipleLocator(sy))
    else:
        ax.xaxis.set_major_locator(mticker.MaxNLocator(nbins=5))
        ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=5))

    if is_geog:
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda val, _: _format_dms(val, is_lon=True, dms=dms)))
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda val, _: _format_dms(val, is_lon=False, dms=dms)))
    elif crs is not None:
        try:
            import pyproj

            parsed = crs if isinstance(crs, pyproj.CRS) else pyproj.CRS.from_user_input(crs)
            if parsed.is_projected:
                transformer = pyproj.Transformer.from_crs(parsed, "EPSG:4326", always_xy=True)
                y_mid = 0.5 * (ylim[0] + ylim[1])
                x_mid = 0.5 * (xlim[0] + xlim[1])

                def _fmt_x(val: float, _pos: int) -> str:
                    lon, _ = transformer.transform(val, y_mid)
                    return _format_dms(lon, is_lon=True, dms=dms) if math.isfinite(lon) else f"{val:.0f}"

                def _fmt_y(val: float, _pos: int) -> str:
                    _, lat = transformer.transform(x_mid, val)
                    return _format_dms(lat, is_lon=False, dms=dms) if math.isfinite(lat) else f"{val:.0f}"

                ax.xaxis.set_major_formatter(mticker.FuncFormatter(_fmt_x))
                ax.yaxis.set_major_formatter(mticker.FuncFormatter(_fmt_y))
                if ax.get_xlabel() in {"Easting [metre]", "Easting [meter]"}:
                    ax.set_xlabel("")
                if ax.get_ylabel() in {"Northing [metre]", "Northing [meter]"}:
                    ax.set_ylabel("")
        except Exception:
            pass

    ax.tick_params(
        axis="both",
        which="major",
        labelsize=tick_pt,
        colors=color,
        direction="out",
        length=2.8,
        width=0.55,
        labeltop=False,
        labelright=False,
        labelbottom=True,
        labelleft=True,
        top=True,
        right=True,
    )
    if style == "minimal_grid":
        ax.grid(True, which="major", linestyle="--", linewidth=0.35, color="#b8b8b8", alpha=grid_alpha, zorder=zorder)
    else:
        ax.grid(False)
    return None


def build_perceptual_norm(
    values: Any,
    *,
    vmin: float | None = None,
    vmax: float | None = None,
    positive_only: bool = True,
    target_median_pos: float = 0.40,
    gamma_bounds: tuple[float, float] = (0.28, 0.85),
) -> mcolors.Normalize:
    """按有效正值中位数求解感知幂指数 PowerNorm，避免偏态连续场大片发白或发死。"""
    if isinstance(values, np.ma.MaskedArray):
        raw = np.asarray(values.compressed(), dtype=float)
    else:
        raw = np.asarray(values, dtype=float).ravel()
    finite = raw[np.isfinite(raw)]
    sample = finite[finite > 0.0] if positive_only else finite
    if sample.size == 0:
        lo = 0.0 if vmin is None else float(vmin)
        hi = (lo + 1.0) if (vmax is None or float(vmax) <= lo) else float(vmax)
        return mcolors.Normalize(vmin=lo, vmax=hi)

    lo = (0.0 if positive_only else float(np.min(sample))) if vmin is None else float(vmin)
    hi = float(np.max(sample)) if vmax is None else float(vmax)
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        return mcolors.Normalize(vmin=lo, vmax=lo + 1.0)

    p50 = float(np.median(sample))
    u50 = (p50 - lo) / (hi - lo)
    t_mid = float(np.clip(target_median_pos, 0.15, 0.75))
    if 0.0 < u50 < t_mid - 0.05:
        gamma = math.log(t_mid) / math.log(u50)
        gamma = float(np.clip(gamma, float(gamma_bounds[0]), float(gamma_bounds[1])))
        return mcolors.PowerNorm(gamma=round(gamma, 2), vmin=lo, vmax=hi)
    return mcolors.Normalize(vmin=lo, vmax=hi)


def _nice_scale_length(target_m: float) -> float:
    if target_m <= 0 or not math.isfinite(target_m):
        return 1000.0
    exp = 10.0 ** math.floor(math.log10(target_m))
    frac = target_m / exp
    for mult in (1.0, 2.0, 2.5, 5.0, 10.0):
        if frac <= mult * 1.15:
            return mult * exp
    return 10.0 * exp


def add_scalebar_and_north(
    ax: Axes,
    *,
    crs_units: str = "metre",
    lat_center: float | None = None,
    loc: str = "lower left",
    north: bool = True,
    north_loc: str = "upper left",
    color: str = GEO_COLORS["text_primary"],
    fontsize: float | None = None,
    use_matplotlib_scalebar: bool = False,
    scale_style: str = "cartographic",
    north_style: str = "compass_star",
) -> dict[str, Any]:
    """自动选择整洁比例尺长度并渲染出版级分段比例尺（cartographic/ticked）与罗盘星指北针（compass_star/sleek_needle/chevron）。"""
    scale_st = scale_style.strip().lower()
    if scale_st not in {"cartographic", "ticked"}:
        raise ValueError(f"不支持的 scale_style '{scale_style}'；可选 'cartographic' 或 'ticked'。")
    north_st = north_style.strip().lower()
    if north_st not in {"compass_star", "sleek_needle", "chevron"}:
        raise ValueError(f"不支持的 north_style '{north_style}'；可选 'compass_star'、'sleek_needle' 或 'chevron'。")

    tick_pt = _resolve_pt(fontsize, "xtick.labelsize", 10.0)
    north_pt = _snap_even(tick_pt + 2.0, 12)
    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    span_x = abs(float(xlim[1]) - float(xlim[0]))
    if span_x <= 0 or not math.isfinite(span_x):
        return {"scale_length_m": None, "backend": "none"}

    units_norm = crs_units.strip().lower()
    if units_norm in {"metre", "meter", "metres", "meters", "m"}:
        dx_metres = span_x
    elif units_norm in {"km", "kilometre", "kilometres", "kilometer", "kilometers"}:
        dx_metres = span_x * 1000.0
    elif units_norm in {"degree", "degrees", "deg"}:
        lat = float(lat_center) if lat_center is not None else 0.5 * (float(ylim[0]) + float(ylim[1]))
        lat = max(-85.0, min(85.0, lat))
        dx_metres = span_x * 111_320.0 * max(math.cos(math.radians(lat)), 0.1)
    else:
        raise ValueError(f"不支持的 crs_units '{crs_units}'。")

    bar_metres = _nice_scale_length(dx_metres * 0.22)
    frac_len = max(0.08, min(0.35, bar_metres / max(dx_metres, 1e-9)))
    bar_metres = _nice_scale_length(dx_metres * frac_len)
    frac_len = max(0.08, min(0.35, bar_metres / max(dx_metres, 1e-9)))

    use_km = bar_metres >= 1000.0
    unit_label = "km" if use_km else "m"
    end_val = bar_metres / 1000.0 if use_km else bar_metres
    mid_val = end_val / 2.0
    fmt = lambda v: f"{int(round(v))}" if abs(v - round(v)) < 1e-6 else f"{v:.1f}"

    fig = ax.figure
    fig_w, fig_h = map(float, fig.get_size_inches()) if fig is not None else (8.5, 6.0)
    pos = ax.get_position()
    box_w_in = max(float(pos.width) * fig_w, 0.5)
    box_h_in = max(float(pos.height) * fig_h, 0.5)
    aspect_xy = float(np.clip(box_h_in / box_w_in, 0.45, 2.2))

    is_geo = hasattr(ax, "projection")
    backend = f"cartographic_{scale_st}"
    scale_artist = None

    if use_matplotlib_scalebar and (not is_geo) and units_norm in {"metre", "meter", "m"}:
        try:
            from matplotlib_scalebar.scalebar import ScaleBar

            sb = ScaleBar(
                1.0,
                units="m",
                location=loc,
                color=color,
                box_alpha=0.0,
                font_properties={"size": tick_pt},
                length_fraction=0.22,
                scale_loc="bottom",
                pad=0.35,
                sep=2,
            )
            if hasattr(sb, "set_gid"):
                sb.set_gid("scalebar")
            ax.add_artist(sb)
            scale_artist = sb
            backend = "matplotlib_scalebar"
        except Exception:
            pass

    if backend != "matplotlib_scalebar":
        loc_norm = loc.strip().lower()
        end_label = f"{fmt(end_val)} {unit_label}"
        pad_x_left = max(0.055, 0.035 + (tick_pt * 0.45 / 72.0) / box_w_in)
        pad_x_right = max(0.068, 0.045 + (len(end_label) * tick_pt * 0.36 / 72.0) / box_w_in)
        if "right" in loc_norm:
            x0 = max(0.04, 1.0 - pad_x_right - frac_len)
        elif "center" in loc_norm:
            x0 = 0.5 - 0.5 * frac_len
        else:
            x0 = pad_x_left

        lbl_h_frac = (tick_pt * 1.25 / 72.0) / box_h_in
        y0 = (1.0 - 0.052 - 0.015 - lbl_h_frac) if "upper" in loc_norm else 0.052
        halo = [path_effects.withStroke(linewidth=2.2, foreground="#ffffff", alpha=0.92)]
        scale_parts: list[Any] = []

        if scale_st == "cartographic":
            bar_h = 0.0085
            q = frac_len * 0.25
            h2 = frac_len * 0.50
            blocks = (
                (0.0, q, color),
                (q, q, "#ffffff"),
                (h2, h2, color),
            )
            for bx, bw, bcol in blocks:
                seg = Rectangle(
                    (x0 + bx, y0), bw, bar_h,
                    facecolor=bcol, edgecolor=color, linewidth=0.65,
                    transform=ax.transAxes, zorder=12, gid="scalebar",
                )
                ax.add_patch(seg)
                scale_parts.append(seg)
            for frac in (0.0, 0.5, 1.0):
                rx = x0 + frac * frac_len
                riser, = ax.plot(
                    [rx, rx], [y0 + bar_h, y0 + bar_h + 0.0055],
                    color=color, linewidth=0.65, transform=ax.transAxes, zorder=12, gid="scalebar",
                )
                scale_parts.append(riser)
            lbl_y = y0 + bar_h + 0.009
        else:
            base_line, = ax.plot(
                [x0, x0 + frac_len], [y0, y0],
                color=color, linewidth=0.9, transform=ax.transAxes, zorder=12, gid="scalebar",
            )
            scale_parts.append(base_line)
            for frac, th in ((0.0, 0.011), (0.25, 0.0065), (0.5, 0.011), (1.0, 0.011)):
                rx = x0 + frac * frac_len
                tick_ln, = ax.plot(
                    [rx, rx], [y0, y0 + th],
                    color=color, linewidth=0.75, transform=ax.transAxes, zorder=12, gid="scalebar",
                )
                scale_parts.append(tick_ln)
            lbl_y = y0 + 0.015

        ax.text(
            x0, lbl_y, "0", fontsize=tick_pt, color=color, ha="center", va="bottom",
            transform=ax.transAxes, zorder=13, gid="scalebar", path_effects=halo,
        )
        if frac_len >= 0.19:
            ax.text(
                x0 + 0.5 * frac_len, lbl_y, fmt(mid_val), fontsize=tick_pt, color=color,
                ha="center", va="bottom", transform=ax.transAxes, zorder=13, gid="scalebar", path_effects=halo,
            )
        ax.text(
            x0 + frac_len, lbl_y, end_label, fontsize=tick_pt, color=color,
            ha="center", va="bottom", transform=ax.transAxes, zorder=13, gid="scalebar", path_effects=halo,
        )
        scale_artist = scale_parts

    north_artists: list[Any] = []
    if north:
        nloc = north_loc.strip().lower()
        n_h_frac = (north_pt * 1.25 / 72.0) / box_h_in
        r_n = 0.044
        r_s = 0.028
        r_ew = 0.026
        sx = r_ew * aspect_xy
        nx_margin = max(0.055 + sx, 0.055 + (north_pt * 0.50 / 72.0) / box_w_in)
        nx = nx_margin if "left" in nloc else (1.0 - nx_margin if "right" in nloc else 0.50)
        ny = (1.0 - 0.048 - r_n - 0.010 - n_h_frac) if "upper" in nloc else (0.052 + r_s)
        n_halo = [path_effects.withStroke(linewidth=2.0, foreground="#ffffff", alpha=0.90)]

        if north_st == "compass_star":
            r_ring = 0.62 * r_s
            ring = Ellipse(
                (nx, ny), width=2.0 * r_ring * aspect_xy, height=2.0 * r_ring,
                facecolor="none", edgecolor=color, linewidth=0.55, alpha=0.55,
                transform=ax.transAxes, zorder=11.5, gid="north_arrow",
            )
            ax.add_patch(ring)
            north_artists.append(ring)

            wx = 0.25 * sx
            wy = 0.25 * r_ew
            p_n = (nx, ny + r_n)
            p_e = (nx + sx, ny)
            p_s = (nx, ny - r_s)
            p_w = (nx - sx, ny)
            p_ne = (nx + wx, ny + wy)
            p_se = (nx + wx, ny - wy)
            p_sw = (nx - wx, ny - wy)
            p_nw = (nx - wx, ny + wy)
            center = (nx, ny)
            facets = (
                ((center, p_n, p_ne), color),
                ((center, p_n, p_nw), "#ffffff"),
                ((center, p_e, p_se), color),
                ((center, p_e, p_ne), "#ffffff"),
                ((center, p_s, p_sw), color),
                ((center, p_s, p_se), "#ffffff"),
                ((center, p_w, p_nw), color),
                ((center, p_w, p_sw), "#ffffff"),
            )
            for pts, fc in facets:
                tri = matplotlib.patches.Polygon(
                    pts, closed=True, facecolor=fc, edgecolor=color, linewidth=0.55,
                    transform=ax.transAxes, zorder=12, gid="north_arrow",
                )
                ax.add_patch(tri)
                north_artists.append(tri)
        elif north_st == "sleek_needle":
            hw = 0.34 * sx
            mid_y = ny - 0.15 * r_s
            left_p = matplotlib.patches.Polygon(
                [(nx, ny + r_n), (nx - hw, mid_y), (nx, ny)],
                closed=True, facecolor=color, edgecolor=color, linewidth=0.65,
                transform=ax.transAxes, zorder=12, gid="north_arrow",
            )
            right_p = matplotlib.patches.Polygon(
                [(nx, ny + r_n), (nx + hw, mid_y), (nx, ny)],
                closed=True, facecolor="#ffffff", edgecolor=color, linewidth=0.65,
                transform=ax.transAxes, zorder=12, gid="north_arrow",
            )
            tail, = ax.plot(
                [nx, nx], [ny - r_s, ny], color=color, linewidth=0.8,
                transform=ax.transAxes, zorder=12, gid="north_arrow",
            )
            cross, = ax.plot(
                [nx - 0.45 * sx, nx + 0.45 * sx], [ny - 0.35 * r_s, ny - 0.35 * r_s],
                color=color, linewidth=0.65, transform=ax.transAxes, zorder=12, gid="north_arrow",
            )
            ax.add_patch(left_p)
            ax.add_patch(right_p)
            north_artists.extend([left_p, right_p, tail, cross])
        else:
            cw = 0.54 * sx
            left_poly = matplotlib.patches.Polygon(
                [(nx, ny + r_n), (nx - cw, ny - 0.5 * r_s), (nx, ny - 0.05 * r_s)],
                closed=True, facecolor=color, edgecolor=color, linewidth=0.7,
                transform=ax.transAxes, zorder=12, gid="north_arrow",
            )
            right_poly = matplotlib.patches.Polygon(
                [(nx, ny + r_n), (nx + cw, ny - 0.5 * r_s), (nx, ny - 0.05 * r_s)],
                closed=True, facecolor="#ffffff", edgecolor=color, linewidth=0.7,
                transform=ax.transAxes, zorder=12, gid="north_arrow",
            )
            ax.add_patch(left_poly)
            ax.add_patch(right_poly)
            north_artists.extend([left_poly, right_poly])

        n_txt = ax.text(
            nx, ny + r_n + 0.010, "N",
            fontsize=north_pt, fontweight="bold", color=color,
            ha="center", va="bottom", transform=ax.transAxes, zorder=13, gid="north_arrow",
            path_effects=n_halo,
        )
        north_artists.append(n_txt)

    return {
        "scale_length_m": bar_metres,
        "label": f"{fmt(end_val)} {unit_label}",
        "backend": backend,
        "scale_style": scale_st,
        "north_style": north_st,
        "scale_artist": scale_artist,
        "north_artists": north_artists,
    }


def add_locator_inset(
    fig_or_ax: Figure | Axes,
    bounds: Sequence[float],
    *,
    shape: str = "rect",
    projection: Any = None,
    frame_lw: float = 0.75,
    frame_color: str = "#4a4a4a",
    facecolor: str = GEO_COLORS["ocean_soft"],
    zorder: int = 10,
) -> Axes:
    """在画布或主图留白角创建矩形研究区框或带 Circular Clipping 的定位球小图。"""
    if shape not in {"rect", "circle"}:
        raise ValueError("shape 仅支持 'rect' 或 'circle'。")
    if len(bounds) != 4:
        raise ValueError("bounds 必须为 4 元组 [x0, y0, width, height]。")
    bx, by, bw, bh = [float(v) for v in bounds]

    if isinstance(fig_or_ax, Figure):
        fig = fig_or_ax
        kwargs = {"projection": projection} if projection is not None else {}
        inset_ax = fig.add_axes([bx, by, bw, bh], zorder=zorder, **kwargs)
    else:
        parent = fig_or_ax
        fig = parent.figure
        if projection is None:
            inset_ax = parent.inset_axes([bx, by, bw, bh], zorder=zorder)
        else:
            try:
                if fig.get_constrained_layout():
                    fig.canvas.draw()
            except Exception:
                pass
            pos = parent.get_position()
            fig_bounds = [
                pos.x0 + bx * pos.width,
                pos.y0 + by * pos.height,
                bw * pos.width,
                bh * pos.height,
            ]
            inset_ax = fig.add_axes(fig_bounds, projection=projection, zorder=zorder)

    inset_ax.set_gid("locator_inset")
    inset_ax.set_facecolor(facecolor)
    inset_ax.set_xticks([])
    inset_ax.set_yticks([])
    inset_ax.xaxis.label.set_visible(False)
    inset_ax.yaxis.label.set_visible(False)

    if shape == "circle":
        if hasattr(inset_ax, "set_box_aspect"):
            inset_ax.set_box_aspect(1.0)
        theta = np.linspace(0.0, 2.0 * np.pi, 128)
        verts = np.vstack([0.5 + 0.5 * np.cos(theta), 0.5 + 0.5 * np.sin(theta)]).T
        circle_path = MplPath(verts)
        if hasattr(inset_ax, "set_boundary"):
            inset_ax.set_boundary(circle_path, transform=inset_ax.transAxes)
            if "geo" in inset_ax.spines:
                inset_ax.spines["geo"].set_visible(frame_lw > 0)
                inset_ax.spines["geo"].set_linewidth(frame_lw)
                inset_ax.spines["geo"].set_edgecolor(frame_color)
        else:
            for sp in inset_ax.spines.values():
                sp.set_visible(False)
            clip_circle = Circle((0.5, 0.5), 0.5, transform=inset_ax.transAxes)
            inset_ax.patch.set_clip_path(clip_circle)
            if frame_lw > 0:
                ring = Circle(
                    (0.5, 0.5),
                    0.5,
                    transform=inset_ax.transAxes,
                    facecolor="none",
                    edgecolor=frame_color,
                    linewidth=frame_lw,
                    zorder=zorder + 20,
                    clip_on=False,
                )
                inset_ax.add_patch(ring)
            else:
                ring = None

            def _clip_children(_event: Any) -> None:
                for child in inset_ax.get_children():
                    if child in {ring, inset_ax.patch} or isinstance(child, matplotlib.spines.Spine):
                        continue
                    try:
                        child.set_clip_path(clip_circle)
                    except Exception:
                        pass

            fig.canvas.mpl_connect("draw_event", _clip_children)
    else:
        if "geo" in inset_ax.spines:
            inset_ax.spines["geo"].set_visible(frame_lw > 0)
            inset_ax.spines["geo"].set_linewidth(frame_lw)
            inset_ax.spines["geo"].set_edgecolor(frame_color)
        else:
            for sp in inset_ax.spines.values():
                sp.set_visible(frame_lw > 0)
                sp.set_linewidth(frame_lw)
                sp.set_edgecolor(frame_color)
    return inset_ax


def add_bivariate_legend(
    fig_or_ax: Figure | Axes,
    bounds: Sequence[float],
    colors_grid: str | Sequence[Sequence[str]] = "stevens_pinkblue",
    x_label: str = "Variable X",
    y_label: str = "Variable Y",
    *,
    x_ticks: tuple[str, str] = ("Low", "High"),
    y_ticks: tuple[str, str] = ("Low", "High"),
    fontsize: float | None = None,
    arrow_color: str = "#333333",
    title: str | None = None,
    zorder: int = 12,
) -> Axes:
    """绘制 3×3 或 5×5 双变量二维色彩矩阵图例，带正交箭头与边界标签。"""
    matrix = get_bivariate_palette(colors_grid) if isinstance(colors_grid, str) else [list(r) for r in colors_grid]
    n_rows = len(matrix)
    n_cols = len(matrix[0]) if n_rows else 0
    if n_rows < 2 or n_cols != n_rows:
        raise ValueError("colors_grid 必须为方阵（至少 2×2）。")

    label_pt = _resolve_pt(fontsize, "xtick.labelsize", 10.0)
    title_pt = _snap_even(label_pt + 2.0, 12)
    rgb = np.array([[mcolors.to_rgb(c) for c in row] for row in matrix], dtype=float)
    leg_ax = add_locator_inset(
        fig_or_ax, bounds, shape="rect", facecolor="none", frame_lw=0.0, zorder=zorder,
    )
    leg_ax.set_gid("bivariate_legend")
    leg_ax.imshow(
        rgb,
        origin="lower",
        extent=(0, n_cols, 0, n_rows),
        aspect="equal",
        interpolation="nearest",
        zorder=1,
    )
    for k in range(n_cols + 1):
        leg_ax.plot([k, k], [0, n_rows], color="#ffffff", linewidth=0.55, zorder=2)
        leg_ax.plot([0, n_cols], [k, k], color="#ffffff", linewidth=0.55, zorder=2)
    leg_ax.set_xlim(-0.55, n_cols + 0.15)
    leg_ax.set_ylim(-0.55, n_rows + 0.15)

    arrow_kw = dict(arrowstyle="-|>,head_width=0.18,head_length=0.28", color=arrow_color, lw=0.85)
    leg_ax.annotate("", xy=(n_cols + 0.05, -0.16), xytext=(0.0, -0.16), arrowprops=arrow_kw, clip_on=False)
    leg_ax.annotate("", xy=(-0.16, n_rows + 0.05), xytext=(-0.16, 0.0), arrowprops=arrow_kw, clip_on=False)

    leg_ax.text(-0.10, -0.34, x_ticks[0], fontsize=label_pt, color=arrow_color, ha="left", va="top", clip_on=False)
    leg_ax.text(n_cols + 0.10, -0.34, x_ticks[1], fontsize=label_pt, color=arrow_color, ha="right", va="top", clip_on=False)
    leg_ax.text(n_cols * 0.5, -1.05, x_label, fontsize=label_pt, fontweight="bold", color=arrow_color, ha="center", va="top", clip_on=False)

    leg_ax.text(-0.34, -0.10, y_ticks[0], fontsize=label_pt, color=arrow_color, ha="right", va="bottom", rotation=90, clip_on=False)
    leg_ax.text(-0.34, n_rows + 0.10, y_ticks[1], fontsize=label_pt, color=arrow_color, ha="right", va="top", rotation=90, clip_on=False)
    leg_ax.text(-1.05, n_rows * 0.5, y_label, fontsize=label_pt, fontweight="bold", color=arrow_color, ha="right", va="center", rotation=90, clip_on=False)

    if title:
        leg_ax.set_title(title, fontsize=title_pt, fontweight="bold", pad=4, color=arrow_color)
    return leg_ax


def add_clean_legend(
    ax: Axes,
    items: Sequence[Any],
    *,
    title: str | None = None,
    loc: str = "lower left",
    ncol: int = 1,
    frameon: bool = False,
    frame_alpha: float = 0.84,
    show_pct: bool = False,
    nodata_label: str | None = None,
    nodata_color: str = GEO_COLORS["nodata_gray"],
    nodata_hatch: str = "///",
    zero_label: str | None = None,
    zero_color: str = GEO_COLORS["zero_neutral"],
    fontsize: float | None = None,
    title_fontsize: float | None = None,
    bbox_to_anchor: Any = None,
):
    """构建无遮挡紧凑图例，可选附加百分比占比与独立的 0 / NoData 隔离色块。"""
    item_pt = _resolve_pt(fontsize, "legend.fontsize", 10.0)
    hdr_pt = _resolve_pt(title_fontsize, "legend.title_fontsize", _snap_even(item_pt + 2.0, 12))
    handles: list[Any] = []
    for raw in items:
        if isinstance(raw, dict):
            label = str(raw["label"])
            color = raw["color"]
            kind = str(raw.get("kind", "patch")).lower()
            pct = raw.get("pct")
            edgecolor = raw.get("edgecolor", "#666666" if kind == "patch" else color)
            lw = float(raw.get("linewidth", 0.5 if kind == "patch" else 1.5))
            hatch = raw.get("hatch")
            marker = raw.get("marker", "o")
            alpha = float(raw.get("alpha", 1.0))
        elif isinstance(raw, (tuple, list)) and len(raw) >= 2:
            label = str(raw[0])
            color = raw[1]
            pct = raw[2] if len(raw) >= 3 else None
            kind, edgecolor, lw, hatch, marker, alpha = "patch", "#666666", 0.5, None, "o", 1.0
        else:
            raise ValueError("items 元素需为 dict 或 (label, color[, pct]) 元组。")

        if show_pct and pct is not None:
            label = f"{label} ({float(pct):.1f}%)"

        if kind == "line":
            handles.append(Line2D([0], [0], color=color, linewidth=lw, label=label, alpha=alpha))
        elif kind == "marker":
            handles.append(
                Line2D([0], [0], color="none", marker=marker, markerfacecolor=color,
                       markeredgecolor=edgecolor, markeredgewidth=lw, markersize=6, label=label, alpha=alpha)
            )
        else:
            handles.append(
                Patch(facecolor=color, edgecolor=edgecolor, linewidth=lw, hatch=hatch, label=label, alpha=alpha)
            )

    if zero_label:
        handles.append(Patch(facecolor=zero_color, edgecolor="#999999", linewidth=0.5, label=zero_label))
    if nodata_label:
        handles.append(Patch(facecolor=nodata_color, edgecolor="#888888", linewidth=0.5, hatch=nodata_hatch, label=nodata_label))

    legend = ax.legend(
        handles=handles,
        title=title,
        loc=loc,
        ncol=ncol,
        frameon=frameon,
        fontsize=item_pt,
        title_fontsize=hdr_pt,
        bbox_to_anchor=bbox_to_anchor,
        handlelength=1.4,
        handleheight=0.95,
        borderpad=0.35,
        labelspacing=0.35,
        columnspacing=1.0,
    )
    if frameon and legend is not None:
        frame = legend.get_frame()
        frame.set_facecolor("#ffffff")
        frame.set_alpha(frame_alpha)
        frame.set_edgecolor("#d0d0d0")
        frame.set_linewidth(0.5)
    if legend is not None:
        legend.set_gid("legend")
        if legend.get_title() is not None:
            legend.get_title().set_fontweight("bold")
    return legend


def add_leader_callouts(
    ax: Axes,
    items: Sequence[Any],
    *,
    use_adjust_text: bool = True,
    fontsize: float | None = None,
    text_color: str = GEO_COLORS["text_primary"],
    line_color: str = "#4a4a4a",
    dot_color: str | None = None,
    halo_width: float = 2.2,
    line_width: float = 0.65,
    dot_size: float = 14.0,
    transform: Any = None,
    zorder: int = 15,
) -> list[Any]:
    """批量绘制 实心锚点 + L 型折线/直线引出线 + 白色光晕标注（支持 adjustText 防碰撞）。"""
    label_pt = _resolve_pt(fontsize, "font.size", 10.0)
    halo = [path_effects.withStroke(linewidth=halo_width, foreground="#ffffff", alpha=0.92)]
    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    span_x = abs(float(xlim[1]) - float(xlim[0])) or 1.0
    span_y = abs(float(ylim[1]) - float(ylim[0])) or 1.0

    created: list[Any] = []
    auto_texts: list[Any] = []
    auto_xs: list[float] = []
    auto_ys: list[float] = []

    for idx, raw in enumerate(items):
        if isinstance(raw, dict):
            label = str(raw["label"])
            x, y = float(raw["xy"][0]), float(raw["xy"][1])
            xytext = raw.get("xytext")
            dx, dy = raw.get("dx"), raw.get("dy")
            l_shape = bool(raw.get("l_shape", True))
            ha = raw.get("ha")
            va = raw.get("va")
            t_color = raw.get("color", text_color)
            d_color = raw.get("dot_color", dot_color or line_color)
        elif isinstance(raw, (tuple, list)) and len(raw) >= 3:
            label, x, y = str(raw[0]), float(raw[1]), float(raw[2])
            xytext = (float(raw[3]), float(raw[4])) if len(raw) >= 5 else None
            dx, dy, l_shape, ha, va = None, None, True, None, None
            t_color, d_color = text_color, (dot_color or line_color)
        else:
            raise ValueError("callout item 必须包含 label 与 xy。")

        scatter_kw = dict(
            s=dot_size, color=d_color, edgecolor="#ffffff", linewidth=0.45, zorder=zorder, gid="callouts",
        )
        if transform is not None:
            scatter_kw["transform"] = transform
        dot = ax.scatter([x], [y], **scatter_kw)
        created.append(dot)

        if xytext is None and (dx is not None or dy is not None):
            xytext = (x + float(dx or 0.0), y + float(dy or 0.0))

        if xytext is not None:
            tx, ty = float(xytext[0]), float(xytext[1])
            conn = "angle,angleA=0,angleB=90,rad=2" if l_shape else "arc3,rad=0.0"
            ann_kw = dict(
                xy=(x, y),
                xytext=(tx, ty),
                ha=ha or ("left" if tx >= x else "right"),
                va=va or "center",
                fontsize=label_pt,
                color=t_color,
                zorder=zorder + 1,
                gid="callouts",
                arrowprops=dict(arrowstyle="-", color=line_color, lw=line_width, connectionstyle=conn, shrinkA=0, shrinkB=1.5),
                path_effects=halo,
            )
            if transform is not None:
                ann_kw["xycoords"] = transform
                ann_kw["textcoords"] = transform
            ann = ax.annotate(label, **ann_kw)
            created.append(ann)
        elif use_adjust_text and transform is None:
            txt = ax.text(
                x, y, label,
                fontsize=label_pt, color=t_color, ha="center", va="center",
                zorder=zorder + 1, gid="callouts", path_effects=halo,
            )
            auto_texts.append(txt)
            auto_xs.append(x)
            auto_ys.append(y)
            created.append(txt)
        else:
            # Tier A 或带投影 transform 时的确定性黄金角放射避让
            angle = idx * 2.399963229728653
            r_x = 0.045 * span_x
            r_y = 0.045 * span_y
            tx = x + r_x * math.cos(angle)
            ty = y + r_y * math.sin(angle)
            ann_kw = dict(
                xy=(x, y),
                xytext=(tx, ty),
                ha="left" if tx >= x else "right",
                va="center",
                fontsize=label_pt,
                color=t_color,
                zorder=zorder + 1,
                gid="callouts",
                arrowprops=dict(arrowstyle="-", color=line_color, lw=line_width, shrinkA=0, shrinkB=1.5),
                path_effects=halo,
            )
            if transform is not None:
                ann_kw["xycoords"] = transform
                ann_kw["textcoords"] = transform
            ann = ax.annotate(label, **ann_kw)
            created.append(ann)

    if auto_texts:
        adjusted = False
        try:
            from adjustText import adjust_text

            adjust_text(
                auto_texts,
                x=auto_xs,
                y=auto_ys,
                ax=ax,
                arrowprops=dict(arrowstyle="-", color=line_color, lw=line_width),
                expand=(1.15, 1.25),
            )
            adjusted = True
        except Exception:
            adjusted = False
        if not adjusted:
            for idx, (txt, x, y) in enumerate(zip(auto_texts, auto_xs, auto_ys)):
                angle = idx * 2.399963229728653
                txt.set_position((x + 0.04 * span_x * math.cos(angle), y + 0.04 * span_y * math.sin(angle)))
                ax.annotate(
                    "",
                    xy=(x, y),
                    xytext=txt.get_position(),
                    arrowprops=dict(arrowstyle="-", color=line_color, lw=line_width, shrinkA=0, shrinkB=1.5),
                    zorder=zorder,
                )
    return created


def attach_marginal_profiles(
    fig: Figure,
    main_spec: SubplotSpec | None = None,
    *,
    top: bool = True,
    right: bool = True,
    ratio: float = 0.20,
    pad: float = 0.03,
    main_projection: Any = None,
) -> dict[str, Axes | None]:
    """围绕主地图正上方和/或正右侧创建紧密对齐的边际经纬度剖面/统计面板容器。"""
    if not (0.08 <= ratio <= 0.45):
        raise ValueError("ratio 应在 [0.08, 0.45] 之间。")
    nrows = 2 if top else 1
    ncols = 2 if right else 1
    height_ratios = [ratio, 1.0] if top else [1.0]
    width_ratios = [1.0, ratio] if right else [1.0]

    if main_spec is not None:
        gs = GridSpecFromSubplotSpec(
            nrows, ncols, subplot_spec=main_spec,
            width_ratios=width_ratios, height_ratios=height_ratios,
            wspace=pad, hspace=pad,
        )
    else:
        gs = fig.add_gridspec(
            nrows, ncols,
            width_ratios=width_ratios, height_ratios=height_ratios,
            wspace=pad, hspace=pad,
        )

    main_row = 1 if top else 0
    main_col = 0
    main_kw = {"projection": main_projection} if main_projection is not None else {}
    ax_main = fig.add_subplot(gs[main_row, main_col], **main_kw)

    tick_pt = _resolve_pt(None, "xtick.labelsize", 10.0)
    ax_top: Axes | None = None
    if top:
        top_kw = {"sharex": ax_main} if main_projection is None else {}
        ax_top = fig.add_subplot(gs[0, main_col], **top_kw)
        ax_top.tick_params(axis="x", labelbottom=False, bottom=False)
        ax_top.tick_params(axis="y", labelsize=tick_pt)
        ax_top.spines["top"].set_visible(False)
        ax_top.spines["right"].set_visible(False)

    ax_right: Axes | None = None
    if right:
        right_kw = {"sharey": ax_main} if main_projection is None else {}
        ax_right = fig.add_subplot(gs[main_row, 1], **right_kw)
        ax_right.tick_params(axis="y", labelleft=False, left=False)
        ax_right.tick_params(axis="x", labelsize=tick_pt)
        ax_right.spines["top"].set_visible(False)
        ax_right.spines["right"].set_visible(False)

    return {"main": ax_main, "top": ax_top, "right": ax_right}


def _resolve_cbar_cmap(cmap: Any):
    if cmap is None:
        return get_scientific_cmap("sequential", "nordic_snow")
    if isinstance(cmap, str):
        raw = cmap.strip()
        _check_banned_cmap(raw)
        key = raw[:-2].lower() if raw.endswith("_r") else raw.lower()
        if key in DIVERGING_PALETTES or key in _CRAMERI_DIVERGING_STOPS:
            return get_scientific_cmap("diverging", raw)
        if key in SEQUENTIAL_PALETTES or key in _CRAMERI_NAMES:
            return get_scientific_cmap("sequential", raw)
        if key in QUALITATIVE_PALETTES:
            return get_scientific_cmap("qualitative", raw)
        return matplotlib.colormaps[raw]
    return cmap


def _format_cbar_tick(val: float) -> str:
    if abs(val) < 1e-9:
        return "0"
    if abs(val - round(val)) < 1e-6 or (abs(val) >= 10.0 and abs(val - round(val)) < 1e-3):
        return f"{int(round(val))}"
    return f"{val:.3g}"


def _auto_cbar_ticks(norm: Any) -> list[float]:
    vmin = float(getattr(norm, "vmin", 0.0) if getattr(norm, "vmin", None) is not None else 0.0)
    vmax = float(getattr(norm, "vmax", 1.0) if getattr(norm, "vmax", None) is not None else 1.0)
    if not (math.isfinite(vmin) and math.isfinite(vmax)) or vmax <= vmin:
        return [vmin]
    fracs = np.array([0.0, 0.25, 0.5, 0.75, 1.0], dtype=float)
    if hasattr(norm, "inverse"):
        try:
            cand = np.asarray(norm.inverse(fracs), dtype=float)
            if cand.shape == fracs.shape and np.all(np.isfinite(cand)):
                return [float(v) for v in cand]
        except Exception:
            pass
    return [float(v) for v in np.linspace(vmin, vmax, 5)]


def add_continuous_colorbar(
    fig_or_ax: Figure | Axes,
    mappable: Any = None,
    *,
    cmap: Any = None,
    norm: Any = None,
    bounds: Sequence[float] | None = None,
    orientation: str = "horizontal",
    label: str | None = None,
    ticks: Sequence[float] | None = None,
    tick_labels: Sequence[str] | None = None,
    zero_label: str | None = None,
    zero_color: str = GEO_COLORS["zero_neutral"],
    nodata_label: str | None = None,
    nodata_color: str = GEO_COLORS["nodata_gray"],
    nodata_hatch: str = "///",
    fontsize: float | None = None,
    title_fontsize: float | None = None,
    frame_lw: float = 0.55,
    zorder: int = 12,
) -> dict[str, Any]:
    """生成高雅的连续渐变色带，支持 PowerNorm/LogNorm/TwoSlopeNorm 及独立的 0 / NoData 色块。"""
    orient = orientation.strip().lower()
    if orient not in {"horizontal", "vertical"}:
        raise ValueError("orientation 仅支持 'horizontal' 或 'vertical'。")

    if mappable is not None:
        if cmap is None:
            cmap = getattr(mappable, "cmap", None)
        if norm is None:
            norm = getattr(mappable, "norm", None)

    resolved_cmap = _resolve_cbar_cmap(cmap)
    if norm is None:
        if mappable is not None and hasattr(mappable, "get_clim"):
            cmin, cmax = mappable.get_clim()
            norm = mcolors.Normalize(vmin=float(cmin), vmax=float(cmax))
        else:
            norm = mcolors.Normalize(vmin=0.0, vmax=1.0)

    if bounds is not None:
        if len(bounds) != 4:
            raise ValueError("bounds 必须为 4 元组 [x0, y0, width, height]。")
        b = [float(v) for v in bounds]
        if isinstance(fig_or_ax, Figure):
            cax = fig_or_ax.add_axes(b, zorder=zorder)
        else:
            cax = fig_or_ax.inset_axes(b, zorder=zorder)
    else:
        if not isinstance(fig_or_ax, Axes):
            raise ValueError("bounds 为 None 时，fig_or_ax 必须为已创建的 Axes。")
        cax = fig_or_ax

    cax.set_xlim(0.0, 1.0)
    cax.set_ylim(0.0, 1.0)
    cax.set_axis_off()
    cax.set_gid("colorbar")

    tick_pt = _resolve_pt(fontsize, "xtick.labelsize", 10.0)
    hdr_pt = _resolve_pt(title_fontsize, "legend.title_fontsize", _snap_even(tick_pt + 2.0, 12))

    used_ticks = [float(v) for v in ticks] if ticks is not None else _auto_cbar_ticks(norm)
    if tick_labels is not None:
        if len(tick_labels) != len(used_ticks):
            raise ValueError("tick_labels 长度必须与 ticks 一致。")
        used_labels = [str(s) for s in tick_labels]
    else:
        used_labels = [_format_cbar_tick(v) for v in used_ticks]

    swatches: list[tuple[str, str, str | None]] = []
    if zero_label:
        swatches.append((str(zero_label), zero_color, None))
    if nodata_label:
        swatches.append((str(nodata_label), nodata_color, nodata_hatch))

    edge_col = "#6b727a"
    if orient == "horizontal":
        by0, by1 = (0.36, 0.56) if label else (0.42, 0.66)
        sx = 0.02
        sw_w = 0.055
        for s_lbl, s_col, s_hatch in swatches:
            cax.add_patch(Rectangle(
                (sx, by0), sw_w, by1 - by0,
                facecolor=s_col, edgecolor=edge_col, linewidth=frame_lw,
                hatch=s_hatch, zorder=2, gid="colorbar",
            ))
            cax.text(
                sx + 0.5 * sw_w, by0 - 0.11, s_lbl,
                fontsize=tick_pt, color=GEO_COLORS["text_primary"],
                ha="center", va="top", zorder=3, gid="colorbar",
            )
            sx += sw_w + 0.035

        bx0 = (sx + 0.02) if swatches else 0.03
        bx1 = 0.96
        grad = np.linspace(0.0, 1.0, 256)[None, :]
        cax.imshow(
            grad, extent=(bx0, bx1, by0, by1), cmap=resolved_cmap,
            vmin=0.0, vmax=1.0, aspect="auto", interpolation="bilinear",
            zorder=2, gid="colorbar",
        )
        cax.add_patch(Rectangle(
            (bx0, by0), bx1 - bx0, by1 - by0,
            facecolor="none", edgecolor=edge_col, linewidth=frame_lw,
            zorder=3, gid="colorbar",
        ))
        for tv, tlab in zip(used_ticks, used_labels):
            try:
                u = float(np.clip(norm(tv), 0.0, 1.0))
            except Exception:
                continue
            tx = bx0 + u * (bx1 - bx0)
            cax.plot([tx, tx], [by0 - 0.05, by0], color=edge_col, linewidth=frame_lw, zorder=3, gid="colorbar")
            cax.text(
                tx, by0 - 0.11, tlab,
                fontsize=tick_pt, color=GEO_COLORS["text_primary"],
                ha="center", va="top", zorder=3, gid="colorbar",
            )
        if label:
            cax.text(
                0.02 if swatches else bx0, by1 + 0.11, str(label),
                fontsize=hdr_pt, fontweight="bold", color=GEO_COLORS["text_primary"],
                ha="left", va="bottom", zorder=3, gid="colorbar",
            )
    else:
        bx0, bx1 = 0.14, 0.30
        by1 = 0.84 if label else 0.94
        sy = 0.04
        sw_h = 0.065
        for s_lbl, s_col, s_hatch in swatches:
            cax.add_patch(Rectangle(
                (bx0, sy), bx1 - bx0, sw_h,
                facecolor=s_col, edgecolor=edge_col, linewidth=frame_lw,
                hatch=s_hatch, zorder=2, gid="colorbar",
            ))
            cax.text(
                bx1 + 0.08, sy + 0.5 * sw_h, s_lbl,
                fontsize=tick_pt, color=GEO_COLORS["text_primary"],
                ha="left", va="center", zorder=3, gid="colorbar",
            )
            sy += sw_h + 0.035

        by0 = (sy + 0.03) if swatches else 0.06
        grad = np.linspace(0.0, 1.0, 256)[:, None]
        cax.imshow(
            grad, origin="lower", extent=(bx0, bx1, by0, by1), cmap=resolved_cmap,
            vmin=0.0, vmax=1.0, aspect="auto", interpolation="bilinear",
            zorder=2, gid="colorbar",
        )
        cax.add_patch(Rectangle(
            (bx0, by0), bx1 - bx0, by1 - by0,
            facecolor="none", edgecolor=edge_col, linewidth=frame_lw,
            zorder=3, gid="colorbar",
        ))
        for tv, tlab in zip(used_ticks, used_labels):
            try:
                u = float(np.clip(norm(tv), 0.0, 1.0))
            except Exception:
                continue
            ty = by0 + u * (by1 - by0)
            cax.plot([bx1, bx1 + 0.05], [ty, ty], color=edge_col, linewidth=frame_lw, zorder=3, gid="colorbar")
            cax.text(
                bx1 + 0.08, ty, tlab,
                fontsize=tick_pt, color=GEO_COLORS["text_primary"],
                ha="left", va="center", zorder=3, gid="colorbar",
            )
        if label:
            cax.text(
                0.04, by1 + 0.05, str(label),
                fontsize=hdr_pt, fontweight="bold", color=GEO_COLORS["text_primary"],
                ha="left", va="bottom", zorder=3, gid="colorbar",
            )

    return {"ax": cax, "bar_extent": (bx0, bx1, by0, by1), "ticks": used_ticks}


_CORNER_ANCHORS: dict[str, tuple[float, float, int, int]] = {
    "lower right": (0.97, 0.03, -1, 1),
    "lower left": (0.03, 0.03, 1, 1),
    "upper right": (0.97, 0.97, -1, -1),
    "upper left": (0.03, 0.97, 1, -1),
    "lower center": (0.50, 0.03, 0, 1),
    "upper center": (0.50, 0.97, 0, -1),
}


def _corner_window(
    corner: str,
    x_lo: float,
    x_hi: float,
    y_lo: float,
    y_hi: float,
    box_frac: tuple[float, float],
) -> tuple[float, float, float, float]:
    if corner not in _CORNER_ANCHORS:
        raise ValueError(f"不支持的角落 '{corner}'；可选：{sorted(_CORNER_ANCHORS)}")
    fx, fy, dx_dir, dy_dir = _CORNER_ANCHORS[corner]
    bw, bh = float(box_frac[0]), float(box_frac[1])
    if dx_dir > 0:
        u0, u1 = fx, min(1.0, fx + bw)
    elif dx_dir < 0:
        u0, u1 = max(0.0, fx - bw), fx
    else:
        u0, u1 = max(0.0, fx - 0.5 * bw), min(1.0, fx + 0.5 * bw)

    if dy_dir > 0:
        v0, v1 = fy, min(1.0, fy + bh)
    else:
        v0, v1 = max(0.0, fy - bh), fy

    sx, sy = x_hi - x_lo, y_hi - y_lo
    return x_lo + u0 * sx, y_lo + v0 * sy, x_lo + u1 * sx, y_lo + v1 * sy


def _score_vector_occupancy(geoms: Any, wx0: float, wy0: float, wx1: float, wy1: float) -> float:
    from shapely.geometry import box as shp_box

    if hasattr(geoms, "geometry"):
        seq = list(geoms.geometry)
    elif hasattr(geoms, "geom_type"):
        seq = [geoms]
    else:
        seq = list(geoms)
    valid = [g for g in seq if g is not None and not getattr(g, "is_empty", False)]
    if not valid:
        return 0.0
    total_count = len(valid)
    if total_count > 5000:
        step = max(1, total_count // 5000)
        valid = valid[::step][:5000]

    win_box = shp_box(wx0, wy0, wx1, wy1)
    win_area = max(float(win_box.area), 1e-12)
    win_perim = max(2.0 * ((wx1 - wx0) + (wy1 - wy0)), 1e-12)

    area_frac = 0.0
    line_frac = 0.0
    pts_inside = 0
    for g in valid:
        try:
            gx0, gy0, gx1, gy1 = g.bounds
        except Exception:
            continue
        if gx1 < wx0 or gx0 > wx1 or gy1 < wy0 or gy0 > wy1:
            continue
        gtype = getattr(g, "geom_type", "")
        if "Point" in gtype:
            if g.intersects(win_box):
                pts_inside += 1
        elif "Line" in gtype:
            try:
                line_frac += float(g.intersection(win_box).length) / win_perim
            except Exception:
                line_frac += 0.1
        else:
            try:
                area_frac += float(g.intersection(win_box).area) / win_area
            except Exception:
                area_frac += 0.25

    pt_score = min(1.0, pts_inside / max(min(len(valid) * 0.08, 25.0), 1.0)) if pts_inside else 0.0
    return float(min(1.0, max(area_frac + min(line_frac, 1.0), pt_score)))


def rank_quiet_corners(
    ax: Axes,
    geoms: Any = None,
    *,
    raster_mask: np.ndarray | None = None,
    raster_extent: Sequence[float] | None = None,
    exclude: Sequence[str] = (),
    candidates: Sequence[str] = ("lower right", "lower left", "upper right", "upper left"),
    box_frac: tuple[float, float] = (0.30, 0.26),
) -> list[tuple[str, float]]:
    """按信息占有率升序评估主图四隅/中栏的空白度，为指北针、比例尺、圆形区位与内嵌图例选址。"""
    excluded = {str(e).strip().lower() for e in exclude}
    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    x_lo, x_hi = min(float(xlim[0]), float(xlim[1])), max(float(xlim[0]), float(xlim[1]))
    y_lo, y_hi = min(float(ylim[0]), float(ylim[1])), max(float(ylim[0]), float(ylim[1]))

    r_mask: np.ndarray | None = None
    if raster_mask is not None:
        r_mask = np.asarray(raster_mask, dtype=bool)
        if r_mask.ndim != 2 or r_mask.size == 0:
            r_mask = None

    ranked: list[tuple[str, float]] = []
    for raw_corner in candidates:
        corner = str(raw_corner).strip().lower()
        if corner in excluded:
            continue
        wx0, wy0, wx1, wy1 = _corner_window(corner, x_lo, x_hi, y_lo, y_hi, box_frac)
        scores: list[float] = []

        if r_mask is not None:
            rx0, rx1, ry0, ry1 = (
                [float(v) for v in raster_extent]
                if raster_extent is not None
                else [x_lo, x_hi, y_lo, y_hi]
            )
            nrows, ncols = r_mask.shape
            rspan_x = max(rx1 - rx0, 1e-12)
            rspan_y = max(ry1 - ry0, 1e-12)
            c0 = int(np.clip(math.floor((wx0 - rx0) / rspan_x * ncols), 0, ncols))
            c1 = int(np.clip(math.ceil((wx1 - rx0) / rspan_x * ncols), 0, ncols))
            # imshow 默认 origin="upper"：行 0 对应 y=ry1（顶边）
            r0 = int(np.clip(math.floor((ry1 - wy1) / rspan_y * nrows), 0, nrows))
            r1 = int(np.clip(math.ceil((ry1 - wy0) / rspan_y * nrows), 0, nrows))
            if r1 > r0 and c1 > c0:
                scores.append(float(np.mean(r_mask[r0:r1, c0:c1])))
            else:
                scores.append(0.0)

        if geoms is not None:
            scores.append(_score_vector_occupancy(geoms, wx0, wy0, wx1, wy1))

        if not scores:
            win_area = max((wx1 - wx0) * (wy1 - wy0), 1e-12)
            fallback_occ = 0.0
            for artist in (*ax.collections, *ax.patches):
                if not artist.get_visible():
                    continue
                try:
                    bb = artist.get_datalim(ax.transData)
                except Exception:
                    continue
                ix0, iy0 = max(wx0, float(bb.x0)), max(wy0, float(bb.y0))
                ix1, iy1 = min(wx1, float(bb.x1)), min(wy1, float(bb.y1))
                if ix1 > ix0 and iy1 > iy0:
                    fallback_occ += ((ix1 - ix0) * (iy1 - iy0)) / win_area
            scores.append(min(1.0, fallback_occ))

        ranked.append((corner, round(float(max(scores)), 6)))

    ranked.sort(key=lambda item: item[1])
    return ranked


def find_quiet_corner(
    ax: Axes,
    geoms: Any = None,
    *,
    raster_mask: np.ndarray | None = None,
    raster_extent: Sequence[float] | None = None,
    exclude: Sequence[str] = (),
    candidates: Sequence[str] = ("lower right", "lower left", "upper right", "upper left"),
    box_frac: tuple[float, float] = (0.30, 0.26),
) -> str:
    """返回信息占有率最低的最安静主图角落名（用于指北针、比例尺、圆形区位或图例放置）。"""
    ranked = rank_quiet_corners(
        ax,
        geoms,
        raster_mask=raster_mask,
        raster_extent=raster_extent,
        exclude=exclude,
        candidates=candidates,
        box_frac=box_frac,
    )
    if not ranked:
        raise ValueError("所有候选角落均被排除，无法选出空白位置。")
    return ranked[0][0]


__all__ = [
    "BANNED_CMAPS",
    "BIVARIATE_PALETTES",
    "DIVERGING_PALETTES",
    "GEO_COLORS",
    "QUALITATIVE_PALETTES",
    "SEQUENTIAL_PALETTES",
    "add_bivariate_legend",
    "add_clean_legend",
    "add_continuous_colorbar",
    "add_graticule_frame",
    "add_leader_callouts",
    "add_locator_inset",
    "add_scalebar_and_north",
    "apply_publication_theme",
    "attach_marginal_profiles",
    "bivariate_classify",
    "build_bivariate_palette",
    "build_perceptual_norm",
    "find_quiet_corner",
    "get_bivariate_palette",
    "get_palette",
    "get_scientific_cmap",
    "list_palettes",
    "rank_quiet_corners",
]
