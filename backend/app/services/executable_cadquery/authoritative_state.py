"""Shared facts for offline executable-CadQuery state reconciliation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DOWNSTREAM_STAGES = (
    "semantic_measurement",
    "semantic_policy",
    "artifacts",
    "package",
    "render",
    "blind_independent_cad_qa",
)


def downstream_stage_order(*, topology_valid: bool) -> list[str]:
    """Return the stages eligible after the current topology boundary."""

    return list(DOWNSTREAM_STAGES) if topology_valid else ["topology"]


def build_transport_forensics(
    *,
    failed_attempt: Mapping[str, Any],
    known_working_api: Mapping[str, Any],
) -> dict[str, Any]:
    """Classify transport paths without invoking either provider.

    A ``GeminiCliProvider`` always crosses the CLI subprocess boundary.  Its
    profile/API-key setting does not turn that subprocess into the direct
    Generative Language REST request used by ``GeminiApiProvider``.
    """

    failed_settings = failed_attempt.get("provider_settings")
    failed_settings = failed_settings if isinstance(failed_settings, Mapping) else {}
    failed_provider = str(failed_attempt.get("provider") or "")
    failed_transport = (
        "gemini_cli_oauth_code_assist"
        if failed_provider in {"gemini_cli", "gemini"}
        else "unknown"
    )
    working_transport = (
        "gemini_api_rest"
        if str(known_working_api.get("provider_id") or "") == "gemini_api"
        else "unknown"
    )
    failed_request = {
        "provider": failed_provider,
        "transport": failed_transport,
        "subprocess_boundary": failed_transport == "gemini_cli_oauth_code_assist",
        "auth_mode": str(failed_settings.get("auth_mode") or "unknown"),
        "api_key_header_used": False,
        "evidence": [
            "GeminiCliProvider.build_command constructs a gemini subprocess command.",
            "The persisted failure is IneligibleTierError from Gemini Code Assist authentication.",
        ],
    }
    known_working_request = {
        "provider": str(known_working_api.get("provider_id") or "unknown"),
        "transport": working_transport,
        "subprocess_boundary": False,
        "endpoint": str(known_working_api.get("endpoint") or ""),
        "auth_header": str(known_working_api.get("auth_header") or ""),
        "api_key_header_used": known_working_api.get("auth_header") == "x-goog-api-key",
        "evidence": [
            "ValidatedGeminiTransport posts directly to the Generative Language API.",
            "The request carries the credential in x-goog-api-key.",
        ],
    }
    same_transport = (
        failed_request["transport"] == known_working_request["transport"]
        and failed_request["api_key_header_used"] is True
        and known_working_request["api_key_header_used"] is True
    )
    error = failed_attempt.get("error")
    error = error if isinstance(error, Mapping) else {}
    return {
        "schema_version": "executable-cadquery-transport-forensics-v1",
        "failed_request": failed_request,
        "known_working_request": known_working_request,
        "failure": {
            "type": str(error.get("type") or "unknown"),
            "message_class": "IneligibleTierError"
            if "IneligibleTierError" in str(error.get("message") or "")
            else "unknown",
        },
        "same_api_key_transport_proven": same_transport,
        "additional_p3_provider_call_allowed": same_transport,
        "provider_call_made_by_forensics": 0,
    }
