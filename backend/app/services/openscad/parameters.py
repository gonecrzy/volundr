from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OpenScadParameter:
    id: str
    name: str
    display_name: str
    type: str
    value: int | float | bool | str
    default_value: int | float | bool | str
    group: str | None = None
    description: str | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    step: int | float | None = None
    options: list[str] = field(default_factory=list)
    option_labels: dict[str, str] = field(default_factory=dict)
    source_line: int | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "type": self.type,
            "value": self.value,
            "default_value": self.default_value,
            "group": self.group,
            "description": self.description,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "step": self.step,
            "options": self.options,
            "option_labels": self.option_labels,
            "source_line": self.source_line,
        }


_ASSIGNMENT_RE = re.compile(
    r"^\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*([^;\n]+);\s*(//[^\n]*)?$",
    re.MULTILINE,
)
_GROUP_RE = re.compile(r"^\s*/\*\s*\[([^\]]+)\]\s*\*/\s*$")
_STOP_RE = re.compile(r"^\s*(module|function)\s+[A-Za-z_$][A-Za-z0-9_$]*\b", re.MULTILINE)


def extract_editable_parameters(source: str) -> list[OpenScadParameter]:
    """Extract simple editable parameters from top-level OpenSCAD assignments.

    This intentionally handles the practical Customizer-style subset that AI
    commonly emits. It is not a full OpenSCAD parser.
    """

    header = _top_level_header(source)
    lines = header.splitlines()
    groups_by_line = _groups_by_line(lines)
    parameters: list[OpenScadParameter] = []

    for match in _ASSIGNMENT_RE.finditer(header):
        name = match.group(1)
        raw_value = match.group(2).strip()
        raw_comment = _clean_comment(match.group(3))
        line_number = header.count("\n", 0, match.start()) + 1

        parsed = _parse_constant(raw_value)
        if parsed is None:
            continue

        description = _description_before(lines, line_number)
        group = _group_for_line(groups_by_line, line_number)
        hints = _parse_customizer_comment(raw_comment, parsed["type"])

        if parsed["type"] == "number[]":
            values = parsed["value"]
            assert isinstance(values, list)
            labels = _array_labels(name, len(values))
            base_display = _display_name(name)
            for index, value in enumerate(values):
                display_name = _display_name_for_array_item(base_display, labels[index])
                parameters.append(
                    OpenScadParameter(
                        id=f"{name}[{index}]",
                        name=f"{name}[{index}]",
                        display_name=display_name,
                        type="number",
                        value=value,
                        default_value=value,
                        group=group,
                        description=description,
                        source_line=line_number,
                        **hints,
                    )
                )
            continue

        parameter_type = parsed["type"]
        value = parsed["value"]
        if parameter_type == "string" and _is_color_parameter(name, raw_comment, value):
            parameter_type = "color"

        parameters.append(
            OpenScadParameter(
                id=name,
                name=name,
                display_name=_display_name(name),
                type=parameter_type,
                value=value,
                default_value=value,
                group=group,
                description=description,
                source_line=line_number,
                **hints,
            )
        )

    return parameters


def _top_level_header(source: str) -> str:
    match = _STOP_RE.search(source)
    if match is None:
        return source
    return source[: match.start()]


def _groups_by_line(lines: list[str]) -> list[tuple[int, str]]:
    groups: list[tuple[int, str]] = []
    for index, line in enumerate(lines, start=1):
        match = _GROUP_RE.match(line)
        if match:
            groups.append((index, match.group(1).strip()))
    return groups


def _group_for_line(groups: list[tuple[int, str]], line_number: int) -> str | None:
    active = [group for group_line, group in groups if group_line < line_number]
    return active[-1] if active else None


def _description_before(lines: list[str], line_number: int) -> str | None:
    previous_index = line_number - 2
    if previous_index < 0 or previous_index >= len(lines):
        return None
    previous = lines[previous_index].strip()
    if not previous.startswith("//"):
        return None
    description = previous.removeprefix("//").strip()
    if description.startswith("@"):
        return None
    return description or None


