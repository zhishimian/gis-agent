"""Cartographic figure gallery, manifest hygiene parsing, and SVG semantic <g id> layer inspection."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET

_MPL_GENERIC_ID = re.compile(
    r"^(figure|axes|patch|line2d|text|PathCollection|LineCollection|PolyCollection|QuadMesh|xtick|ytick|matplotlib)_?\d*$",
    re.IGNORECASE,
)


def list_svg_layers(svg_path: Path) -> list[dict[str, Any]]:
    if not svg_path.is_file():
        return []
    try:
        tree = ET.parse(svg_path)
    except ET.ParseError:
        return []

    root = tree.getroot()
    seen: set[str] = set()
    layers: list[dict[str, Any]] = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag != "g":
            continue
        gid = (elem.attrib.get("id") or "").strip()
        if not gid or gid in seen:
            continue
        seen.add(gid)
        is_semantic = not bool(_MPL_GENERIC_ID.match(gid))
        if is_semantic or gid.startswith("axes_"):
            layers.append({
                "id": gid,
                "semantic": is_semantic,
                "child_count": len(list(elem)),
            })
    layers.sort(key=lambda item: (not item["semantic"], item["id"]))
    return layers[:80]


def _read_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.is_file():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


class FigureService:
    """Discovers generated PNG/SVG figures paired with layout diagnostics and SVG layer trees."""

    def list_figures(self, output_dir: Path) -> list[dict[str, Any]]:
        if not output_dir.is_dir():
            return []

        groups: dict[tuple[Path, str], dict[str, Any]] = {}
        candidates = sorted(
            (p for p in output_dir.rglob("*") if p.is_file() and p.suffix.lower() in {".png", ".svg"}),
            key=lambda p: p.stat().st_mtime_ns,
        )
        for path in candidates:
            if path.name == "preview.png" and (path.parent / "map.png").exists():
                continue
            key = (path.parent.resolve(), path.stem)
            entry = groups.setdefault(
                key,
                {
                    "id": f"{path.parent.name}_{path.stem}",
                    "name": path.stem,
                    "directory": str(path.parent.resolve()),
                    "png_path": None,
                    "svg_path": None,
                    "preview_path": None,
                    "manifest_path": None,
                    "mtime_ns": path.stat().st_mtime_ns,
                    "bytes": 0,
                },
            )
            ext = path.suffix.lower()
            if ext == ".png":
                entry["png_path"] = str(path.resolve())
                entry["bytes"] = max(entry["bytes"], path.stat().st_size)
            elif ext == ".svg":
                entry["svg_path"] = str(path.resolve())
                if entry["bytes"] == 0:
                    entry["bytes"] = path.stat().st_size
            entry["mtime_ns"] = max(entry["mtime_ns"], path.stat().st_mtime_ns)

        items = sorted(groups.values(), key=lambda x: x["mtime_ns"])
        for idx, item in enumerate(items, 1):
            dir_path = Path(item["directory"])
            preview = dir_path / "preview.png"
            if preview.is_file():
                item["preview_path"] = str(preview.resolve())
            manifest_file = dir_path / "manifest.json"
            manifest = _read_manifest(manifest_file)
            if manifest:
                item["manifest_path"] = str(manifest_file.resolve())
                item["layout_diagnostics"] = manifest.get("layout_diagnostics")
                item["warnings"] = manifest.get("warnings", [])
                item["figure_meta"] = manifest.get("figure")
            if item["svg_path"]:
                item["svg_layers"] = list_svg_layers(Path(item["svg_path"]))
            else:
                item["svg_layers"] = []
            item["version"] = idx
        return items
