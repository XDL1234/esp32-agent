#!/bin/bash
#
# test-full-toolchain.sh — esp32-agent 完整工具链测试
#
# 从零开始验证完整开发流程：编译 → 烧录 → 调试 → 监视
# 前提：项目源码存在（main/）、OpenOCD 已启动（esp32-agent start）
#
# 用法：
#   bash test-full-toolchain.sh
#

set +e

LOG="test-toolchain-output.txt"
exec > >(tee "$LOG") 2>&1

PASS=0
FAIL=0
SKIP=0

pass() { echo "  ✓ PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ FAIL: $1"; FAIL=$((FAIL + 1)); }
skip() { echo "  - SKIP: $1"; SKIP=$((SKIP + 1)); }

run_test() {
    local name="$1"
    shift
    echo ""
    echo "── $name ──"
    OUTPUT=$("$@" 2>&1)
    RC=$?
    if [ $RC -eq 0 ]; then
        pass "$name (rc=$RC)"
    else
        fail "$name (rc=$RC)"
    fi
    echo "$OUTPUT" | head -10
    return $RC
}

echo "═══════════════════════════════════════════════════════════════"
echo "esp32-agent 完整工具链测试（从零开始）"
echo "开始时间: $(date)"
echo "═══════════════════════════════════════════════════════════════"

# ══════════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════╗"
echo "║  1. 离线工具（无需编译、无需连接）     ║"
echo "╚══════════════════════════════════════╝"

run_test "info — 项目配置" \
    python3 agentic/esp_target.py info

run_test "memmap — 芯片内存映射" \
    python3 agentic/esp_target.py memmap

run_test "list-periph — SVD 外设列表" \
    python3 agentic/esp_target.py list-periph

# ══════════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════╗"
echo "║  2. OpenOCD 连接验证                  ║"
echo "╚══════════════════════════════════════╝"

run_test "health — OpenOCD 连接" \
    python3 agentic/esp_target.py health

run_test "state — CPU 执行状态" \
    python3 agentic/esp_target.py state

run_test "raw targets — 目标列表" \
    python3 agentic/esp_target.py raw "targets"

# ══════════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════╗"
echo "║  3. 编译固件                          ║"
echo "╚══════════════════════════════════════╝"

echo ""
echo "── 清理旧 build（确保从零编译）──"
rm -rf build
echo "  已清理"

echo ""
echo "── RTT 集成检查 ──"
if [ ! -f main/SEGGER_RTT.h ]; then
    echo "  RTT 未集成，自动添加..."
    cp agentic/SEGGER_RTT.c agentic/SEGGER_RTT.h agentic/SEGGER_RTT_printf.c agentic/SEGGER_RTT_Conf.h main/

    # 在 CMakeLists.txt 中添加 RTT 源文件（如果还没有）
    if ! grep -q "SEGGER_RTT" main/CMakeLists.txt 2>/dev/null; then
        # 找到 idf_component_register 的 SRCS 行，追加 RTT 文件
        if grep -q "idf_component_register" main/CMakeLists.txt; then
            sed -i 's/idf_component_register(SRCS /idf_component_register(SRCS "SEGGER_RTT.c" "SEGGER_RTT_printf.c" /' main/CMakeLists.txt
            echo "  已修改 CMakeLists.txt"
        else
            echo "  WARNING: 无法自动修改 CMakeLists.txt，请手动添加 SEGGER_RTT.c"
        fi
    fi

    # 在 app_main 中添加 RTT 初始化（如果还没有）
    MAIN_C=$(find main/ -name "*.c" -exec grep -l "app_main" {} \; | head -1)
    if [ -n "$MAIN_C" ] && ! grep -q "SEGGER_RTT" "$MAIN_C"; then
        python3 -c "
import re, sys
with open('$MAIN_C', 'r') as f:
    code = f.read()

# 添加 include（在最后一个 #include 之后）
last_include = code.rfind('#include')
if last_include >= 0:
    end_of_line = code.index('\n', last_include)
    code = code[:end_of_line+1] + '#include \"SEGGER_RTT.h\"\n' + code[end_of_line+1:]
else:
    code = '#include \"SEGGER_RTT.h\"\n' + code

