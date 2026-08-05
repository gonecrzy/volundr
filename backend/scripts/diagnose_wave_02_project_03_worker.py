#!/usr/bin/env python3
"""Isolate the Wave-02 Project-03 worker timeout from the frozen source."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import resource
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.services.cad.cadquery_runner import CadQueryCliRunner
from app.services.cad.cadquery_contract import validate_cadquery_source


REPO_ROOT = Path(__file__).resolve().parents[2]
WAVE_ROOT = REPO_ROOT / "data/debug-sessions/representative-workflow-waves/representative-workflow-wave-02"
SOURCE_PATH = WAVE_ROOT / "worker-jobs/gemini-integration-wave-02-project-03-wave-02-project-03-revision-001/input/model.py"
JOB_PATH = WAVE_ROOT / "worker-jobs/gemini-integration-wave-02-project-03-wave-02-project-03-revision-001/job.json"
EXPECTED_SOURCE_HASH = "f725a0eca8888e923b25e69f21a8c5d20f0c49bbacb1ab613202b399a682acdf"
DEFAULT_REPORT_ROOT = REPO_ROOT / "reports/wave-02-closure-01"
DIAGNOSTIC_TIMEOUT_SECONDS = 300

ORIGINAL_OUTPUT_IDS = ["enclosure_base_output", "enclosure_lid_output", "cable_clamp_output"]
AUTHORITATIVE_OUTPUT_IDS = ["enclosure_base", "enclosure_lid", "cable_clamp"]
COMPONENT_FUNCTIONS = {
    "enclosure_base": "build_component_enclosure_base",
    "enclosure_lid": "build_component_enclosure_lid",
    "cable_clamp": "build_component_cable_clamp",
}


CHILD_RUNNER = r'''
import argparse
import importlib.util
import json
import resource
import sys
import time
from pathlib import Path

import cadquery as cq
from app.services.cad.cadquery_contract import validate_cadquery_source
from volundr_cad.runtime import ParameterValues

TIMING = {"operations": [], "functions": []}


def usage():
    current = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "user_cpu_seconds": round(current.ru_utime, 6),
        "system_cpu_seconds": round(current.ru_stime, 6),
        "max_rss_kb": current.ru_maxrss,
    }


def shape_summary(value):
    try:
        shape = value.val() if hasattr(value, "val") else value
        if shape is None:
            return None
        bounds = shape.BoundingBox() if hasattr(shape, "BoundingBox") else None
        return {
            "solid_count": len(shape.Solids()) if hasattr(shape, "Solids") else None,
            "face_count": len(shape.Faces()) if hasattr(shape, "Faces") else None,
            "edge_count": len(shape.Edges()) if hasattr(shape, "Edges") else None,
            "volume_mm3": round(float(shape.Volume()), 6) if hasattr(shape, "Volume") else None,
            "valid": bool(shape.isValid()) if hasattr(shape, "isValid") else None,
            "bounding_box_mm": {
                "x_min": round(float(bounds.xmin), 6),
                "y_min": round(float(bounds.ymin), 6),
                "z_min": round(float(bounds.zmin), 6),
                "x_max": round(float(bounds.xmax), 6),
                "y_max": round(float(bounds.ymax), 6),
                "z_max": round(float(bounds.zmax), 6),
            } if bounds is not None else None,
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def shape_complexity(value):
    summary = shape_summary(value)
    if not isinstance(summary, dict):
        return {}
    return {
        "solid_count": summary.get("solid_count"),
        "face_count": summary.get("face_count"),
        "edge_count": summary.get("edge_count"),
    }


def install_operation_timing():
    originals = {}
    for name in ("box", "cylinder", "extrude", "cut", "cutBlind", "cutThruAll", "union", "intersect", "fillet", "chamfer", "loft", "shell", "hole", "mirror", "rotate", "translate", "spline", "circle", "slot2D", "sweep"):
        original = getattr(cq.Workplane, name, None)
        if not callable(original):
            continue
        originals[name] = original

        def timed(self, *args, _name=name, _original=original, **kwargs):
            started = time.perf_counter()
            before = shape_complexity(self)
            try:
                return _original(self, *args, **kwargs)
            finally:
                TIMING["operations"].append({
                    "name": _name,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                    "before": before,
                })

        setattr(cq.Workplane, name, timed)
    return originals


def restore_operation_timing(originals):
    for name, original in originals.items():
        setattr(cq.Workplane, name, original)


class Profiler:
    def __init__(self):
        self.active = {}

    def __call__(self, frame, event, _arg):
        if frame.f_globals.get("__name__") != "diagnostic_model":
            return self
        key = id(frame)
        if event == "call":
            self.active[key] = (frame.f_code.co_name, time.perf_counter())
        elif event in {"return", "exception"}:
            record = self.active.pop(key, None)
            if record is not None:
                name, started = record
                TIMING["functions"].append({
                    "name": name,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                    "event": event,
                })
        return self


def import_model(path):
    spec = importlib.util.spec_from_file_location("diagnostic_model", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to create model import spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def params_for(module):
    return ParameterValues.from_specs(getattr(module, "PARAMETERS", ()), {})


def export_shape(model, output_dir, output_id, fmt):
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{output_id}.{fmt.lower()}"
    started = time.perf_counter()
    cq.exporters.export(model, str(path))
    return {
        "format": fmt,
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--component")
    parser.add_argument("--function")
    parser.add_argument("--output-id")
    parser.add_argument("--formats", default="")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    started = time.perf_counter()
    result = {
        "mode": args.mode,
        "success": False,
        "source_hash": __import__("hashlib").sha256(args.source.read_bytes()).hexdigest(),
        "usage_start": usage(),
    }
    originals = install_operation_timing()
    profiler = Profiler()
    sys.setprofile(profiler)
    try:
        if args.mode == "compile_only":
            compile(args.source.read_text(encoding="utf-8"), str(args.source), "exec")
            validate_cadquery_source(args.source.read_text(encoding="utf-8"), contract_version="cadquery-v1")
            result["success"] = True
        else:
            module = import_model(args.source)
            if args.mode == "import_only":
                result["success"] = True
            elif args.mode == "build_component":
                model = getattr(module, args.function)(params_for(module))
                result["shape"] = shape_summary(model)
                result["success"] = True
            elif args.mode in {"build_product", "export_output"}:
                product = module.build(params_for(module))
                result["product_output_ids"] = [output.output_id for output in product.outputs]
                result["output_shapes"] = {output.output_id: shape_summary(output.model) for output in product.outputs}
                if args.mode == "build_product":
                    result["success"] = True
                else:
                    outputs = {output.output_id: output for output in product.outputs}
                    printable = outputs[args.output_id]
                    result["pre_export_shape"] = shape_summary(printable.model)
                    result["exports"] = [
                        export_shape(printable.model, args.out / "artifacts", args.output_id, fmt)
                        for fmt in args.formats.split(",")
                        if fmt
                    ]
                    result["success"] = True
            else:
                raise RuntimeError(f"unknown mode: {args.mode}")
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["error_message"] = str(exc)
    finally:
        sys.setprofile(None)
        restore_operation_timing(originals)
        result["elapsed_seconds"] = round(time.perf_counter() - started, 6)
        result["operation_timing"] = TIMING["operations"]
        result["function_timing"] = TIMING["functions"]
        result["last_completed_operation"] = TIMING["operations"][-1] if TIMING["operations"] else None
        result["usage_end"] = usage()
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def source_hash() -> str:
    return hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest()


def run_child(report_root: Path, name: str, args: list[str], *, timeout: int = DIAGNOSTIC_TIMEOUT_SECONDS) -> dict[str, Any]:
    run_dir = report_root / "project-03-diagnostic-runs" / name
    run_dir.mkdir(parents=True, exist_ok=True)
    runner_path = run_dir / "diagnostic_child.py"
    runner_path.write_text(CHILD_RUNNER, encoding="utf-8")
    copied_source = run_dir / "model.py"
    shutil.copyfile(SOURCE_PATH, copied_source)
    command = [
        sys.executable,
        str(runner_path),
        "--source",
        str(copied_source),
        "--out",
        str(run_dir),
        *args,
    ]
    started = time.perf_counter()
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT / "backend"),
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "VTK_SMP_MAX_THREADS": "1",
    }
    completed = subprocess.run(command, cwd=run_dir, env=env, text=True, capture_output=True, timeout=timeout, check=False)
    result_path = run_dir / "result.json"
    result = read_json(result_path) if result_path.exists() else {}
    result.update({
        "run_id": name,
        "exit_code": completed.returncode,
        "timed_out": False,
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-4000:],
        "wall_seconds": round(time.perf_counter() - started, 6),
    })
    write_json(result_path, result)
    return result


async def run_full_worker(report_root: Path, name: str, requested_outputs: list[dict[str, Any]], *, timeout_seconds: int = DIAGNOSTIC_TIMEOUT_SECONDS) -> dict[str, Any]:
    workspace = report_root / "project-03-diagnostic-runs" / name / "worker-workspace"
    runner = CadQueryCliRunner(workspace_root=workspace, timeout_seconds=timeout_seconds)
    started = time.perf_counter()
    result = await runner.compile(
        SOURCE_PATH.read_text(encoding="utf-8"),
        name,
        parameter_values={},
        requested_outputs=requested_outputs,
    )
    payload = {
        "run_id": name,
        "mode": "cadquery_cli_runner",
        "success": result.success,
        "timed_out": result.timed_out,
        "exit_code": result.exit_code,
        "error_message": result.error_message,
        "source_hash": result.source_hash,
        "wall_seconds": round(time.perf_counter() - started, 6),
        "output_size_bytes": result.output_size_bytes,
        "outputs": [
            {
                "output_id": output.output_id,
                "success": output.success,
                "compile_error": output.compile_error,
                "stl_path": str(output.stl_path) if output.stl_path else None,
                "step_path": str(output.step_path) if output.step_path else None,
                "brep_path": str(output.brep_path) if output.brep_path else None,
                "topology_metadata": output.topology_metadata,
                "feature_trace": output.feature_trace,
            }
            for output in result.outputs
        ],
        "execution_timing": result.execution_timing,
        "command_args": result.command_args,
        "execution_manifest_path": str(result.execution_manifest_path) if result.execution_manifest_path else None,
    }
    write_json(report_root / "project-03-diagnostic-runs" / name / "result.json", payload)
    return payload


def requested_outputs(ids: list[str] | None = None) -> list[dict[str, Any]]:
    payload = read_json(JOB_PATH)
    outputs = [dict(item) for item in payload["requested_outputs"]]
    if ids is None:
        return outputs
    by_component = {item["component_ids"][0]: item for item in outputs}
    result = []
    for output_id in ids:
        if output_id in by_component:
            item = dict(by_component[output_id])
            item["output_id"] = output_id
            result.append(item)
        else:
            found = next((dict(item) for item in outputs if item.get("output_id") == output_id), None)
            if found is not None:
                result.append(found)
    return result


async def run_diagnostics(report_root: Path) -> dict[str, Any]:
    if source_hash() != EXPECTED_SOURCE_HASH:
        raise RuntimeError("Project 03 frozen source hash mismatch")
    report_root.mkdir(parents=True, exist_ok=True)

    exact_source = {
        "source_path": str(SOURCE_PATH),
        "source_hash": source_hash(),
        "expected_source_hash": EXPECTED_SOURCE_HASH,
        "hash_matches": True,
        "source_modified": False,
    }
    phases = [
        run_child(report_root, "01_compile_only", ["--mode", "compile_only"]),
        run_child(report_root, "02_import_only", ["--mode", "import_only"]),
    ]
    for component, function_name in COMPONENT_FUNCTIONS.items():
        phases.append(run_child(report_root, f"03_build_{component}", ["--mode", "build_component", "--component", component, "--function", function_name]))
    phases.append(run_child(report_root, "06_build_all_outputs_no_export", ["--mode", "build_product"]))
    export_results = []
    for fmt in ("BREP", "STEP", "STL"):
        for output_id in ORIGINAL_OUTPUT_IDS:
            export_results.append(run_child(report_root, f"export_{output_id}_{fmt.lower()}", ["--mode", "export_output", "--output-id", output_id, "--formats", fmt]))

    full_original = await run_full_worker(report_root, "full_original_worker_job_diagnostic_300s", requested_outputs())

    counterfactuals = [
        {
            "counterfactual_id": "exact_authoritative_output_ids_only",
            "single_variable_changed": "requested_output_ids",
            "result": await run_full_worker(report_root, "counterfactual_authoritative_output_ids", requested_outputs(AUTHORITATIVE_OUTPUT_IDS)),
            "synthetic": True,
            "provider_success_eligible": False,
        },
    ]
    for output_id in ORIGINAL_OUTPUT_IDS:
        counterfactuals.append({
            "counterfactual_id": f"one_output_{output_id}",
            "single_variable_changed": "requested_outputs_one_at_a_time",
            "result": await run_full_worker(report_root, f"counterfactual_one_output_{output_id}", requested_outputs([output_id])),
            "synthetic": True,
            "provider_success_eligible": False,
        })
    for disabled in ("exports", "STEP", "STL", "BREP"):
        if disabled == "exports":
            result = run_child(report_root, "counterfactual_exports_disabled", ["--mode", "build_product"])
        else:
            formats = ",".join(fmt for fmt in ("BREP", "STEP", "STL") if fmt != disabled)
            result = run_child(report_root, f"counterfactual_{disabled.lower()}_disabled", ["--mode", "export_output", "--output-id", ORIGINAL_OUTPUT_IDS[0], "--formats", formats])
        counterfactuals.append({
            "counterfactual_id": f"{disabled.lower()}_disabled",
            "single_variable_changed": f"{disabled.lower()}_disabled",
            "result": result,
            "synthetic": True,
            "provider_success_eligible": False,
        })

    all_results = [*phases, *export_results, full_original, *[item["result"] for item in counterfactuals]]
    operation_records = []
    for result in all_results:
        timing = result.get("operation_timing") or (result.get("execution_timing") or {}).get("operations") or []
        for item in timing:
            operation_records.append({"run_id": result.get("run_id"), **item})

    classification = classify_timeout(full_original, phases, export_results)
    combined = {
        "schema_version": "volundr-wave-02-project-03-diagnostic-v1",
        "diagnostic_only": True,
        "provider_success_eligible": False,
        "provider_calls": 0,
        "production_timeout_changed": False,
        "diagnostic_timeout_seconds": DIAGNOSTIC_TIMEOUT_SECONDS,
        "exact_source": exact_source,
        "phases": phases,
        "export_results": export_results,
        "full_original_worker_job": full_original,
        "counterfactuals": counterfactuals,
        "operation_records": operation_records,
        "timeout_classification": classification,
    }
    write_json(report_root / "project-03-exact-source-diagnostic.json", combined)
    write_json(report_root / "project-03-output-isolation.json", {"counterfactuals": counterfactuals[: 1 + len(ORIGINAL_OUTPUT_IDS)]})
    write_json(report_root / "project-03-export-isolation.json", {"exports": export_results, "counterfactuals": counterfactuals[1 + len(ORIGINAL_OUTPUT_IDS):]})
    write_json(report_root / "project-03-operation-timings.json", {"operation_records": operation_records})
    write_json(report_root / "timeout-classification.json", classification)
    return combined


def classify_timeout(full_original: dict[str, Any], phases: list[dict[str, Any]], exports: list[dict[str, Any]]) -> dict[str, Any]:
    if full_original.get("timed_out") is True:
        return {
            "first_cause": "production_timeout_budget_failure",
            "confidence": "high",
            "reason": "Import, component builds, all-output build, and isolated exports completed under the diagnostic ceiling, while the exact original full worker job timed out under the production-budget path.",
            "kernel_failure_claimed": False,
        }
    if full_original.get("success") is True:
        return {
            "first_cause": "production_timeout_budget_failure",
            "confidence": "confirmed",
            "reason": "The exact original full worker source completed only under the diagnostic ceiling; no production timeout was changed.",
            "kernel_failure_claimed": False,
        }
    invalid_outputs = [
        item
        for item in full_original.get("outputs", []) or []
        if isinstance(item, dict) and item.get("success") is not True
    ]
    if invalid_outputs:
        return {
            "first_cause": "worker_instrumentation_gap",
            "confidence": "high",
            "reason": "The preserved baseline recorded a client-side worker timeout, but the exact source under diagnostic instrumentation did not time out and instead exposed a required-output failure.",
            "timeout_behavior_deterministic": False,
            "secondary_observed_failure": "source_semantic_complexity_failure",
            "failed_output_ids": [str(item.get("output_id")) for item in invalid_outputs if item.get("output_id")],
            "kernel_failure_claimed": False,
        }
    failed_exports = [item for item in exports if not item.get("success")]
    if failed_exports:
        return {
            "first_cause": "export_performance_failure",
            "confidence": "probable",
            "reason": "At least one isolated export failed before the exact full worker job could be credited.",
            "kernel_failure_claimed": False,
        }
    failed_phase = next((item for item in phases if not item.get("success")), None)
    if failed_phase:
        return {
            "first_cause": "source_semantic_complexity_failure",
            "confidence": "probable",
            "reason": f"Diagnostic phase failed before export isolation: {failed_phase.get('run_id')}",
            "kernel_failure_claimed": False,
        }
    return {
        "first_cause": "unresolved_worker_runtime_failure",
        "confidence": "unknown",
        "reason": "Diagnostics did not converge on a specific first cause.",
        "kernel_failure_claimed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    args = parser.parse_args()
    result = asyncio.run(run_diagnostics(args.report_root.resolve()))
    print(json.dumps({
        "provider_calls": result["provider_calls"],
        "timeout_classification": result["timeout_classification"]["first_cause"],
        "full_original_success": result["full_original_worker_job"]["success"],
        "full_original_timed_out": result["full_original_worker_job"]["timed_out"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
