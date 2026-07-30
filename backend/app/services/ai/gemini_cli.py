import asyncio
import contextlib
import json
import os
import signal
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.ai.provider import (
    DesignPlanRequest,
    DesignPlanResult,
    ModelGenerationRequest,
    ModelGenerationResult,
    RequirementExtractionRequest,
    RequirementExtractionResult,
    RevisionPlanRequest,
    RevisionPlanResult,
    SourceBriefRequest,
    SourceBriefResult,
)

GEMINI_RULESET_VERSION = "gemini-ruleset-v1"
REQUIREMENTS_PROMPT_VERSION = "requirements-v1"
SOURCE_BRIEF_PROMPT_VERSION = "source-brief-v1"
DESIGN_PLAN_PROMPT_VERSION = "design-plan-v1"
REVISION_PLAN_PROMPT_VERSION = "revision-planning-v1"
SCOPE_CORRECTION_PROMPT_VERSION = "cadquery-scope-correction-v1"
CONTRACT_REPAIR_PROMPT_VERSION = "cadquery-contract-repair-v1"
CADQUERY_SOURCE_PROMPT_VERSION = "cadquery-generation-v1"
CADQUERY_EXECUTION_REPAIR_PROMPT_VERSION = "cadquery-execution-repair-v1"


class GeminiCliProvider:
    def __init__(
        self,
        *,
        binary: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
        policy_path: str | Path | None = None,
    ) -> None:
        self.binary = binary or settings.gemini_binary
        self.model = model or settings.gemini_model
        self.timeout_seconds = timeout_seconds or settings.gemini_timeout_seconds
        configured_policy = policy_path if policy_path is not None else settings.gemini_policy_path
        self.policy_path = Path(configured_policy) if configured_policy else Path(__file__).with_name("gemini_no_tools_policy.toml")

    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        return await self.generate_cadquery_model(request)

    async def generate_cadquery_model(
        self,
        request: ModelGenerationRequest,
    ) -> ModelGenerationResult:
        prompt = self.build_cadquery_prompt(request)
        raw_output = await self._run_prompt(prompt)

        return ModelGenerationResult(
            raw_output=raw_output,
            provider="gemini_cli",
            provider_model=self.model,
        )

    async def extract_requirements(
        self,
        request: RequirementExtractionRequest,
    ) -> RequirementExtractionResult:
        prompt = self.build_requirement_prompt(request)
        raw_output = await self._run_prompt(prompt)

        return RequirementExtractionResult(
            raw_output=raw_output,
            provider="gemini_cli",
            provider_model=self.model,
        )

    async def create_source_brief(self, request: SourceBriefRequest) -> SourceBriefResult:
        prompt = self.build_source_brief_prompt(request)
        raw_output = await self._run_prompt(prompt)

        return SourceBriefResult(
            raw_output=raw_output,
            provider="gemini_cli",
            provider_model=self.model,
        )

    async def create_design_plan(self, request: DesignPlanRequest) -> DesignPlanResult:
        prompt = self.build_design_plan_prompt(request)
        raw_output = await self._run_prompt(prompt)

        return DesignPlanResult(
            raw_output=raw_output,
            provider="gemini_cli",
            provider_model=self.model,
        )

    async def create_revision_plan(self, request: RevisionPlanRequest) -> RevisionPlanResult:
        prompt = self.build_revision_plan_prompt(request)
        raw_output = await self._run_prompt(prompt)

        return RevisionPlanResult(
            raw_output=raw_output,
            provider="gemini_cli",
            provider_model=self.model,
        )

    async def _run_prompt(self, prompt: str) -> str:
        command = self.build_command(prompt)

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        stdout_task = asyncio.create_task(self._read_stream(process.stdout))
        stderr_task = asyncio.create_task(self._read_stream(process.stderr))
        try:
            await asyncio.wait_for(process.wait(), timeout=self.timeout_seconds)
        except TimeoutError as exc:
            await self._terminate_process_group(process)
            stdout, stderr = await self._collect_output(stdout_task, stderr_task)
            diagnostic = self._diagnostic_tail(stderr) or self._diagnostic_tail(stdout)
            message = f"Gemini CLI timed out after {self.timeout_seconds} seconds"
            if diagnostic:
                message = f"{message}: {diagnostic}"
            raise RuntimeError(message) from exc
        except asyncio.CancelledError:
            self._kill_process_group(process)
            stdout_task.cancel()
            stderr_task.cancel()
            raise

        stdout, stderr = await self._collect_output(stdout_task, stderr_task)

        if process.returncode != 0:
            diagnostic = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(diagnostic or "Gemini CLI failed")

        return stdout.decode("utf-8", errors="replace")

    async def _terminate_process_group(
        self,
        process: asyncio.subprocess.Process,
    ) -> None:
        if process.returncode is not None:
            return
        self._signal_process_group(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            self._kill_process_group(process)
            with contextlib.suppress(Exception):
                await process.wait()

    async def _read_stream(
        self,
        stream: asyncio.StreamReader | None,
    ) -> bytes:
        if stream is None:
            return b""
        return await stream.read()

    async def _collect_output(
        self,
        stdout_task: asyncio.Task[bytes],
        stderr_task: asyncio.Task[bytes],
    ) -> tuple[bytes, bytes]:
        outputs = await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        return tuple(output if isinstance(output, bytes) else b"" for output in outputs)  # type: ignore[return-value]

    def _kill_process_group(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        self._signal_process_group(process.pid, signal.SIGKILL)

    def _signal_process_group(self, pid: int, sig: signal.Signals) -> None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pid, sig)

    def build_command(self, prompt: str) -> list[str]:
        command = [self.binary, "-p", prompt, "--output-format", "text", "--skip-trust"]
        if self.model:
            command.extend(["--model", self.model])
        if self.policy_path:
            command.extend(["--policy", str(self.policy_path)])
        return command

    def _diagnostic_tail(self, output: bytes, *, max_chars: int = 1200) -> str:
        text = output.decode("utf-8", errors="replace").strip()
        if not text:
            return ""
        return text[-max_chars:]

    @property
    def gemini_ruleset_version(self) -> str:
        return GEMINI_RULESET_VERSION

    @property
    def ruleset_version(self) -> str:
        return self.gemini_ruleset_version

    def prompt_template_version_for(self, request: ModelGenerationRequest) -> str:
        if request.compiler_diagnostics:
            return CADQUERY_EXECUTION_REPAIR_PROMPT_VERSION
        if request.contract_diagnostics:
            return CONTRACT_REPAIR_PROMPT_VERSION
        if request.scope_diagnostics:
            return SCOPE_CORRECTION_PROMPT_VERSION
        if request.revision_plan and request.scoped_revision_context:
            return "cadquery-component-revision-v1"
        if request.revision_plan:
            return "cadquery-revision-v1"
        return CADQUERY_SOURCE_PROMPT_VERSION

    def requirement_prompt_template_version(self) -> str:
        return REQUIREMENTS_PROMPT_VERSION

    def source_brief_prompt_template_version(self) -> str:
        return SOURCE_BRIEF_PROMPT_VERSION

    def cadquery_prompt_template_version(self) -> str:
        return CADQUERY_SOURCE_PROMPT_VERSION

    def design_plan_prompt_template_version(self) -> str:
        return DESIGN_PLAN_PROMPT_VERSION

    def revision_plan_prompt_template_version(self) -> str:
        return REVISION_PLAN_PROMPT_VERSION

    def provider_settings(self) -> dict[str, Any]:
        return {
            "binary": self.binary,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "output_format": "text",
            "skip_trust": True,
            "policy_path": str(self.policy_path) if self.policy_path else None,
            "auth_mode": "api_key" if os.environ.get("GEMINI_API_KEY") else "gemini_profile",
        }

    def build_prompt(self, request: ModelGenerationRequest) -> str:
        return self.build_cadquery_prompt(request)

    def build_cadquery_prompt(self, request: ModelGenerationRequest) -> str:
        parts = [
            "You generate CadQuery Python for Volundr.",
            "Return only a single fenced python block. Do not include prose outside the block.",
            "The response must start with ```python and end with ```.",
            "Follow these rules exactly:",
            "- Use millimeters.",
            "- Follow the cadquery-v1 source contract.",
            "- The only imports allowed are exactly `import cadquery as cq` and `from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product`.",
            "- Define typed `ParameterSpec` entries for user-adjustable dimensions and options.",
            "- Runtime signatures: `ParameterSpec(id, label, type, default, unit=None, min_value=None, max_value=None, choices=(), editable=True, protected=False)`, `PrintableOutput(output_id, label, model, component_id=None, component_ids=(), quantity=1, required=True, expected_solid_count=1, allow_disconnected_solids=False, metadata={})`, and `Product(outputs, parameters=(), schema_version=\"cadquery-v1\", metadata={})`.",
            "- Do not use unsupported ParameterSpec aliases such as description, min, max, minimum, maximum, value, default_value, units, or help; use `min_value` and `max_value` exactly for numeric ranges.",
            "- ParameterSpec type must be exactly one of float, int, bool, str, or enum; never use number.",
            "- Always quote ParameterSpec type values, for example type=\"float\"; never write type=float.",
            "- ParameterSpec default must be a literal value, not a variable reference.",
            "- Define all ParameterSpec entries at module level in `PARAMETERS = [...]` before build(params); never inside build(params).",
            "- Define `def build(params):` with exactly one parameter named params.",
            "- Do not define `build_model()`; that name is only for legacy probes.",
            "- Return exactly one `Product` from build(params).",
            "- Every output must be a `PrintableOutput` with output_id, component_id or component_ids, label, model, quantity, required, expected_solid_count, and allow_disconnected_solids.",
            "- Top-level statements may only be the allowed imports, literal parameter metadata, optional helper function definitions, and `def build(params):`.",
            "- Simple helper functions may also be defined inside build(params) when that makes the model easier to structure.",
            "- Do not run CadQuery operations, construct geometry, call helper functions, or do any other execution at top level.",
            "- Use params[\"parameter_id\"] inside build(params) instead of hard-coding editable dimensions.",
            "- build(params) must create CadQuery Workplane, Shape, Solid, Compound, or Assembly-exportable objects for PrintableOutput.model.",
            "- Do not use try/except; generated CadQuery must fail visibly so diagnostics can identify the real API or geometry issue.",
            "- Do not wrap fillet(), chamfer(), or optional details in try/except; use a simple known-good operation or omit the detail.",
            "- Do not import or use `math`; the only import allowed by the runner is `import cadquery as cq`.",
            "- Avoid sin/cos/trigonometric loops. Use fixed point lists or CadQuery polygon/spline profiles instead of sin/cos loops.",
            "- Do not call `map()`, `.split()`, or parse string parameters; use literal numeric parameters directly.",
            "- If `thread_spec` is requested, expose it as a numeric millimeter diameter such as `thread_spec = 6.0`, not a string like `M6x1`.",
            "- Do not write files, read files, import local modules, use shell commands, network access, subprocesses, pathlib, os, sys, eval, exec, open(), getattr(), globals(), locals(), or vars().",
            "- Do not use syntax from other CAD languages. This is Python CadQuery.",
            "- Prefer real CAD operations such as box(), cylinder(), workplane(), hole(), cutBlind(), cutThruAll(), union(), cut(), extrude(), loft(), fillet(), chamfer(), translate(), rotate(), and mirror().",
            "- Extrude only closed profiles such as rect(), circle(), polygon(), or polyline(...).close(); do not extrude a bare lineTo() path.",
            "- For one-piece outputs, boolean-union additive solids into one returned model unless the user explicitly requests separate parts.",
            "- Return the main fused solid directly, not a Compound of loose solids.",
            "- Model holes and cutouts as subtractive CadQuery features such as hole(), cutBlind(), cutThruAll(), or cut().",
            "- Keep requested creative/style geometry integrated with the functional body rather than returning loose decorative bodies.",
            "",
            "Known-good CadQuery patterns:",
            "- Multiple through-holes: `wp.faces(\">Z\").workplane().pushPoints([(x, y)]).hole(hole_diameter)`.",
            "- Translate with a single tuple: `shape.translate((x, y, z))`; do not pass x, y, z as separate translate arguments.",
            "- Build simple decorative solids with circle()/rect()/polygon()/box()/extrude(), then union() or cut() them into the functional body.",
            "- Prefer one extruded 2D profile for creative one-piece brackets: draw the functional L outline and creative silhouette as one closed polyline/spline, then extrude once.",
            "- Do not cut shallow decorative marks from faces unless the cutter overlaps the solid interior; non-overlapping or tangent cutters can create invalid fragments.",
            "- For indicator slots, use `rect(indicator_width, length).extrude(depth)` as a cutter, then cut it from the parent body.",
            "- When adding ribs, rails, handles, tabs, or decorations, overlap the parent solid by at least 0.5 mm before union(); never leave ribs, rails, handles, tabs, or decorations merely tangent to a face.",
            "- For tray carriers and open-top enclosures, build bottom, walls, rails, ribs, and handles from simple overlapping boxes instead of cutting one deep top-open cavity from a closed shell.",
            "- For carrier handles, use two overlapping posts and an overlapping crossbar; do not cut a finger hole through a standalone handle block.",
            "- Carrier handle posts must overlap side walls or the back wall, never float in the open center; place side handle posts at x = +/- (outer_width / 2 - wall_thickness / 2), or omit the handle rather than returning a disconnected or invalid handle.",
            "- For L brackets, prefer two overlapping rectangular flanges plus an overlapping triangular rib instead of one complex extruded L polyline.",
            "- Use `hole(diameter)` for holes; if you need several holes, use pushPoints([...]).hole(diameter).",
            "- For hinged boxes, prefer simple overlapping hinge tabs or barrels without pin-hole cuts; valid separate base and lid solids are more important than detailed hinge mechanics.",
            "- Do not call hallucinated or unavailable helpers such as `.holes()`, `.knurl()`, `.hexArray()`, `.triangle()`, `.distribute()`, `.add_knurling()`, or `show_object()`.",
            "- Do not add top-level execution such as `product = build(params)`; Volundr calls build(params).",
            "",
        ]
        if request.contract_diagnostics:
            parts.extend(
                [
                    "Contract repair mode:",
                    "- This is contract repair, not design revision.",
                    "- Repair only violations of the CadQuery product source contract.",
                    "- Preserve geometry, user dimensions, protected design-specification values, planned outputs, and unrelated working code.",
                    "- Keep every ParameterSpec ID and PrintableOutput output_id required by the Design Plan unless the diagnostics explicitly require a correction.",
                    "- If diagnostics mention unsupported ParameterSpec keywords, remove unsupported fields such as description and replace min/max aliases with min_value/max_value.",
                    "- Return the full corrected CadQuery Python source, not a patch.",
                    "",
                    "Source-contract diagnostics:",
                    request.contract_diagnostics,
                    "",
                    "Authoritative Design Specification JSON:",
                    json.dumps(request.design_specification, indent=2, sort_keys=True),
                    "",
                    "Authoritative Design Plan JSON:",
                    json.dumps(request.design_plan, indent=2, sort_keys=True),
                    "",
                    "Current CadQuery source to repair begins below:",
                    request.current_source or "",
                    "Current CadQuery source to repair ends above.",
                    "",
                ]
            )
        elif request.scope_diagnostics:
            parts.extend(
                [
                    "Revision scope correction mode:",
                    "- This is scope correction, not a new design revision.",
                    "- Revert unauthorized edits to protected components, protected outputs, protected parameters, and unrelated code.",
                    "- Preserve the approved targeted change where it does not conflict with the scope findings.",
                    "- Return the complete corrected CadQuery Python source for the whole product.",
                    "",
                    "Approved Revision Plan:",
                    json.dumps(request.revision_plan, indent=2, sort_keys=True),
                    "",
                    "Scoped revision context:",
                    json.dumps(request.scoped_revision_context, indent=2, sort_keys=True),
                    "",
                    "Scope diagnostics to correct:",
                    request.scope_diagnostics,
                    "",
                    "Current revised CadQuery source begins below:",
                    request.current_source or "",
                    "Current revised CadQuery source ends above.",
                    "",
                ]
            )
        elif request.revision_plan and request.current_source:
            parts.extend(
                [
                    "Structured revision mode:",
                    "- Return the complete revised CadQuery Python source for the whole product, not a patch.",
                    "- Make only changes approved by the Revision Plan and its scoped revision context.",
                    "- Preserve protected parameters, components, features, outputs, and interfaces exactly.",
                    "- Keep every existing PrintableOutput required by the Design Plan unless the Revision Plan explicitly permits removal.",
                    "- Preserve active configuration ParameterSpec IDs so configured revisions remain executable.",
                    "- Do not rewrite to another CAD language.",
                    "",
                    "Approved Revision Plan:",
                    json.dumps(request.revision_plan, indent=2, sort_keys=True),
                ]
            )
            if request.scoped_revision_context:
                parts.extend(
                    [
                        "",
                        "Scoped revision context:",
                        json.dumps(request.scoped_revision_context, indent=2, sort_keys=True),
                    ]
                )
            if request.configuration_context:
                parts.extend(
                    [
                        "",
                        "Active configuration context:",
                        json.dumps(request.configuration_context, indent=2, sort_keys=True),
                    ]
                )
            if request.scope_diagnostics:
                parts.extend(
                    [
                        "",
                        "Revision scope diagnostics to correct:",
                        request.scope_diagnostics,
                    ]
                )
            parts.extend(
                [
                    "",
                    "Current accepted CadQuery source begins below:",
                    request.current_source,
                    "Current accepted CadQuery source ends above.",
                    "",
                ]
            )
        elif request.current_source or request.compiler_diagnostics:
            parts.extend(
                [
                    "Repair mode:",
                    "- Repair the current CadQuery source so it satisfies the same user intent and compiles cleanly.",
                    "- Preserve the top-level parameter names and meanings unless a diagnostic proves one is invalid.",
                    "- Fix the diagnosed Python/CadQuery API issue directly; do not rewrite into another CAD language.",
                    "- Return the full corrected CadQuery Python source, not a patch.",
                    "",
                    "Compiler/runtime diagnostics:",
                    request.compiler_diagnostics or "No diagnostics provided.",
                    "",
                    "Current CadQuery source to repair begins below:",
                    request.current_source or "",
                    "Current CadQuery source to repair ends above.",
                    "",
                ]
            )
        parts.extend(
            [
                f"Project name: {request.project_name}",
                f"Original intent: {request.original_intent}",
                f"User instruction: {request.user_instruction}",
            ]
        )
        return "\n".join(parts)

    def build_requirement_prompt(self, request: RequirementExtractionRequest) -> str:
        return self._build_requirement_prompt(request)

    def build_source_brief_prompt(self, request: SourceBriefRequest) -> str:
        return self._build_source_brief_prompt(request)

    def build_design_plan_prompt(self, request: DesignPlanRequest) -> str:
        return self._build_design_plan_prompt(request)

    def build_revision_plan_prompt(self, request: RevisionPlanRequest) -> str:
        return self._build_revision_plan_prompt(request)

    def _build_source_brief_prompt(self, request: SourceBriefRequest) -> str:
        return "\n".join(
            [
                "You create a compact structured design brief before CAD source generation.",
                "Return JSON only. Do not generate CAD source.",
                "The brief constrains correctness without locking down the exact creative shape.",
                "Required JSON fields:",
                "- schema_version: exactly source-brief-v1",
                "- intent_understanding: object_type, functional_goal, style_goal",
                "- planned_outputs: array of printable outputs with id, expected_connected_body_count, must_be_connected, approx_size_mm",
                "- functional_features: array of required functional features with id and role/count when known",
                "- style_features: array of requested decorative features with id, role, and attachment_rule",
                "- hard_requirements: array of concise requirements for generation and validation",
                "- open_questions: array; leave empty when enough information is available",
                "",
                "Rules:",
                "- Prefer one connected printable body unless the user explicitly requests multiple separate parts.",
                "- If decorative features are requested, decorative features must physically attach, overlap, or be fused into the functional body unless the user asks for loose pieces.",
                "- Preserve creative freedom; do not prescribe exact polygons, coordinates, or a fixed template unless required for function.",
                "- Include approximate sizing only when implied by the prompt or benchmark expectations; use null for unknown dimensions.",
                "",
                f"Project name: {request.project_name}",
                f"Original intent: {request.original_intent}",
                f"User instruction: {request.user_instruction}",
                "",
                "Expected source parameters:",
                json.dumps(request.expected_parameters, indent=2, sort_keys=True),
                "",
                "Expected geometric invariants:",
                json.dumps(request.expected_geometric_invariants, indent=2, sort_keys=True),
                "",
                f"Mesh expectation: {request.mesh_expectation or 'not specified'}",
            ]
        )

    def _build_design_plan_prompt(self, request: DesignPlanRequest) -> str:
        if request.schema_repair_of_raw_output is not None:
            task = [
                "Repair this Parametric Design Plan response into valid JSON for the required schema.",
                "Do not generate CAD source. Do not invent new critical requirements.",
                "Preserve the original planning intent and return JSON only.",
                "",
                "Schema validation error:",
                request.schema_validation_error or "unknown schema error",
                "",
                "Invalid raw output:",
                request.schema_repair_of_raw_output,
            ]
        else:
            task = [
                "Create a generic Parametric Design Plan for Volundr from the approved Design Specification.",
                "Return JSON only. Do not generate CAD source.",
                "Model the product generically: parameters, derived parameters, dependency edges, components, features, presets, assembly strategy, printable outputs, risks, and design level.",
                "The Design Plan must be reusable for configurable functional products. Do not use a fishing-tray carrier as the schema template.",
                "A parameter with source_requirement_id must copy that source requirement's value and unit within tolerance. Do not use source_requirement_id for calculated stack, envelope, or overall product dimensions; represent those as derived_parameters with dependency_edges.",
                "Every dependency edge must connect existing parameter or derived_parameter IDs in the plan. If an edge target such as case_inner_height_mm is needed, include that target in derived_parameters with its expression and depends_on list.",
                "Do not use dependency_edges for component or feature IDs; feature dependencies belong in each feature's parameters list.",
                "Ask plan clarification only when component structure, printable outputs, assembly strategy, or configuration dependencies cannot be chosen safely.",
            ]
        schema = {
            "schema_version": "1.0",
            "design_level": "single_part|product|assembly",
            "product_type": "string",
            "purpose": "string",
            "units": "mm",
            "parameters": [
                {
                    "id": "string",
                    "label": "string",
                    "value": 0,
                    "unit": "mm",
                    "source_requirement_id": "string|null",
                    "editable": True,
                    "protected": False,
                    "component_id": "string|null",
                }
            ],
            "derived_parameters": [
                {
                    "id": "string",
                    "label": "string",
                    "expression": "string",
                    "unit": "mm",
                    "depends_on": ["parameter_id"],
                }
            ],
                "dependency_edges": [
                {
                    "from": "source_parameter_id",
                    "to": "dependent_parameter_or_derived_parameter_id",
                    "relationship": "string",
                }
            ],
            "components": [
                {
                    "id": "string",
                    "label": "string",
                    "description": "string",
                    "features": ["feature_id"],
                    "parameters": ["parameter_id"],
                }
            ],
            "features": [
                {
                    "id": "string",
                    "component_id": "component_id",
                    "type": "hole_group|wall|rib|shell|lid|slot|adapter|handle|other",
                    "description": "string",
                    "parameters": ["parameter_id"],
                    "protected": False,
                }
            ],
            "presets": [
                {
                    "id": "string",
                    "label": "string",
                    "parameter_values": {"parameter_id": 0},
                }
            ],
            "assembly_strategy": {"type": "single_part|multi_part|assembly", "instructions": ["string"]},
            "printable_outputs": [
                {
                    "id": "string",
                    "label": "string",
                    "component_ids": ["component_id"],
                    "quantity": 1,
                    "orientation": "string",
                }
            ],
            "risks": [
                {
                    "id": "string",
                    "severity": "notice|warning|critical",
                    "description": "string",
                    "mitigation": "string",
                }
            ],
            "clarification_required": False,
            "clarification_questions": [],
            "plan_ready": True,
            "outcome": "plan_ready|plan_clarification_required|plan_failed",
        }
        return "\n".join(
            task
            + [
                "",
                f"Project name: {request.project_name}",
                f"Original intent: {request.original_intent}",
                f"User request: {request.user_instruction}",
                "",
                "Approved Design Specification JSON:",
                json.dumps(request.design_specification, indent=2, sort_keys=True),
                "",
                "Previous Design Plan:",
                json.dumps(request.previous_design_plan, indent=2, sort_keys=True)
                if request.previous_design_plan
                else "None",
                "",
                "Clarification answers:",
                json.dumps(request.clarification_answers, indent=2, sort_keys=True),
                "",
                "Versioned defaults:",
                json.dumps(request.defaults, indent=2, sort_keys=True),
                "",
                "Required JSON shape:",
                json.dumps(schema, indent=2, sort_keys=True),
            ]
        )

    def _build_revision_plan_prompt(self, request: RevisionPlanRequest) -> str:
        if request.schema_repair_of_raw_output is not None:
            task = [
                "Repair this structured Revision Plan response into valid JSON for the required schema.",
                "Do not generate CAD source. Do not broaden the revision scope.",
                "Preserve the original revision intent and return JSON only.",
                "",
                "Schema validation error:",
                request.schema_validation_error or "unknown schema error",
                "",
                "Invalid raw output:",
                request.schema_repair_of_raw_output,
            ]
        else:
            task = [
                "Create a structured Volundr Revision Plan.",
                "Return JSON only. Do not generate CAD source.",
                "Identify the exact requested change, affected component/feature/output/parameter, required dependency changes, protected unaffected areas, validation findings addressed, versioning decision, success criteria, and prohibited changes.",
                "Use the Design Plan dependency graph to allow required dependent changes. Do not authorize broad redesign from source alone.",
                "Ask clarification when the target, value, strategy, base revision, or supported complexity is ambiguous.",
            ]
        schema = {
            "schema_version": "revision-plan-v1",
            "reason": "user_request|geometric_finding|printability_finding|source_quality_finding|assembly_finding|output_failure|parameter_change|preset_change|configuration_change",
            "summary": "string",
            "requested_changes": [
                {
                    "target_type": "product_parameter|derived_parameter|component|feature|printable_output|requirement|assembly_relationship|preset|validation_finding",
                    "target_id": "string",
                    "current_value": 0,
                    "requested_value": 0,
                    "change_type": "replace|add|remove|adjust",
                    "source": "user|finding|calculated",
                }
            ],
            "targeted_components": ["component_id"],
            "targeted_features": ["feature_id"],
            "targeted_outputs": ["output_id"],
            "targeted_findings": ["finding_id"],
            "allowed_parameter_changes": ["parameter_id"],
            "required_dependency_changes": [
                {"parameter_id": "parameter_id", "affects": ["dependent_id"]}
            ],
            "allowed_component_changes": ["component_id"],
            "allowed_feature_changes": ["feature_id"],
            "protected_parameters": [
                {"parameter_id": "parameter_id", "expected_value": 0, "unit": "mm"}
            ],
            "protected_components": ["component_id"],
            "protected_features": ["feature_id"],
            "protected_outputs": ["output_id"],
            "prohibited_changes": ["string"],
            "success_criteria": [
                {"type": "parameter_value", "target_id": "parameter_id", "expected_value": 0}
            ],
            "requires_design_specification_version": False,
            "requires_design_plan_version": False,
            "clarification_questions": [],
            "outcome": "revision_ready|clarification_required|revision_conflict|unsupported_revision|planning_failed",
        }
        return "\n".join(
            task
            + [
                "",
                f"Project name: {request.project_name}",
                f"Original intent: {request.original_intent}",
                f"Revision reason: {request.reason}",
                f"User revision request: {request.user_instruction}",
                f"Base revision id: {request.base_revision_id}",
                "",
                "Design Specification JSON:",
                json.dumps(request.design_specification, indent=2, sort_keys=True),
                "",
                "Approved Design Plan JSON:",
                json.dumps(request.design_plan, indent=2, sort_keys=True),
                "",
                "Output manifest:",
                json.dumps(request.output_manifest, indent=2, sort_keys=True),
                "",
                "Source metadata:",
                json.dumps(request.source_metadata, indent=2, sort_keys=True),
                "",
                "Selected findings:",
                json.dumps(request.selected_findings, indent=2, sort_keys=True),
                "",
                "Clarification answers:",
                json.dumps(request.clarification_answers, indent=2, sort_keys=True),
                "",
                "Previous Revision Plan:",
                json.dumps(request.previous_revision_plan, indent=2, sort_keys=True)
                if request.previous_revision_plan
                else "None",
                "",
                "Required JSON shape:",
                json.dumps(schema, indent=2, sort_keys=True),
            ]
        )

    def _build_requirement_prompt(self, request: RequirementExtractionRequest) -> str:
        if request.schema_repair_of_raw_output is not None:
            task = [
                "Repair this requirement-extraction response into valid JSON for the required schema.",
                "Do not add CAD source. Do not invent critical dimensions.",
                "Preserve the original meaning and return JSON only.",
                "",
                "Schema validation error:",
                request.schema_validation_error or "unknown schema error",
                "",
                "Invalid raw output:",
                request.schema_repair_of_raw_output,
            ]
        else:
            task = [
                "Extract a structured Volundr Design Specification from the user request.",
                "Return JSON only. Do not generate CAD source.",
                "Classify whether generation is ready, clarification is required, requirements conflict, or the request is unsupported.",
            "Do not silently invent critical dimensions. Use allowed defaults only when they are non-critical or explicitly defaultable.",
            "Do not use tools, web search, files, or external resources. Use only this prompt, supplied defaults, previous specifications, and clarification answers.",
            ]
        schema = {
            "schema_version": "1.0",
            "object_type": "string",
            "purpose": "string",
            "units": "mm",
            "supported_scope": True,
            "critical_dimensions": [
                {
                    "id": "string",
                    "label": "string",
                    "value": 0,
                    "unit": "mm",
                    "tolerance": None,
                    "source": "user|clarification|calculated|printer_profile|product_default|ai_assumption",
                    "importance": "critical|important|optional|cosmetic",
                    "protected": True,
                }
            ],
            "parameters": [],
            "functional_requirements": [],
            "print_requirements": {},
            "assumptions": [],
            "conflicts": [],
            "missing_requirements": [],
            "clarification_required": False,
            "clarification_questions": [],
            "generation_ready": True,
            "outcome": "generation_ready|clarification_required|requirements_conflict|unsupported_request|extraction_failed",
        }
        return "\n".join(
            task
            + [
                "",
                "Mandatory clarification cases include missing mating dimensions, conflicting dimensions, essential mounting method, required fastener geometry, unsafe fit inference, inaccessible internal cavity ambiguity, missing load context, ambiguous references, ambiguous units, and materially different interpretations.",
                "Ask no more than five minimal questions in the first round.",
                "",
                f"Project name: {request.project_name}",
                f"Original intent: {request.original_intent}",
                f"User request: {request.user_instruction}",
                "",
                "Versioned defaults:",
                json.dumps(request.defaults, indent=2, sort_keys=True),
                "",
                "Previous Design Specification:",
                json.dumps(request.previous_specification, indent=2, sort_keys=True)
                if request.previous_specification
                else "None",
                "",
                "Clarification answers:",
                json.dumps(request.clarification_answers, indent=2, sort_keys=True),
                "",
                "Required JSON shape:",
                json.dumps(schema, indent=2, sort_keys=True),
            ]
        )
