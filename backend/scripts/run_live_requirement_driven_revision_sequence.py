#!/usr/bin/env python3
"""Run the exact requirement-first bottle-holder revision sequence.

This is a diagnostic-only backend path.  It uses the real Gemini provider,
FastAPI services, and the real CadQuery worker, but never opens a browser.
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


REQUEST = (
    "Create a wall-mounted holder for an 81 mm bottle, suitable for a moving "
    "boat, with one-handed removal and two #8 mounting screws."
)
SEQUENCE = [
    ("initial", REQUEST),
    ("fit_feedback", "The printed fit is too tight. Add 0.5 mm clearance per side."),
    ("structural_feedback", "Make the mounting plate thicker and reinforce it because it flexes."),
    ("irregular_mounting_change", "Move the lower mounting hole 8 mm left to clear an obstruction."),
    ("optional_control", "Expose bottle diameter as an adjustable control."),
]


async def snapshot(client: httpx.AsyncClient, project_id: str, response: dict[str, Any]) -> dict[str, Any]:
    async def get(path: str) -> Any:
        result = await client.get(path)
        if result.status_code == 404:
            return None
        result.raise_for_status()
        return result.json()

    revision_id = response.get("revision_id") or response.get("current_working_revision_id")
    return {
        "workflow_response": response,
        "project": await get(f"/projects/{project_id}"),
        "active_requirements": await get(f"/projects/{project_id}/requirements/active"),
        "design_specification": await get(f"/projects/{project_id}/design-specification"),
        "design_plan": await get(f"/projects/{project_id}/design-plan"),
        "revisions": await get(f"/projects/{project_id}/revisions") or [],
        "revision": await get(f"/revisions/{revision_id}") if revision_id else None,
        "outputs": await get(f"/revisions/{revision_id}/outputs") if revision_id else [],
        "findings": await get(f"/candidates/{revision_id}/findings") if revision_id else [],
        "generation_attempts": await get(f"/projects/{project_id}/generation-attempts") or [],
        "workflow_runs": await get(f"/projects/{project_id}/workflow-runs") or [],
    }


async def run_sequence(api_port: int, env: dict[str, str], backend_root: Path, report_path: Path) -> dict[str, Any]:
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
            draft = await client.post("/projects/draft")
            draft.raise_for_status()
            project_id = draft.json()["id"]
            stages: list[dict[str, Any]] = []
            for index, (stage, message) in enumerate(SEQUENCE):
                started = time.perf_counter()
                response = await client.post(
                    f"/projects/{project_id}/chat",
                    json={"message": message, "client_message_id": f"live-requirement-sequence-{index}"},
                )
                elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
                if response.status_code >= 400:
                    stages.append({"stage": stage, "request": message, "http_status": response.status_code, "error": response.text, "elapsed_ms": elapsed_ms})
                    break
                state = await snapshot(client, project_id, response.json())
                state.update({"stage": stage, "request": message, "elapsed_ms": elapsed_ms})
                stages.append(state)
                # A failed initial request has no safe base for later revisions;
                # preserve the evidence and stop rather than inventing a branch.
                if stage == "initial" and not state["project"].get("active_revision_id"):
                    break
            report = {
                "request": REQUEST,
                "sequence": [message for _, message in SEQUENCE],
                "diagnostic_mode": "real_provider_real_fastapi_real_cadquery_worker_no_browser",
                "api_host": "127.0.0.1",
                "project_id": project_id,
                "stages": stages,
                "worker_pid": worker.pid,
                "worker_alive_after_request": worker.poll() is None,
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
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--keep-data", action="store_true")
    args = parser.parse_args()
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("VOLUNDR_GEMINI_API_KEY") or settings.gemini_api_key):
        print("GEMINI_API_KEY or VOLUNDR_GEMINI_API_KEY is required; the key is never written to the report.", file=sys.stderr)
        return 2
    backend_root = Path(__file__).resolve().parents[1]
    temporary = None if args.keep_data else tempfile.TemporaryDirectory(prefix="volundr-live-requirement-sequence-")
    root = Path(tempfile.mkdtemp(prefix="volundr-live-requirement-sequence-")) if args.keep_data else Path(temporary.name)
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.report or Path(tempfile.gettempdir()) / f"volundr-requirement-driven-live-{uuid4().hex}.json"
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
    report = asyncio.run(run_sequence(free_port(), env, backend_root, report_path))
    last_stage = report["stages"][-1] if report["stages"] else {}
    last_response = last_stage.get("workflow_response") if isinstance(last_stage, dict) else None
    print(json.dumps({
        "report": str(report_path),
        "stage_count": len(report["stages"]),
        "last_action": last_response.get("action") if isinstance(last_response, dict) else None,
        "last_stage": last_response.get("current_stage") if isinstance(last_response, dict) else last_stage.get("stage"),
        "http_status": last_stage.get("http_status"),
    }, indent=2))
    if temporary is not None:
        temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
