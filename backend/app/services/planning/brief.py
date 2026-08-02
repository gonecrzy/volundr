"""Deterministic CAD brief construction from the requirement ledger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class DirectCadBrief:
    payload: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return self.payload


class DirectCadBriefBuilder:
    def build(
        self,
        *,
        project_id: str,
        active_requirements: Iterable[dict[str, Any]],
        revision_delta: Iterable[dict[str, Any]] = (),
        preserved_requirements: Iterable[dict[str, Any]] = (),
        project_state: dict[str, Any] | None = None,
        revision_id: str | None = None,
    ) -> DirectCadBrief:
        requirements = [self._requirement(item) for item in active_requirements if isinstance(item, dict)]
        delta = [dict(item) for item in revision_delta if isinstance(item, dict)]
        preserved = [dict(item) for item in preserved_requirements if isinstance(item, dict)]
        state = project_state or {}
        component_id = "primary_part"
        execution_parameters = self._execution_parameters(requirements, component_id)
        features = []
        primary_body = self._features(component_id)
        required_features = self._required_features(requirements, component_id)
        outputs = [{
            "id": "primary_printable_output",
            "label": "Primary printable part",
            "component_ids": [component_id],
            "required": True,
            "quantity": 1,
            "expected_solid_count": 1,
            "allow_disconnected_solids": False,
        }]
        payload = {
            "schema_version": "cad-brief-v1",
            "planning_depth": "direct_brief",
            "project_id": project_id,
            "revision_id": revision_id,
            "units": str(state.get("units") or "mm"),
            "coordinate_frames": [{"id": "part", "kind": "component_local", "handedness": "right"}],
            "requirements": requirements,
            "revision_delta": delta,
            "preserved_requirements": preserved,
            "proposals": [],
            "components": [{
                "id": component_id,
                "label": "Primary printable part",
                "role": "printable_part",
                "required": True,
                "parameters": [item["id"] for item in execution_parameters],
            }],
            "parameters": execution_parameters,
            "features": features,
            "required_features": [*primary_body, *required_features],
            "relationships": [],
            "validation_targets": self._validation_targets(requirements),
            "exposed_controls": [],
            "outputs": ["STEP", "STL", "BREP"],
            "printable_outputs": outputs,
        }
        return DirectCadBrief(payload)

    @staticmethod
    def _requirement(item: dict[str, Any]) -> dict[str, Any]:
        result = dict(item)
        result.setdefault("source", "requirement_ledger")
        result.setdefault("status", "active")
        result.setdefault("explicit", True)
        return result

    @staticmethod
    def _features(component_id: str) -> list[dict[str, Any]]:
        return [{
            "id": "primary_body",
            "label": "Primary body",
            "component_id": component_id,
            "kind": "body",
            "required": True,
            "requirement_ids": [],
            "parameters": [],
        }]

    @staticmethod
    def _execution_parameters(requirements: list[dict[str, Any]], component_id: str) -> list[dict[str, Any]]:
        parameters: list[dict[str, Any]] = []
        for item in requirements:
            parameter_id = item.get("requirement_id") or item.get("id")
            value = item.get("value", item.get("expected_value"))
            if not isinstance(parameter_id, str) or not parameter_id or value is None:
                continue
            parameter_type = "bool" if isinstance(value, bool) else "int" if isinstance(value, int) else "float" if isinstance(value, (float, int)) else "str"
            parameters.append({
                "id": parameter_id,
                "label": str(item.get("label") or parameter_id).replace("_", " ").title(),
                "type": parameter_type,
                "value": value,
                "unit": item.get("unit"),
                "source_requirement_id": parameter_id,
                "component_id": component_id,
                "editable": False,
                "protected": False,
                "source": "requirement_ledger",
            })
        return parameters

    @staticmethod
    def _required_features(requirements: list[dict[str, Any]], component_id: str) -> list[dict[str, Any]]:
        features: list[dict[str, Any]] = []
        for item in requirements:
            requirement_type = str(item.get("type") or item.get("requirement_type") or "")
            requirement_id = item.get("requirement_id") or item.get("id")
            feature_id = {
                "count": "required_feature_count",
                "position": "required_feature_positions",
                "feature_presence": "required_feature_presence",
                "support": "support_feature",
                "retention": "retention_feature",
                "mounting_interface": "mounting_interface",
                "fit": "fit_feature",
            }.get(requirement_type)
            if feature_id and not any(feature["id"] == feature_id for feature in features):
                features.append({
                    "id": feature_id,
                    "label": feature_id.replace("_", " ").title(),
                    "component_id": component_id,
                    "kind": requirement_type,
                    "required": True,
                    "requirement_ids": [requirement_id] if requirement_id else [],
                    "parameters": [],
                })
            elif feature_id:
                next(feature for feature in features if feature["id"] == feature_id)["requirement_ids"].append(requirement_id)
        return features

    @staticmethod
    def _validation_targets(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        targets = []
        for item in requirements:
            requirement_type = str(item.get("type") or item.get("requirement_type") or "")
            requirement_id = item.get("requirement_id") or item.get("id")
            kind = str(item.get("kind") or requirement_type).lower()
            measurable = {
                "capacity": "supported_capacity",
                "count": "count",
                "dimension": "dimension",
                "clearance": "clearance",
                "fit": "fit",
                "spacing": "spacing",
                "position": "position",
                "orientation": "orientation",
            }
            measurement = measurable.get(kind)
            if measurement is None and requirement_type in {
                "count", "position", "orientation", "fit", "mounting_interface",
                "support", "retention", "removal_access",
            }:
                measurement = requirement_type
            if measurement is None:
                continue
            target = {
                "id": f"verify_{requirement_id}",
                "requirement_id": requirement_id,
                "type": kind,
                "measurement": measurement,
                "operator": item.get("operator"),
                "expected_value": item.get("value"),
                "unit": item.get("unit"),
                "object_type": item.get("object_type"),
                "status": "required_evidence",
            }
            targets.append({key: value for key, value in target.items() if value is not None})
        return targets
