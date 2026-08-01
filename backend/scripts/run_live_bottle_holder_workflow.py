#!/usr/bin/env python3
"""Run the exact bottle-holder request through real services without a browser."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from uuid import uuid4
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings


REQUEST = (
    "Create a wall-mounted holder for an 81 mm bottle, suitable for a moving "
    "boat, with one-handed removal and two #8 mounting screws."
)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def terminate_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


async def wait_for_health(base_url: str, process: subprocess.Popen[bytes]) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=5) as client:
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError("FastAPI exited before becoming healthy")
            try:
                response = await client.get("/health")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.25)
    raise RuntimeError("FastAPI did not become healthy within 30 seconds")


async def run_workflow(api_port: int, env: dict[str, str], backend_root: Path, report_path: Path) -> dict[str, Any]:
    base_url = f"http://127.0.0.1:{api_port}/api"
    worker_log = Path(env["VOLUNDR_DATA_DIR"]) / "cad-worker.log"
    api_log = Path(env["VOLUNDR_DATA_DIR"]) / "api.log"
    worker = subprocess.Popen(
        [sys.executable, "-m", "app.workers.cad_worker"],
        cwd=backend_root,
        env=env,
        stdout=worker_log.open("wb"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(api_port)],
        cwd=backend_root,
        env=env,
        stdout=api_log.open("wb"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        await wait_for_health(base_url.removesuffix("/api"), api)
        async with httpx.AsyncClient(base_url=base_url, timeout=300) as client:
            draft = await client.post("/projects/draft")
            draft.raise_for_status()
            project = draft.json()
            started_at = time.perf_counter()
            chat = await client.post(
                f"/projects/{project['id']}/chat",
                json={"message": REQUEST, "client_message_id": "live-bottle-holder-exact-v1"},
            )
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
            if chat.status_code >= 400:
                raise RuntimeError(f"chat request failed ({chat.status_code}): {chat.text}")
            response = chat.json()

            async def get(path: str) -> Any:
                result = await client.get(path)
                if result.status_code == 404:
                    return None
                result.raise_for_status()
                return result.json()

            revisions = await get(f"/projects/{project['id']}/revisions") or []
            current_project = await get(f"/projects/{project['id']}")
            specification = await get(f"/design-specifications/{response['design_specification_id']}") if response.get("design_specification_id") else None
            design_plan = await get(f"/design-plans/{response['design_plan_id']}") if response.get("design_plan_id") else None
            workflow_events = await get(f"/workflow-runs/{response['workflow_run_id']}/events") if response.get("workflow_run_id") else []
            outputs = []
            findings = []
            revision_id = response.get("revision_id") or response.get("current_working_revision_id")
            if revision_id:
                outputs = await get(f"/revisions/{revision_id}/outputs") or []
                findings = await get(f"/candidates/{revision_id}/findings") or []
            report = {
                "request": REQUEST,
                "diagnostic_mode": "real_provider_real_fastapi_real_cadquery_worker_no_browser",
                "api_host": "127.0.0.1",
                "workflow": response,
                "project": current_project,
                "requirements": specification,
                "design_plan": design_plan,
                "workflow_events": workflow_events or [],
                "revisions": revisions,
                "outputs": outputs,
                "findings": findings,
                "generation_attempts": await get(f"/projects/{project['id']}/generation-attempts") or [],
                "workflow_runs": await get(f"/projects/{project['id']}/workflow-runs") or [],
                "chat_elapsed_ms": elapsed_ms,
                "worker_pid": worker.pid,
                "worker_alive_after_request": worker.poll() is None,
            }
            report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
            return report
    finally:
        terminate_process(api)
        terminate_process(worker)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=None, help="write the redacted JSON result here")
    parser.add_argument("--keep-data", action="store_true", help="keep the temporary live data directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("VOLUNDR_GEMINI_API_KEY") or settings.gemini_api_key):
        print("GEMINI_API_KEY or VOLUNDR_GEMINI_API_KEY is required; the key is never written to the report.", file=sys.stderr)
        return 2
    backend_root = Path(__file__).resolve().parents[1]
    keep_root = args.keep_data
    temporary = None if keep_root else tempfile.TemporaryDirectory(prefix="volundr-live-bottle-holder-")
    root = Path(tempfile.mkdtemp(prefix="volundr-live-bottle-holder-")) if keep_root else Path(temporary.name)
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.report or Path(tempfile.gettempdir()) / f"volundr-bottle-holder-live-{uuid4().hex}.json"
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(backend_root),
            "VOLUNDR_AI_PROVIDER": "gemini_api",
            "VOLUNDR_DATA_DIR": str(data_dir),
            "VOLUNDR_CAD_WORKSPACE_DIR": str(data_dir / "jobs"),
        }
    )
    api_port = free_port()
    try:
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
        report = asyncio.run(run_workflow(api_port, env, backend_root, report_path))
        print(json.dumps({
            "report": str(report_path),
            "action": report["workflow"].get("action"),
            "stage": report["workflow"].get("current_stage"),
            "current_working_revision_id": report["workflow"].get("current_working_revision_id"),
            "revision_count": len(report["revisions"]),
            "output_count": len(report["outputs"]),
            "finding_count": len(report["findings"]),
            "chat_elapsed_ms": report["chat_elapsed_ms"],
        }, indent=2))
        return 0
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
