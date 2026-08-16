# 基于 JTAG 的 Agentic 固件开发

本项目使用 JTAG 进行调试、日志捕获和寄存器检查。
烧录方式由 `esp_target_config.json` 中的设置决定
（`flash.method`：通过 OpenOCD `program_esp` 的 `jtag` 方式，或通过
`esptool.py` 的 `serial` 方式）。

## 配置

两个配置文件控制工具链：

**`agentic/esp_target_config.json`** — 项目级工具配置：
- 使用哪个芯片硬件描述
- OpenOCD 设置（板级配置、端口、烧录命令）
- 烧录方式（`jtag` 或 `serial`）以及适用时的串口参数
- 工具链前缀（用于推导 nm、objdump、addr2line 和默认 GDB）
- GDB 可执行文件（未指定时默认为 `{prefix}gdb`）
- 日志方式（rtt 或 apptrace）

**`agentic/chips/<chip>.json`** — 纯硬件参考（内存映射、架构）。
由 `esp_target_config.json` 引用。无需按项目编辑。
芯片 JSON 文件可能包含对应 SVD 文件的引用，其中定义了外设寄存器。

**`agentic/board.md`** — 描述具体的开发板：GPIO 引脚分配、I2C/SPI
总线连接、LED（类型、引脚、协议）、按钮、传感器、电源域，以及与
固件开发相关的其他硬件上下文。在编写任何与板载外设交互的代码之前
请先阅读此文件。

查看完整的解析后配置：
```
python3 agentic/esp_target.py info
```

查看芯片内存映射：
```
python3 agentic/esp_target.py memmap
```

所有工具位于 `agentic/` 子目录中。`esp_target.py` 和 `rtt_reader.py`
会自动从其所在目录读取 `esp_target_config.json`。

## 项目结构

```
project/
├── CLAUDE.md                     # 本文件
├── agentic/                      # agentic 工具（所有工具位于此处）
│   ├── esp_target_config.json    # 工具配置（OpenOCD、GDB、日志、烧录方式）
│   ├── board.md                  # 板级硬件描述（引脚、LED、总线）
│   ├── esp_target.py             # 目标控制工具
│   ├── svd_parser.py             # SVD 解析器（由 esp_target.py 使用）
│   ├── rtt_reader.py             # RTT 日志读取守护进程
│   ├── esp-session-start.sh      # 启动 OpenOCD
│   ├── esp-session-stop.sh       # 停止守护进程
│   ├── idf_build.sh              # idf.py 包装脚本（在 Git Bash 上绕过 MSYSTEM）
│   ├── chips/
│   │   ├── <chip>.json           # 硬件参考（内存映射、架构）
│   │   └── <chip>.svd            # 外设寄存器定义（可选）
│   └── .esp-agent/               # 运行时状态（会话启动时创建）
│       ├── openocd.log           # OpenOCD 守护进程日志
│       ├── rtt.log               # 固件 RTT 输出
│       └── rtt_reader.log        # rtt_reader 标准错误输出（可选）
├── main/
│   ├── CMakeLists.txt            # 组件注册（idf_component_register）
│   ├── *.c / *.h                 # 应用源代码
│   ├── SEGGER_RTT.c              # RTT 库（目标端）
│   ├── SEGGER_RTT.h
│   ├── SEGGER_RTT_Conf.h         # RTT 配置（架构相关的锁宏）
│   └── SEGGER_RTT_printf.c
├── CMakeLists.txt                # 顶层项目 CMakeLists
├── sdkconfig                     # ESP-IDF menuconfig 输出
└── build/                        # 构建输出（生成的）
    ├── flasher_args.json         # 烧录布局：哪个二进制文件在哪个偏移地址
    ├── <project>.bin             # 应用二进制文件
    ├── <project>.elf             # 带调试符号的 ELF 文件
    ├── bootloader/
    │   └── bootloader.bin
    └── partition_table/
        └── partition-table.bin
```

## 架构