def _clean_comment(comment: str | None) -> str:
    if not comment:
        return ""
    return comment.removeprefix("//").strip()


def _parse_constant(raw_value: str) -> dict[str, Any] | None:
    if re.fullmatch(r"-?\d+", raw_value):
        return {"type": "number", "value": int(raw_value)}
    if re.fullmatch(r"-?\d+\.\d+", raw_value):
        return {"type": "number", "value": float(raw_value)}
    if raw_value in {"true", "false"}:
        return {"type": "boolean", "value": raw_value == "true"}
    if re.fullmatch(r'"(?:[^"\\]|\\.)*"', raw_value):
        return {"type": "string", "value": raw_value[1:-1]}
    if raw_value.startswith("[") and raw_value.endswith("]"):
        items = [item.strip() for item in raw_value[1:-1].split(",")]
        if not items or any(not item for item in items):
            return None
        numbers: list[int | float] = []
        for item in items:
            parsed = _parse_constant(item)
            if parsed is None or parsed["type"] != "number":
                return None
            numbers.append(parsed["value"])
        return {"type": "number[]", "value": numbers}
    return None


def _parse_customizer_comment(
    comment: str,
    parameter_type: str,
) -> dict[str, Any]:
    hints: dict[str, Any] = {
        "minimum": None,
        "maximum": None,
        "step": None,
        "options": [],
        "option_labels": {},
    }
    if not comment:
        return hints

    if re.fullmatch(r"-?\d+(?:\.\d+)?", comment):
        value = _number(comment)
        if parameter_type == "string":
            hints["maximum"] = value
        else:
            hints["step"] = value
        return hints

    if not (comment.startswith("[") and comment.endswith("]")):
        return hints

    inner = comment[1:-1].strip()
    if "," in inner:
        options: list[str] = []
        labels: dict[str, str] = {}
        for raw_option in inner.split(","):
            option = raw_option.strip()
            if not option:
                continue
            value, _, label = option.partition(":")
            value = value.strip()
            label = label.strip()
            options.append(value)
            if label:
                labels[value] = label
        hints["options"] = options
        hints["option_labels"] = labels
        return hints

    parts = [part.strip() for part in inner.split(":")]
    if len(parts) not in {2, 3} or any(not re.fullmatch(r"-?\d+(?:\.\d+)?", part) for part in parts):
        return hints

    if len(parts) == 2:
        hints["minimum"] = _number(parts[0])
        hints["maximum"] = _number(parts[1])
    else:
        hints["minimum"] = _number(parts[0])
        hints["step"] = _number(parts[1])
        hints["maximum"] = _number(parts[2])
    return hints


def _number(value: str) -> int | float:
    parsed = float(value)
    return int(parsed) if parsed.is_integer() else parsed


def _is_color_parameter(name: str, comment: str, value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if comment.strip().lower() == "color":
        return True
    return name.lower().endswith("_color")


def _display_name(name: str) -> str:
    if name == "$fn":
        return "Resolution"
    words = [word for word in name.replace("$", "").replace("_", " ").split(" ") if word]
    return " ".join(word[:1].upper() + word[1:] for word in words)


def _array_labels(name: str, length: int) -> list[str]:
    if length == 2:
        return ["X", "Y"]
    if length != 3:
        return [str(index + 1) for index in range(length)]
    lower = name.lower()
    if any(token in lower for token in ("size", "dimension", "body", "base")):
        return ["Width", "Depth", "Height"]
    return ["X", "Y", "Z"]


def _display_name_for_array_item(base_display: str, label: str) -> str:
    if label in {"Width", "Depth", "Height"}:
        return re.sub(r"\s+Size$", "", base_display) + f" {label}"
    return f"{base_display} {label}"
