import pytest

from app.services.ai.source_extraction import SourceExtractionError, extract_scad_source


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
