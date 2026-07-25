import asyncio
from typing import Any

from app.core.config import settings
from app.services.ai.provider import ModelGenerationRequest, ModelGenerationResult

GEMINI_RULESET_VERSION = "gemini-ruleset-v1"
LEGACY_INITIAL_PROMPT_VERSION = "legacy-initial-v1"
LEGACY_REVISION_PROMPT_VERSION = "legacy-revision-v1"
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

    def build_command(self, prompt: str) -> list[str]:
        command = [self.binary, "-p", prompt, "--output-format", "text", "--skip-trust"]
        if self.model:
            command.extend(["--model", self.model])
        return command

    @property
    def gemini_ruleset_version(self) -> str:
        return GEMINI_RULESET_VERSION

    def prompt_template_version_for(self, request: ModelGenerationRequest) -> str:
        if request.compiler_diagnostics:
            return LEGACY_COMPILE_REPAIR_PROMPT_VERSION
        if request.current_source:
            return LEGACY_REVISION_PROMPT_VERSION
        return LEGACY_INITIAL_PROMPT_VERSION

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

    def _build_prompt(self, request: ModelGenerationRequest) -> str:
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
