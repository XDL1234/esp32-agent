#!/bin/bash
#
# esp-session-start.sh — 启动 OpenOCD，用于 agentic 固件开发。
#
# 在启动 AI 助手前运行。从 esp_target_config.json 读取配置。
# 不依赖固件已编译。RTT 日志和 apptrace 在需要时单独启动。
#
# 用法：
#   ./agentic/esp-session-start.sh
#   ./agentic/esp-session-start.sh --config path/to/esp_target_config.json
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="$SCRIPT_DIR/.esp-agent"
CONFIG="$SCRIPT_DIR/esp_target_config.json"

[[ "$1" == "--config" ]] && CONFIG="$2"

# ── Helpers ─────────────────────────────────────────

die()  { echo "[session] ERROR: $*" >&2; exit 1; }
info() { echo "[session] $*"; }

[ -f "$CONFIG" ] || die "Config not found: $CONFIG"

# ── Platform detection ──────────────────────────────
# Step 1: detect platform via uname (fast, no dependencies)
# Step 2: override with config field if present

case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) PLATFORM="windows" ;;
    Darwin*)              PLATFORM="macos" ;;
    *)                    PLATFORM="linux" ;;
esac

# ── Set Python based on detected platform ───────────

if [ "$PLATFORM" = "windows" ]; then
    if [ -n "$IDF_PYTHON_ENV_PATH" ] && [ -f "$IDF_PYTHON_ENV_PATH/Scripts/python.exe" ]; then
        PYTHON="$IDF_PYTHON_ENV_PATH/Scripts/python.exe"
    else
        PYTHON="python3"
        command -v "$PYTHON" >/dev/null 2>&1 || PYTHON="python"
    fi
else
    PYTHON="python3"
fi

# ── Read config (now that we have a working Python) ─

read_cfg() {
    "$PYTHON" -c "
import json, sys
d = json.load(open(sys.argv[1]))
print(eval(sys.argv[2]))
" "$CONFIG" "$1"
}

# Override platform from config if explicitly set
CFG_PLATFORM=$(read_cfg "d.get('platform', '')" 2>/dev/null || true)
if [ -n "$CFG_PLATFORM" ]; then
    PLATFORM="$CFG_PLATFORM"
    # Re-set Python if config says windows but uname didn't detect it (unlikely but safe)
    if [ "$PLATFORM" = "windows" ] && [ -n "$IDF_PYTHON_ENV_PATH" ] && [ -f "$IDF_PYTHON_ENV_PATH/Scripts/python.exe" ]; then
        PYTHON="$IDF_PYTHON_ENV_PATH/Scripts/python.exe"
    elif [ "$PLATFORM" != "windows" ]; then
        PYTHON="python3"
    fi
fi

# ── Read config fields ──────────────────────────────

BOARD_CFG=$(read_cfg "d['openocd']['board_cfg']")
TCL_PORT=$(read_cfg "d['openocd'].get('tcl_port', 6666)")

# Validate TCL_PORT is numeric
if ! [[ "$TCL_PORT" =~ ^[0-9]+$ ]]; then
    die "Invalid tcl_port in config: $TCL_PORT"
fi

info "Config:       $CONFIG"
info "Platform:     $PLATFORM"
info "Board config: $BOARD_CFG"
info "Tcl port:     $TCL_PORT"

# ── Stop only this project's stale process ──────────

if [ -f "$STATE_DIR/openocd.pid" ]; then
    OLD_PID=$(cat "$STATE_DIR/openocd.pid" 2>/dev/null || true)
    if [[ "$OLD_PID" =~ ^[0-9]+$ ]]; then
        if [ "$PLATFORM" = "windows" ]; then
            powershell -NoProfile -Command \
                "\$p = Get-Process -Id $OLD_PID -ErrorAction SilentlyContinue; if (\$p -and \$p.ProcessName -like 'openocd*') { Stop-Process -Id $OLD_PID -Force }" \
                2>/dev/null || true
        elif ps -p "$OLD_PID" -o comm= 2>/dev/null | grep -qi openocd; then
            kill "$OLD_PID" 2>/dev/null || true
        fi
    fi
    rm -f "$STATE_DIR/openocd.pid"
    sleep 1
fi

# ── Create state directory ──────────────────────────

mkdir -p "$STATE_DIR"

# ── Start OpenOCD ───────────────────────────────────

info "Starting OpenOCD..."
if [ "$PLATFORM" = "windows" ]; then
    # Use Python DETACHED_PROCESS for a fully independent process.
    # This is more reliable than PowerShell Start-Process, which can hang
    # on file-handle redirection, and than 'cmd start /B', which has
    # path-quoting issues through Git Bash.
    "$PYTHON" -c "
import subprocess, sys
with open(sys.argv[2], 'w') as logf:
    p = subprocess.Popen(
        ['openocd', '-f', sys.argv[1]],
        stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
print(p.pid)
" "$BOARD_CFG" "$STATE_DIR/openocd.log" > "$STATE_DIR/openocd.pid"
else
    nohup openocd -f "$BOARD_CFG" > "$STATE_DIR/openocd.log" 2>&1 &
    echo $! > "$STATE_DIR/openocd.pid"
    disown 2>/dev/null || true
fi

# ── Wait for OpenOCD Tcl port ───────────────────────

info "Waiting for OpenOCD..."
TRIES=0
if [ "$PLATFORM" = "windows" ]; then
    while ! "$PYTHON" -c "
import socket, sys
s = socket.create_connection(('localhost', int(sys.argv[1])), 1)
s.close()
" "$TCL_PORT" 2>/dev/null; do
        sleep 0.5
        TRIES=$((TRIES + 1))
        [ $TRIES -ge 20 ] && die "OpenOCD failed to start. Check $STATE_DIR/openocd.log"
    done
else
    while ! nc -z localhost "$TCL_PORT" 2>/dev/null; do
        sleep 0.5
        TRIES=$((TRIES + 1))
        [ $TRIES -ge 20 ] && die "OpenOCD failed to start. Check $STATE_DIR/openocd.log"
    done
fi
info "OpenOCD ready (PID $(cat "$STATE_DIR/openocd.pid"))"

# ── Verify target ───────────────────────────────────

HEALTH=$("$PYTHON" "$SCRIPT_DIR/esp_target.py" --config "$CONFIG" health 2>/dev/null || echo '{"ok": false}')
if echo "$HEALTH" | "$PYTHON" -c "import sys,json; sys.exit(0 if json.load(sys.stdin).get('ok') else 1)" 2>/dev/null; then
    info "Target responsive: $HEALTH"
else
    info "WARNING: Target not responding. Check USB connection."
fi

# ── Summary ─────────────────────────────────────────

echo ""
info "═══════════════════════════════════════════"
info "OpenOCD running. Start Claude Code or Codex now."
info "═══════════════════════════════════════════"
info ""
info "OpenOCD log: $STATE_DIR/openocd.log"
info ""
info "To start RTT logging (after firmware is built and flashed):"
info "  $PYTHON $SCRIPT_DIR/rtt_reader.py --elf build/<project>.elf --output $STATE_DIR/rtt.log --kill-existing --daemonize"
info ""
info "To stop: $SCRIPT_DIR/esp-session-stop.sh"
