#!/usr/bin/env python3
"""Run a small opt-in multi-design evaluation through real Volundr services.

The runner is diagnostic only: it uses the real Gemini API provider, FastAPI,
and CadQuery worker without opening a browser or changing product policy.
Each case gets a fresh project in one isolated temporary data directory.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.core.config import settings
from run_live_bottle_holder_workflow import free_port, terminate_process, wait_for_health


CASES = (
    {
        "case_id": "A_wall_bracket",
        "request": "Create a compact wall-mounted tool bracket with two screw holes, a support ledge, and an open front for easy removal.",
    },
    {
        "case_id": "B_organizer_tray",
        "request": "Create a desktop organizer tray with four equal compartments, rounded outside corners, and a stable flat base.",
    },
    {
        "case_id": "C_lidded_enclosure",
        "request": "Create a small printable electronics enclosure with a removable lid, a cable opening, and mounting feet.",
    },
)


async def get_json(client: httpx.AsyncClient, path: str) -> Any:
    response = await client.get(path)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


async def run_case(client: httpx.AsyncClient, case: dict[str, str]) -> dict[str, Any]:
    draft = await client.post("/projects/draft")
    draft.raise_for_status()
    project = draft.json()
    started = time.perf_counter()
    chat = await client.post(
        f"/projects/{project['id']}/chat",
        json={"message": case["request"], "client_message_id": f"multi-design-{case['case_id']}"},
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    response: dict[str, Any]
    if chat.status_code >= 400:
        response = {"http_status": chat.status_code, "error": chat.text}
    else:
        response = chat.json()
    revision_id = response.get("revision_id") or response.get("current_working_revision_id")
    return {
        "case_id": case["case_id"],
        "request": case["request"],
        "chat_elapsed_ms": elapsed_ms,
        "workflow_response": response,
        "project": await get_json(client, f"/projects/{project['id']}"),
        "workspace": await get_json(client, f"/projects/{project['id']}/workspace"),
        "requirements": await get_json(client, f"/projects/{project['id']}/requirements/active"),
        "design_specification": await get_json(client, f"/projects/{project['id']}/design-specification"),
        "design_plan": await get_json(client, f"/projects/{project['id']}/design-plan"),
        "revisions": await get_json(client, f"/projects/{project['id']}/revisions") or [],
        "revision": await get_json(client, f"/revisions/{revision_id}") if revision_id else None,
        "outputs": await get_json(client, f"/revisions/{revision_id}/outputs") if revision_id else [],
        "findings": await get_json(client, f"/candidates/{revision_id}/findings") if revision_id else [],
        "generation_attempts": await get_json(client, f"/projects/{project['id']}/generation-attempts") or [],
        "workflow_runs": await get_json(client, f"/projects/{project['id']}/workflow-runs") or [],
    }


async def run_evaluation(api_port: int, env: dict[str, str], backend_root: Path, report_path: Path) -> dict[str, Any]:
    data_dir = Path(env["VOLUNDR_DATA_DIR"])
    worker_log = (data_dir / "cad-worker.log").open("wb")
    api_log = (data_dir / "api.log").open("wb")
    worker = subprocess.Popen(
        [sys.executable, "-m", "app.workers.cad_worker"],
        cwd=backend_root,
        env=env,
        stdout=worker_log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(api_port)],
        cwd=backend_root,
        env=env,
        stdout=api_log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        await wait_for_health(f"http://127.0.0.1:{api_port}", api)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{api_port}/api", timeout=600) as client:
            cases = [await run_case(client, case) for case in CASES]
        report = {
            "evaluation": "multi_design_live",
            "diagnostic_mode": "real_provider_real_fastapi_real_cadquery_worker_no_browser",
            "api_host": "127.0.0.1",
            "cases": cases,
            "worker_pid": worker.pid,
            "worker_alive_after_requests": worker.poll() is None,
        }
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        return report
    finally:
        terminate_process(api)
        terminate_process(worker)
        worker_log.close()
        api_log.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="write the redacted JSON evidence here")
    parser.add_argument("--keep-data", action="store_true", help="keep the isolated live data directory")
    args = parser.parse_args()
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("VOLUNDR_GEMINI_API_KEY") or settings.gemini_api_key):
        print("GEMINI_API_KEY or VOLUNDR_GEMINI_API_KEY is required; the key is never written to the report.", file=sys.stderr)
        return 2

    backend_root = Path(__file__).resolve().parents[1]
    temporary = None if args.keep_data else tempfile.TemporaryDirectory(prefix="volundr-live-multi-design-")
    root = Path(tempfile.mkdtemp(prefix="volundr-live-multi-design-")) if args.keep_data else Path(temporary.name)
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(backend_root),
        "VOLUNDR_AI_PROVIDER": "gemini_api",
        "VOLUNDR_CHAT_FIRST": "true",
        "VOLUNDR_DATA_DIR": str(data_dir),
        "VOLUNDR_CAD_WORKSPACE_DIR": str(data_dir / "jobs"),
    })
    migration = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_root,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )
    if migration.returncode:
        print(migration.stderr, file=sys.stderr)
        return migration.returncode
    try:
        report = asyncio.run(run_evaluation(free_port(), env, backend_root, args.report))
        summary = []
        for case in report["cases"]:
            workflow = case["workflow_response"]
            summary.append({
                "case_id": case["case_id"],
                "action": workflow.get("action"),
                "stage": workflow.get("current_stage"),
                "current_working_revision_id": workflow.get("current_working_revision_id"),
                "revision_count": len(case["revisions"]),
                "output_count": len(case["outputs"] or []),
                "finding_count": len(case["findings"] or []),
                "chat_elapsed_ms": case["chat_elapsed_ms"],
            })
        print(json.dumps({"report": str(args.report), "cases": summary}, indent=2))
        return 0
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
