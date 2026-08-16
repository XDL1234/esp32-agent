# Windows 配置指南（VSCode + ESP-IDF 扩展）

esp32-agent 通过 **VSCode ESP-IDF 扩展提供的内置 Git Bash 终端**
支持 Windows——大多数 Windows ESP-IDF 用户已经具备这个环境。无需额外安装，
无需 PowerShell 脚本，无需 WSL。

## 前置条件

1. **VSCode** — [https://code.visualstudio.com/](https://code.visualstudio.com/)
2. **ESP-IDF 扩展** — Marketplace ID `espressif.esp-idf-extension`。
   安装后运行一键快速安装；它会捆绑 Python、交叉编译器、OpenOCD 和 Git Bash。
3. **USB-JTAG 驱动** — 通常由 ESP-IDF 安装器自动安装。如果开发板未被识别，
   从 ESP-IDF PowerShell 运行 `Install-Espressif-USB-Drivers`。

## 打开正确的终端

扩展自带配置好的 Git Bash profile。在 VSCode 中：

- `查看 → 终端`（或 ``Ctrl+` ``）
- 点击 `+` 下拉菜单 → **ESP-IDF PowerShell** 或 **ESP-IDF Terminal**
- 或通过扩展命令 `ESP-IDF: Open ESP-IDF Terminal` 打开

在该终端中，以下变量已自动设置：

| 变量 | 用途 |
|---|---|
| `$IDF_PATH` | ESP-IDF 源码树 |
| `$IDF_PYTHON_ENV_PATH` | Python venv（含 `idf.py`、`esptool`、`pyserial`） |
| `PATH` | 包含 `openocd`、交叉编译器、`idf.py` |

**不需要**手动执行 `. $IDF_PATH/export.sh`——扩展已经导出了所有环境。

## 为什么需要 `idf_build.sh` 包装脚本

ESP-IDF ≥ 5.5 拒绝在 MSYS2 / Git Bash 下运行：它在启动时检查 `$MSYSTEM`
并直接退出。包装脚本在调用 `idf.py` 前移除该变量：

```bash
./agentic/idf_build.sh            # = idf.py build
./agentic/idf_build.sh menuconfig
./agentic/idf_build.sh clean
```

内部流程：

1. 定位 ESP-IDF venv Python（`IDF_PYTHON_ENV_PATH/Scripts/python.exe`）
2. 清除 `MSYSTEM` 和 `MSYS` 环境变量
3. 通过 `cygpath -w` 将 MINGW 风格路径（`/e/project`）转换为 Windows 格式
   （`E:\project`）
4. 通过 venv Python 调用 `idf.py`

在 Linux / macOS 上同一脚本是透明直通——可以无条件使用。

## Windows 上启动会话

```bash
./agentic/esp-session-start.sh
python3 agentic/esp_target.py health
```

启动脚本优先使用 `IDF_PYTHON_ENV_PATH/Scripts/python.exe`，
回退到系统 `python3` / `python`。

## 常见问题

- **"openocd: command not found"** — 你在普通 Git Bash 中，不是 ESP-IDF
  终端。通过扩展重新打开。
- **"bash: ./agentic/esp-session-start.sh: /bin/bash^M: bad interpreter"** —
  CRLF 换行符。如果你用 `core.autocrlf=true` 克隆的，执行
  `git config core.autocrlf input` 并重新克隆，或 `dos2unix agentic/*.sh`。
- **`esp_target.py flash` 卡住** — 挂起的 OpenOCD 占用了 USB 句柄。
  执行 `./agentic/esp-session-stop.sh` 后重启。
- **`rtt_reader.py --kill-existing` 没有清理旧进程** — 确认当前项目的
  `agentic/.esp-agent/rtt_reader.pid` 存在。工具只停止该 PID 且命令行为
  `rtt_reader.py` 的进程，不会按进程名全局清理。

## 与 Linux/macOS 的差异

| 功能 | Linux / macOS | Windows（Git Bash） |
|---|---|---|
| Shell | bash | Git Bash（MSYS2） |
| Python 守护进程化 | `os.fork()` | `DETACHED_PROCESS` 子进程 |
| OpenOCD 启动 | `nohup` + `disown` | Python `DETACHED_PROCESS` |
| 停止 OpenOCD | 校验项目 PID 后 `kill` | 校验项目 PID 后 `Stop-Process -Force` |
| 停止 RTT reader | 校验项目 PID 后 `SIGTERM` | 校验命令行后 `taskkill /F` |
| `idf.py` 调用 | 直接 | 通过 `idf_build.sh`（清除 `MSYSTEM`） |
| 串口自动检测 | `/dev/cu.usbmodem*` / `/dev/ttyUSB*` | `COM*`（通过 pyserial） |
| subprocess 编码 | UTF-8（默认） | `text=False` + 手动 UTF-8 解码 |
| USB 枚举等待 | ~3 秒 | ~5 秒（轮询 VID 0x303A） |

以上差异全部在内部处理——用户面对的命令在三个平台上完全一致。

## WSL2

WSL2 等同于 Linux。可以工作，但 USB 透传到 WSL 内核需要配置 `usbipd-win`。
对大多数用户来说，原生 VSCode + ESP-IDF 扩展路径更简单。
