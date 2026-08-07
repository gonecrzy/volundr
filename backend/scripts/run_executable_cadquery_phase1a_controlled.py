"""Launch the bounded Phase 1A survey through the credential-safe live harness pattern.

The repository root ``.env`` is resolved once into a temporary backend-only
environment file.  The worker receives neither credential; the survey process
receives only the shared API settings used by the ordinary API process.  The
temporary environment file and successful-run data are removed on exit.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import tempfile
from typing import Any

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "backend/.venv/bin/python"
ALEMBIC = ROOT / "backend/.venv/bin/alembic"
SURVEY = ROOT / "backend/scripts/run_executable_cadquery_phase1a_survey.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--only-project-order", type=int)
    parser.add_argument("--project-orders", type=str)
    parser.add_argument("--record-suffix", type=str, default="first-pass")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = args.manifest.resolve()
    output_root = args.output_root.resolve()
    root_values = {
        key: value
        for key, value in dotenv_values(ROOT / ".env").items()
        if value is not None
    }
    primary = root_values.get("GEMINI_API_KEY", "")
    fallback = root_values.get("GEMINI_API_KEY_2", "")
    if not primary or not fallback:
        raise SystemExit("root credential presence precondition failed")

    live_dir = Path(tempfile.mkdtemp(prefix="volundr-phase1a."))
    backend_env_file = Path(tempfile.mktemp(prefix="volundr-phase1a-backend-env."))
    backend_env_file.write_text(
        "export VOLUNDR_GEMINI_PRIMARY_API_KEY="
        + shlex.quote(primary)
        + "\nexport VOLUNDR_GEMINI_FALLBACK_API_KEY="
        + shlex.quote(fallback)
        + "\n",
        encoding="utf-8",
    )
    backend_env_file.chmod(0o600)
    data_dir = live_dir / "data"
    jobs_dir = data_dir / "jobs"
    jobs_dir.mkdir(parents=True)
    environment = os.environ.copy()
    environment.update(
        {
            "VOLUNDR_GEMINI_PRIMARY_API_KEY": primary,
            "VOLUNDR_GEMINI_FALLBACK_API_KEY": fallback,
            "VOLUNDR_AI_PROVIDER": "gemini_api",
            "VOLUNDR_EXECUTABLE_CADQUERY_FLOW_ENABLED": "true",
            "VOLUNDR_EXECUTABLE_CADQUERY_CORPUS_MANIFEST_PATH": str(manifest),
            "VOLUNDR_DEVELOPER_TOOLS_ENABLED": "true",
            "VOLUNDR_GEMINI_API_MAX_RETRIES": "1",
            "VOLUNDR_DATA_DIR": str(data_dir),
            "VOLUNDR_CAD_WORKSPACE_DIR": str(jobs_dir),
            "PYTHONPATH": str(ROOT / "backend"),
            "GEMINI_API_KEY": "",
            "GEMINI_API_KEY_2": "",
        }
    )
    worker: subprocess.Popen[Any] | None = None
    survey: subprocess.Popen[Any] | None = None
    success = False
    try:
        subprocess.run([str(ALEMBIC), "upgrade", "head"], cwd=ROOT / "backend", env=environment, check=True)
        worker_log = live_dir / "cad-worker.log"
        with worker_log.open("w", encoding="utf-8") as stream:
            worker = subprocess.Popen(
                [str(PYTHON), "-m", "app.workers.cad_worker"],
                cwd=ROOT,
                env=environment,
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        survey_log = live_dir / "survey.log"
        survey_args = [
            str(PYTHON),
            str(SURVEY),
            "--manifest",
            str(manifest),
            "--output-root",
            str(output_root),
            "--record-suffix",
            args.record_suffix,
        ]
        if args.only_project_order is not None:
            survey_args.extend(["--only-project-order", str(args.only_project_order)])
        if args.project_orders is not None:
            survey_args.extend(["--project-orders", args.project_orders])
        with survey_log.open("w", encoding="utf-8") as stream:
            survey = subprocess.Popen(
                survey_args,
                cwd=ROOT,
                env=environment,
                stdout=stream,
                stderr=subprocess.STDOUT,
            )
        return_code = survey.wait()
        record_count = len(list(output_root.glob(f"project-*-{args.record_suffix}.json")))
        print(f"survey_return_code={return_code}")
        print(f"first_pass_records={record_count}")
        if return_code != 0:
            print(f"retained_live_data={live_dir}")
            tail = survey_log.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
            for line in tail:
                print(line[:600])
            return return_code
        success = True
        return 0
    finally:
        for process in (survey, worker):
            if process is not None and process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        backend_env_file.unlink(missing_ok=True)
        if success:
            shutil.rmtree(live_dir, ignore_errors=True)
if __name__ == "__main__":
    raise SystemExit(main())
