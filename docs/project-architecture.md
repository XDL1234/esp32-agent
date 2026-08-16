# 项目架构与上游对比文档

## 概述

**esp32-agent** 是一个跨平台、多芯片的 ESP32 开发框架，专为 AI 编程助手设计。
Fork 自 [ccattuto/esp-agentic-dev](https://github.com/ccattuto/esp-agentic-dev)，
在其基础上进行了大量扩展。

---

## 与上游项目的对比

### 功能对比

| 特性 | 上游 esp-agentic-dev | 本项目 esp32-agent |
|------|---------------------|---------------------|
| 支持芯片 | C3 / C6 / S3（3 款） | C3 / C6 / H2 / S3 / **P4**（5 款） |
| 架构 | 仅 RISC-V | RISC-V + **Xtensa** |
| 烧录方式 | 仅 JTAG | JTAG + **串口（esptool）** |
| 擦除方式 | 仅 JTAG | JTAG + **串口** |
| 多核支持 | 无 | **运行时自动发现，逐核操作** |
| 平台 | Linux / macOS | Linux / macOS + **Windows** |
| RTT 源码 | 仅 Conf.h | **完整源码内置**（.c/.h/_printf.c/_Conf.h） |
| RTT 锁宏 | 仅 RISC-V | RISC-V + **Xtensa** |
| 目录布局 | 扁平（工具在根目录） | **`agentic/` 子目录**（不污染项目根） |
| 配置向导 | 无（手动复制） | **`esp32-agent init` 交互式向导** |
| Agent 集成 | Claude 指令模板 | **Claude Code 与 Codex 共用标准 Skill** |
| 进程管理 | Unix kill/pkill | Unix + **Windows PowerShell** |
| 编码兼容 | 默认（Linux UTF-8） | **Windows GBK 安全** |

### 结构对比

```
上游 esp-agentic-dev/                    本项目 esp32-agent/
├── tools/                               ├── agentic/              ← 重命名 + 扩展
│   ├── esp_target.py                    │   ├── esp_target.py     ← 多核/Xtensa/串口
│   ├── rtt_reader.py                    │   ├── rtt_reader.py     ← Windows 兼容
│   └── svd_parser.py                    │   ├── svd_parser.py
│                                        │   ├── SEGGER_RTT.c      ← 新增：完整 RTT 源码
│                                        │   ├── SEGGER_RTT.h
│                                        │   ├── SEGGER_RTT_printf.c
│                                        │   ├── SEGGER_RTT_Conf.h ← 新增 Xtensa 锁
│                                        │   ├── idf_build.sh      ← 新增：跨平台编译
│                                        │   ├── esp-session-start.sh ← 重写：多平台
│                                        │   ├── esp-session-stop.sh  ← 重写：PowerShell
│                                        │   └── chips/            ← 从根目录移入
├── chips/                               │       ├── esp32c3.json
│   ├── esp32c3.json                     │       ├── esp32c6.json
│   ├── esp32c6.json                     │       ├── esp32h2.json  ← 新增
│   └── esp32s3.json                     │       ├── esp32s3.json
│                                        │       ├── esp32p4.json  ← 新增
│                                        │       └── *.svd         ← SVD 内置
├── svd-main/svd/                        │
│   └── *.svd（独立子目录）              │
├── templates/                           ├── templates/
│   ├── CLAUDE.md                        │   └── configs/          ← 每芯片独立模板
│   ├── esp_target_config.json（单一）   │       ├── esp32c3.json
│   ├── esp-session-start.sh             │       ├── esp32c6.json
│   └── esp-session-stop.sh              │       ├── esp32h2.json
│                                        │       ├── esp32p4.json
│                                        │       └── esp32s3.json
├── rtt/                                 │
│   └── SEGGER_RTT_Conf.h               │
├── boards/                              ├── boards/
│   ├── codecell_c3.md                   │   ├── codecell_c3.md
│   └── waveshare_esp32c6.md             │   ├── waveshare_esp32c6.md
│                                        │   └── esp32p4_function_ev_board.md ← 新增
├── .claude/settings.local.json          ├── Skills/esp32-agent/   ← Claude/Codex 共用
├── docs/                                ├── docs/                 ← 扩展
│   └── design-decisions.md              │   ├── design-decisions.md
│                                        │   ├── flash-methods.md  ← 新增
│                                        │   ├── multi-chip-guide.md ← 新增
│                                        │   └── windows-setup.md  ← 新增
├── examples/                            ├── examples/
│   └── codecellc3_hello_world/          │   └── esp32c3_hello_rtt/
├── slides/                              │
│   └── *.html                           │
│                                        ├── scripts/
│                                        │   └── setup.sh          ← 新增：配置脚本
│                                        ├── bin/esp32-agent       ← 新增：统一入口
│                                        ├── install.sh            ← 新增：一键安装
│                                        └── CONTRIBUTING.md       ← 新增
```

---

## 本项目目录结构详解

### 根目录

| 文件 | 用途 |
|------|------|
| `bin/esp32-agent` | **统一入口**。支持初始化、诊断、会话管理和更新 |
| `install.sh` | 将 CLI 和同一份 Skill 安装到 Claude Code 与 Codex |
| `README.md` | 项目说明、快速开始、支持矩阵 |
| `CONTRIBUTING.md` | 贡献指南 |
| `LICENSE` | MIT 许可证 |

### `agentic/` — 核心工具（部署到用户项目）

这是部署到用户 ESP-IDF 项目中的完整工具集。

| 文件 | 用途 | 依赖 |
|------|------|------|
| `esp_target.py` | **目标控制主工具**。烧录、复位、内存读写、寄存器检查、多核管理 | OpenOCD Tcl 端口 |
| `rtt_reader.py` | **RTT 日志守护进程**。通过 JTAG 内存轮询读取固件日志 | OpenOCD Tcl 端口 |
| `svd_parser.py` | SVD 文件解析器，提供按名称访问外设寄存器的能力 | 无（离线） |
| `esp-session-start.sh` | 启动 OpenOCD 守护进程，等待就绪，验证目标连接 | OpenOCD |
| `esp-session-stop.sh` | 停止 OpenOCD 和 rtt_reader，释放 USB | PowerShell (Win) / kill (Unix) |
| `idf_build.sh` | `idf.py` 跨平台包装脚本，绕过 Windows MSYSTEM 检查 | ESP-IDF |
| `SEGGER_RTT.c` | RTT 库核心实现（目标端） | 无 |
| `SEGGER_RTT.h` | RTT 库头文件 | 无 |
| `SEGGER_RTT_printf.c` | RTT printf 实现 | 无 |
| `SEGGER_RTT_Conf.h` | RTT 配置（含 RISC-V + Xtensa 中断锁宏） | 无 |

### `agentic/chips/` — 芯片硬件描述

| 文件 | 内容 |
|------|------|
| `esp32c3.json` | ESP32-C3 内存映射（SRAM、Flash、外设地址） |
| `esp32c6.json` | ESP32-C6 内存映射 |
| `esp32h2.json` | ESP32-H2 内存映射 |
| `esp32s3.json` | ESP32-S3 内存映射 |
| `esp32p4.json` | ESP32-P4 内存映射 |
| `*.svd` | 各芯片的 SVD 文件（外设寄存器定义），来自 espressif/svd |

芯片 JSON 只包含硅片本身的事实（架构、内存区域），不包含工具配置。

### `templates/` — 部署模板

| 文件 | 用途 |
|------|------|
| `configs/esp32*.json` | 每芯片的工具配置模板（OpenOCD 板级配置、端口、工具链前缀） |

配置模板不含 `flash.method`——该字段由配置向导根据用户选择注入。

### `boards/` — 开发板描述

| 文件 | 开发板 |
|------|--------|
| `codecell_c3.md` | CodeCell ESP32-C3 模块 |
| `waveshare_esp32c6.md` | Waveshare ESP32-C6 开发板 |
| `esp32p4_function_ev_board.md` | ESP32-P4-Function-EV-Board |

描述 GPIO 引脚分配、外设连接、LED、按钮等硬件信息。
部署时复制到用户项目的 `agentic/board.md`，用户根据实际硬件修改。

### `scripts/` — 安装脚本

| 文件 | 用途 |
|------|------|
| `setup.sh` | 兼容入口，转发到 `esp32-agent init` |

### `docs/` — 文档

| 文件 | 内容 |
|------|------|
| `design-decisions.md` | 架构设计决策和理由 |
| `flash-methods.md` | JTAG vs 串口烧录对比 |
| `multi-chip-guide.md` | 如何添加新芯片支持 |
| `windows-setup.md` | Windows VSCode ESP-IDF 终端配置 |

### `Skills/esp32-agent/` — Agent Skill

| 文件 | 用途 |
|------|------|
| `SKILL.md` | Claude Code 与 Codex 共用的核心工作流 |
| `agents/openai.yaml` | Codex UI 元数据 |
| `references/` | 按需加载的工作流、命令与安全规则 |

### `examples/` — 示例项目

| 目录 | 内容 |
|------|------|
| `esp32c3_hello_rtt/` | ESP32-C3 RTT Hello World 示例 |

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│  AI 编程助手（Claude Code / Codex / Cursor）                  │
│                                                             │
│  读取 Skill 与 CLAUDE.md/AGENTS.md → 了解命令和工作流           │
│  读取 board.md  → 了解硬件连接                               │
└──────────┬──────────────┬──────────────┬────────────────────┘
           │              │              │
     ┌─────▼─────┐ ┌─────▼─────┐ ┌─────▼─────┐
     │ idf_build │ │esp_target │ │rtt_reader │
     │   .sh     │ │   .py     │ │   .py     │
     └─────┬─────┘ └─────┬─────┘ └─────┬─────┘
           │              │              │
           │         ┌────▼────┐         │
           │         │ OpenOCD │◄────────┘
           │         │  Tcl    │
           │         │ :6666   │
           │         └────┬────┘
           │              │
     ┌─────▼─────┐  ┌────▼────┐
     │  ESP-IDF  │  │USB-JTAG │
     │  编译系统  │  │         │
     └───────────┘  └────┬────┘
                         │
                    ┌────▼────┐
                    │ ESP32   │
                    │ 目标MCU │
                    └─────────┘
```

### 数据流

1. **编译**：`idf_build.sh` → `idf.py build` → `build/` 目录
2. **烧录（JTAG）**：`esp_target.py flash` → OpenOCD `program_esp` → Flash
3. **烧录（串口）**：`esp_target.py flash` → 停 OpenOCD → `esptool.py --after=hard_reset` → 轮询 USB 枚举 → 重启 OpenOCD → resume
4. **调试**：`esp_target.py` → OpenOCD Tcl → JTAG → CPU halt/resume/寄存器
5. **日志**：`rtt_reader.py` → OpenOCD `mdw` → SRAM RTT 缓冲区 → `rtt.log`
6. **GDB**：`gdb -batch` → OpenOCD GDB RSP :3333 → 符号级调试

### 关键设计原则

1. **OpenOCD 是唯一的调试通道** — 所有硬件交互通过 Tcl 端口，无需 UART
2. **串口仅用于烧录** — 调试/日志/寄存器始终走 JTAG
3. **一根 USB 线** — 内置 USB-JTAG 芯片无需额外硬件
4. **运行时自动发现** — 多核数量、平台类型、串口设备均自动检测
5. **双端共用** — Claude Code 与 Codex 安装同一份 Skill，避免内容漂移

---

## 部署后的用户项目结构

运行 `esp32-agent init` 后，用户的 ESP-IDF 项目变为：

```
user-project/
├── CLAUDE.md                         ← AI 读取此文件了解所有命令
├── AGENTS.md                          ← Codex 等 Agent 的项目指令
├── agentic/                          ← 完整工具集
│   ├── esp_target_config.json        ← 含 platform/chip/flash 配置
│   ├── esp_target.py
│   ├── rtt_reader.py
│   ├── svd_parser.py
│   ├── esp-session-start.sh
│   ├── esp-session-stop.sh
│   ├── idf_build.sh
│   ├── SEGGER_RTT.c / .h / _printf.c / _Conf.h
│   ├── board.md                      ← 用户需修改
│   ├── chips/<chip>.json + .svd
│   └── .esp-agent/                   ← 运行时（会话启动后创建）
│       ├── openocd.pid
│       ├── openocd.log
│       └── rtt.log
├── main/                             ← 用户固件源码
├── CMakeLists.txt
├── sdkconfig
└── build/                            ← 编译输出
```

---

## ESP-IDF 版本兼容性

| ESP-IDF 版本 | 兼容性 | 说明 |
|---|---|---|
| 5.0+ | 配置支持 | C3/C6/H2/S3；具体能力取决于芯片与 OpenOCD 版本 |
| 5.3+ | 配置支持 | P4 |
| 5.5+ | 配置支持 | Windows MSYSTEM 检查由 `idf_build.sh` 处理 |

工具链不管理 ESP-IDF 版本，只读取 `$IDF_PATH` 指向的安装。
