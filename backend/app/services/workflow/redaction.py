from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


class RedactionError(RuntimeError):
    pass


class RedactionService:
    version = "workflow-redaction-v1"

    _secret_patterns = (
        re.compile(r"AIza[0-9A-Za-z_\-]{10,}"),
        re.compile(r"(?i)\b(api[_-]?key|authorization|bearer|token|cookie|set-cookie)\b\s*[:=]\s*(?:bearer\s+)?[^,\s}\]]+"),
        re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+[^,\s}\]]+"),
        re.compile(r"(?i)\bpostgres(?:ql)?://[^,\s]+"),
        re.compile(r"(?i)\bmysql://[^,\s]+"),
        re.compile(r"(?i)\bsig(nature)?=[0-9A-Za-z%_\-]+"),
        re.compile(r"(?i)(/home/|/users/|/root/)[^,\s}\]]+"),
    )
    _sensitive_keys = re.compile(
        r"(?i)(api[_-]?key|authorization|cookie|set-cookie|token|secret|password|credential|gemini)"
    )
    _absolute_path_pattern = re.compile(
        r"(?<![A-Za-z0-9_])(?P<path>(?:/(?:tmp|var/tmp|home|root|Users|private/tmp|workspace|workspaces|app/data|opt|srv|mnt|run|data)(?:/[^\s\"'`,}\]]+)+|[A-Za-z]:[\\/][^\s\"'`,}\]]+))"
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

    def normalize_evidence_text(
        self,
        text: str,
        *,
        data_root: Path,
        evidence_root: Path,
        registered_paths: Mapping[str, Mapping[str, str]] | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Redact secrets and replace host paths in durable runtime evidence.

        This deliberately lives beside the existing secret redactor so callers
        can distinguish path normalization findings from secret replacement.
        Removed values are never included in the returned findings.
        """

        registered = {
            str(Path(path)): dict(reference)
            for path, reference in (registered_paths or {}).items()
        }
        findings: list[dict[str, Any]] = []

        def replace(match: re.Match[str]) -> str:
            raw_path = match.group("path").rstrip(".,:;)]}")
            normalized_path = raw_path.replace("\\", "/")
            reference = registered.get(str(Path(raw_path))) or registered.get(normalized_path)
            if reference:
                replacement = f"artifact:{reference['artifact_id']}/{reference['relative_path']}"
                kind = "evidence.absolute_path_removed"
            else:
                path_object = Path(raw_path)
                replacement = None
                try:
                    relative = path_object.resolve().relative_to(evidence_root.resolve())
                    replacement = f"session-relative:{relative.as_posix()}"
                    kind = "evidence.temporary_path_normalized"
                except ValueError:
                    try:
                        relative = path_object.resolve().relative_to(data_root.resolve())
                        replacement = f"data-relative:{relative.as_posix()}"
                        kind = "evidence.absolute_path_removed"
                    except ValueError:
                        if normalized_path.startswith(("/tmp/", "/var/tmp/", "/private/tmp/")):
                            replacement = "[REDACTED_TEMPORARY_PATH]"
                            kind = "evidence.temporary_path_normalized"
                        else:
                            replacement = "[REDACTED_PATH]"
                            kind = "evidence.unregistered_path_redacted"
            findings.append(
                {
                    "kind": kind,
                    "field_path": "text",
                    "action": "replace_absolute_path",
                    "replacement": replacement,
                    "count": 1,
                }
            )
            return replacement

        normalized = self._absolute_path_pattern.sub(replace, text)
        redacted, _ = self.redact_text(normalized)
        return redacted, findings

    def redact_evidence_value(
        self,
        value: Any,
        *,
        data_root: Path,
        evidence_root: Path,
        registered_paths: Mapping[str, Mapping[str, str]] | None = None,
    ) -> tuple[Any, list[dict[str, Any]]]:
        findings: list[dict[str, Any]] = []

        def visit(current: Any, field_name: str = "") -> Any:
            if isinstance(current, Mapping):
                result: dict[str, Any] = {}
                for key, nested in current.items():
                    key_text = str(key)
                    if self._sensitive_keys.search(key_text):
                        result[key_text] = "[REDACTED]"
                    elif key_text.casefold() == "headers" and isinstance(nested, Mapping):
                        result[key_text] = self._allowed_header_subset(nested)
                    else:
                        result[key_text] = visit(nested, key_text)
                return result
            if isinstance(current, list):
                return [visit(item, field_name) for item in current]
            if isinstance(current, str):
                # Generated source is preserved as source text. Runtime paths
                # in worker/provider/error evidence are normalized below.
                if field_name.lower() in {"source", "generated_source", "source_code"}:
                    redacted, _ = self.redact_text(current)
                    return redacted
                normalized, current_findings = self.normalize_evidence_text(
                    current,
                    data_root=data_root,
                    evidence_root=evidence_root,
                    registered_paths=registered_paths,
                )
                findings.extend(current_findings)
                return normalized
            return current

        return visit(value), findings

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
