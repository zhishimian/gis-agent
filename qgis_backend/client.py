import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class QGISClient:
    launcher:Path=Path("E:/exe/qgis/bin/qgis_process-qgis-ltr.bat")
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
            print(response.stderr,end="")

        if response.returncode!=0:
            print(response.stdout,end="")
        response.check_returncode()
        return json.loads(response.stdout)

    def execute(
        self,
        algorithm_id:str,
        /,
        **parameters:Any,
    )->dict[str,Any]:
        response=self._call("run",algorithm_id,"-",payload={"inputs":parameters},)

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
