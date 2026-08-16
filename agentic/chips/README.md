# 芯片硬件描述

本目录下每个 JSON 文件描述一款特定微控制器的硬件。这些文件只包含芯片本身的
事实——内存映射、架构、芯片名称。不含工具配置，不含项目特定设置。

## 使用芯片配置

芯片配置通过 `esp_target_config.json` 引用：

```json
{
  "chip": "agentic/chips/esp32c3.json",
  ...
}
```

工具不需要直接指定芯片——它们读取项目配置并跟随引用。

## 添加新芯片

创建名为 `<chip>.json` 的 JSON 文件，结构如下：

```json
{
  "name": "ESP32-S3",
  "arch": "xtensa",
  "svd": "agentic/chips/esp32s3.svd",
  "memory": {
    "sram": {
      "start": "0x3FC88000",
      "size": "0x78000",
      "description": "Internal SRAM (data bus)"
    }
  }
}
```

### 必填字段

**`name`** — 人类可读的芯片名称。显示在 `esp_target.py health` 和
`esp_target.py info` 输出中。

**`arch`** — CPU 架构。工具用它选择 `regs` 命令的正确寄存器集。
当前值：`riscv32`、`xtensa`。

**`memory.sram`** — 数据总线可访问的主 SRAM 区域。必须有 `start`（十六进制
字符串）和 `size`（十六进制字符串）。`rtt_reader.py` 用它确定扫描 RTT
控制块的搜索范围，`esp_target.py memmap` 用它显示内存布局。

### 可选字段

**`svd`** — 指向芯片的 SVD 文件。从 https://github.com/espressif/svd 下载。
SVD 文件提供外设寄存器定义（含位域布局），启用 `esp_target.py decode` 和
`read-reg`。

### 可选内存区域

按需添加。每个区域需要 `start`、`size` 和 `description`。常见区域：

```json
{
  "memory": {
    "sram": { "start": "0x3FC88000", "size": "0x78000", "description": "Internal SRAM (data bus)" },
    "sram0_ibus": { "start": "0x40370000", "size": "0x8000", "description": "Internal SRAM 0 (instruction bus alias)" },
    "flash_dbus": { "start": "0x3C000000", "size": "0x2000000", "description": "Flash (data bus, memory-mapped, read-only)" },
    "peripherals": { "start": "0x60000000", "size": "0xD1000", "description": "Peripheral registers" }
  }
}
```

`sram*_ibus` 别名很重要——OpenOCD 内存读取必须使用数据总线地址，不能用
指令总线别名。在芯片配置中同时记录两者有助于避免这个错误。

### 信息来源

每款 ESP32 芯片的内存映射在其技术参考手册中，通常在第 1 章（系统和内存）。
Espressif 在 https://www.espressif.com/en/support/documents/technical-documents
发布这些文档。

关键章节：
- "Address Mapping" 或 "System Address Mapping" — 完整地址空间布局
- "Internal Memory" — SRAM 大小和数据/指令总线地址
- "Peripheral Registers" — 外设基地址范围

### 配套文件

**`esp_target_config.json`** — 引用开发板配置，添加工具设置（OpenOCD board
config、flash 命令、GDB 可执行文件、端口）。参见 `templates/configs/` 的结构。

**SVD 文件**（可选）— 从 https://github.com/espressif/svd 下载。

### 测试新芯片配置

验证内存映射显示正确：
```bash
python3 agentic/esp_target.py memmap
```

验证 SRAM 可访问（OpenOCD 运行且目标已连接）：
```bash
python3 agentic/esp_target.py read <sram_start_address> 4
```

验证 SVD 外设列表正常：
```bash
python3 agentic/esp_target.py list-periph
```

如果 RTT reader 能在 SRAM 中扫描到控制块，说明内存区域定义正确：
```bash
python3 agentic/rtt_reader.py --scan-only
```

## 现有芯片配置

| 文件 | 芯片 | 架构 | SRAM | 内置 USB-JTAG | 已测试 |
|------|------|------|------|--------------|--------|
| `esp32c3.json` | ESP32-C3 | RISC-V (RV32IMC) | 400KB | 是 | 是 |
| `esp32c6.json` | ESP32-C6 | RISC-V (RV32IMAC) | 512KB | 是 | 是 |
| `esp32h2.json` | ESP32-H2 | RISC-V (RV32IMAC) | 320KB | 是 | 否 |
| `esp32s3.json` | ESP32-S3 | Xtensa LX7（双核） | 512KB | 是 | 否 |
| `esp32p4.json` | ESP32-P4 | RISC-V (RV32IMAFC, 双核) | 768KB | 是 | 是 |
