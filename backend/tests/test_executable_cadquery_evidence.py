from pathlib import Path

from app.services.executable_cadquery.evidence import persist_exact_provider_response


def test_provider_response_evidence_is_exact_private_and_write_once(tmp_path: Path) -> None:
    response = "```python\nprint('provider response')\n```\n"

    path = persist_exact_provider_response(
        tmp_path,
        workflow_id="workflow-1",
        attempt_number=1,
        raw_response=response,
    )
    second_path = persist_exact_provider_response(
        tmp_path,
        workflow_id="workflow-1",
        attempt_number=1,
        raw_response="replacement must not win",
    )

    assert second_path == path
    assert path.read_text(encoding="utf-8") == response
    assert path.stat().st_mode & 0o777 == 0o600
