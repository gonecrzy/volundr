from __future__ import annotations

from app.services.documentation_audit import (
    classify_document,
    find_stale_reference_violations,
    validate_markdown_links,
)


def test_document_classification_makes_current_and_historical_roles_explicit() -> None:
    assert classify_document("docs/CURRENT_TRAJECTORY.md", "# current") == "current_authoritative"
    assert classify_document(
        "docs/GEMINI_PROVIDER_CONTRACT_FOUNDATION.md",
        "historical study evidence",
    ) == "historical_immutable"
    assert classify_document("docs/archive/old.md", "superseded") == "historical_superseded"


def test_stale_reference_check_allows_only_path_scoped_historical_terms() -> None:
    documents = {
        "docs/CURRENT_TRAJECTORY.md": "The current integration uses H1 and T5; output_id is canonical.",
        "docs/active.md": "H0 is the current provider decision and id is the canonical output identity.",
        "docs/archive/old.md": "Historical H0 used seed 1701 and id.",
    }

    findings = find_stale_reference_violations(documents)

    assert {item["path"] for item in findings} == {"docs/active.md"}
    assert {item["rule_id"] for item in findings} == {
        "obsolete-thinking-profile",
        "obsolete-output-identity",
    }


def test_stale_reference_check_covers_each_obsolete_current_guidance_rule() -> None:
    documents = {
        "docs/one.md": "geometry uses T0-current; seed 1701 is current; repair is the current gate.",
        "docs/two.md": "Profile B is the current provider profile and the current provider decision is here.",
        "docs/three.md": "The current provider decision is here too.",
    }

    findings = find_stale_reference_violations(documents)

    assert {
        item["rule_id"]
        for item in findings
    } == {
        "obsolete-geometry-prompt",
        "obsolete-seed",
        "obsolete-repair-gate",
        "obsolete-provider-profile",
        "multiple-current-provider-decisions",
    }


def test_markdown_link_validation_reports_missing_targets() -> None:
    documents = {
        "docs/current.md": "See [contract](PROVIDER_CONTRACT.md) and [missing](NOPE.md).",
        "docs/PROVIDER_CONTRACT.md": "# contract",
    }

    findings = validate_markdown_links(documents)

    assert findings == [
        {
            "path": "docs/current.md",
            "target": "docs/NOPE.md",
            "line": 1,
            "reason": "target_not_found",
        }
    ]
