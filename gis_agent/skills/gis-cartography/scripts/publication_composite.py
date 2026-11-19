"""Offline publication-grade composite cartography showcase using primitives.py.

Generates synthetic projected spatial catchments, rivers and station hotspots
(no external network or datasets needed) and exports a multi-panel figure
demonstrating apply_publication_theme (even-integer typography scaled by fig_width),
attach_marginal_profiles, bivariate_classify, add_bivariate_legend,
add_graticule_frame, add_scalebar_and_north, add_locator_inset(shape="circle"),
add_leader_callouts, add_clean_legend, layered SVG gid grouping and layout_diagnostics.

Usage:
    python publication_composite.py
    python publication_composite.py settings.json
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, box

from gis_agent.integrations.plotting.primitives import (
    GEO_COLORS,
    add_bivariate_legend,
    add_clean_legend,
    add_graticule_frame,
    add_leader_callouts,
    add_locator_inset,
    add_scalebar_and_north,
    apply_publication_theme,
    attach_marginal_profiles,
    bivariate_classify,
    get_bivariate_palette,
)
from gis_agent.integrations.plotting.runtime import MapPanel, configure_plotting, export_figure


def _build_synthetic_basin_data(seed: int = 42):
    rng = np.random.default_rng(seed)
    x0, y0 = 440_000.0, 3_460_000.0
    nx, ny = 8, 6
    dx, dy = 18_000.0, 18_000.0

    polys = []
    cx_list, cy_list = [], []
    heat_load, veg_gain = [], []
    region_id = []
    for row in range(ny):
        for col in range(nx):
            if col <= 1 and row <= 1:
                continue
            px = x0 + col * dx
            py = y0 + row * dy
            poly = box(px, py, px + dx, py + dy)
            polys.append(poly)
            cx, cy = poly.centroid.x, poly.centroid.y
            cx_list.append(cx)
            cy_list.append(cy)
            u = col / max(nx - 1, 1)
            v = row / max(ny - 1, 1)
            val_x = 18.0 + 52.0 * (0.65 * u + 0.35 * (1.0 - v)) + float(rng.normal(0, 6.0))
            val_y = 0.08 + 0.55 * (0.6 * v + 0.4 * u) + float(rng.normal(0, 0.06))
            if col == 7 and row == 5:
                val_x = np.nan
            heat_load.append(val_x)
            veg_gain.append(val_y)
            region_id.append(f"C{row}{col}")

    gdf = gpd.GeoDataFrame(
        {
            "zone_id": region_id,
            "cx": cx_list,
            "cy": cy_list,
            "heat_load": heat_load,
            "veg_gain": veg_gain,
        },
        geometry=polys,
        crs="EPSG:32650",
    )

    main_river = LineString([
        (456_000, 3_474_000),
        (482_000, 3_496_000),
        (512_000, 3_516_000),
        (542_000, 3_540_000),
        (574_000, 3_560_000),
    ])
    tributary = LineString([
        (482_000, 3_556_000),
        (498_000, 3_534_000),
        (512_000, 3_516_000),
    ])
    rivers = gpd.GeoDataFrame(
        {"name": ["Main Stem", "North Fork"]},
        geometry=[main_river, tributary],
        crs="EPSG:32650",
    )
    study_hull = gpd.GeoDataFrame(geometry=[gdf.union_all()], crs="EPSG:32650")
    return gdf, rivers, study_hull


def draw(
    output_dir: str | None = None,
    *,
    style: str = "light_geo",
    font_style: str = "sans",
    formats: tuple[str, ...] | list[str] = ("png",),
    dpi: int = 300,
) -> dict:
    configure_plotting(font_style=font_style, svg_editable_text=True)
    import matplotlib.pyplot as plt

    target_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="v905_composite_"))
    fig_w, fig_h = 10.2, 6.4
    theme = apply_publication_theme(style=style, fig_width=fig_w)
    t2 = theme["fonts"]["T2"]
    t3 = theme["fonts"]["T3"]
    t4 = theme["fonts"]["T4"]
    gdf, rivers, study_hull = _build_synthetic_basin_data()

    matrix = get_bivariate_palette("teal_terracotta")
    biv = bivariate_classify(gdf["heat_load"], gdf["veg_gain"], bins=3, method="quantile")
    gdf["x_bin"] = biv["x_bin"]
    gdf["y_bin"] = biv["y_bin"]
    gdf["pair_idx"] = biv["pair_index"]

    valid_mask = gdf["pair_idx"] >= 0
    gdf["fill_color"] = [
        matrix[int(yb)][int(xb)] if ok else GEO_COLORS["nodata_gray"]
        for ok, xb, yb in zip(valid_mask, gdf["x_bin"], gdf["y_bin"])
    ]

    fig = plt.figure(figsize=(fig_w, fig_h))
    try:
        outer = fig.add_gridspec(1, 2, width_ratios=[1.70, 1.0], wspace=0.22, left=0.115, right=0.97, top=0.90, bottom=0.11)
        panels = attach_marginal_profiles(fig, outer[0, 0], top=True, right=True, ratio=0.18, pad=0.03)
        ax_map = panels["main"]
        ax_top = panels["top"]
        ax_right = panels["right"]

        ax_map.set_facecolor(GEO_COLORS["ocean_clean"])
        valid_gdf = gdf[valid_mask]
        nodata_gdf = gdf[~valid_mask]
        valid_gdf.plot(
            ax=ax_map,
            color=valid_gdf["fill_color"].tolist(),
            edgecolor="#ffffff",
            linewidth=0.55,
            zorder=2,
            gid="catchments_bivariate",
        )
        if not nodata_gdf.empty:
            nodata_gdf.plot(
                ax=ax_map,
                facecolor=GEO_COLORS["nodata_gray"],
                edgecolor="#ffffff",
                linewidth=0.55,
                hatch="///",
                zorder=2,
                gid="catchments_nodata",
            )
        study_hull.boundary.plot(ax=ax_map, color=GEO_COLORS["border_study"], linewidth=1.0, zorder=3, gid="study_boundary")
        rivers.plot(ax=ax_map, color=GEO_COLORS["water_accent"], linewidth=[1.6, 1.0], zorder=4, gid="hydrography")

        ax_map.set_xlim(434_000, 592_000)
        ax_map.set_ylim(3_454_000, 3_576_000)
        ax_map.set_aspect("equal")

        add_graticule_frame(ax_map, crs="EPSG:32650", style="ticks_only", dms=False, step=(55_000, 40_000), labelsize=t4)
        add_scalebar_and_north(
            ax_map, crs_units="metre", loc="lower right", north=True, north_loc="upper right",
            fontsize=t4, use_matplotlib_scalebar=False,
        )

        valid_rows = gdf[valid_mask].copy()
        valid_rows["tier"] = np.where(
            (valid_rows["x_bin"] == 2) & (valid_rows["y_bin"] == 2), "High-High",
            np.where(valid_rows["x_bin"] >= valid_rows["y_bin"], "Heat Dom.", "Cooling Dom."),
        )
        tier_colors = {
            "High-High": matrix[2][2],
            "Heat Dom.": matrix[0][2],
            "Cooling Dom.": matrix[2][0],
        }
        x_bins = np.linspace(440_000, 584_000, 9)
        bottom_x = np.zeros(len(x_bins) - 1)
        for label_key, col_hex in tier_colors.items():
            counts, _ = np.histogram(valid_rows.loc[valid_rows["tier"] == label_key, "cx"], bins=x_bins)
            ax_top.bar(
                0.5 * (x_bins[:-1] + x_bins[1:]),
                counts,
                width=(x_bins[1] - x_bins[0]) * 0.86,
                bottom=bottom_x,
                color=col_hex,
                edgecolor="#ffffff",
                linewidth=0.35,
            )
            bottom_x += counts
        ax_top.set_ylabel("Zones", fontsize=t3)
        ax_top.set_title("a  Thermal & Green Cooling", loc="left", fontsize=t2, fontweight="bold", pad=8)

        y_bins = np.linspace(3_460_000, 3_568_000, 7)
        left_y = np.zeros(len(y_bins) - 1)
        for label_key, col_hex in tier_colors.items():
            counts, _ = np.histogram(valid_rows.loc[valid_rows["tier"] == label_key, "cy"], bins=y_bins)
            ax_right.barh(
                0.5 * (y_bins[:-1] + y_bins[1:]),
                counts,
                height=(y_bins[1] - y_bins[0]) * 0.86,
                left=left_y,
                color=col_hex,
                edgecolor="#ffffff",
                linewidth=0.35,
            )
            left_y += counts
        ax_right.set_xlabel("Zones", fontsize=t3)

        inset_ax = add_locator_inset(
            ax_map, [0.025, 0.67, 0.24, 0.27], shape="circle", facecolor=GEO_COLORS["ocean_soft"], frame_lw=0.85,
        )
        context_box = gpd.GeoDataFrame(geometry=[box(320_000, 3_340_000, 700_000, 3_720_000)], crs="EPSG:32650")
        basin_macro = gpd.GeoDataFrame(geometry=[box(380_000, 3_400_000, 640_000, 3_640_000).difference(box(380_000, 3_400_000, 460_000, 3_470_000))], crs="EPSG:32650")
        context_box.plot(ax=inset_ax, color=GEO_COLORS["ocean_soft"])
        basin_macro.plot(ax=inset_ax, facecolor=GEO_COLORS["land_muted"], edgecolor=GEO_COLORS["border_muted"], linewidth=0.5)
        gpd.GeoDataFrame(geometry=[box(434_000, 3_454_000, 592_000, 3_576_000)]).boundary.plot(
            ax=inset_ax, color=GEO_COLORS["highlight_accent"], linewidth=1.3,
        )
        inset_ax.set_xlim(350_000, 670_000)
        inset_ax.set_ylim(3_360_000, 3_680_000)

        add_bivariate_legend(
            ax_map,
            [0.08, 0.095, 0.22, 0.22],
            colors_grid=matrix,
            x_label="Heat",
            y_label="Cooling",
            fontsize=t4,
        )

        callouts = [
            {"label": "Upper Gorge", "xy": (566_000, 3_548_000), "xytext": (534_000, 3_566_000), "ha": "right"},
            {"label": "Alluvial Fan", "xy": (512_000, 3_516_000), "xytext": (486_000, 3_542_000), "ha": "right"},
            {"label": "Delta Marsh", "xy": (484_000, 3_496_000), "xytext": (494_000, 3_512_000), "ha": "left"},
            {"label": "Estuary", "xy": (486_000, 3_472_000), "xytext": (506_000, 3_464_000), "ha": "left"},
        ]
        add_leader_callouts(ax_map, callouts, fontsize=t3, dot_color=GEO_COLORS["border_study"])

        ax_bars = fig.add_subplot(outer[0, 1])
        top_zones = valid_rows.sort_values("heat_load", ascending=True).tail(8)
        y_pos = np.arange(len(top_zones))
        ax_bars.barh(
            y_pos,
            top_zones["heat_load"],
            color=top_zones["fill_color"].tolist(),
            edgecolor="#ffffff",
            linewidth=0.45,
            height=0.68,
            gid="top_catchment_bars",
        )
        ax_bars.set_yticks(y_pos)
        ax_bars.set_yticklabels(top_zones["zone_id"].tolist(), fontsize=t4)
        ax_bars.set_xlim(0, 96)
        ax_bars.set_ylim(-3.3, len(top_zones) - 0.25)
        mean_val = float(valid_rows["heat_load"].mean())
        ax_bars.axvline(mean_val, color=GEO_COLORS["border_study"], linestyle="--", linewidth=0.9)
        ax_bars.text(
            2.0, -1.75,
            f"Mean\n{mean_val:.0f}",
            fontsize=t4, color=GEO_COLORS["text_secondary"], ha="left", va="center",
        )
        ax_bars.spines["top"].set_visible(False)
        ax_bars.spines["right"].set_visible(False)
        ax_bars.set_xlabel("Heat Index", fontsize=t3)
        ax_bars.set_title("b  Top-8 Catchments", loc="left", fontsize=t2, fontweight="bold", pad=8)

        total_all = len(gdf)
        legend_items = [
            {
                "label": key,
                "color": col_hex,
                "pct": 100.0 * float((valid_rows["tier"] == key).sum()) / total_all,
            }
            for key, col_hex in tier_colors.items()
        ]
        add_clean_legend(
            ax_bars,
            legend_items,
            title="Regime Share",
            loc="lower right",
            frameon=False,
            show_pct=True,
            nodata_label=f"No data ({100.0 * (~valid_mask).sum() / total_all:.1f}%)",
            fontsize=t4,
            title_fontsize=t3,
        )

        return export_figure(
            fig,
            target_dir,
            formats=tuple(formats),
            dpi=dpi,
            map_panels=(MapPanel("main", ax_map, "EPSG:32650"),),
        )
    finally:
        plt.close(fig)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].strip():
        params = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        draw(**params)
    else:
        draw()
