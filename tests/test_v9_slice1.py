import json
from pathlib import Path
import sys

import pytest

from gis_agent.integrations.qgis.catalog import load_catalog, make_search_tool
from gis_agent.integrations.qgis.client import QGISClient
from gis_agent.persistence.json import truncate_log, write_json
from gis_agent.tools.files import make_file_tools
from gis_agent.tools.planning import finish_task
from gis_agent.tools.qgis_alg import make_run_qgis_tool
from gis_agent.tools.qgis_python import run_python_script


def test_write_json_retries_transient_permission_error(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "session.json"
    attempts = []
    original_replace = Path.replace

    def flaky_replace(self: Path, dst: Path) -> Path:
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError("模拟 Windows 瞬时句柄占用")
        return original_replace(self, dst)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    write_json(target, {"ok": True, "turn": 3})
    assert len(attempts) == 3
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True, "turn": 3}


def test_truncate_log_preserves_head_and_tail_traceback() -> None:
    lines = ["Header: starting job\n"] + [f"progress {i}\n" for i in range(200)] + ["ValueError: invalid CRS\n"]
    text = "".join(lines)
    shortened = truncate_log(text, limit=1200, head_lines=5, tail_lines=5)
    assert len(shortened) <= 1200
    assert "Header: starting job" in shortened
    assert "ValueError: invalid CRS" in shortened
    assert "省略" in shortened


def test_script_timeout_kills_process_tree_and_keeps_partial_logs(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    script = tmp_path / "hang.py"
    script.write_text(
        f"import subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
        f"print('spawned grandchild', flush=True)\n"
        f"time.sleep(120)\n",
        encoding="utf-8",
    )
    result = run_python_script(Path(sys.executable), tmp_path / "logs", str(script), timeout_sec=5)
    assert not result["ok"]
    assert result["timed_out"] and result["status"] == "timed_out"
    assert "spawned grandchild" in result["stdout"]
    if pid_file.is_file():
        grandchild_pid = int(pid_file.read_text().strip())
        # 验证孙进程也已被进程树清理终止
        check = run_python_script(
            Path(sys.executable),
            tmp_path / "logs",
            str(
                _write_script(
                    tmp_path / "check_pid.py",
                    f"import os, json\n"
                    f"alive = False\n"
                    f"try:\n"
                    f"    os.kill({grandchild_pid}, 0)\n"
                    f"    alive = True\n"
                    f"except OSError:\n"
                    f"    alive = False\n"
                    f"open(os.environ['GIS_AGENT_RESULT_PATH'], 'w').write(json.dumps({{'alive': alive}}))\n",
                )
            ),
        )
        assert check["ok"] and not check["result"]["alive"]


def _write_script(path: Path, code: str) -> Path:
    path.write_text(code, encoding="utf-8")
    return path


def test_recursive_output_discovery_and_protected_input_detection(tmp_path: Path) -> None:
    raw_input = tmp_path / "input" / "roads.geojson"
    raw_input.parent.mkdir()
    raw_input.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    out_root = tmp_path / "outputs"
    script = tmp_path / "nested_out.py"
    script.write_text(
        f"from pathlib import Path\n"
        f"target = Path({str(out_root / 'stage1' / 'sub' / 'clean.geojson')!r})\n"
        f"target.parent.mkdir(parents=True, exist_ok=True)\n"
        f"target.write_text('ok', encoding='utf-8')\n",
        encoding="utf-8",
    )
    good = run_python_script(
        Path(sys.executable),
        tmp_path / "logs",
        str(script),
        watch_roots=(out_root,),
        protected_paths=(raw_input.parent,),
    )
    assert good["ok"] and good["status"] == "succeeded"
    assert any(item["path"].endswith("clean.geojson") and item["bytes"] == 2 and not item["empty"] for item in good["outputs"])

    tamper = tmp_path / "tamper.py"
    tamper.write_text(f"open({str(raw_input)!r}, 'w').write('corrupted')\n", encoding="utf-8")
    bad = run_python_script(
        Path(sys.executable),
        tmp_path / "logs",
        str(tamper),
        protected_paths=(raw_input.parent,),
    )
    assert not bad["ok"] and "受保护输入" in bad["error"]


def test_file_tools_write_boundaries_and_finish_nonempty_check(tmp_path: Path) -> None:
    protected = tmp_path / "dataset"
    protected.mkdir()
    raw = protected / "source.csv"
    raw.write_text("a,b\n1,2\n", encoding="utf-8")
    workspace = tmp_path / "work"
    tools = {t.name: t for t in make_file_tools(allowed_roots=(workspace,), protected_paths=(protected,))}

    assert not tools["write_file"].run({"path": str(protected / "hack.txt"), "content": "x"})["ok"]
    assert not tools["edit_file"].run({"path": str(raw), "old_text": "1,2", "new_text": "9,9"})["ok"]
    assert not tools["write_file"].run({"path": str(tmp_path / "outside.txt"), "content": "x"})["ok"]
    ok_write = tools["write_file"].run({"path": str(workspace / "script.py"), "content": "print(1)"})
    assert ok_write["ok"]

    empty_artifact = workspace / "empty.gpkg"
    empty_artifact.write_bytes(b"")
    rejected = finish_task("completed", "交付空文件", artifacts=[str(empty_artifact)])
    assert not rejected["ok"] and "0字节" in rejected["error"]
    assert finish_task("completed", "交付正常脚本", artifacts=[str(workspace / "script.py")], output_dir=workspace)["ok"]


def test_static_qgis_search_and_run_validation(qgis_dir: Path, tmp_path: Path) -> None:
    client = QGISClient(qgis_dir / "bin/qgis_process-qgis-ltr.bat")
    catalog = load_catalog(client)
    cache: dict = {}
    protected = tmp_path / "protected"
    protected.mkdir()
    source = protected / "pt.geojson"
    source.write_text(
        json.dumps({
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
            "features": [{"type": "Feature", "properties": {"id": 1}, "geometry": {"type": "Point", "coordinates": [0, 0]}}],
        }),
        encoding="utf-8",
    )
    search_tool = make_search_tool(catalog, client, cache)
    run_tool = make_run_qgis_tool(client, catalog, cache, protected_paths=(protected,))

    found = search_tool.run({"query": "native:buffer", "limit": 1})
    assert len(found) == 1 and "DISTANCE" in found[0]["parameters"]
    assert "native:buffer" in cache

    # 大小写错误参数被拦截
    bad_key = run_tool.run({"algorithm_id": "native:buffer", "parameters": {"input": str(source), "OUTPUT": str(tmp_path / "a.gpkg")}})
    assert not bad_key["ok"] and "INPUT" in bad_key["allowed_parameters"]

    # 禁止写入受保护目录
    bad_dest = run_tool.run({"algorithm_id": "native:buffer", "parameters": {"INPUT": str(source), "DISTANCE": 100, "OUTPUT": str(protected / "out.gpkg")}})
    assert not bad_dest["ok"] and "受保护" in bad_dest["error"]

    # 正常执行与禁止覆盖已有输出
    out = tmp_path / "out" / "buffered.gpkg"
    good = run_tool.run({"algorithm_id": "native:buffer", "parameters": {"INPUT": str(source), "DISTANCE": 100, "OUTPUT": str(out)}})
    assert good["ok"] and out.is_file() and out.stat().st_size > 0
    overwrite = run_tool.run({"algorithm_id": "native:buffer", "parameters": {"INPUT": str(source), "DISTANCE": 100, "OUTPUT": str(out)}})
    assert not overwrite["ok"]
