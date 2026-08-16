# 开发板：Waveshare ESP32-C6-LCD-1.47

微雪（Waveshare）出品的紧凑型开发板，搭载 ESP32-C6FH4 SoC，配备
1.47 英寸 172×320 TFT LCD（ST7789V3）、板载 WS2812B RGB LED、microSD 卡
槽（支持 SPI 和 4 位 SDIO 模式）、两个按键（RESET 和 BOOT），以及 USB-C 接口
用于供电/编程/调试。

## MCU

| 参数 | 值 |
|-----------|-------|
| 芯片 | ESP32-C6FH4 |
| HP 核心 | 32 位 RISC-V，最高 160 MHz，4 级流水线 |
| LP 核心 | 32 位 RISC-V，最高 20 MHz，2 级流水线 |
| Flash | 4 MB（Quad SPI，封装内集成） |
| HP SRAM | 512 KB |
| LP SRAM | 16 KB |
| 无线通信 | Wi-Fi 6 (802.11ax)、Bluetooth 5.3 LE、Zigbee 3.0、Thread 1.3 |
| 封装 | QFN32 (5×5 mm) |

## MCU 架构说明

### RISC-V 实现

ESP32-C6 拥有两个 RISC-V 核心。

**HP（高性能）CPU** — 主应用核心：
- 指令集：RV32IMACU（整数、乘除法、原子操作、压缩指令、用户模式）
- 4 级顺序标量流水线，最高 160 MHz
- 运行 ESP-IDF / FreeRTOS 应用代码

**LP（低功耗）CPU** — 在所有电源模式（包括深度睡眠）下均可用：
- 指令集：RV32IMC，最高 20 MHz，2 级流水线
- 独占访问 LP 外设（LP_UART、LP_I2C、LP_GPIO0–7）
- 在正常应用固件中不被 ESP-IDF 使用

### HP CPU 中缺失的标准 RISC-V 性能计数器 CSR

HP CPU **未**实现 Zicntr 扩展：

| CSR | 地址 | 状态 |
|-----|---------|--------|
| `mcycle` | 0xB00 | **未实现** — 触发非法指令异常 |
| `mcycleh` | 0xB80 | **未实现** — 触发非法指令异常 |
| `minstret` | 0xB02 | **未实现** — 触发非法指令异常 |
| `minstreth` | 0xB82 | **未实现** — 触发非法指令异常 |

### 非标准性能计数器 CSR

ESP32-C6 HP CPU 在 RISC-V 自定义 CSR 地址空间中提供了自定义性能计数器 CSR
（PULP/RI5CY 血统，与 ESP32-C3 地址相同）：

| CSR | 地址 | 描述 |
|-----|---------|-------------|
| `mpcer` | 0x7E0 | 机器性能计数器事件 — bit 0: CYCLE, bit 1: INST, bit 2: LD_HAZARD, bit 3: JMP_HAZARD, bit 4: IDLE, bit 5: LOAD, bit 6: STORE, bit 7: JMP_UNCOND, bit 8: BRANCH, bit 9: BRANCH_TAKEN, bit 10: INST_COMP |
| `mpcmr` | 0x7E1 | 机器性能计数器模式 — bit 0: COUNT_EN, bit 1: COUNT_SAT (0=回绕, 1=达到最大值时停止)。**复位值：0x3**（已启用，饱和模式） |
| `mpccr` | 0x7E2 | 机器性能计数器计数值 — 32 位可读写计数器 |

> **注意：** 只有**一个**计数器寄存器（`mpccr`，地址 0x7E2）。除非需要更改
> 计数事件，否则不需要初始化序列，因为 `mpcmr` 复位值为 0x3（已启用）。

### 固件中使用的 ESP-IDF API

在 ESP-IDF 应用代码中，使用标准的 CPU 计数器辅助函数：

```c
#include "esp_cpu.h"
#include "esp_private/esp_clk.h"

uint32_t start = esp_cpu_get_cycle_count();
/* ... 短代码段或忙等待 ... */
uint32_t elapsed_cycles = esp_cpu_get_cycle_count() - start;
uint32_t elapsed_us = elapsed_cycles / (esp_clk_cpu_freq() / 1000000U);
```

