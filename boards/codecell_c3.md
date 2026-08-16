# 开发板：CodeCell C3（Microbots）

一款由 Microbots 推出的紧凑型（18.5 mm 宽）开发模块，搭载
ESP32-C3-MINI-1-N4。专为机器人、可穿戴设备和物联网应用设计。
板载光线/接近传感器、9 轴 IMU、锂电池充电电路，以及用于
供电/编程/调试的 USB-C 接口。

## MCU

| 参数 | 值 |
|-----------|-------|
| 模块 | ESP32-C3-MINI-1-N4 |
| 内核 | 32 位 RISC-V 单核，最高 160 MHz |
| Flash | 4 MB（SPI，封装内置） |
| SRAM | 400 KB |
| 无线 | Wi-Fi 802.11 b/g/n，蓝牙 5（LE） |

## MCU 架构说明

### RISC-V 实现

ESP32-C3 实现了 RV32IMC（整数、乘除法、压缩指令集）。
它**未**实现 Zicntr 扩展，因此标准性能监控 CSR 不可用：

| CSR | 地址 | 状态 |
|-----|---------|--------|
| `mcycle` | 0xB00 | **未实现** — 触发非法指令陷阱 |
| `mcycleh` | 0xB80 | **未实现** — 触发非法指令陷阱 |
| `minstret` | 0xB02 | **未实现** — 触发非法指令陷阱 |
| `minstreth` | 0xB82 | **未实现** — 触发非法指令陷阱 |

在 SiFive 及其他标准 RISC-V 内核上常见的 `csrr a0, mcycle` 代码，
在此芯片上会引发非法指令异常。

### 非标准性能计数器 CSR

ESP32-C3 提供了一组源自 PULP/RI5CY 架构的自定义 CSR，
可用于周期计数、指令计数及其他微架构事件：

| CSR | 地址 | 描述 |
|-----|---------|-------------|
| `mpcer` | 0x7E0 | 机器性能计数器事件 — 每个位启用一种事件类型；bit 0 = CYCLE，bit 1 = INST，bit 2 = LD_HAZARD，bit 3 = JMP_HAZARD，bit 4 = IDLE，bit 5 = LOAD，bit 6 = STORE，bit 7 = JMP_UNCOND，bit 8 = BRANCH，bit 9 = BRANCH_TAKEN，bit 10 = INST_COMP。可同时设置多个位，但即使多个已启用事件同时发生，计数器每周期仅递增 1 |
| `mpcmr` | 0x7E1 | 机器性能计数器模式 — bit 0：COUNT_EN（启用/禁用），bit 1：COUNT_SAT（0=回绕，1=达到最大值时停止）。**复位值：0x3**（已启用，饱和模式） |
| `mpccr` | 0x7E2 | 机器性能计数器计数值 — 32 位可读写计数器 |

> **注意：** 根据 ESP32-C3 TRM §1，只有**一个**计数器寄存器（`mpccr`，地址 0x7E2）。
> 访问地址 0x780–0x79F（有时出现在 PULP/RI5CY 文档中）会在此芯片上触发非法指令异常。
> 由于 `mpcmr` 复位值为 0x3（已启用），除非需要更改计数事件，否则无需初始化序列。

### 固件中使用的 ESP-IDF API

在 ESP-IDF 应用代码中，建议使用标准 CPU 计数器辅助函数，
而非手动编写 CSR 读取代码：

```c
#include "esp_cpu.h"
#include "esp_private/esp_clk.h"

uint32_t start = esp_cpu_get_cycle_count();
/* ... 短代码段或忙等待 ... */
uint32_t elapsed_cycles = esp_cpu_get_cycle_count() - start;
uint32_t elapsed_us = elapsed_cycles / (esp_clk_cpu_freq() / 1000000U);
```

在 ESP32-C3 上，`esp_cpu_get_cycle_count()` **不会**读取 `mcycle`。
ESP-IDF 将其路由到芯片的自定义性能计数器 CSR 路径，
因此这是在普通固件中对短代码路径计时和实现基于周期延迟的正确 API。

### 原始 CSR 背景

`mpcer` 位图（设置对应位以启用该事件的计数）：

