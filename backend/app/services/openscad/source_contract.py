from __future__ import annotations

import hashlib
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from app.core.config import settings

CONTRACT_VERSION = "source-contract-v1"
VALIDATOR_VERSION = "openscad-static-validator-v1"


@dataclass(frozen=True)
class SourceToken:
    kind: str
    value: str
    line: int


@dataclass(frozen=True)
class SourceMapping:
    requirement_id: str
    marker_type: str
    target_name: str
    target_kind: str
    line: int


@dataclass(frozen=True)
class SourceGeometryMapping:
    geometry_type: str
    attributes: dict[str, str]
    line: int
    feature_id: str | None = None


@dataclass(frozen=True)
class SourceDependencyMapping:
    from_id: str
    to_id: str
    target_name: str
    target_kind: str
    line: int


@dataclass(frozen=True)
class SourceOutputMapping:
    output_id: str
    component_ids: list[str]
    target_name: str
    target_kind: str
    line: int
    module_name: str | None = None
    filename: str | None = None
    required: bool | None = None


@dataclass(frozen=True)
class SourceMetadata:
    source_hash: str
    source_size_bytes: int
    line_count: int
    module_names: list[str] = field(default_factory=list)
    parameter_names: list[str] = field(default_factory=list)
    include_paths: list[str] = field(default_factory=list)
    top_level_calls: list[str] = field(default_factory=list)
    top_level_geometry_calls: list[str] = field(default_factory=list)
    requirement_mappings: dict[str, SourceMapping] = field(default_factory=dict)
    feature_mappings: dict[str, SourceMapping] = field(default_factory=dict)
    component_mappings: dict[str, SourceMapping] = field(default_factory=dict)
    dependency_mappings: list[SourceDependencyMapping] = field(default_factory=list)
    output_mappings: dict[str, SourceOutputMapping] = field(default_factory=dict)
    geometry_mappings: list[SourceGeometryMapping] = field(default_factory=list)
    assignments: dict[str, str] = field(default_factory=dict)
    assignment_lines: dict[str, int] = field(default_factory=dict)
    sections: set[str] = field(default_factory=set)
    has_assertion: bool = False
    has_unbalanced_braces: bool = False
    has_unbalanced_parentheses: bool = False
    main_model_body_empty: bool = False

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sections"] = sorted(self.sections)
        return payload


@dataclass(frozen=True)
class SourceContractFinding:
    rule_id: str
    category: str
    severity: str
    is_blocking: bool
    title: str
    explanation: str
    suggested_correction: str
    detected_value: str | None = None
    unit: str | None = None
    threshold_value: str | None = None
    source_line_start: int | None = None
    source_line_end: int | None = None
    related_requirement_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceScanResult:
    tokens: list[SourceToken]
    comments: list[SourceToken]
    metadata: SourceMetadata


@dataclass(frozen=True)
class SourceContractResult:
    contract_version: str
    validator_version: str
    ruleset_version: str
    passed_hard_checks: bool
    hard_violations: list[SourceContractFinding]
    quality_findings: list[SourceContractFinding]
    specification_findings: list[SourceContractFinding]
    source_metadata: SourceMetadata
    validation_ms: float

    def to_json(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "validator_version": self.validator_version,
            "ruleset_version": self.ruleset_version,
            "passed_hard_checks": self.passed_hard_checks,
            "hard_violations": [finding.to_json() for finding in self.hard_violations],
            "quality_findings": [finding.to_json() for finding in self.quality_findings],
            "specification_findings": [
                finding.to_json() for finding in self.specification_findings
            ],
            "source_metadata": self.source_metadata.to_json(),
            "validation_ms": self.validation_ms,
        }


