"""Isolated GeoBenchX blind holdout runner sharing the Plan A SQLite budget ledger.

Reads ONLY geobenchx-questions-only.json and geobenchx-data-map.json (49-item catalog).
Never reads organizer labels or reference solutions.
"""
import argparse
import concurrent.futures
from dataclasses import asdict, replace
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.geoagentbench.common import (
    HOST,
    MATERIALS,
    PROJECT,
    Ledger,
    Protection,
    costs,
    credentials,
    frozen_sources,
    load,
    now,
    retryable_transport,
    save,
)
from benchmarks.geoagentbench.evaluate import trace

DATA_ROOT = (MATERIALS / "extracted/GeoBenchX_package/Data").resolve()
DEFAULT_IDS = (
    "TASK_250309_135125_854050",
    "TASK_250309_135125_883928",
    "TASK_250309_135125_138450",
)


def prepare_geobenchx(run_dir: Path, task_id: str) -> Path:
    questions = load(MATERIALS / "geobenchx-questions-only.json")
    task_obj = next(item for item in questions if item["id"] == task_id)
    raw_catalog = load(MATERIALS / "geobenchx-data-map.json")

    work = (run_dir / "geobenchx" / task_id / "attempt_01").resolve()
    for sub in ("output", "temp", "scripts", "records"):
        (work / sub).mkdir(parents=True, exist_ok=True)

    catalog_entries = []
    catalog_lines = []
    for name, meta in raw_catalog.items():
        entry = {"name": name, "kind": meta["kind"], "path": meta["path"]}
        catalog_entries.append(entry)
        catalog_lines.append(f"- [{meta['kind']}] {name}: {meta['path']}")

    catalog_path = work / "catalog.json"
    save(catalog_path, catalog_entries)

    prompt = (
        "Complete the following GIS task using ONLY the supplied local GeoBenchX data catalog and installed tools/libraries.\n\n"
        f"Task:\n{task_obj['task'].strip()}\n\n"
        f"Runtime paths:\n"
        f"- Working directory: {work}\n"
        f"- Output directory (save maps, CSV/JSON summaries, and scripts here): {work / 'output'}\n"
        f"- Full machine-readable catalog JSON: {catalog_path}\n\n"
        "Available Data Catalog (49 datasets, read-only):\n"
        + "\n".join(catalog_lines)
        + "\n\nExecution rules:\n"
        "1. Use absolute paths when calling tools. Never modify files inside the read-only Data directory.\n"
        "2. Statistical ZIP archives in StatData contain World Bank CSVs and can be read directly in Python (zipfile/pandas).\n"
        "3. No external network access or follow-up human input is available in this automated benchmark run.\n"
        "4. If the required spatial or statistical data for the requested region/topic is genuinely absent from the 49-item catalog above, "
        "do NOT fabricate data or substitute unrelated regions; finish with status='blocked' and state clearly which catalog datasets were checked and what is missing.\n"
        "5. Keep scripts and intermediate/final outputs in the output directory and state material assumptions (e.g., CRS, units, thresholds)."
    )
    (work / "prompt.txt").write_text(prompt, encoding="utf-8")
    return work


