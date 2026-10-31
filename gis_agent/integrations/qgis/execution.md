# Shared QGIS script execution

In GIS-Agent, run_python_script uses the configured GIS interpreter, a script-local working directory and the checkout on sys.path. arguments safely reach sys.argv through JSON, including spaces and layer URIs. Other hosts should configure the same interpreter, expose this checkout on PYTHONPATH, and set GIS_AGENT_RESULT_PATH to a writable JSON file.
Use actual layer names and original parameter names/case from the current algorithm help/schema. A standard standalone operation can use a direct QGIS tool; batches and custom data flow can use scripts.

```python
import sys
from gis_agent.integrations.qgis.python_runtime import run_processing


def job():
    import processing
    return processing.run("native:buffer", {
        "INPUT": sys.argv[1], "DISTANCE": float(sys.argv[3]),
        "SEGMENTS": int(sys.argv[4]), "END_CAP_STYLE": 0, "JOIN_STYLE": 0,
        "MITER_LIMIT": 2, "DISSOLVE": False, "OUTPUT": sys.argv[2],
    })


run_processing(job)
```

Arguments are the actual source URI, absolute output path, distance in the appropriate layer units and segments per quarter-circle. This example illustrates an interface, not a universal buffer/CRS policy.
run_processing initializes Processing, invokes the job, clears the project/application and writes ordinary JSON. Keep layers, iterators and writers in the job's local scope; return only ordinary JSON and paths. Processing.initialize prepares native algorithms; do not register a duplicate native provider. The helper rethrows errors with traceback/nonzero status. It cannot remove arbitrary global references or guarantee every plugin/driver lifecycle.
Cross-process results need files; memory layers only live in their process. A distance-unit setting cannot replace a suitable coordinate transform. Never use os._exit to certify normal cleanup.
Pure GeoPandas/Shapely/Matplotlib scripts do not need QgsApplication. Print logs normally; structured results go to GIS_AGENT_RESULT_PATH. Files from a failed execution remain diagnostic until the affected work succeeds.

Direct tool results have outputs, for example `{"ok":true,"outputs":{"OUTPUT":"/work/result.gpkg"}}`. The script helper returns Processing's dictionary; run_python_script wraps it in result, for example `{"ok":true,"returncode":0,"result":{"OUTPUT":"/work/result.gpkg"}}`. Reuse these paths and inspect real layers rather than guessing names.
Use host metadata/field tools for basic checks. For errors follow the exact traceback and [execution gotchas](../../skills/gis-spatial-analysis/references/gotchas.md).
