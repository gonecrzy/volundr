"""Fair, model-by-model Ollama calibration primitives.

This module deliberately keeps transport/profile/representation failures away
from CAD-quality conclusions.  The live runner is built on these small,
deterministic operations so that raw evidence and normalized representations
can never be confused.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import textwrap
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable


CALIBRATION_STATES = frozenset(
    {
        "discovered",
        "identity_verified",
        "loading",
        "operational",
        "calibration_running",
        "needs_integration_resolution",
        "needs_template_resolution",
        "needs_timeout_resolution",
        "production_profile_validated",
        "native_profile_validated",
        "native_only_validated",
        "holdout_failed",
        "infrastructure_rejected",
        "admitted",
        "deferred",
    }
)
ADMISSION_STATUSES = frozenset(
    {
        "admitted_production",
        "admitted_native_diagnostic",
        "deferred_for_profile_resolution",
        "deferred_for_adapter_resolution",
        "rejected_infrastructure",
        "rejected_resource_limit",
        "operational_low_cad_quality",
    }
)

ERROR_OWNER_BY_PREFIX = {
    "infrastructure.": "infrastructure",
    "ollama.": "infrastructure",
    "adapter.": "adapter",
    "profile.": "profile",
    "representation.": "representation",
    "model.": "model_contract",
    "cad.": "cad",
}


@dataclass(frozen=True)
class ModelIdentity:
    model_name: str
    digest_prefix: str
    quantization: str
    model_id: str | None = None
    purpose: str = ""


@dataclass(frozen=True)
class VerifiedIdentity:
    model_name: str
    full_digest: str
    quantization: str
    size: int | None = None
    parameter_size: str | None = None
    family: str | None = None
    architecture: str | None = None
    context_length: int | None = None
    template: str | None = None
    stop_parameters: dict[str, Any] = field(default_factory=dict)
    capabilities: tuple[str, ...] = ()


def verify_model_identity(expected: ModelIdentity, actual: dict[str, Any]) -> VerifiedIdentity:
    name = actual.get("name")
    digest = actual.get("digest")
    quantization = actual.get("quantization")
    if (
        name != expected.model_name
        or not isinstance(digest, str)
        or not digest.removeprefix("sha256:").startswith(expected.digest_prefix)
        or quantization != expected.quantization
    ):
        raise ValueError(
            "identity mismatch: expected exact model name, digest prefix, and quantization"
        )
    return VerifiedIdentity(
        model_name=name,
        full_digest=digest,
        quantization=quantization,
        size=actual.get("size") if isinstance(actual.get("size"), int) else None,
        parameter_size=actual.get("parameter_size") if isinstance(actual.get("parameter_size"), str) else None,
        family=actual.get("family") if isinstance(actual.get("family"), str) else None,
        architecture=actual.get("architecture") if isinstance(actual.get("architecture"), str) else None,
        context_length=actual.get("context_length") if isinstance(actual.get("context_length"), int) else None,
        template=actual.get("template") if isinstance(actual.get("template"), str) else None,
        stop_parameters=actual.get("stop_parameters") if isinstance(actual.get("stop_parameters"), dict) else {},
        capabilities=tuple(actual.get("capabilities", [])) if isinstance(actual.get("capabilities"), list) else (),
    )


@dataclass(frozen=True)
class NormalizedResponse:
    raw_response: str
    normalized_response: str
    codes: tuple[str, ...] = ()


_REASONING_BLOCK_RE = re.compile(
    r"(?:<think>.*?</think>|<thinking>.*?</thinking>|<\|thinking\|>.*?<\|end\|>)",
    re.IGNORECASE | re.DOTALL,
)
_FENCE_RE = re.compile(r"\A\s*```(?:json|python|py|cadquery)?\s*|\s*```\s*\Z", re.IGNORECASE)


def _strip_representation_wrappers(text: str) -> tuple[str, list[str]]:
    codes: list[str] = []
    stripped = text.replace("\r\n", "\n").replace("\r", "\n")
    if stripped != text:
        codes.append("representation.line_endings_normalized")
    without_reasoning = _REASONING_BLOCK_RE.sub("", stripped).strip()
    if without_reasoning != stripped.strip():
        codes.append("representation.reasoning_wrapped")
    without_fence = _FENCE_RE.sub("", without_reasoning, count=1).strip()
    if without_fence != without_reasoning:
        codes.append("representation.markdown_wrapped")
    return without_fence, codes


def _extract_one_json_object(text: str) -> tuple[Any, bool]:
    decoder = json.JSONDecoder()
    try:
        value, end = decoder.raw_decode(text)
        return value, end != len(text)
    except json.JSONDecodeError:
        pass
    for index, character in enumerate(text):
        if character not in "{[":
            continue
        try:
            value, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if text[index + end :].strip():
            return value, True
        return value, True
    raise ValueError("structured response is not valid JSON")


def normalize_structured_response(
    raw_response: str,
    *,
    expected_slot_ids: Iterable[int] | None = None,
) -> NormalizedResponse:
    text, codes = _strip_representation_wrappers(raw_response)
    payload, wrapped = _extract_one_json_object(text)
    if wrapped and text != json.dumps(payload, separators=(",", ":")):
        codes.append("representation.prose_wrapped")
    if not isinstance(payload, dict):
        raise ValueError("structured response must be a JSON object")
    if expected_slot_ids is not None and isinstance(payload.get("slots"), list):
        expected = list(expected_slot_ids)
        actual_ids = [item.get("slot_id") for item in payload["slots"] if isinstance(item, dict)]
        if actual_ids != sorted(actual_ids):
            codes.append("representation.slot_order_variant")
        if set(actual_ids) != set(expected):
            raise ValueError("structured response has unknown or missing slot IDs")
        payload = {**payload, "slots": sorted(payload["slots"], key=lambda item: expected.index(item["slot_id"]))}
    return NormalizedResponse(
        raw_response=raw_response,
        normalized_response=json.dumps(payload, indent=2, sort_keys=True) + "\n",
        codes=tuple(dict.fromkeys(codes)),
    )


def normalize_native_source(
    raw_response: str,
    *,
    required_operations: Iterable[str] = (),
) -> NormalizedResponse:
    text, codes = _strip_representation_wrappers(raw_response)
    required = tuple(required_operations)
    missing = [operation for operation in required if operation not in text]
    if missing:
        raise ValueError("cannot normalize CAD intent; missing operation(s): " + ", ".join(missing))
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise ValueError(f"native source is not valid Python: {exc.msg}") from exc
    for node in tree.body:
        if isinstance(node, ast.Import):
            if len(node.names) != 1 or node.names[0].name != "cadquery":
                raise ValueError("native source contains an unapproved import")
        elif isinstance(node, ast.ImportFrom):
            raise ValueError("native source contains an unapproved import form")
    if re.search(r"\b(?:subprocess|socket|requests|urllib|os\.system|open)\b", text):
        raise ValueError("native source contains an unsafe operation")
    result_assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) for target in node.targets)
        and ("cq." in ast.unparse(node.value) or any(isinstance(child, ast.Call) and "cq." in ast.unparse(child.func) for child in ast.walk(node.value)))
    ]
    if not any(isinstance(target, ast.Name) and target.id == "result" for node in result_assignments for target in node.targets):
        if len(result_assignments) != 1:
            raise ValueError("multiple plausible final CadQuery objects; result alias is ambiguous")
        target = next(target for target in result_assignments[0].targets if isinstance(target, ast.Name))
        text = text.rstrip() + f"\nresult = {target.id}\n"
        codes.append("representation.final_symbol_alias")
    return NormalizedResponse(raw_response=raw_response, normalized_response=text, codes=tuple(dict.fromkeys(codes)))


def wrap_native_source_for_worker(source: str) -> str:
    """Wrap a normalized native script without changing its CAD statements.

    The wrapper supplies only the existing Volundr output contract.  It does
    not add geometry, dimensions, features, or operations.
    """

    lines = source.splitlines()
    body = [line for line in lines if not re.match(r"^\s*import\s+cadquery\s+as\s+cq\s*$", line)]
    wrapped = "\n".join(
        [
            "import cadquery as cq",
            "from volundr_cad.runtime import PrintableOutput, Product",
            "",
            "def build(params):",
            textwrap.indent("\n".join(body), "    "),
            "    return Product(outputs=[PrintableOutput(output_id='native_result', label='Native calibration result', model=result, component_id='native_result', expected_solid_count=1, allow_disconnected_solids=False)])",
            "",
        ]
    )
    return wrapped


@dataclass(frozen=True)
class CalibrationIssue:
    issue_id: str
    model: str
    stage: str
    owner: str
    error_code: str
    message: str
    evidence_path: str
    blocking_calibration: bool
    blocking_other_models: bool
    recommended_resolution: str
    status: str = "open"
    worker_validated: bool = False
    counts_against_cad_quality: bool = False


def classify_calibration_failure(
    *,
    stage: str,
    error_code: str,
    message: str,
    evidence_path: str = "",
    worker_validated: bool = False,
) -> CalibrationIssue:
    owner = next((value for prefix, value in ERROR_OWNER_BY_PREFIX.items() if error_code.startswith(prefix)), "adapter")
    quality = owner == "cad" and worker_validated
    return CalibrationIssue(
        issue_id=hashlib.sha256(f"{stage}:{error_code}:{message}".encode()).hexdigest()[:16],
        model="",
        stage=stage,
        owner=owner,
        error_code=error_code,
        message=message,
        evidence_path=evidence_path,
        blocking_calibration=owner in {"infrastructure", "adapter", "profile"},
        blocking_other_models=False,
        recommended_resolution=f"Resolve {owner} issue and recalibrate this model",
        worker_validated=worker_validated,
        counts_against_cad_quality=quality,
    )


def build_resolution_queue(issues: Iterable[CalibrationIssue]) -> list[dict[str, Any]]:
    return [
        {
            "issue_id": issue.issue_id,
            "model": issue.model,
            "stage": issue.stage,
            "owner": issue.owner,
            "error_code": issue.error_code,
            "evidence_path": issue.evidence_path,
            "blocking_calibration": issue.blocking_calibration,
            "blocking_other_models": issue.blocking_other_models,
            "recommended_resolution": issue.recommended_resolution,
            "status": issue.status,
        }
        for issue in issues
    ]


@dataclass(frozen=True)
class CalibrationProfile:
    profile_version: str
    model_name: str
    model_digest: str
    response_modes: tuple[str, ...] = ()
    chat_template: str | None = None
    system_prompt: str | None = None
    native_system_prompt: str | None = None
    stop_sequences: tuple[str, ...] = ()
    structured_output_supported: bool = False
    structured_output_method: str | None = None
    reasoning_tag_policy: str | None = None
    markdown_policy: str | None = None
    native_extraction_policy: str | None = None
    final_object_policy: str | None = None
    slot_mapping_policy: str | None = None
    context_length: int = 8192
    max_output_tokens: int = 4096
    temperature: float = 0.2
    top_p: float = 0.8
    top_k: int = 20
    seed_policy: str | int | None = None
    connect_timeout_seconds: float = 15.0
    first_token_timeout_seconds: float = 300.0
    idle_timeout_seconds: float = 300.0
    total_timeout_seconds: float = 1800.0
    keep_alive: str | int = "30m"
    known_safe_normalizations: tuple[str, ...] = ()
    known_unsupported_behaviors: tuple[str, ...] = ()
    calibration_status: str = "candidate"
    holdout_status: str = "not_started"
    profile_hash: str | None = None
    iteration: int = 0

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for field_name in ("response_modes", "stop_sequences", "known_safe_normalizations", "known_unsupported_behaviors"):
            result[field_name] = list(result[field_name])
        return result

    def assert_holdout_compatible(self, candidate: dict[str, Any]) -> None:
        if _profile_hash(candidate) != self.profile_hash:
            raise HoldoutFrozenError("profile changed after holdout validation began")

    def next_iteration(self, iteration: int) -> "CalibrationProfile":
        if iteration > 3:
            raise ProfileIterationLimitError("profile iteration limit is three")
        if iteration != self.iteration + 1:
            raise ValueError("profile iterations must advance sequentially")
        return replace(self, iteration=iteration, profile_hash=None, calibration_status="candidate")


def load_calibration_profile(path: Path) -> CalibrationProfile:
    """Load a JSON-compatible YAML profile without adding an unneeded parser."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("calibration profile must be an object")
    required = {"profile_version", "model_name", "model_digest", "response_modes", "chat_template"}
    if not required <= payload.keys():
        raise ValueError(f"calibration profile is missing fields: {sorted(required - payload.keys())}")
    for key in ("response_modes", "stop_sequences", "known_safe_normalizations", "known_unsupported_behaviors"):
        if key in payload:
            payload[key] = tuple(payload[key])
    return CalibrationProfile(**payload)


