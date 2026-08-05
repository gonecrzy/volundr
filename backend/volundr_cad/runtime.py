import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import cadquery as cq

from volundr_cad.capsule_slot import (
    CapsuleSlotFrame,
    cut_capsule_slot_v1,
)

from volundr_cad.patterns import (
    circular_pattern_points,
    linear_pattern_points,
    rectangular_pattern_points,
    resolve_pattern_points,
)


def place_pattern_cutters(
    profile: Any,
    points: Sequence[Sequence[float]],
    *,
    coordinate_space: str = "component_local_3d",
) -> Any:
    """Place one copy of a cutter profile at each canonical 3D point.

    This helper intentionally handles only component-local placements. World
    points must be transformed by Volundr before they reach provider-owned
    geometry, and workplane-local points should use ``pushPoints`` instead.
    The returned Workplane contains the placed solids and can be passed to a
    normal CadQuery boolean such as ``body.cut(cutters)``.
    """

    if coordinate_space != "component_local_3d":
        raise ValueError(
            "place_pattern_cutters requires component_local_3d points; "
            "transform world or workplane points before placement"
        )
    base_shape = profile.val() if hasattr(profile, "val") else profile
    if not isinstance(base_shape, cq.Shape):
        raise TypeError("pattern cutter profile must be a CadQuery Workplane or Shape")
    shape_type = base_shape.ShapeType()
    if shape_type not in {"Solid", "Compound"} or (
        shape_type == "Compound" and not base_shape.Solids()
    ):
        raise TypeError(
            "pattern cutter profile must be a volumetric Solid or Compound; "
            "close and extrude the profile before placing it"
        )
    if not points:
        raise ValueError("pattern cutter points cannot be empty")

    placed_shapes = []
    for index, point in enumerate(points):
        if isinstance(point, (str, bytes)) or len(point) != 3:
            raise ValueError(f"pattern point {index} must contain three coordinates")
        coordinates = tuple(float(value) for value in point)
        if not all(math.isfinite(value) for value in coordinates):
            raise ValueError(f"pattern point {index} must contain finite coordinates")
        placed_shapes.append(base_shape.translate(cq.Vector(*coordinates)))
    return cq.Workplane("XY").newObject(placed_shapes)

ParameterType = Literal["float", "int", "bool", "str", "enum"]


class ParameterValidationError(ValueError):
    pass


def _metadata_decorator(attribute: str, payload: dict[str, Any]):
    def decorate(function):
        existing = list(getattr(function, attribute, ()))
        existing.append(payload)
        setattr(function, attribute, tuple(existing))
        return function

    return decorate


def component(component_id: str):
    return _metadata_decorator("__volundr_components__", {"id": component_id})


def feature(feature_id: str, *, component: str | None = None):
    return _metadata_decorator(
        "__volundr_features__",
        {"id": feature_id, "component_id": component},
    )


def shared_helper(helper_id: str):
    return _metadata_decorator("__volundr_shared_helpers__", {"id": helper_id})


def protected_interface(interface_id: str, *, parameters: tuple[str, ...] = ()):
    return _metadata_decorator(
        "__volundr_protected_interfaces__",
        {"id": interface_id, "parameters": tuple(parameters)},
    )


