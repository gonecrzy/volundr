"""Explicit, evidence-first Gemini provider-contract integration tooling.

Nothing in this package is imported by normal production provider routing.
Callers must select the versioned integration profile explicitly.
"""

from .profile import INTEGRATION_PROFILE_ID, GeminiFlashLiteContractV1

__all__ = ["INTEGRATION_PROFILE_ID", "GeminiFlashLiteContractV1"]

