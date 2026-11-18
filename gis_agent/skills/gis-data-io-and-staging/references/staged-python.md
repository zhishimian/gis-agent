# Staged Python and local repair

Keep cheap, coupled work in one script. Split at a stable costly prefix followed
by changing analysis or export when saved compute exceeds write/read/check costs.
No line-count rule, stage-registration tools or whole-task DAG are required.

Staged Python scripts can use a simple JSON job shape:
```json
{"inputs":{"prepared":"/work/intermediate.npy"},"parameters":{"mode":"summarize"},"outputs":{"statistics":"/work/statistics_v2.json"}}
```
Run [staged_compute.py](../scripts/staged_compute.py) with the JSON path. First
prepare with empty inputs, parameters mode=prepare/size=1000/rounds=3 and
outputs.prepared set to a new NPY path. Then summarize the saved file with the
job above. The example returns outputs/metrics/warnings/assumptions via
GIS_AGENT_RESULT_PATH. It never silently resumes from file existence alone.

After failure retain traceback and partial files. A small known bug can use
edit_file on the downstream script while reusing persisted upstream files whose
inputs and assumptions remain unchanged. When source or version is unclear, use
execution_history with a recent execution ID or script name, then inspect
detail/script/stderr as needed.

Persist intermediate stages in self-contained local formats such as closed GPKG,
GeoTIFF, NPY, CSV or JSON, and write revised downstream outputs to explicit new
paths rather than silently overwriting unverified files.