```
Coding Agent
  ├── idf.py build                    → 编译固件
  ├── esp_target.py (shell exec)      → 烧录、复位、检查寄存器
  ├── GDB batch scripts (on-demand)   → 符号感知调试
  ├── reads board.md                  → 板级描述
  ├── reads .esp-agent/rtt.log        → 固件日志输出
  └── reads .esp-agent/openocd.log    → 基础设施诊断

esp_target.py
  └── OpenOCD Tcl port                → mww/mdw, program_esp, halt/resume
      （或在 flash.method = serial 时委托给 esptool）

rtt_reader.py（后台守护进程）
  └── OpenOCD Tcl port                → 通过 mdw/mww 轮询 RTT 环形缓冲区

OpenOCD（持久守护进程）
  ├── Tcl port     — 来自 esp_target.py 和 rtt_reader.py 的命令
  ├── GDB RSP port — 按需符号感知调试
  └── USB-JTAG     → 目标 MCU
```

esp_target.py 和 rtt_reader.py 同时连接到 OpenOCD 的 Tcl 端口。
OpenOCD 在内部序列化 JTAG 事务。端口号在 `esp_target_config.json` 中定义。

## 前提条件

ESP-IDF 环境必须在 shell 中处于激活状态 — `idf.py`、`openocd`
和交叉编译器必须在 PATH 中。如果任何命令报 "command not found" 错误，
请告知用户在启动会话的 shell 中运行 `. $IDF_PATH/export.sh`，然后重启。

**在 Windows 上**，打开 VSCode ESP-IDF 扩展的内置终端（Git Bash）。
`$IDF_PATH` 和 `IDF_PYTHON_ENV_PATH` 已由扩展设置 — 无需手动
`export.sh`。

假定 OpenOCD 已在运行并连接到目标。通过以下命令验证连接：

```
python3 agentic/esp_target.py health
```

如果 OpenOCD 无响应，重启会话：

```
./agentic/esp-session-stop.sh
./agentic/esp-session-start.sh
```

**`esp-session-start.sh`** — 读取 `esp_target_config.json`，终止任何
残留的 OpenOCD 进程，启动新的 OpenOCD 守护进程（日志 →
`.esp-agent/openocd.log`），等待 Tcl 端口就绪，然后通过
`esp_target.py health` 验证目标响应。如果 OpenOCD 启动失败则退出并报错。

**`esp-session-stop.sh`** — 终止 OpenOCD（通过 `.esp-agent/openocd.pid`
中的 PID 和进程名），停止任何运行中的 `rtt_reader.py`，并保留
`.esp-agent/` 中的日志。

RTT 日志需要单独启动，在构建并烧录了支持 RTT 的固件之后：
```
python3 agentic/rtt_reader.py --elf build/<project>.elf --output agentic/.esp-agent/rtt.log --kill-existing --daemonize
```

## 构建

```
./agentic/idf_build.sh
```

在 Git Bash / MSYS2 上，此包装脚本会在调用 `idf.py` 前从环境中移除
`$MSYSTEM`（ESP-IDF ≥ 5.5 否则拒绝运行）。在 Linux 和 macOS 上，
其行为与 `idf.py` 完全相同。

**重要：编译命令必须设置 10 分钟超时**（`timeout: 600000`）。
首次全量编译需要 3-10 分钟，增量编译通常 10-30 秒。

其他 idf.py 子命令同样可用：
```
./agentic/idf_build.sh menuconfig
./agentic/idf_build.sh clean
./agentic/idf_build.sh size
```

解析编译器输出中的错误和警告。所有构建产物位于 `build/` 中。
关键输出为：
- `build/flasher_args.json` — 烧录偏移地址的权威来源
- `build/<project>.bin` — 应用二进制文件
- `build/<project>.elf` — 带调试符号的 ELF 文件（GDB 和 RTT 需要）

## ESP-IDF 参考

ESP-IDF 框架源码树位于 `$IDF_PATH`。可查阅其中的 API 用法、
外设驱动模式和工作示例。

```
$IDF_PATH/
├── examples/                     # 每个功能的工作示例
├── components/                   # 框架源代码
└── tools/
    └── esp_app_trace/            # 主机端 apptrace 解码器
```

实现外设驱动或功能时：
1. 在 `$IDF_PATH/examples/` 中查找工作参考
2. 阅读 `$IDF_PATH/components/<component>/include/` 中的组件头文件
3. 检查 `$IDF_PATH/components/<component>/Kconfig` 中的 menuconfig 选项

