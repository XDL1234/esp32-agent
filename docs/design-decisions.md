# 设计决策

本文档记录了 esp32-agent 关键设计选择的理由，包括在真实硬件上测试得到的经验教训。

## 架构

### 纯 JTAG，不用串口（上游设计）

上游项目的整个工作流通过 OpenOCD 的 JTAG 接口路由。串口在任何环节都不使用——
不用于烧录，不用于日志，不用于复位控制。这消除了一类可靠性问题：

- 串口设备路径不可预测地变化（`/dev/cu.usbmodemXXXX`）。
- 串口 bootloader 协议（esptool.py 使用）需要 DTR/RTS 翻转来进入下载模式，
  这很脆弱且依赖开发板。
- 自主 AI 助手无法从操作中途消失的串口中恢复。
- macOS 上的 CDC-ACM 有重连 bug、幽灵设备条目，以及每次芯片复位后数秒的
  枚举延迟。

JTAG 通过 OpenOCD 避免了所有这些问题。ESP32-C3 上的 USB-JTAG 链路与
CDC-ACM 串口共享同一物理 USB 连接，但 OpenOCD 的 `esp_usb_jtag` 驱动在
JTAG 协议层面管理重连，比操作系统级的 USB 设备生命周期稳健得多。

### 本项目的扩展：串口烧录回退

ESP32-P4 的 `program_esp`（JTAG 烧录）在 v3.1 芯片版本上不稳定——大固件
写入可能卡住或损坏。因此本项目添加了 `flash.method: "serial"` 选项：

- 烧录时停止 OpenOCD，调用 `esptool.py --after=hard_reset`
- esptool 硬复位芯片后，USB-JTAG 控制器断电重启
- 轮询 USB 设备重新出现（通常 3-6 秒），然后重启 OpenOCD
- **不再调用 `reset run`**——芯片已被 esptool 复位，固件已在运行
- 调试、日志、寄存器检查仍然走 JTAG——只有烧录走串口
- 自动检测 Espressif USB 设备（VID `0x303A`），无需手动指定端口

关键经验教训：ESP32-P4 的 USB-Serial-JTAG 共用一个 USB 接口，任何芯片复位
都会导致 USB 断开重连。OpenOCD 无法从这种断开中恢复（`failed to revive
USB device`），必须杀掉旧进程、等 USB 枚举完成后启动新实例。

### OpenOCD 作为单一控制点

所有与目标的交互——烧录、复位、内存访问、寄存器读取、日志捕获——都通过
OpenOCD。这给 AI 助手提供了单一、稳定的接口：

- `esp_target.py` 通过 Tcl 端口（:6666）发送命令
- `rtt_reader.py` 通过同一 Tcl 端口轮询内存（独立连接）
- GDB 通过 RSP 端口（:3333）进行符号级调试
- 三者可以并发操作——OpenOCD 内部序列化 JTAG 事务

替代方案——让不同工具通过不同接口与目标通信（esptool 走串口、GDB 走 JTAG、
监视器走串口）——会产生协调问题和故障模式，自主 AI 助手难以恢复。

### 配置分离：芯片 vs 项目

硬件参考数据（`chips/<chip>.json`）与工具配置（`esp_target_config.json`）
分离。芯片文件只包含芯片本身的事实——内存映射、架构、芯片名称。项目配置包含
此设置特有的一切——哪个 JTAG 探针、哪些端口、哪个 SVD 文件、哪个 GDB 可执行文件。

这意味着芯片配置可以跨项目共享并贡献回仓库，而项目配置保持本地可编辑。

### RTT 用于持续日志，apptrace 用于诊断

支持两种日志路径，各有不同的权衡：

**SEGGER RTT** 是 agentic 开发循环的主要日志机制。固件写入 RAM 中的共享内存
环形缓冲区。Python reader（`rtt_reader.py`）通过 OpenOCD 内存读取（`mdw`）
在自己的 Tcl 连接上轮询缓冲区。这意味着：

- 输出是纯文本，AI 助手可以立即读取。
- reader 不阻塞 OpenOCD——日志流式传输时 `esp_target.py` 正常工作。
- 无 ESP-IDF 依赖——RTT 在裸机或任何 RTOS 上都能工作。
- AI 助手可以在观察固件输出的同时读写内存、检查寄存器，全部并发。

**ESP-IDF apptrace** 通过重定向 vprintf 函数捕获所有 `ESP_LOGx` 输出
（包括内部 WiFi、BLE 和 RTOS 日志）。但是：

- `esp apptrace start` 阻塞 OpenOCD 事件循环——捕获期间其他工具无法与
  OpenOCD 通信。
- 输出是二进制格式，需要用 `logtrace_proc.py` 后处理。
- 低速率日志需要显式 `esp_apptrace_flush()` 调用，因为跟踪数据只在缓冲区
  填满时才对主机可见。
- 在 RISC-V 目标上，apptrace 握手在启动时触发——OpenOCD 必须已连接且目标
  必须复位才能注册调试桩。

apptrace 适用于需要查看 ESP-IDF 内部日志的深度诊断会话。其他场景 RTT 更好。

### Shell 接口而非 MCP

工具是通过 bash 调用的普通命令行程序，不是 MCP（Model Context Protocol）
服务器。这是刻意的选择：

- Shell 命令是通用的。任何能运行 bash 的 AI 助手——Claude Code、Cursor、
  Aider，或人类——都可以使用这些工具，无需额外集成。
