#!/usr/bin/env bash

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
printf '%s\n' "[esp32-agent] 'scripts/setup.sh' is deprecated; using 'esp32-agent init'." >&2
exec env ESP32_AGENT_REPO_DIR="$REPO_DIR" "$REPO_DIR/bin/esp32-agent" init "$@"
