# Staged Python and local repair

Keep cheap, coupled work in one script. Split at a stable costly prefix followed
by changing analysis/export, when saved compute exceeds write/read/check costs.
No line-count rule, stage-registration tools or whole-task DAG are required.

Ordinary and controlled Python can share this JSON job shape:
```json
{"inputs":{"prepared":"/work/intermediate.npy"},"parameters":{"mode":"summarize"},"outputs":{"statistics":"/work/statistics_v2.json"}}
```
Run [staged_compute.py](../scripts/staged_compute.py) with the JSON path. First
prepare with empty inputs, parameters mode=prepare/size=1000/rounds=3 and
outputs.prepared set to a new NPY path. Then summarize the saved file with the
job above. The example returns outputs/metrics/warnings/assumptions via
GIS_AGENT_RESULT_PATH. It never silently resumes from file existence.

After failure retain traceback and partial files. A small known bug can use
edit_file. When source/version is unclear, use execution_history with a recent
execution ID or script name, then detail/script/stderr as needed. Recorded code
is distinct from today's working file; ordinary original-path snapshots still
have the documented identity limit.

For costly repeated repairs with explicit local dependencies, promote the
affected scope using the [existing local_replay contract](../../../integrations/qgis/replay.md).
Read that reference before constructing a plan. Use real source_execution,
accepted inputs, a candidate SHA or unique snapshot patch, and declared helpers.
Read inputs/parameters/outputs from sys.argv[1]. outputs_only applies to all
writes except GIS_AGENT_RESULT_PATH. The program freezes code and preserves
versions. Unknown hidden reads, active databases and lost Python memory cannot
be recovered. Ordinary saved results have unverified historical identity;
adopting a current file does not prove it matches its old execution.

Closed GPKG, self-contained TIFF/NPY/CSV/JSON fit the controlled boundary; final
GDB export stays ordinary. Family cache still requires input/code/environment/
completion checks. No new plan shorthand or global cache is introduced.
