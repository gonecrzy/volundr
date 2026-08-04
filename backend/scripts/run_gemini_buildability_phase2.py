#!/usr/bin/env python3
"""Run the authorized five-case, two-arm Gemini buildability validation."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx

from app.services.gemini_consistency.buildability_reanalysis import (
    DEFAULT_MIN_INTERVAL_SECONDS,
    RollingWindowRateLimiter,
    apply_profile_b_generation_config,
    merge_phase2_manual_review,
)
from app.services.gemini_consistency.corpus import load_flash_lite_study_corpus
from app.services.workflow.redaction import RedactionService
from run_live_bottle_holder_workflow import terminate_process, wait_for_health
from run_live_multi_design_evaluation import get_json, run_case


CASE_IDS = ("case-001", "case-002", "case-003", "case-006", "case-008")
UPSTREAM = "https://generativelanguage.googleapis.com"


class GeminiProxy(ThreadingHTTPServer):
    def __init__(self, arm: str, limiter: RollingWindowRateLimiter) -> None:
        self.arm = arm
        self.limiter = limiter
        self.events: list[dict[str, Any]] = []
        self.quota_exhausted = False
        super().__init__(("127.0.0.1", 0), GeminiProxyHandler)


class GeminiProxyHandler(BaseHTTPRequestHandler):
    server: GeminiProxy

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        self._forward(None)

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        self._forward(self.rfile.read(length))

    def _forward(self, body: bytes | None) -> None:
        if self.server.quota_exhausted:
            self.send_error(429, "quota exhausted; experiment stopped")
            return
        limiter_event = self.server.limiter.acquire()
        outgoing = body
        if self.server.arm == "profile-b-sampling" and body and self.command == "POST" and ":generateContent" in self.path:
            try:
                payload = json.loads(body)
                if isinstance(payload, dict) and isinstance(payload.get("generationConfig"), dict):
                    payload["generationConfig"] = apply_profile_b_generation_config(payload["generationConfig"])
                    outgoing = json.dumps(payload).encode("utf-8")
            except (TypeError, ValueError):
                outgoing = body
        headers = {key: value for key, value in self.headers.items() if key.lower() not in {"host", "content-length", "accept-encoding"}}
        try:
            response = httpx.request(self.command, f"{UPSTREAM}{self.path}", headers=headers, content=outgoing, timeout=180.0)
            response_body = response.content
            self.send_response(response.status_code)
            for key, value in response.headers.items():
                if key.lower() not in {"content-length", "transfer-encoding", "connection", "content-encoding"}:
                    self.send_header(key, value)
            self.send_header("content-length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
            if response.status_code == 429:
                self.server.quota_exhausted = True
            self.server.events.append({**limiter_event, "method": self.command, "path": self.path.split("?", 1)[0], "status_code": response.status_code, "arm": self.server.arm})
        except httpx.HTTPError as exc:
            self.send_error(502, str(exc))
            self.server.events.append({**limiter_event, "method": self.command, "path": self.path.split("?", 1)[0], "status_code": 502, "error": "proxy_transport_failure", "arm": self.server.arm})


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_proxy(arm: str, limiter: RollingWindowRateLimiter) -> tuple[GeminiProxy, threading.Thread]:
    proxy = GeminiProxy(arm, limiter)
    thread = threading.Thread(target=proxy.serve_forever, name=f"gemini-rate-proxy-{arm}", daemon=True)
    thread.start()
    return proxy, thread


def _safe_run_migration(env: dict[str, str], backend_root: Path) -> None:
    migration = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=backend_root, env=env, check=False, text=True, capture_output=True)
    if migration.returncode:
        raise RuntimeError(migration.stderr or "database migration failed")


async def _run_arm(*, arm: str, cases: list[dict[str, Any]], output_root: Path, backend_root: Path, limiter: RollingWindowRateLimiter) -> dict[str, Any]:
    data_root = output_root / "phase-2" / "live-data-final" / arm
    data_root.mkdir(parents=True, exist_ok=True)
    proxy, proxy_thread = _start_proxy(arm, limiter)
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(backend_root),
        "VOLUNDR_AI_PROVIDER": "gemini_api",
        "VOLUNDR_DATA_DIR": str(data_root),
        "VOLUNDR_CAD_WORKSPACE_DIR": str(data_root / "jobs"),
        "VOLUNDR_GEMINI_API_BASE_URL": f"http://127.0.0.1:{proxy.server_port}/v1beta",
        "VOLUNDR_GEMINI_API_MAX_RETRIES": "0",
        "VOLUNDR_GEMINI_API_MAX_RETRY_SLEEP_SECONDS": "0",
        "VOLUNDR_GEMINI_MODEL": "gemini-3.5-flash-lite",
        "VOLUNDR_GEMINI_REQUIREMENTS_MODEL": "gemini-3.5-flash-lite",
        "VOLUNDR_GEMINI_DESIGN_PLAN_MODEL": "gemini-3.5-flash-lite",
        "VOLUNDR_GEMINI_GEOMETRY_MODEL": "gemini-3.5-flash-lite",
        "VOLUNDR_GEMINI_GEOMETRY_REPAIR_MODEL": "gemini-3.5-flash-lite",
    })
    _safe_run_migration(env, backend_root)
    worker_log = (data_root / "cad-worker.log").open("wb")
    api_log = (data_root / "api.log").open("wb")
    worker = subprocess.Popen([sys.executable, "-m", "app.workers.cad_worker"], cwd=backend_root, env=env, stdout=worker_log, stderr=subprocess.STDOUT, start_new_session=True)
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(_free_port())], cwd=backend_root, env=env, stdout=api_log, stderr=subprocess.STDOUT, start_new_session=True)
    port = int(api.args[-1])
    results: list[dict[str, Any]] = []
    try:
        await wait_for_health(f"http://127.0.0.1:{port}", api)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}/api", timeout=600) as client:
            for case in cases:
                results.append(await run_case(client, case))
                if proxy.quota_exhausted:
                    break
    finally:
        terminate_process(api)
        terminate_process(worker)
        worker_log.close()
        api_log.close()
        proxy.shutdown()
        proxy.server_close()
        proxy_thread.join(timeout=5)
    provider_interactions = []
    for chain_path in sorted(data_root.rglob("generation-runs/*/chain.json")):
        try:
            chain = json.loads(chain_path.read_text(encoding="utf-8"))
            request_path = chain_path.parent / "request.json"
            request = json.loads(request_path.read_text(encoding="utf-8")) if request_path.is_file() else None
            provider_interactions.append({"source_provider_call_path": str(chain_path.relative_to(output_root)), "request": request, "chain": chain})
        except json.JSONDecodeError:
            continue
    return {"arm": arm, "cases": results, "project_operations": len(results), "quota_exhausted": proxy.quota_exhausted, "rate_limit": {"policy": proxy.limiter.report(), "events": proxy.events}, "provider_interactions": provider_interactions, "provider_calls": len(proxy.events), "data_root": f"phase-2/live-data-final/{arm}"}


def _case_documents(study_root: Path) -> list[dict[str, Any]]:
    corpus = load_flash_lite_study_corpus(study_root / "corpus.json")
    return [{"case_id": case.case_id, "title": case.title, "request": case.initial_prompt, "fact_sheet": case.fact_sheet, "expected_route": case.expected_route_category} for case in (corpus.case(case_id) for case_id in CASE_IDS)]


def _write_report(path: Path, value: Any, root: Path) -> None:
    redactor = RedactionService()
    safe, _ = redactor.redact_evidence_value(value, data_root=root / "data", evidence_root=path.parent)
    redactor.assert_json_redacted(safe)
    path.write_text(json.dumps(safe, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _enrich_existing_phase2_report(output_root: Path) -> dict[str, Any]:
    path = output_root / "reports/phase-2-project-results.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    for arm in report.get("arms", []):
        data_root = output_root / arm["data_root"]
        interactions = []
        for chain_path in sorted(data_root.rglob("generation-runs/*/chain.json")):
            chain = json.loads(chain_path.read_text(encoding="utf-8"))
            request_path = chain_path.parent / "request.json"
            interaction = {
                "source_provider_call_path": str(chain_path.relative_to(output_root)),
                "model_identity": "gemini-3.5-flash-lite",
                "request": json.loads(request_path.read_text(encoding="utf-8")) if request_path.is_file() else None,
                "chain": chain,
                "raw_response_text": (chain_path.parent / "raw-output.txt").read_text(encoding="utf-8") if (chain_path.parent / "raw-output.txt").is_file() else None,
                "parsed_response": json.loads((chain_path.parent / "provider-parsed.json").read_text(encoding="utf-8")) if (chain_path.parent / "provider-parsed.json").is_file() else None,
                "normalized_response": json.loads((chain_path.parent / "provider-normalized.json").read_text(encoding="utf-8")) if (chain_path.parent / "provider-normalized.json").is_file() else None,
            }
            interactions.append(interaction)
        arm["provider_interactions"] = interactions
        arm["provider_calls"] = len(arm.get("rate_limit", {}).get("events", []))
    _write_report(path, report, output_root)
    merge_phase2_manual_review(output_root)
    return report


def _comparison(arms: list[dict[str, Any]]) -> dict[str, Any]:
    by_arm = {arm["arm"]: arm for arm in arms}
    summaries = {}
    for arm in arms:
        summaries[arm["arm"]] = {
            "project_operations": arm["project_operations"],
            "cases_reached": len(arm["cases"]),
            "quota_exhausted": arm["quota_exhausted"],
            "responses_with_revision": sum(bool(case.get("workflow_response", {}).get("revision_id") or case.get("workflow_response", {}).get("current_working_revision_id")) for case in arm["cases"]),
            "worker_ready_valid_source": sum(bool((case.get("project") or {}).get("worker_ready_valid_source")) for case in arm["cases"]),
            "output_count": sum(len(case.get("outputs") or []) for case in arm["cases"]),
            "finding_count": sum(len(case.get("findings") or []) for case in arm["cases"]),
            "provider_calls": arm["provider_calls"],
            "tokens": 0,
            "latency_ms": 0,
        }
    return {"comparison_type": "small_descriptive_live_comparison_no_statistical_significance", "arms": summaries, "candidate": "profile-b-sampling", "current": "current-production", "improvements_in_at_least_two_cases": False, "final_blocker": "requires manual review of per-case workflow and topology evidence"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01"))
    parser.add_argument("--study-root", type=Path, default=Path("data/debug-sessions/gemini-flash-lite-study/gemini-flash-lite-study-01"))
    parser.add_argument("--rebuild-only", action="store_true", help="enrich the existing final-attempt report without making provider calls")
    args = parser.parse_args()
    output_root = args.output_root
    if args.rebuild_only:
        report = _enrich_existing_phase2_report(output_root)
        print(json.dumps({"rebuild_only": True, "arms": [{"arm": arm["arm"], "provider_calls": arm["provider_calls"], "provider_interactions": len(arm.get("provider_interactions", []))} for arm in report.get("arms", [])]}, indent=2, sort_keys=True))
        return 0
    cases = _case_documents(args.study_root)
    backend_root = Path(__file__).resolve().parents[1]
    arms: list[dict[str, Any]] = []
    experiment_limiter = RollingWindowRateLimiter(min_interval_seconds=DEFAULT_MIN_INTERVAL_SECONDS)
    for arm in ("current-production", "profile-b-sampling"):
        result = asyncio.run(_run_arm(arm=arm, cases=cases, output_root=output_root, backend_root=backend_root, limiter=experiment_limiter))
        arms.append(result)
        if result["quota_exhausted"] or result["project_operations"] < 5:
            break
    comparison = _comparison(arms)
    _write_report(output_root / "reports/phase-2-project-results.json", {"schema_version": "gemini-profile-ablation-phase-2-project-results-v1", "case_ids": list(CASE_IDS), "arms": arms}, output_root)
    _write_report(output_root / "reports/phase-2-comparison.json", {"schema_version": "gemini-profile-ablation-phase-2-comparison-v1", **comparison}, output_root)
    print(json.dumps({"arms": [{"arm": arm["arm"], "project_operations": arm["project_operations"], "provider_calls": arm["provider_calls"], "quota_exhausted": arm["quota_exhausted"]} for arm in arms], "comparison": comparison}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
