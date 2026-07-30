import pytest

from volundr_cad.runtime import (
    ParameterSpec,
    ParameterValidationError,
    ParameterValues,
    PrintableOutput,
    Product,
)


def test_parameter_values_apply_defaults_and_validate_overrides() -> None:
    specs = [
        ParameterSpec(
            id="width_mm",
            label="Width",
            type="float",
            default=80.0,
            min_value=10.0,
            max_value=200.0,
        ),
        ParameterSpec(id="rib_count", label="Ribs", type="int", default=3),
        ParameterSpec(id="label_text", label="Label", type="str", default="A"),
    ]

    values = ParameterValues.from_specs(specs, {"width_mm": 90})

    assert values == {"width_mm": 90.0, "rib_count": 3, "label_text": "A"}


def test_parameter_values_reject_unknown_and_out_of_range_values() -> None:
    specs = [
        ParameterSpec(
            id="width_mm",
            label="Width",
            type="float",
            default=80.0,
            min_value=10.0,
            max_value=200.0,
        )
    ]

    with pytest.raises(ParameterValidationError, match="above maximum"):
        ParameterValues.from_specs(specs, {"width_mm": 250})
    with pytest.raises(ParameterValidationError, match="unknown parameter"):
        ParameterValues.from_specs(specs, {"width_mm": 90, "height_mm": 20})


def test_product_requires_printable_outputs() -> None:
    output = PrintableOutput(
        output_id="body",
        component_id="body",
        label="Body",
        model=object(),
    )

    assert Product(outputs=[output]).schema_version == "cadquery-v1"

    with pytest.raises(ParameterValidationError, match="at least one PrintableOutput"):
        Product(outputs=[])
