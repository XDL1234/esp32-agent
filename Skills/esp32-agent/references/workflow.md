# Workflow

## Contents

- Project discovery
- Development loop
- Runtime logging
- Failure diagnosis
- Completion criteria

## Project discovery

1. Read `agentic/esp_target_config.json` to identify the chip, flash method, OpenOCD ports, and toolchain.
2. Read `agentic/board.md` for the actual board wiring and constraints. If it is still a generic template, do not invent pin assignments; ask for the board model or schematic.
3. Inspect the existing ESP-IDF components, `sdkconfig`, partition table, and build state before editing.
4. Run `esp32-agent doctor` and resolve missing ESP-IDF/OpenOCD prerequisites.

## Development loop

1. Make the smallest source change that addresses the task.
2. Run `./agentic/idf_build.sh`.
3. Start the target session with `esp32-agent start` if it is not already responsive.
4. Flash normal application changes with:

   ```bash
   python3 agentic/esp_target.py flash-and-run build/ --app-only
   ```

5. Check `python3 agentic/esp_target.py health` and `state`.
6. Observe RTT output or the relevant registers and compare the result with the expected behavior.
7. Diagnose from evidence, edit, and repeat.

Use a full flash when the bootloader, partition table, flash configuration, or other non-application artifacts changed.

## Runtime logging

Prefer an ELF symbol lookup over a full SRAM scan:

```bash
python3 agentic/rtt_reader.py --elf build/<project>.elf --scan-only
python3 agentic/rtt_reader.py --elf build/<project>.elf \
  --output agentic/.esp-agent/rtt.log --kill-existing --daemonize
```

Restart the reader after flashing because the RTT control block address can move. Read `agentic/.esp-agent/openocd.log` for transport problems and `agentic/.esp-agent/rtt.log` for firmware output.

## Failure diagnosis

1. Separate build, transport, flash, boot, and application failures.
2. Check OpenOCD health and logs before changing firmware for a transport failure.
3. For a crash or hang, inspect RTT panic output, halt the target, read CPU registers, and use GDB with the current ELF.
4. Use SVD-aware `decode` or `inspect` for peripheral state instead of guessing MMIO fields.
5. Resume the CPU after inspection unless keeping it halted is intentional.

## Completion criteria

A hardware task is complete only when the requested code builds and the relevant device behavior is observed. If hardware is unavailable, explicitly report that verification stopped after an offline build or static check.
