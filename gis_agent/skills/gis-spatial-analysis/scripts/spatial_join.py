"""Build a spatial match ledger and optional explicitly chosen field ratio.

Requires GeoPandas, Shapely, pandas, NumPy and a GeoPackage driver. One JSON
settings path is accepted. Writes features.gpkg, matches.csv and structured JSON.
Keeps every source feature and every match; it never chooses a winning match.
Missing, zero-denominator and nonfinite ratios remain null. Errors propagate.
"""
import json
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd


def analyze(source: str, reference: str, source_key: str, reference_key: str,
            output_dir: str, *, source_layer: str | None = None,
            reference_layer: str | None = None, predicate: str = "intersects",
            query_geometry: str = "geometry", analysis_crs: str | None = None,
            numerator: str | None = None, denominator: str | None = None,
            ratio_field: str = "ratio") -> dict:
    left = gpd.read_file(source, layer=source_layer)
    right = gpd.read_file(reference, layer=reference_layer)
    if left.crs is None or right.crs is None:
        raise ValueError("Both layers need a known CRS")
    for data, key in ((left, source_key), (right, reference_key)):
        if data[key].isna().any() or data[key].duplicated().any():
            raise ValueError(f"{key} must be a nonnull unique business key")
        if data.geometry.isna().any() or data.geometry.is_empty.any():
            raise ValueError("Null or empty geometry requires an explicit matching policy")
    if "match_count" in left:
        raise ValueError("match_count already exists; choose an explicit output schema")
    query = left[[source_key, left.geometry.name]].rename(columns={source_key: "source_id"}).copy()
    target = right[[reference_key, right.geometry.name]].rename(columns={reference_key: "reference_id"}).copy()
    query["source_id"] = query["source_id"].astype(object)
    target["reference_id"] = target["reference_id"].astype(object)
    if analysis_crs:
        query, target = query.to_crs(analysis_crs), target.to_crs(analysis_crs)
    elif query.crs != target.crs:
        raise ValueError("CRS mismatch; specify an appropriate analysis_crs")
    if query_geometry == "representative_point":
        query.geometry = query.geometry.representative_point()
    elif query_geometry != "geometry":
        raise ValueError("query_geometry must be geometry or representative_point")
    hits = gpd.sjoin(query, target, how="left", predicate=predicate)
    counts = hits.groupby("source_id")["reference_id"].count()
    result = left.copy()
    result["match_count"] = result[source_key].map(counts).fillna(0).astype(int)
    undefined = None
    if (numerator is None) != (denominator is None):
        raise ValueError("Specify both numerator and denominator")
    if numerator is not None:
        if ratio_field in result:
            raise ValueError(f"Output field already exists: {ratio_field}")
        top = pd.to_numeric(result[numerator], errors="raise")
        bottom = pd.to_numeric(result[denominator], errors="raise")
        valid = top.notna() & bottom.notna() & np.isfinite(top) & np.isfinite(bottom) & (bottom != 0)
        quotient = top.div(bottom.where(valid)).where(valid)
        result[ratio_field] = quotient.where(np.isfinite(quotient))
        undefined = int(result[ratio_field].isna().sum())
    folder = Path(output_dir).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    output, ledger = folder / "features.gpkg", folder / "matches.csv"
    if output.exists() or ledger.exists():
        raise FileExistsError("Choose an unused output directory")
    result.to_file(output, layer="features", driver="GPKG", index=False)
    hits[["source_id", "reference_id"]].dropna(subset=["reference_id"]).to_csv(ledger, index=False)
    return {"outputs": {"features": str(output), "matches": str(ledger)},
            "source_count": len(left), "result_count": len(result),
            "unmatched": int((result.match_count == 0).sum()),
            "multiple_matches": int((result.match_count > 1).sum()),
            "match_pairs": int(counts.sum()), "undefined_ratios": undefined,
            "predicate": predicate, "query_geometry": query_geometry,
            "analysis_crs": str(query.crs), "output_crs": str(result.crs)}


if __name__ == "__main__":
    value = analyze(**json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    Path(os.environ["GIS_AGENT_RESULT_PATH"]).write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
