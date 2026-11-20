"""Authorized workspace sandbox, file tree, credential vault, and QGIS detection."""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from threading import RLock
from typing import Any

from gis_agent.adapters.credentials import Credentials
from gis_agent.config import AppConfig, QGISConfig
from gis_agent.core.model import DEEPSEEK_MAX_OUTPUT_TOKENS, ModelConfig
from gis_agent.runtime.probe import probe_current_python

ALLOWED_ATTACH_EXTS = {
    ".shp", ".gpkg", ".geojson", ".json", ".fgb", ".kml",
    ".tif", ".tiff", ".img", ".vrt", ".asc",
    ".csv", ".tsv", ".xlsx", ".parquet", ".nc",
    ".png", ".svg", ".jpg", ".jpeg", ".html", ".py",
}
SPATIAL_EXTS = {".shp", ".gpkg", ".geojson", ".fgb", ".kml", ".tif", ".tiff", ".img", ".vrt", ".asc", ".nc"}
VECTOR_EXTS = {".shp", ".gpkg", ".geojson", ".fgb", ".kml"}
RASTER_EXTS = {".tif", ".tiff", ".img", ".vrt", ".asc"}
FIGURE_EXTS = {".png", ".svg", ".jpg", ".jpeg"}


def _user_settings_path() -> Path:
    return Path.home() / ".opengis-studio" / "settings.json"


def _resolve_qgis_launchers(qgis_dir: Path) -> QGISConfig | None:
    qgis_dir = qgis_dir.expanduser().resolve()
    if not qgis_dir.is_dir():
        return None
    candidates = [
        (qgis_dir / "bin/qgis_process-qgis-ltr.bat", qgis_dir / "bin/python-qgis-ltr.bat"),
        (qgis_dir / "bin/qgis_process-qgis.bat", qgis_dir / "bin/python-qgis.bat"),
        (qgis_dir / "bin/qgis_process", qgis_dir / "bin/python3"),
        (qgis_dir / "Contents/MacOS/bin/qgis_process", qgis_dir / "Contents/MacOS/bin/python3"),
    ]
    for proc_bin, py_bin in candidates:
        if proc_bin.is_file() and py_bin.is_file():
            return QGISConfig(proc_bin, py_bin)
    return None


