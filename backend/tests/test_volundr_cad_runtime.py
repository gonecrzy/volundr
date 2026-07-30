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
        expected_solid_count=1,
        allow_disconnected_solids=False,
    )

    assert Product(outputs=[output]).schema_version == "cadquery-v1"

    with pytest.raises(ParameterValidationError, match="at least one PrintableOutput"):
        Product(outputs=[])


def test_product_requires_parameter_specs() -> None:
    output = PrintableOutput(
        output_id="body",
        component_id="body",
        label="Body",
        model=object(),
        expected_solid_count=1,
        allow_disconnected_solids=False,
    )

    with pytest.raises(ParameterValidationError, match="parameters must be ParameterSpec"):
        Product(outputs=[output], parameters={"width": 10})


def test_printable_output_requires_component_identity_and_topology_policy() -> None:
    with pytest.raises(ParameterValidationError, match="component_id"):
        PrintableOutput(
            output_id="body",
            label="Body",
            model=object(),
            expected_solid_count=1,
            allow_disconnected_solids=False,
        )
    with pytest.raises(ParameterValidationError, match="allow_disconnected_solids"):
        PrintableOutput(
            output_id="body",
            component_id="body",
            label="Body",
            model=object(),
            expected_solid_count=1,
            allow_disconnected_solids="false",  # type: ignore[arg-type]
        )


def test_product_rejects_duplicate_and_non_printable_outputs() -> None:
    first = PrintableOutput(
        output_id="body",
        component_id="body",
        label="Body",
        model=object(),
        expected_solid_count=1,
        allow_disconnected_solids=False,
    )
    duplicate = PrintableOutput(
        output_id="body",
        component_id="body_copy",
        label="Body copy",
        model=object(),
        expected_solid_count=1,
        allow_disconnected_solids=False,
    )

    with pytest.raises(ParameterValidationError, match="duplicate output_id"):
        Product(outputs=[first, duplicate])
    with pytest.raises(ParameterValidationError, match="outputs must be PrintableOutput"):
        Product(outputs=[object()])  # type: ignore[list-item]
