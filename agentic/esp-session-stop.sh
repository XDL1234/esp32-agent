#!/bin/bash
#
# esp-session-stop.sh — Tear down agentic firmware development infrastructure.
#
# Stops OpenOCD and any rtt_reader.py that may be running.
#

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="$SCRIPT_DIR/.esp-agent"

info() { echo "[session] $*"; }

# ── Platform detection ─────────────────────────────
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) PLATFORM="windows" ;;
    *)                     PLATFORM="unix" ;;
esac

if [ ! -d "$STATE_DIR" ]; then
    info "No active session found."
    exit 0
fi

info "Stopping infrastructure..."

# Stop only the OpenOCD process recorded for this project.
if [ -f "$STATE_DIR/openocd.pid" ]; then
    PID=$(cat "$STATE_DIR/openocd.pid" 2>/dev/null || true)
    if [[ "$PID" =~ ^[0-9]+$ ]]; then
        if [ "$PLATFORM" = "windows" ]; then
            powershell -NoProfile -Command \
                "\$p = Get-Process -Id $PID -ErrorAction SilentlyContinue; if (\$p -and \$p.ProcessName -like 'openocd*') { Stop-Process -Id $PID -Force }" \
                2>/dev/null && info "Stopped OpenOCD PID $PID" || true
        elif ps -p "$PID" -o comm= 2>/dev/null | grep -qi openocd; then
            kill "$PID" 2>/dev/null && info "Stopped OpenOCD PID $PID" || true
        fi
    fi
fi
rm -f "$STATE_DIR/openocd.pid"

# Stop only the RTT reader recorded for this project.
if [ -f "$STATE_DIR/rtt_reader.pid" ]; then
    PID=$(cat "$STATE_DIR/rtt_reader.pid" 2>/dev/null || true)
    if [[ "$PID" =~ ^[0-9]+$ ]]; then
        if [ "$PLATFORM" = "windows" ]; then
            powershell -NoProfile -Command \
                "\$p = Get-CimInstance Win32_Process -Filter 'ProcessId=$PID' -ErrorAction SilentlyContinue; if (\$p -and \$p.CommandLine -like '*rtt_reader.py*') { Stop-Process -Id $PID -Force }" \
                2>/dev/null && info "Stopped RTT reader PID $PID" || true
        elif ps -p "$PID" -o args= 2>/dev/null | grep -q rtt_reader.py; then
            kill "$PID" 2>/dev/null && info "Stopped RTT reader PID $PID" || true
        fi
    fi
fi
rm -f "$STATE_DIR/rtt_reader.pid"

# Wait for USB device release
sleep 2

info "Done. Logs preserved in $STATE_DIR/"
