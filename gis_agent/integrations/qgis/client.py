import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QGISClient:
    launcher:Path
    timeout:int=300

    def _call(self,*arguments:str,
              payload:dict[str,Any]| None=None,)-> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.launcher),"--json",*arguments],
            input=(
                json.dumps(payload,ensure_ascii=False)
                if payload is not None
                else None
            ),
            capture_output=True,
            encoding="utf-8",
            timeout=self.timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,)

    def query(self,*arguments:str)->dict[str,Any]:
        response=self._call(*arguments)

        if response.stderr:
            logger.info("%s", response.stderr.rstrip())

        if response.returncode!=0:
            logger.error("%s", response.stdout.rstrip())
        response.check_returncode()
        return json.loads(response.stdout)

    def execute(
        self,
        algorithm_id:str,
        /,
        project_path: str | None = None,
        **parameters:Any,
    )->dict[str,Any]:
        if project_path is not None and (not Path(project_path).is_absolute() or not Path(project_path).is_file()):
            return {"ok": False, "error": "project_path 必须是已有QGIS工程的绝对路径。"}
        response=self._call("run",algorithm_id,"-",payload={"inputs":parameters, **({"project_path": project_path} if project_path else {})},)

        if response.returncode!=0:
            return {
                "ok":False,
                "algorithm_id":algorithm_id,
                "returncode":response.returncode,
                "stdout":response.stdout,
                "stderr":response.stderr,
            }
        result=json.loads(response.stdout)

        return {
                "ok":True,
                "algorithm_id":algorithm_id,
                "outputs":result["results"],
                "log":result.get("log",{}),
                "stderr":response.stderr,
            }
