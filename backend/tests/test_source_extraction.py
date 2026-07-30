import pytest

from app.services.ai.source_extraction import (
    SourceExtractionError,
    extract_python_source,
    extract_scad_source,
)


def test_extracts_plain_scad_source() -> None:
    source = "module main_model() { cube([1, 1, 1]); }\nmain_model();"

    assert extract_scad_source(source) == source


def test_extracts_fenced_scad_block() -> None:
    raw_output = """
Here is the model:

```scad
module main_model() {
  cube([10, 10, 10]);
}
main_model();
```
"""

    assert "cube([10, 10, 10]);" in extract_scad_source(raw_output)


def test_extracts_fenced_openscad_block() -> None:
    raw_output = """
```openscad
module main_model() {
  cylinder(h = 10, d = 5);
}
main_model();
```
"""

    assert "cylinder(h = 10, d = 5);" in extract_scad_source(raw_output)


def test_rejects_output_without_main_model() -> None:
    with pytest.raises(SourceExtractionError, match="main_model"):
        extract_scad_source("cube([1, 1, 1]);")


def test_rejects_multiple_top_level_main_model_calls() -> None:
    with pytest.raises(SourceExtractionError, match="exactly one"):
        extract_scad_source(
            """
module main_model() { cube([1, 1, 1]); }
main_model();
main_model();
"""
        )


def test_extracts_fenced_python_source_with_build_model() -> None:
    raw_output = """
```python
import cadquery as cq

plate_width = 80

def build_model():
    return cq.Workplane("XY").box(plate_width, 35, 6)
```
"""

    source = extract_python_source(raw_output)

    assert "def build_model()" in source
    assert "plate_width = 80" in source


def test_rejects_python_source_without_build_model() -> None:
    with pytest.raises(SourceExtractionError, match="build_model"):
        extract_python_source("import cadquery as cq\nresult = cq.Workplane('XY').box(1, 1, 1)")
