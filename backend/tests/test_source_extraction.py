import pytest

from app.services.ai.source_extraction import (
    SourceExtractionError,
    extract_python_source,
)

VALID_CADQUERY_SOURCE = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(id="width_mm", label="Width", type="float", default=80.0),
]

def build(params):
    body = cq.Workplane("XY").box(params["width_mm"], 35, 6)
    return Product(
        parameters=PARAMETERS,
        outputs=[PrintableOutput(output_id="body", component_id="body", label="Body", model=body, expected_solid_count=1, allow_disconnected_solids=False)],
    )
""".strip()


def test_rejects_fenced_python_source_with_obsolete_build_model() -> None:
    raw_output = """
```python
import cadquery as cq

plate_width = 80

def build_model():
    return cq.Workplane("XY").box(plate_width, 35, 6)
```
"""

    with pytest.raises(SourceExtractionError, match="build\\(params\\)"):
        extract_python_source(raw_output)


def test_extracts_fenced_cadquery_v1_source_with_build_entrypoint() -> None:
    raw_output = """
```cadquery
{source}
```
""".format(source=VALID_CADQUERY_SOURCE)

    source = extract_python_source(raw_output)

    assert "def build(params)" in source
    assert "PrintableOutput" in source


def test_rejects_python_source_without_build_entrypoint() -> None:
    with pytest.raises(SourceExtractionError, match="build\\(params\\)"):
        extract_python_source(
            "```python\nimport cadquery as cq\nresult = cq.Workplane('XY').box(1, 1, 1)\n```"
        )


def test_rejects_unfenced_raw_source_by_default() -> None:
    with pytest.raises(SourceExtractionError, match="fenced"):
        extract_python_source(VALID_CADQUERY_SOURCE)


def test_extracts_raw_source_when_explicitly_allowed() -> None:
    source = extract_python_source(VALID_CADQUERY_SOURCE, allow_raw_source=True)

    assert source == VALID_CADQUERY_SOURCE


def test_rejects_unterminated_fenced_python_source() -> None:
    raw_output = """
```python
import cadquery as cq

def build_model():
    return cq.Workplane("XY").box(1, 1,
"""

    with pytest.raises(SourceExtractionError, match="unterminated"):
        extract_python_source(raw_output)


def test_rejects_unterminated_fenced_cadquery_source() -> None:
    raw_output = """
```cadquery
import cadquery as cq

def build(params):
    return Product(
"""

    with pytest.raises(SourceExtractionError, match="unterminated"):
        extract_python_source(raw_output)
