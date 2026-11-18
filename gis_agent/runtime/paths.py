from pathlib import Path
import sys


def package_dir() -> Path:
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        candidate = (Path(frozen) / "gis_agent").resolve()
        if candidate.is_dir():
            return candidate
    return Path(__file__).resolve().parents[1]


def import_root() -> Path:
    return package_dir().parent


def package_resource(*parts: str) -> Path:
    return package_dir().joinpath(*parts)


def default_project_dir() -> Path:
    root = import_root()
    if any(part in {"site-packages", "dist-packages", "plugins"} for part in root.parts):
        return Path.cwd().resolve()
    return root
