import re

from app.services.cad.cadquery_contract import CadQueryContractError, validate_cadquery_source
from app.services.openscad.source_contract import scan_openscad_source


class SourceExtractionError(ValueError):
    pass


FENCED_BLOCK_RE = re.compile(
    r"```(?:scad|openscad)\s*(?P<source>.*?)```",
    re.IGNORECASE | re.DOTALL,
)
PYTHON_FENCED_BLOCK_RE = re.compile(
    r"```(?:python|py|cadquery)\s*(?P<source>.*?)```",
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


def extract_python_source(raw_output: str) -> str:
    candidates = [
        match.group("source").strip() for match in PYTHON_FENCED_BLOCK_RE.finditer(raw_output)
    ]
    if not candidates and re.search(r"```(?:python|py)\b", raw_output, flags=re.IGNORECASE):
        raise SourceExtractionError("unterminated Python source block")
    if not candidates:
        candidates = [raw_output.strip()]

    for candidate in candidates:
        if _looks_like_python_cadquery(candidate):
            _validate_python_source(candidate)
            return candidate

    raise SourceExtractionError("no valid Python source found")


def _looks_like_python_cadquery(source: str) -> bool:
    return (
        "def build(" in source
        or "def build_model" in source
        or "import cadquery" in source
        or "cq.Workplane" in source
        or "PrintableOutput" in source
    )


def _validate_python_source(source: str) -> None:
    if re.search(r"^\s*def\s+build\s*\(", source, flags=re.MULTILINE):
        try:
            validate_cadquery_source(source, contract_version="cadquery-v1")
        except CadQueryContractError as exc:
            raise SourceExtractionError(str(exc)) from exc
        return
    if re.search(r"^\s*def\s+build_model\s*\(", source, flags=re.MULTILINE):
        try:
            validate_cadquery_source(source)
        except CadQueryContractError as exc:
            raise SourceExtractionError(str(exc)) from exc
        return
    raise SourceExtractionError("Python source must define build(params) or build_model()")


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
