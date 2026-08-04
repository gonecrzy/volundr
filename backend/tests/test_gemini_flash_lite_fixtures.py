import json
from pathlib import Path


FIXTURE_ROOT = Path(__file__).parents[2] / "tests" / "fixtures" / "gemini-live-responses"


def test_committed_gemini_fixtures_are_minimal_and_redacted() -> None:
    fixtures = sorted(FIXTURE_ROOT.glob("*.json"))

    assert fixtures
    for path in fixtures:
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["fixture_id"]
        assert document["originating_study"]
        assert document["stage"]
        assert "expected_parse_classification" in document
        rendered = path.read_text(encoding="utf-8").casefold()
        assert "authorization: bearer" not in rendered
        assert "api_key=" not in rendered
        assert "/root/" not in rendered
