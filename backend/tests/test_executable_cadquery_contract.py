import json

import pytest

from app.services.executable_cadquery.contract import (
    ExecutableCadQueryContractError,
    diagnose_cadquery_contract_error,
    parse_executable_cadquery_response,
    RESPONSE_SCHEMA_VERSION,
)
from app.services.executable_cadquery.fixtures import (
    FROZEN_MOUNTING_BRACKET_CONTRACT,
    valid_mounting_bracket_source,
)


def multi_output_contract() -> dict[str, object]:
    return {
        **FROZEN_MOUNTING_BRACKET_CONTRACT,
        "outputs": [
            {
                "output_id": "enclosure_base",
                "required": True,
                "output_type": "printable_component",
                "expected_solid_count": 1,
            },
            {
                "output_id": "enclosure_lid",
                "required": True,
                "output_type": "printable_component",
                "expected_solid_count": 1,
            },
        ],
        "requirements": [],
        "relationships": [],
        "protected_facts": [],
    }


def valid_multi_output_source() -> str:
    source = valid_mounting_bracket_source()
    return source.replace(
        'output_id="mounting_bracket",\n        label="Mounting bracket",\n        model=body,\n        component_id="mounting_bracket",',
        'output_id="enclosure_base",\n        label="Enclosure base",\n        model=body,\n        component_id="enclosure_base",',
    ).replace(
        '    ),))\n',
        '    ), PrintableOutput(\n        output_id="enclosure_lid",\n        label="Enclosure lid",\n        model=body,\n        component_id="enclosure_lid",\n        required=True,\n        expected_solid_count=1,\n        allow_disconnected_solids=False,\n    )))\n',
    )


def response_for(source: str) -> str:
    return source


def test_accepts_complete_source_and_preserves_source_bytes() -> None:
    source = valid_mounting_bracket_source()

    parsed = parse_executable_cadquery_response(
        response_for(source), FROZEN_MOUNTING_BRACKET_CONTRACT
    )

    assert parsed.schema_version == RESPONSE_SCHEMA_VERSION
    assert parsed.outputs[0].output_id == "mounting_bracket"
    assert parsed.outputs[0].source == source
    assert len(parsed.outputs[0].source_hash) == 64


def test_accepts_exactly_one_fenced_python_module() -> None:
    source = valid_mounting_bracket_source()

    parsed = parse_executable_cadquery_response(
        f"```python\n{source}\n```", FROZEN_MOUNTING_BRACKET_CONTRACT
    )

    assert parsed.outputs[0].source == source


def test_accepts_all_outputs_from_a_frozen_multi_output_contract() -> None:
    source = valid_multi_output_source()

    parsed = parse_executable_cadquery_response(source, multi_output_contract())

    assert [output.output_id for output in parsed.outputs] == ["enclosure_base", "enclosure_lid"]
    assert all(output.source == source for output in parsed.outputs)


@pytest.mark.parametrize(
    "raw_response, expected_kind",
    [
        ("", "response_empty_or_extraction_failure"),
        ("Here is the module:\n\n" + valid_mounting_bracket_source(), "response_empty_or_extraction_failure"),
        (
            f"```python\n{valid_mounting_bracket_source()}\n```\n```python\n{valid_mounting_bracket_source()}\n```",
            "response_empty_or_extraction_failure",
        ),
        ("not a complete module", "response_empty_or_extraction_failure"),
    ],
)
def test_separates_empty_and_extraction_failures(raw_response: str, expected_kind: str) -> None:
    with pytest.raises(ExecutableCadQueryContractError) as exc_info:
        parse_executable_cadquery_response(raw_response, FROZEN_MOUNTING_BRACKET_CONTRACT)

    assert exc_info.value.failure_kind == expected_kind


def test_separates_python_syntax_failure() -> None:
    with pytest.raises(ExecutableCadQueryContractError) as exc_info:
        parse_executable_cadquery_response(
            "def build(params):\n    return (", FROZEN_MOUNTING_BRACKET_CONTRACT
        )

    assert exc_info.value.failure_kind == "python_syntax_error"
    assert "invalid Python syntax" in str(exc_info.value)
    assert exc_info.value.extracted_source_hash
    assert exc_info.value.extracted_source == "def build(params):\n    return ("
    assert exc_info.value.diagnostic["code"] == "python_syntax_error"


def test_nested_import_diagnostic_points_to_nested_import_not_top_level_import() -> None:
    source = (
        "import cadquery as cq\n"
        "\n"
        "def build(params):\n"
        "    from math import sqrt\n"
        "    return cq.Workplane('XY')\n"
    )

    diagnostic = diagnose_cadquery_contract_error(
        source,
        "imports are only allowed at top level",
    )

    assert diagnostic["code"] == "nested_import_forbidden"
    assert diagnostic["line"] == 4
    assert diagnostic["node_type"] == "ImportFrom"
    assert diagnostic["enclosing_scope"] == "build"
    assert diagnostic["ast_path"] == "module.body[1].body[0]"


def test_rejects_canonical_output_identity_changes() -> None:
    source = valid_mounting_bracket_source().replace("mounting_bracket", "other")

    with pytest.raises(ExecutableCadQueryContractError, match="canonical output"):
        parse_executable_cadquery_response(
            response_for(source),
            FROZEN_MOUNTING_BRACKET_CONTRACT,
        )


@pytest.mark.parametrize(
    "source, expected_message",
    [
        (
            "import os\n\ndef build(params):\n    return Product(outputs=())\n",
            "import",
        ),
        (
            "import cadquery as cq\nfrom volundr_cad.runtime import PrintableOutput, Product\n\ndef build(params):\n    cq.exporters.export(cq.Workplane('XY'), 'out.step')\n    return Product(outputs=())\n",
            "artifact",
        ),
    ],
)
def test_reuses_existing_source_contract_safety(source: str, expected_message: str) -> None:
    with pytest.raises(ExecutableCadQueryContractError, match=expected_message) as exc_info:
        parse_executable_cadquery_response(
            response_for(source), FROZEN_MOUNTING_BRACKET_CONTRACT
        )
    assert exc_info.value.failure_kind == "source_contract_violation"


def test_contract_does_not_contain_construction_strategy() -> None:
    contract = FROZEN_MOUNTING_BRACKET_CONTRACT

    rendered = json.dumps(contract, sort_keys=True)
    assert "workplane" not in rendered.lower()
    assert "boolean" not in rendered.lower()
    assert "sketch order" not in rendered.lower()
