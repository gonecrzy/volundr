from app.services.executable_cadquery.fixtures import (
    FROZEN_MOUNTING_BRACKET_CONTRACT,
    FROZEN_MOUNTING_BRACKET_USER_PROMPT,
    frozen_mounting_bracket_contract,
    valid_mounting_bracket_source,
)


def test_mounting_bracket_fixture_is_frozen_and_canonical() -> None:
    assert FROZEN_MOUNTING_BRACKET_USER_PROMPT.startswith("Create a mounting bracket")
    assert FROZEN_MOUNTING_BRACKET_CONTRACT == frozen_mounting_bracket_contract()
    assert FROZEN_MOUNTING_BRACKET_CONTRACT["schema_version"] == "executable-cadquery-design-contract-v1"
    assert FROZEN_MOUNTING_BRACKET_CONTRACT["units"] == "mm"
    assert [item["output_id"] for item in FROZEN_MOUNTING_BRACKET_CONTRACT["outputs"]] == [
        "mounting_bracket"
    ]


def test_fixture_source_is_standalone_cadquery_source() -> None:
    source = valid_mounting_bracket_source()

    assert "def build(params):" in source
    assert "return Product" in source
    assert "mounting_bracket" in source
    assert "```" not in source
