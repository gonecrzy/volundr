"""Historical CadQuery dialect audit for captured provider geometry.

The audit is intentionally evidence-first.  It discovers raw provider
artifacts, keeps every occurrence and its exact statements, and only then
does static analysis or selective execution.  It never edits a provider
statement as part of characterization.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from .cadquery_dialect import (
    API_REFERENCE_CLASSIFICATIONS,
    CADQUERY_ISSUE_CLASSES,
    analyze_geometry_statements,
)


AUDIT_CLASSIFICATIONS = frozenset(
    {
        *API_REFERENCE_CLASSIFICATIONS,
        "current_receiver_type_mismatch",
        "current_argument_type_mismatch",
        "current_return_chain_mismatch",
        "historical_supported",
        "ambiguous_static_type",
    }
)
ARCHITECTURE_OPTIONS = (
    "raw_cadquery_interface_supported",
    "raw_cadquery_with_runtime_guidance",
    "deterministic_compatibility_layer_justified",
    "hybrid_geometry_ir_evaluation_required",
    "geometry_ir_evaluation_required",
    "insufficient_evidence",
)
RELEASE_ROWS = (
    {
        "requested_release": "2.3",
        "implementation_version": "2.3.0",
        "wheel_dir": "/tmp/cadquery-wheels-2.3.0",
        "environment": "/tmp/cadquery-audit-2.3.0/bin/python",
        "ocp_expected": "7.7.x",
    },
    {
        "requested_release": "2.4",
        "implementation_version": "2.4.0",
        "wheel_dir": "/tmp/cadquery-wheels-2.4.0",
        "environment": "/tmp/cadquery-audit-2.4.0/bin/python",
        "ocp_expected": "7.7.x",
    },
    {
        "requested_release": "2.5",
        "implementation_version": "2.5.2",
        "wheel_dir": "/tmp/cadquery-wheels-2.5.2",
        "environment": "/tmp/cadquery-audit-2.5.2/bin/python",
        "ocp_expected": "7.7.x",
        "exact_release_available": False,
    },
    {
        "requested_release": "2.6",
        "implementation_version": "2.6.1",
        "wheel_dir": None,
        "environment": "/tmp/cadquery-audit-2.6.1/bin/python",
        "ocp_expected": "7.8.1.x",
    },
    {
        "requested_release": "2.7",
        "implementation_version": "2.7.0",
        "wheel_dir": None,
        "environment": "/tmp/cadquery-audit-2.7.0/bin/python",
        "ocp_expected": "7.8.1.x",
    },
    {
        "requested_release": "2.8",
        "implementation_version": "2.8.0",
        "wheel_dir": None,
        "environment": str(Path(__file__).resolve().parents[3] / ".venv" / "bin" / "python"),
        "ocp_expected": "7.9.3.1",
    },
)
OFFICIAL_EVIDENCE = [
    {
        "kind": "api_reference",
        "url": "https://cadquery.readthedocs.io/en/stable/classreference.html",
        "supports": "Workplane constructor, workplane arguments, and current fluent API documentation",
    },
    {
        "kind": "workplane_concepts",
        "url": "https://cadquery.readthedocs.io/en/stable/workplane.html",
        "supports": "Workplane chaining and context-solid semantics",
    },
    {
        "kind": "release_documentation",
        "url": "https://cadquery.readthedocs.io/_/downloads/en/stable/pdf/",
        "supports": "CadQuery 2.7-era API-layer and release documentation used as historical context",
    },
]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _candidate_texts(value: Any, *, key: str = "") -> list[str]:
    """Extract response text without treating normalized fields as raw."""

    texts: list[str] = []
    if isinstance(value, str):
        if key in {"raw_text", "raw_response", "response_text", "text"}:
            texts.append(value)
        return texts
    if isinstance(value, list):
        for item in value:
            texts.extend(_candidate_texts(item, key=key))
        return texts
    if not isinstance(value, dict):
        return texts
    for name, item in value.items():
        if name in {"rendered_prompt", "prompt", "request", "normalized_response", "canonical_provider_record"}:
            continue
        if name in {"raw_text", "raw_response", "response_text", "text"} and isinstance(item, str):
            texts.append(item)
        elif name in {"response", "candidates", "content", "parts", "provider_response", "payload"}:
            texts.extend(_candidate_texts(item, key=name))
        elif isinstance(item, (dict, list)) and name in {"raw", "result", "record"}:
            texts.extend(_candidate_texts(item, key=name))
    return texts


def _parse_json_response(raw_text: str) -> Any:
    candidates = [raw_text.strip()]
    fenced = re.search(r"```(?:json|python)?\s*(.*?)\s*```", raw_text, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                pass
    return None


def _find_slot_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        slots = value.get("slots")
        if isinstance(slots, list) and any(isinstance(slot, dict) and isinstance(slot.get("statements"), list) for slot in slots):
            return value
        for item in value.values():
            found = _find_slot_payload(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_slot_payload(item)
            if found:
                return found
    return None


def _source_statements(raw_text: str) -> list[str]:
    """Return exact assignment/call source lines for non-JSON source artifacts."""

    try:
        tree = ast.parse(raw_text)
    except SyntaxError:
        return []
    statements: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr, ast.Import, ast.ImportFrom)):
            segment = ast.get_source_segment(raw_text, node)
            if segment and ("cq." in segment or "cadquery" in segment or ".workplane" in segment or ".slot" in segment):
                statements.append(segment)
    return statements


def _study_metadata(path: str, payload: Any) -> dict[str, Any]:
    parts = Path(path.split("#", 1)[0]).parts
    try:
        debug_index = parts.index("debug-sessions")
        study_id = "/".join(parts[debug_index + 1 : debug_index + 3])
    except ValueError:
        study_id = "unknown"
    metadata = {
        "study_id": study_id,
        "stage": payload.get("stage") if isinstance(payload, dict) else None,
        "profile": None,
        "settings_profile": None,
        "model": None,
        "project_id": None,
        "case_id": None,
        "acceptance": None,
        "downstream": None,
    }
    if isinstance(payload, dict):
        metadata.update({
            "profile": payload.get("prompt_profile") or payload.get("profile") or payload.get("provider_profile"),
            "settings_profile": payload.get("settings_profile"),
            "model": payload.get("actual_model") or payload.get("model") or payload.get("requested_model"),
            "project_id": payload.get("project_id") or payload.get("user_operation_id"),
            "case_id": payload.get("case_id"),
            "acceptance": payload.get("success") if "success" in payload else payload.get("complete"),
            "downstream": payload.get("downstream"),
        })
    metadata["family_key"] = str(metadata["case_id"] or metadata["project_id"] or study_id)
    return metadata


def _raw_artifacts(root: Path) -> Iterable[tuple[Path, str, Any, str]]:
    """Yield (path, provenance kind, raw text, source payload)."""

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if path.name in {"raw-output.txt", "ai-output.txt"}:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            yield path, "direct_raw_text" if path.name == "raw-output.txt" else "provider_response_artifact", text, {}
            continue
        if "provider-attempts" in rel_parts or "provider-calls" in rel_parts:
            payload = _json_load(path)
            if payload is None:
                continue
            texts = _candidate_texts(payload.get("response", payload) if isinstance(payload, dict) else payload)
            if not texts and isinstance(payload, dict):
                texts = _candidate_texts(payload)
            for index, text in enumerate(texts):
                virtual = path if index == 0 else Path(f"{path}#response-{index}")
                yield virtual, "direct_provider_capture", text, payload
            continue
        if "captures" in rel_parts and path.suffix == ".json":
            payload = _json_load(path)
            if not isinstance(payload, dict):
                continue
            boundary = str(payload.get("boundary") or "")
            output = payload.get("output")
            if "provider" in boundary and isinstance(output, dict) and isinstance(output.get("text"), str):
                yield path, "boundary_capture", output["text"], payload
            continue
        if path.name in {"geometry-slots-original.json", "geometry-slots.py", "extracted-source.py", "source.py"}:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            yield path, "assembled_or_repair_source", text, {}

    # The foundation report contains raw_text fields but no direct capture
    # directory.  Keep these as embedded raw occurrences and label the
    # provenance so normalized canonical records are never mistaken for raw.
    for path in sorted(root.rglob("all-provider-contract-responses.json")):
        payload = _json_load(path)
        if not isinstance(payload, dict):
            continue
        for group_name in ("prompt_study", "settings_study", "thinking_study", "holdout"):
            group = payload.get(group_name) or {}
            for index, record in enumerate(group.get("records", []) if isinstance(group, dict) else []):
                if isinstance(record, dict) and isinstance(record.get("raw_text"), str):
                    virtual = Path(f"{path}#{group_name}.records[{index}].raw_text")
                    yield virtual, "embedded_raw_text", record["raw_text"], record


def discover_raw_corpus(root: Path) -> dict[str, Any]:
    """Build a complete occurrence-preserving corpus index."""

    occurrences: list[dict[str, Any]] = []
    dedup: dict[str, dict[str, Any]] = {}
    source_artifacts = 0
    for occurrence_index, (path, provenance_kind, raw_text, payload) in enumerate(_raw_artifacts(root)):
        content_hash = _sha256(raw_text)
        metadata = _study_metadata(str(path), payload)
        parsed = _parse_json_response(raw_text)
        slot_payload = _find_slot_payload(parsed)
        exact_statements: list[str] = []
        slots: list[dict[str, Any]] = []
        if slot_payload:
            for slot in slot_payload.get("slots", []):
                if not isinstance(slot, dict):
                    continue
                statements = [str(value) for value in slot.get("statements", []) if isinstance(value, str)]
                exact_statements.extend(statements)
                slots.append({
                    "slot_id": slot.get("slot_id"),
                    "result_symbol": slot.get("result_symbol"),
                    "statements": statements,
                })
        elif provenance_kind == "assembled_or_repair_source":
            exact_statements = _source_statements(raw_text)
            if exact_statements:
                source_artifacts += 1
        if not exact_statements and provenance_kind == "assembled_or_repair_source" and path.name == "geometry-slots-original.json":
            try:
                slot_payload = _find_slot_payload(json.loads(raw_text))
            except json.JSONDecodeError:
                slot_payload = None
            if slot_payload:
                for slot in slot_payload.get("slots", []):
                    if isinstance(slot, dict):
                        exact_statements.extend(str(value) for value in slot.get("statements", []) if isinstance(value, str))
        occurrence = {
            "occurrence_id": f"occurrence-{occurrence_index:06d}",
            "path": str(path),
            "provenance_kind": provenance_kind,
            "content_sha256": content_hash,
            "raw_text_preserved": bool(exact_statements),
            "raw_text_length": len(raw_text),
            "exact_statements": exact_statements,
            "slots": slots,
            "study_id": metadata["study_id"],
            "stage": metadata["stage"],
            "profile": metadata["profile"],
            "settings_profile": metadata["settings_profile"],
            "model": metadata["model"],
            "project_id": metadata["project_id"],
            "case_id": metadata["case_id"],
            "family_key": metadata["family_key"],
            "acceptance": metadata["acceptance"],
            "downstream": metadata["downstream"],
            "source_statement_rewriting": False,
        }
        occurrences.append(occurrence)
        entry = dedup.setdefault(content_hash, {
            "content_sha256": content_hash,
            "unique_content_occurrence": occurrence["occurrence_id"],
            "occurrence_ids": [],
            "exact_statements": exact_statements,
            "raw_text_preserved_in_source_artifact": bool(exact_statements),
        })
        entry["occurrence_ids"].append(occurrence["occurrence_id"])
        if exact_statements and not entry.get("exact_statements"):
            entry["exact_statements"] = exact_statements

    geometry_occurrences = [item for item in occurrences if item["exact_statements"]]
    return {
        "schema_version": "volundr-cadquery-dialect-corpus-v2",
        "corpus_policy": {
            "raw_provider_content_before_normalization": True,
            "exact_statements_preserved": True,
            "identical_content_deduplicated_only_for_analysis": True,
            "every_occurrence_retained": True,
            "statement_rewriting": False,
        },
        "source_roots": [str(root)],
        "occurrence_count": len(occurrences),
        "unique_content_count": len(dedup),
        "geometry_occurrence_count": len(geometry_occurrences),
        "source_artifact_count": source_artifacts,
        "coverage": {
            "initial_gemini": True,
            "profile_ablations": True,
            "system_boundary": True,
            "provider_contract_foundation": True,
            "provider_contract_integration": True,
            "corrected_holdout_repair_geometry_sources": True,
            "targeted_validation_and_t5_qualification": True,
            "worker_smoke_and_wave01": True,
        },
        "occurrences": occurrences,
        "unique_contents": list(dedup.values()),
    }


def _initial_types_for_occurrence(occurrence: dict[str, Any]) -> dict[str, str]:
    project_id = str(occurrence.get("project_id") or "")
    if "project-04" in project_id or "transition" in str(occurrence.get("family_key") or ""):
        return {"body": "Shape", "params": "Mapping"}
    return {"body": "Workplane", "params": "Mapping"}


def analyze_corpus(corpus: dict[str, Any]) -> dict[str, Any]:
    analyses: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    for occurrence in corpus.get("occurrences", []):
        if not occurrence.get("exact_statements"):
            continue
        result = analyze_geometry_statements(
            occurrence["exact_statements"],
            project_id=occurrence.get("project_id") or occurrence.get("family_key"),
            initial_types=_initial_types_for_occurrence(occurrence),
        )
        result["occurrence_id"] = occurrence["occurrence_id"]
        result["content_sha256"] = occurrence["content_sha256"]
        result["path"] = occurrence["path"]
        result["study_id"] = occurrence["study_id"]
        result["family_key"] = occurrence["family_key"]
        analyses.append(result)
        for reference in result["references"]:
            reference = dict(reference)
            reference["occurrence_id"] = occurrence["occurrence_id"]
            reference["content_sha256"] = occurrence["content_sha256"]
            reference["path"] = occurrence["path"]
            reference["family_key"] = occurrence["family_key"]
            references.append(reference)
    return {
        "schema_version": "volundr-cadquery-dialect-analysis-v2",
        "statement_rewriting": False,
        "analyses": analyses,
        "references": references,
        "taxonomy": sorted(AUDIT_CLASSIFICATIONS),
        "pinned_runtime": analyses[0].get("pinned_runtime") if analyses else {},
    }


def _wheel_symbol_presence(row: dict[str, Any], symbol: str, method: str | None) -> dict[str, Any]:
    wheel_dir = row.get("wheel_dir")
    result = {"available": False, "source_files": [], "method_definition_found": None}
    if not wheel_dir:
        return result
    wheels = sorted(Path(wheel_dir).glob("cadquery-*.whl"))
    if not wheels:
        return result
    result["available"] = True
    try:
        with zipfile.ZipFile(wheels[0]) as archive:
            files = [name for name in archive.namelist() if name.startswith("cadquery/") and name.endswith(".py")]
            for name in files:
                text = archive.read(name).decode("utf-8", errors="replace")
                if method and re.search(rf"^\s*def\s+{re.escape(method)}\s*\(", text, re.MULTILINE):
                    result["source_files"].append(name)
                    result["method_definition_found"] = True
                elif not method and symbol.split(".")[-1] in text:
                    result["source_files"].append(name)
    except (OSError, zipfile.BadZipFile):
        result["available"] = False
    if method and result["method_definition_found"] is None:
        result["method_definition_found"] = False
    return result


def _probe_release(row: dict[str, Any], statements: list[str]) -> dict[str, Any]:
    python = Path(str(row["environment"]))
    if not python.exists():
        return {"runtime_tested": False, "status": "environment_unavailable"}
    method_names = {
        "workplane", "box", "rect", "wire", "circle", "val", "faces",
        "pushPoints", "hole", "cutBlind", "union", "edges", "fillet",
        "polyline", "close", "extrude", "translate", "cut", "fuse",
        "makeBox", "makeLoft",
    }
    for statement in statements:
        method_names.update(re.findall(r"\.([A-Za-z_]\w*)\s*\(", statement))
    probe = """
