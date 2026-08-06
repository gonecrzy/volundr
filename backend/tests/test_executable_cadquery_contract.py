import json

import pytest

from app.services.executable_cadquery.contract import (
    ExecutableCadQueryContractError,
    parse_executable_cadquery_response,
)
from app.services.executable_cadquery.fixtures import (
    FROZEN_MOUNTING_BRACKET_CONTRACT,
    valid_mounting_bracket_source,
)


def response_for(source: str, *, output_id: str = "mounting_bracket") -> str:
    return json.dumps(
        {
            "schema_version": "executable-cadquery-response-v1",
            "outputs": [{"output_id": output_id, "parameters": {}, "source": source}],
        }
    )


def test_accepts_complete_source_and_preserves_source_bytes() -> None:
    source = valid_mounting_bracket_source()

    parsed = parse_executable_cadquery_response(
        response_for(source), FROZEN_MOUNTING_BRACKET_CONTRACT
    )

    assert parsed.schema_version == "executable-cadquery-response-v1"
    assert parsed.outputs[0].output_id == "mounting_bracket"
    assert parsed.outputs[0].source == source
    assert len(parsed.outputs[0].source_hash) == 64


@pytest.mark.parametrize(
    "raw_response, expected_message",
    [
        ("not json", "response is not valid JSON"),
        (json.dumps({"schema_version": "wrong", "outputs": []}), "schema_version"),
        (json.dumps({"schema_version": "executable-cadquery-response-v1", "outputs": []}), "outputs"),
    ],
)
def test_rejects_invalid_provider_envelopes(raw_response: str, expected_message: str) -> None:
    with pytest.raises(ExecutableCadQueryContractError, match=expected_message):
        parse_executable_cadquery_response(raw_response, FROZEN_MOUNTING_BRACKET_CONTRACT)


@pytest.mark.parametrize("output_id", ["other", "mounting_bracket_extra"])
def test_rejects_canonical_output_identity_changes(output_id: str) -> None:
    with pytest.raises(ExecutableCadQueryContractError, match="canonical output"):
        parse_executable_cadquery_response(
            response_for(valid_mounting_bracket_source(), output_id=output_id),
            FROZEN_MOUNTING_BRACKET_CONTRACT,
        )


def test_rejects_multiple_sources_for_single_output() -> None:
    payload = {
        "schema_version": "executable-cadquery-response-v1",
        "outputs": [
            {"output_id": "mounting_bracket", "parameters": {}, "source": valid_mounting_bracket_source()},
            {"output_id": "mounting_bracket", "parameters": {}, "source": valid_mounting_bracket_source()},
        ],
    }

    with pytest.raises(ExecutableCadQueryContractError, match="duplicate"):
        parse_executable_cadquery_response(json.dumps(payload), FROZEN_MOUNTING_BRACKET_CONTRACT)


@pytest.mark.parametrize(
    "source, expected_message",
    [
        ("def build(params):\n    return (", "Python syntax"),
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
    with pytest.raises(ExecutableCadQueryContractError, match=expected_message):
        parse_executable_cadquery_response(
            response_for(source), FROZEN_MOUNTING_BRACKET_CONTRACT
        )


def test_contract_does_not_contain_construction_strategy() -> None:
    contract = FROZEN_MOUNTING_BRACKET_CONTRACT

    rendered = json.dumps(contract, sort_keys=True)
    assert "workplane" not in rendered.lower()
    assert "boolean" not in rendered.lower()
    assert "sketch order" not in rendered.lower()
