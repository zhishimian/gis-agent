"""Reproject two layers and clip. Run with run_python_script and one JSON settings path.

Requires the checkout's run_processing helper and QGIS Processing. Writes a new
GeoPackage and structured JSON; failures propagate with a nonzero exit status.
Clipping may split features. Preserve a business key before using this example.
"""
import json
import sys
from pathlib import Path

from gis_agent.integrations.qgis.python_runtime import run_processing


def run(source: str, mask: str, target_crs: str, output: str) -> None:
    destination = Path(output)
    if not destination.is_absolute() or destination.suffix.lower() != ".gpkg":
        raise ValueError("output must be an absolute GeoPackage path")
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    def job() -> dict:
        import processing

        projected = processing.run("native:reprojectlayer", {
            "INPUT": source, "TARGET_CRS": target_crs, "OUTPUT": "TEMPORARY_OUTPUT",
        })["OUTPUT"]
        overlay = processing.run("native:reprojectlayer", {
            "INPUT": mask, "TARGET_CRS": target_crs, "OUTPUT": "TEMPORARY_OUTPUT",
        })["OUTPUT"]
        return processing.run("native:clip", {
            "INPUT": projected, "OVERLAY": overlay, "OUTPUT": str(destination),
        })

    run_processing(job)


if __name__ == "__main__":
    run(**json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
