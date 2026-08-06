# Executable CadQuery Complete-Source v2
> **Execution mode:** Inline Execution

**Goal:** Correct only the experimental Gemini transport so the golden path exchanges one complete raw Python module, fairly exercises source-level L0 repair, and preserves the existing executor, validator, semantic checks, revision flow, and frontend.

**Root cause:** v1 requested and parsed a JSON envelope. The live failure therefore occurred before source extraction, and the L0 request did not contain the exact failed provider response or its normalized error.

**Design:** `contract.py` extracts either raw Python or exactly one fenced Python block, rejects prose/multiple blocks/empty responses, runs an explicit syntax check, then delegates source safety and output identity to the existing `cadquery-v1` validator. The frozen contract supplies the sole expected output ID. `repair.py` carries the exact prior response and normalized error in L0 facts while redacting only public diagnostic channels. `workflow.py` writes the exact provider response to a private mode-0600 ignored runtime evidence file and records only safe metadata in provenance. No source rewriting, patching, reconstruction, or executor changes are allowed.

### Task 1: RED contract/parser tests
**Files:** `backend/tests/test_executable_cadquery_contract.py`

Add failing tests for raw Python, one fenced Python block, prose-plus-code rejection, multiple-block rejection, empty/extraction failure, syntax failure, source-contract violation, output identity mismatch, and source preservation.

**Verification:** targeted contract tests fail for the missing v2 behavior, not due to test setup.

### Task 2: RED repair/evidence tests
**Files:** `backend/tests/test_executable_cadquery_repair.py`, `backend/tests/test_executable_cadquery_workflow.py`

Add failing tests proving L0 receives the exact prior response and normalized error, protected runtime evidence is mode 0600 and write-once, and public repair facts redact credential/path material.

**Verification:** targeted repair/workflow tests fail before implementation.

### Task 3: Minimal v2 transport implementation
**Files:** `backend/app/services/executable_cadquery/contract.py`, `backend/app/services/executable_cadquery/repair.py`, `backend/app/services/ai/gemini_cli.py`, `backend/app/services/executable_cadquery/workflow.py`

Implement v2 extraction/error classes, raw-source prompt, exact prior-response/error repair fields, and protected ignored runtime evidence. Keep execution and downstream result handling unchanged.

**Verification:** contract, repair, workflow, routing, fixture, and redaction tests pass.

### Task 4: Update offline providers and assertions
**Files:** `backend/app/testing/e2e_fixture_server.py`, `backend/tests/test_executable_cadquery_workflow.py`, `backend/tests/test_executable_cadquery_routing.py`, `frontend/e2e/live/executable-cadquery-gemini.live.spec.ts`

Return raw source from offline providers, assert the v2 prompt and exact L0 fields, and make live evidence report source extraction/repair boundaries without changing the frozen fixture or live operation count.

**Verification:** targeted backend suite, frontend build/unit/offline browser suite, and redaction scans.

### Task 5: Transport correction commit and push
Commit the verified transport correction before any live call and push only `experiment/gemini-executable-cadquery-v1`.

**Verification:** clean branch, remote SHA match, main unchanged, no migration changes.

### Task 6: One controlled live creation
Run the exact frozen mounting-bracket creation once with the existing credential order and repair ladder. Do not start a second creation or alter the fixture. Record one permitted final decision; only classify provider nonviability after extraction and L0 source-level repair have actually been attempted.

**Verification:** inspect protected runtime evidence, source/worker/topology/semantic/artifact evidence, and final decision before final branch audit.