### 绝不猜测芯片特定的硬件常量

芯片特定的值 — GPIO 矩阵信号索引、寄存器位域位置、外设基地址 —
是任意的硬件分配，在不同芯片系列之间各不相同。它们不能从第一性原理
推导，绝不能猜测。

始终在以下位置查找：
```
$IDF_PATH/components/soc/<chip>/include/soc/
  gpio_sig_map.h      — GPIO 矩阵信号索引
  io_mux_reg.h        — IO_MUX 寄存器位定义
  <periph>_struct.h   — 外设寄存器布局

$IDF_PATH/components/hal/<chip>/include/hal/
  <periph>_ll.h       — 底层驱动常量
```

## 烧录

烧录所有组件（bootloader + 分区表 + 应用）：
```
python3 agentic/esp_target.py flash build/
```

仅烧录应用（更快，适用于迭代开发）：
```
python3 agentic/esp_target.py flash build/ --app-only
```

烧录、复位并运行一步完成：
```
python3 agentic/esp_target.py flash-and-run build/ --app-only
```

烧录方式由 `esp_target_config.json` 中的 `flash.method` 设置（配置向导时选择）：
- `"jtag"` — 使用 OpenOCD `program_esp`。OpenOCD 保持运行，不中断调试会话。
- `"serial"` — 使用 `esptool.py` 通过 USB CDC。工具会自动检测 Espressif
  设备，烧录前停止 OpenOCD，烧录后自动重启并重连。

绝不硬编码烧录偏移地址 — 它们来自 `build/flasher_args.json`。

烧录新固件后，重启 RTT 读取器（控制块地址可能已改变）：
```
python3 agentic/rtt_reader.py --elf build/<project>.elf --output agentic/.esp-agent/rtt.log --kill-existing --daemonize
```

## 目标控制

所有命令通过 `agentic/esp_target.py` 执行：

```
# 复位
python3 agentic/esp_target.py reset run

# 检查执行状态
python3 agentic/esp_target.py state

# 暂停 / 恢复
python3 agentic/esp_target.py halt
python3 agentic/esp_target.py wait-halt
python3 agentic/esp_target.py resume

# 擦除整个 flash
python3 agentic/esp_target.py erase

# 读取内存（CPU 运行时可用）
python3 agentic/esp_target.py read <addr> <count>
python3 agentic/esp_target.py read <addr> <count> --width 8

# 写入内存
python3 agentic/esp_target.py write <addr> <value> [<value> ...]
python3 agentic/esp_target.py write <addr> <value> --width 8

# 转储所有 CPU 寄存器（必须先暂停）
python3 agentic/esp_target.py halt
python3 agentic/esp_target.py cpu-regs
python3 agentic/esp_target.py resume

# 读取 / 写入单个 CPU 寄存器
python3 agentic/esp_target.py cpu-reg pc
python3 agentic/esp_target.py cpu-reg-write a0 0x1234

# 原始 OpenOCD 命令
python3 agentic/esp_target.py raw "targets"
```

OpenOCD 的 `reg <name> <value>` 写入响应在不同寄存器间不统一。
`pc` 在写入时可能回显先前的值。如果写入后的 `pc` 值很重要，
请随后执行显式的 `cpu-reg pc` 读取。

查看有效的 SRAM 和外设地址，请检查内存映射：
```
python3 agentic/esp_target.py memmap
```

访问 SRAM 时使用数据总线地址，而非指令总线别名。

## SVD 感知的寄存器检查

配置了 SVD 文件后，可以通过名称访问寄存器：

```
python3 agentic/esp_target.py list-periph
python3 agentic/esp_target.py list-regs GPIO
python3 agentic/esp_target.py read-reg GPIO.OUT
python3 agentic/esp_target.py decode GPIO.OUT
python3 agentic/esp_target.py inspect UART0
python3 agentic/esp_target.py write-reg GPIO.OUT_W1TS 0x400
```

寄存器路径表示法为 `PERIPHERAL.REGISTER` 或
`PERIPHERAL.REGISTER.FIELD`。`list-periph`、`list-regs` 和 `memmap`
可离线工作，无需 OpenOCD。

## GDB 调试

