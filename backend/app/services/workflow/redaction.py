from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit


class RedactionError(RuntimeError):
    pass


class RedactionService:
    version = "workflow-redaction-v1"

    _secret_patterns = (
        re.compile(r"AIza[0-9A-Za-z_\-]{10,}"),
        re.compile(r"(?i)\b(api[_-]?key|authorization|bearer|token|cookie|set-cookie)\b\s*[:=]\s*[^,\s}\]]+"),
        re.compile(r"(?i)\bpostgres(?:ql)?://[^,\s]+"),
        re.compile(r"(?i)\bmysql://[^,\s]+"),
        re.compile(r"(?i)\bsig(nature)?=[0-9A-Za-z%_\-]+"),
        re.compile(r"(?i)(/home/|/users/|/root/)[^,\s}\]]+"),
    )
    _sensitive_keys = re.compile(
        r"(?i)(api[_-]?key|authorization|cookie|set-cookie|token|secret|password|credential|gemini)"
    )
    _allowed_headers = {"content-type", "accept", "user-agent", "retry-after"}
    _request_metadata_allowlist = {
        "url",
        "method",
        "headers",
        "provider",
        "model",
        "timeout_seconds",
        "retry_count",
        "status_code",
        "duration_ms",
        "request_id",
    }

    def redact_mapping(self, payload: Mapping[str, Any], *, artifact_type: str) -> dict[str, Any]:
        if artifact_type == "provider_request_metadata":
            return self._redact_provider_request_metadata(payload)
        return self._redact_value(dict(payload))

    def redact_text(self, text: str) -> tuple[str, list[str]]:
        replacements: list[str] = []
        redacted = text
        for pattern in self._secret_patterns:
            redacted, count = pattern.subn("[REDACTED]", redacted)
            if count:
                replacements.append(pattern.pattern)
        return redacted, replacements

    def assert_text_redacted(self, text: str) -> None:
        for pattern in self._secret_patterns:
            if pattern.search(text):
                raise RedactionError("debug bundle redaction could not be confirmed")

    def assert_json_redacted(self, payload: Any) -> None:
        self.assert_text_redacted(json.dumps(payload, sort_keys=True, default=str))

    def _redact_provider_request_metadata(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            normalized_key = str(key).lower()
            if normalized_key not in self._request_metadata_allowlist:
                if self._sensitive_keys.search(str(key)):
                    redacted[str(key)] = "[REDACTED]"
                continue
            if normalized_key == "url" and isinstance(value, str):
                redacted[str(key)] = self._strip_query(value)
            elif normalized_key == "headers" and isinstance(value, Mapping):
                redacted[str(key)] = self._allowed_header_subset(value)
            else:
                redacted[str(key)] = self._redact_value(value)
        return redacted

    def _allowed_header_subset(self, headers: Mapping[str, Any]) -> dict[str, str]:
        result: dict[str, str] = {}
        for key, value in headers.items():
            normalized = str(key).lower()
            if normalized in self._allowed_headers:
                result[normalized] = str(value)
        return result

    def _strip_query(self, url: str) -> str:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for key, nested in value.items():
                if self._sensitive_keys.search(str(key)):
                    result[str(key)] = "[REDACTED]"
                elif str(key).lower() == "url" and isinstance(nested, str):
                    result[str(key)] = self._strip_query(nested)
                elif str(key).lower() == "headers" and isinstance(nested, Mapping):
                    result[str(key)] = self._allowed_header_subset(nested)
                else:
                    result[str(key)] = self._redact_value(nested)
            return result
        if isinstance(value, list):
            return [self._redact_value(item) for item in value]
        if isinstance(value, str):
            redacted, _ = self.redact_text(value)
            return redacted
        return value
