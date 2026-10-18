import json
import os
import subprocess
from functools import partial
from pathlib import Path
from typing import Any
from uuid import uuid4

from tools.base import Tool


def run_python_script(
    launcher: Path,
    log_dir: Path,
    script_path: str,
    arguments: list[str] | None = None,
) -> dict[str, Any]:
    script = Path(script_path).expanduser().resolve()
    if not script.is_file() or script.suffix.lower() != ".py":
        return {"ok": False, "error": f"Python 脚本不存在或扩展名不是 .py：{script}"}

    log_dir = (log_dir / uuid4().hex).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "stdout.txt"
    stderr_path = log_dir / "stderr.txt"
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        result = subprocess.run(
            [str(launcher), "-B", str(script), *(arguments or [])],
            cwd=script.parent,
            env=os.environ | {
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "QT_QPA_PLATFORM": "offscreen",
            },
            stdout=stdout,
            stderr=stderr,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": stdout_path.read_text(encoding="utf-8", errors="replace")[-4000:],
        "stderr": stderr_path.read_text(encoding="utf-8", errors="replace")[-4000:],
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }


def inspect_data(launcher: Path, log_dir: Path, source: str) -> dict[str, Any]:
    script = Path(__file__).resolve().parents[1] / "qgis_backend" / "inspect_data.py"
    result = run_python_script(launcher, log_dir, str(script), [source])
    if result["ok"]:
        result["data"] = json.loads(Path(result["stdout_path"]).read_text(encoding="utf-8"))
        del result["stdout"]
    return result


def make_qgis_python_tools(launcher: Path, log_dir: Path) -> list[Tool]:
    return [
        Tool(
            name="inspect_data",
            description=(
                "读取 GIS 数据元信息。矢量返回字段、三条属性样例、数量、几何类型、"
                "CRS 和范围；栅格返回尺寸、像元大小、波段、NoData、CRS 和范围。"
                "多图层容器先返回 layers，再用选定图层的 source 调用本工具。"
                "不进行完整几何校验或全量数值统计。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "绝对数据路径或上一轮返回的图层 source。"}
                },
                "required": ["source"],
                "additionalProperties": False,
            },
            function=partial(inspect_data, launcher, log_dir),
        ),
        Tool(
            name="run_python_script",
            description=(
                "执行已保存的 .py 脚本，使用独立 QGIS Python 进程。"
                "需要 PyQGIS 或 Processing 时，由脚本显式初始化。"
                "工作目录为脚本所在目录，不共享上次执行的变量。"
                "等待脚本退出，返回退出码、日志尾部和完整日志路径。"
                "先用 write_file 保存脚本；修改脚本后可以重新执行。"
            ),
            parameters={
                "type": "object",
                "properties": {"script_path": {"type": "string"}},
                "required": ["script_path"],
                "additionalProperties": False,
            },
            function=partial(run_python_script, launcher, log_dir),
        ),
    ]