GDB 连接到 OpenOCD 的 GDB RSP 端口。通过以下命令查找可执行文件和端口：
```
python3 agentic/esp_target.py info
```

### 批处理模式（agentic 使用的首选方式）

```
<gdb_executable> -batch \
    -ex "target remote :<gdb_port>" \
    -ex "bt" \
    build/<project>.elf
```

### 暂停/恢复协议

**GDB 连接时会暂停 CPU。** 当 GDB 批处理会话退出时，CPU 保持暂停状态
— RTT 输出停止。之后务必恢复：

```
python3 agentic/esp_target.py resume
```

如果 GDB 之后 RTT 输出静默，检查
`python3 agentic/esp_target.py state` 并在暂停时恢复。

GDB 连接期间，不要使用 esp_target.py 的 halt/resume/reset 命令。
内存读取和 RTT 轮询可以与 GDB 安全并发。

## RTT 日志捕获

固件必须包含 SEGGER RTT 并写入通道 0：
```c
#include "SEGGER_RTT.h"
SEGGER_RTT_WriteString(0, "Hello from RTT\n");
SEGGER_RTT_printf(0, "value = %d\n", some_value);
```

启动读取器：
```
python3 agentic/rtt_reader.py --elf build/<project>.elf --output agentic/.esp-agent/rtt.log --kill-existing --daemonize
```

定位 RTT 控制块的选项：
1. `--elf build/<project>.elf` — 默认方式，即时，始终正确
2. `--address <addr>` — 已知地址，即时
3. （无标志）— 扫描 SRAM，较慢；最后手段

附加标志：
- `--rotate` — 将旧日志轮转为带时间戳的文件而非截断

运行读取器后，等待 2-3 秒然后读取 `agentic/.esp-agent/rtt.log`。
如果日志为空，请检查你的代码而非重启读取器。

### RTT 恢复

如果 RTT 产生乱码或停止接收数据：
1. 终止 rtt_reader.py 进程
2. 重新烧录：`python3 agentic/esp_target.py flash-and-run build/ --app-only`
3. 使用 `--elf` 重启读取器以获取新的控制块地址

## 访问日志

- **固件输出** — `agentic/.esp-agent/rtt.log`
- **OpenOCD 日志** — `agentic/.esp-agent/openocd.log`

## 重要约束

- 内存读取（`mdw`）在 CPU 运行时可用；CPU 寄存器读取需要先暂停
- GDB 会话活跃时不要通过 esp_target.py 暂停 CPU
- 芯片复位后，等待约 1 秒再发送命令 — USB-JTAG 链路在复位期间会短暂断开
- RTT 控制块地址在固件以不同静态变量布局重新构建时会改变 —
  重新烧录后务必重启 rtt_reader.py
- 烧录偏移地址取决于芯片和项目 — 始终从 `build/flasher_args.json` 读取，
  绝不硬编码
- 查阅 `python3 agentic/esp_target.py memmap` 获取内存地址 —
  不要假设一个芯片的地址范围适用于另一个芯片

## 典型开发周期

1. 编辑 `main/` 中的源代码
2. `./agentic/idf_build.sh` — 修复任何编译错误
3. `python3 agentic/esp_target.py flash build/ --app-only`
4. `python3 agentic/esp_target.py reset run`
5. 等待 2 秒，读取 `agentic/.esp-agent/rtt.log`
6. 如果有问题，检查硬件状态：
   - `decode` / `inspect` 外设寄存器
   - 崩溃后 `halt` + `cpu-regs`
   - GDB 批处理进行符号感知检查
7. 诊断、编辑、重复

或使用快捷方式：
```
python3 agentic/esp_target.py flash-and-run build/ --app-only
```

## 调试崩溃或挂起

1. 检查 `agentic/.esp-agent/rtt.log` 中的 panic 回溯
2. `python3 agentic/esp_target.py halt`
3. `python3 agentic/esp_target.py cpu-regs` — 检查 `pc`
4. `python3 agentic/esp_target.py cpu-reg mcause` — 异常原因
5. 使用 GDB 进行符号感知诊断（通过 `info` 查找可执行文件和端口）：
   ```
   <gdb_executable> -batch \
       -ex "target remote :<gdb_port>" \
       -ex "bt full" \
       -ex "info registers" \
       -ex "info threads" \
       build/<project>.elf
   ```
