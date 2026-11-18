import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QGISClient:
    launcher: Path
    timeout: int = 300

    def _call(
        self,
        *arguments: str,
        payload: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        return subprocess.run(
            [str(self.launcher), "--json", *arguments],
            input=(json.dumps(payload, ensure_ascii=False) if payload is not None else None),
            capture_output=True,
            encoding="utf-8",
            timeout=timeout or self.timeout,
            creationflags=flags,
        )

    def query(self, *arguments: str) -> dict[str, Any]:
        response = self._call(*arguments)
        if response.stderr:
            logger.info("%s", response.stderr.rstrip())
        if response.returncode != 0:
            logger.error("%s", response.stdout.rstrip())
        response.check_returncode()
        return json.loads(response.stdout)

    def execute(
        self,
        algorithm_id: str,
        /,
        project_path: str | None = None,
        timeout_sec: int | None = None,
        **parameters: Any,
    ) -> dict[str, Any]:
        if project_path is not None and (not Path(project_path).is_absolute() or not Path(project_path).is_file()):
            return {"ok": False, "status": "failed", "error": "project_path 必须是已有QGIS工程的绝对路径。"}
        try:
            response = self._call(
                "run",
                algorithm_id,
                "-",
                payload={"inputs": parameters, **({"project_path": project_path} if project_path else {})},
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "status": "timed_out",
                "timed_out": True,
                "algorithm_id": algorithm_id,
                "error": f"QGIS 算法执行超过 {timeout_sec or self.timeout} 秒超时限制。",
            }

        if response.returncode != 0:
            return {
                "ok": False,
                "status": "failed",
                "algorithm_id": algorithm_id,
                "returncode": response.returncode,
                "stdout": response.stdout,
                "stderr": response.stderr,
            }
        result = json.loads(response.stdout)
        return {
            "ok": True,
            "status": "succeeded",
            "algorithm_id": algorithm_id,
            "outputs": result["results"],
            "log": result.get("log", {}),
            "stderr": response.stderr,
        }