- 工具可以直接调试。你可以在终端运行 `esp_target.py decode GPIO.OUT`，
  看到 AI 助手看到的完全相同的输出。
- 无需管理额外守护进程。OpenOCD 已经是一个持久进程；添加 MCP 服务器意味着
  两个长期运行的进程需要启动、监控和停止。
- CLAUDE.md 足以完成工具发现。AI 助手读取一次就知道所有可用命令、参数和
  输出格式。

MCP 在特定场景下有价值：同时管理多个目标（将命令路由到正确的目标）、将 RTT
输出作为结构化事件流式传输、或服务于无法执行 shell 命令的 AI 助手。如果需要，
MCP 服务器可以作为现有 CLI 工具的薄包装层添加——工具本身不变。

### `agentic/` 子目录布局（本项目扩展）

上游项目将工具放在项目根目录（扁平布局）。本项目将所有工具整合到 `agentic/`
子目录中：

- 不污染用户的 ESP-IDF 项目根目录
- 工具可以作为 git submodule 或直接复制引入
- `esp_target_config.json` 从脚本自身目录加载，无需用户指定路径
- 运行时状态（`.esp-agent/`）也在 `agentic/` 下，与项目源码隔离

## 实现细节

### 会话管理

OpenOCD 作为持久守护进程运行，在 AI 助手会话前启动一次。会话启动脚本从
`esp_target_config.json` 读取开发板配置和端口——不依赖固件已编译或 ELF
文件存在。RTT reader 在需要时单独启动，在含 RTT 支持的固件烧录后。

这种分离意味着你可以启动会话、首次编译固件、烧录，然后才启动日志捕获——
而不是要求会话开始前就有编译好的 ELF。

### 从 flasher_args.json 读取烧录偏移量

烧录偏移量（bootloader 在 0x0，分区表在 0x8000，app 在 0x10000）不是硬编码的。
工具读取 `build/flasher_args.json`，这是 ESP-IDF 构建系统生成的，反映项目中
配置的实际分区布局。即使使用自定义分区方案也能确保正确性。

### 使用 mww/mdw 而非 write_memory/read_memory

OpenOCD 有两套内存访问命令：旧版 `mww`/`mdw` 和新版 Tcl 原生
`write_memory`/`read_memory`。我们使用旧版命令，因为 `mww`/`mdw` 在 telnet
和 Tcl 接口中行为完全一致，且在 OpenOCD 各版本中稳定多年。

### 显式寄存器读取

OpenOCD 的 `reg` 命令列出所有寄存器名称但不从目标读取值。只有用
`reg <name>` 查询特定寄存器时才会获取值。`esp_target.py` 的 `regs` 命令
逐个显式读取每个核心寄存器和关键 CSR，而不是尝试解析 `reg` 列表输出。

### RTT 控制块发现

RTT reader 支持三种查找控制块的方法，按速度排序：

1. **直接地址**（`--address`）— 即时，用于地址已从上次会话中获知的情况。
2. **ELF 符号查找**（`--elf`）— 对 ELF 运行 `nm` 查找 `_SEGGER_RTT` 符号。
   即时，但需要 ELF 已编译。
3. **RAM 扫描**（默认）— 通过 `mdw` 分块读取 RAM，查找 `"SEGGER RTT"`
   魔术签名。慢但无需任何符号信息。

控制块地址在固件以不同静态变量布局重新编译时会改变，因此重新烧录后必须重启 reader。

### RISC-V 和 Xtensa RTT 中断屏蔽

SEGGER RTT 库的锁定宏默认使用 ARM 特定指令（PRIMASK/BASEPRI）。
修改后的 `SEGGER_RTT_Conf.h` 通过编译器预定义宏自动选择正确的锁实现：

- **RISC-V**（`#if defined(__riscv)`）：`csrrci`/`csrw` 操作 `mstatus` MIE 位，
  在环形缓冲区指针更新期间禁用/恢复中断。覆盖 ESP32-C3/C6/H2/P4。
- **Xtensa**（`#elif defined(__XTENSA__)`）：`rsil`/`wsr.ps` 将中断级别
  设为 15（屏蔽所有中断），操作完成后恢复原始 PS 寄存器值。覆盖 ESP32-S3。
- **ARM**：保留原有的 PRIMASK/BASEPRI 宏（非 ESP32 场景备用）。

无需手动配置——编译器根据目标架构自动选择。

### RTT 源码内置

完整的 SEGGER RTT 源码（`SEGGER_RTT.c`、`SEGGER_RTT.h`、
`SEGGER_RTT_printf.c`、`SEGGER_RTT_Conf.h`）内置在 `agentic/` 目录中。
这使得 AI 助手可以在用户要求监控固件输出时自动完成 RTT 集成：

1. 检测 `main/SEGGER_RTT.h` 是否存在
2. 如果不存在，从 `agentic/` 复制 4 个文件到 `main/`
3. 修改 `CMakeLists.txt` 注册源文件
4. 在固件中添加 RTT 输出代码

无需用户手动从 SEGGER 官网下载。RTT 源码基于 BSD-3-Clause 许可证，
允许重新分发。

### apptrace 刷新要求

ESP-IDF 的 apptrace 协议以固定大小的块向主机暴露跟踪数据。低吞吐量日志
（每秒几行）时，缓冲区永远不会填满，数据永远不会对 OpenOCD 的轮询器可见。
固件循环中需要显式 `esp_apptrace_flush()` 调用来强制传输。
