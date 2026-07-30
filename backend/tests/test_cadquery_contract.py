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


def test_cadquery_contract_defaults_to_v1_product_source() -> None:
    source = """
import cadquery as cq

def build_model():
    return cq.Workplane("XY").box(1, 1, 1)
"""

    with pytest.raises(CadQueryContractError, match="build\\(params\\)"):
        validate_cadquery_source(source)


def test_cadquery_contract_rejects_legacy_probe_contract_version() -> None:
    source = """
import cadquery as cq

def build_model():
    return cq.Workplane("XY").box(1, 1, 1)
"""

    with pytest.raises(CadQueryContractError, match="unsupported CadQuery contract_version"):
        validate_cadquery_source(source, contract_version="cadquery-probe-v1")


def test_cadquery_v1_contract_rejects_artifact_writes() -> None:
    source = cadquery_v1_source().replace(
        "return Product(",
        'cq.exporters.export(body, "/tmp/model.step")\n    return Product(',
    )

    with pytest.raises(CadQueryContractError, match="artifact writing"):
        validate_cadquery_source(source, contract_version="cadquery-v1")


@pytest.mark.parametrize("method_name", ["exportStep", "exportStl", "exportBrep"])
def test_cadquery_v1_contract_rejects_method_artifact_exports(method_name: str) -> None:
    source = cadquery_v1_source().replace(
        "return Product(",
        f'body.val().{method_name}("/tmp/body.step")\n    return Product(',
    )

    with pytest.raises(CadQueryContractError, match="artifact writing"):
        validate_cadquery_source(source, contract_version="cadquery-v1")


@pytest.mark.parametrize(
    ("constructor", "keyword"),
    [
        ("ParameterSpec", "description"),
        ("ParameterSpec", "min"),
        ("ParameterSpec", "max"),
        ("PrintableOutput", "description"),
        ("Product", "title"),
    ],
)
def test_cadquery_v1_contract_rejects_unknown_runtime_constructor_keywords(
    constructor: str,
    keyword: str,
) -> None:
    source = cadquery_v1_source().replace(
        f"{constructor}(",
        f"{constructor}({keyword}=\"unsupported\",",
        1,
    )

    with pytest.raises(CadQueryContractError, match=rf"{constructor}.*{keyword}"):
        validate_cadquery_source(source, contract_version="cadquery-v1")


def test_cadquery_v1_contract_rejects_duplicate_output_ids() -> None:
    source = cadquery_v1_source().replace(
        "            )\n        ],",
        """            ),
            PrintableOutput(
                output_id="body",
                component_id="body_copy",
                label="Duplicate body",
                model=body,
                expected_solid_count=1,
                allow_disconnected_solids=False,
            )
        ],""",
    )

    with pytest.raises(CadQueryContractError, match="duplicate output_id"):
        validate_cadquery_source(source, contract_version="cadquery-v1")


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ('                component_id="body",\n', "component_id"),
        ("                expected_solid_count=1,\n", "expected_solid_count"),
        ("                allow_disconnected_solids=False,\n", "allow_disconnected_solids"),
    ],
)
def test_cadquery_v1_contract_requires_explicit_printable_output_policy(
    line: str,
    message: str,
) -> None:
    source = cadquery_v1_source().replace(line, "")

    with pytest.raises(CadQueryContractError, match=message):
        validate_cadquery_source(source, contract_version="cadquery-v1")


def test_cadquery_v1_contract_rejects_unsupported_parameter_type() -> None:
    source = cadquery_v1_source().replace('type="float"', 'type="number"', 1)

    with pytest.raises(CadQueryContractError, match="ParameterSpec.*type.*number"):
        validate_cadquery_source(source, contract_version="cadquery-v1")


def test_cadquery_v1_contract_reports_unquoted_parameter_type() -> None:
    source = cadquery_v1_source().replace('type="float"', "type=float", 1)

    with pytest.raises(CadQueryContractError, match="ParameterSpec type.*string literal"):
        validate_cadquery_source(source, contract_version="cadquery-v1")


def test_cadquery_v1_contract_rejects_build_local_parameter_specs() -> None:
    source = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

def build(params):
    width = params["width_mm"]
    body = cq.Workplane("XY").box(width, 40, 6)
    parameters = [
        ParameterSpec(
            id="width_mm",
            label="Width",
            type="float",
            default=80.0,
            unit="mm",
        )
    ]
    return Product(
        parameters=parameters,
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

    with pytest.raises(CadQueryContractError, match="module-level PARAMETERS"):
        validate_cadquery_source(source, contract_version="cadquery-v1")


def test_cadquery_v1_contract_requires_product_parameters_reference_module_parameters() -> None:
    source = cadquery_v1_source().replace("parameters=PARAMETERS", "parameters=params")

    with pytest.raises(CadQueryContractError, match="Product parameters must reference module-level PARAMETERS"):
        validate_cadquery_source(source, contract_version="cadquery-v1")


def test_cadquery_v1_contract_accepts_top_level_helper_functions() -> None:
    source = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(id="width_mm", label="Width", type="float", default=80.0, unit="mm")
]

