import re


class SourceExtractionError(ValueError):
    pass


FENCED_BLOCK_RE = re.compile(
    r"```(?:scad|openscad)\s*(?P<source>.*?)```",
    re.IGNORECASE | re.DOTALL,
)


def extract_scad_source(raw_output: str) -> str:
    candidates = [match.group("source").strip() for match in FENCED_BLOCK_RE.finditer(raw_output)]
    if not candidates:
        candidates = [raw_output.strip()]

    for candidate in candidates:
        if _looks_like_scad(candidate):
            _validate_source(candidate)
            return candidate
        if _contains_scad_syntax(candidate):
            _validate_source(candidate)

    raise SourceExtractionError("no valid OpenSCAD source found")


def _looks_like_scad(source: str) -> bool:
    return "module main_model" in source or "main_model();" in source


def _contains_scad_syntax(source: str) -> bool:
    return any(token in source for token in ("cube(", "cylinder(", "sphere(", "module "))


def _validate_source(source: str) -> None:
    if "module main_model" not in source:
        raise SourceExtractionError("OpenSCAD source must define main_model")
    call_count = len(re.findall(r"(?<!module\s)\bmain_model\s*\(\s*\)\s*;", source))
    if call_count != 1:
        raise SourceExtractionError("OpenSCAD source must contain exactly one main_model(); call")
