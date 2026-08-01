from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.provider import DesignPlanRequest


def test_compact_plan_prompt_uses_compact_contract() -> None:
    prompt = GeminiCliProvider(model="test-model").build_design_plan_prompt(
        DesignPlanRequest(
            project_name="Project",
            original_intent="fit and retain a part",
            user_instruction="fit and retain a part",
            design_specification={"units": "mm"},
            planning_depth="compact_plan",
        )
    )

    assert "compact-cad-plan-v1" in prompt
    assert "compact CAD execution plan" in prompt
    assert "detailed Design Plan" not in prompt
