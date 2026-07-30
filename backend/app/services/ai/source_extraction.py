import re

from app.services.cad.cadquery_contract import CadQueryContractError, validate_cadquery_source


class SourceExtractionError(ValueError):
    pass


PYTHON_FENCED_BLOCK_RE = re.compile(
    r"```(?:python|py|cadquery)\s*(?P<source>.*?)```",
    re.IGNORECASE | re.DOTALL,
)


def extract_python_source(raw_output: str, *, allow_raw_source: bool = False) -> str:
    candidates = [
        match.group("source").strip() for match in PYTHON_FENCED_BLOCK_RE.finditer(raw_output)
    ]
    if not candidates and re.search(r"```(?:python|py|cadquery)\b", raw_output, flags=re.IGNORECASE):
        raise SourceExtractionError("unterminated Python source block")
    if not candidates:
        if not allow_raw_source:
            raise SourceExtractionError("CadQuery source must be returned in a fenced source block")
        candidates = [raw_output.strip()]

    for candidate in candidates:
        if _looks_like_python_cadquery(candidate):
            _validate_python_source(candidate)
            return candidate

    raise SourceExtractionError("no valid Python source found")


def _looks_like_python_cadquery(source: str) -> bool:
    return (
        "def build(" in source
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
    raise SourceExtractionError("Python source must define build(params)")
