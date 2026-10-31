"""Measure bounded geometry samples without assuming a buffer shape.

Requires GeoPandas, Shapely, NumPy and pandas. One JSON settings path produces structured
JSON. Measurements are planar XY in an explicit projected CRS; geographic
inputs get type/topology facts only unless measure_crs is supplied. Reference
distance requires one selected, nonempty reference feature. Errors propagate.
"""
import json
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely


def leaves(geometry):
    if geometry.geom_type.startswith("Multi") or geometry.geom_type == "GeometryCollection":
        for part in geometry.geoms:
            yield from leaves(part)
    else:
        yield geometry


def measure(source: str, *, layer: str | None = None, key: str | None = None,
            ids: list | None = None, limit: int = 5, measure_crs: str | None = None,
            reference: dict | None = None) -> dict:
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    data = gpd.read_file(source, layer=layer)
    if data.crs is None:
        raise ValueError("Input CRS is unknown")
    total = len(data)
    if ids is not None:
        if key is None:
            raise ValueError("ids requires key")
        data = data.loc[data[key].isin(ids)]
    selected = data.head(limit).copy()
    if measure_crs:
        selected = selected.to_crs(measure_crs)
    projected = selected.crs.is_projected
    ref = None
    if reference:
        if not projected:
            raise ValueError("Distance measurement requires an explicit projected CRS")
        other = gpd.read_file(reference["source"], layer=reference.get("layer"))
        if other.crs is None:
            raise ValueError("Reference CRS is unknown")
        if "key" in reference:
            other = other.loc[other[reference["key"]] == reference["value"]]
        if len(other) != 1 or other.geometry.iloc[0] is None or other.geometry.iloc[0].is_empty:
            raise ValueError("Select exactly one nonempty reference feature")
        ref = other.to_crs(selected.crs).geometry.iloc[0]
        if not ref.is_valid:
            raise ValueError("Reference geometry is invalid")
    facts = []
    for index, row in selected.iterrows():
        geometry = row.geometry
        identifier = row[key] if key else index
        fact = {"id": None if pd.isna(identifier) else identifier, "type": None if geometry is None else geometry.geom_type,
                "null": geometry is None, "empty": None if geometry is None else geometry.is_empty}
        if geometry is not None and not geometry.is_empty:
            parts = list(leaves(geometry))
            polygons = [part for part in parts if part.geom_type == "Polygon"]
            fact.update(valid=bool(geometry.is_valid), leaf_parts=len(parts), polygon_parts=len(polygons),
                        holes=sum(len(part.interiors) for part in polygons), bounds=list(geometry.bounds),
                        has_z=bool(geometry.has_z))
            if projected and geometry.is_valid:
                fact.update(area=float(geometry.area), length=float(geometry.length))
                if ref is not None:
                    coordinates = shapely.get_coordinates(geometry)
                    distances = shapely.distance(shapely.points(coordinates), ref)
                    boundary = geometry.boundary if geometry.geom_type in {"Polygon", "MultiPolygon"} else None
                    fact.update(distance=float(geometry.distance(ref)),
                                polygon_boundary_distance=float(boundary.distance(ref)) if boundary is not None else None,
                                vertex_distance={"count": len(distances), "min": float(np.min(distances)), "max": float(np.max(distances))})
        facts.append(fact)
    return {"dataset_rows": total, "selected_rows": len(data), "measured_rows": len(facts),
            "source_crs": str(data.crs), "measurement_crs": str(selected.crs),
            "coordinate_units": [axis.unit_name for axis in selected.crs.axis_info[:2]],
            "metrics": "planar XY; area in squared coordinate units; length/distance in coordinate units" if projected else "type/topology only; choose measure_crs for metric measurements",
            "vertex_scope": "All components and rings, including repeated ring closure vertices; distances at vertices do not bound every boundary point",
            "facts": facts}


if __name__ == "__main__":
    value = measure(**json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    Path(os.environ["GIS_AGENT_RESULT_PATH"]).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str), encoding="utf-8")
