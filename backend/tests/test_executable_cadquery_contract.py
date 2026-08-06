import json

import pytest

from app.services.executable_cadquery.contract import (
    ExecutableCadQueryContractError,
    parse_executable_cadquery_response,
    RESPONSE_SCHEMA_VERSION,
)
from app.services.executable_cadquery.fixtures import (
    FROZEN_MOUNTING_BRACKET_CONTRACT,
    valid_mounting_bracket_source,
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
