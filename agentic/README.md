# SEGGER RTT 支持文件

本目录内置 `SEGGER_RTT.c`、`SEGGER_RTT.h`、`SEGGER_RTT_printf.c` 和修改过的
`SEGGER_RTT_Conf.h`，可以直接复制到 ESP-IDF 组件中使用，无需另行下载。

## SEGGER_RTT_Conf.h

这是 SEGGER RTT 库的配置头文件，添加了 RISC-V 和 Xtensa 中断锁定宏：
RISC-V 使用 `csrrci`/`csrw` 操作 `mstatus` MIE 位，Xtensa 使用
`rsil`/`wsr.ps` 保存并恢复处理器状态。

## 使用方法

将本目录中的 4 个 `SEGGER_RTT*` 文件复制到 ESP-IDF 项目的组件目录，并在
`CMakeLists.txt` 中注册 `SEGGER_RTT.c` 和 `SEGGER_RTT_printf.c`。

## 支持的架构

| 架构 | 锁定机制 | 状态 |
|---|---|---|
| RISC-V（ESP32-C3 / C6 / H2 / P4） | `csrrci`/`csrw` on `mstatus` MIE | 已验证 |
| Xtensa（ESP32 / S2 / S3） | `rsil`/`wsr.ps` on `PS` | 已实现 |
