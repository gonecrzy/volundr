import asyncio
import contextlib
import json
import os
import signal
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
)

GEMINI_RULESET_VERSION = "gemini-ruleset-v1"
REQUIREMENTS_PROMPT_VERSION = "requirements-v1"
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


class GeminiCliProvider:
    def __init__(
        self,
        *,
        binary: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.binary = binary or settings.gemini_binary
        self.model = model or settings.gemini_model
        self.timeout_seconds = timeout_seconds or settings.gemini_timeout_seconds

    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        prompt = self.build_prompt(request)
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
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            await self._terminate_process_group(process)
            raise RuntimeError(f"Gemini CLI timed out after {self.timeout_seconds} seconds") from exc
        except asyncio.CancelledError:
            self._kill_process_group(process)
            raise

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
            await asyncio.wait_for(process.communicate(), timeout=5)
        except TimeoutError:
            self._kill_process_group(process)
            with contextlib.suppress(Exception):
                await process.communicate()

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
        return command

    @property
    def gemini_ruleset_version(self) -> str:
        return GEMINI_RULESET_VERSION

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
        }

    def build_prompt(self, request: ModelGenerationRequest) -> str:
        return self._build_prompt(request)

    def build_requirement_prompt(self, request: RequirementExtractionRequest) -> str:
        return self._build_requirement_prompt(request)

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
            "- Units are millimeters.",
            "- Include a USER PARAMETERS section.",
            "- Define module main_model().",
            "- End with exactly one top-level main_model(); call.",
            "- Do not use import(), surface(), include/use paths, host file access, STL, binary data, or base64.",
            "- Prefer practical FDM-printable functional geometry.",
            "- For initial builds, stay literal and simple before adding secondary features.",
            "- Do not add decorative cutouts, lightening holes, pass-through holes, vents, windows, slots, or pockets unless the user explicitly asks for them or they are structurally necessary.",
            "- Every subtraction must directly serve the user's requested function; avoid subtractive features that weaken the part or remove support surfaces.",
            "- Preserve load-bearing walls, tray support surfaces, retention features, and handles unless the user asks to change them.",
            "- If a grip, access notch, drain, fastener hole, or clearance cut is needed, keep it local and sized for that purpose instead of cutting through unrelated geometry.",
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
                [
                    "",
                    "Current accepted OpenSCAD source. Preserve working geometry and make the smallest necessary change:",
                    request.current_source,
                ]
            )
        if request.compiler_diagnostics:
            parts.extend(["", "Compiler diagnostics to account for:", request.compiler_diagnostics])
        return "\n".join(parts)

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
                "Every protected requirement must use // @volundr-requirement <design_spec_requirement_id> immediately before its parameter assignment.",
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
                "Use this same selected-output contract for single-output plans.",
                "Do not require source-file edits between component compiles; Volundr will compile each output with a command-line selected_output override.",
                "Keep the model in millimeters, near the XY origin, and at or above Z=0.",
                "Do not use import(), surface(), include/use paths, host file access, STL, binary data, or base64.",
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
                    "to": "dependent_parameter_or_feature_id",
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
        return "\n".join(
            [
                "Repair OpenSCAD source so it satisfies Volundr source-contract validation.",
                "Return only a single fenced openscad block. Do not include prose outside the block.",
                "This is contract repair, not design revision.",
                "Preserve geometry, all user dimensions, protected Design Specification values, required features, unrelated modules, and working Boolean structure.",
                "Only fix the listed contract violations, marker omissions, section omissions, prohibited constructs, or verifiability issues.",
                "Do not change protected parameter values unless the diagnostics explicitly say the current value is wrong and the Design Specification value is provided.",
                "Do not use import(), surface(), include/use paths, host file access, STL, binary data, or base64.",
                "Ensure protected dimensions use // @volundr-requirement <id> immediately before the parameter assignment.",
                "Ensure protected features use // @volundr-feature <id> immediately before the implementing module or statement.",
                "Preserve and repair // @volundr-geometry markers for bounds, hole groups, holes, and wall thickness when those features exist.",
                "Do not add geometry markers that claim a feature or dimension the source does not implement.",
                "Ensure module main_model() exists and the file ends with exactly one top-level main_model(); call.",
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
