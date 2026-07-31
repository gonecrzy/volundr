from pathlib import Path

import pytest

from app.services.cad.source_scaffold import (
    ScaffoldSourceError,
    extract_geometry_functions,
    render_cadquery_scaffold,
    validate_scaffold_integrity,
    validate_scaffold_source,
)
from app.services.cad.cadquery_contract import validate_cadquery_source


PLAN = {
    "parameters": [
        {
            "id": "bottle_diameter",
            "label": "Bottle diameter",
            "type": "float",
            "value": 81.0,
            "unit": "mm",
            "protected": True,
            "source_requirement_id": "bottle_diameter",
        },
        {
            "id": "floor_thickness",
            "label": "Floor thickness",
            "type": "float",
            "value": 3.0,
            "unit": "mm",
            "protected": True,
        },
    ],
    "components": [{"id": "holder_body", "features": ["feature_snap_arm"]}],
    "features": [
        {
            "id": "feature_snap_arm",
            "component_id": "holder_body",
            "type": "retention",
            "required": True,
        }
    ],
    "printable_outputs": [
        {
            "id": "holder",
            "label": "Holder",
            "component_ids": ["holder_body"],
            "required": True,
            "expected_solid_count": 1,
            "allow_disconnected_solids": False,
        }
    ],
}


GEOMETRY = {
    "_ai_component_holder_body": """
def _ai_component_holder_body(params):
    return cq.Workplane("XY").box(params["bottle_diameter"], 20, params["floor_thickness"])
""",
    "_ai_feature_feature_snap_arm": """
def _ai_feature_feature_snap_arm(body, params):
    return body.union(cq.Workplane("XY").box(2, 2, params["floor_thickness"]))
""",
}


def test_scaffold_owns_canonical_contract_and_build_entrypoint() -> None:
    rendered = render_cadquery_scaffold(PLAN, GEOMETRY)

    assert 'ParameterSpec(id="bottle_diameter"' in rendered.source
    assert '@component("holder_body")' in rendered.source
    assert '@feature("feature_snap_arm", component="holder_body")' in rendered.source
    assert 'PrintableOutput(output_id="holder"' in rendered.source
    assert "def build(params):" in rendered.source
    assert rendered.scaffold_hash
    validate_cadquery_source(rendered.source)


def test_geometry_payload_rejects_scaffold_edits_and_unknown_functions() -> None:
    payload = """
```python
def _ai_component_holder_body(params):
    return cq.Workplane("XY").box(10, 10, 3)
def _ai_feature_feature_snap_arm(body, params):
    return body
```
"""
    functions = extract_geometry_functions(payload, set(GEOMETRY))
    rendered = render_cadquery_scaffold(PLAN, functions)

    assert validate_scaffold_integrity(rendered.source, rendered) == []
    mutated = rendered.source.replace('output_id="holder"', 'output_id="renamed"')
    findings = validate_scaffold_integrity(mutated, rendered)
    assert any(finding["rule_id"] == "cadquery.scaffold_owned_region_changed" for finding in findings)
    assert validate_scaffold_source(mutated)

    with pytest.raises(ScaffoldSourceError, match="unexpected geometry function"):
        extract_geometry_functions(
            payload.replace("_ai_feature_feature_snap_arm", "_ai_feature_other"),
            set(GEOMETRY),
        )


def test_geometry_payload_rejects_imports_and_runtime_registrations() -> None:
    with pytest.raises(ScaffoldSourceError, match="only geometry function definitions"):
        extract_geometry_functions(
            "```python\nimport os\ndef _ai_component_holder_body(params):\n    return None\n```",
            {"_ai_component_holder_body"},
        )


def test_geometry_payload_strips_only_the_duplicate_approved_cadquery_import() -> None:
    functions = extract_geometry_functions(
        "```python\nimport cadquery as cq\ndef _ai_component_holder_body(params):\n    return cq.Workplane(\"XY\")\n```",
        {"_ai_component_holder_body"},
    )

    assert list(functions) == ["_ai_component_holder_body"]