| 位 | 字段 | 计数事件 |
|-----|-------|--------------|
| 0 | CYCLE | 时钟周期（WFI 期间不递增） |
| 1 | INST | 已退休指令 |
| 2 | LD_HAZARD | 加载数据冒险停顿周期 |
| 3 | JMP_HAZARD | 跳转冒险停顿周期 |
| 4 | IDLE | 空闲周期 |
| 5 | LOAD | 加载指令 |
| 6 | STORE | 存储指令 |
| 7 | JMP_UNCOND | 无条件跳转 |
| 8 | BRANCH | 分支指令 |
| 9 | BRANCH_TAKEN | 已执行的分支 |
| 10 | INST_COMP | 压缩指令 |

如果需要直接裸机 CSR 访问，可按如下方式配置和读取周期计数器：

```c
/* 一次性初始化：选择周期作为计数事件并启用 */
__asm__ volatile ("csrwi 0x7E1, 0");   /* mpcmr: 配置时先禁用 */
__asm__ volatile ("csrwi 0x7E0, 1");   /* mpcer: 设置 bit 0 (CYCLE) */
__asm__ volatile ("csrwi 0x7E1, 1");   /* mpcmr: 全局启用          */

/* 读取地址 0x7E2 (mpccr) 处的计数器 */
uint32_t t0, t1;
__asm__ volatile ("csrr %0, 0x7E2" : "=r"(t0));
/* ... 被测量的代码 ... */
__asm__ volatile ("csrr %0, 0x7E2" : "=r"(t1));
uint32_t cycles = t1 - t0;
```

注意：这些 CSR 仅限机器模式访问。用户模式代码无法访问，
且不会在 FreeRTOS 上下文切换时保存。

## 引脚分配

### I2C

| 总线 | SDA | SCL | 速率 | 连接的设备 |
|-----|-----|-----|-------|-------------------|
| I2C0 | GPIO8 | GPIO9 | 400 kHz | VCNL4040 (0x60)，BNO085 (0x4A) |

I2C 总线由板载传感器和排针共享。
连接外部设备时不要使用冲突的 I2C 地址。
如果使用板载传感器，总线配置是固定的。

### GPIO（排针引出）

| 引脚 | 标签 | ADC | PWM | 备注 |
|-----|-------|-----|-----|-------|
| GPIO1 | IO1 | ADC1_CH1 | 是 | 支持模拟输入 |
| GPIO2 | IO2 | ADC1_CH2 | 是 | 支持模拟输入；与充电状态共用（CHG，低电平有效）；Strapping 引脚 |
| GPIO3 | IO3 | ADC1_CH3 | 是 | 支持模拟输入；与电池电压监测共用（VBAT/2 分压器） |
| GPIO5 | IO5 | ADC2_CH0 | 是 | 通用 |
| GPIO6 | IO6 | — | 是 | 通用 |
| GPIO7 | IO7 | — | 是 | 通用 |
| GPIO8 | SDA | — | 是 | I2C 数据线；与板载传感器共用（2k 上拉） |
| GPIO9 | SCL | — | 是 | I2C 时钟线；与板载传感器共用（2k 上拉）；Strapping 引脚（启动模式） |

所有引出的 GPIO 均支持通过 ESP32-C3 的 LEDC 外设输出 PWM
（6 通道，可配置频率和分辨率）。

### 保留/未引出

| 引脚 | 功能 | 备注 |
|-----|----------|-------|
| GPIO0 | 未引出 | 连接至 ESP32-C3-MINI-1 模块内部；未路由到任何排针 |
| GPIO4 | 未引出 | 连接至 ESP32-C3-MINI-1 模块内部；未路由到任何排针 |
| GPIO10 | SK6805-EC10 LED | 板载可寻址 RGB LED（WS2812 协议） |
| GPIO18 | USB D- | USB Serial/JTAG — 请勿重新配置 |
| GPIO19 | USB D+ | USB Serial/JTAG — 请勿重新配置 |

## LED

| 引脚 | 类型 | 协议 | 备注 |
|-----|------|----------|-------|
| GPIO10 | SK6805-EC10 | WS2812（单线，时序脉冲） | 可寻址 RGB。24 位 GRB 颜色顺序，800 kHz。时序：`T0H=0.3 us`，`T0L=0.9 us`，`T1H=0.65 us`，`T1L=0.55 us`，复位低电平 `>= 80 us`（已验证 `100 us`）。驱动示例参见 `$IDF_PATH/examples/peripherals/rmt/led_strip/`。 |

此开发板没有简单的开关 LED。

## 板载传感器

### VCNL4040 — 光线和接近传感器