在 ESP32-C6 上，`esp_cpu_get_cycle_count()` 读取的是自定义 `mpccr` CSR（地址
0x7E2），而非 `mcycle`。这是在正常固件中对短代码路径计时和基于周期延迟的正确 API。

### 原始 CSR 访问

```c
/* 一次性初始化：选择周期作为计数事件并启用 */
__asm__ volatile ("csrwi 0x7E1, 0");   /* mpcmr: 配置时先禁用 */
__asm__ volatile ("csrwi 0x7E0, 1");   /* mpcer: 设置 bit 0 (CYCLE) */
__asm__ volatile ("csrwi 0x7E1, 1");   /* mpcmr: 全局启用 */

uint32_t t0, t1;
__asm__ volatile ("csrr %0, 0x7E2" : "=r"(t0));
/* ... 被测量的代码 ... */
__asm__ volatile ("csrr %0, 0x7E2" : "=r"(t1));
uint32_t cycles = t1 - t0;
```

`mpcer` 位映射：

| 位 | 字段 | 计数事件 |
|-----|-------|--------------|
| 0 | CYCLE | 时钟周期（WFI 期间不递增） |
| 1 | INST | 已退休指令数 |
| 2 | LD_HAZARD | 加载数据冒险停顿周期 |
| 3 | JMP_HAZARD | 跳转冒险停顿周期 |
| 4 | IDLE | 空闲周期 |
| 5 | LOAD | 加载指令 |
| 6 | STORE | 存储指令 |
| 7 | JMP_UNCOND | 无条件跳转 |
| 8 | BRANCH | 分支指令 |
| 9 | BRANCH_TAKEN | 已执行的分支 |
| 10 | INST_COMP | 压缩指令 |

这些 CSR 仅限机器模式访问，且不会在 FreeRTOS 上下文切换时被保存。

## 引脚分配

### 共享 SPI 总线（LCD + SD 卡）

GPIO6 和 GPIO7 构成一条由 LCD 和 SD 卡共享的 SPI 总线。
通过各自的片选线选择设备。

| 信号 | GPIO |
|--------|------|
| MOSI (LCD_DIN / SD_MOSI) | GPIO6 |
| CLK  (LCD_CLK / SD_SCLK) | GPIO7 |

### LCD（ST7789V3，4 线 SPI）

| 信号 | GPIO | 备注 |
|--------|------|-------|
| DIN (MOSI) | GPIO6 | 共享 SPI 总线 |
| CLK | GPIO7 | 共享 SPI 总线 |
| CS | GPIO14 | 低电平有效 |
| DC | GPIO15 | 低 = 命令，高 = 数据 |
| RST | GPIO21 | 低电平有效；与 SDIO_D1 冲突 |
| BL | GPIO22 | 通过 N-MOSFET Q1 控制背光；支持 PWM；与 SDIO_D2 冲突 |

### microSD 卡

**SPI 模式：**

| 信号 | GPIO | 备注 |
|--------|------|-------|
| MOSI | GPIO6 | 与 LCD_DIN 共享 |
| SCLK | GPIO7 | 与 LCD_CLK 共享 |
| MISO | GPIO5 | |
| CS | GPIO4 | |

**SDIO 4 位模式：**

| 信号 | GPIO | 备注 |
|--------|------|-------|
| SDIO_CMD | GPIO18 | |
| SDIO_CLK | GPIO19 | |
| SDIO_D0 | GPIO20 | |
| SDIO_D1 | GPIO21 | 与 LCD_RST 冲突 |
| SDIO_D2 | GPIO22 | 与 LCD_BL 冲突 |
| SDIO_D3 | GPIO23 | |

SDIO 模式与 LCD 不能同时使用：SDIO_D1/D2 与 LCD_RST (GPIO21) 和
LCD_BL (GPIO22) 共享引脚。在 SD 卡以 4 位 SDIO 模式工作时，
LCD 不得被初始化或驱动。

### ADC

