import re

from app.services.openscad.source_contract import scan_openscad_source


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
    return (
        "module main_model" in source
        or "main_model();" in source
        or "module render_selected_output" in source
        or "render_selected_output();" in source
    )


def _contains_scad_syntax(source: str) -> bool:
    return any(token in source for token in ("cube(", "cylinder(", "sphere(", "module "))


def _validate_source(source: str) -> None:
    scan = scan_openscad_source(source)
    if "main_model" in scan.metadata.module_names:
        expected_call = "main_model"
    elif "render_selected_output" in scan.metadata.module_names:
        expected_call = "render_selected_output"
    else:
        raise SourceExtractionError("OpenSCAD source must define main_model or render_selected_output")
    call_count = scan.metadata.top_level_calls.count(expected_call)
    if call_count != 1:
        raise SourceExtractionError(f"OpenSCAD source must contain exactly one {expected_call}(); call")