class SourceContractValidator:
    def __init__(
        self,
        *,
        max_source_bytes: int | None = None,
        ruleset_version: str = "gemini-ruleset-v1",
    ) -> None:
        self.max_source_bytes = max_source_bytes or settings.max_source_bytes
        self.ruleset_version = ruleset_version

    def validate(
        self,
        source: str,
        *,
        design_specification: dict[str, Any] | None,
        design_plan: dict[str, Any] | None = None,
        source_type: str,
    ) -> SourceContractResult:
        started = time.perf_counter()
        scan = scan_openscad_source(source)
        metadata = scan.metadata
        hard = self._hard_findings(source, scan, source_type=source_type, design_plan=design_plan)
        spec_findings = self._specification_findings(
            scan,
            design_specification=design_specification,
            design_plan=design_plan,
            source_type=source_type,
        )
        quality = self._quality_findings(source, scan)
        passed = not hard and not any(finding.is_blocking for finding in spec_findings)
        return SourceContractResult(
            contract_version=CONTRACT_VERSION,
            validator_version=VALIDATOR_VERSION,
            ruleset_version=self.ruleset_version,
            passed_hard_checks=passed,
            hard_violations=hard,
            quality_findings=quality,
            specification_findings=spec_findings,
            source_metadata=metadata,
            validation_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    def _hard_findings(
        self,
        source: str,
        scan: SourceScanResult,
        *,
        source_type: str,
        design_plan: dict[str, Any] | None = None,
    ) -> list[SourceContractFinding]:
        findings: list[SourceContractFinding] = []
        metadata = scan.metadata
        if not source.strip():
            findings.append(_finding("source_structure.empty_source", "source_structure", "Source is empty"))
        if metadata.source_size_bytes > self.max_source_bytes:
            findings.append(
                _finding(
                    "source_security.source_too_large",
                    "source_security",
                    "Source exceeds size limit",
                    detected_value=str(metadata.source_size_bytes),
                    threshold_value=str(self.max_source_bytes),
                )
            )
        for index, token in enumerate(scan.tokens):
            lower = token.value.lower()
            next_token = _next_non_comment(scan.tokens, index)
            if lower == "import" and next_token and next_token.value == "(":
                findings.append(
                    _finding(
                        "source_security.forbidden_import",
                        "source_security",
                        "Forbidden import()",
                        line=token.line,
                        detected_value="import()",
                    )
                )
            if lower == "surface" and next_token and next_token.value == "(":
                findings.append(
                    _finding(
                        "source_security.forbidden_surface",
                        "source_security",
                        "Forbidden surface()",
                        line=token.line,
                        detected_value="surface()",
                    )
                )
            if lower in {"include", "use"}:
                findings.append(
                    _finding(
                        "source_security.forbidden_include",
                        "source_security",
                        "Forbidden include/use directive",
                        line=token.line,
                        detected_value=token.value,
                    )
                )
        string_values = [token.value for token in scan.tokens if token.kind == "string"]
        if any(".." in value or re.search(r"(^|[\"'])/[A-Za-z0-9_.-]", value) for value in string_values):
            findings.append(
                _finding(
                    "source_security.suspicious_path",
                    "source_security",
                    "Suspicious filesystem path",
                    detected_value="path-like string",
                )
            )
        if metadata.has_unbalanced_braces:
            findings.append(
                _finding("source_structure.unbalanced_braces", "source_structure", "Unbalanced braces")
            )
        if metadata.has_unbalanced_parentheses:
            findings.append(
                _finding(
                    "source_structure.unbalanced_parentheses",
                    "source_structure",
                    "Unbalanced parentheses",
                )
            )
        requires_output_selector = _requires_output_selector(design_plan)
        expected_final_call = "render_selected_output" if requires_output_selector else "main_model"
        if requires_output_selector:
            if "selected_output" not in metadata.assignments:
                findings.append(
                    _finding(
                        "source_structure.missing_selected_output_parameter",
                        "source_structure",
                        "Missing selected_output parameter",
                    )
                )
            if "render_selected_output" not in metadata.module_names:
                findings.append(
                    _finding(
                        "source_structure.missing_render_selected_output_module",
                        "source_structure",
                        "Missing render_selected_output module",
                    )
                )
            if metadata.top_level_calls.count("render_selected_output") != 1:
                findings.append(
                    _finding(
                        "source_structure.missing_final_render_selected_output_call",
                        "source_structure",
                        "Missing final render_selected_output() call",
                        detected_value=str(metadata.top_level_calls.count("render_selected_output")),
                        threshold_value="1",
                    )
                )
        elif "main_model" not in metadata.module_names:
            findings.append(
                _finding(
                    "source_structure.missing_main_model_module",
                    "source_structure",
                    "Missing main_model module",
                )
            )
        if not requires_output_selector and metadata.top_level_calls.count("main_model") != 1:
            findings.append(
                _finding(
                    "source_structure.missing_final_main_model_call",
                    "source_structure",
                    "Missing final main_model() call",
                    detected_value=str(metadata.top_level_calls.count("main_model")),
                    threshold_value="1",
                )
            )
        unintended_top_level = [
            call for call in metadata.top_level_geometry_calls if call != expected_final_call
        ]
        if unintended_top_level:
            findings.append(
                _finding(
                    "source_structure.unintended_top_level_call",
                    "source_structure",
                    "Unintended top-level geometry call",
                    detected_value=", ".join(unintended_top_level),
                )
            )
        if not requires_output_selector and metadata.main_model_body_empty:
            findings.append(
                _finding(
                    "source_structure.empty_main_model_body",
                    "source_structure",
                    "main_model body is empty",
                )
            )
        if source_type in {"ai_initial", "ai_repair"} and "user_parameters" not in metadata.sections:
            findings.append(
                _finding(
                    "source_structure.missing_user_parameters_section",
                    "source_structure",
                    "Missing USER PARAMETERS section",
                )
            )
        return findings

    def _specification_findings(
        self,
        scan: SourceScanResult,
        *,
        design_specification: dict[str, Any] | None,
        design_plan: dict[str, Any] | None,
        source_type: str,
    ) -> list[SourceContractFinding]:
        if source_type not in {"ai_initial", "ai_revision", "ai_repair"}:
            return []
        findings: list[SourceContractFinding] = []
        constants = _evaluate_constants(scan.metadata.assignments)
        if design_specification is not None:
            findings.extend(
                self._design_specification_findings(
                    scan,
                    design_specification=design_specification,
                    constants=constants,
                )
            )
        if design_plan is not None:
            findings.extend(
                self._design_plan_findings(
                    scan,
                    design_plan=design_plan,
                )
            )
        return findings

    def _design_specification_findings(
        self,
        scan: SourceScanResult,
        *,
        design_specification: dict[str, Any],
        constants: dict[str, float],
    ) -> list[SourceContractFinding]:
        findings: list[SourceContractFinding] = []
        for dimension in design_specification.get("critical_dimensions", []):
            if not dimension.get("protected"):
                continue
            requirement_id = str(dimension.get("id"))
            mapping = scan.metadata.requirement_mappings.get(requirement_id)
            expected = dimension.get("value")
            if mapping is None:
                findings.append(
                    _finding(
                        "specification_compliance.missing_protected_requirement_mapping",
                        "specification_compliance",
                        "Missing protected requirement mapping",
                        related_requirement_id=requirement_id,
                        threshold_value=str(expected),
                    )
                )
                continue
            detected = constants.get(mapping.target_name)
            if detected is None:
                findings.append(
                    _finding(
                        "specification_compliance.protected_value_unverifiable",
                        "specification_compliance",
                        "Protected value is not statically verifiable",
                        line=mapping.line,
                        related_requirement_id=requirement_id,
                        detected_value=scan.metadata.assignments.get(mapping.target_name),
                        threshold_value=str(expected),
                    )
                )
                continue
            try:
                expected_number = float(expected)
            except (TypeError, ValueError):
                continue
            tolerance = _dimension_tolerance(dimension)
            if abs(detected - expected_number) > tolerance:
                findings.append(
                    _finding(
                        "specification_compliance.protected_value_mismatch",
                        "specification_compliance",
                        "Protected value does not match Design Specification",
                        line=mapping.line,
                        related_requirement_id=requirement_id,
                        detected_value=_format_number(detected),
                        threshold_value=_format_number(expected_number),
                    )
                )
        for requirement in design_specification.get("functional_requirements", []):
            if not requirement.get("protected"):
                continue
            requirement_id = str(requirement.get("id"))
            if requirement_id not in scan.metadata.feature_mappings:
                findings.append(
                    _finding(
                        "specification_compliance.missing_required_feature_marker",
                        "specification_compliance",
                        "Missing required feature marker",
                        related_requirement_id=requirement_id,
                    )
                )
        return findings

    def _design_plan_findings(
        self,
        scan: SourceScanResult,
        *,
        design_plan: dict[str, Any],
    ) -> list[SourceContractFinding]:
        findings: list[SourceContractFinding] = []
        for parameter in design_plan.get("parameters", []):
            parameter_id = str(parameter.get("id"))
            if not parameter_id:
                continue
            if parameter.get("protected") or parameter.get("editable", False):
                if parameter_id not in scan.metadata.assignments:
                    findings.append(
                        _finding(
                            "design_plan_compliance.missing_plan_parameter",
                            "specification_compliance",
                            "Missing Design Plan parameter",
                            related_requirement_id=parameter.get("source_requirement_id"),
                            threshold_value=parameter_id,
                        )
                    )
        for component in design_plan.get("components", []):
            component_id = str(component.get("id"))
            if component_id and component_id not in scan.metadata.component_mappings:
                findings.append(
                    _finding(
                        "design_plan_compliance.missing_component_marker",
                        "specification_compliance",
                        "Missing Design Plan component marker",
                        threshold_value=component_id,
                    )
                )
        for feature in design_plan.get("features", []):
            feature_id = str(feature.get("id"))
            if feature_id and feature_id not in scan.metadata.feature_mappings:
                findings.append(
                    _finding(
                        "design_plan_compliance.missing_feature_marker",
                        "specification_compliance",
                        "Missing Design Plan feature marker",
                        threshold_value=feature_id,
                    )
                )
        dependency_pairs = {
            (mapping.from_id, mapping.to_id) for mapping in scan.metadata.dependency_mappings
        }
        for edge in design_plan.get("dependency_edges", []):
            from_id = str(edge.get("from") or edge.get("from_") or "")
            to_id = str(edge.get("to") or "")
            if from_id and to_id and (from_id, to_id) not in dependency_pairs:
                findings.append(
                    _finding(
                        "design_plan_compliance.missing_dependency_marker",
                        "specification_compliance",
                        "Missing Design Plan dependency marker",
                        detected_value=f"{from_id} -> {to_id}",
                    )
                )
        for output in design_plan.get("printable_outputs", []):
            output_id = str(output.get("id"))
            if not output_id:
                continue
            mapping = scan.metadata.output_mappings.get(output_id)
            if mapping is None:
                findings.append(
                    _finding(
                        "design_plan_compliance.missing_output_marker",
                        "specification_compliance",
                        "Missing Design Plan printable output marker",
                        threshold_value=output_id,
                    )
                )
                continue
            expected_module = str(output.get("module_name") or output.get("module") or "").strip()
            marker_module = mapping.module_name or mapping.target_name
            if expected_module and marker_module != expected_module:
                findings.append(
                    _finding(
                        "design_plan_compliance.output_module_mismatch",
                        "specification_compliance",
                        "Printable output marker references the wrong module",
                        detected_value=marker_module,
                        threshold_value=expected_module,
                        line=mapping.line,
                    )
                )
            if marker_module not in scan.metadata.module_names:
                findings.append(
                    _finding(
                        "design_plan_compliance.output_module_missing",
                        "specification_compliance",
                        "Printable output marker references a missing module",
                        detected_value=marker_module,
                        threshold_value=output_id,
                        line=mapping.line,
                    )
                )
        return findings

    def _quality_findings(self, source: str, scan: SourceScanResult) -> list[SourceContractFinding]:
        findings: list[SourceContractFinding] = []
        metadata = scan.metadata
        if "assumptions" not in metadata.sections:
            findings.append(
                _finding(
                    "source_structure.missing_assumptions_comment",
                    "source_structure",
                    "Missing assumptions comment",
                    severity="notice",
                    blocking=False,
                )
            )
        if "print_notes" not in metadata.sections:
            findings.append(
                _finding(
                    "source_structure.missing_print_notes",
                    "source_structure",
                    "Missing print notes",
                    severity="warning",
                    blocking=False,
                )
            )
        if not metadata.has_assertion:
            findings.append(
                _finding(
                    "source_parameterization.missing_assertions",
                    "source_parameterization",
                    "Missing parameter assertions",
                    severity="warning",
                    blocking=False,
                )
            )
        fn_expr = metadata.assignments.get("$fn")
        if fn_expr:
            constants = _evaluate_constants(metadata.assignments)
            fn_value = constants.get("$fn")
            if fn_value is not None and fn_value > 96:
                findings.append(
                    _finding(
                        "source_complexity.excessive_fn",
                        "source_complexity",
                        "Excessive $fn value",
                        severity="warning",
                        blocking=False,
                        line=metadata.assignment_lines.get("$fn"),
                        detected_value=_format_number(fn_value),
                        threshold_value="96",
                    )
                )
        repeated_numbers = _repeated_numeric_literals(source)
        if repeated_numbers:
            findings.append(
                _finding(
                    "source_parameterization.repeated_magic_number",
                    "source_parameterization",
                    "Repeated numeric literal",
                    severity="notice",
                    blocking=False,
                    detected_value=repeated_numbers[0],
                )
            )
        return findings


def scan_openscad_source(source: str) -> SourceScanResult:
    tokens, comments = _tokenize(source)
    metadata = _metadata(source, tokens, comments)
    return SourceScanResult(tokens=tokens, comments=comments, metadata=metadata)


def _tokenize(source: str) -> tuple[list[SourceToken], list[SourceToken]]:
    tokens: list[SourceToken] = []
    comments: list[SourceToken] = []
    index = 0
    line = 1
    while index < len(source):
        char = source[index]
        if char in " \t\r":
            index += 1
            continue
        if char == "\n":
            line += 1
            index += 1
            continue
        if source.startswith("//", index):
            start_line = line
            end = source.find("\n", index)
            if end == -1:
                end = len(source)
            value = source[index:end]
            comments.append(SourceToken("comment", value, start_line))
            index = end
            continue
        if source.startswith("/*", index):
            start_line = line
            end = source.find("*/", index + 2)
            if end == -1:
                value = source[index:]
                line += value.count("\n")
                comments.append(SourceToken("comment", value, start_line))
                index = len(source)
                continue
            value = source[index : end + 2]
            line += value.count("\n")
            comments.append(SourceToken("comment", value, start_line))
            index = end + 2
            continue
        if char in {'"', "'"}:
            quote = char
            start_line = line
            start = index
            index += 1
            escaped = False
            while index < len(source):
                current = source[index]
                if current == "\n":
                    line += 1
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == quote:
                    index += 1
                    break
                index += 1
            tokens.append(SourceToken("string", source[start:index], start_line))
            continue
        if char == "<":
            start_line = line
            end = source.find(">", index + 1)
            if end != -1:
                tokens.append(SourceToken("path", source[index : end + 1], start_line))
                index = end + 1
                continue
        if char.isalpha() or char == "_" or char == "$":
            start = index
            while index < len(source) and (
                source[index].isalnum() or source[index] in {"_", "$"}
            ):
                index += 1
            tokens.append(SourceToken("identifier", source[start:index], line))
            continue
        if char.isdigit() or (char == "." and index + 1 < len(source) and source[index + 1].isdigit()):
            start = index
            while index < len(source) and (source[index].isdigit() or source[index] == "."):
                index += 1
            tokens.append(SourceToken("number", source[start:index], line))
            continue
        if char in "{}()[]=;,+-*/":
            tokens.append(SourceToken("symbol", char, line))
            index += 1
            continue
        tokens.append(SourceToken("symbol", char, line))
        index += 1
    return tokens, comments


def _metadata(source: str, tokens: list[SourceToken], comments: list[SourceToken]) -> SourceMetadata:
    module_names: list[str] = []
    parameter_names: list[str] = []
    include_paths: list[str] = []
    top_level_calls: list[str] = []
    top_level_geometry_calls: list[str] = []
    assignments: dict[str, str] = {}
    assignment_lines: dict[str, int] = {}
    sections = _sections(comments)
    (
        requirement_markers,
        feature_markers,
        component_markers,
        dependency_markers,
        output_markers,
        geometry_markers,
    ) = _pending_markers(comments)
    requirement_mappings: dict[str, SourceMapping] = {}
    feature_mappings: dict[str, SourceMapping] = {}
    component_mappings: dict[str, SourceMapping] = {}
    dependency_mappings: list[SourceDependencyMapping] = []
    output_mappings: dict[str, SourceOutputMapping] = {}
    brace_depth = 0
    paren_depth = 0
    unbalanced_braces = False
    unbalanced_parentheses = False
    main_body_tokens = 0
    pending_main_body = False
    in_main_body = False
    main_body_depth = 0
    index = 0
    while index < len(tokens):
        token = tokens[index]
        lower = token.value.lower()
        if token.value == "{":
            brace_depth += 1
            if pending_main_body:
                pending_main_body = False
                in_main_body = True
                main_body_depth = brace_depth
            index += 1
            continue
        if token.value == "}":
            if brace_depth == 0:
                unbalanced_braces = True
            else:
                if in_main_body and brace_depth == main_body_depth:
                    in_main_body = False
                    main_body_depth = 0
                brace_depth -= 1
            index += 1
            continue
        if token.value == "(":
            paren_depth += 1
        elif token.value == ")":
            if paren_depth == 0:
                unbalanced_parentheses = True
            else:
                paren_depth -= 1
        if in_main_body and brace_depth >= main_body_depth and token.value not in {"{", "}", ";"}:
            main_body_tokens += 1
        if lower in {"include", "use"}:
            next_token = _next_non_comment(tokens, index)
            if next_token:
                include_paths.append(next_token.value)
        if lower == "module":
            name = _next_identifier(tokens, index)
            if name:
                module_names.append(name.value)
                for marker in _markers_for_line(feature_markers, token.line):
                    feature_mappings[marker] = SourceMapping(
                        requirement_id=marker,
                        marker_type="feature",
                        target_name=name.value,
                        target_kind="module",
                        line=name.line,
                    )
                for marker in _markers_for_line(component_markers, token.line):
                    if marker not in component_mappings:
                        component_mappings[marker] = SourceMapping(
                            requirement_id=marker,
                            marker_type="component",
                            target_name=name.value,
                            target_kind="module",
                            line=name.line,
                        )
                for output_marker in _output_markers_for_line(output_markers, token.line):
                    output_mappings[output_marker["id"]] = SourceOutputMapping(
                        output_id=output_marker["id"],
                        component_ids=output_marker.get("component_ids", []),
                        target_name=name.value,
                        target_kind="module",
                        line=name.line,
                        module_name=output_marker.get("module_name"),
                        filename=output_marker.get("filename"),
                        required=output_marker.get("required"),
                    )
                if name.value == "main_model":
                    pending_main_body = True
        elif lower == "function":
            pass
        elif token.kind == "identifier":
            next_token = _next_non_comment(tokens, index)
            previous = _previous_non_comment(tokens, index)
            if (
                next_token
                and next_token.value == "="
                and brace_depth == 0
                and (previous is None or previous.value in {";", "}"})
            ):
                expression, end_index = _assignment_expression(tokens, index + 2)
                assignments[token.value] = expression
                assignment_lines[token.value] = token.line
                if token.value not in parameter_names:
                    parameter_names.append(token.value)
                marker = _marker_for_line(requirement_markers, token.line)
                if marker and marker not in requirement_mappings:
                    requirement_mappings[marker] = SourceMapping(
                        requirement_id=marker,
                        marker_type="requirement",
                        target_name=token.value,
                        target_kind="parameter",
                        line=token.line,
                    )
                for component_marker in _markers_for_line(component_markers, token.line):
                    if component_marker not in component_mappings:
                        component_mappings[component_marker] = SourceMapping(
                            requirement_id=component_marker,
                            marker_type="component",
                            target_name=token.value,
                            target_kind="parameter",
                            line=token.line,
                        )
                for dependency_marker in _dependency_markers_for_line(
                    dependency_markers,
                    token.line,
                ):
                    dependency_mappings.append(
                        SourceDependencyMapping(
                            from_id=dependency_marker[0],
                            to_id=dependency_marker[1],
                            target_name=token.value,
                            target_kind="parameter",
                            line=token.line,
                        )
                    )
                index = end_index
                continue
            if (
                next_token
                and next_token.value == "("
                and previous
                and previous.value.lower() not in {"module", "function"}
                and brace_depth == 0
            ):
                if token.value not in {"assert", "echo"}:
                    top_level_calls.append(token.value)
                if token.value not in {"main_model", "render_selected_output", "assert", "echo"}:
                    top_level_geometry_calls.append(token.value)
        index += 1
    return SourceMetadata(
        source_hash=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        source_size_bytes=len(source.encode("utf-8")),
        line_count=len(source.splitlines()),
        module_names=module_names,
        parameter_names=parameter_names,
        include_paths=include_paths,
        top_level_calls=top_level_calls,
        top_level_geometry_calls=top_level_geometry_calls,
        requirement_mappings=requirement_mappings,
        feature_mappings=feature_mappings,
        component_mappings=component_mappings,
        dependency_mappings=dependency_mappings,
        output_mappings=output_mappings,
        geometry_mappings=[
            SourceGeometryMapping(
                geometry_type=attributes["type"],
                attributes=attributes,
                line=line,
                feature_id=_last_marker_for_line(feature_markers, line),
            )
            for line, attributes in sorted(geometry_markers.items())
            if "type" in attributes
        ],
        assignments=assignments,
        assignment_lines=assignment_lines,
        sections=sections,
        has_assertion=any(token.value.lower() == "assert" for token in tokens),
        has_unbalanced_braces=unbalanced_braces or brace_depth != 0,
        has_unbalanced_parentheses=unbalanced_parentheses or paren_depth != 0,
        main_model_body_empty="main_model" in module_names and main_body_tokens == 0,
    )


def _sections(comments: list[SourceToken]) -> set[str]:
    sections: set[str] = set()
    for comment in comments:
        normalized = re.sub(r"[^a-z0-9]+", "_", comment.value.lower()).strip("_")
        if "user_parameters" in normalized:
            sections.add("user_parameters")
        if "derived_values" in normalized:
            sections.add("derived_values")
        if "validation" in normalized:
            sections.add("validation")
        if "modules" in normalized or "feature_modules" in normalized:
            sections.add("modules")
        if "final_model" in normalized:
            sections.add("final_model")
        if "assumptions" in normalized:
            sections.add("assumptions")
        if "print_notes" in normalized or "print_orientation" in normalized:
            sections.add("print_notes")
    return sections


def _pending_markers(
    comments: list[SourceToken],
) -> tuple[
    dict[int, str],
    dict[int, list[str]],
    dict[int, list[str]],
    dict[int, list[tuple[str, str]]],
    dict[int, list[dict[str, Any]]],
    dict[int, dict[str, str]],
]:
    requirement_markers: dict[int, str] = {}
    feature_markers: dict[int, list[str]] = {}
    component_markers: dict[int, list[str]] = {}
    dependency_markers: dict[int, list[tuple[str, str]]] = {}
    output_markers: dict[int, list[dict[str, Any]]] = {}
    geometry_markers: dict[int, dict[str, str]] = {}
    for comment in comments:
        requirement_match = re.search(r"@volundr-requirement\s+([A-Za-z0-9_.-]+)", comment.value)
        if requirement_match:
            requirement_markers[comment.line] = requirement_match.group(1)
        for feature_match in re.finditer(r"@volundr-feature\s+([A-Za-z0-9_.-]+)", comment.value):
            feature_markers.setdefault(comment.line, []).append(feature_match.group(1))
        for component_match in re.finditer(
            r"@volundr-component\s+([A-Za-z0-9_.-]+)",
            comment.value,
        ):
            component_markers.setdefault(comment.line, []).append(component_match.group(1))
        for dependency_match in re.finditer(
            r"@volundr-dependency\s+([A-Za-z0-9_.-]+)\s*->\s*([A-Za-z0-9_.-]+)",
            comment.value,
        ):
            dependency_markers.setdefault(comment.line, []).append(
                (dependency_match.group(1), dependency_match.group(2))
            )
        for output_match in re.finditer(r"@volundr-output\s+([A-Za-z0-9_.-]+)(.*)", comment.value):
            remainder = output_match.group(2)
            components_match = re.search(
                r"components=([A-Za-z0-9_.-]+(?:,[A-Za-z0-9_.-]+)*)",
                remainder,
            )
            module_match = re.search(r"module=([A-Za-z_][A-Za-z0-9_]*)", remainder)
            filename_match = re.search(r"filename=([A-Za-z0-9_.-]+)", remainder)
            required_match = re.search(r"required=(true|false)", remainder, flags=re.IGNORECASE)
            component_ids = [
                component_id.strip()
                for component_id in (components_match.group(1) if components_match else "").split(",")
                if component_id.strip()
            ]
            output_markers.setdefault(comment.line, []).append(
                {
                    "id": output_match.group(1),
                    "component_ids": component_ids,
                    "module_name": module_match.group(1) if module_match else None,
                    "filename": filename_match.group(1) if filename_match else None,
                    "required": _bool_text(required_match.group(1)) if required_match else None,
                }
            )
        geometry_match = re.search(r"@volundr-geometry\s+(.+)", comment.value)
        if geometry_match:
            geometry_markers[comment.line] = _geometry_attributes(geometry_match.group(1))
    return (
        requirement_markers,
        feature_markers,
        component_markers,
        dependency_markers,
        output_markers,
        geometry_markers,
    )


def _geometry_attributes(text: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for key, value in re.findall(r"([A-Za-z_][A-Za-z0-9_-]*)=([^,\s]+)", text):
        attributes[key] = value.strip().strip('"')
    return attributes


def _marker_for_line(markers: dict[int, str], line: int) -> str | None:
    candidates = [marker_line for marker_line in markers if 0 <= line - marker_line <= 4]
    return markers[max(candidates)] if candidates else None


def _markers_for_line(markers: dict[int, list[str]], line: int) -> list[str]:
    candidates = [marker_line for marker_line in markers if 0 <= line - marker_line <= 4]
    if not candidates:
        return []
    result: list[str] = []
    for marker_line in sorted(candidates):
        result.extend(markers[marker_line])
    return result


def _last_marker_for_line(markers: dict[int, list[str]], line: int) -> str | None:
    candidates = _markers_for_line(markers, line)
    return candidates[-1] if candidates else None


def _dependency_markers_for_line(
    markers: dict[int, list[tuple[str, str]]],
    line: int,
) -> list[tuple[str, str]]:
    candidates = [marker_line for marker_line in markers if 0 <= line - marker_line <= 4]
    result: list[tuple[str, str]] = []
    for marker_line in sorted(candidates):
        result.extend(markers[marker_line])
    return result


def _output_markers_for_line(
    markers: dict[int, list[dict[str, Any]]],
    line: int,
) -> list[dict[str, Any]]:
    candidates = [marker_line for marker_line in markers if 0 <= line - marker_line <= 4]
    result: list[dict[str, Any]] = []
    for marker_line in sorted(candidates):
        result.extend(markers[marker_line])
    return result


def _next_non_comment(tokens: list[SourceToken], index: int) -> SourceToken | None:
    return tokens[index + 1] if index + 1 < len(tokens) else None


def _previous_non_comment(tokens: list[SourceToken], index: int) -> SourceToken | None:
    return tokens[index - 1] if index > 0 else None


def _next_identifier(tokens: list[SourceToken], index: int) -> SourceToken | None:
    for token in tokens[index + 1 : index + 4]:
        if token.kind == "identifier":
            return token
    return None


def _assignment_expression(tokens: list[SourceToken], index: int) -> tuple[str, int]:
    parts: list[str] = []
    while index < len(tokens):
        token = tokens[index]
        if token.value == ";":
            return " ".join(parts), index
        parts.append(token.value)
        index += 1
    return " ".join(parts), index


def _evaluate_constants(assignments: dict[str, str]) -> dict[str, float]:
    constants: dict[str, float] = {}
    remaining = dict(assignments)
    for _ in range(len(remaining) + 1):
        progressed = False
        for name, expression in list(remaining.items()):
            value = _eval_expression(expression, constants)
            if value is not None:
                constants[name] = value
                del remaining[name]
                progressed = True
        if not progressed:
            break
    return constants


def _eval_expression(expression: str, constants: dict[str, float]) -> float | None:
    tokens = re.findall(r"\$?[A-Za-z_][A-Za-z0-9_$]*|\d+(?:\.\d+)?|\.\d+|[()+\-*/]", expression)
    if not tokens:
        return None
    position = 0

    def parse_expression() -> float | None:
        nonlocal position
        value = parse_term()
        while position < len(tokens) and tokens[position] in {"+", "-"}:
            operator = tokens[position]
            position += 1
            rhs = parse_term()
            if value is None or rhs is None:
                return None
            value = value + rhs if operator == "+" else value - rhs
        return value

    def parse_term() -> float | None:
        nonlocal position
        value = parse_factor()
        while position < len(tokens) and tokens[position] in {"*", "/"}:
            operator = tokens[position]
            position += 1
            rhs = parse_factor()
            if value is None or rhs is None:
                return None
            if operator == "/" and rhs == 0:
                return None
            value = value * rhs if operator == "*" else value / rhs
        return value

    def parse_factor() -> float | None:
        nonlocal position
        if position >= len(tokens):
            return None
        token = tokens[position]
        if token in {"+", "-"}:
            position += 1
            value = parse_factor()
            if value is None:
                return None
            return value if token == "+" else -value
        if token == "(":
            position += 1
            value = parse_expression()
            if position >= len(tokens) or tokens[position] != ")":
                return None
            position += 1
            return value
        position += 1
        if re.fullmatch(r"\d+(?:\.\d+)?|\.\d+", token):
            return float(token)
        return constants.get(token)

    value = parse_expression()
    return value if value is not None and position == len(tokens) else None


def _dimension_tolerance(dimension: dict[str, Any]) -> float:
    tolerance = dimension.get("tolerance")
    try:
        return float(tolerance) if tolerance is not None else 1e-6
    except (TypeError, ValueError):
        return 1e-6


def _repeated_numeric_literals(source: str) -> list[str]:
    stripped = "\n".join(line.split("//", 1)[0] for line in source.splitlines())
    numbers = re.findall(r"(?<![A-Za-z_])\b(?:[2-9]\d|\d{3,})(?:\.\d+)?\b", stripped)
    repeated = sorted({number for number in numbers if numbers.count(number) >= 3})
    return repeated


def _format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def _bool_text(value: str) -> bool:
    return value.strip().lower() == "true"


def _requires_output_selector(design_plan: dict[str, Any] | None) -> bool:
    if design_plan is None:
        return False
    outputs = design_plan.get("printable_outputs", [])
    return any(isinstance(output, dict) and output.get("id") for output in outputs)


def _finding(
    rule_id: str,
    category: str,
    title: str,
    *,
    severity: str = "critical",
    blocking: bool = True,
    line: int | None = None,
    detected_value: str | None = None,
    threshold_value: str | None = None,
    related_requirement_id: str | None = None,
) -> SourceContractFinding:
    return SourceContractFinding(
        rule_id=rule_id,
        category=category,
        severity=severity,
        is_blocking=blocking,
        title=title,
        explanation=title,
        suggested_correction="Revise the generated OpenSCAD to satisfy the Volundr source contract.",
        detected_value=detected_value,
        threshold_value=threshold_value,
        source_line_start=line,
        source_line_end=line,
        related_requirement_id=related_requirement_id,
    )