ESP32-C6 拥有一个 12 位 SAR ADC（ADC1），共 7 个通道。没有
ADC2，因此不存在 ADC 与 Wi-Fi 的冲突（与 ESP32-C3 不同，Wi-Fi 激活时
所有通道仍可使用）。

| GPIO | ADC 通道 | 备注 |
|------|-------------|-------|
| GPIO0 | ADC1_CH0 | 同时为 XTAL_32K_P（未安装 32 kHz 晶振） |
| GPIO1 | ADC1_CH1 | 同时为 XTAL_32K_N（未安装 32 kHz 晶振） |
| GPIO2 | ADC1_CH2 | |
| GPIO3 | ADC1_CH3 | |
| GPIO4 | ADC1_CH4 | SPI 模式下为 SD_CS；Strapping 引脚 (MTMS) |
| GPIO5 | ADC1_CH5 | SPI 模式下为 SD_MISO；Strapping 引脚 (MTDI) |
| GPIO6 | ADC1_CH6 | 专用于 SPI MOSI — 不可用于 ADC |

### 排针引出的 GPIO

| GPIO | ADC | LP GPIO | 备注 |
|------|-----|---------|-------|
| GPIO0 | ADC1_CH0 | LP_GPIO0 | 通用 |
| GPIO1 | ADC1_CH1 | LP_GPIO1 | 通用 |
| GPIO2 | ADC1_CH2 | LP_GPIO2 | 通用 |
| GPIO3 | ADC1_CH3 | LP_GPIO3 | 通用 |
| GPIO4 | ADC1_CH4 | LP_GPIO4 | SD_CS (SPI)；Strapping 引脚 (MTMS) |
| GPIO5 | ADC1_CH5 | LP_GPIO5 | SD_MISO (SPI)；Strapping 引脚 (MTDI) |
| GPIO9 | — | — | BOOT 按键 (Key2, 10 kΩ 上拉)；Strapping 引脚（启动模式） |
| GPIO16 | — | — | UART0 TXD |
| GPIO17 | — | — | UART0 RXD |
| GPIO18 | — | — | SDIO_CMD (SDIO 模式) |
| GPIO19 | — | — | SDIO_CLK (SDIO 模式) |
| GPIO20 | — | — | SDIO_D0 (SDIO 模式) |
| GPIO23 | — | — | SDIO_D3 (SDIO 模式) |

### 保留 / 未引出

| GPIO | 功能 | 备注 |
|------|----------|-------|
| GPIO6 | SPI MOSI | 共享 LCD_DIN / SD_MOSI — 不可通用 |
| GPIO7 | SPI CLK | 共享 LCD_CLK / SD_SCLK — 不可通用 |
| GPIO8 | WS2812B LED | 板载可寻址 RGB LED |
| GPIO12 | USB D− | USB Serial/JTAG — 请勿重新配置 |
| GPIO13 | USB D+ | USB Serial/JTAG — 请勿重新配置 |
| GPIO14 | LCD_CS | LCD 片选 |
| GPIO15 | LCD_DC | LCD 数据/命令 |
| GPIO21 | LCD_RST / SDIO_D1 | LCD 复位或 SDIO 4 位模式 |
| GPIO22 | LCD_BL / SDIO_D2 | LCD 背光或 SDIO 4 位模式 |
| GPIO10, GPIO11 | — | QFN32 封装中不存在 |

## LED

| GPIO | 类型 | 协议 | 备注 |
|------|------|----------|-------|
| GPIO8 | WS2812B-0807 | WS2812（单线，时序脉冲） | 可寻址 RGB。800 kHz。**字节顺序为 RGB（非 GRB）**：实际器件为兴光 XL-0807RGBC-WS2812B；其数据手册明确指定 R、G、B 通道顺序（"单线传输三通道 (RGB)"）。标准 WS2812B 使用 GRB — 此变体不同。发送 `{0xFF,0x00,0x00}` 为红色。参见 `$IDF_PATH/examples/peripherals/rmt/led_strip/` |

## 显示屏

### ST7789V3 TFT LCD — 1.47 英寸