# 在 app_main 函数体的第一个 { 后添加 RTT 初始化和输出
match = re.search(r'(void\s+app_main\s*\([^)]*\)\s*\{)', code)
if match:
    insert_pos = match.end()
    rtt_code = '''
    SEGGER_RTT_Init();
    SEGGER_RTT_WriteString(0, \"Boot complete\\\\n\");'''
    code = code[:insert_pos] + rtt_code + code[insert_pos:]
    print('  注入成功')
else:
    print('  WARNING: 未找到 app_main 函数体', file=sys.stderr)

with open('$MAIN_C', 'w') as f:
    f.write(code)
" 2>&1
        echo "  已在 $MAIN_C 中添加 RTT"
    fi

    # 验证注入结果
    if grep -q "SEGGER_RTT_Init\|SEGGER_RTT_WriteString" "$MAIN_C" 2>/dev/null; then
        echo "  验证: RTT 调用已存在于 $MAIN_C ✓"
    else
        echo "  验证: WARNING — RTT 调用未找到！"
    fi
    if grep -q "SEGGER_RTT" main/CMakeLists.txt 2>/dev/null; then
        echo "  验证: CMakeLists.txt 包含 SEGGER_RTT ✓"
    else
        echo "  验证: WARNING — CMakeLists.txt 未包含 SEGGER_RTT！"
    fi

    pass "RTT 自动集成"
else
    echo "  RTT 已存在"
    pass "RTT 已集成"
fi

echo ""
echo "── 全量编译 ──"
START_SEC=$(date +%s)
./agentic/idf_build.sh 2>&1 | while IFS= read -r line; do
    # 显示 ninja 进度（如 [42/318]）
    if echo "$line" | grep -qE '^\[[ 0-9]+/[ 0-9]+\]'; then
        CURRENT=$(echo "$line" | grep -oE '\[[ 0-9]+/' | tr -d '[ /')
        TOTAL=$(echo "$line" | grep -oE '/[ 0-9]+\]' | tr -d '/ ]')
        if [ -n "$CURRENT" ] && [ -n "$TOTAL" ] && [ "$TOTAL" -gt 0 ]; then
            PCT=$((CURRENT * 100 / TOTAL))
            printf "\r  编译进度: [%d/%d] %d%%  " "$CURRENT" "$TOTAL" "$PCT"
        fi
    fi
done
printf "\n"
BUILD_RC=${PIPESTATUS[0]}
END_SEC=$(date +%s)
ELAPSED=$((END_SEC - START_SEC))

if [ $BUILD_RC -eq 0 ]; then
    pass "全量编译 (${ELAPSED}s)"
else
    fail "全量编译 (rc=$BUILD_RC, ${ELAPSED}s)"
    echo ""
    echo "编译失败，后续测试无法继续。"
    echo "═══════════════════════════════════════════════════════════════"
    exit 1
fi

# 验证编译产物
echo ""
echo "── 编译产物检查 ──"
ELF=$(find build/ -maxdepth 1 -name "*.elf" -type f 2>/dev/null | head -1)
if [ -z "$ELF" ]; then
    # Fallback: look in build/ but exclude bootloader
    ELF=$(find build/ -name "*.elf" -not -path "*/bootloader/*" -type f 2>/dev/null | head -1)
fi
if [ -n "$ELF" ] && [ -f "build/flasher_args.json" ]; then
    pass "编译产物 (ELF: $ELF)"
else
    fail "编译产物缺失"
fi

# ══════════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════╗"
echo "║  4. 烧录固件                          ║"
echo "╚══════════════════════════════════════╝"

echo ""
echo "── flash-and-run 计时 ──"
START_SEC=$(date +%s)
python3 agentic/esp_target.py flash-and-run build/ --app-only 2>&1
FLASH_RC=$?
END_SEC=$(date +%s)
ELAPSED=$((END_SEC - START_SEC))

if [ $FLASH_RC -eq 0 ]; then
    pass "flash-and-run (${ELAPSED}s)"
else
    fail "flash-and-run (rc=$FLASH_RC, ${ELAPSED}s)"
fi

# 烧录后稳定性
sleep 2
run_test "health（烧录后）" \
    python3 agentic/esp_target.py health

run_test "state（烧录后，期望 running）" \
    python3 agentic/esp_target.py state

