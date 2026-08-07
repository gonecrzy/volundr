from __future__ import annotations

from scripts.reconcile_executable_cadquery_phase0 import _blind_reviewer_result, _verify_authority
from app.services.executable_cadquery.authoritative_state import (
    build_transport_forensics,
    downstream_stage_order,
)


def test_downstream_stage_order_starts_after_verified_topology() -> None:
    assert downstream_stage_order(topology_valid=True) == [
        "semantic_measurement",
        "semantic_policy",
        "artifacts",
        "package",
        "render",
        "blind_independent_cad_qa",
    ]


def test_ineligible_tier_cli_attempt_is_proven_not_api_key_transport() -> None:
    evidence = build_transport_forensics(
        failed_attempt={
            "provider_settings": {
                "binary": "gemini",
                "auth_mode": "gemini_profile",
            },
            "provider": "gemini_cli",
            "error": {
                "type": "RuntimeError",
                "message": "IneligibleTierError: unsupported client",
            },
        },
        known_working_api={
            "provider_id": "gemini_api",
            "transport": "validated_gemini_transport",
            "auth_header": "x-goog-api-key",
            "endpoint": "/models/{model}:generateContent",
        },
    )

    assert evidence["failed_request"]["transport"] == "gemini_cli_oauth_code_assist"
    assert evidence["failed_request"]["api_key_header_used"] is False
    assert evidence["known_working_request"]["transport"] == "gemini_api_rest"
    assert evidence["known_working_request"]["api_key_header_used"] is True
    assert evidence["same_api_key_transport_proven"] is False
    assert evidence["additional_p3_provider_call_allowed"] is False


def test_authority_check_accepts_manifests_without_redundant_source_hash(tmp_path) -> None:
    source = tmp_path / "source.py"
    source.write_text("build", encoding="utf-8")
    source_hash = __import__("hashlib").sha256(source.read_bytes()).hexdigest()
    authority = {
        "source_hash": source_hash,
        "hash_verification": {"valid": True},
        "identity": {"job_id": "job-1"},
    }
    check = _verify_authority(
        project={"project_id": "project-02"},
        authority=authority,
        source_path=source,
        output_manifest={"outputs": [{"output_id": "part"}]},
        worker_result={
            "job_id": "job-1",
            "outputs": [{"output_id": "part", "source_hash": source_hash, "success": True}],
        },
        job={"requested_outputs": [{"output_id": "part"}]},
    )

    assert check["valid"] is True


def test_blind_reviewer_treats_policy_verified_measurements_as_passed() -> None:
    result = _blind_reviewer_result(
        semantic={
            "findings": [
                {
                    "requirement_id": "dimension",
                    "status": "verified",
                    "measured_value": {"width": 10},
                }
            ]
        },
        deterministic_pass=True,
        packet_sha256="packet-hash",
    )

    assert result["requirements"] == [
        {
            "requirement_id": "dimension",
            "evidence_type": "measured",
            "observed": {"width": 10},
            "verdict": "pass",
            "discrepancies": [],
        }
    ]
