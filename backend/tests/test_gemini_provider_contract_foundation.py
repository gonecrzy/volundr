from __future__ import annotations

import json
from pathlib import Path

from scripts.run_gemini_provider_contract_foundation import (
    HOLDOUT_PACKET_IDS,
    MODEL,
    SECONDARY_ENV,
    SELECTION_PACKET_IDS,
    holdout_packets,
    prepare_study,
    selection_packets,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_selection_and_holdout_packets_are_disjoint_and_frozen() -> None:
    selection = selection_packets()
    holdout = holdout_packets()

    assert [item["packet_id"] for item in selection] == list(SELECTION_PACKET_IDS)
    assert [item["packet_id"] for item in holdout] == list(HOLDOUT_PACKET_IDS)
    assert not {item["packet_id"] for item in selection} & {item["packet_id"] for item in holdout}
    assert [item["stage"] for item in holdout].count("requirements") == 3
    assert [item["stage"] for item in holdout].count("plan") == 3
    assert [item["stage"] for item in holdout].count("geometry") == 3
    assert [item["stage"] for item in holdout].count("repair") == 1


def test_prepare_creates_preregistration_before_any_calls(tmp_path: Path) -> None:
    result = prepare_study(tmp_path / "study", REPO_ROOT)
    prereg = json.loads((tmp_path / "study/reports/study-preregistration.json").read_text(encoding="utf-8"))

    assert result["provider_calls"] == 0
    assert result["worker_calls"] == 0
    assert prereg["model"] == MODEL
    assert prereg["credential_policy"] == {
        "automatic_rotation": False,
        "credential_slot": "secondary",
        "credential_source": SECONDARY_ENV,
        "primary_fallback": False,
    }
    assert prereg["rate_policy"]["concurrency"] == 1
    assert prereg["rate_policy"]["default_requests_per_minute"] == 12
    assert prereg["rate_policy"]["hard_max_requests_per_rolling_60_seconds"] == 15
