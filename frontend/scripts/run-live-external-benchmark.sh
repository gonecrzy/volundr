#!/usr/bin/env bash
set -euo pipefail

# External benchmark runs must exercise the production requirement path.
# Frozen corpus contract injection remains available to its dedicated
# repeatability harness, but is never inherited by this benchmark runner.
unset VOLUNDR_EXECUTABLE_CADQUERY_CORPUS_MANIFEST_PATH

script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$script_root/run-live-e2e.sh" "$@"