def run_worker_inprocess(work: Path, run_dir: Path) -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    from openai import DefaultHttpxClient, OpenAI
    from gis_agent.application import AgentFactory
    from gis_agent.config import AppConfig
    from gis_agent.integrations.llm import chat, make_token_counter, request_view
    from gis_agent.integrations.qgis.catalog import load_catalog
    from gis_agent.integrations.qgis.client import QGISClient
    from gis_agent.persistence.checkpoints import SqliteCheckpointer
    from gis_agent.persistence.sessions import SessionStore
    from gis_agent.prompts import render_prompt
    from gis_agent.skills import skill_index

    spec = load(run_dir / "config.json")
    if frozen_sources() != spec["source_hashes"]:
        raise Protection("Frozen product source changed")

    record = work / "records"
    record.mkdir(parents=True, exist_ok=True)

    def event(kind: str, **values):
        with (record / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time": now(), "kind": kind, **values}, ensure_ascii=False, default=str) + "\n")

    logging.basicConfig(filename=record / "runtime.log", encoding="utf-8", level=logging.INFO)
    key, url, model_name = credentials(spec["credential_reference"])
    config = AppConfig.from_env(PROJECT)
    model = replace(
        config.model,
        base_url=url,
        model=model_name,
        max_tokens=spec["max_output_tokens"],
        provider="deepseek",
        context_window=1048576,
        supports_images=True,
    )
    wrapper = record / "python-isolated.bat"
    child_entry = Path(__file__).resolve().parent / "geoagentbench" / "child_entry.py"
    wrapper.write_text(
        '@echo off\r\ncall "' + str(config.qgis.python_launcher) + '" -B "' + str(child_entry) + '" %*\r\n',
        encoding="utf-8",
    )
    config = replace(
        config,
        model=model,
        session_root=record / "sessions",
        output_root=work,
        memory=None,
        max_retries=0,
        qgis=replace(config.qgis, python_launcher=wrapper),
        context=replace(config.context, request_token_limit=350000),
    )
    for name in ("TEMP", "TMP"):
        os.environ[name] = str(work / "temp")
    os.environ.update(
        GAB_WORK=str(work),
        GAB_PROJECT=str(PROJECT),
        GAB_EXTRA=str(run_dir / "environment/baseline-empty"),
        GAB_READ_EXTRA=str(DATA_ROOT),
        MPLCONFIGDIR=str(work / "temp/matplotlib"),
        PROJ_NETWORK="OFF",
    )
    for name in list(os.environ):
        if any(token in name.upper() for token in ("API_KEY", "ACCESS_KEY", "SECRET")):
            os.environ.pop(name, None)

    ledger = Ledger(run_dir / "ledger.sqlite", spec["budget_cny"])
    task_key = work.relative_to(run_dir).as_posix()
    rows = load(record / "usage.json") if (record / "usage.json").exists() else []
    started = time.perf_counter()
    max_calls = 50
    task_seconds = 900
    task_budget_cny = 2.5

    with OpenAI(
        api_key=key,
        base_url=url,
        max_retries=0,
        timeout=180,
        http_client=DefaultHttpxClient(trust_env=False),
    ) as client:
        del key

        def metered(messages, schemas, _transport_retry=True):
            if len(rows) >= max_calls or time.perf_counter() - started > task_seconds:
                raise Protection("Task request count or elapsed-time protection")
            view, images = request_view(messages, model)
            input_upper = (
                len(json.dumps({"messages": view, "tools": schemas}, ensure_ascii=False).encode("utf-8"))
                + 16384
                + 64 * len(messages)
                + images * 65536
            )
            reserve = (input_upper * 2 + model.max_tokens * 8) / 1e6
            identifier = ledger.reserve(task_key, reserve, task_budget_cny)
            number = len(rows) + 1
            row = {
                "number": number,
                "started": now(),
                "state": "sending",
                "reserved_cny": reserve,
                "ledger_id": identifier,
            }
            rows.append(row)
            save(record / "usage.json", rows)
            save(
                record / f"requests/{number:04d}.json",
                {"model": model.model, "messages": view, "tools": schemas, "max_tokens": model.max_tokens},
            )
            t0 = time.perf_counter()
            try:
                reply = chat(client, model, messages, schemas)
            except Exception as error:
                row.update(
                    state="transport_error",
                    error_type=type(error).__name__,
                    elapsed_seconds=time.perf_counter() - t0,
                )
                save(record / "usage.json", rows)
                event("model_transport_error", number=number, retry=bool(_transport_retry and retryable_transport(error)))
                if _transport_retry and retryable_transport(error):
                    time.sleep(2)
                    return metered(messages, schemas, False)
                raise
            ended = now()
            measured = costs(reply.usage or {}, row["started"], ended)
            ledger.settle(identifier, measured["peak_cny"], measured)
            row.update(
                state="received",
                ended=ended,
                elapsed_seconds=time.perf_counter() - t0,
                usage=reply.usage,
                model=reply.model,
                finish_reason=reply.finish_reason,
                **measured,
            )
            save(record / f"replies/{number:04d}.json", reply.message)
            save(record / "usage.json", rows)
            event(
                "model_response",
                number=number,
                tools=[x["function"]["name"] for x in reply.message.get("tool_calls") or []],
                cost_cny=measured["estimated_cny"],
            )
            return reply

        qgis = QGISClient(config.qgis.process_launcher)
        catalog = load_catalog(qgis)
        store = SessionStore(config.session_root, "task")
        store.root.mkdir(parents=True, exist_ok=True)
        messages = store.read_record()
        with SqliteCheckpointer.from_conn_string(str(record / "checkpoint.sqlite")) as saver:
            prompt = render_prompt(
                "system.j2",
                output_dir=work / "output",
                supports_images=True,
                supports_memory=False,
                skills=skill_index(),
            )
            (record / "system_prompt.txt").write_text(prompt, encoding="utf-8")
            save(
                record / "runtime_config.json",
                {"model": asdict(model), "context": asdict(config.context), "sdk_retries": 0, "memory": False},
            )
            agent = AgentFactory(config, metered, make_token_counter(model), qgis, catalog).create(
                store, messages, work / "output", saver, prompt
            )
            base_execute = agent.registry.execute
            repeated = []

            def observed(name, args):
                def check(value, writing=False):
                    if isinstance(value, str) and Path(value.split("|")[0]).is_absolute():
                        p = Path(value.split("|")[0]).resolve()
                        roots = (
                            [work / "output", work / "temp", work / "scripts"]
                            if writing
                            else [work, PROJECT / "gis_agent", DATA_ROOT]
                        )
                        return any(p == r or p.is_relative_to(r) for r in roots)
                    if isinstance(value, (list, tuple)):
                        return all(check(v, writing) for v in value)
                    if isinstance(value, dict):
                        return all(check(v, writing) for v in value.values())
                    return True

                if not check(args, name in {"write_file", "edit_file"}):
                    event("scope_refused", tool=name)
                    return {"ok": False, "error": "Benchmark scope: current workspace, GeoBenchX Data catalog, and GIS-Agent skills only."}
                event("tool_start", tool=name, arguments=args)
                begin = time.perf_counter()
                result = base_execute(name, args)
                failed = isinstance(result, dict) and result.get("ok") is False
                event("tool_end", tool=name, failed=failed, elapsed_seconds=time.perf_counter() - begin)
                signature = json.dumps([name, args], sort_keys=True, ensure_ascii=False) if failed else None
                repeated.append(signature)
                if signature and len(repeated) >= 5 and all(s == signature for s in repeated[-5:]):
                    raise Protection("Five identical consecutive tool failures")
                return result

            agent.registry.execute = observed
            save(record / "tool_schemas.json", agent.registry.schemas())
            event("agent_start")
            if messages:
                result = agent.resume(messages)
            else:
                messages.append({"role": "user", "origin": "user", "content": (work / "prompt.txt").read_text(encoding="utf-8")})
                result = agent.run(messages)
            save(record / "result.json", {"outcome": result, "elapsed_seconds": time.perf_counter() - started, "ended": now()})
            event("agent_end", status=result.get("status"))


def launch_one(work: Path, run_dir: Path) -> dict:
    status_path = work / "status.json"
    if status_path.exists():
        return load(status_path)
    begin = time.perf_counter()
    with (work / "records/worker.log").open("ab") as log_stream:
        proc = subprocess.Popen(
            [str(HOST), "-B", str(Path(__file__).resolve()), "worker", "--work", str(work), "--run-dir", str(run_dir)],
            cwd=work,
            stdout=log_stream,
            stderr=log_stream,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            env=os.environ | {"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"},
        )
        timed_out = False
        try:
            code = proc.wait(timeout=1020)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
            code, timed_out = -1, True
    result = load(work / "records/result.json") if (work / "records/result.json").exists() else None
    error = load(work / "records/error.json") if (work / "records/error.json").exists() else None
    evidence = trace(work)
    usage = load(work / "records/usage.json") if (work / "records/usage.json").exists() else []
    row = {
        "id": work.parent.name,
        "returncode": code,
        "timeout": timed_out,
        "elapsed_seconds": time.perf_counter() - begin,
        "status": "timeout"
        if timed_out
        else (
            result["outcome"].get("status", "unknown")
            if result
            else ("protection_stop" if error and error.get("type") == "Protection" else "infrastructure_error")
        ),
        "outcome": result["outcome"] if result else None,
        "error": error,
        "responses": sum(1 for x in usage if x.get("state") == "received"),
        "tool_calls": len(evidence["calls"]),
        "tool_failures": len(evidence["failures"]),
        "estimated_cny": sum(x.get("estimated_cny", 0) or 0 for x in usage),
        "cached_tokens": sum(x.get("cached_tokens", 0) or 0 for x in usage),
        "input_tokens": sum(x.get("input_tokens", 0) or 0 for x in usage),
        "output_tokens": sum(x.get("output_tokens", 0) or 0 for x in usage),
        "ended": now(),
    }
    save(status_path, row)
    print(json.dumps({"task": row["id"], "status": row["status"], "seconds": round(row["elapsed_seconds"], 1), "cny": round(row["estimated_cny"], 4)}), flush=True)
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "run", "worker"])
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--ids", default=",".join(DEFAULT_IDS))
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()

    if args.mode == "worker":
        work = args.work.resolve()
        try:
            run_worker_inprocess(work, run_dir)
        except Exception as error:
            (work / "records/exception.txt").write_text(traceback.format_exc(), encoding="utf-8")
            save(work / "records/error.json", {"time": now(), "type": type(error).__name__, "message": str(error)[:1000]})
            sys.exit(2)
        return

    task_ids = [item.strip() for item in args.ids.split(",") if item.strip()]
    workspaces = [prepare_geobenchx(run_dir, tid) for tid in task_ids]
    if args.mode == "prepare":
        print(f"Prepared {len(workspaces)} GeoBenchX blind workspaces.")
        return

    summary = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(launch_one, w, run_dir) for w in workspaces]
        for fut in concurrent.futures.as_completed(futures):
            summary.append(fut.result())
    save(run_dir / "geobenchx-summary.json", summary)
    print(json.dumps({"geobenchx_completed": len(summary), "total_cny": round(sum(x["estimated_cny"] for x in summary), 4)}))


if __name__ == "__main__":
    main()
