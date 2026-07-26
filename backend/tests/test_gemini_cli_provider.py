import asyncio
import os
import signal
from pathlib import Path

import pytest

from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.provider import RequirementExtractionRequest


def _write_sleeping_cli(path: Path, pidfile: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                "sleep 30 &",
                f"echo \"$$ $!\" > {pidfile}",
                "wait $!",
            ]
        ),
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_diagnostic_sleeping_cli(path: Path, pidfile: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                "echo 'Attempt 1 failed with status 429. Retrying with backoff...' >&2",
                "echo 'RESOURCE_EXHAUSTED quota exceeded' >&2",
                "sleep 30 &",
                f"echo \"$$ $!\" > {pidfile}",
                "wait $!",
            ]
        ),
        encoding="utf-8",
    )
    path.chmod(0o755)


def _requirement_request() -> RequirementExtractionRequest:
    return RequirementExtractionRequest(
        project_name="Draft",
        original_intent="Create a bracket.",
        user_instruction="Create a bracket.",
    )


async def _wait_for_pidfile(pidfile: Path) -> tuple[int, int]:
    for _ in range(100):
        if pidfile.exists():
            parent_pid, child_pid = pidfile.read_text(encoding="utf-8").strip().split()
            return int(parent_pid), int(child_pid)
        await asyncio.sleep(0.01)
    raise AssertionError("fake Gemini CLI did not start")


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _kill_if_alive(*pids: int) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


@pytest.mark.asyncio
async def test_gemini_cli_timeout_kills_process_group(tmp_path: Path) -> None:
    pidfile = tmp_path / "pidfile"
    binary = tmp_path / "fake-gemini"
    _write_sleeping_cli(binary, pidfile)
    provider = GeminiCliProvider(binary=str(binary), model=None, timeout_seconds=0.1)

    parent_pid = child_pid = None
    try:
        with pytest.raises(RuntimeError, match="timed out"):
            await provider.extract_requirements(_requirement_request())
        parent_pid, child_pid = await _wait_for_pidfile(pidfile)
        await asyncio.sleep(0.05)
        assert not _process_exists(parent_pid)
        assert not _process_exists(child_pid)
    finally:
        _kill_if_alive(*(pid for pid in (parent_pid, child_pid) if pid is not None))


@pytest.mark.asyncio
async def test_gemini_cli_timeout_preserves_stderr_tail(tmp_path: Path) -> None:
    pidfile = tmp_path / "pidfile"
    binary = tmp_path / "fake-gemini"
    _write_diagnostic_sleeping_cli(binary, pidfile)
    provider = GeminiCliProvider(binary=str(binary), model=None, timeout_seconds=0.1)

    parent_pid = child_pid = None
    try:
        with pytest.raises(RuntimeError) as excinfo:
            await provider.extract_requirements(_requirement_request())
        message = str(excinfo.value)
        assert "timed out" in message
        assert "RESOURCE_EXHAUSTED quota exceeded" in message
        parent_pid, child_pid = await _wait_for_pidfile(pidfile)
    finally:
        _kill_if_alive(*(pid for pid in (parent_pid, child_pid) if pid is not None))


@pytest.mark.asyncio
async def test_gemini_cli_cancellation_kills_process_group(tmp_path: Path) -> None:
    pidfile = tmp_path / "pidfile"
    binary = tmp_path / "fake-gemini"
    _write_sleeping_cli(binary, pidfile)
    provider = GeminiCliProvider(binary=str(binary), model=None, timeout_seconds=30)

    task = asyncio.create_task(provider.extract_requirements(_requirement_request()))
    parent_pid = child_pid = None
    try:
        parent_pid, child_pid = await _wait_for_pidfile(pidfile)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.05)
        assert not _process_exists(parent_pid)
        assert not _process_exists(child_pid)
    finally:
        _kill_if_alive(*(pid for pid in (parent_pid, child_pid) if pid is not None))


def test_gemini_cli_command_uses_no_tool_policy() -> None:
    provider = GeminiCliProvider(binary="gemini", model="gemini-3.5-flash-lite")

    command = provider.build_command("prompt")

    assert "--policy" in command
    assert command[command.index("--policy") + 1].endswith("gemini_no_tools_policy.toml")


def test_gemini_cli_provider_settings_include_policy_path() -> None:
    provider = GeminiCliProvider(
        binary="gemini",
        model="gemini-3.5-flash-lite",
        policy_path="/tmp/volundr-no-tools.toml",
    )

    settings = provider.provider_settings()

    assert settings["policy_path"] == "/tmp/volundr-no-tools.toml"


def test_gemini_cli_provider_settings_report_auth_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "secret-value")
    provider = GeminiCliProvider(binary="gemini", model="gemini-3.5-flash-lite")

    assert provider.provider_settings()["auth_mode"] == "api_key"

    monkeypatch.delenv("GEMINI_API_KEY")
    assert provider.provider_settings()["auth_mode"] == "gemini_profile"


def test_requirement_prompt_forbids_external_tools() -> None:
    provider = GeminiCliProvider(binary="gemini", model="gemini-3.5-flash-lite")

    prompt = provider.build_requirement_prompt(_requirement_request())

    assert "Do not use tools, web search, files, or external resources" in prompt
