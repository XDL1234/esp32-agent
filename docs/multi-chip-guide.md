# 多芯片指南

esp32-agent 支持以下 5 款内置 USB-JTAG 的芯片。本指南介绍如何选择芯片，以及如何添加新芯片。

## 支持矩阵

| 芯片 | 架构 | JSON | SVD | 已测试 |
| --- | --- | --- | --- | --- |
| ESP32-C3 | RISC-V | `esp32c3.json` | `esp32c3.svd` | **是** |
| ESP32-C6 | RISC-V | `esp32c6.json` | `esp32c6.svd` | **是** |
| ESP32-H2 | RISC-V | `esp32h2.json` | `esp32h2.svd` | 否 |
| ESP32-S3 | Xtensa LX7（双核） | `esp32s3.json` | `esp32s3.svd` | 否 |
| **ESP32-P4** | RISC-V（双核） | `esp32p4.json` | `esp32p4.svd` | **是** |

所有芯片均支持 JTAG 和串口两种烧录方式，在配置向导中自主选择。

**多核支持**：工具运行时从 OpenOCD 自动发现核心数量，无需配置。

多核开发板上 `state`/`halt`/`resume`/`cpu-regs` 会自动操作并显示所有核心。

额外的 SVD 文件（esp32.svd、esp32c2.svd、esp32s2.svd 等）保留在仓库中备用，

但对应芯片的完整配置尚未入库，欢迎社区贡献。

## 为新项目选择芯片

运行 `esp32-agent init`，向导会自动列出所有支持的芯片供选择。

无需手动复制配置文件。

如果你的芯片不在向导列表中，可手动复制架构最接近的配置模板并调整：

- RISC-V（C3 / C6 / H2 / P4）：工具链前缀 `riscv32-esp-elf-`
- Xtensa LX7（S3）：`xtensa-esp32s3-elf-`

## 添加新芯片

需要三个文件。

### 1. 芯片 JSON（`agentic/chips/<chip>.json`）

```json
{
  "name": "ESP32-<X>",
  "arch": "riscv32",
  "svd": "agentic/chips/esp32<x>.svd",
  "memory": {
    "sram": {
      "start": "0x...",
      "size":  "0x...",
      "description": "Internal SRAM (data bus)"
    }
  }
}
```

必填字段：

- `name` — 人类可读的芯片名称
- `arch` — `riscv32` 或 `xtensa`
- `memory.sram` — 数据总线可访问的主 SRAM 区域。`rtt_reader.py` 用它
  搜索控制块，`memmap` 用它显示内存布局。

建议添加的内存区域：

`flash_dbus`、`flash_ibus`、`sram*_ibus`、`peripherals`、`rtc`。

每款 ESP32 芯片的内存映射在其技术参考手册中——查找第 1 章的"Address Mapping" 或 "System Address Mapping"。

### 2. SVD 文件（`agentic/chips/<chip>.svd`）

从 [espressif/svd](https://github.com/espressif/svd) 获取：

```bash
curl -L -o agentic/chips/esp32<x>.svd \
    https://raw.githubusercontent.com/espressif/svd/main/svd/esp32<x>.svd
```

### 3. 配置模板（`templates/configs/esp32<x>.json`）

复制现有模板并编辑：

- `chip` → `chips/<your>.json`
- `openocd.board_cfg` → 例如 `board/esp32<x>-builtin.cfg`
- `toolchain.prefix` → 正确的交叉编译器前缀
- `gdb.executable` → 对应的 GDB 二进制名称

注意：模板中不包含 `flash.method`，该字段由配置向导根据用户选择自动注入。

### 测试新芯片配置

离线测试：

```bash
python3 agentic/esp_target.py memmap
python3 agentic/esp_target.py list-periph
```

连接硬件后：

```bash
./agentic/esp-session-start.sh
python3 agentic/esp_target.py health
python3 agentic/esp_target.py read <sram_start> 4
```

如果成功且已烧录含 RTT 的固件，reader 应能找到控制块：

```bash
python3 agentic/rtt_reader.py --scan-only
```

请提交 PR，附带你的配置文件并在上方支持矩阵中添加一行。