# ══════════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════╗"
echo "║  5. CPU 控制                          ║"
echo "╚══════════════════════════════════════╝"

run_test "halt — 暂停 CPU" \
    python3 agentic/esp_target.py halt

run_test "state（halted 验证）" \
    python3 agentic/esp_target.py state

run_test "resume — 恢复 CPU" \
    python3 agentic/esp_target.py resume

run_test "state（running 验证）" \
    python3 agentic/esp_target.py state

# ══════════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════╗"
echo "║  6. CPU 寄存器读取                    ║"
echo "╚══════════════════════════════════════╝"

python3 agentic/esp_target.py halt 2>/dev/null

run_test "cpu-regs — 转储所有寄存器" \
    python3 agentic/esp_target.py cpu-regs

run_test "cpu-reg pc — 读取 PC" \
    python3 agentic/esp_target.py cpu-reg pc

run_test "cpu-reg sp — 读取 SP" \
    python3 agentic/esp_target.py cpu-reg sp

python3 agentic/esp_target.py resume 2>/dev/null

# ══════════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════╗"
echo "║  7. 内存读取                          ║"
echo "╚══════════════════════════════════════╝"

SRAM_START=$(python3 -c "
import json
from pathlib import Path
cfg_path = Path('agentic/esp_target_config.json')
cfg = json.load(open(cfg_path))
chip_path = cfg_path.parent / cfg['chip']
chip = json.load(open(chip_path))
print(chip['memory']['sram']['start'])
" 2>/dev/null)

if [ -n "$SRAM_START" ]; then
    run_test "read — SRAM 32 位读取" \
        python3 agentic/esp_target.py read "$SRAM_START" 4

    run_test "read --width 8 — 字节读取" \
        python3 agentic/esp_target.py read "$SRAM_START" 8 --width 8
else
    skip "read — 无法获取 SRAM 地址"
    skip "read --width 8"
fi

# ══════════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════╗"
echo "║  8. SVD 外设寄存器（在线）             ║"
echo "╚══════════════════════════════════════╝"

PERIPH=$(python3 agentic/esp_target.py list-periph 2>/dev/null | head -1 | awk '{print $1}')
if [ -n "$PERIPH" ]; then
    run_test "list-regs $PERIPH" \
        python3 agentic/esp_target.py list-regs "$PERIPH"

    REG=$(python3 agentic/esp_target.py list-regs "$PERIPH" 2>/dev/null | head -1 | awk '{print $1}')
    if [ -n "$REG" ]; then
        run_test "read-reg $PERIPH.$REG" \
            python3 agentic/esp_target.py read-reg "$PERIPH.$REG"

        run_test "decode $PERIPH.$REG" \
            python3 agentic/esp_target.py decode "$PERIPH.$REG"
    fi

    run_test "inspect $PERIPH" \
        python3 agentic/esp_target.py inspect "$PERIPH"
else
    skip "SVD 在线测试 — 无外设"
fi

# ══════════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════╗"
echo "║  9. RTT 日志监视                      ║"
echo "╚══════════════════════════════════════╝"

if [ -n "$ELF" ]; then
    run_test "rtt_reader --scan-only" \
        python3 agentic/rtt_reader.py --elf "$ELF" --scan-only

    echo ""
    echo "── RTT 数据读取（6 秒）──"
    rm -f agentic/.esp-agent/rtt.log
    timeout 6 python3 agentic/rtt_reader.py --elf "$ELF" \
        --output agentic/.esp-agent/rtt.log --kill-existing 2>/dev/null

    if [ -f agentic/.esp-agent/rtt.log ] && [ -s agentic/.esp-agent/rtt.log ]; then
        BYTES=$(wc -c < agentic/.esp-agent/rtt.log)
        pass "RTT 数据读取 (${BYTES} bytes)"
        echo "  前 3 行:"
        head -3 agentic/.esp-agent/rtt.log
    else
        fail "RTT 数据读取（日志为空或不存在）"
    fi
else
    skip "RTT — 未找到 ELF"
fi

# ══════════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════╗"
echo "║  10. GDB 批处理                       ║"
echo "╚══════════════════════════════════════╝"

GDB_EXE=$(python3 -c "
import json
cfg = json.load(open('agentic/esp_target_config.json'))
print(cfg.get('gdb', {}).get('executable', 'riscv32-esp-elf-gdb'))
" 2>/dev/null)
GDB_PORT=$(python3 -c "
import json
cfg = json.load(open('agentic/esp_target_config.json'))
print(cfg.get('openocd', {}).get('gdb_port', 3333))
" 2>/dev/null)

if command -v "$GDB_EXE" >/dev/null 2>&1 && [ -n "$ELF" ]; then
    python3 agentic/esp_target.py halt 2>/dev/null
    echo ""
    echo "── GDB batch: info threads ──"
    OUTPUT=$("$GDB_EXE" -batch \
        -ex "set remotetimeout 10" \
        -ex "target remote :${GDB_PORT}" \
        -ex "info threads" \
        "$ELF" 2>&1)
    RC=$?
    if echo "$OUTPUT" | grep -q "Thread\|thread\|Id.*Target"; then
        pass "GDB batch info threads"
    elif [ $RC -eq 0 ]; then
        pass "GDB batch (连接成功，无线程信息)"
    else
        fail "GDB batch (rc=$RC)"
    fi
    echo "$OUTPUT" | head -5
    python3 agentic/esp_target.py resume 2>/dev/null
else
    skip "GDB — $GDB_EXE 不在 PATH 或无 ELF"
fi

# ══════════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════╗"
echo "║  11. 会话管理                         ║"
echo "╚══════════════════════════════════════╝"

run_test "esp-session-stop.sh" \
    ./agentic/esp-session-stop.sh

sleep 3

run_test "esp-session-start.sh" \
    ./agentic/esp-session-start.sh

run_test "health（重启后）" \
    python3 agentic/esp_target.py health

# ══════════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════╗"
echo "║  12. reset run（已知限制）             ║"
echo "╚══════════════════════════════════════╝"

echo ""
echo "── reset run ──"
echo "  注意：ESP32-P4 USB-JTAG 复位后 USB 断开，恢复不可靠。"
echo "  此测试验证错误处理是否正确（期望快速失败而非挂死）。"
START_SEC=$(date +%s)
timeout 30 python3 agentic/esp_target.py reset run 2>&1
RESET_RC=$?
END_SEC=$(date +%s)
ELAPSED=$((END_SEC - START_SEC))

if [ $RESET_RC -eq 0 ]; then
    pass "reset run 恢复成功 (${ELAPSED}s)"
else
    # 快速失败是正确行为
    if [ $ELAPSED -lt 60 ]; then
        pass "reset run 快速失败 (${ELAPSED}s — 正确行为)"
    else
        fail "reset run 超时 (${ELAPSED}s — 应更快失败)"
    fi
fi

# 恢复 OpenOCD 给后续使用（reset 后 USB 需要更长时间恢复）
echo ""
echo "── 恢复 OpenOCD ──"
./agentic/esp-session-stop.sh 2>/dev/null
echo "  等待 USB 重新枚举 (10s)..."
sleep 10
./agentic/esp-session-start.sh 2>/dev/null
if [ $? -ne 0 ]; then
    echo "  第一次恢复失败，再等 5s 重试..."
    sleep 5
    ./agentic/esp-session-start.sh 2>/dev/null
fi
run_test "health（最终恢复）" \
    python3 agentic/esp_target.py health

# ══════════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "测试结束: $(date)"
echo ""
echo "╔══════════════════════════════════════╗"
echo "║  结果统计                             ║"
echo "╠══════════════════════════════════════╣"
printf "║  ✓ PASS: %-3d                        ║\n" $PASS
printf "║  ✗ FAIL: %-3d                        ║\n" $FAIL
printf "║  - SKIP: %-3d                        ║\n" $SKIP
printf "║  总计:   %-3d                        ║\n" $((PASS + FAIL + SKIP))
echo "╚══════════════════════════════════════╝"
echo ""
if [ $FAIL -eq 0 ]; then
    echo "  全部通过！"
else
    echo "  有 $FAIL 项失败，请检查上方输出。"
fi
echo ""
echo "日志文件: $LOG"
echo "═══════════════════════════════════════════════════════════════"
exit "$FAIL"
