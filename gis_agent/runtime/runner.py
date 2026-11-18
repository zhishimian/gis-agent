import os
import signal
import subprocess
from pathlib import Path
from threading import Event
from time import perf_counter
from typing import Any


SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", "python_logs", ".venv"}


def snapshot_files(roots: tuple[Path, ...], max_entries: int = 5000) -> dict[str, tuple[int, int]]:
    entries: dict[str, tuple[int, int]] = {}
    for root in roots:
        resolved = root.expanduser().resolve()
        if not resolved.exists():
            continue
        if resolved.is_file():
            stat = resolved.stat()
            entries[str(resolved)] = (stat.st_mtime_ns, stat.st_size)
            continue
        for current, dirs, files in os.walk(resolved):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.endswith(".assets")]
            for name in files:
                if len(entries) >= max_entries:
                    return entries
                target = Path(current) / name
                try:
                    stat = target.stat()
                except OSError:
                    continue
                entries[str(target)] = (stat.st_mtime_ns, stat.st_size)
    return entries


def extract_explicit_paths(structured_result: Any) -> list[str]:
    if not isinstance(structured_result, dict):
        return []
    found: list[str] = []
    for key in ("artifacts", "outputs", "files"):
        value = structured_result.get(key)
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, list):
            found.extend(item for item in value if isinstance(item, str))
        elif isinstance(value, dict):
            found.extend(item for item in value.values() if isinstance(item, str))
    return list(dict.fromkeys(found))


def collect_outputs(
    before: dict[str, tuple[int, int]],
    after: dict[str, tuple[int, int]],
    explicit_paths: list[str] | tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    outputs: list[dict[str, Any]] = []

    def record(raw_path: str, source: str) -> None:
        try:
            target = Path(raw_path).expanduser().resolve()
        except OSError:
            return
        key = str(target)
        if key in seen:
            return
        seen.add(key)
        if not target.exists():
            outputs.append({"path": key, "exists": False, "bytes": 0, "empty": True, "source": source})
            return
        if target.is_dir():
            has_files = any(item.is_file() and item.stat().st_size > 0 for item in target.rglob("*"))
            outputs.append({"path": key, "exists": True, "kind": "directory", "empty": not has_files, "source": source})
            return
        size = target.stat().st_size
        outputs.append({"path": key, "exists": True, "bytes": size, "empty": size == 0, "source": source})

    for item in explicit_paths:
        record(item, "declared")
    for path_str, state in sorted(after.items()):
        if before.get(path_str) != state:
            record(path_str, "scanned")
    return outputs


def terminate_process_tree(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except OSError:
            process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def run_process(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
    timeout_sec: int = 180,
    watch_roots: tuple[Path, ...] = (),
    protected_paths: tuple[Path, ...] = (),
    cancel_event: Event | None = None,
) -> dict[str, Any]:
    if not 1 <= timeout_sec <= 3600:
        raise ValueError("timeout_sec 必须在 1 到 3600 秒之间。")
    before_outputs = snapshot_files(watch_roots) if watch_roots else {}
    before_protected = snapshot_files(protected_paths) if protected_paths else {}
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
    started = perf_counter()
    deadline = started + timeout_sec
    timed_out = False
    cancelled = False

    with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=stdout_file,
            stderr=stderr_file,
            creationflags=flags,
            start_new_session=(os.name != "nt"),
        )
        returncode = -1
        while True:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                terminate_process_tree(process)
                returncode = -2
                break
            remaining = deadline - perf_counter()
            if remaining <= 0:
                timed_out = True
                terminate_process_tree(process)
                returncode = -1
                break
            try:
                returncode = process.wait(timeout=min(0.2, remaining))
                break
            except subprocess.TimeoutExpired:
                continue

    elapsed_ms = round((perf_counter() - started) * 1000, 2)
    after_outputs = snapshot_files(watch_roots) if watch_roots else {}
    tampered: list[str] = []
    if protected_paths:
        after_protected = snapshot_files(protected_paths)
        tampered = sorted(
            path for path, state in before_protected.items()
            if after_protected.get(path) != state
        )

    if cancelled:
        status = "cancelled"
    elif timed_out:
        status = "timed_out"
    elif returncode == 0 and not tampered:
        status = "succeeded"
    else:
        status = "failed"
    return {
        "status": status,
        "returncode": returncode,
        "timed_out": timed_out,
        "cancelled": cancelled,
        "elapsed_ms": elapsed_ms,
        "before_outputs": before_outputs,
        "after_outputs": after_outputs,
        "tampered_inputs": tampered,
    }
