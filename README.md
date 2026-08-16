# esp32-agent

面向 Claude Code 和 Codex 的 ESP-IDF 硬件开发 Skill 与工具链。让 Agent 完成编辑、编译、烧录、RTT 日志、寄存器检查和 GDB 调试闭环。

支持 Linux、macOS 和 Windows ESP-IDF 终端，覆盖 ESP32-C3、C6、H2、S3 和 P4。

## 一条命令安装

在 Bash、Git Bash 或 ESP-IDF 终端中执行：

```bash
curl -fsSL https://raw.githubusercontent.com/XDL1234/esp32-agent/main/install.sh | bash
```

安装器会：

- 安装 `esp32-agent` 命令到 `~/.local/bin/`
- 将同一个 `esp32-agent` Skill 安装到 `~/.claude/skills/` 和 `~/.codex/skills/`
- 将运行时仓库安装到 `~/.local/share/esp32-agent/repo/`
- 保留已有的同名非托管 Skill，并先创建带时间戳的备份

确保 `~/.local/bin` 在 `PATH` 中，然后重启 Claude Code 或 Codex 以加载 Skill。

## 初始化 ESP-IDF 项目

进入项目目录：

```bash
cd my-esp-idf-project
esp32-agent init
```

也可以安装后立即初始化当前目录：

```bash
curl -fsSL https://raw.githubusercontent.com/XDL1234/esp32-agent/main/install.sh | bash -s -- --init
```

自动化或 CI 中使用非交互参数：

```bash
esp32-agent init --chip esp32c6 --flash jtag --board waveshare-esp32c6
```

初始化只部署当前芯片需要的工具、配置和 SVD，并向现有 `CLAUDE.md`、`AGENTS.md` 添加一个受标记管理的小段落，不覆盖用户已有内容或权限设置。

## 日常使用

```bash
esp32-agent doctor   # 检查 ESP-IDF、OpenOCD、Python 和项目配置
esp32-agent start    # 启动项目的 OpenOCD 会话
esp32-agent stop     # 停止当前项目会话
esp32-agent update   # 更新 CLI 和 Claude/Codex Skill
```

然后在 Claude Code 或 Codex 中直接描述任务，例如：

```text
检查这个 ESP32-C6 项目，修复 I2C 传感器读取问题，编译、烧录并用 RTT 验证。
```

Skill 会根据 ESP-IDF 与硬件开发任务自动触发，也可以从客户端的 Skill 列表中显式选择 `esp32-agent`。

## 核心能力

| 能力 | 实现 |
| --- | --- |
| 构建 | ESP-IDF / Ninja 增量构建 |
| 烧录 | OpenOCD JTAG 或 esptool 串口 |
| 日志 | SEGGER RTT，通过 OpenOCD 读取内存 |
| 调试 | GDB 批处理、CPU 寄存器、内存读写 |
| 外设检查 | SVD 感知的寄存器读取与位域解码 |
| 多芯片 | C3、C6、H2、S3、P4，RISC-V 与 Xtensa |
| Agent | Claude Code 与 Codex 使用同一份 Skill |

## 项目布局

```text
Skills/esp32-agent/   标准 Skill 源，Claude 与 Codex 共用
bin/esp32-agent       统一 CLI
install.sh            一键用户安装器
agentic/              OpenOCD、RTT、SVD 和目标控制工具
boards/               已知开发板描述与通用模板
templates/configs/    芯片配置模板
tests/                离线和硬件在环测试
```

初始化后的 ESP-IDF 项目只包含必要内容：

```text
project/
├── CLAUDE.md
├── AGENTS.md
└── agentic/
    ├── esp_target_config.json
    ├── board.md
    ├── esp_target.py
    ├── rtt_reader.py
    ├── svd_parser.py
    ├── esp-session-start.sh
    ├── esp-session-stop.sh
    ├── idf_build.sh
    └── chips/<selected-chip>.json + .svd
```

## 要求

- Python 3.8+
- ESP-IDF 5.0+
- ESP-IDF 附带的 Espressif OpenOCD
- 支持内置 USB-JTAG 的目标芯片及 USB 数据线
- Git；一键安装需要 `curl`

Windows 请在 ESP-IDF Terminal 或 Git Bash 中运行。详见 [Windows 配置](docs/windows-setup.md)。

## 安全边界

普通构建、用户要求的应用烧录、日志和只读诊断属于正常工作流。擦除 Flash、任意内存/寄存器写入、eFuse/安全配置、原始 OpenOCD Tcl 等操作必须在执行前获得明确确认。

## 来源与许可

本项目基于 [ccattuto/esp-agentic-dev](https://github.com/ccattuto/esp-agentic-dev) 扩展，项目代码采用 [MIT License](LICENSE)。SVD 与 SEGGER RTT 等内置第三方文件保留各自许可证，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

问题与贡献请使用 [GitHub Issues](https://github.com/XDL1234/esp32-agent/issues) 和 [CONTRIBUTING.md](CONTRIBUTING.md)。