| 参数 | 值 |
|-----------|-------|
| 模组型号 | LBS147TC-IF15 |
| 驱动 IC | ST7789V3 |
| 尺寸 | 1.47 英寸 |
| 分辨率 | 172 (H) × 320 (V) 像素 |
| 色深 | 262K 色（18 位，通过 SPI 以 RGB565 驱动） |
| 显示模式 | 常黑，透射式 |
| 像素排列 | RGB 垂直条纹 |
| 接口 | 4 线 SPI |
| 有效显示区域 | 17.39 mm (H) × 32.35 mm (V) |
| 像素间距 | 0.034 mm (H) × 0.101 mm (V) |
| 亮度 | 350 cd/m²（典型值） |
| 对比度 | 1000:1（典型值） |
| 可视角度 | 各方向 ≥ 80° |
| 背光 | 2 颗白色 LED 并联；Vf = 2.8–3.2 V，If = 40 mA 典型值 |
| 工作温度 | −20 °C 至 +70 °C |

#### SPI 信号连接

| LCD 信号 | GPIO | 描述 |
|------------|------|-------------|
| SCL (CLK) | GPIO7 | SPI 时钟 |
| SDA (DIN) | GPIO6 | SPI MOSI |
| CS | GPIO14 | 片选，低电平有效 |
| D/C (RS) | GPIO15 | 数据（高）/ 命令（低） |
| RES | GPIO21 | 复位，低电平有效 |
| LED (BL) | GPIO22 | 背光使能 |

#### SPI 时序约束

| 参数 | 最小值 | 备注 |
|-----------|-----|-------|
| SCL 写周期 | 16 ns | 最大写时钟 ≈ 62.5 MHz |
| SCL 高/低电平宽度 | 7 ns | |
| CS 建立/保持时间 | 15 ns | |
| D/CX 建立时间 | 10 ns | |

#### 背光电路

背光由 SI2302CDS N 沟道 MOSFET (Q1) 驱动：
- 栅极：GPIO22 → 1 kΩ (R9) → MOSFET 栅极
- 100 kΩ (R7) 下拉确保 GPIO 浮空时 LED 关闭
- 源极接 GND；漏极接 LED 阴极
- 支持通过 ESP32-C6 LEDC 外设在 GPIO22 上进行 PWM 亮度控制

#### ESP-IDF 驱动说明

使用 `esp_lcd` 组件配合 SPI 总线。ST7789V3 与 ST7789 寄存器兼容。
已确认可用的设置：

- `x_gap = 34`（34 像素水平偏移；面板使用 240 宽 GRAM 中的第 34–205 列）
- `y_gap = 0`（面板使用全部 320 行）
- `mirror_x = true`, `mirror_y = false` — 竖屏方向，y=0 在顶部（远离 USB 连接器一侧）
- `data_endian = LCD_RGB_DATA_ENDIAN_LITTLE` — **必需**：ESP32-C6 DMA 先发送每个 RGB565 字的低字节；不设置此项时 ST7789 默认大端序，所有颜色会错乱
- `invert_color = true` — 此常黑面板需要此设置以获得正确亮度
- `rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB`
- `bits_per_pixel = 16` (RGB565)
- 背光：GPIO22 高电平 = 开启（N-MOSFET 栅极，高电平有效）
- SPI 时钟：已测试最高约 40 MHz；面板规格允许最高约 62.5 MHz

参考：`$IDF_PATH/examples/peripherals/lcd/tjpgd/`

## Strapping 引脚

| 引脚 | 功能 | 复位时默认值 | 备注 |
|-----|----------|-----------------|-------|
| GPIO8 | 启动模式（与 GPIO9 配合）；ROM UART 打印控制 | 浮空 | 浮空或高电平 → SPI 启动 |
| GPIO9 | 启动模式（与 GPIO8 配合） | 上拉 (=1) | 高 → SPI 启动（正常）；低 → 下载启动；Key2 短接至 GND |
| GPIO15 | JTAG 信号源 | 浮空 | 低 → 选择 USB JTAG；板上无上拉 |
| MTMS (GPIO4) | SDIO 采样/驱动时钟沿 | 浮空 | 仅在复位时采样；之后可作为 GPIO4 自由使用 |
| MTDI (GPIO5) | SDIO 采样/驱动时钟沿 | 浮空 | 仅在复位时采样；之后可作为 GPIO5 自由使用 |

