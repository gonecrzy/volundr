import json
import sys

import pytest

from app.services.cad.cadquery_runner import CadQueryCliRunner


SOURCE = '''
import cadquery as cq
from volundr_cad.runtime import PrintableOutput, Product, component, feature

def _ai_component_body(params):
    return cq.Workplane("XY").box(20, 20, 4)

@component("body")
def build_component_body(params):
    body = _ai_component_body(params)
    return apply_feature_slot(body, params)

def _ai_feature_slot(body, params):
    cutter = cq.Workplane("XY").box(4, 8, 8).translate((0, 0, 2))
    return body.cut(cutter)

@feature("slot", component="body")
def apply_feature_slot(body, params):
    return _ai_feature_slot(body, params)

def build(params):
    return Product(outputs=[PrintableOutput(output_id="body", label="Body", model=build_component_body(params), component_id="body", expected_solid_count=1, allow_disconnected_solids=False)])
'''


@pytest.mark.asyncio
async def test_execution_manifest_records_compact_source_to_result_feature_trace(tmp_path) -> None:
    runner = CadQueryCliRunner(
        python_binary=sys.executable,
        workspace_root=tmp_path,
        timeout_seconds=30,
    )

    result = await runner.compile(SOURCE, "feature-trace-test")

    assert result.success is True
    payload = json.loads(result.execution_manifest_path.read_text(encoding="utf-8"))
    traces = payload["feature_trace"]
    trace = next(item for item in traces if item["source_function_id"] == "_ai_feature_slot")
    assert trace["source_executed"] is True
    assert trace["shape_changed"] is True
    assert trace["input_shape_hash"]
    assert trace["output_shape_hash"]
    assert trace["input"]["solid_count"] == 1
    assert trace["output"]["solid_count"] == 1
    assert trace["operation_category"] == "subtractive"


@pytest.mark.asyncio
async def test_execution_manifest_records_no_effect_feature_trace(tmp_path) -> None:
    source = SOURCE.replace(
        'return body.cut(cutter)',
        'return body',
    )
    runner = CadQueryCliRunner(
        python_binary=sys.executable,
        workspace_root=tmp_path,
        timeout_seconds=30,
    )

    result = await runner.compile(source, "feature-trace-no-effect-test")

    assert result.success is True
    payload = json.loads(result.execution_manifest_path.read_text(encoding="utf-8"))
    trace = next(item for item in payload["feature_trace"] if item["source_function_id"] == "_ai_feature_slot")
    assert trace["source_executed"] is True
    assert trace["shape_changed"] is False
    assert trace["operation_category"] == "no_effect"
