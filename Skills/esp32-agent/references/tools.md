# Tool reference

## Session and environment

```bash
esp32-agent doctor
esp32-agent start
esp32-agent stop
python3 agentic/esp_target.py info
python3 agentic/esp_target.py health
```

## Build and flash

```bash
./agentic/idf_build.sh
python3 agentic/esp_target.py flash build/
python3 agentic/esp_target.py flash build/ --app-only
python3 agentic/esp_target.py flash-and-run build/ --app-only
```

The configured `flash.method` selects JTAG or serial internally. Read offsets and image names from `build/flasher_args.json`; do not hardcode them.

## Target state and CPU registers

```bash
python3 agentic/esp_target.py state
python3 agentic/esp_target.py halt
python3 agentic/esp_target.py cpu-regs
python3 agentic/esp_target.py cpu-reg pc
python3 agentic/esp_target.py resume
```

## Memory and peripherals

```bash
python3 agentic/esp_target.py memmap
python3 agentic/esp_target.py list-periph
python3 agentic/esp_target.py list-regs GPIO
python3 agentic/esp_target.py read-reg GPIO.OUT
python3 agentic/esp_target.py decode GPIO.OUT
python3 agentic/esp_target.py inspect GPIO
python3 agentic/esp_target.py read 0x60000000 4
```

Memory writes, register writes, CPU register writes, flash erase, and `raw` commands require explicit confirmation because they can alter the running target or persistent storage.

## GDB

Read the executable and port from `python3 agentic/esp_target.py info`, then use batch mode with the active ELF:

```bash
<gdb> -batch \
  -ex "set remotetimeout 10" \
  -ex "target remote :<port>" \
  -ex "bt full" \
  -ex "info registers" \
  -ex "info threads" \
  build/<project>.elf
```
