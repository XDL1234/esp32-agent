# 贡献指南

感谢你的参与。本项目范围明确——让 AI 编程助手通过 JTAG 驱动 ESP32 开发——

但有几个高价值的贡献方向。

## 高价值贡献

1. **新芯片配置。** 添加 `agentic/chips/<chip>.json`（内存映射），
   放入对应 SVD 文件，并在 `templates/configs/` 中添加预设。
   参见 [docs/multi-chip-guide.md](docs/multi-chip-guide.md)。
2. **新开发板文件。** 添加 `boards/<board>.md`，包含引脚分配、
   LED、按键、总线和注意事项。参考
   `boards/esp32p4_function_ev_board.md` 的格式。
3. **实机测试报告。** 支持矩阵中标记为"否"的芯片需要确认。
   请提交 issue，注明芯片、开发板、主机操作系统，以及哪些功能正常/异常。
4. **示例项目。** 每个芯片一个最小 ESP-IDF 项目（含 RTT），
   放在 `examples/<chip>_<feature>/` 下。

## 基本规则

- **仅使用标准库**（Python 工具）。如需 `pyserial`，工具会自动回退到
  ESP-IDF venv Python——不要添加硬性运行时依赖。
- **跨平台。** 提交前应验证 Linux、macOS 和 Windows 相关路径。`os.fork()`
  仅限 Linux/macOS；Windows 使用
  现有的 `DETACHED_PROCESS` 分支作为参考。
- **不破坏兼容性。** 对 `esp_target_config.json` 的破坏性变更必须
  在 PR 描述和相关文档中提供迁移说明。
- **许可证。** MIT，继承自上游。新文件也应使用 MIT。
