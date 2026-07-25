import asyncio
import json
from typing import Any

from app.core.config import settings
from app.services.ai.provider import (
    ModelGenerationRequest,
    ModelGenerationResult,
    RequirementExtractionRequest,
    RequirementExtractionResult,
)

GEMINI_RULESET_VERSION = "gemini-ruleset-v1"
REQUIREMENTS_PROMPT_VERSION = "requirements-v1"
OPENSCAD_GENERATION_PROMPT_VERSION = "openscad-generation-v3"
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
        command = self.build_command(prompt)

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise RuntimeError(f"Gemini CLI timed out after {self.timeout_seconds} seconds") from exc

        if process.returncode != 0:
            diagnostic = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(diagnostic or "Gemini CLI failed")

        return ModelGenerationResult(
            raw_output=stdout.decode("utf-8", errors="replace"),
            provider="gemini_cli",
            provider_model=self.model,
        )

    async def extract_requirements(
        self,
        request: RequirementExtractionRequest,
    ) -> RequirementExtractionResult:
        prompt = self.build_requirement_prompt(request)
        command = self.build_command(prompt)

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise RuntimeError(f"Gemini CLI timed out after {self.timeout_seconds} seconds") from exc

        if process.returncode != 0:
            diagnostic = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(diagnostic or "Gemini CLI failed")

        return RequirementExtractionResult(
            raw_output=stdout.decode("utf-8", errors="replace"),
            provider="gemini_cli",
            provider_model=self.model,
        )

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
        if request.compiler_diagnostics:
            return LEGACY_COMPILE_REPAIR_PROMPT_VERSION
        if request.current_source:
            return LEGACY_REVISION_PROMPT_VERSION
        if request.design_specification:
            return OPENSCAD_GENERATION_PROMPT_VERSION
        return LEGACY_INITIAL_PROMPT_VERSION

    def requirement_prompt_template_version(self) -> str:
        return REQUIREMENTS_PROMPT_VERSION

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

    def _build_prompt(self, request: ModelGenerationRequest) -> str:
        if request.contract_diagnostics:
            return self._build_contract_repair_prompt(request)
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
