# 配置模板

本目录下每个文件是 `esp_target_config.json` 的起始模板——每款芯片一个。
`esp32-agent init` 配置向导会自动选择并部署到你的项目中。

| 文件 | 芯片 | 架构 | 推荐烧录方式 |
|---|---|---|---|
| `esp32c3.json` | ESP32-C3 | RISC-V | JTAG |
| `esp32c6.json` | ESP32-C6 | RISC-V | JTAG |
| `esp32h2.json` | ESP32-H2 | RISC-V | JTAG |
| `esp32s3.json` | ESP32-S3 | Xtensa | JTAG |
| `esp32p4.json` | ESP32-P4 | RISC-V | 串口 |

所有芯片均内置 USB-Serial-JTAG 接口。烧录方式在配置向导中自主选择，
模板文件本身不包含 `flash.method`（由向导注入）。

## 选择烧录方式

- **JTAG** — 所有内置 USB-JTAG 的芯片。中小固件。OpenOCD 的
  `program_esp` 命令直接写入 Flash，开箱即用。
- **串口** — 大固件（> 1 MB 大致阈值），或 JTAG 烧录不稳定时
  （P4 尤其如此）。工具会停止 OpenOCD，调用 `esptool.py`，
  然后重启 OpenOCD。运行时状态（RTT / GDB / OpenOCD）会被保留。

详见 `docs/flash-methods.md`。