def build_lip(width):
    return cq.Workplane("XY").box(width, 5, 3)

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
                model=body.union(build_lip(width)),
                expected_solid_count=1,
                allow_disconnected_solids=False,
            )
        ],
    )
"""

    validate_cadquery_source(source, contract_version="cadquery-v1")


def test_cadquery_v1_contract_accepts_static_ownership_decorators() -> None:
    source = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product, component, feature, shared_helper

PARAMETERS = [
    ParameterSpec(id="width_mm", label="Width", type="float", default=80.0, unit="mm")
]

@shared_helper("lip_profile")
def build_lip(width):
    return cq.Workplane("XY").box(width, 5, 3)

@component("body")
@feature("body_lip", component="body")
def build_body(params):
    width = params["width_mm"]
    return cq.Workplane("XY").box(width, 40, 6).union(build_lip(width))

def build(params):
    body = build_body(params)
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

    metadata = validate_cadquery_source(source, contract_version="cadquery-v1")

    assert metadata.output_ids == ["body"]
    assert metadata.component_ids == ["body"]


def test_cadquery_v1_contract_accepts_nested_helper_functions() -> None:
    source = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(id="width_mm", label="Width", type="float", default=80.0, unit="mm")
]

def build(params):
    width = params["width_mm"]
    def build_lip():
        return cq.Workplane("XY").box(width, 5, 3)

    body = cq.Workplane("XY").box(width, 80, 10)
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(
                output_id="body",
                component_id="body",
                label="Main body",
                model=body.union(build_lip()),
                expected_solid_count=1,
                allow_disconnected_solids=False,
            )
        ],
    )
"""

    validate_cadquery_source(source, contract_version="cadquery-v1")


@pytest.mark.parametrize(
    "source",
    [
        "import os\n" + cadquery_v1_source(),
        "from subprocess import run\n" + cadquery_v1_source(),
        "import socket\n" + cadquery_v1_source(),
        "import requests\n" + cadquery_v1_source(),
        "from urllib.request import urlopen\n" + cadquery_v1_source(),
        cadquery_v1_source().replace("import cadquery as cq", "import cadquery"),
        cadquery_v1_source().replace("import cadquery as cq", "from cadquery import Workplane"),
    ],
)
def test_cadquery_contract_rejects_unauthorized_imports(source: str) -> None:
    with pytest.raises(CadQueryContractError, match="import"):
        validate_cadquery_source(source, contract_version="cadquery-v1")


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
    source = cadquery_v1_source().replace(
        'width = params["width_mm"]',
        f'{call_name}("x")\n    width = params["width_mm"]',
    )

    with pytest.raises(CadQueryContractError, match=call_name):
        validate_cadquery_source(source, contract_version="cadquery-v1")


def test_cadquery_contract_rejects_environment_inspection_attempt() -> None:
    source = cadquery_v1_source().replace(
        'width = params["width_mm"]',
        '__import__("os").environ.get("GEMINI_API_KEY")\n    width = params["width_mm"]',
    )

    with pytest.raises(CadQueryContractError, match="__import__"):
        validate_cadquery_source(source, contract_version="cadquery-v1")


def test_cadquery_contract_rejects_unknown_direct_function_calls() -> None:
    source = cadquery_v1_source().replace(
        'width = params["width_mm"]',
        'dangerous_factory()\n    width = params["width_mm"]',
    )

    with pytest.raises(CadQueryContractError, match="dangerous_factory"):
        validate_cadquery_source(source, contract_version="cadquery-v1")


def test_cadquery_contract_rejects_top_level_execution() -> None:
    source = cadquery_v1_source().replace(
        "PARAMETERS = [",
        'result = cq.Workplane("XY").box(1, 1, 1)\n\nPARAMETERS = [',
    )

    with pytest.raises(CadQueryContractError, match="top-level assignment"):
        validate_cadquery_source(source, contract_version="cadquery-v1")


def test_cadquery_contract_rejects_missing_build() -> None:
    with pytest.raises(CadQueryContractError, match="build\\(params\\)"):
        validate_cadquery_source("import cadquery as cq\n\nbody_width = 10\n")
