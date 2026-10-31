import json
import os
import runpy
import sys
from pathlib import Path


def main() -> None:
    request = json.loads(Path(os.environ["GIS_AGENT_SCRIPT_REQUEST"]).read_text(encoding="utf-8"))
    script = Path(request["script"])
    sys.argv = [str(script), *request["arguments"]]
    sys.path[:0] = [str(script.parent), os.environ["GIS_AGENT_PROJECT_ROOT"]]
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
