from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


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
class SourceParameterMapping:
    parameter_id: str
    target_name: str
    target_kind: str
    line: int
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceModuleFingerprint:
    module_name: str
    line: int
    normalized_hash: str
    called_modules: list[str] = field(default_factory=list)
    referenced_parameters: list[str] = field(default_factory=list)
    component_ids: list[str] = field(default_factory=list)
    feature_ids: list[str] = field(default_factory=list)
    output_ids: list[str] = field(default_factory=list)
    is_shared: bool = False


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
    parameter_mappings: dict[str, SourceParameterMapping] = field(default_factory=dict)
    dependency_mappings: list[SourceDependencyMapping] = field(default_factory=list)
    output_mappings: dict[str, SourceOutputMapping] = field(default_factory=dict)
    shared_module_mappings: dict[str, SourceMapping] = field(default_factory=dict)
    module_fingerprints: dict[str, SourceModuleFingerprint] = field(default_factory=dict)
    parameter_fingerprints: dict[str, str] = field(default_factory=dict)
    output_fingerprints: dict[str, str] = field(default_factory=dict)
    geometry_mappings: list[SourceGeometryMapping] = field(default_factory=list)
    assignments: dict[str, str] = field(default_factory=dict)
    assignment_lines: dict[str, int] = field(default_factory=dict)
    sections: set[str] = field(default_factory=set)
    has_assertion: bool = False
    has_unbalanced_braces: bool = False
    has_unbalanced_parentheses: bool = False
    source_body_empty: bool = False

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sections"] = sorted(self.sections)
        return payload


def evaluate_constants(assignments: dict[str, str]) -> dict[str, float]:
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
