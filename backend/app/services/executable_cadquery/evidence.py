"""Private runtime evidence for provider-owned executable-source attempts."""

from __future__ import annotations

from pathlib import Path
import re


_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


def persist_exact_provider_response(
    data_root: Path,
    *,
    workflow_id: str,
    attempt_number: int,
    raw_response: str,
) -> Path:
    """Persist one exact provider response under private ignored runtime data.

    The response is intentionally not normalized or rewritten. The enclosing
    runtime data directory is ignored by the repository; this file is private
    mode 0600 and write-once so repair prompts can refer to the exact failure.
    """

    safe_workflow_id = _SAFE_ID.sub("_", workflow_id).strip("._") or "workflow"
    root = data_root / "debug-sessions" / "executable-cadquery" / safe_workflow_id
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    path = root / f"attempt-{int(attempt_number):02d}-provider-response.txt"
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(raw_response)
    except FileExistsError:
        pass
    path.chmod(0o600)
    return path
