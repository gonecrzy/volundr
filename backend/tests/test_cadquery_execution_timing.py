import json
import sys

import pytest

from app.services.cad.cadquery_runner import CadQueryCliRunner


SOURCE = '''
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [ParameterSpec(id="size", label="Size", type="float", default=10.0, unit="mm")]

def build(params):
    body = cq.Workplane("XY").box(params["size"], params["size"], 3)
    return Product(
        parameters=PARAMETERS,
        outputs=[PrintableOutput(output_id="body", label="Body", model=body, component_id="body", expected_solid_count=1, allow_disconnected_solids=False)],
    )
'''


@pytest.mark.asyncio
async def test_execution_manifest_records_function_operation_and_output_timing(tmp_path) -> None:
    runner = CadQueryCliRunner(
        python_binary=sys.executable,
        workspace_root=tmp_path,
        timeout_seconds=30,
    )

    result = await runner.compile(SOURCE, "timing-test")

    assert result.success is True
    payload = json.loads(result.execution_manifest_path.read_text(encoding="utf-8"))
    timing = payload["execution_timing"]
    assert timing["total_ms"] >= 0
    assert timing["functions"]
    assert timing["operations"]
    assert timing["outputs"]["body"]["export_ms"] >= 0
    assert timing["functions"][0]["name"] in {"build", "_execute_product_outputs"}
