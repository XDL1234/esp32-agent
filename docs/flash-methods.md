# 烧录方式：JTAG vs 串口

`esp_target_config.json` 允许你选择固件镜像写入 Flash 的方式。两种方式共享同一个 `esp_target.py flash` 命令——只有底层传输不同。

```json
{
  "flash": {
    "method": "jtag" | "serial",
    ...
  }
}
```

## 简要结论

- **JTAG**（`method: "jtag"`）— 中小固件烧录快，零额外配置，在烧录时不会断开OpenOCD
- **串口**（`method: "serial"`）— 大固件必需，或 JTAG 烧录不稳定时使用，烧录时会断开OpenOCD，成功后自动重启OpenOCD

烧录方式在配置向导中自主选择，所有芯片均支持两种方式。

## 方式：`jtag`

使用 OpenOCD 的 `program_esp` 命令，通过现有 Tcl 连接执行。

**优点**

- 无需额外硬件或工具
- 不中断正在运行的 OpenOCD 会话
- `esp-session-start.sh` 成功后即可直接使用

**缺点**

- 速度受 JTAG 吞吐量限制——8 MB 固件明显慢于 esptool 的 USB CDC 路径
- 某些芯片/开发板（特别是 ESP32-P4 v3.1 版本）的 `program_esp` 支持不稳定；
  写入可能卡住或损坏

**配置：**

```json
{
  "flash": {
    "method": "jtag",
    "default_offsets": {
      "bootloader":       "0x0",
      "partition_table":  "0x8000",
      "application":      "0x10000"
    }
  }
}
```

实际偏移量从 `idf.py build` 生成的 `build/flasher_args.json` 读取；

`default_offsets` 仅作为回退。

## 方式：`serial`

使用 `esptool.py` 通过 USB CDC。工具执行流程：

1. 通过当前项目的 PID 文件停止 OpenOCD（Windows 用 PowerShell `Stop-Process`，Unix 用 `kill`）
2. 等待 1 秒（进程清理）
3. 自动检测 Espressif 设备（USB VID `0x303A`）——或使用
   `flash.serial.port` 中配置的端口
4. 调用 `esptool.py --before=default_reset --after=hard_reset write_flash`
   → 芯片进入下载模式 → 写入 flash → 硬复位 → 固件从 flash 启动
   → USB-JTAG 控制器随芯片复位断电重启
5. 轮询 USB 设备（VID `0x303A`）重新出现（通常 3-6 秒，最长 12 秒）
6. 等待 1 秒（USB 稳定）
7. 启动 OpenOCD（Windows 用 Python `DETACHED_PROCESS`，Unix 用 `nohup`）
8. 连接 OpenOCD Tcl 端口
9. `resume`（确保 CPU 在运行）

**关键约束**：串口烧录后**绝不调用 `reset run`**——芯片已被 esptool 硬复位，再次复位会导致 USB-JTAG 断开且 OpenOCD 无法恢复。串口烧录后 RTT reader 需要重启（控制块地址可能已改变）——`rtt_reader.py --kill-existing` 可以正确处理。

**优点**

- 多 MB 固件烧录速度快
- 稳定——esptool.py 在所有 ESP32 芯片上有多年生产使用经验
- 即使芯片没有内置 USB-JTAG，只要有串口桥接也能工作

**缺点**

- 短暂停止 OpenOCD（USB 重新枚举约 5-8 秒，总计约 20 秒开销）
- 需要 `pyserial`——工具会自动回退到 ESP-IDF venv Python（通常自动可用）

**配置：**

```json
{
  "flash": {
    "method": "serial",
    "serial": {
      "port":       "auto",
      "baud":       460800,
      "flash_mode": "dio",
      "flash_freq": "40m",
      "flash_size": "16MB"
    },
    "default_offsets": {
      "bootloader":       "0x2000",
      "partition_table":  "0x8000",
      "application":      "0x10000"
    }
  }
}
```

将 `port` 设为具体设备（如 macOS 上 `/dev/cu.usbmodem01`，Windows 上`COM5`）可跳过自动检测。

## 切换方式

随时可以通过编辑 `flash.method` 切换。无需其他更改；重新运行`esp_target.py flash` 即可使用新配置。

## 当 `esp_target.py info` 显示错误的方式

`info` 子命令报告解析后的配置：

```bash
python3 agentic/esp_target.py info
```

查看 `Flash method:` 行。如果显示 `jtag` 但你设置了 `serial`（或反之），请确认你编辑的是工具实际读取的配置文件——它从自身脚本目录加载`agentic/esp_target_config.json`。
