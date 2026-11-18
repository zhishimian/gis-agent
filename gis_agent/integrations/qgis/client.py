from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import subprocess
import tempfile
from threading import Event
from time import perf_counter
from typing import Any

from gis_agent.runtime.runner import terminate_process_tree

logger = logging.getLogger(__name__)


class _ProcessCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class QGISClient:
    launcher: Path
    timeout: int = 300
    cancel_event: Event | None = None

    def _call(
        self,
        *arguments: str,
        payload: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        effective_timeout = timeout or self.timeout
        flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
        if self.cancel_event is None:
            return subprocess.run(
                [str(self.launcher), "--json", *arguments],
                input=(json.dumps(payload, ensure_ascii=False) if payload is not None else None),
                capture_output=True,
                encoding="utf-8",
                timeout=effective_timeout,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            out_path, err_path = tmp_dir / "stdout.txt", tmp_dir / "stderr.txt"
            in_path = tmp_dir / "stdin.json"
            if payload is not None:
                in_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with (
                (in_path.open("rb") if payload is not None else open(os.devnull, "rb")) as stdin_f,
                out_path.open("wb") as stdout_f,
                err_path.open("wb") as stderr_f,
            ):
                proc = subprocess.Popen(
                    [str(self.launcher), "--json", *arguments],
                    stdin=stdin_f,
                    stdout=stdout_f,
                    stderr=stderr_f,
                    creationflags=flags,
                    start_new_session=(os.name != "nt"),
                )
                deadline = perf_counter() + effective_timeout
                while True:
                    if self.cancel_event.is_set():
                        terminate_process_tree(proc)
                        raise _ProcessCancelled()
                    remaining = deadline - perf_counter()
                    if remaining <= 0:
                        terminate_process_tree(proc)
                        raise subprocess.TimeoutExpired(proc.args, effective_timeout)
                    try:
                        returncode = proc.wait(timeout=min(0.2, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        continue
            stdout = out_path.read_text(encoding="utf-8", errors="replace")
            stderr = err_path.read_text(encoding="utf-8", errors="replace")
            return subprocess.CompletedProcess(proc.args, returncode, stdout, stderr)

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
        except _ProcessCancelled:
            return {
                "ok": False,
                "status": "cancelled",
                "cancelled": True,
                "algorithm_id": algorithm_id,
                "error": "QGIS 算法执行已被用户主动中止，子进程树已清理。",
            }
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