class HoldoutFrozenError(ValueError):
    pass


class ProfileIterationLimitError(ValueError):
    pass


def _profile_hash(profile: CalibrationProfile | dict[str, Any]) -> str:
    payload = profile.to_dict() if isinstance(profile, CalibrationProfile) else dict(profile)
    payload.pop("profile_hash", None)
    payload.pop("calibration_status", None)
    payload.pop("holdout_status", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def freeze_profile(profile: CalibrationProfile) -> CalibrationProfile:
    digest = _profile_hash(profile)
    if profile.profile_hash is not None and profile.profile_hash != digest:
        raise ValueError("profile hash does not match profile contents")
    return replace(profile, profile_hash=digest, calibration_status="frozen")


def can_count_cad_quality(issue: CalibrationIssue, *, profile_validated: bool) -> bool:
    """A CAD finding is quality evidence only after fair profile + worker gates."""

    return bool(
        profile_validated
        and issue.owner == "cad"
        and issue.worker_validated
        and issue.counts_against_cad_quality
    )


@dataclass(frozen=True)
class CapabilityClassification:
    native_capability: str
    production_compatibility: str
    admission: str


def classify_native_and_production(
    *,
    native_validated: bool,
    production_validated: bool,
    production_partial: bool = False,
    production_tested: bool = False,
) -> CapabilityClassification:
    if production_validated:
        production = "compatible"
        admission = "admitted_production"
    else:
        production = "partially_compatible" if production_partial else ("incompatible" if production_tested else "not_tested")
        admission = "admitted_native_diagnostic" if native_validated else "deferred_for_profile_resolution"
    return CapabilityClassification(
        native_capability="validated" if native_validated else "not_tested",
        production_compatibility=production,
        admission=admission,
    )


@dataclass(frozen=True)
class AdmissionResult:
    formal_benchmark_authorized: bool
    specialist_count: int
    generic_baseline_count: int
    blocking_model_ids: tuple[str, ...] = ()
    reason: str | None = None


def admission_gate(models: Iterable[dict[str, Any]], *, intended_model_ids: Iterable[str]) -> AdmissionResult:
    records = list(models)
    intended = tuple(intended_model_ids)
    by_id = {str(item.get("model_id")): item for item in records}
    specialists = [item for item in records if "specialist" in str(item.get("purpose", "")).casefold() and item.get("admission") in {"admitted_production", "admitted_native_diagnostic"}]
    generic = [item for item in records if "generic" in str(item.get("purpose", "")).casefold() and item.get("admission") == "admitted_production"]
    blocking = tuple(model_id for model_id in intended if model_id not in by_id or by_id[model_id].get("state") not in {"admitted", "deferred", "infrastructure_rejected"} or by_id[model_id].get("admission", "").startswith("deferred"))
    authorized = bool(specialists and generic and not blocking and all(model_id in by_id for model_id in intended))
    return AdmissionResult(
        formal_benchmark_authorized=authorized,
        specialist_count=len(specialists),
        generic_baseline_count=len(generic),
        blocking_model_ids=blocking,
        reason=None if authorized else "all intended models must have final status plus specialist and generic admissions",
    )


def require_formal_benchmark_admission(evidence_root: Path) -> dict[str, Any]:
    """Return the frozen admission record or block the later benchmark."""

    candidates = sorted(
        (path / "admission.json" for path in evidence_root.iterdir() if path.is_dir()),
        reverse=True,
    ) if evidence_root.exists() else []
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("formal_benchmark_authorized") is True:
            return payload
    raise RuntimeError(
        "formal five-case benchmark is blocked: no Ollama calibration admission "
        "record authorizes it"
    )


async def run_models_serially(
    model_names: Iterable[str],
    calibrate: Callable[[str], Awaitable[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Run one active generation/model load at a time and continue model errors."""

    results: list[dict[str, Any]] = []
    for model_name in model_names:
        try:
            result = await calibrate(model_name)
        except Exception as exc:  # model-scoped failures are evidence, not process failures
            if getattr(exc, "blocking_other_models", False):
                raise
            result = {
                "model": model_name,
                "state": "deferred",
                "admission": "deferred_for_resolution",
                "error": str(exc),
            }
        results.append(result)
    return results


EXPECTED_MODEL_IDENTITIES = (
    ModelIdentity("volundr-cad-coder-native:q8_0", "78a442269750", "Q8_0", "cad-coder", "CAD specialist"),
    ModelIdentity("volundr-procad-coder-native:q8_0", "92d3a018374f", "Q8_0", "procad-coder", "CAD specialist"),
    ModelIdentity("hf.co/yuvit-batra/qwen2.5-coder-7b-cadquery-gguf:Q4_K_M", "692bb3cfa2f4", "Q4_K_M", "qwen25-cadquery", "CAD specialist"),
    ModelIdentity("qwen2.5-coder:14b-instruct-q5_K_M", "05d16c5ac1c1", "Q5_K_M", "qwen25-coder-14b", "generic coding baseline"),
    ModelIdentity("deepseek-coder-v2:16b-lite-instruct-q4_K_M", "dac6ff6589c9", "Q4_K_M", "deepseek-coder-v2-lite", "generic coding baseline"),
    ModelIdentity("joshuaokolo/C3Dv0:latest", "0e44735f72fb", "Q8_0", "c3dv0", "CAD specialist"),
)
