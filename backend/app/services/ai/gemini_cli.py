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
OPENSCAD_GENERATION_PROMPT_VERSION = "openscad-generation-v3"
PLANNED_OPENSCAD_GENERATION_PROMPT_VERSION = "openscad-generation-v5"
STRUCTURED_REVISION_PROMPT_VERSION = "openscad-revision-v2"
COMPONENT_REVISION_PROMPT_VERSION = "openscad-component-revision-v1"
SCOPE_CORRECTION_PROMPT_VERSION = "scope-correction-v1"
LEGACY_INITIAL_PROMPT_VERSION = "legacy-initial-v1"
LEGACY_REVISION_PROMPT_VERSION = "legacy-revision-v1"
CONTRACT_REPAIR_PROMPT_VERSION = "contract-repair-v2"
LEGACY_COMPILE_REPAIR_PROMPT_VERSION = "legacy-compile-repair-v1"
CADQUERY_SOURCE_PROMPT_VERSION = "cadquery-source-v2"


def _current_source_prompt_section(*, current_source: str, is_repair: bool) -> list[str]:
    if is_repair:
        return [
            "",
            "Current OpenSCAD source requiring repair. Preserve only geometry that is not contradicted by the diagnostics, user request, or source contract.",
            "Fix the diagnosed issue directly; do not preserve disconnected, non-compiling, invalid, or incorrectly positive/subtractive geometry:",
            current_source,
        ]
    return [
        "",
        "Current accepted OpenSCAD source. Preserve working geometry that is not contradicted by the user request.",
        "If the user requests a stylistic or functional redesign, make that requested change while preserving the functional core and source contract:",
        current_source,
    ]


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
        prompt = self.build_prompt(request)
        raw_output = await self._run_prompt(prompt)

        return ModelGenerationResult(
            raw_output=raw_output,
            provider="gemini_cli",
            provider_model=self.model,
        )

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
        if request.contract_diagnostics:
            return CONTRACT_REPAIR_PROMPT_VERSION
        if request.scope_diagnostics:
            return SCOPE_CORRECTION_PROMPT_VERSION
        if request.compiler_diagnostics:
            return LEGACY_COMPILE_REPAIR_PROMPT_VERSION
        if request.revision_plan and request.scoped_revision_context:
            return COMPONENT_REVISION_PROMPT_VERSION
        if request.revision_plan:
            return STRUCTURED_REVISION_PROMPT_VERSION
        if request.current_source:
            return LEGACY_REVISION_PROMPT_VERSION
        if request.design_plan:
            return PLANNED_OPENSCAD_GENERATION_PROMPT_VERSION
        if request.design_specification:
            return OPENSCAD_GENERATION_PROMPT_VERSION
        return LEGACY_INITIAL_PROMPT_VERSION

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
        return self._build_prompt(request)

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
            "- Do not use OpenSCAD syntax. This is Python CadQuery, not SCAD.",
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
            "- Use `hole(diameter)` for holes; if you need several holes, use pushPoints([...]).hole(diameter).",
            "- Do not call hallucinated or unavailable helpers such as `.holes()`, `.knurl()`, `.hexArray()`, `.triangle()`, `.distribute()`, `.add_knurling()`, or `show_object()`.",
            "- Do not add top-level execution such as `product = build(params)`; Volundr calls build(params).",
            "",
        ]
        if request.current_source or request.compiler_diagnostics:
            parts.extend(
                [
                    "Repair mode:",
                    "- Repair the current CadQuery source so it satisfies the same user intent and compiles cleanly.",
                    "- Preserve the top-level parameter names and meanings unless a diagnostic proves one is invalid.",
                    "- Fix the diagnosed Python/CadQuery API issue directly; do not rewrite into OpenSCAD or another CAD language.",
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

    def _build_prompt(self, request: ModelGenerationRequest) -> str:
        if request.contract_diagnostics:
            return self._build_contract_repair_prompt(request)
        if request.scope_diagnostics:
            return self._build_scope_correction_prompt(request)
        if request.revision_plan and request.current_source and request.scoped_revision_context:
            return self._build_component_revision_prompt(request)
        if request.revision_plan and request.current_source:
            return self._build_structured_revision_prompt(request)
        if request.design_specification and request.design_plan and not request.current_source:
            return self._build_planned_openscad_prompt(request)
        if request.design_specification and not request.current_source:
            return self._build_design_spec_openscad_prompt(request)
        parts = [
            "You generate OpenSCAD for Volundr.",
            "Return only a single OpenSCAD source block. Do not include shell commands.",
            "Follow these rules exactly:",
            *self._legacy_openscad_generation_rules(),
            "",
            *self._legacy_openscad_pattern_examples(),
            "",
            f"Project name: {request.project_name}",
            f"Original intent: {request.original_intent}",
            f"User instruction: {request.user_instruction}",
        ]
        if request.current_source:
            if request.design_specification:
                parts.extend(
                    [
                        "",
                        "Design Specification context is authoritative for protected dimensions and requirements:",
                        json.dumps(request.design_specification, indent=2, sort_keys=True),
                    ]
                )
            parts.extend(
                _current_source_prompt_section(
                    current_source=request.current_source,
                    is_repair=bool(request.compiler_diagnostics),
                )
            )
        if request.compiler_diagnostics:
            parts.extend(["", "Compiler diagnostics to account for:", request.compiler_diagnostics])
        return "\n".join(parts)

    def _build_source_brief_prompt(self, request: SourceBriefRequest) -> str:
        return "\n".join(
            [
                "You create a compact structured design brief before OpenSCAD generation.",
                "Return JSON only. Do not generate OpenSCAD.",
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

    def _legacy_openscad_generation_rules(self) -> list[str]:
        return [
            "- Units are millimeters.",
            "- Include a USER PARAMETERS section.",
            "- Define module main_model().",
            "- End with exactly one top-level main_model(); call.",
            "- Do not use import(), surface(), include/use paths, host file access, STL, binary data, or base64.",
            *self._openscad_syntax_guardrails(),
            "- Prefer practical FDM-printable functional geometry.",
            "- Treat explicit style, theme, silhouette, and decorative requests as part of the design intent, not as optional extras.",
            "- Build requested functional features as real geometry before adding or integrating styling; the styled result must still satisfy the requested object type and use.",
            "- Do not automatically simplify away requested creative or stylistic geometry; build it when it can coexist with the functional core.",
            "- Model requested through-holes, slots, pockets, and clearances as subtractive geometry inside difference(), with cutters that pass completely through the target solid.",
            "- Keep requested decorative cutouts, relief, silhouettes, vents, windows, slots, or pockets local and bounded so they do not destroy load-bearing geometry or required mounting/contact surfaces.",
            "- Every subtraction must serve requested function, requested style, or necessary clearance; avoid subtractive features that weaken unrelated support surfaces.",
            "- Preserve load-bearing walls, mounting faces, tray support surfaces, retention features, and handles unless the user asks to change them.",
            "- If a grip, access notch, drain, fastener hole, clearance cut, or decorative feature is needed, keep it sized and positioned for that purpose instead of cutting through unrelated geometry.",
        ]

    def _openscad_syntax_guardrails(self) -> list[str]:
        return [
            "- Use valid OpenSCAD syntax only; this is not CadQuery, Build123D, Python, JavaScript, or object-oriented CAD.",
            "- Do not use pseudo-CAD method chaining such as .translate(), .rotate(), .union(), .workplane(), .add_hole(), or #print().",
            "- Do not assign geometry objects to variables; define modules and call them inside union(), difference(), hull(), or minkowski().",
            "- Do not call unknown modules such as extrude(); use linear_extrude() or rotate_extrude() with valid OpenSCAD child geometry.",
            "- Use PI for the circle constant; do not use lowercase pi.",
            "- Every assignment and module call must be syntactically complete with balanced parentheses/braces and semicolons where OpenSCAD requires them.",
            "- Do not write recursive modules or self-calling modules; every module expansion must be finite.",
            "- circle() accepts r or d, not r1/r2. Use cylinder(h=..., r1=..., r2=...) only for tapered 3D cylinders.",
            "- For thread-like or knurled details, prefer bounded approximations such as grooves, ribs, shallow cuts, or labeled clearance holes over invalid rotate_extrude tricks.",
            "- For one-piece outputs, all visible bodies must physically overlap or be joined into one connected solid unless the user explicitly requests separate parts.",
            "- Do not leave decorative silhouettes, ribs, handles, indicators, or cutout frames as loose disconnected solids.",
            "- Do not call non-existent string parsing helpers such as str_to_num; OpenSCAD string handling is limited.",
            "- String parameters are for labels, style choices, or selection. Use explicit numeric parameters or derived numeric defaults for geometry.",
        ]

    def _legacy_openscad_pattern_examples(self) -> list[str]:
        return [
            "CAD PATTERN EXAMPLES:",
            "- through_hole_example: use oversized subtractive cutters inside difference():",
            "  eps = 0.01;",
            "  difference() {",
            "    cube([part_length, part_width, part_thickness]);",
            "    translate([x, y, -eps]) cylinder(h = part_thickness + 2*eps, d = hole_diameter);",
            "  }",
            "- l_bracket_core_example: make a real 90-degree support from perpendicular solids before styling:",
            "  union() {",
            "    cube([shelf_leg_length, bracket_width, material_thickness]);",
            "    rotate([0, -90, 0]) cube([wall_leg_length, bracket_width, material_thickness]);",
            "    translate([rib_offset, 0, material_thickness]) rotate([0, -90, 0]) linear_extrude(height = rib_thickness) polygon([[0,0], [rib_x,0], [0,rib_z]]);",
            "  }",
            "- style_overlay_example: style visible regions after the functional core; keep mounting faces and holes outside decorative cuts.",
        ]

    def _build_design_spec_openscad_prompt(self, request: ModelGenerationRequest) -> str:
        return "\n".join(
            [
                "You generate OpenSCAD for Volundr from an approved Design Specification.",
                "Return only a single fenced openscad block. Do not include prose outside the block.",
                "The Design Specification is the authoritative design source. The raw user request is secondary intent only.",
                "Preserve every protected value and required feature exactly.",
                "Expose important dimensions as named user parameters.",
                "Every protected critical dimension must have a machine-readable mapping comment immediately before its parameter assignment:",
                "// @volundr-requirement <design_spec_requirement_id>",
                "Every protected functional requirement must have a machine-readable feature marker immediately before the implementing module or statement:",
                "// @volundr-feature <design_spec_requirement_id>",
                "Add machine-readable geometry markers for measurable protected geometry immediately after the related feature marker or before the related module:",
                "// @volundr-geometry type=bounds x=<width_parameter> y=<depth_parameter> z=<height_parameter>",
                "// @volundr-geometry type=hole_group count=<integer> diameter=<diameter_parameter> spacing=<spacing_parameter> axis=x|y|z",
                "// @volundr-geometry type=hole diameter=<diameter_parameter> axis=x|y|z",
                "// @volundr-geometry type=wall_thickness value=<wall_thickness_parameter> region=<short_region_id>",
                "Use geometry markers only for dimensions or features represented by named parameters in the source.",
                "Disclose product defaults and AI assumptions in source comments.",
                "Do not add undocumented critical dimensions.",
                "Keep the model in millimeters, near the XY origin, and at or above Z=0.",
                "Define module main_model() and end with exactly one top-level main_model(); call.",
                "Do not use import(), surface(), include/use paths, host file access, STL, binary data, or base64.",
                *self._openscad_syntax_guardrails(),
                "Use this recognizable section skeleton:",
                "/* Project: ...",
                "Units: millimeters",
                "Purpose: ...",
                "Assumptions: ...",
                "Print notes: ... */",
                "// ===== QUALITY =====",
                "// ===== USER PARAMETERS =====",
                "// ===== DERIVED VALUES =====",
                "// ===== VALIDATION =====",
                "// ===== MODULES =====",
                "// ===== FINAL MODEL =====",
                "",
                f"Project name: {request.project_name}",
                f"Original intent: {request.original_intent}",
                f"Secondary raw user request: {request.user_instruction}",
                "",
                "Approved Design Specification JSON:",
                json.dumps(request.design_specification, indent=2, sort_keys=True),
            ]
        )

    def _build_planned_openscad_prompt(self, request: ModelGenerationRequest) -> str:
        return "\n".join(
            [
                "You generate OpenSCAD for Volundr from an approved Parametric Design Plan.",
                "Return only a single fenced openscad block. Do not include prose outside the block.",
                "The Design Specification is the requirements authority. The approved Design Plan is the product-structure authority.",
                "Preserve every protected requirement, Design Plan parameter, dependency edge, component, feature, preset-relevant parameter, and printable output.",
                "Expose editable Design Plan parameters in USER PARAMETERS.",
                "Place derived Design Plan parameters in DERIVED VALUES and preserve dependency relationships.",
                "Every protected Design Specification critical dimension and every Design Plan parameter with source_requirement_id must use // @volundr-requirement <design_spec_requirement_id> immediately before its parameter assignment. This includes count parameters such as tray_count.",
                "Every protected Design Specification functional requirement must use // @volundr-feature <design_spec_functional_requirement_id> immediately before the module or statement that implements that requirement. Do not use @volundr-requirement for functional requirements.",
                "Every component must use // @volundr-component <design_plan_component_id> near the parameter/module that implements it.",
                "Every feature must use // @volundr-feature <design_plan_feature_id> immediately before the implementing module or statement.",
                "Every dependency edge must use // @volundr-dependency <from_parameter_id> -> <to_parameter_id> immediately before the derived assignment.",
                "Generate one authoritative OpenSCAD source for the complete product.",
                "Every printable output must have one implementation module and one marker immediately before that module:",
                "// @volundr-output <output_id> module=<module_name> required=<true|false> filename=<safe_filename.stl> components=<comma_separated_component_ids>",
                "Define selected_output = \"<first_output_id>\" as a USER PARAMETERS value.",
                "Define module render_selected_output() that dispatches to the output module matching selected_output and asserts false for unknown output IDs.",
                "End with exactly one top-level render_selected_output(); call.",
                "Add @volundr-geometry markers for supported measurable bounds, holes, hole groups, and wall thickness.",
                "Include assertions for invalid configurations and dependencies, such as impossible counts, negative clearances, too-thin walls, or outputs that exceed derived bounds.",
                "For cases, trays, holders, and enclosures, prefer additive construction of explicit base, side walls, rails, lips, lids, and handles. If using difference() for a cavity, bound the subtractor so it cannot remove a required wall, top bridge, handle support, retention feature, or mounting surface.",
                "Any handle, latch, retention stop, rail, rib, or hinge feature must have positive overlap with its supporting component; do not leave required features as disconnected bodies in a single printable output.",
                "Use this same selected-output contract for single-output plans.",
                "Do not require source-file edits between component compiles; Volundr will compile each output with a command-line selected_output override.",
                "Keep the model in millimeters, near the XY origin, and at or above Z=0.",
                "Do not use import(), surface(), include/use paths, host file access, STL, binary data, or base64.",
                *self._openscad_syntax_guardrails(),
                "",
                f"Project name: {request.project_name}",
                f"Original intent: {request.original_intent}",
                f"Secondary raw user request: {request.user_instruction}",
                "",
                "Approved Design Specification JSON:",
                json.dumps(request.design_specification, indent=2, sort_keys=True),
                "",
                "Approved Parametric Design Plan JSON:",
                json.dumps(request.design_plan, indent=2, sort_keys=True),
            ]
        )

    def _build_design_plan_prompt(self, request: DesignPlanRequest) -> str:
        if request.schema_repair_of_raw_output is not None:
            task = [
                "Repair this Parametric Design Plan response into valid JSON for the required schema.",
                "Do not generate OpenSCAD. Do not invent new critical requirements.",
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
                "Return JSON only. Do not generate OpenSCAD.",
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
                "Do not generate OpenSCAD. Do not broaden the revision scope.",
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
                "Return JSON only. Do not generate OpenSCAD.",
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

    def _build_structured_revision_prompt(self, request: ModelGenerationRequest) -> str:
        return "\n".join(
            [
                "Revise this Volundr OpenSCAD project from an approved structured Revision Plan.",
                "Return only a single fenced openscad block. Do not include prose outside the block.",
                "The Revision Plan is the only authority for what may change.",
                "Return complete authoritative OpenSCAD source for the whole product.",
                "Change only approved targets and dependency changes.",
                "Preserve all protected requirement, component, feature, dependency, geometry, and output markers.",
                "Retain every planned printable output and the selected_output/render_selected_output contract.",
                "Preserve unrelated modules and unaffected output behavior where practical.",
                "Do not simplify away difficult features, remove outputs, or redesign unrelated components.",
                "Do not use import(), surface(), include/use paths, host file access, STL, binary data, or base64.",
                "",
                f"Project name: {request.project_name}",
                f"Original intent: {request.original_intent}",
                f"User revision request: {request.user_instruction}",
                "",
                "Approved Revision Plan JSON:",
                json.dumps(request.revision_plan, indent=2, sort_keys=True),
                "",
                "Current Design Specification JSON:",
                json.dumps(request.design_specification, indent=2, sort_keys=True),
                "",
                "Current Design Plan JSON:",
                json.dumps(request.design_plan, indent=2, sort_keys=True),
                "",
                "Current output manifest:",
                json.dumps(request.output_manifest, indent=2, sort_keys=True),
                "",
                "Selected findings:",
                json.dumps(request.selected_findings, indent=2, sort_keys=True),
                "",
                "Base authoritative OpenSCAD source:",
                request.current_source or "",
            ]
        )

    def _build_component_revision_prompt(self, request: ModelGenerationRequest) -> str:
        return "\n".join(
            [
                "Revise this Volundr OpenSCAD project using the approved component-scoped Revision Plan.",
                "Return only a single fenced openscad block. Do not include prose outside the block.",
                "Return the complete authoritative SCAD source for the whole product; do not return a source fragment.",
                "Edit only targeted components, targeted features, targeted outputs, and explicitly allowed shared modules.",
                "Preserve protected component modules, protected feature markers, protected output mappings, protected interface parameters, and protected parameter values.",
                "Preserve selected_output and render_selected_output behavior for every planned printable output.",
                "Preserve active configuration compatibility: all configured override parameters must remain exposed and must not be reset to Design Plan defaults.",
                "Do not rename unrelated modules, remove difficult features, add undeclared outputs/components, or broaden the revision scope.",
                "If an unplanned shared dependency appears necessary, keep the source unchanged in that area and let Volundr reject or re-plan the revision.",
                "Do not use import(), surface(), include/use paths, host file access, STL, binary data, or base64.",
                "",
                f"Project name: {request.project_name}",
                f"Original intent: {request.original_intent}",
                f"User revision request: {request.user_instruction}",
                "",
                "Scoped revision context:",
                json.dumps(request.scoped_revision_context, indent=2, sort_keys=True),
                "",
                "Active configuration context:",
                json.dumps(request.configuration_context, indent=2, sort_keys=True),
                "",
                "Approved Revision Plan JSON:",
                json.dumps(request.revision_plan, indent=2, sort_keys=True),
                "",
                "Current Design Specification JSON:",
                json.dumps(request.design_specification, indent=2, sort_keys=True),
                "",
                "Current Design Plan JSON:",
                json.dumps(request.design_plan, indent=2, sort_keys=True),
                "",
                "Current output manifest:",
                json.dumps(request.output_manifest, indent=2, sort_keys=True),
                "",
                "Selected findings:",
                json.dumps(request.selected_findings, indent=2, sort_keys=True),
                "",
                "Base authoritative OpenSCAD source:",
                request.current_source or "",
            ]
        )

    def _build_scope_correction_prompt(self, request: ModelGenerationRequest) -> str:
        return "\n".join(
            [
                "Correct this revised Volundr OpenSCAD source so it satisfies the approved component revision scope.",
                "Return only a single fenced openscad block. Do not include prose outside the block.",
                "This is scope correction, not a new design revision.",
                "Return complete authoritative SCAD source for the whole product; do not return a fragment.",
                "Revert unauthorized edits to protected components, protected outputs, protected interface parameters, unapproved shared modules, and unrelated modules.",
                "Preserve the approved targeted change where it does not conflict with the scope findings.",
                "Do not broaden the revision, add undeclared outputs/components, or rename unrelated modules.",
                "Preserve active configuration compatibility and every output selector mapping.",
                "",
                f"Project name: {request.project_name}",
                f"User revision request: {request.user_instruction}",
                "",
                "Approved Revision Plan JSON:",
                json.dumps(request.revision_plan, indent=2, sort_keys=True),
                "",
                "Scoped revision context:",
                json.dumps(request.scoped_revision_context, indent=2, sort_keys=True),
                "",
                "Scope findings to correct:",
                request.scope_diagnostics or "",
                "",
                "Current revised source that exceeded scope:",
                request.current_source or "",
            ]
        )

    def _build_contract_repair_prompt(self, request: ModelGenerationRequest) -> str:
        has_design_plan_outputs = bool(
            request.design_plan
            and any(
                isinstance(output, dict) and output.get("id")
                for output in request.design_plan.get("printable_outputs", [])
            )
        )
        final_model_instruction = (
            "Ensure the file ends with exactly one top-level render_selected_output(); call."
            if has_design_plan_outputs
            else "Ensure module main_model() exists and the file ends with exactly one top-level main_model(); call."
        )
        design_plan_instructions = (
            [
                "Preserve selected_output, render_selected_output(), and every @volundr-output mapping from the Design Plan.",
                "Repair missing Design Plan @volundr-component, @volundr-feature, @volundr-dependency, and @volundr-output markers without changing the intended geometry.",
                "Dependency markers must exactly match Design Plan edges as // @volundr-dependency <from_parameter_id> -> <to_parameter_id> immediately before the assignment for the target parameter.",
                "Do not copy validator diagnostic text such as 'expected' or 'detected' into any @volundr-dependency marker.",
            ]
            if request.design_plan
            else []
        )
        return "\n".join(
            [
                "Repair OpenSCAD source so it satisfies Volundr source-contract validation.",
                "Return only a single fenced openscad block. Do not include prose outside the block.",
                "This is contract repair, not design revision.",
                "Preserve geometry, all user dimensions, protected Design Specification values, required features, unrelated modules, and working Boolean structure.",
                "Only fix the listed contract violations, marker omissions, section omissions, prohibited constructs, or verifiability issues.",
                "Do not change protected parameter values unless the diagnostics explicitly say the current value is wrong and the Design Specification value is provided.",
                "Do not use import(), surface(), include/use paths, host file access, STL, binary data, or base64.",
                "Ensure every protected Design Specification critical dimension uses // @volundr-requirement <id> immediately before the parameter assignment, including count parameters such as tray_count.",
                "Ensure every protected Design Specification functional requirement uses // @volundr-feature <id> immediately before the implementing module or statement.",
                "Do not use @volundr-requirement for protected functional requirements; use @volundr-feature for those.",
                "Preserve and repair // @volundr-geometry markers for bounds, hole groups, holes, and wall thickness when those features exist.",
                "Do not add geometry markers that claim a feature or dimension the source does not implement.",
                *design_plan_instructions,
                final_model_instruction,
                "",
                f"Project name: {request.project_name}",
                f"Original intent: {request.original_intent}",
                f"User instruction: {request.user_instruction}",
                "",
                "Source-contract diagnostics:",
                request.contract_diagnostics or "",
                "",
                "Authoritative Design Specification JSON:",
                json.dumps(request.design_specification, indent=2, sort_keys=True),
                "",
                "Authoritative Design Plan JSON:",
                json.dumps(request.design_plan, indent=2, sort_keys=True),
                "",
                "Source to repair:",
                request.current_source or "",
            ]
        )

    def _build_requirement_prompt(self, request: RequirementExtractionRequest) -> str:
        if request.schema_repair_of_raw_output is not None:
            task = [
                "Repair this requirement-extraction response into valid JSON for the required schema.",
                "Do not add OpenSCAD. Do not invent critical dimensions.",
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
                "Return JSON only. Do not generate OpenSCAD.",
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
