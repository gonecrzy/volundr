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
from app.services.cad.cadquery_source_authority import (
    format_authoritative_identity_section,
)
from app.services.cad.geometry_bodies import (
    GEOMETRY_BODIES_SCHEMA_VERSION,
    build_geometry_function_inventory,
)
from app.services.cad.source_scaffold import SCAFFOLD_VERSION
from app.services.projects.plan_provenance import FASTENER_LOOKUP_TABLES

GEMINI_RULESET_VERSION = "gemini-ruleset-v1"
REQUIREMENTS_PROMPT_VERSION = "requirements-v3"
SOURCE_BRIEF_PROMPT_VERSION = "source-brief-v1"
DESIGN_PLAN_PROMPT_VERSION = "design-plan-v3"
REVISION_PLAN_PROMPT_VERSION = "revision-planning-v1"
SCOPE_CORRECTION_PROMPT_VERSION = "cadquery-scope-correction-v2"
CONTRACT_REPAIR_PROMPT_VERSION = "cadquery-contract-repair-v3"
CADQUERY_SOURCE_PROMPT_VERSION = "cadquery-generation-v6"
CADQUERY_GEOMETRY_BODY_PROMPT_VERSION = "cadquery-geometry-body-v4"
CADQUERY_GEOMETRY_BODY_REPAIR_PROMPT_VERSION = "cadquery-geometry-body-repair-v4"
CADQUERY_EXECUTION_REPAIR_PROMPT_VERSION = "cadquery-execution-repair-v2"
CADQUERY_COMPONENT_REVISION_PROMPT_VERSION = "cadquery-component-revision-v2"


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
        if request.geometry_body_diagnostics:
            return CADQUERY_GEOMETRY_BODY_REPAIR_PROMPT_VERSION
        if request.generation_contract_version == SCAFFOLD_VERSION:
            return CADQUERY_GEOMETRY_BODY_PROMPT_VERSION
        if request.compiler_diagnostics:
            return CADQUERY_EXECUTION_REPAIR_PROMPT_VERSION
        if request.contract_diagnostics:
            return CONTRACT_REPAIR_PROMPT_VERSION
        if request.scope_diagnostics:
            return SCOPE_CORRECTION_PROMPT_VERSION
        if request.revision_plan and request.scoped_revision_context:
            return CADQUERY_COMPONENT_REVISION_PROMPT_VERSION
        if request.revision_plan:
            return "cadquery-revision-v1"
        return CADQUERY_SOURCE_PROMPT_VERSION

    def requirement_prompt_template_version(self) -> str:
        return REQUIREMENTS_PROMPT_VERSION

    def source_brief_prompt_template_version(self) -> str:
        return SOURCE_BRIEF_PROMPT_VERSION

    def cadquery_prompt_template_version(self) -> str:
        return CADQUERY_SOURCE_PROMPT_VERSION

    def cadquery_generation_contract_version(self) -> str:
        return SCAFFOLD_VERSION

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
        if request.generation_contract_version == SCAFFOLD_VERSION or request.geometry_body_diagnostics:
            return self.build_scaffold_geometry_prompt(request)
        parts = [
            "You generate CadQuery Python for Volundr.",
            "Return only a single fenced python block. Do not include prose outside the block.",
            "The response must start with ```python and end with ```.",
            "Follow these rules exactly:",
            "- Use millimeters.",
            "- Follow the cadquery-v1 source contract.",
            "- The only imports allowed are exactly `import cadquery as cq` and `from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product, component, feature, shared_helper, protected_interface`.",
            "- Define typed `ParameterSpec` entries for user-adjustable dimensions and options.",
            "- Runtime signatures: `ParameterSpec(id, label, type, default, unit=None, min_value=None, max_value=None, choices=(), editable=True, protected=False, source_requirement_id=None, source=None)`, `PrintableOutput(output_id, label, model, component_id=None, component_ids=(), quantity=1, required=True, expected_solid_count=1, allow_disconnected_solids=False, metadata={})`, and `Product(outputs, parameters=(), schema_version=\"cadquery-v1\", metadata={})`.",
            "- Use static ownership decorators on top-level helpers: `@component(\"component_id\")`, `@feature(\"feature_id\", component=\"component_id\")`, `@shared_helper(\"helper_id\")`, and `@protected_interface(\"interface_id\", parameters=(\"parameter_id\",))`.",
            "- Decorators are metadata only; still return the complete authoritative source from build(params), never source fragments.",
            "- Do not use unsupported ParameterSpec aliases such as description, min, max, minimum, maximum, value, default_value, units, or help; use `min_value` and `max_value` exactly for numeric ranges.",
            "- ParameterSpec type must be exactly one of float, int, bool, str, or enum; never use number.",
            "- Always quote ParameterSpec type values, for example type=\"float\"; never write type=float.",
            "- ParameterSpec default must be a literal value, not a variable reference.",
            "- When a Design Plan parameter has source_requirement_id or source, copy those fields into its ParameterSpec exactly.",
            "- Define all ParameterSpec entries at module level in `PARAMETERS = [...]` before build(params); never inside build(params).",
            "- Define `def build(params):` with exactly one parameter named params.",
            "- Do not define `build_model()`; generated source must use `build(params)`.",
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
                    "- Keep every ParameterSpec ID, @component ID, @feature ID, and PrintableOutput output_id required by the authoritative identity inventory exactly.",
                    "- Do not invent alternate IDs, remove parameters, hardcode protected values, redesign outputs, or change component decomposition.",
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
                    format_authoritative_identity_section(request.source_authority),
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
                    "- Revert every unauthorized identity change. Do not create aliases or replacement IDs.",
                    "- Preserve the approved targeted change where it does not conflict with the scope findings.",
                    "- Return the complete corrected CadQuery Python source for the whole product.",
                    "",
                    "Approved Revision Plan:",
                    json.dumps(request.revision_plan, indent=2, sort_keys=True),
                    "",
                    "Scoped revision context:",
                    json.dumps(request.scoped_revision_context, indent=2, sort_keys=True),
                    "",
                    format_authoritative_identity_section(request.source_authority),
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
                    "- Target stable component and output IDs are product identities; Python symbol names are flexible implementation details.",
                    "- New revision-local parameters are allowed only when the approved Revision Plan allows them.",
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
                    format_authoritative_identity_section(request.source_authority),
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
                    "- Preserve the authoritative parameter inventory, component IDs, feature IDs, output IDs, expected solid counts, and protected values.",
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
                    format_authoritative_identity_section(request.source_authority),
                    "",
                ]
            )
        elif request.design_specification or request.design_plan:
            design_specification = request.design_specification or {}
            design_plan = request.design_plan or {}
            printable_outputs = list(design_plan.get("printable_outputs", []))
            identity_table = {
                "required_components": [
                    component.get("id")
                    for component in design_plan.get("components", [])
                    if isinstance(component, dict) and component.get("id")
                ],
                "required_features": [
                    {
                        "id": feature.get("id"),
                        "component_id": feature.get("component_id"),
                        "protected": bool(feature.get("protected")),
                    }
                    for feature in design_plan.get("features", [])
                    if isinstance(feature, dict) and feature.get("id")
                ],
                "required_outputs": [
                    {
                        "id": output.get("id") or output.get("output_id"),
                        "component_ids": output.get("component_ids", []),
                        "required": output.get("required", True),
                    }
                    for output in printable_outputs
                    if isinstance(output, dict)
                ],
                "required_parameters": [
                    {
                        "id": parameter.get("id"),
                        "value": parameter.get("value"),
                        "unit": parameter.get("unit"),
                        "type": parameter.get("type") or parameter.get("parameter_type"),
                        "protected": bool(parameter.get("protected")),
                        "source_requirement_id": parameter.get("source_requirement_id"),
                        "source": parameter.get("source"),
                    }
                    for parameter in design_plan.get("parameters", [])
                    if isinstance(parameter, dict) and parameter.get("id")
                ],
            }
            topology_expectations = [
                {
                    "output_id": output.get("id") or output.get("output_id"),
                    "component_id": output.get("component_id"),
                    "component_ids": output.get("component_ids", []),
                    "expected_solid_count": output.get("expected_solid_count", 1),
                    "allow_disconnected_solids": output.get(
                        "allow_disconnected_solids",
                        False,
                    ),
                    "required": output.get("required", True),
                }
                for output in printable_outputs
                if isinstance(output, dict)
            ]
            parts.extend(
                [
                    "Initial generation mode:",
                    "- Generate from the approved staged product definition, not from the raw user prompt alone.",
                    "- Return the complete Python source for the whole product; do not return snippets, patches, prose, JSON, other CAD languages, or helper-only fragments.",
                    "- Implement every planned component, feature, dependency, parameter, and printable output unless the plan explicitly marks it optional.",
                    "- Preserve protected requirement values and topology expectations exactly.",
                    "- Use exact stable product IDs from the identity table for @component, @feature, ParameterSpec.id, and PrintableOutput.output_id.",
                    "- Python function names may differ from stable product IDs, but decorators and PrintableOutput metadata must bind the exact stable IDs.",
                    "- Do not invent replacement product IDs or fuzzy aliases such as base_body for planned output base.",
                    "",
                    "Authoritative Design Specification JSON:",
                    json.dumps(design_specification, indent=2, sort_keys=True),
                    "",
                    "Authoritative Design Plan JSON:",
                    json.dumps(design_plan, indent=2, sort_keys=True),
                    "",
                    "Required stable identity table:",
                    json.dumps(identity_table, indent=2, sort_keys=True),
                    "",
                    "Typed parameter contract:",
                    json.dumps(design_plan.get("parameters", []), indent=2, sort_keys=True),
                    "",
                    "Printer/profile requirements:",
                    json.dumps(
                        design_specification.get("print_requirements", {}),
                        indent=2,
                        sort_keys=True,
                    ),
                    "",
                    "Topology expectations:",
                    json.dumps(topology_expectations, indent=2, sort_keys=True),
                    "",
                    "Security restrictions:",
                    "- The source must satisfy cadquery-v1 AST validation and use only the allowed imports, runtime constructors, and safe CadQuery operations listed above.",
                    "- Do not access files, network, subprocesses, environment variables, local modules, shell commands, or dynamic Python execution.",
                    "",
                    format_authoritative_identity_section(request.source_authority),
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

    def build_scaffold_geometry_prompt(self, request: ModelGenerationRequest) -> str:
        plan = request.design_plan or {}
        inventory = build_geometry_function_inventory(plan)
        expected_functions = inventory["expected_function_ids"]
        parameter_ids = inventory["allowed_parameters"]
        lines = [
            "You generate only structured CadQuery geometry bodies for Volundr.",
            "Return JSON only, optionally inside one json code fence. Do not include prose outside JSON.",
            f"Use schema_version exactly {GEOMETRY_BODIES_SCHEMA_VERSION}.",
            "Return ordered statements and exactly one result_symbol for each function; never return def declarations, decorators, imports, return statements, fences, or prose inside a body.",
            "Volundr deterministically owns all parameters, components, features, outputs, IDs, and the build entrypoint.",
            "Use CadQuery as `cq` and the canonical parameter IDs exactly as provided.",
            "Implement every required function_id exactly once. Do not rename, omit, or add functions.",
            "Assign the component shape or modified feature shape to result_symbol. Volundr appends the sole return statement deterministically.",
            "Do not add file, network, subprocess, or dynamic Python access.",
            "Canonical parameter IDs: " + ", ".join(parameter_ids),
            "Required function authority inventory:",
            json.dumps(inventory["functions"], indent=2, sort_keys=True),
            "",
            "Binding per-function parameter-effect contract:",
            "Every required direct parameter must reach the stated geometry effect directly or through one of its approved derived parameters.",
            "A parameter reference used only in an assignment, comment, or unrelated helper does not satisfy the contract.",
            "For pattern_count, do not use a fixed range, fixed point list, repeated literal geometry calls, or a two-point list when the approved count is two.",
            "For pattern_spacing, do not replace the approved spacing with fixed point coordinates.",
            "For every required pattern, Volundr supplies the canonical point parameter in params. Use that exact point parameter in pushPoints; never rebuild, replace, reorder, slice, truncate, or offset the point array, and never call a pattern helper from a geometry body.",
            "For dimension and radius_or_diameter, do not replace an approved parameter or derived value with a matching numeric literal.",
            "When static proof is unclear, use the required parameter or approved derived value in the geometry operation explicitly; unverifiable critical effects block assembly.",
            "Per-function obligations:",
            *[
                "- {function_id}: direct={direct}; derived={derived}; effects={effects}".format(
                    function_id=function.get("function_id"),
                    direct=function.get("required_direct_parameters", []),
                    derived=function.get("allowed_derived_parameters", []),
                    effects=function.get("required_parameter_effects", []),
                )
                for function in inventory["functions"]
            ],
            "Canonical repeated-pattern authority:",
            json.dumps(inventory["parameter_effect_contract"].get("patterns", []), indent=2, sort_keys=True),
            json.dumps(inventory["parameter_effect_contract"], indent=2, sort_keys=True),
            "",
            "Required response shape:",
            json.dumps(
                {
                    "schema_version": GEOMETRY_BODIES_SCHEMA_VERSION,
                    "functions": [
                        {"function_id": function_id, "statements": ["body = ..."], "result_symbol": "body"}
                        for function_id in expected_functions
                    ],
                },
                indent=2,
            ),
        ]
        if request.geometry_body_diagnostics:
            lines.extend(
                [
                    "",
                    f"Repair mode: {CADQUERY_GEOMETRY_BODY_REPAIR_PROMPT_VERSION}",
                    "Repair only the structured geometry-body response using the diagnostics below.",
                    "Do not change scaffold-owned parameters, IDs, function signatures, or the Design Plan.",
                    "Rejected response diagnostics:",
                    request.geometry_body_diagnostics,
                    "Rejected structured response:",
                    request.current_source or "",
                ]
            )
        if request.contract_diagnostics:
            lines.extend(["", "Repair diagnostics:", request.contract_diagnostics])
        if request.compiler_diagnostics:
            lines.extend(["", "Execution diagnostics:", request.compiler_diagnostics])
        if request.current_source:
            lines.extend(["", "Current scaffold source for geometry context:", request.current_source])
        lines.extend(
            [
                "",
                "Design Specification:",
                json.dumps(request.design_specification or {}, indent=2, sort_keys=True),
                "",
                "Design Plan:",
                json.dumps(plan, indent=2, sort_keys=True),
                "",
                "User instruction:",
                request.user_instruction,
            ]
        )
        return "\n".join(lines)

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
                "Preserve direct user requirements exactly; represent implementation dimensions as derived_formula or standard_lookup values instead of changing the user value.",
                "Never use one parameter ID for both a nominal designation and a geometric dimension. Split mounting_screw_designation from mounting_hole_diameter.",
                "Use only the supplied versioned standard mappings and include the lookup key, variant, and result_field when a variant exposes more than one measurement.",
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
                "Every parameter must include provenance.relationship: direct, derived_formula, calculated, standard_lookup, product_default, printer_default, ai_proposal, or user_override.",
                "A parameter with source_requirement_id must copy that source requirement's value and unit only when its provenance relationship is direct. Derived implementation dimensions must not be marked direct.",
                "Use derived_parameters or derived_formula provenance for calculated stack, envelope, or overall product dimensions, not direct source-linked values.",
                "Use derived_formula for deterministic formulas and include source_requirement_ids, source_parameter_ids, and the arithmetic expression. The expression may be on the derived parameter or duplicated in provenance. Use standard_lookup for nominal hardware designations and include table_id, key, variant, and result_field when needed; never treat a designation as a metric dimension.",
                "Do not use one parameter ID for both a nominal designation and a geometric dimension. Keep a screw designation such as #8 separate from a proposed clearance-hole diameter.",
                "Every dependency edge must connect existing parameter or derived_parameter IDs in the plan. If an edge target such as case_inner_height_mm is needed, include that target in derived_parameters with its expression and depends_on list.",
                "Do not use dependency_edges for component or feature IDs; feature dependencies belong in each feature's parameters list.",
                "For repeated functional features, emit a generic patterns entry owned by the feature and component. Volundr computes canonical points from its count and spacing/radius parameters; do not put pattern arithmetic in geometry bodies.",
                "For a repeated linear mounting arrangement, use the explicit or proposed count and spacing, set centered=true, and distinguish the arrangement axis from the wall-normal hole-cutting axis.",
                "Ask plan clarification only when component structure, printable outputs, assembly strategy, or configuration dependencies cannot be chosen safely.",
                "For any physical product with mounting, containment, support, retention, or removal requirements, emit schema_version 1.1 and an explicit functional_contract.",
                "Resolve mounting plane, plane normal, hole axis, arrangement axis, support-floor decision, removal direction, and retention strategy. Never return unresolved alternatives such as 'or' choices.",
                "Choose exactly one supported retention strategy when the functional context supports a reasonable proposal. Use one of flexible_snap_arm, retaining_lip, spring_clip, removable_strap, rotating_gate, latch, or friction_band. Do not use reviewed_proposal, unspecified, generic_retention, choose_later, or some_clip as a strategy.",
                "For moving-vehicle containment with one-handed release, prefer a flexible_snap_arm proposal unless the Design Specification states a material, durability, or architecture constraint that makes it unsuitable. Include a stable feature_id, owning component, retained object relationship, retention direction, release behavior, removal direction, editable proposed parameters, and verification metadata.",
                "Use Volundr proposals for ordinary defaults; do not ask the user for routine wall thickness, clearance, or fillet values.",
            ]
        schema = {
            "schema_version": "1.1",
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
                    "provenance": {
                        "relationship": "direct|derived_formula|calculated|standard_lookup|product_default|printer_default|ai_proposal|user_override",
                        "source_requirement_ids": ["string"],
                        "source_parameter_ids": ["string"],
                        "expression": "string|null",
                        "lookup": {"table_id": "string", "key": "string", "variant": "string", "result_field": "string|null"},
                        "explanation": "string",
                    },
                    "editable": True,
                    "protected": False,
                    "component_id": "string|null",
                }
            ],
                "derived_parameters": [
                    {
                        "id": "string",
                        "label": "string",
                        "expression": "string|null",
                        "unit": "mm",
                        "depends_on": ["parameter_id"],
                        "provenance": {
                            "relationship": "derived_formula|calculated|standard_lookup",
                            "source_requirement_ids": ["string"],
                            "source_parameter_ids": ["string"],
                            "lookup": {"table_id": "string", "key": "string", "variant": "string", "result_field": "string|null"},
                            "explanation": "string",
                        },
                    }
                ],
                "patterns": [
                    {
                        "pattern_id": "stable_pattern_id",
                        "owning_feature_id": "feature_id",
                        "owning_component_id": "component_id",
                        "pattern_type": "linear|rectangular|circular",
                        "point_parameter_id": "feature_points",
                        "count_parameter_id": "count_parameter_id|null",
                        "spacing_parameter_id": "spacing_parameter_id|null",
                        "axis": "X|Y|Z|null",
                        "plane": "XY|XZ|YZ|null",
                        "centered": True,
                        "origin": [0, 0, 0],
                        "unit": "mm"
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
            "functional_contract": {
                "coordinate_frames": [{"id": "primary_product_frame", "axes": {"x": "horizontal", "y": "normal", "z": "vertical"}}],
                "mounting_interfaces": [{"id": "string", "type": "planar_mount", "component_id": "component_id", "mounting_plane": "XZ", "normal_axis": "Y", "fastener_count": 2, "fastener_type": "string", "hole_axis": "Y", "arrangement_axis": "Z", "hole_style": "clearance", "spacing": {"value": 0, "unit": "mm", "source": "volundr_proposal"}}],
                "support_interfaces": [{"id": "string", "type": "contained_object_support", "component_id": "component_id", "object_requirement_id": "parameter_id", "primary_axis": "Z", "bottom_support_required": True, "minimum_floor_thickness": {"value": 0, "unit": "mm", "source": "volundr_proposal"}, "removal_direction": "+Z"}],
                "retention_interfaces": [{"id": "string", "type": "retention", "required": True, "environment": "string", "release_behavior": "one_handed_pull", "strategy": "flexible_snap_arm", "component_id": "component_id", "feature_id": "retention_feature", "retained_object_requirement_id": "parameter_id", "retention_direction": "string", "removal_direction": "+Z", "parameters": [{"id": "retention_overlap", "value": 2.0, "unit": "mm", "source": "volundr_proposal", "editable": True}], "verification": {"feature_geometry_required": True, "parameter_effect_required": True, "human_review_required": True}}],
            },
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
                "Available standard mappings:",
                json.dumps(FASTENER_LOOKUP_TABLES, indent=2, sort_keys=True),
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
            "schema_version": "revision-plan-v2",
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
                {"type": "mounting_hole_axis|mounting_hole_count|mounting_hole_diameter|mounting_hole_spacing|support_floor_present|minimum_floor_thickness|required_feature_geometry_present|parameter_geometry_effect|output_exists|solid_count|bounds_preserved", "target_id": "output_or_parameter_id", "expected_value": 0}
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
                "Preserve nominal hardware designations as strings, including the # prefix. A designation such as #8 is not an 8 mm dimension; use a semantic ID such as mounting_screw_designation and leave hole diameter to a later standard lookup proposal.",
                "When the request says wall-mounted, wall-mounted means a vertical planar wall mount unless the user states otherwise; propose ordinary screw spacing and orientation rather than asking for them.",
                "When a moving-vehicle request requires secure retention and one-handed removal, do not ask the user to choose an implementation mechanism when a supported concrete proposal is reasonable; let the Design Plan propose one.",
                "do not ask the user to convert a nominal designation such as #8 into a metric diameter.",
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
