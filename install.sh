#!/usr/bin/env bash

set -euo pipefail

REPO_URL="${ESP32_AGENT_REPO_URL:-https://github.com/XDL1234/esp32-agent.git}"
INSTALL_HOME="${ESP32_AGENT_HOME:-$HOME/.local/share/esp32-agent}"
REPO_DIR="$INSTALL_HOME/repo"
BIN_DIR="${ESP32_AGENT_BIN_DIR:-$HOME/.local/bin}"
CLAUDE_SKILLS_DIR="${ESP32_AGENT_CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
CODEX_SKILLS_DIR="${ESP32_AGENT_CODEX_SKILLS_DIR:-${CODEX_HOME:-$HOME/.codex}/skills}"
RUN_INIT=0
REUSE=0
INIT_ARGS=()

info() { printf '[esp32-agent installer] %s\n' "$*"; }
die() { printf '[esp32-agent installer] ERROR: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --init) RUN_INIT=1; shift; INIT_ARGS=("$@"); break ;;
        --reuse) REUSE=1; shift ;;
        -h|--help)
            printf '%s\n' "Usage: install.sh [--init]"
            exit 0
            ;;
        *) die "Unknown option: $1" ;;
    esac
done

command -v git >/dev/null 2>&1 || die "Git is required."

if [ "$REUSE" -eq 0 ]; then
    if [ -d "$REPO_DIR/.git" ]; then
        git -C "$REPO_DIR" remote set-url origin "$REPO_URL"
        git -C "$REPO_DIR" pull --ff-only
    elif [ -e "$REPO_DIR" ]; then
        die "$REPO_DIR exists but is not an esp32-agent Git checkout."
    else
        mkdir -p "$INSTALL_HOME"
        git clone --depth 1 --filter=blob:none --sparse "$REPO_URL" "$REPO_DIR"
    fi
fi

[ -d "$REPO_DIR/.git" ] || die "$REPO_DIR is not an esp32-agent Git checkout."
git -C "$REPO_DIR" sparse-checkout set agentic boards templates/configs Skills/esp32-agent bin

[ -f "$REPO_DIR/bin/esp32-agent" ] || die "Installed checkout is missing bin/esp32-agent."
[ -f "$REPO_DIR/Skills/esp32-agent/SKILL.md" ] || die "Installed checkout is missing the esp32-agent skill."

sync_skill() {
    local target="$1/esp32-agent"
    local marker="$target/.esp32-agent-managed"
    mkdir -p "$1"
    if [ -e "$target" ] && [ ! -f "$marker" ]; then
        local backup="$target.backup.$(date +%Y%m%d%H%M%S)"
        mv "$target" "$backup"
        info "Backed up existing skill to $backup"
    elif [ -e "$target" ]; then
        rm -rf "$target"
    fi
    cp -R "$REPO_DIR/Skills/esp32-agent" "$target"
    printf '%s\n' "$REPO_URL" > "$marker"
}

sync_skill "$CLAUDE_SKILLS_DIR"
sync_skill "$CODEX_SKILLS_DIR"

mkdir -p "$BIN_DIR"
cp "$REPO_DIR/bin/esp32-agent" "$BIN_DIR/esp32-agent"
chmod +x "$BIN_DIR/esp32-agent"

info "Installed Claude skill: $CLAUDE_SKILLS_DIR/esp32-agent"
info "Installed Codex skill:  $CODEX_SKILLS_DIR/esp32-agent"
info "Installed CLI:          $BIN_DIR/esp32-agent"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) info "Add $BIN_DIR to PATH or run $BIN_DIR/esp32-agent directly." ;;
esac

if [ "$RUN_INIT" -eq 1 ]; then
    ESP32_AGENT_REPO_DIR="$REPO_DIR" "$BIN_DIR/esp32-agent" init "${INIT_ARGS[@]}"
else
    info "Next: esp32-agent init"
fi
