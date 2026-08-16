#!/bin/bash
#
# idf_build.sh — idf.py 包装脚本，跨平台兼容。
#
# - Windows (Git Bash / MSYS2)：清除 $MSYSTEM 后通过 IDF venv Python 调用 idf.py
# - Linux / macOS：直接透传到 idf.py（与上游行为一致）
#
# 用法：
#   ./agentic/idf_build.sh              # 等同于 idf.py build
#   ./agentic/idf_build.sh menuconfig   # 等同于 idf.py menuconfig
#   ./agentic/idf_build.sh clean        # 等同于 idf.py clean
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG="$SCRIPT_DIR/esp_target_config.json"

ACTION="${*:-build}"

# ── 读取 platform 字段（fallback 到 uname 自动检测）──

PLATFORM=""
if [ -f "$CONFIG" ]; then
    PLATFORM=$(python3 -c "import json; print(json.load(open('$CONFIG')).get('platform',''))" 2>/dev/null || true)
fi
if [ -z "$PLATFORM" ]; then
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*) PLATFORM="windows" ;;
        *)                    PLATFORM="linux" ;;
    esac
fi

# ── 按平台分支 ──────────────────────────────────────

if [ "$PLATFORM" = "windows" ]; then
    # Windows: 通过 IDF venv Python 调用，清除 MSYSTEM
    IDF_PYTHON="${IDF_PYTHON_ENV_PATH}/Scripts/python.exe"
    [ -f "$IDF_PYTHON" ] || { echo "ERROR: Cannot find ESP-IDF Python venv. Set IDF_PYTHON_ENV_PATH." >&2; exit 1; }

    IDF_PY="${IDF_PATH}/tools/idf.py"
    [ -f "$IDF_PY" ] || { echo "ERROR: IDF_PATH not set or idf.py not found at $IDF_PY" >&2; exit 1; }

    WIN_PROJECT_DIR=$(cygpath -w "$PROJECT_DIR")

    exec "$IDF_PYTHON" -c "
import os, subprocess, sys
env = os.environ.copy()
env.pop('MSYSTEM', None)
env.pop('MSYS', None)
idf_py = os.path.join(env['IDF_PATH'], 'tools', 'idf.py')
args = [sys.executable, idf_py] + sys.argv[1:]
sys.exit(subprocess.run(args, env=env, cwd=r'${WIN_PROJECT_DIR}').returncode)
" $ACTION
else
    # Linux / macOS: 直接调用 idf.py（与上游一致）
    exec idf.py $ACTION
fi
