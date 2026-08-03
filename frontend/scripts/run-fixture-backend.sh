#!/usr/bin/env bash
set -euo pipefail

fixture_root="${VOLUNDR_E2E_DATA_DIR:-$(mktemp -d /tmp/volundr-playwright-fixture.XXXXXX)}"
cleanup_fixture="false"
if [[ -z "${VOLUNDR_E2E_DATA_DIR:-}" ]]; then
  cleanup_fixture="true"
fi

exec env \
  PYTHONPATH=../backend \
  VOLUNDR_E2E_DATA_DIR="$fixture_root" \
  VOLUNDR_E2E_CLEANUP="$cleanup_fixture" \
  VOLUNDR_DEVELOPER_TOOLS_ENABLED="true" \
  VOLUNDR_E2E_PORT="${VOLUNDR_E2E_PORT:?VOLUNDR_E2E_PORT is required}" \
  ../backend/.venv/bin/python -m app.testing.e2e_fixture_server