手动进入下载（烧录）模式：按住 Key2（GPIO9 接 GND）同时按下 Key1（RESET / CHIP_PU）。

## 电源

| 来源 | 电压 | 备注 |
|--------|---------|-------|
| USB-C | 5V 输入 | 编程、JTAG 和板卡供电 |
| 3.3V 电源轨 | 3.3V | ME6217C33M5G LDO 稳压器从 5V 降压 |

此板无锂电池连接器。

## USB

ESP32-C6 内置的 USB Serial/JTAG 控制器使用 GPIO12 (D−) 和
GPIO13 (D+)。USB-C 连接器提供：

- JTAG 调试（由 OpenOCD / `idf.py flash monitor` 使用）
- USB CDC-ACM 串口（辅助控制台，非 UART0）
- 5V 板卡供电

请勿重新配置 GPIO12 或 GPIO13。

## Flash

| 容量 | 类型 | 备注 |
|------|------|-------|
| 4 MB | Quad SPI（封装内集成） | 内存映射：0x42000000（指令）/ 0x3C000000（数据） |

## 按键

| 按键 | 信号 | GPIO | 备注 |
|--------|--------|------|-------|
| Key1 | RESET | CHIP_PU | 复位芯片；10 kΩ 上拉 (R4) 至 3.3V |
| Key2 | BOOT | GPIO9 | 上电时按住进入下载启动模式；10 kΩ 上拉 (R5) 至 3.3V |

## 板卡特定约束

- GPIO6 和 GPIO7 由 LCD 和 SD 卡共享 — 未经 CS 控制不要同时使用两个
  外设；这些引脚不可用于通用 GPIO
- GPIO8 硬连接至 WS2812B LED — 不可通用
- GPIO12/GPIO13 为 USB D−/D+ — 请勿重新配置
- GPIO14、GPIO15、GPIO21、GPIO22 专用于 LCD；复用需要
  禁用 LCD 驱动初始化
- SDIO 4 位模式 (GPIO18–GPIO23) 与 LCD_RST (GPIO21) 和
  LCD_BL (GPIO22) 冲突；SDIO 4 位传输期间 LCD 不得处于活动状态
- GPIO9 为 BOOT strapping 引脚 — 正常 SPI 启动时复位时必须为高电平
  （上拉，Key2 释放）
- GPIO4 (MTMS) 和 GPIO5 (MTDI) 为 strapping 引脚，复位时采样；
  启动期间应保持浮空或弱上拉
- GPIO15（JTAG 源选择）板上无上拉电阻；保持浮空以使用 USB JTAG（默认）
- 未安装 32 kHz 晶振；GPIO0/GPIO1 的 XTAL_32K_P/N 功能
  不可用 — 请勿使用
- GPIO10 和 GPIO11 在 QFN32 封装中不存在
- 此模组无 PSRAM
- PCB 天线位于板卡边缘 — 避免在其附近放置金属或接地平面
- 所有 ADC 通道 (GPIO0–GPIO6) 均在 ADC1 上；ESP32-C6 上 Wi-Fi 不会阻塞
  ADC1（此芯片无 ADC2）

## 参考资料

- [微雪 Wiki](https://www.waveshare.com/wiki/ESP32-C6-LCD-1.47)
- [ESP32-C6 数据手册](https://www.espressif.com/documentation/esp32-c6_datasheet_en.pdf)
- [ESP32-C6 技术参考手册（预发布 v0.3）](https://www.espressif.com/documentation/esp32-c6_technical_reference_manual_en.pdf)
- [ST7789V3 数据手册](https://www.waveshare.com/wiki/File:ST7789V3_SPEC_V1.0.pdf)
- [XL-0807RGBC-WS2812B 数据手册（兴光）](https://files.waveshare.com/wiki/ESP32-S3-Nano/XL-0807RGBC-WS2812B.pdf)
