from __future__ import annotations

import hashlib
import json
from typing import Any


def normalized_repair_hash(value: str) -> str:
    try:
        parsed: Any = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        normalized: Any = " ".join(str(value).split())
    else:
        normalized = parsed
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def compare_repair_responses(original: str, repaired: str) -> dict[str, Any]:
    original_hash = normalized_repair_hash(original)
    repaired_hash = normalized_repair_hash(repaired)
    return {
        "original_hash": original_hash,
        "repaired_hash": repaired_hash,
        "unchanged": original_hash == repaired_hash,
    }
