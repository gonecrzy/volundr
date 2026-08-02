"""Deterministic CadQuery source scaffolding.

The provider supplies geometry functions only.  Volundr owns the runtime
contract, identities, output manifest, and build entrypoint rendered here.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import textwrap
from dataclasses import dataclass, field
from typing import Any

from app.services.cad.parameter_effects import (
    build_parameter_effect_contract,
    classify_derived_dependency_findings,
)
from app.services.cad.patterns import (
    build_pattern_manifest,
    normalize_pattern_specs,
    validate_pattern_specs,
)
from app.services.cad.python_symbols import analyze_scaffold_source


SCAFFOLD_VERSION = "cadquery-scaffold-v1"
_FENCE_RE = re.compile(r"```(?:python|py|cadquery)\s*(?P<source>.*?)```", re.IGNORECASE | re.DOTALL)
_AI_BEGIN = "# VOLUNDR_AI_BEGIN "
_AI_END = "# VOLUNDR_AI_END "


class ScaffoldSourceError(ValueError):
    pass


@dataclass(frozen=True)
class ScaffoldRender:
    source: str
    scaffold_hash: str
    scaffold_skeleton: str
    expected_geometry_functions: tuple[str, ...]
    derived_parameter_manifest: list[dict[str, Any]] = field(default_factory=list)
    parameter_effect_manifest: list[dict[str, Any]] = field(default_factory=list)
    pattern_manifest: list[dict[str, Any]] = field(default_factory=list)
    version: str = SCAFFOLD_VERSION


def extract_geometry_functions(
    raw_output: str,
    expected_function_names: set[str],
) -> dict[str, str]:
    """Extract only the provider-owned top-level geometry functions."""

    matches = list(_FENCE_RE.finditer(raw_output))
    if not matches:
        raise ScaffoldSourceError("geometry functions must be returned in a fenced Python block")
    source = matches[0].group("source").strip()
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ScaffoldSourceError(f"invalid geometry function syntax: {exc.msg}") from exc

    function_nodes: list[ast.FunctionDef] = []
    for node in tree.body:
        if isinstance(node, ast.Import) and len(node.names) == 1:
            alias = node.names[0]
            if alias.name == "cadquery" and alias.asname == "cq":
                continue
        if not isinstance(node, ast.FunctionDef):
            raise ScaffoldSourceError("only geometry function definitions are allowed")
        function_nodes.append(node)
    if not function_nodes:
        raise ScaffoldSourceError("only geometry function definitions are allowed")

    functions: dict[str, str] = {}
    for node in function_nodes:
        if node.decorator_list:
            raise ScaffoldSourceError("geometry functions cannot declare runtime registrations")
        if node.name not in expected_function_names:
            raise ScaffoldSourceError(f"unexpected geometry function: {node.name}")
        if node.name in functions:
            raise ScaffoldSourceError(f"duplicate geometry function: {node.name}")
        positional = list(node.args.posonlyargs) + list(node.args.args)
        expected_args = ["body", "params"] if "feature" in node.name else ["params"]
        if [argument.arg for argument in positional] != expected_args:
            raise ScaffoldSourceError(
                f"geometry function {node.name} must accept ({', '.join(expected_args)})"
            )
        if node.args.defaults or node.args.kwonlyargs or node.args.vararg or node.args.kwarg:
            raise ScaffoldSourceError(f"geometry function {node.name} has unsupported arguments")
        for child in ast.walk(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                raise ScaffoldSourceError("geometry functions cannot contain imports")
            if isinstance(child, ast.Call) and _call_name(child.func) in {
                "ParameterSpec",
                "PrintableOutput",
                "Product",
                "component",
                "feature",
                "shared_helper",
                "protected_interface",
            }:
                raise ScaffoldSourceError("geometry functions cannot create runtime registrations")
        segment = ast.get_source_segment(source, node)
        functions[node.name] = textwrap.dedent(segment or ast.unparse(node)).strip()

    missing = expected_function_names - functions.keys()
    if missing:
        raise ScaffoldSourceError(
            "missing geometry functions: " + ", ".join(sorted(missing))
        )
    return functions


def render_cadquery_scaffold(
    design_plan: dict[str, Any],
    geometry_functions: dict[str, str],
) -> ScaffoldRender:
    """Render canonical source around provider-owned geometry functions."""

    design_plan = normalize_pattern_specs(design_plan)
    validate_pattern_specs(design_plan)
    components = [item for item in design_plan.get("components", []) or [] if isinstance(item, dict)]
    features = [item for item in design_plan.get("features", []) or [] if isinstance(item, dict)]
    outputs = [item for item in design_plan.get("printable_outputs", []) or [] if isinstance(item, dict)]
    if not components or not outputs:
        raise ScaffoldSourceError("Design Plan must define components and printable outputs")

    component_ids = [str(item.get("id")) for item in components if item.get("id")]
    feature_by_id = {str(item["id"]): item for item in features if item.get("id")}
    component_by_id = {str(item["id"]): item for item in components if item.get("id")}
    expected_functions: list[str] = []
    for component_id in component_ids:
        expected_functions.append(_component_geometry_name(component_id))
    for feature_id, feature in feature_by_id.items():
        if feature.get("component_id") in component_by_id:
            expected_functions.append(_feature_geometry_name(feature_id))
    expected = tuple(expected_functions)
    missing = set(expected) - set(geometry_functions)
    extra = set(geometry_functions) - set(expected)
    if missing:
        raise ScaffoldSourceError("missing geometry functions: " + ", ".join(sorted(missing)))
    if extra:
        raise ScaffoldSourceError("unexpected geometry functions: " + ", ".join(sorted(extra)))

    effect_contract = build_parameter_effect_contract(design_plan)
    dependency_findings = classify_derived_dependency_findings(
        effect_contract,
        source="\n\n".join(geometry_functions.values()),
    )
    blocking_dependency_findings = [
        item
        for item in dependency_findings
        if item.get("blocking", item.get("is_blocking", True))
    ]
    if blocking_dependency_findings:
        raise ScaffoldSourceError("approved derived-parameter dependency graph is invalid")

    lines: list[str] = [
        "# VOLUNDR_SCAFFOLD_VERSION: " + SCAFFOLD_VERSION,
        "# VOLUNDR_SCAFFOLD_HASH: __PLACEHOLDER__",
        "import cadquery as cq",
        "from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product, component, feature, shared_helper, protected_interface, resolve_pattern_points, place_pattern_cutters",
        "",
        "PARAMETERS = [",
    ]
    parameter_entries = [
        parameter
        for parameter in design_plan.get("parameters", []) or []
        if isinstance(parameter, dict)
    ]
    parameter_ids = {
        str(parameter.get("id"))
        for parameter in parameter_entries
        if parameter.get("id")
    }
    for derived in design_plan.get("derived_parameters", []) or []:
        if not isinstance(derived, dict) or not derived.get("id"):
            continue
        if str(derived["id"]) in parameter_ids:
            continue
        derived_record = next(
            (
                item
                for item in effect_contract.get("derived_parameters", [])
                if item.get("parameter_id") == str(derived["id"])
            ),
            None,
        )
        resolved_value = derived_record.get("resolved_value") if derived_record else None
        if resolved_value is None:
            dependency_finding = next(
                (
                    item
                    for item in dependency_findings
                    if str(item.get("parameter_id") or "") == str(derived["id"])
                ),
                None,
            )
            if dependency_finding and not dependency_finding.get(
                "blocking", dependency_finding.get("is_blocking", True)
            ):
                resolved_value = derived.get("value")
                if resolved_value is None:
                    continue
            if resolved_value is None:
                if not _derived_parameter_required_by_execution(effect_contract, str(derived["id"])):
                    # Keep unresolved planning metadata out of PARAMETERS.
                    # It remains present in the immutable plan/effect
                    # evidence, but an ordinary one-off design does not need
                    # a provider's unused formula to execute.
                    continue
                raise ScaffoldSourceError(f"derived parameter {derived['id']} could not be resolved")
        parameter_entries.append(
            {
                **derived,
                "value": resolved_value,
                "editable": False,
                "protected": False,
                "source": "calculated",
            }
        )
    for parameter in parameter_entries:
        if not isinstance(parameter, dict) or not parameter.get("id"):
            continue
        lines.append("    " + _parameter_spec_expression(parameter) + ",")
    lines.extend(["]", ""])

    pattern_manifest = _resolved_pattern_manifest(design_plan, effect_contract)
    if pattern_manifest:
        lines.extend([
            "def _volundr_apply_patterns(params):",
            "    return params.with_derived_values({",
        ])
        for pattern in pattern_manifest:
            lines.append(
                f"        {_literal(pattern['point_parameter_id'])}: "
                f"resolve_pattern_points({_python_literal(pattern['specification'])}, params).points,"
            )
        lines.extend(["    })", ""])

    for component_id in component_ids:
        function_name = _component_geometry_name(component_id)
        lines.extend(_ai_block(function_name, geometry_functions[function_name]))
        lines.extend(
            [
                f'@component("{component_id}")',
                f"def {_component_builder_name(component_id)}(params):",
                f"    body = {function_name}(params)",
            ]
        )
        for feature_id in _features_for_component(features, component_id):
            lines.append(f"    body = {_feature_wrapper_name(feature_id)}(body, params)")
        lines.extend(["    return body", ""])

    for feature_id, feature in feature_by_id.items():
        component_id = feature.get("component_id")
        if component_id not in component_by_id:
            continue
        function_name = _feature_geometry_name(feature_id)
        lines.extend(_ai_block(function_name, geometry_functions[function_name]))
        lines.extend(
            [
                f'@feature("{feature_id}", component="{component_id}")',
                f"def {_feature_wrapper_name(feature_id)}(body, params):",
                f"    return {function_name}(body, params)",
                "",
            ]
        )

    lines.extend(["def build(params):"])
    if pattern_manifest:
        lines.append("    params = _volundr_apply_patterns(params)")
    for component_id in component_ids:
        lines.append(f"    {_component_builder_name(component_id)}_model = {_component_builder_name(component_id)}(params)")
    lines.append("    return Product(")
    lines.append("        parameters=PARAMETERS,")
    lines.append("        outputs=[")
    for output in outputs:
        output_id = _required_id(output, "id", "output")
        output_components = [str(item) for item in output.get("component_ids", []) if item]
        if not output_components and output.get("component_id"):
            output_components = [str(output["component_id"])]
        if not output_components or any(item not in component_by_id for item in output_components):
            raise ScaffoldSourceError(f"output {output_id} has invalid component ownership")
        model_expression = _model_expression(output_components)
        label = output.get("label") or output_id
        required = bool(output.get("required", True))
        expected_solid_count = int(output.get("expected_solid_count") or 1)
        allow_disconnected = bool(output.get("allow_disconnected_solids", False))
        lines.append(
            "            PrintableOutput("
            f"output_id={_literal(output_id)}, label={_literal(str(label))}, model={model_expression}, "
            f"component_ids={_literal_tuple(output_components)}, quantity={int(output.get('quantity') or 1)}, "
            f"required={required!r}, expected_solid_count={expected_solid_count}, "
            f"allow_disconnected_solids={allow_disconnected!r}),"
        )
    lines.extend(["        ],", '        schema_version="cadquery-v1",', "    )", ""])
    source = "\n".join(lines).rstrip() + "\n"
    skeleton = _skeleton(source)
    scaffold_hash = hashlib.sha256(skeleton.encode("utf-8")).hexdigest()
    source = source.replace("__PLACEHOLDER__", scaffold_hash)
    skeleton = _skeleton(source)
    return ScaffoldRender(
        source=source,
        scaffold_hash=scaffold_hash,
        scaffold_skeleton=skeleton,
        expected_geometry_functions=expected,
        derived_parameter_manifest=list(effect_contract.get("derived_parameters", [])),
        parameter_effect_manifest=list(effect_contract.get("functions", [])),
        pattern_manifest=pattern_manifest,
    )


def _resolved_pattern_manifest(
    design_plan: dict[str, Any], effect_contract: dict[str, Any]
) -> list[dict[str, Any]]:
    values = {
        str(item.get("id")): item.get("value")
        for item in design_plan.get("parameters", []) or []
        if isinstance(item, dict) and item.get("id")
    }
    values.update({
        str(item.get("parameter_id")): item.get("resolved_value")
        for item in effect_contract.get("derived_parameters", []) or []
        if isinstance(item, dict) and item.get("parameter_id")
    })
    # Region-distributed one-off layouts are plan guidance, not one of the
    # deterministic point helpers. Keep them in plan/effect evidence while
    # leaving their local placement to the owning provider function.
    resolved_plan = dict(design_plan)
    resolved_plan["patterns"] = [
        pattern
        for pattern in design_plan.get("patterns", []) or []
        if isinstance(pattern, dict)
        and str(pattern.get("pattern_type") or "").lower() != "distributed_within_region"
    ]
    return build_pattern_manifest(resolved_plan, resolved_values=values)


def validate_scaffold_integrity(source: str, rendered: ScaffoldRender) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if _skeleton(source) != rendered.scaffold_skeleton:
        findings.append(
            {
                "rule_id": "cadquery.scaffold_owned_region_changed",
                "category": "source_contract",
                "severity": "critical",
                "is_blocking": True,
                "message": "A scaffold-owned CadQuery source region was changed.",
            }
        )
    if hashlib.sha256(_skeleton(source).encode("utf-8")).hexdigest() != rendered.scaffold_hash:
        findings.append(
            {
                "rule_id": "cadquery.scaffold_hash_mismatch",
                "category": "source_contract",
                "severity": "critical",
                "is_blocking": True,
                "message": "Rendered CadQuery source does not match its scaffold fingerprint.",
            }
        )
    return findings


def validate_scaffold_source(source: str) -> list[dict[str, Any]]:
    """Validate the embedded scaffold fingerprint without provider context."""

    if "VOLUNDR_SCAFFOLD_VERSION:" not in source:
        return []
    match = re.search(r"^# VOLUNDR_SCAFFOLD_HASH: (?P<hash>[0-9a-f]{64})$", source, re.MULTILINE)
    actual_hash = hashlib.sha256(_skeleton(source).encode("utf-8")).hexdigest()
    if match is None or match.group("hash") != actual_hash:
        return [
            {
                "rule_id": "cadquery.scaffold_owned_region_changed",
                "category": "source_contract",
                "severity": "critical",
                "is_blocking": True,
                "explanation": "A scaffold-owned CadQuery source region was changed.",
                "suggested_correction": "Regenerate the source from the approved Volundr scaffold.",
            }
        ]
    return analyze_scaffold_source(source)


def geometry_function_names(design_plan: dict[str, Any]) -> tuple[str, ...]:
    return render_cadquery_scaffold(
        design_plan,
        {name: _empty_geometry_function(name) for name in _expected_geometry_function_names(design_plan)},
    ).expected_geometry_functions


def _expected_geometry_function_names(plan: dict[str, Any]) -> set[str]:
    names = {
        _component_geometry_name(str(item["id"]))
        for item in plan.get("components", []) or []
        if isinstance(item, dict) and item.get("id")
    }
    names.update(
        _feature_geometry_name(str(item["id"]))
        for item in plan.get("features", []) or []
        if isinstance(item, dict) and item.get("id") and item.get("component_id")
    )
    return names


def _ai_block(function_name: str, function_source: str) -> list[str]:
    return [_AI_BEGIN + function_name, *function_source.splitlines(), _AI_END + function_name, ""]


def _skeleton(source: str) -> str:
    lines = source.splitlines()
    output: list[str] = []
    in_ai = False
    for line in lines:
        if line.startswith(_AI_BEGIN):
            in_ai = True
            output.append(line)
            output.append("# VOLUNDR_AI_BODY_OMITTED")
            continue
        if line.startswith("# VOLUNDR_SCAFFOLD_HASH:"):
            output.append("# VOLUNDR_SCAFFOLD_HASH: <omitted>")
            continue
        if line.startswith(_AI_END):
            in_ai = False
            output.append(line)
            continue
        if not in_ai:
            output.append(line)
    return "\n".join(output).rstrip() + "\n"


def _parameter_spec_expression(parameter: dict[str, Any]) -> str:
    parameter_id = _required_id(parameter, "id", "parameter")
    parameter_type = str(
        parameter.get("type")
        or parameter.get("parameter_type")
        or _infer_type(parameter)
    )
    parameter_type = {
        "number": "float",
        "integer": "int",
        "boolean": "bool",
    }.get(parameter_type, parameter_type)
    default = parameter.get("default", parameter.get("value"))
    if default is None:
        raise ScaffoldSourceError(f"parameter {parameter_id} has no canonical default")
    fields = [
        f"id={_literal(parameter_id)}",
        f"label={_literal(str(parameter.get('label') or parameter_id))}",
        f"type={_literal(parameter_type)}",
        f"default={_literal(default)}",
    ]
    for key in ("unit", "min_value", "max_value", "source_requirement_id", "source"):
        if parameter.get(key) is not None:
            fields.append(f"{key}={_literal(parameter[key])}")
    if parameter.get("choices"):
        fields.append(f"choices={_literal_tuple(parameter['choices'])}")
    fields.extend(
        [
            f"editable={bool(parameter.get('editable', True))!r}",
            f"protected={bool(parameter.get('protected', False))!r}",
        ]
    )
    return "ParameterSpec(" + ", ".join(fields) + ")"


def _features_for_component(features: list[dict[str, Any]], component_id: str) -> list[str]:
    return [
        str(feature["id"])
        for feature in features
        if feature.get("id") and feature.get("component_id") == component_id
    ]


def _model_expression(component_ids: list[str]) -> str:
    expressions = [f"{_component_builder_name(component_id)}_model" for component_id in component_ids]
    if len(expressions) == 1:
        return expressions[0]
    return "cq.Compound.makeCompound([" + ", ".join(expressions) + "])"


def _component_geometry_name(component_id: str) -> str:
    return "_ai_component_" + _safe_identifier(component_id)


def _component_builder_name(component_id: str) -> str:
    return "build_component_" + _safe_identifier(component_id)


def _feature_geometry_name(feature_id: str) -> str:
    return "_ai_feature_" + _safe_identifier(feature_id)


def _feature_wrapper_name(feature_id: str) -> str:
    return "apply_feature_" + _safe_identifier(feature_id)


def _safe_identifier(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not normalized or normalized[0].isdigit():
        normalized = "id_" + normalized
    return normalized


def _required_id(payload: dict[str, Any], key: str, kind: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ScaffoldSourceError(f"{kind} is missing a stable {key}")
    return value


def _derived_parameter_required_by_execution(contract: dict[str, Any], parameter_id: str) -> bool:
    if parameter_id in {str(value) for value in contract.get("exposed_control_ids", []) or []}:
        return True
    for function in contract.get("functions", []) or []:
        if not isinstance(function, dict):
            continue
        if parameter_id in {
            str(value)
            for key in ("required_direct_parameters", "required_inputs", "allowed_derived_parameters")
            for value in function.get(key, []) or []
        }:
            return True
        if any(
            isinstance(effect, dict) and str(effect.get("parameter_id") or "") == parameter_id
            for effect in function.get("required_parameter_effects", []) or []
        ):
            return True
    for pattern in contract.get("patterns", []) or []:
        if not isinstance(pattern, dict) or not pattern.get("effect_required"):
            continue
        specification = pattern.get("specification") if isinstance(pattern.get("specification"), dict) else pattern
        if parameter_id in {
            str(specification.get(key) or "")
            for key in (
                "count_parameter_id",
                "spacing_parameter_id",
                "rows_parameter_id",
                "columns_parameter_id",
                "row_spacing_parameter_id",
                "column_spacing_parameter_id",
                "radius_parameter_id",
            )
        }:
            return True
    return False


def _literal(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ": "))


def _python_literal(value: Any) -> str:
    return repr(value)


def _literal_tuple(values: Any) -> str:
    items = list(values) if isinstance(values, (list, tuple)) else [values]
    suffix = ",)" if len(items) == 1 else ")"
    return "(" + ", ".join(_literal(item) for item in items) + suffix


def _infer_type(value: Any) -> str:
    if isinstance(value, dict):
        unit = str(value.get("unit") or "").lower()
        parameter_id = str(value.get("id") or "").lower()
        if unit == "count" or parameter_id.endswith("_count") or parameter_id in {"count", "quantity"}:
            return "int"
        if unit in {"mm", "millimeter", "millimeters", "deg", "degree", "degrees"}:
            return "float"
        value = value.get("value")
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"


def _call_name(node: ast.expr) -> str | None:
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None


def _empty_geometry_function(name: str) -> str:
    args = "body, params" if "feature" in name else "params"
    return f"def {name}({args}):\n    raise RuntimeError('geometry body not supplied')"