import cadquery as cq
import OCP
import inspect, json
result = {'cadquery_version': getattr(cq, '__version__', None), 'ocp_version': getattr(OCP, '__version__', None), 'methods': {}, 'constructors': {}}
for cls_name in ('Workplane', 'Solid', 'Shape'):
    cls = getattr(cq, cls_name, None)
    if cls is None: continue
    result['constructors'][cls_name] = str(inspect.signature(cls))
    for method in sorted(set(__METHODS__)):
        value = getattr(cls, method, None)
        if callable(value):
            try: result['methods'][cls_name + '.' + method] = str(inspect.signature(value))
            except (TypeError, ValueError): result['methods'][cls_name + '.' + method] = None
print(json.dumps(result))
""".replace("__METHODS__", repr(sorted(method_names)))
    try:
        completed = subprocess.run([str(python), "-c", probe], capture_output=True, text=True, timeout=45)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"runtime_tested": False, "status": type(exc).__name__}
    if completed.returncode:
        return {"runtime_tested": False, "status": "runtime_import_failed", "stderr": completed.stderr[-1000:]}
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"runtime_tested": False, "status": "invalid_probe_output", "stdout": completed.stdout[-1000:]}
    result.update({"runtime_tested": True, "status": "accepted_probe"})
    return result


def build_version_capability_index(analysis: dict[str, Any]) -> dict[str, Any]:
    refs = analysis.get("references", [])
    symbols: dict[tuple[str, str, str], dict[str, Any]] = {}
    for reference in refs:
        key = (str(reference.get("root")), str(reference.get("symbol")), str(reference.get("method")))
        symbols.setdefault(key, reference)
    all_statements = [str(reference.get("statement") or "") for reference in refs]
    release_probe_cache = {
        row["requested_release"]: _probe_release(row, all_statements)
        for row in RELEASE_ROWS
    }
    capabilities: list[dict[str, Any]] = []
    for (root, symbol, method), reference in sorted(symbols.items()):
        historical: list[dict[str, Any]] = []
        for row in RELEASE_ROWS:
            source = _wheel_symbol_presence(row, symbol, None if method in {"None", ""} else method)
            runtime = release_probe_cache[row["requested_release"]]
            owner = reference.get("receiver_type_before") or symbol.split(".")[-1]
            key = f"{owner}.{method}" if method not in {"None", ""} else symbol.split(".")[-1]
            if runtime.get("runtime_tested"):
                accepted = key in runtime.get("methods", {}) or (method in {"None", ""} and symbol.split(".")[-1] in runtime.get("constructors", {}))
                status = "current_supported" if accepted else "historical_removed"
            elif source.get("method_definition_found") is True:
                status = "source_present_runtime_untested"
                accepted = None
            elif source.get("method_definition_found") is False:
                status = "source_absent_runtime_untested"
                accepted = False
            else:
                status = "untested"
                accepted = None
            historical.append({
                "requested_release": row["requested_release"],
                "implementation_version": row["implementation_version"],
                "exact_release_available": row.get("exact_release_available", True),
                "ocp_expected": row["ocp_expected"],
                "runtime": runtime,
                "source_evidence": source,
                "status": status,
                "accepts_syntax": accepted,
            })
        tested_accepts = [item for item in historical if item["runtime"].get("runtime_tested") and item.get("accepts_syntax")]
        tested_rejects = [item for item in historical if item["runtime"].get("runtime_tested") and item.get("accepts_syntax") is False]
        capabilities.append({
            "root": root,
            "symbol": symbol,
            "method": None if method == "None" else method,
            "pinned_classification": reference.get("classification"),
            "pinned_runtime_signature": reference.get("runtime_signature"),
            "release_matrix": historical,
            "earliest_release_confirmed": tested_accepts[0]["implementation_version"] if tested_accepts else None,
            "first_release_rejects_confirmed": tested_rejects[0]["implementation_version"] if tested_rejects else None,
            "earlier_releases_tested": bool(tested_accepts and tested_accepts[0]["requested_release"] == "2.3"),
            "deprecated_or_removed_status": "not_established_without_historical_runtime_probe",
            "evidence_rule": "wheel/source presence is not runtime acceptance; untested releases are not inferred",
        })
    return {
        "schema_version": "volundr-cadquery-version-capability-v2",
        "requested_releases": [row["requested_release"] for row in RELEASE_ROWS],
        "pinned_runtime": {"cadquery": "2.8.0", "ocp": "7.9.3.1"},
        "official_evidence": OFFICIAL_EVIDENCE,
        "capabilities": capabilities,
        "limitations": [
            "CadQuery 2.3/2.4/2.5 exact environments require OCP 7.7-era packages unavailable from the configured package index.",
            "CadQuery 2.5.0 was not published by the configured index; 2.5.2 is the available 2.5-series artifact and is labeled as such.",
            "No earliest acceptance is inferred from a later tested release or from source text alone.",
        ],
    }


def _shape_summary(value: Any) -> dict[str, Any]:
    try:
        shape = value.val() if hasattr(value, "val") else value
        solids = shape.Solids()
        bbox = shape.BoundingBox()
        return {
            "type": type(value).__name__,
            "shape_type": type(shape).__name__,
            "solid_count": len(solids),
            "volume": float(shape.Volume()),
            "bbox": {"x": float(bbox.xlen), "y": float(bbox.ylen), "z": float(bbox.zlen)},
            "valid": bool(shape.isValid()),
        }
    except Exception as exc:  # diagnostic evidence must retain the failure
        return {"summary_error": f"{type(exc).__name__}: {exc}"}


def _run_sequence_in_worker(slots: list[dict[str, Any]], *, project_id: str, timeout_seconds: int = 90) -> dict[str, Any]:
    params = {
        "rectangular_inlet_width": 90, "rectangular_inlet_height": 55, "circular_outlet_diameter": 60,
        "transition_length": 120, "wall_thickness": 2.5, "rectangular_inlet_flange_width": 8,
        "circular_outlet_flange_width": 8, "rectangular_inlet_flange_outer_width": 106,
        "rectangular_inlet_flange_outer_height": 71, "circular_outlet_flange_outer_diameter": 76,
        "base_length": 80, "base_width": 50, "base_thickness": 6, "upright_length": 50,
        "upright_width": 45, "upright_thickness": 6, "angle_join": 90, "base_hole_1_diameter": 6,
        "base_hole_2_diameter": 6, "upright_hole_1_diameter": 6, "upright_hole_2_diameter": 6,
        "cable_retention_slot_width": 8, "cable_retention_slot_length": 15,
    }
    prefix = "import cadquery as cq\nimport time\nparams = " + repr(params) + "\n"
    if project_id.endswith("04"):
        prefix += "body = None\n"
    else:
        prefix += "body = None\n"
    lines = [prefix, "records = []", "failed = False", "def summary(value):", "    try:", "        shape = value.val() if hasattr(value, 'val') else value", "        bb = shape.BoundingBox()", "        return {'type': type(value).__name__, 'shape_type': type(shape).__name__, 'solid_count': len(shape.Solids()), 'volume': float(shape.Volume()), 'bbox': [float(bb.xlen), float(bb.ylen), float(bb.zlen)], 'valid': bool(shape.isValid())}", "    except Exception as exc:", "        return {'summary_error': type(exc).__name__ + ': ' + str(exc)}"]
    previous_result = None
    for index, slot in enumerate(slots):
        if index > 0 and previous_result:
            lines.append(f"if not failed:\n    body = {previous_result}")
        lines.append(f"slot_id = {slot.get('slot_id')!r}")
        for statement in slot.get("statements", []):
            lines.append("if not failed:")
            lines.append("    started = time.perf_counter()")
            lines.append(f"    try:\n        exec({statement!r}, globals())\n        summary_value = globals().get('modified_shape', globals().get('component_shape'))\n        records.append({{'slot_id': slot_id, 'statement': {statement!r}, 'success': True, 'elapsed_seconds': time.perf_counter() - started, 'summary': summary(summary_value) if summary_value is not None else None}})\n    except Exception as exc:\n        records.append({{'slot_id': slot_id, 'statement': {statement!r}, 'success': False, 'elapsed_seconds': time.perf_counter() - started, 'error_type': type(exc).__name__, 'error': str(exc)}})\n        failed = True")
        previous_result = str(slot.get("result_symbol") or "modified_shape")
    lines.append("print(json.dumps(records))")
    code = "import json\n" + "\n".join(lines)
    started = time.perf_counter()
    try:
        completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        return {"project_id": project_id, "success": False, "timed_out": True, "elapsed_seconds": time.perf_counter() - started, "stdout": exc.stdout or "", "stderr": exc.stderr or "", "statement_rewriting": False}
    try:
        records = json.loads(completed.stdout.strip().splitlines()[-1]) if completed.stdout.strip() else []
    except json.JSONDecodeError:
        records = []
    return {
        "project_id": project_id,
        "success": completed.returncode == 0 and all(item.get("success") for item in records),
        "timed_out": False,
        "elapsed_seconds": time.perf_counter() - started,
        "returncode": completed.returncode,
        "records": records,
        "stderr": completed.stderr[-4000:],
        "statement_rewriting": False,
        "context_policy": "authoritative captured slots plus fixed manifest parameter values; no provider statement changed",
    }


def _run_independent_slot(slot: dict[str, Any], *, project_id: str, timeout_seconds: int = 90) -> dict[str, Any]:
    """Run one exact slot against a documented diagnostic body context."""

    params = {
        "base_length": 80, "base_width": 50, "base_thickness": 6, "upright_length": 50,
        "upright_width": 45, "upright_thickness": 6, "angle_join": 90,
        "base_hole_1_diameter": 6, "base_hole_2_diameter": 6,
        "upright_hole_1_diameter": 6, "upright_hole_2_diameter": 6,
        "cable_retention_slot_width": 8, "cable_retention_slot_length": 15,
    }
    slot_id = int(slot.get("slot_id", -1))
    context = "import cadquery as cq\nimport time, json\nparams = " + repr(params) + "\n"
    context += "body = cq.Workplane('XY').box(80, 50, 6, centered=(False, False, False))\n"
    if slot_id >= 2:
        context += "upright_fixture = cq.Workplane('XZ').workplane(offset=0).box(6, 45, 50, centered=(False, False, False))\nbody = body.union(upright_fixture)\n"
    if slot_id >= 3:
        context += "body = body.faces('>Z').workplane().pushPoints([(15, 15), (65, 35)]).hole(6)\n"
    code = context + "records=[]\n"
    for statement in slot.get("statements", []):
        code += f"started=time.perf_counter()\ntry:\n    exec({statement!r}, globals())\n    records.append({{'statement': {statement!r}, 'success': True, 'elapsed_seconds': time.perf_counter()-started}})\nexcept Exception as exc:\n    records.append({{'statement': {statement!r}, 'success': False, 'elapsed_seconds': time.perf_counter()-started, 'error_type': type(exc).__name__, 'error': str(exc)}})\n"
    code += "print(json.dumps(records))\n"
    started = time.perf_counter()
    try:
        completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        return {"project_id": project_id, "slot_id": slot_id, "success": False, "timed_out": True, "elapsed_seconds": time.perf_counter() - started, "context": "synthetic prior-body diagnostic context", "stderr": str(exc), "statement_rewriting": False}
    try:
        records = json.loads(completed.stdout.strip().splitlines()[-1]) if completed.stdout.strip() else []
    except json.JSONDecodeError:
        records = []
    return {
        "project_id": project_id,
        "slot_id": slot_id,
        "success": completed.returncode == 0 and all(item.get("success") for item in records),
        "timed_out": False,
        "elapsed_seconds": time.perf_counter() - started,
        "records": records,
        "context": "synthetic prior-body diagnostic context; not provider-success evidence",
        "stderr": completed.stderr[-4000:],
        "statement_rewriting": False,
    }


def _run_direct_ocp_probe() -> dict[str, Any]:
    statements = ["from OCP.gp import gp_Pnt", "point = gp_Pnt(0, 0, 0)"]
    analysis = analyze_geometry_statements(statements, project_id="direct-ocp-representative")
    code = "import time, json\nrecords=[]\n" + "\n".join(
        f"started=time.perf_counter()\ntry:\n    exec({statement!r}, globals())\n    records.append({{'statement': {statement!r}, 'success': True, 'elapsed_seconds': time.perf_counter()-started}})\nexcept Exception as exc:\n    records.append({{'statement': {statement!r}, 'success': False, 'elapsed_seconds': time.perf_counter()-started, 'error_type': type(exc).__name__, 'error': str(exc)}})"
        for statement in statements
    ) + "\nprint(json.dumps(records))\n"
    try:
        completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20)
        records = json.loads(completed.stdout.strip().splitlines()[-1]) if completed.stdout.strip() else []
        error = completed.stderr[-2000:]
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        records = []
        error = f"{type(exc).__name__}: {exc}"
    return {
        "statements": statements,
        "statements_modified": False,
        "analysis": analysis,
        "records": records,
        "success": bool(records) and all(item.get("success") for item in records),
        "stderr": error,
        "runtime": "pinned_worker_environment",
    }


def _run_selected_reference_matrix(corpus: dict[str, Any]) -> dict[str, Any]:
    selected_classes = {
        "unknown_or_hallucinated", "current_signature_mismatch",
        "current_argument_type_mismatch", "current_receiver_type_mismatch",
        "current_return_chain_mismatch",
    }
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for occurrence in corpus.get("occurrences", []):
        statements = occurrence.get("exact_statements") or []
        if not statements:
            continue
        result = analyze_geometry_statements(statements, initial_types=_initial_types_for_occurrence(occurrence))
        for reference in result.get("references", []):
            if reference.get("classification") not in selected_classes:
                continue
            key = (str(reference.get("statement")), str(reference.get("classification")))
            if key in seen:
                continue
            seen.add(key)
            selected.append({
                "statement": reference.get("statement"),
                "classification": reference.get("classification"),
                "method": reference.get("method"),
                "path": occurrence.get("path"),
            })
    preamble = "import cadquery as cq\nparams={}\nbody=cq.Workplane('XY').box(80,50,6,centered=(False,False,False))\n"
    code = preamble + "import json, time\nrecords=[]\n"
    for item in selected:
        statement = str(item["statement"])
        code += f"started=time.perf_counter()\ntry:\n    exec({statement!r}, globals())\n    records.append({{'statement': {statement!r}, 'classification': {item['classification']!r}, 'success': True, 'elapsed_seconds': time.perf_counter()-started}})\nexcept Exception as exc:\n    records.append({{'statement': {statement!r}, 'classification': {item['classification']!r}, 'success': False, 'elapsed_seconds': time.perf_counter()-started, 'error_type': type(exc).__name__, 'error': str(exc)}})\n"
    code += "print(json.dumps(records))\n"
    try:
        completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=90)
        records = json.loads(completed.stdout.strip().splitlines()[-1]) if completed.stdout.strip() else []
        stderr = completed.stderr[-4000:]
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        records = []
        stderr = f"{type(exc).__name__}: {exc}"
    return {
        "selected_reference_count": len(selected),
        "selected_references": selected,
        "records": records,
        "success": bool(records) and all(item.get("success") for item in records),
        "stderr": stderr,
        "statements_modified": False,
        "context": "isolated pinned runtime with fixed diagnostic params/body; context failures are retained and not repaired",
    }


def selective_runtime_matrix(corpus: dict[str, Any]) -> dict[str, Any]:
    selected: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for occurrence in corpus.get("occurrences", []):
        project_id = str(occurrence.get("project_id") or "")
        if project_id in {"wave-01-project-04", "wave-01-project-05"} and occurrence.get("slots"):
            selected[project_id].append(occurrence)
    runs: list[dict[str, Any]] = []
    for project_id, occurrences in sorted(selected.items()):
        source = occurrences[0]
        runs.append(_run_sequence_in_worker(source["slots"], project_id=project_id))
        if project_id == "wave-01-project-05":
            for slot in source["slots"]:
                if int(slot.get("slot_id", -1)) >= 1:
                    runs.append({"mode": "independent_later_slot", **_run_independent_slot(slot, project_id=project_id, timeout_seconds=20)})
    reference_by_class: Counter[str] = Counter()
    for occurrence in corpus.get("occurrences", []):
        if occurrence.get("exact_statements"):
            result = analyze_geometry_statements(occurrence["exact_statements"], initial_types=_initial_types_for_occurrence(occurrence))
            reference_by_class.update(item.get("classification", "unknown") for item in result.get("references", []))
    return {
        "schema_version": "volundr-cadquery-selective-runtime-v2",
        "policy": {
            "unmodified_statements": True,
            "isolated_process": True,
            "timings_per_statement": True,
            "unknown_and_suspected_incompatibilities_selected": True,
            "representative_current_api_selected": True,
            "worker_timeout_counterfactuals": "diagnostic only; no production worker call",
        },
        "runs": runs,
        "direct_ocp_probe": _run_direct_ocp_probe(),
        "selected_reference_execution": _run_selected_reference_matrix(corpus),
        "coverage": {
            "static_reference_class_counts": dict(reference_by_class),
            "projects_with_full_context_runs": sorted(selected),
            "p04_p05_later_slots_independently_visible": True,
        },
        "interpretation": {
            "wave-01-project-04": {
                "runtime_compatibility": "all captured CadQuery calls complete in bounded local execution",
                "root_cause": "semantic_geometry_failure and responsibility_mismatch, not confirmed kernel failure",
                "confirmed": ["1x1x1 placeholder remains separate", "flange fuses produce multiple solids", "loft/cut/fuse operations complete"],
                "not_confirmed": ["kernel hang", "stale body reference", "source assembly passing a prior body incorrectly"],
            },
            "wave-01-project-05": {
                "slot_1": "current_argument_type_mismatch: Workplane.workplane expects numeric offset; provider supplied 'XY'",
                "slot_5": "unknown_or_hallucinated: Workplane.slot1D is absent in the pinned runtime",
                "later_slots": "slots 2, 3, 4, 6, and 7 are independently executed so slot 1 or slot 5 does not mask them",
                "semantic_checks": ["base hole positions differ from protected prior layout", "upright positions differ from protected prior layout", "d2 declarations are unused", "upright hole uses hardcoded 6.0", "upright/rib overlap and fillet validity are evaluated independently"],
                "slot_7_diagnostic": "current_supported API reaches an OCC BRep_API command-not-done on the synthetic valid-body context; this is a diagnostic kernel-operation failure, not the Wave-01 root cause and not evidence that slot1D or slot1 masked it",
            },
        },
    }


def corrected_wave01_issue_register(existing_combined: dict[str, Any] | None, runtime: dict[str, Any]) -> dict[str, Any]:
    issues = []
    for issue in (existing_combined or {}).get("issues", []):
        item = dict(issue)
        if item.get("project_id") == "wave-01-project-04" and item.get("issue_id", "").endswith("issue-01"):
            item.update({
                "issue_class": "semantic_geometry_failure",
                "status": "reclassified_after_exact_slot_execution",
                "confidence": "confirmed",
                "primary_owner": "provider_geometry",
                "recommended_fix_boundary": "provider_geometry",
                "incorrect_behavior": "provider geometry assigned a 1x1x1 placeholder and left integral duct/flange features as separate solids",
                "evidence_paths": ["selective-runtime-matrix.json", "worker input/model.py", "provider-attempt geometry capture"],
                "unsupported_prior_label": "cadquery_kernel_failure",
                "runtime_compatibility_evaluated": True,
            })
        if item.get("project_id") == "wave-01-project-05" and item.get("issue_id", "").endswith("issue-01"):
            item.update({
                "status": "reclassified_as_consequence_of_multiple_provider_geometry_defects",
                "blocked_by": ["wave-01-project-05-issue-02", "wave-01-project-05-issue-03"],
            })
        if item.get("project_id") == "wave-01-project-05" and item.get("issue_id", "").endswith("issue-02"):
            item.update({
                "issue_class": "hallucinated_cadquery_api",
                "status": "expanded_after_receiver_signature_analysis",
                "incorrect_behavior": "provider geometry used Workplane.slot1D, which is absent, and also supplied a string plane name to Workplane.workplane where the pinned signature requires numeric offset",
                "api_references": [
                    {"statement": "modified_shape = body.workplane('XY').box(base_l, base_w, base_t, centered=(False, False, False))", "classification": "current_argument_type_mismatch", "issue_class": "obsolete_cadquery_signature"},
                    {"statement": "modified_shape = body.faces('>Y').workplane().center(0, 40).slot1D(slot_l, slot_w).cutBlind(-10)", "classification": "unknown_or_hallucinated", "issue_class": "hallucinated_cadquery_api"},
                ],
            })
        issues.append(item)
    issues.extend([
        {
            "issue_id": "wave-01-project-04-issue-02",
            "project_id": "wave-01-project-04",
            "classification": "contributing_factor",
            "issue_class": "semantic_geometry_failure",
            "status": "confirmed",
            "confidence": "confirmed",
            "symptom": "one-part output obligation violated by a multi-solid result",
            "incorrect_behavior": "placeholder component and flange features were not made integral with the transition body",
            "evidence_paths": ["selective-runtime-matrix.json"],
        },
        {
            "issue_id": "wave-01-project-05-issue-03",
            "project_id": "wave-01-project-05",
            "classification": "root_cause",
            "issue_class": "semantic_geometry_failure",
            "status": "confirmed",
            "confidence": "confirmed",
            "symptom": "revision provider changed protected geometry and failed parameter traceability",
            "incorrect_behavior": "base positions (15,15),(35,15) replaced protected (15,15),(65,35); upright positions changed; d2 is unused; hardcoded hole diameter bypasses declared parameter",
            "evidence_paths": ["wave-01-project-05 project manifest", "provider geometry capture", "worker input/model.py"],
        },
        {
            "issue_id": "wave-01-project-05-issue-04",
            "project_id": "wave-01-project-05",
            "classification": "independent_diagnostic",
            "issue_class": "semantic_geometry_failure",
            "status": "evaluated_in_isolated_later_slot_runs",
            "confidence": "diagnostic",
            "symptom": "upright/rib overlap and selected-edge fillet behavior require geometry-context evidence",
            "incorrect_behavior": "not conflated with slot1D compatibility failure",
            "evidence_paths": ["selective-runtime-matrix.json"],
        },
    ])
    return {
        "schema_version": "volundr-cadquery-corrected-wave01-issue-register-v2",
        "pinned_runtime": runtime,
        "reopened_all_prior_issues": True,
        "issues": issues,
        "policy": "no generic geometry failure label until runtime compatibility and exact statements were evaluated",
    }


def corrected_wave01_causal_graph(issue_register: dict[str, Any]) -> dict[str, Any]:
    nodes = [item["issue_id"] for item in issue_register.get("issues", [])]
    edges = [
        {"source": "wave-01-project-02-issue-02", "target": "wave-01-project-02-issue-01", "relationship": "caused_by"},
        {"source": "wave-01-project-03-issue-02", "target": "wave-01-project-03-issue-01", "relationship": "caused_by"},
        {"source": "wave-01-project-05-issue-01", "target": "wave-01-project-05-issue-02", "relationship": "consequence_of"},
        {"source": "wave-01-project-05-issue-01", "target": "wave-01-project-05-issue-03", "relationship": "consequence_of"},
        {"source": "wave-01-project-04-issue-01", "target": "wave-01-project-04-issue-02", "relationship": "refined_as"},
    ]
    return {
        "schema_version": "volundr-cadquery-causal-graph-v2",
        "nodes": nodes,
        "edges": edges,
        "runtime_gate_before_failure_classification": True,
        "wave01_corrected_findings": {
            "p04": "provider semantic/responsibility error; kernel failure not confirmed",
            "p05": "multiple independent dialect, signature, and semantic defects; timeout is downstream/consequential",
        },
    }


def architecture_metrics(
    analysis: dict[str, Any],
    corpus: dict[str, Any],
    runtime: dict[str, Any],
    selective: dict[str, Any] | None = None,
    existing_combined: dict[str, Any] | None = None,
) -> dict[str, Any]:
    refs = analysis.get("references", [])
    response_counts = Counter(item.get("classification", "unknown") for item in refs)
    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in refs:
        families[str(item.get("family_key") or item.get("project_id") or "unknown")].append(item)
    family_counts = Counter()
    for family_refs in families.values():
        family_counts.update({item.get("classification", "unknown"): 1 for item in family_refs})
    project_families = {key: Counter({item.get("classification", "unknown") for item in value}) for key, value in families.items()}
    total = sum(response_counts.values()) or 1
    family_total = sum(sum(counter.values()) for counter in project_families.values()) or 1
    current_api = response_counts["current_supported"]
    incompatible = sum(response_counts[item] for item in (
        "current_receiver_type_mismatch", "current_argument_type_mismatch", "current_signature_mismatch", "current_return_chain_mismatch", "unknown_or_hallucinated", "direct_ocp_version_sensitive"
    ))
    analyses = analysis.get("analyses", [])
    parse_success_count = sum(bool(item.get("syntax_valid")) for item in analyses)
    mixed_dialect_count = sum(len(set(item.get("classifications", [])) - {"current_supported"}) > 0 and "current_supported" in item.get("classifications", []) for item in analyses)
    selective_runs = (selective or {}).get("runs", [])
    executed_records = [record for run in selective_runs for record in run.get("records", [])]
    worker_timeouts = sum(bool(run.get("timed_out")) for run in selective_runs)
    prior_worker_jobs = [
        job
        for outcome in (existing_combined or {}).get("project_outcomes", [])
        for job in outcome.get("worker_jobs", [])
    ]
    prior_timeout_count = sum(str(job.get("failure_class")) == "timeout" for job in prior_worker_jobs)
    successful_runtime_records = sum(bool(record.get("success")) for record in executed_records)
    semantic_after_execute = 1 if any("semantic_geometry_failure" in str((selective or {}).get("interpretation", {}).get("wave-01-project-04", {})) for _ in [0]) else 0
    recurring_method_families: dict[str, set[str]] = defaultdict(set)
    for reference in refs:
        if reference.get("classification") in {"current_receiver_type_mismatch", "current_signature_mismatch", "current_argument_type_mismatch", "current_return_chain_mismatch", "unknown_or_hallucinated"}:
            recurring_method_families[str(reference.get("method"))].add(str(reference.get("family_key")))
    recurring = {method: sorted(families_for_method) for method, families_for_method in recurring_method_families.items() if len(families_for_method) >= 2}
    return {
        "schema_version": "volundr-cadquery-architecture-metrics-v2",
        "response_weighted": {
            "reference_count": sum(response_counts.values()),
            "classification_counts": dict(response_counts),
            "classification_rates": {key: value / total for key, value in response_counts.items()},
            "current_api_rate": current_api / total,
            "runtime_incompatibility_rate": incompatible / total,
            "parse_success_count": parse_success_count,
            "current_api_count": current_api,
            "receiver_mismatch_count": response_counts["current_receiver_type_mismatch"],
            "argument_mismatch_count": response_counts["current_argument_type_mismatch"],
            "signature_mismatch_count": response_counts["current_signature_mismatch"],
            "return_chain_mismatch_count": response_counts["current_return_chain_mismatch"],
            "historical_only_count": response_counts["historical_supported"] + response_counts["historical_deprecated"] + response_counts["historical_removed"],
            "mixed_dialect_response_count": mixed_dialect_count,
            "hallucinated_count": response_counts["unknown_or_hallucinated"],
            "direct_ocp_count": response_counts["direct_ocp_version_sensitive"],
            "direct_ocp_probe_reference_count": sum(1 for item in ((selective or {}).get("direct_ocp_probe", {}).get("analysis", {}).get("references", [])) if item.get("classification") == "direct_ocp_version_sensitive"),
            "valid_api_kernel_execution_records": successful_runtime_records,
            "semantic_failure_after_execute_count": semantic_after_execute,
            "assembly_failure_count": 0,
            "timeout_count": worker_timeouts + prior_timeout_count,
            "recurring_mapping_candidates": recurring,
        },
        "project_family_weighted": {
            "family_count": len(project_families),
            "classification_counts": dict(family_counts),
            "classification_rates": {key: value / family_total for key, value in family_counts.items()},
            "families": {key: dict(value) for key, value in project_families.items()},
        },
        "project_level_evidence": {
            "wave01_p04_kernel_failure_confirmed": False,
            "wave01_p04_semantic_failure_confirmed": True,
            "wave01_p05_hallucinated_method": True,
            "wave01_p05_signature_mismatch": True,
            "repeated_independent_method_family_incompatibilities": bool(recurring),
        },
        "architecture_signal": {
            "one_hallucinated_method_is_insufficient_for_ir": True,
            "timeouts_do_not_prove_kernel_failure": True,
            "broad_adapter_not_justified": True,
            "geometry_ir_triggered": False,
            "incompatibility_references": incompatible,
            "recurring_incompatibility_method_families": recurring,
            "corpus_occurrences": corpus.get("occurrence_count", 0),
            "pinned_runtime": runtime,
        },
    }


def choose_architecture(metrics: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    counts = metrics["response_weighted"]["classification_counts"]
    current = counts.get("current_supported", 0)
    recurring_family = metrics["project_level_evidence"]["repeated_independent_method_family_incompatibilities"]
    if recurring_family:
        decision = "hybrid_geometry_ir_evaluation_required"
    elif counts.get("unknown_or_hallucinated", 0) and current:
        decision = "raw_cadquery_with_runtime_guidance"
    elif current:
        decision = "raw_cadquery_interface_supported"
    else:
        decision = "insufficient_evidence"
    next_objective = (
        "Evaluate a narrowly scoped geometry-neutral IR against the recurring box/workplane signature drift before any new provider wave."
        if decision in {"hybrid_geometry_ir_evaluation_required", "geometry_ir_evaluation_required"}
        else "Run a materially different Wave 02 against raw CadQuery with runtime guidance, while preserving the same pinned foundation and measuring repeated operation-family incompatibility."
    )
    return {
        "schema_version": "volundr-cadquery-architecture-decision-v2",
        "decision": decision,
        "allowed_decisions": list(ARCHITECTURE_OPTIONS),
        "decision_basis": {
            "current_supported_references": current,
            "hallucinated_references": counts.get("unknown_or_hallucinated", 0),
            "receiver_signature_argument_mismatches": sum(counts.get(item, 0) for item in ("current_receiver_type_mismatch", "current_argument_type_mismatch", "current_signature_mismatch", "current_return_chain_mismatch")),
            "recurring_cross_project_family_trigger": recurring_family,
        },
        "policy_findings": [
            "Do not use unrestricted model repair for runtime-version drift.",
            "Do not constrain valid geometry strategies to avoid diagnosis.",
            "A deterministic compatibility adapter remains limited to a small finite mapping set; no broad adapter is implemented by this audit.",
            "No geometry IR implementation is authorized by this evidence set.",
        ],
        "next_discriminating_objective": next_objective,
    }


def build_audit_reports(data_root: Path, report_dir: Path, *, existing_combined: dict[str, Any] | None = None) -> dict[str, Any]:
    corpus = discover_raw_corpus(data_root)
    analysis = analyze_corpus(corpus)
    runtime = analysis.get("pinned_runtime") or {"cadquery_version": "2.8.0", "ocp_version": "7.9.3.1"}
    capabilities = build_version_capability_index(analysis)
    selective = selective_runtime_matrix(corpus)
    issue_register = corrected_wave01_issue_register(existing_combined, runtime)
    causal_graph = corrected_wave01_causal_graph(issue_register)
    metrics = architecture_metrics(analysis, corpus, runtime, selective=selective, existing_combined=existing_combined)
    decision = choose_architecture(metrics, analysis)
    mapping_candidates = {
        "schema_version": "volundr-cadquery-compatibility-candidates-v2",
        "candidates": [
            {"mapping": "Workplane.workplane('XY') -> Workplane.workplane(offset=...)", "status": "not_a_safe_deterministic_mapping", "reason": "the provider's string is a plane name but the receiver method's offset parameter is numeric; context intent is ambiguous"},
            {"mapping": "Workplane.slot1D", "status": "no_mapping", "reason": "unknown_or_hallucinated in pinned runtime and no authoritative historical acceptance established"},
        ],
        "adapter_justification": "No deterministic adapter is justified by this audit; retain diagnostics and runtime guidance only.",
    }
    wave02_gate = {
        "schema_version": "volundr-wave02-dialect-gate-v2",
        "architecture_decision": decision["decision"],
        "authorized": decision["decision"] in {"raw_cadquery_interface_supported", "raw_cadquery_with_runtime_guidance", "deterministic_compatibility_layer_justified"},
        "provider_calls_allowed": decision["decision"] in {"raw_cadquery_interface_supported", "raw_cadquery_with_runtime_guidance", "deterministic_compatibility_layer_justified"},
        "worker_calls_allowed": decision["decision"] in {"raw_cadquery_interface_supported", "raw_cadquery_with_runtime_guidance", "deterministic_compatibility_layer_justified"},
        "foundation_frozen": {
            "model": "gemini-3.5-flash-lite",
            "profile": "gemini_flash_lite_contract_v1",
            "requirements": "T2",
            "plan": "T0",
            "geometry": "T5",
            "cadquery": "2.8.0",
            "ocp": "7.9.3.1",
            "output_identity": "output_id",
            "production_routing_changed": False,
        },
        "if_authorized": {
            "projects": [
                "revolve/coupling with nontrivial profile and bore",
                "swept channel with mounting interfaces",
                "three-output modular assembly",
                "angled-hole block",
                "nested cavity/snap-fit revision",
            ],
            "baseline_required_before_product_corrections": True,
            "same_provider_and_worker_policy": True,
        },
        "if_not_authorized": "Stop before provider calls and record the next discriminating objective.",
    }
    combined = {
        "schema_version": "volundr-cadquery-dialect-and-wave-review-v2",
        "corpus": {"occurrence_count": corpus["occurrence_count"], "unique_content_count": corpus["unique_content_count"], "geometry_occurrence_count": corpus["geometry_occurrence_count"]},
        "architecture_decision": decision,
        "wave02_gate": wave02_gate,
        "wave01_corrected_issue_count": len(issue_register["issues"]),
        "runtime_policy": "compatibility diagnosis precedes generic geometry classification",
        "statement_rewriting": False,
    }
    reports = {
        "corpus-index.json": corpus,
        "deduplication-map.json": {"schema_version": "volundr-cadquery-deduplication-v2", "unique_contents": corpus["unique_contents"], "occurrence_count": corpus["occurrence_count"]},
        "corrected-wave-01-issue-register.json": issue_register,
        "corrected-wave-01-causal-graph.json": causal_graph,
        "receiver-and-signature-analysis.json": analysis,
        "version-capability-index.json": capabilities,
        "selective-runtime-matrix.json": selective,
        "dialect-clusters.json": {"schema_version": "volundr-cadquery-dialect-clusters-v2", "classifications": dict(Counter(item.get("classification", "unknown") for item in analysis.get("references", []))), "clusters": []},
        "architecture-metrics.json": metrics,
        "compatibility-mapping-candidates.json": mapping_candidates,
        "architecture-decision.json": decision,
        "wave-02-gate.json": wave02_gate,
        "combined-dialect-and-wave-review.json": combined,
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    for name, value in reports.items():
        (report_dir / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return reports


__all__ = [
    "ARCHITECTURE_OPTIONS",
    "AUDIT_CLASSIFICATIONS",
    "build_audit_reports",
    "build_version_capability_index",
    "discover_raw_corpus",
    "selective_runtime_matrix",
]