| 参数 | 值 |
|-----------|-------|
| I2C 地址 | 0x60 |
| 总线 | I2C0 (GPIO8/GPIO9) |
| 功能 | 16 位环境光检测，接近检测距离可达 20 cm |
| 数据手册 | [VCNL4040](https://www.vishay.com/docs/84274/vcnl4040.pdf) |

### BNO085 — 9 轴 IMU

| 参数 | 值 |
|-----------|-------|
| I2C 地址 | 0x4A |
| 总线 | I2C0 (GPIO8/GPIO9) |
| 功能 | 3 轴加速度计、陀螺仪、磁力计；板载传感器融合提供横滚/俯仰/偏航、活动分类、敲击检测、步数统计 |
| 数据手册 | [BNO085](https://www.ceva-ip.com/wp-content/uploads/BNO080_085-Datasheet.pdf) |

**I2C 驱动注意事项：** 使用旧版 `driver/i2c.h` API 并设置 `sda_pullup_en = GPIO_PULLUP_ENABLE` 和 `scl_pullup_en = GPIO_PULLUP_ENABLE`。较新的 `driver/i2c_master.h` API 的总线初始化序列可能会瞬间干扰 SDA/SCL，导致 BNO085 锁定到地址 0x4B 而非 0x4A。

## 电源

| 来源 | 电压 | 备注 |
|--------|---------|-------|
| USB-C | 5V | 同时用于编程和 JTAG 调试 |
| 锂电池 | 3.7V 标称 | 1.25 mm 间距 JST 连接器；可选 170 mAh 20C 电池 |
| 3.3V 输出 | 3.3V | NCP177 LDO，最大 500 mA |

电源管理由 BQ24232 芯片处理，具有动态电源路径控制 —
开发板可在充电时正常工作。默认锂电池充电电流为 90 mA。

## USB

开发板使用 ESP32-C3 内置的 USB Serial/JTAG 控制器，
连接在 GPIO18 (D-) 和 GPIO19 (D+) 上。单个 USB-C 接口提供：

- JTAG 调试（本框架使用）
- 串口 CDC-ACM（本框架未使用）
- 供电和电池充电

请勿重新配置 GPIO18/GPIO19 — 这将导致 JTAG 访问和 USB 充电均失效。

## Flash

| 容量 | 类型 | 备注 |
|------|------|-------|
| 4 MB | Quad SPI（封装内置） | 内存映射地址：0x3C000000（数据）/ 0x42000000（指令） |

## 按键

此开发板没有 BOOT 或 RESET 按键。ESP32-C3 通过 USB 自动进入启动模式。
如果固件进入崩溃循环，手动进入启动模式需要在重新连接 USB 时
将 SCL (GPIO9) 短接到 GND。

## 开发板特定约束

- GPIO0 和 GPIO4 未路由到任何排针 — 不可使用
- GPIO10 硬连接到 SK6805 LED — 不可用于通用用途
- GPIO18/GPIO19 为 USB 专用 — 不可用于通用用途
- GPIO8/GPIO9 由 I2C 排针和板载传感器共享 —
  外部 I2C 设备不得与地址 0x60 (VCNL4040)
  或 0x4A (BNO085) 冲突
- GPIO2 是 Strapping 引脚 — 避免重负载或大电容
- GPIO9 是 Strapping 引脚（启动模式选择） — 避免在启动时拉低，
  除非有意进入下载模式
- GPIO5 (ADC2_CH0) 在 Wi-Fi 激活时不能用于 ADC —
  在 Wi-Fi 应用中使用 GPIO1/GPIO2/GPIO3 (ADC1) 进行模拟读取
- SK6805 LED 由 VCC（充电器输出轨）供电，而非 3.3V —
  未连接 USB 或电池时 LED 可能无法工作
- 此模块无 PSRAM
- 无 RESET 按键 — 通过 RTC 看门狗或 `esp_restart()` 进行程序化复位
- PCB 天线位于板边缘 — 避免在其附近放置金属或接地平面

## 参考资料

- [产品页面](https://microbots.io/products/codecell)
- [原理图](https://github.com/microbotsio/CodeCell)
- [Arduino 库和示例](https://github.com/microbotsio/CodeCell)
- [教程](https://microbots.io/pages/learn-codecell)
- [I2C 通信指南](https://microbots.io/blogs/codecell/codecell-i2c-communication)
- [电路说明](https://microbots.io/blogs/codecell/understanding-codecell-circuitry)
