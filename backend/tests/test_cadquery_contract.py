import pytest

from app.services.cad.cadquery_contract import CadQueryContractError, validate_cadquery_source


def cadquery_v1_source() -> str:
    return """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(
        id="width_mm",
        label="Width",
        type="float",
        default=80.0,
        unit="mm",
        min_value=10.0,
        max_value=200.0,
    )
]

def build(params):
    width = params["width_mm"]
    body = cq.Workplane("XY").box(width, 40, 6)
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(
                output_id="body",
                component_id="body",
                label="Main body",
                model=body,
                expected_solid_count=1,
                allow_disconnected_solids=False,
            )
        ],
    )
"""


def test_cadquery_v1_contract_accepts_typed_product_source() -> None:
    metadata = validate_cadquery_source(
        cadquery_v1_source(),
        contract_version="cadquery-v1",
    )

    assert metadata.contract_version == "cadquery-v1"
    assert metadata.entrypoint == "build"
    assert metadata.parameter_ids == ["width_mm"]
    assert metadata.output_ids == ["body"]
    assert metadata.component_ids == ["body"]
    assert metadata.expected_solid_counts == {"body": 1}


def test_cadquery_v1_contract_rejects_probe_build_model_only_source() -> None:
    source = """
import cadquery as cq

def build_model():
    return cq.Workplane("XY").box(1, 1, 1)
"""

    with pytest.raises(CadQueryContractError, match="build\\(params\\)"):
        validate_cadquery_source(source, contract_version="cadquery-v1")


def test_cadquery_v1_contract_rejects_artifact_writes() -> None:
    source = cadquery_v1_source().replace(
        "return Product(",
        'cq.exporters.export(body, "/tmp/model.step")\n    return Product(',
    )

    with pytest.raises(CadQueryContractError, match="artifact writing"):
        validate_cadquery_source(source, contract_version="cadquery-v1")


def test_cadquery_contract_accepts_parameter_constants_and_build_functions() -> None:
    source = """
import cadquery as cq

body_width = 120.0
body_depth = 80.0
use_lip = True
style = "plain"

def build_lip():
    return cq.Workplane("XY").box(body_width, 5, 3)

def build_model():
    body = cq.Workplane("XY").box(body_width, body_depth, 10)
    return body.union(build_lip())
"""

    validate_cadquery_source(source)


def test_cadquery_contract_accepts_nested_helper_functions() -> None:
    source = """
import cadquery as cq

body_width = 120.0

def build_model():
    def build_lip():
        return cq.Workplane("XY").box(body_width, 5, 3)

    body = cq.Workplane("XY").box(body_width, 80, 10)
    return body.union(build_lip())
"""

    validate_cadquery_source(source)


@pytest.mark.parametrize(
    "source",
    [
        "import os\nimport cadquery as cq\n\ndef build_model():\n    return None\n",
        "from subprocess import run\nimport cadquery as cq\n\ndef build_model():\n    return None\n",
        "import cadquery\n\ndef build_model():\n    return cadquery.Workplane('XY')\n",
        "from cadquery import Workplane\n\ndef build_model():\n    return Workplane('XY')\n",
    ],
)
def test_cadquery_contract_rejects_unauthorized_imports(source: str) -> None:
    with pytest.raises(CadQueryContractError, match="import"):
        validate_cadquery_source(source)


@pytest.mark.parametrize(
    "call_name",
    [
        "open",
        "eval",
        "exec",
        "compile",
        "__import__",
        "globals",
        "locals",
        "vars",
        "getattr",
    ],
)
def test_cadquery_contract_rejects_unsafe_calls(call_name: str) -> None:
    source = f"""
import cadquery as cq

def build_model():
    {call_name}("x")
    return cq.Workplane("XY").box(1, 1, 1)
"""

    with pytest.raises(CadQueryContractError, match=call_name):
        validate_cadquery_source(source)


def test_cadquery_contract_rejects_unknown_direct_function_calls() -> None:
    source = """
import cadquery as cq

def build_model():
    return dangerous_factory()
"""

    with pytest.raises(CadQueryContractError, match="dangerous_factory"):
        validate_cadquery_source(source)


def test_cadquery_contract_rejects_top_level_execution() -> None:
    source = """
import cadquery as cq

result = cq.Workplane("XY").box(1, 1, 1)

def build_model():
    return result
"""

    with pytest.raises(CadQueryContractError, match="top-level assignment"):
        validate_cadquery_source(source)


def test_cadquery_contract_rejects_missing_build_model() -> None:
    with pytest.raises(CadQueryContractError, match="build_model"):
        validate_cadquery_source("import cadquery as cq\n\nbody_width = 10\n")