class WorkspaceService:
    """Manages active project folder, strict path authorization, credentials, and environment probes."""

    def __init__(self, project_dir: Path, *, settings_path: Path | None = None) -> None:
        self._lock = RLock()
        self.project_dir = project_dir.expanduser().resolve()
        self.settings_path = (settings_path or _user_settings_path()).expanduser().resolve()
        self.attached_files: set[Path] = set()
        self._runtime_api_keys: dict[str, str] = {}

    def _read_settings(self) -> dict[str, Any]:
        if not self.settings_path.is_file():
            return {}
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = self._read_settings()
            for key, value in updates.items():
                if value is None or value == "":
                    current.pop(key, None)
                else:
                    current[key] = value
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
            return current

    def load_config(self) -> AppConfig:
        with self._lock:
            cfg = AppConfig.from_env(self.project_dir)
            settings = self._read_settings()

            provider = settings.get("provider") or cfg.model.provider
            model_name = settings.get("model") or cfg.model.model
            base_url = settings.get("base_url") or cfg.model.base_url
            if (provider, model_name, base_url) != (cfg.model.provider, cfg.model.model, cfg.model.base_url):
                default_url = {
                    "deepseek": "https://api.deepseek.com",
                    "openai": "https://api.openai.com/v1",
                    "compatible": base_url,
                }.get(provider, base_url)
                max_tok = DEEPSEEK_MAX_OUTPUT_TOKENS if provider == "deepseek" else min(cfg.model.max_tokens, 16384)
                win = 1_048_576 if provider == "deepseek" else cfg.model.context_window
                tok = "deepseek-ai/DeepSeek-V4.1-Flash-1017" if provider == "deepseek" else "bytes"
                new_model = ModelConfig(
                    model=model_name,
                    base_url=settings.get("base_url") or default_url,
                    max_tokens=max_tok,
                    context_window=win,
                    tokenizer=tok,
                    provider=provider,
                    output_parameter="max_completion_tokens" if provider == "openai" else "max_tokens",
                    supports_images=(provider == "deepseek" and model_name == "deepseek-flash") or cfg.model.supports_images,
                    image_tokens=cfg.model.image_tokens or 1024,
                )
                api_env = {
                    "deepseek": "DEEPSEEK_API_KEY",
                    "openai": "OPENAI_API_KEY",
                    "compatible": "LLM_API_KEY",
                }.get(provider, cfg.api_key_env)
                cfg = replace(cfg, model=new_model, api_key_env=api_env)

            qgis_dir = settings.get("qgis_dir")
            if isinstance(qgis_dir, str) and qgis_dir.strip():
                qgis_cfg = _resolve_qgis_launchers(Path(qgis_dir))
                if qgis_cfg is not None:
                    cfg = replace(cfg, qgis=replace(qgis_cfg, font_files=cfg.fonts))
            return cfg

    def resolve_api_key(self, config: AppConfig | None = None) -> str:
        cfg = config or self.load_config()
        env_key = os.environ.get(cfg.api_key_env, "").strip()
        if env_key:
            return env_key
        creds = Credentials(cfg)
        with self._lock:
            runtime_key = self._runtime_api_keys.get(creds.service, "")
        if runtime_key:
            return runtime_key
        return creds.read().strip()

    def credentials_status(self) -> dict[str, Any]:
        cfg = self.load_config()
        creds = Credentials(cfg)
        env_val = os.environ.get(cfg.api_key_env, "").strip()
        keyring_val = creds.read().strip()
        with self._lock:
            runtime_val = self._runtime_api_keys.get(creds.service, "")
        configured = bool(env_val or keyring_val or runtime_val)
        source = "env" if env_val else ("keyring" if keyring_val else ("runtime" if runtime_val else "none"))
        return {
            "configured": configured,
            "source": source,
            "provider": cfg.model.provider,
            "model": cfg.model.model,
            "base_url": cfg.model.base_url,
            "api_key_env": cfg.api_key_env,
            "keyring_backend": creds.label if creds.backend is not None else None,
        }

    def save_credentials(
        self,
        *,
        api_key: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        if provider is not None:
            updates["provider"] = provider.strip()
        if model is not None:
            updates["model"] = model.strip()
        if base_url is not None:
            updates["base_url"] = base_url.strip()
        if updates:
            self._write_settings(updates)
        cfg = self.load_config()
        saved_to_keyring = False
        if api_key is not None and api_key.strip():
            clean_key = api_key.strip()
            creds = Credentials(cfg)
            saved_to_keyring = creds.save(clean_key)
            with self._lock:
                self._runtime_api_keys[creds.service] = clean_key
        status = self.credentials_status()
        status["saved_to_keyring"] = saved_to_keyring
        return status

    def select_project(self, raw_dir: str) -> dict[str, Any]:
        target = Path(raw_dir).expanduser().resolve()
        if not target.is_dir():
            raise FileNotFoundError(f"工作目录不存在：{target}")
        with self._lock:
            self.project_dir = target
        return {
            "project_dir": str(target),
            "files": self.list_files()["items"],
        }

    def attach_file(self, raw_path: str) -> dict[str, Any]:
        clean = raw_path.split("|layername=", 1)[0]
        target = Path(clean).expanduser().resolve()
        if not target.exists():
            raise FileNotFoundError(f"文件不存在：{target}")
        ext = target.suffix.lower()
        if target.is_file() and ext not in ALLOWED_ATTACH_EXTS:
            raise ValueError(f"不支持附加预览的文件类型：{ext or '无后缀'}")
        with self._lock:
            self.attached_files.add(target)
        return {
            "path": str(target),
            "name": target.name,
            "kind": self._classify_path(target),
            "bytes": target.stat().st_size if target.is_file() else 0,
        }

    def authorize_path(self, raw_path: str, *, allow_attached: bool = True) -> Path:
        clean = raw_path.split("|layername=", 1)[0]
        target = Path(clean).expanduser().resolve()
        with self._lock:
            cfg = self.load_config()
            roots = (self.project_dir.resolve(), cfg.output_root.resolve(), cfg.session_root.resolve())
            if any(target.is_relative_to(root) for root in roots):
                return target
            if allow_attached and target in self.attached_files:
                return target
        raise PermissionError(f"路径超出当前授权工作区边界：{target}")

    @staticmethod
    def _classify_path(path: Path) -> str:
        ext = path.suffix.lower()
        if ext in VECTOR_EXTS:
            return "vector"
        if ext in RASTER_EXTS:
            return "raster"
        if ext in FIGURE_EXTS:
            return "figure"
        if ext in {".csv", ".tsv", ".xlsx", ".parquet"}:
            return "table"
        if ext in {".html", ".htm"}:
            return "html_map"
        if ext == ".py":
            return "script"
        return "other"

    def list_files(self, sub_dir: str | None = None, *, session_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            base = self.project_dir
            cfg = self.load_config()
            attached = sorted(self.attached_files)

        target_dir = base if not sub_dir else self.authorize_path(str((base / sub_dir) if not Path(sub_dir).is_absolute() else Path(sub_dir)))
        if not target_dir.is_dir():
            raise FileNotFoundError(f"目录不存在：{target_dir}")

        skip = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules", "sessions"}
        items: list[dict[str, Any]] = []
        for entry in sorted(target_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if entry.name.startswith(".") and entry.name not in {".env.example"}:
                continue
            if entry.name in skip:
                continue
            if entry.is_dir():
                items.append({
                    "name": entry.name,
                    "path": str(entry.resolve()),
                    "rel_path": os.path.relpath(entry, base).replace("\\", "/"),
                    "is_dir": True,
                    "kind": "directory",
                    "bytes": 0,
                })
            elif entry.is_file():
                ext = entry.suffix.lower()
                # Collapse shapefile sidecars in top listing while keeping .shp
                if ext in {".dbf", ".shx", ".prj", ".cpg", ".sbn", ".sbx", ".qpj"} and entry.with_suffix(".shp").exists():
                    continue
                items.append({
                    "name": entry.name,
                    "path": str(entry.resolve()),
                    "rel_path": os.path.relpath(entry, base).replace("\\", "/"),
                    "is_dir": False,
                    "kind": self._classify_path(entry),
                    "bytes": entry.stat().st_size,
                    "is_spatial": ext in SPATIAL_EXTS,
                })

        attached_items = [
            {
                "name": p.name,
                "path": str(p),
                "rel_path": p.name,
                "is_dir": False,
                "kind": self._classify_path(p),
                "bytes": p.stat().st_size if p.is_file() else 0,
                "attached": True,
            }
            for p in attached
            if p.exists()
        ]
        output_dir = cfg.output_root / session_id if session_id else cfg.output_root
        return {
            "project_dir": str(base),
            "current_dir": str(target_dir),
            "output_dir": str(output_dir),
            "items": items[:400],
            "attached": attached_items,
        }

    def detect_qgis_dirs(self) -> list[str]:
        candidates: list[Path] = []
        if env_dir := os.environ.get("GIS_AGENT_QGIS_DIR", "").strip():
            candidates.append(Path(env_dir))
        if os.name == "nt":
            for root in (Path("C:/Program Files"), Path("D:/"), Path("E:/exe"), Path("C:/OSGeo4W64"), Path("C:/OSGeo4W")):
                if not root.exists():
                    continue
                if _resolve_qgis_launchers(root):
                    candidates.append(root)
                for sub in root.glob("QGIS*"):
                    candidates.append(sub)
        else:
            for root in (Path("/usr"), Path("/Applications")):
                if root.exists():
                    candidates.append(root)
        if proc := shutil.which("qgis_process"):
            candidates.append(Path(proc).resolve().parents[1])

        found: list[str] = []
        seen: set[str] = set()
        for cand in candidates:
            if _resolve_qgis_launchers(cand) is not None:
                norm = str(cand.resolve())
                if norm not in seen:
                    seen.add(norm)
                    found.append(norm)
        return found

    def configure_qgis(self, qgis_dir: str | None) -> dict[str, Any]:
        clean = (qgis_dir or "").strip()
        if not clean:
            self._write_settings({"qgis_dir": None})
            return {"ok": True, "has_qgis": self.load_config().qgis is not None, "qgis_dir": None}
        target = Path(clean).expanduser().resolve()
        if _resolve_qgis_launchers(target) is None:
            raise ValueError(f"未在目录下找到有效的 qgis_process 与 python-qgis 启动器：{target}")
        self._write_settings({"qgis_dir": str(target)})
        return {"ok": True, "has_qgis": True, "qgis_dir": str(target)}

    def get_env_info(self) -> dict[str, Any]:
        cfg = self.load_config()
        py_info = probe_current_python()
        creds = self.credentials_status()
        qgis_path = str(cfg.qgis.process_launcher.parent.parent) if cfg.qgis is not None else None
        return {
            "project_dir": str(self.project_dir),
            "python": py_info,
            "has_qgis": cfg.qgis is not None,
            "qgis_dir": qgis_path,
            "detected_qgis_dirs": self.detect_qgis_dirs(),
            "credentials": creds,
        }

    def reveal_or_open(self, raw_path: str, action: str = "reveal") -> dict[str, Any]:
        target = self.authorize_path(raw_path)
        if not target.exists():
            raise FileNotFoundError(f"文件或目录不存在：{target}")
        if action not in {"reveal", "open"}:
            raise ValueError("action 仅支持 reveal 或 open。")

        if sys.platform == "win32":
            if action == "reveal":
                subprocess.Popen(["explorer", f"/select,{target}"])
            else:
                os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(target)] if action == "reveal" else ["open", str(target)])
        else:
            open_target = target.parent if (action == "reveal" and target.is_file()) else target
            subprocess.Popen(["xdg-open", str(open_target)])
        return {"ok": True, "path": str(target), "action": action}
