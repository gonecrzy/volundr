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
