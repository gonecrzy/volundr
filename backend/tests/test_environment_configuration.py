import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _active_env_names(path: Path) -> set[str]:
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        names.add(stripped.split("=", 1)[0])
    return names


def test_normal_environment_example_has_only_deployment_decisions() -> None:
    assert _active_env_names(REPOSITORY_ROOT / ".env.example") == {
        "VOLUNDR_WEB_PORT",
        "VOLUNDR_API_PORT",
        "VOLUNDR_DATA_DIR",
        "VOLUNDR_AI_PROVIDER",
        "GEMINI_API_KEY",
        "VOLUNDR_GEMINI_MODEL",
    }


def test_removed_rollout_flags_are_absent_from_production_configuration() -> None:
    backend_configuration_files = (
        REPOSITORY_ROOT / "backend/app/core/config.py",
        REPOSITORY_ROOT / "docker-compose.yml",
    )
    removed_backend_names = (
        "VOLUNDR_GENERATION_MODE",
        "VOLUNDR_ENABLE_DESIGN_PLANS",
        "VOLUNDR_ENABLE_MULTI_OUTPUT",
        "VOLUNDR_ENABLE_STRUCTURED_REVISIONS",
        "VOLUNDR_CHAT_FIRST",
    )

    for path in backend_configuration_files:
        content = path.read_text(encoding="utf-8")
        assert not any(
            re.search(rf"(?<![A-Z0-9_]){name}(?![A-Z0-9_])", content)
            for name in removed_backend_names
        ), path

    for path in (REPOSITORY_ROOT / "frontend/Dockerfile", REPOSITORY_ROOT / "frontend/src/main.tsx"):
        content = path.read_text(encoding="utf-8")
        assert "VITE_VOLUNDR_GENERATION_MODE" not in content


def test_frontend_environment_example_cannot_contain_provider_secrets() -> None:
    frontend_example = (REPOSITORY_ROOT / "frontend/.env.example").read_text(encoding="utf-8")

    assert "GEMINI_API_KEY" not in frontend_example
    assert "VOLUNDR_GEMINI" not in frontend_example