@dataclass(frozen=True)
class ParameterSpec:
    id: str
    label: str
    type: ParameterType
    default: float | int | bool | str
    unit: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    choices: tuple[str, ...] = ()
    editable: bool = True
    protected: bool = False
    source_requirement_id: str | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ParameterValidationError("parameter id cannot be blank")
        if self.type == "enum" and not self.choices:
            raise ParameterValidationError("enum parameters require choices")
        self.validate(self.default)

    def validate(self, value: Any) -> float | int | bool | str:
        if self.type == "bool":
            if not isinstance(value, bool):
                raise ParameterValidationError(f"{self.id} must be a bool")
            return value
        if self.type == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ParameterValidationError(f"{self.id} must be an int")
            self._validate_range(float(value))
            return value
        if self.type == "float":
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ParameterValidationError(f"{self.id} must be a float")
            number = float(value)
            self._validate_range(number)
            return number
        if self.type == "str":
            if not isinstance(value, str):
                raise ParameterValidationError(f"{self.id} must be a str")
            return value
        if self.type == "enum":
            if not isinstance(value, str):
                raise ParameterValidationError(f"{self.id} must be an enum string")
            if value not in self.choices:
                raise ParameterValidationError(f"{self.id} must be one of {', '.join(self.choices)}")
            return value
        raise ParameterValidationError(f"{self.id} has unsupported type {self.type}")

    def _validate_range(self, value: float) -> None:
        if self.min_value is not None and value < self.min_value:
            raise ParameterValidationError(f"{self.id} is below minimum {self.min_value}")
        if self.max_value is not None and value > self.max_value:
            raise ParameterValidationError(f"{self.id} is above maximum {self.max_value}")


class ParameterValues(dict[str, float | int | bool | str]):
    @classmethod
    def from_specs(
        cls,
        specs: Sequence[ParameterSpec],
        values: Mapping[str, Any] | None = None,
    ) -> "ParameterValues":
        provided = dict(values or {})
        validated = cls()
        seen: set[str] = set()
        for spec in specs:
            if spec.id in seen:
                raise ParameterValidationError(f"duplicate parameter id {spec.id}")
            seen.add(spec.id)
            raw_value = provided.pop(spec.id, spec.default)
            validated[spec.id] = spec.validate(raw_value)
        if provided:
            unknown = ", ".join(sorted(provided))
            raise ParameterValidationError(f"unknown parameter values: {unknown}")
        return validated

    def with_derived_values(self, values: Mapping[str, Any]) -> "ParameterValues":
        enriched = type(self)(self)
        enriched.update(values)
        return enriched


@dataclass(frozen=True)
class PrintableOutput:
    output_id: str
    label: str
    model: Any
    component_id: str | None = None
    component_ids: tuple[str, ...] = ()
    quantity: int = 1
    required: bool = True
    expected_solid_count: int = 1
    allow_disconnected_solids: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.output_id.strip():
            raise ParameterValidationError("output_id cannot be blank")
        if not self.component_id and not self.component_ids:
            raise ParameterValidationError("PrintableOutput requires component_id or component_ids")
        if self.component_id is not None and not self.component_id.strip():
            raise ParameterValidationError("component_id cannot be blank")
        if any(not component_id.strip() for component_id in self.component_ids):
            raise ParameterValidationError("component_ids cannot include blank values")
        if self.quantity < 1:
            raise ParameterValidationError("quantity must be at least 1")
        if self.expected_solid_count < 1:
            raise ParameterValidationError("expected_solid_count must be at least 1")
        if not isinstance(self.allow_disconnected_solids, bool):
            raise ParameterValidationError("allow_disconnected_solids must be a bool")


@dataclass(frozen=True)
class Product:
    outputs: Sequence[PrintableOutput]
    parameters: Sequence[ParameterSpec] = ()
    schema_version: str = "cadquery-v1"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != "cadquery-v1":
            raise ParameterValidationError("Product schema_version must be cadquery-v1")
        if not self.outputs:
            raise ParameterValidationError("Product requires at least one PrintableOutput")
        if any(not isinstance(output, PrintableOutput) for output in self.outputs):
            raise ParameterValidationError("Product outputs must be PrintableOutput entries")
        output_ids: set[str] = set()
        for output in self.outputs:
            if output.output_id in output_ids:
                raise ParameterValidationError(f"duplicate output_id {output.output_id}")
            output_ids.add(output.output_id)
        if not isinstance(self.parameters, Sequence) or isinstance(self.parameters, str | bytes):
            raise ParameterValidationError("Product parameters must be ParameterSpec entries")
        if any(not isinstance(parameter, ParameterSpec) for parameter in self.parameters):
            raise ParameterValidationError("Product parameters must be ParameterSpec entries")
