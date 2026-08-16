#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
CLI="$SCRIPT_DIR/bin/esp32-agent"

if [ -f "$(pwd)/agentic/esp_target_config.json" ]; then
    exec env ESP32_AGENT_REPO_DIR="$SCRIPT_DIR" "$CLI" start
fi

printf '%s\n' "[esp32-agent] 'esp-agent.sh' is deprecated; using 'esp32-agent init'." >&2
exec env ESP32_AGENT_REPO_DIR="$SCRIPT_DIR" "$CLI" init "$@"