6. 检查外设状态：`decode <PERIPH>.<REG>`
7. 读取栈指针附近的内存
8. `python3 agentic/esp_target.py resume`

## OpenOCD Tcl 接口

`raw` 命令暴露完整的 OpenOCD 命令词汇：

```
python3 agentic/esp_target.py raw "targets"
python3 agentic/esp_target.py raw "flash info 0"
```

Tcl 接口是完整的 Tcl 解释器。需要重复查询硬件状态时（采样 GPIO、
探测多个寄存器），用 Tcl 脚本比多次调用 `read` 快得多：

```bash
python3 agentic/esp_target.py raw "set val [mdw 0x60004000 1]; return \$val"
```

可以使用循环、`after` 延迟，并在返回前聚合输出。调用者只能看到
脚本的返回值，不要在 Tcl 脚本中 print 到 stdout。

## ESP-IDF apptrace（替代日志方式）

apptrace 可将所有 `ESP_LOGx` 输出通过 JTAG 重定向。与 RTT 互补——
RTT 用于持续的 agentic 日志，apptrace 用于诊断捕获会话。

### 启用 apptrace

1. `idf.py menuconfig` →
   `Component config → Application Level Tracing → Data Destination 1` → `JTAG`
2. 固件中：
   ```c
   #include "esp_app_trace.h"
   esp_log_set_vprintf(esp_apptrace_vprintf);
   ```
3. 低速率日志需显式刷新：
   ```c
   esp_apptrace_flush(ESP_APPTRACE_DEST_JTAG, 1000);
   ```

### 捕获和解码

```
python3 agentic/esp_target.py raw "reset run"
# 等待 2 秒
python3 agentic/esp_target.py raw "esp apptrace start file:///tmp/apptrace.log 1 -1 30 0"
```

解码：
```
python3 $IDF_PATH/tools/esp_app_trace/logtrace_proc.py /tmp/apptrace.log build/<project>.elf
```

### 关键限制

`esp apptrace start` **阻塞 OpenOCD 事件循环**。捕获期间
esp_target.py 和 rtt_reader.py 无法通信。仅作诊断捕获会话使用，
不适合持续开发循环。

| | RTT | apptrace |
|---|---|---|
| 日志来源 | 显式 SEGGER_RTT_printf() | 所有 ESP_LOGx 自动 |
| 输出格式 | 纯文本，即时 | 二进制，需解码 |
| 持续流式 | 是 | 否（定时窗口） |
| 阻塞 OpenOCD | 否 | 是 |
| 最适合 | agentic 开发循环 | 深度 ESP-IDF 诊断 |

## 为新固件添加 RTT

完整 RTT 源码已包含在 `agentic/` 目录中，`SEGGER_RTT_Conf.h` 已添加
RISC-V 和 Xtensa 中断锁定支持，无需另行下载。

步骤：

1. 将 4 个 RTT 文件复制到 `main/`：
   ```bash
   cp agentic/SEGGER_RTT.c agentic/SEGGER_RTT.h agentic/SEGGER_RTT_printf.c agentic/SEGGER_RTT_Conf.h main/
   ```
2. 在 `main/CMakeLists.txt` 中注册：
   ```cmake
   idf_component_register(SRCS "SEGGER_RTT.c" "SEGGER_RTT_printf.c" "app_main.c"
                          PRIV_REQUIRES spi_flash
                          INCLUDE_DIRS ".")
   ```
3. `SEGGER_RTT_Conf.h` 包含架构相关的中断锁宏。RISC-V 目标使用
   `csrrci`/`csrw` 操作 `mstatus` MIE 位，由 `#if defined(__riscv)`
   保护；Xtensa 目标使用 `rsil`/`wsr.ps` 保存并恢复处理器状态。
4. 在应用代码中：
   ```c
   #include "SEGGER_RTT.h"

   void app_main(void) {
       SEGGER_RTT_WriteString(0, "Boot complete\n");
       while (1) {
           SEGGER_RTT_printf(0, "tick %d\n", counter++);
           vTaskDelay(pdMS_TO_TICKS(1000));
       }
   }
   ```
