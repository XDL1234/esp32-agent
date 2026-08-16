---
name: esp32-agent
description: Build, flash, inspect, monitor, and debug ESP-IDF firmware on ESP32-C3, ESP32-C6, ESP32-H2, ESP32-S3, and ESP32-P4 through OpenOCD, JTAG, serial flashing, RTT logs, GDB, memory access, and SVD-aware peripheral registers. Use when working in an ESP-IDF project, operating supported ESP32 hardware, diagnosing firmware or hardware behavior, reading board pin assignments, or continuing an esp32-agent development session.
---

# esp32-agent

Use the project-local `agentic/` tools to run a measured edit, build, flash, observe, and diagnose loop. Treat hardware state and command output as evidence; never claim a hardware result without checking it.

## Start

1. Confirm the current directory is an ESP-IDF project.
2. If `agentic/esp_target_config.json` is absent, ask the user to run `esp32-agent init` or run it when initialization is explicitly requested.
3. Read `agentic/esp_target_config.json` and `agentic/board.md` before writing board-specific code.
4. Run `esp32-agent doctor` before the first hardware operation in a session.
5. Start OpenOCD with `esp32-agent start` when target access is needed.

Read [workflow.md](references/workflow.md) for the development and diagnosis sequence. Read [tools.md](references/tools.md) only when exact CLI syntax is needed. Read [safety.md](references/safety.md) before any destructive or raw hardware operation.

## Work

- Build with `./agentic/idf_build.sh`; let ESP-IDF and Ninja decide whether the build is incremental.
- Flash with `python3 agentic/esp_target.py flash-and-run build/ --app-only` for normal iterations.
- Verify target state after flashing. A successful process exit without a responsive target is incomplete.
- Use RTT for continuous application logs and GDB or SVD register inspection for focused diagnosis.
- Re-read `agentic/board.md` before assigning GPIO, buses, power controls, sensors, LEDs, or buttons.
- Prefer ESP-IDF APIs and chip documentation over guessed addresses or constants.

## Safety

- Ask for explicit confirmation before flash erase, arbitrary memory/register writes, raw OpenOCD Tcl, fuse/security changes, or changes that can affect attached hardware.
- Do not use process-name-wide kill commands. Operate only on PIDs recorded under this project's `agentic/.esp-agent/` directory.
- Stop and report ambiguity when more than one matching serial device is connected.
- Preserve existing user source and agent instruction files during initialization.

## Finish

1. Build after source changes.
2. When hardware is available and the task requires it, flash and observe the device.
3. Report the exact checks performed, relevant output, and any verification that could not be run.
4. Leave the target running unless the task requires it halted; stop the session only when requested or no longer needed.
