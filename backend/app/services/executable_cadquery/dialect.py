"""Machine-readable description of the existing cadquery-v1 source policy."""

from __future__ import annotations

import hashlib
import json

from app.services.cad.cadquery_contract import (
    ALLOWED_TOP_LEVEL_NODE_TYPES,
    PARAMETER_SPEC_TYPES,
    RUNTIME_CONSTRUCTOR_KEYWORDS,
    RUNTIME_IMPORT_NAMES,
    RUNTIME_METADATA_DECORATOR_NAMES,
    SAFE_CALL_NAMES,
    UNSAFE_CALL_NAMES,
)


CADQUERY_V1_SOURCE_DIALECT_VERSION = "cadquery-v1-source-dialect"

# This is deliberately protocol-only geometry. It demonstrates the exact
# module shape without teaching a construction strategy for the live fixture.
CADQUERY_V1_SOURCE_SKELETON = '''import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = (ParameterSpec(
    id="example_size",
    label="Example size",
    type="float",
    default=1.0,
    unit="mm",
),)


def _make_model():
    return cq.Workplane("XY").box(1.0, 1.0, 1.0)


def build(params):
    model = _make_model()
    return Product(
        outputs=(PrintableOutput(
            output_id="mounting_bracket",
            label="Complete output",
            model=model,
            component_id="mounting_bracket",
            required=True,
            expected_solid_count=1,
            allow_disconnected_solids=False,
        ),),
        parameters=PARAMETERS,
    )
'''


def _policy_without_hash() -> dict[str, object]:
    return {
        "version": CADQUERY_V1_SOURCE_DIALECT_VERSION,
        "contract_version": "cadquery-v1",
        "required_module_structure": [
            "approved imports at module scope",
            "module-level literal/static parameter declarations",
            "optional helper function definitions",
            "exactly one build(params) entry point",
            "build(params) returns Product",
            "Product registers at least one PrintableOutput",
            "PrintableOutput uses the canonical output ID and expected solid count",
            "PrintableOutput declares the disconnected-solid policy",
        ],
        "allowed_imports": {
            "cadquery": "import cadquery as cq",
            "volundr_cad.runtime": sorted(RUNTIME_IMPORT_NAMES),
        },
        "allowed_top_level_statements": [
            node_type.__name__ for node_type in ALLOWED_TOP_LEVEL_NODE_TYPES
        ]
        + ["ImportFrom"],
        "forbidden_top_level_statements": [
            "If",
            "For",
            "While",
            "Try",
            "With",
            "AsyncWith",
            "Expr",
            "Return",
            "Raise",
            "Assert",
            "Match",
        ],
        "permitted_metadata_classes": "ClassDef with only annotated parameter fields and no decorators or dynamic bases",
        "forbidden_anywhere": [
            "try/except",
            "with and async with",
            "imports inside functions",
            "global and nonlocal",
            "unsafe calls",
            "dynamic calls",
            "dunder attribute access",
            "unsupported imports",
            "direct filesystem or artifact writing",
            "eval, exec, and dynamic imports",
        ],
        "control_flow_inside_functions": {
            "if": True,
            "for": True,
            "while": True,
            "comprehensions": True,
            "local_assignments": True,
            "returns": True,
            "supported_function_calls": "Calls are permitted only under the cadquery-v1 call validator.",
            "try": False,
            "with": False,
            "imports": False,
            "global": False,
            "nonlocal": False,
        },
        "validator_policy_inputs": {
            "approved_runtime_imports": sorted(RUNTIME_IMPORT_NAMES),
            "approved_runtime_metadata_decorators": sorted(RUNTIME_METADATA_DECORATOR_NAMES),
            "approved_parameter_types": sorted(PARAMETER_SPEC_TYPES),
            "approved_safe_direct_calls": sorted(SAFE_CALL_NAMES),
            "forbidden_direct_calls": sorted(UNSAFE_CALL_NAMES),
            "runtime_constructor_keywords": {
                name: sorted(values) for name, values in sorted(RUNTIME_CONSTRUCTOR_KEYWORDS.items())
            },
        },
    }


def cadquery_v1_source_dialect() -> dict[str, object]:
    """Return the provider-facing policy generated from validator constants."""

    policy = _policy_without_hash()
    policy["hash"] = cadquery_v1_source_dialect_hash()
    return policy


def cadquery_v1_source_dialect_hash() -> str:
    encoded = json.dumps(
        _policy_without_hash(), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def cadquery_v1_source_skeleton_hash() -> str:
    return hashlib.sha256(CADQUERY_V1_SOURCE_SKELETON.encode("utf-8")).hexdigest()
