"""Ring 3 local spatial engine & human-in-the-loop server package."""
from __future__ import annotations

import os
from pathlib import Path
import sys


def sanitize_spatial_env() -> None:
    """Strip conflicting host PROJ/GDAL variables unless they point inside current Python prefix."""
    prefix = Path(sys.prefix).resolve()
    for var in ("PROJ_LIB", "PROJ_DATA", "GDAL_DATA"):
        raw = os.environ.get(var)
        if not raw:
            continue
        try:
            if Path(raw).expanduser().resolve().is_relative_to(prefix):
                continue
        except OSError:
            pass
        os.environ.pop(var, None)


sanitize_spatial_env()

from gis_agent.server.app import create_app, main, run_server

__all__ = ["create_app", "main", "run_server", "sanitize_spatial_env"]
