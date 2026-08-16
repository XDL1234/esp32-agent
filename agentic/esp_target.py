#!/usr/bin/env python3
"""
esp_target.py — Chip-agnostic target control over OpenOCD Tcl interface.

Configuration is read from esp_target_config.json (tooling setup) which
references a chip JSON file (hardware description) and an SVD file
(peripheral register definitions).

No serial port. No GDB (except when explicitly invoked). Just JTAG.

Usage:
    python3 esp_target.py <command>
    python3 esp_target.py --config esp_target_config.json <command>

Examples:
    esp_target.py health
    esp_target.py flash-and-run build/ --app-only
    esp_target.py read-reg GPIO.OUT
    esp_target.py decode GPIO.OUT
    esp_target.py list-periph
    esp_target.py list-regs GPIO
    esp_target.py read 0x60004000 8
    esp_target.py raw "flash info 0"
"""

import socket
import json
import time
import sys
import os
import re
import subprocess
import argparse
from pathlib import Path
from typing import Optional

try:
    from svd_parser import SVDDevice, parse_svd, load_svd_cached
except ImportError:
    SVDDevice = None
    parse_svd = None
    load_svd_cached = None


# ── OpenOCD Tcl connection ────────────────────────────

class OpenOCDError(Exception):
    pass


def _tcl_word(value):
    """Escape one Tcl word without relying on shell or Tcl substitutions."""
    return re.sub(r'([\\ {}\[\]$;"\t\r\n])', r'\\\1', str(value))


class OpenOCDConnection:
    """Low-level OpenOCD Tcl interface."""

    TCL_DELIMITER = b'\x1a'

    def __init__(self, host='localhost', port=6666, timeout=10):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None

    def connect(self):
        # Quick probe first — fail in <1s if nothing is listening
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(2)
        try:
            probe.connect((self.host, self.port))
        except (ConnectionRefusedError, OSError, socket.timeout) as e:
            probe.close()
            raise OpenOCDError(
                f"Cannot connect to OpenOCD at {self.host}:{self.port} — "
                f"is OpenOCD running? ({e})"
            )
        probe.close()

        # Now do the real connection
        self.sock = socket.create_connection(
            (self.host, self.port), timeout=self.timeout
        )
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # Tcl port sends no banner — ready immediately

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    def command(self, cmd):
        """Send a command, return response string."""
        self.sock.sendall((cmd + '\x1a').encode())
        buf = b''
        while not buf.endswith(self.TCL_DELIMITER):
            chunk = self.sock.recv(4096)
            if not chunk:
                raise OpenOCDError("Connection closed")
            buf += chunk
        return buf[:-1].decode(errors='replace').strip()


# ── Configuration ─────────────────────────────────────

class ChipConfig:
    """Hardware description loaded from chip JSON (pure silicon reference)."""

    def __init__(self, config_path):
        with open(config_path) as f:
            self.data = json.load(f)

    @property
    def name(self):
        return self.data.get('name', 'Unknown')

    @property
    def arch(self):
        return self.data.get('arch', 'unknown')

    def memory_region(self, name):
        region = self.data.get('memory', {}).get(name)
        if region:
            return {
                'start': int(region['start'], 0),
                'size': int(region['size'], 0),
                'description': region.get('description', ''),
            }
        return None

    @property
    def sram(self):
        return self.memory_region('sram')

    @property
    def memory_map(self):
        return self.data.get('memory', {})


class ProjectConfig:
    """Tooling configuration loaded from esp_target_config.json.

    References a chip JSON and SVD file, and contains OpenOCD, GDB,
    flash, and logging settings specific to this project/setup.
    """

    def __init__(self, config_path):
        self.config_path = Path(config_path)
        self.config_dir = self.config_path.parent
        with open(config_path) as f:
            self.data = json.load(f)

        # Load chip config
        chip_path = self.config_dir / self.data.get('chip', '')
        if not chip_path.exists():
            raise FileNotFoundError(f"Chip config not found: {chip_path}")
        self.chip = ChipConfig(chip_path)

    @property
    def svd_path(self):
        svd = self.chip.data.get('svd')
        if svd:
            return self.config_dir / svd
        return None

    # OpenOCD settings
    @property
    def tcl_port(self):
        return self.data.get('openocd', {}).get('tcl_port', 6666)

    @property
    def gdb_port(self):
        return self.data.get('openocd', {}).get('gdb_port', 3333)

    @property
    def board_cfg(self):
        return self.data.get('openocd', {}).get('board_cfg', '')

    @property
    def flash_command(self):
        return self.data.get('openocd', {}).get('flash_command', 'program')

    # Toolchain settings
    @property
    def toolchain_prefix(self):
        return self.data.get('toolchain', {}).get('prefix', '')

    @property
    def gdb_executable(self):
        return self.data.get('gdb', {}).get('executable', f'{self.toolchain_prefix}gdb')

    @property
    def nm(self):
        return f'{self.toolchain_prefix}nm'

    @property
    def objdump(self):
        return f'{self.toolchain_prefix}objdump'

    @property
    def addr2line(self):
        return f'{self.toolchain_prefix}addr2line'

    # Flash settings
    @property
    def flash_offsets(self):
        offsets = self.data.get('flash', {}).get('default_offsets', {})
        return {k: int(v, 0) for k, v in offsets.items()}

    @property
    def platform(self):
        p = self.data.get('platform', '')
        if not p:
            p = 'windows' if sys.platform == 'win32' else ('macos' if sys.platform == 'darwin' else 'linux')
        return p

    @property
    def flash_method(self):
        return self.data.get('flash', {}).get('method', 'jtag')

    @property
    def flash_serial(self):
        return self.data.get('flash', {}).get('serial', {})

    # Logging settings
    @property
    def logging_method(self):
        return self.data.get('logging', {}).get('method', 'rtt')

    # RTT config derived from chip SRAM
    @property
    def rtt_search_start(self):
        sram = self.chip.sram
        return sram['start'] if sram else 0x20000000

    @property
    def rtt_search_size(self):
        sram = self.chip.sram
        return sram['size'] if sram else 0x10000


# ── Target controller ─────────────────────────────────

class Target:
    """High-level target control combining OpenOCD + project config + SVD."""

    def __init__(self, config: ProjectConfig, svd_device=None):
        self.config = config
        self.chip = config.chip
        self.svd = svd_device
        self.ocd = OpenOCDConnection(port=config.tcl_port)

    def connect(self):
        self.ocd.connect()

    def close(self):
        self.ocd.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    def command(self, cmd):
        return self.ocd.command(cmd)

    # ── Multi-core discovery ─────────────────────────

    def _parse_targets(self):
        """Parse OpenOCD 'targets' output, return list of core dicts."""
        resp = self.command('targets')
        cores = []
        for line in resp.splitlines():
            m = re.match(r'\s*(\d+)(\*)?\s+(\S+)\s+\S+\s+\S+\s+\S+\s+(\S+)', line)
            if m:
                cores.append({
                    'index': int(m.group(1)),
                    'selected': m.group(2) == '*',
                    'name': m.group(3),
                    'state': m.group(4),
                })
        return cores

    def _select_core(self, name):
        """Switch OpenOCD's current target to the named core."""
        self.command(f'targets {name}')

    # ── Target state ──────────────────────────────────

    def halt(self):
        cores = self._parse_targets()
        if len(cores) <= 1:
            return self.command('halt')
        results = []
        for c in cores:
            if c['state'] == 'unavailable':
                continue
            self._select_core(c['name'])
            resp = self.command('halt')
            results.append(f"{c['name']}: halted")
        if cores:
            self._select_core(cores[0]['name'])
        return '\n'.join(results) if results else ''

    def resume(self, addr=None):
        cores = self._parse_targets()
        if len(cores) <= 1:
            if addr is not None:
                return self.command(f'resume {addr:#x}')
            return self.command('resume')
        results = []
        for c in cores:
            if c['state'] == 'unavailable':
                continue
            self._select_core(c['name'])
            if addr is not None and c['selected']:
                self.command(f'resume {addr:#x}')
            else:
                self.command('resume')
            results.append(f"{c['name']}: resumed")
        if cores:
            self._select_core(cores[0]['name'])
        return '\n'.join(results) if results else ''

    def reset(self, mode='run'):
        try:
            return self.command(f'reset {mode}')
        except (OpenOCDError, OSError, socket.timeout, TimeoutError) as e:
            # On chips with USB-Serial-JTAG (P4, C3, C6, H2, S3), reset
            # disconnects USB. OpenOCD loses the device and the Tcl command
            # times out or the connection drops. Try to restart OpenOCD.
            print("[reset] USB-JTAG disconnected during reset, restarting OpenOCD...",
                  file=sys.stderr)
            self._restart_openocd()
            # Verify recovery succeeded
            if self.ocd.sock is None:
                raise OpenOCDError(
                    "reset caused USB-JTAG disconnect and OpenOCD could not recover. "
                    "Run './agentic/esp-session-start.sh' manually after USB re-enumerates."
                )
            return f'reset {mode} (OpenOCD restarted)'

    def state(self):
        cores = self._parse_targets()
        if len(cores) <= 1:
            if cores:
                return cores[0]['state']
            return 'unknown'
        return cores

    def wait_halt(self, timeout_s=5.0, poll_interval_s=0.05):
        """Wait until the target reports halted, or raise on timeout."""
        deadline = time.monotonic() + timeout_s
        last_state = 'unknown'

        while time.monotonic() < deadline:
            s = self.state()
            if isinstance(s, list):
                last_state = ', '.join(f"{c['name']}={c['state']}" for c in s)
                if all(c['state'] in ('halted', 'unavailable') for c in s):
                    return 'halted'
            else:
                last_state = s
                if s == 'halted':
                    return s
            time.sleep(poll_interval_s)

        raise OpenOCDError(
            f"Timed out waiting for target halt after {timeout_s:.3f}s "
            f"(last state: {last_state})"
        )

    # ── Raw memory access ─────────────────────────────

    _MD_CMD = {32: 'mdw', 16: 'mdh', 8: 'mdb'}
    _MW_CMD = {32: 'mww', 16: 'mwh', 8: 'mwb'}

    def read_memory(self, addr, count=1, width=32):
        cmd = self._MD_CMD.get(width)
        if cmd is None:
            raise OpenOCDError(f"Unsupported width: {width}")
        resp = self.command(f'{cmd} {addr:#x} {count}')
        values = []
        for line in resp.splitlines():
            if ':' in line:
                hex_part = line.split(':', 1)[1].strip()
                for token in hex_part.split():
                    try:
                        values.append(int(token, 16))
                    except ValueError:
                        pass
        if not values:
            raise OpenOCDError(f"Bad memory read: {resp}")
        return values

    def write_memory(self, addr, values, width=32):
        cmd = self._MW_CMD.get(width)
        if cmd is None:
            raise OpenOCDError(f"Unsupported width: {width}")
        if isinstance(values, int):
            values = [values]
        bytes_per = width // 8
        for i, val in enumerate(values):
            self.command(f'{cmd} {addr + i * bytes_per:#x} {val:#x}')

    def read_u32(self, addr):
        return self.read_memory(addr, 1, 32)[0]

    def write_u32(self, addr, value):
        return self.write_memory(addr, [value], 32)

    # ── CPU registers ─────────────────────────────────

    _RISCV_CORE_REGS = [
        'zero', 'ra', 'sp', 'gp', 'tp',
        't0', 't1', 't2',
        'fp', 's1',
        'a0', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7',
        's2', 's3', 's4', 's5', 's6', 's7', 's8', 's9', 's10', 's11',
        't3', 't4', 't5', 't6',
        'pc',
    ]

    _RISCV_CSRS = [
        'mstatus', 'mepc', 'mcause', 'mtval', 'mtvec',
    ]

    _XTENSA_CORE_REGS = [
        'pc', 'a0', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7',
        'a8', 'a9', 'a10', 'a11', 'a12', 'a13', 'a14', 'a15',
        'sar',
    ]

    _XTENSA_SPECIAL_REGS = [
        'ps', 'exccause', 'excvaddr', 'epc1', 'epc2', 'epc3',
        'eps2', 'eps3', 'depc', 'windowbase', 'windowstart',
    ]

    def _reg_names_for_arch(self, include_special=True):
        arch = self.chip.arch if self.chip else 'riscv32'
        if arch == 'xtensa':
            names = list(self._XTENSA_CORE_REGS)
            if include_special:
                names += self._XTENSA_SPECIAL_REGS
        else:
            names = list(self._RISCV_CORE_REGS)
            if include_special:
                names += self._RISCV_CSRS
        return names

    def read_registers(self, include_csrs=True, core=None):
        """Read CPU registers. Requires target to be halted.
        If core is specified, switches to that core first."""
        if core is not None:
            self._select_core(core)
        regs = {}
        reg_names = self._reg_names_for_arch(include_special=include_csrs)
        for name in reg_names:
            try:
                regs[name] = self.read_register(name)
            except OpenOCDError:
                pass
        return regs

    def read_all_cores_registers(self, include_csrs=True):
        """Read registers from all cores. Returns {core_name: {'state': ..., 'registers': ...}}."""
        cores = self._parse_targets()
        results = {}
        for c in cores:
            if c['state'] == 'unavailable':
                results[c['name']] = {'state': 'unavailable', 'registers': {}}
                continue
            self._select_core(c['name'])
            if c['state'] != 'halted':
                self.command('halt')
            regs = self.read_registers(include_csrs=include_csrs)
            results[c['name']] = {'state': c['state'], 'registers': regs}
        if cores:
            self._select_core(cores[0]['name'])
        return results

    def read_register(self, name):
        """Read a single CPU register by name. Requires target to be halted."""
        resp = self.command(f'reg {name}')
        m = re.search(r'(0x[0-9a-fA-F]+)', resp)
        if m:
            return int(m.group(1), 16)
        raise OpenOCDError(f"Could not read register {name}: {resp}")

    def write_register(self, name, value):
        """Write a single CPU register by name. Requires target to be halted."""
        resp = self.command(f'reg {name} {value:#x}')
        m = re.search(r'(0x[0-9a-fA-F]+)', resp)
        if m:
            return int(m.group(1), 16)
        raise OpenOCDError(f"Could not write register {name}: {resp}")

    # ── SVD-aware peripheral access ───────────────────

    def read_reg(self, path):
        """Read a peripheral register by SVD path: 'GPIO.OUT'."""
        if self.svd is None:
            raise OpenOCDError("No SVD loaded — cannot use symbolic register names")
        periph, reg, field, addr = self.svd.lookup(path)
        value = self.read_u32(addr)
        if field:
            return field.extract(value)
        return value

    def write_reg(self, path, value):
        """Write a peripheral register by SVD path: 'GPIO.OUT'."""
        if self.svd is None:
            raise OpenOCDError("No SVD loaded — cannot use symbolic register names")
        periph, reg, field, addr = self.svd.lookup(path)
        if field:
            if field.bit_width == 0:
                raise OpenOCDError(
                    f"Field '{field.name}' has bit_width=0; cannot write"
                )
            current = self.read_u32(addr)
            current &= ~field.mask
            current |= (value << field.bit_offset) & field.mask
            self.write_u32(addr, current)
        else:
            self.write_u32(addr, value)

    def decode_reg(self, path, value=None):
        """Read and decode a register into named fields."""
        if self.svd is None:
            raise OpenOCDError("No SVD loaded — cannot use symbolic register names")
        periph, reg, _, addr = self.svd.lookup(path)
        if value is None:
            value = self.read_u32(addr)
        return {
            'address': f"{addr:#010x}",
            'raw': f"{value:#010x}",
            'fields': reg.decode(value),
            'formatted': reg.format(value),
        }

    def inspect_peripheral(self, periph_name):
        """Read all registers of a peripheral."""
        if self.svd is None:
            raise OpenOCDError("No SVD loaded")
        periph = None
        for k, v in self.svd.peripherals.items():
            if k.upper() == periph_name.upper():
                periph = v
                break
        if periph is None:
            raise KeyError(f"No peripheral '{periph_name}'")

        results = {}
        for rname, reg in sorted(periph.registers.items(), key=lambda x: x[1].offset):
            addr = periph.base_address + reg.offset
            try:
                value = self.read_u32(addr)
                results[rname] = {
                    'address': f"{addr:#010x}",
                    'value': f"{value:#010x}",
                    'description': reg.description,
                }
            except OpenOCDError as e:
                results[rname] = {'error': str(e)}
        return results

    # ── Flash operations ──────────────────────────────

    def flash_binary(self, filepath, offset, verify=True):
        filepath = str(Path(filepath).resolve())
        cmd = f'{self.config.flash_command} {_tcl_word(filepath)} {offset:#x}'
        if verify:
            cmd += ' verify'
        # Flash can take a long time — temporarily extend socket timeout
        old_timeout = self.ocd.sock.gettimeout()
        self.ocd.sock.settimeout(max(old_timeout or 10, 300))
        try:
            resp = self.command(cmd)
        finally:
            self.ocd.sock.settimeout(old_timeout)
        if 'error' in resp.lower():
            raise OpenOCDError(f"Flash failed: {resp}")
        return resp

    def flash_project(self, build_dir, app_only=False):
        method = self.config.flash_method
        if method == 'serial':
            return self._flash_project_serial(build_dir, app_only=app_only)
        return self._flash_project_jtag(build_dir, app_only=app_only)

    def _wait_for_usb_device(self, timeout=15):
        """Poll until an Espressif USB device (VID 0x303A) appears, or timeout."""
        import time as _time
        start = _time.time()
        while _time.time() - start < timeout:
            try:
                ports = self._list_serial_ports()
                for _dev, vid, _desc in ports:
                    if vid == 0x303A:
                        return True
            except Exception:
                pass
            _time.sleep(0.5)
        return False

    def _stop_openocd_for_serial(self):
        """Stop OpenOCD to free USB for serial access. Returns True if it was running."""
        script_dir = Path(__file__).resolve().parent
        stop_sh = script_dir / 'esp-session-stop.sh'
        state_dir = script_dir / '.esp-agent'
        pid_file = state_dir / 'openocd.pid'

        was_running = False

        # Try graceful close via socket
        if self.ocd and self.ocd.sock is not None:
            was_running = True
            try:
                self.close()
            except Exception:
                pass

        # Always check PID file — socket may be dead but process alive
        if pid_file.exists():
            was_running = True
            if stop_sh.exists():
                subprocess.run(['bash', str(stop_sh)], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif was_running:
            raise OpenOCDError(
                "OpenOCD is connected but this project has no PID file; "
                "refusing to stop an unowned process"
            )

        if was_running:
            # Brief pause for process cleanup
            time.sleep(1)

        return was_running

    def _restart_openocd(self):
        """Restart OpenOCD after serial operation and reconnect."""
        script_dir = Path(__file__).resolve().parent
        start_sh = script_dir / 'esp-session-start.sh'
        if not start_sh.exists():
            raise OpenOCDError(
                "esp-session-start.sh not found; cannot restart OpenOCD"
            )
        print("[serial] Restarting OpenOCD...", file=sys.stderr)
        # esptool --after=hard_reset resets the chip → USB-JTAG re-enumerates.
        # Poll for the USB serial device, then wait extra for JTAG interface.
        usb_found = self._wait_for_usb_device(timeout=15)
        if not usb_found:
            raise OpenOCDError(
                "USB device not found after 15s; run "
                "'esp32-agent start' after USB re-enumerates"
            )
        # JTAG interface takes longer than serial to become ready
        print("[serial] Waiting for JTAG interface (3s)...", file=sys.stderr)
        time.sleep(3)
        for attempt in range(2):
            try:
                proc = subprocess.run(
                    ['bash', str(start_sh)], capture_output=True, text=False, timeout=45)
            except subprocess.TimeoutExpired:
                print(f"[serial] esp-session-start.sh timed out (attempt {attempt + 1}/2)",
                      file=sys.stderr)
                if attempt < 1:
                    time.sleep(3)
                continue
            if proc.returncode == 0:
                try:
                    self.connect()
                    print("[serial] OpenOCD reconnected", file=sys.stderr)
                    return True
                except Exception as e:
                    print(f"[serial] WARNING: OpenOCD reconnect failed: {e}",
                          file=sys.stderr)
            if attempt < 1:
                print(f"[serial] Retry 2/2 in 3s...", file=sys.stderr)
                time.sleep(3)
        raise OpenOCDError(
            "OpenOCD restart failed after 2 attempts; run 'esp32-agent start' "
            "after USB re-enumerates"
        )

    def _list_serial_ports(self):
        """Return [(device, vid, description)] using pyserial, falling back
        to IDF's venv python if system python lacks pyserial."""
        try:
            from serial.tools import list_ports
            return [(p.device, getattr(p, 'vid', None),
                     (p.description or '') + ' ' + (p.hwid or ''))
                    for p in list_ports.comports()]
        except ImportError:
            pass

        idf_python = os.environ.get('IDF_PYTHON_ENV_PATH')
        if idf_python:
            if self.config.platform == 'windows':
                py = Path(idf_python) / 'Scripts' / 'python.exe'
            else:
                py = Path(idf_python) / 'bin' / 'python'
            if py.exists():
                code = (
                    "import json\n"
                    "from serial.tools import list_ports\n"
                    "print(json.dumps([[p.device, p.vid, "
                    "(p.description or '') + ' ' + (p.hwid or '')] "
                    "for p in list_ports.comports()]))"
                )
                try:
                    out = subprocess.check_output([str(py), '-c', code],
                                                  text=False, timeout=10)
                    return json.loads(out.decode('utf-8', errors='replace').strip())
                except Exception:
                    pass

        raise OpenOCDError("pyserial not installed — cannot auto-detect port")

    def _detect_serial_port(self, preferred=None):
        """Return a serial port path. Prefer `preferred` if present; else
        auto-detect an Espressif device (VID 0x303A)."""
        ports = self._list_serial_ports()
        available = {dev for dev, _vid, _desc in ports}

        if preferred and preferred.lower() != 'auto' and preferred in available:
            return preferred

        # Prefer Espressif VID 0x303A, but never guess between devices.
        candidates = [dev for dev, vid, _desc in ports if vid == 0x303A]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise OpenOCDError(
                "Multiple Espressif devices found: "
                f"{', '.join(sorted(candidates))}. Set flash.serial.port explicitly."
            )

        # Fallback: description-based hints
        hints = ('USB', 'JTAG', 'CP210', 'CH340', 'FT232')
        candidates = [dev for dev, _vid, desc in ports
                      if any(h in desc.upper() for h in hints)]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise OpenOCDError(
                "Multiple serial devices match: "
                f"{', '.join(sorted(candidates))}. Set flash.serial.port explicitly."
            )

        raise OpenOCDError(
            f"No Espressif device found. Available ports: "
            f"{', '.join(sorted(available)) or '(none)'}"
        )

    def _flash_project_serial(self, build_dir, app_only=False):
        """Flash via esptool over USB serial (stops/starts OpenOCD)."""
        build_dir = Path(build_dir)
        serial_cfg = self.config.flash_serial
        port = self._detect_serial_port(serial_cfg.get('port'))
        baud = str(serial_cfg.get('baud', 460800))
        flash_mode = serial_cfg.get('flash_mode', 'dio')
        flash_freq = serial_cfg.get('flash_freq', '40m')
        flash_size = serial_cfg.get('flash_size', 'keep')
        chip = self.chip.data.get('name', 'auto').lower().replace('-', '')

        args_file = build_dir / 'flasher_args.json'
        parts = []
        if args_file.exists():
            with open(args_file) as f:
                args = json.load(f)
            if app_only:
                if 'app' in args:
                    info = args['app']
                    parts.append((info['offset'], str(build_dir / info['file'])))
            else:
                flash_files = args.get('flash_files', {})
                for offset, fname in flash_files.items():
                    parts.append((offset, str(build_dir / fname)))
        else:
            raise OpenOCDError(f"flasher_args.json not found in {build_dir}")

        ocd_was_running = self._stop_openocd_for_serial()

        idf_path = os.environ.get('IDF_PATH')
        if not idf_path:
            raise OpenOCDError("IDF_PATH not set — source export.sh first")
        esptool = Path(idf_path) / 'components' / 'esptool_py' / 'esptool' / 'esptool.py'

        idf_python = os.environ.get('IDF_PYTHON_ENV_PATH')
        if idf_python:
            if self.config.platform == 'windows':
                py = Path(idf_python) / 'Scripts' / 'python.exe'
            else:
                py = Path(idf_python) / 'bin' / 'python'
            py = str(py) if py.exists() else sys.executable
        else:
            py = sys.executable

        cmd = [py, str(esptool), '--chip', chip, '-p', port, '-b', baud,
               '--before=default_reset', '--after=hard_reset', 'write_flash',
               '--flash_mode', flash_mode, '--flash_freq', flash_freq,
               '--flash_size', flash_size]
        for offset, fname in parts:
            cmd.extend([offset, fname])

        results = []
        try:
            print(f"[flash] serial port: {port} @ {baud} baud", file=sys.stderr)
            proc = subprocess.run(cmd, capture_output=True, text=False, timeout=300)
            if proc.returncode != 0:
                stdout = proc.stdout.decode('utf-8', errors='replace')
                stderr = proc.stderr.decode('utf-8', errors='replace')
                raise OpenOCDError(f"esptool failed:\n{stdout}\n{stderr}")
            for offset, fname in parts:
                results.append((Path(fname).name, 'ok', f'written at {offset}'))
        finally:
            if ocd_was_running:
                self._restart_openocd()
        return results

    def _flash_project_jtag(self, build_dir, app_only=False):
        build_dir = Path(build_dir)
        args_file = build_dir / 'flasher_args.json'

        if args_file.exists():
            with open(args_file) as f:
                args = json.load(f)
        else:
            args = {}
            offsets = self.config.flash_offsets
            for part, offset_val in offsets.items():
                args[part] = {'offset': f'{offset_val:#x}'}

        results = []

        if not app_only:
            for part in ('bootloader', 'partition-table', 'partition_table'):
                if part in args:
                    info = args[part]
                    filepath = build_dir / info.get('file', f'{part}/{part.replace("-","_")}.bin')
                    if filepath.exists():
                        offset = int(info['offset'], 0) if isinstance(info['offset'], str) else info['offset']
                        resp = self.flash_binary(filepath, offset)
                        results.append((part, 'ok', resp))
                    else:
                        results.append((part, 'skipped', f'file not found: {filepath}'))

        if 'app' in args:
            app_info = args['app']
            filepath = build_dir / app_info['file']
            offset = int(app_info['offset'], 0) if isinstance(app_info['offset'], str) else app_info['offset']
        else:
            bins = list(build_dir.glob('*.bin'))
            if not bins:
                raise OpenOCDError(f"No .bin files found in {build_dir}")
            filepath = bins[0]
            offset = self.config.flash_offsets.get('application', 0x10000)

        resp = self.flash_binary(filepath, offset)
        results.append(('app', 'ok', resp))
        return results

    def erase_flash(self):
        method = self.config.flash_method
        if method == 'serial':
            return self._erase_flash_serial()
        return self._erase_flash_jtag()

    def _erase_flash_jtag(self):
        return self.command('flash erase_sector 0 0 last')

    def _erase_flash_serial(self):
        serial_cfg = self.config.flash_serial
        port = self._detect_serial_port(serial_cfg.get('port'))
        chip = self.chip.data.get('name', 'auto').lower().replace('-', '')

        idf_path = os.environ.get('IDF_PATH')
        if not idf_path:
            raise OpenOCDError("IDF_PATH not set — source export.sh first")
        esptool = Path(idf_path) / 'components' / 'esptool_py' / 'esptool' / 'esptool.py'

        idf_python = os.environ.get('IDF_PYTHON_ENV_PATH')
        if idf_python:
            if self.config.platform == 'windows':
                py = Path(idf_python) / 'Scripts' / 'python.exe'
            else:
                py = Path(idf_python) / 'bin' / 'python'
            py = str(py) if py.exists() else sys.executable
        else:
            py = sys.executable

        cmd = [py, str(esptool), '--chip', chip, '-p', port,
               '--before=default_reset', '--after=hard_reset', 'erase_flash']

        ocd_was_running = self._stop_openocd_for_serial()

        try:
            print(f"[erase] serial port: {port}", file=sys.stderr)
            proc = subprocess.run(cmd, capture_output=True, text=False, timeout=120)
            if proc.returncode != 0:
                stdout = proc.stdout.decode('utf-8', errors='replace')
                stderr = proc.stderr.decode('utf-8', errors='replace')
                raise OpenOCDError(f"esptool erase_flash failed:\n{stdout}\n{stderr}")
            result = "Flash erased successfully (serial)"
        finally:
            if ocd_was_running:
                self._restart_openocd()
        return result

    def erase_region(self, addr, length):
        return self.command(f'flash erase_address {addr:#x} {length:#x}')

    # ── Convenience ───────────────────────────────────

    def flash_and_run(self, build_dir, app_only=False, settle_time=2.0):
        """Flash firmware, reset the target, and wait for boot."""
        is_serial = self.config.flash_method == 'serial'
        results = self.flash_project(build_dir, app_only=app_only)
        if not is_serial:
            # JTAG flash doesn't reset the chip — do it explicitly
            try:
                self.reset('run')
            except Exception:
                pass
        else:
            # Serial flash uses --after=hard_reset, chip rebooted from flash.
            # OpenOCD reconnect may have halted the CPU — resume it.
            try:
                self.resume()
            except Exception:
                pass
        time.sleep(settle_time)
        try:
            state = self.state()
        except Exception:
            state = 'unknown (OpenOCD not connected)'
        return {
            'flash': [(p, s, r) for p, s, r in results],
            'state': state,
        }

    def health_check(self):
        try:
            cores = self._parse_targets()
            chip = self.chip.name
            svd = self.svd.name if self.svd else 'not loaded'
            if len(cores) <= 1:
                state = cores[0]['state'] if cores else 'unknown'
                return {'ok': True, 'state': state, 'chip': chip, 'svd': svd}
            states = {c['name']: c['state'] for c in cores}
            return {'ok': True, 'cores': len(cores), 'states': states,
                    'chip': chip, 'svd': svd}
        except Exception as e:
            return {'ok': False, 'error': str(e)}


# ── CLI ───────────────────────────────────────────────

CONFIG_FILENAME = 'esp_target_config.json'


def find_project_config(override_path=None):
    """Find esp_target_config.json in current dir or script dir."""
    if override_path:
        p = Path(override_path)
        if p.exists():
            return p
        print(f"Error: config not found: {p}", file=sys.stderr)
        sys.exit(1)

    for d in [Path('.'), Path(__file__).parent]:
        p = d / CONFIG_FILENAME
        if p.exists():
            return p

    print(f"Error: {CONFIG_FILENAME} not found in current directory.", file=sys.stderr)
    print(f"Create one or use --config to specify the path.", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='Target control over OpenOCD (chip-agnostic)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s health
  %(prog)s read-reg GPIO.OUT
  %(prog)s decode GPIO.OUT
  %(prog)s write-reg GPIO.OUT_W1TS 0x400
  %(prog)s list-periph
  %(prog)s list-regs GPIO
  %(prog)s inspect GPIO
  %(prog)s flash-and-run build/ --app-only
  %(prog)s read 0x60004000 8
  %(prog)s raw "targets"
        """
    )
    parser.add_argument('--config', default=None,
                        help=f'Config file (default: {CONFIG_FILENAME} in current dir)')
    parser.add_argument('--host', default='localhost', help='OpenOCD host')
    parser.add_argument('--ocd-timeout', type=float, default=None,
                        help='Override OpenOCD Tcl socket timeout in seconds (default: 10)')

    sub = parser.add_subparsers(dest='cmd')

    # Target state
    sub.add_parser('health', help='Check OpenOCD and target connectivity')
    sub.add_parser('state', help='Show target execution state')
    sub.add_parser('halt', help='Halt the CPU')
    sub.add_parser('resume', help='Resume CPU execution')
    p = sub.add_parser('wait-halt', help='Wait until the CPU halts')
    p.add_argument('--timeout', type=float, default=5.0, help='Timeout in seconds')
    p.add_argument('--poll-interval', type=float, default=0.05, help='Polling interval in seconds')
    p = sub.add_parser('reset', help='Reset the target')
    p.add_argument('mode', nargs='?', default='run', choices=['run', 'halt', 'init'])

    # SVD-aware register access
    p = sub.add_parser('read-reg', help='Read peripheral register (e.g. GPIO.OUT)')
    p.add_argument('path', help='PERIPHERAL.REGISTER[.FIELD]')

    p = sub.add_parser('write-reg', help='Write peripheral register')
    p.add_argument('path', help='PERIPHERAL.REGISTER[.FIELD]')
    p.add_argument('value', help='Value to write (hex or decimal)')

    p = sub.add_parser('decode', help='Read and decode register fields')
    p.add_argument('path', help='PERIPHERAL.REGISTER')

    p = sub.add_parser('inspect', help='Read all registers of a peripheral')
    p.add_argument('peripheral', help='Peripheral name (e.g. GPIO, UART0)')

    p = sub.add_parser('list-periph', help='List all peripherals from SVD')
    p = sub.add_parser('list-regs', help='List registers of a peripheral')
    p.add_argument('peripheral', help='Peripheral name')

    # Raw memory access
    p = sub.add_parser('read', help='Read memory (words, halfwords, or bytes)')
    p.add_argument('addr', help='Start address (hex)')
    p.add_argument('count', nargs='?', type=int, default=1, help='Word count')
    p.add_argument('--width', type=int, default=32, choices=[8, 16, 32])

    p = sub.add_parser('write', help='Write memory (words, halfwords, or bytes)')
    p.add_argument('addr', help='Address (hex)')
    p.add_argument('values', nargs='+', help='Value(s) to write (hex)')
    p.add_argument('--width', type=int, default=32, choices=[8, 16, 32])

    # CPU registers
    sub.add_parser('cpu-regs', aliases=['regs'], help='Dump CPU registers')
    p = sub.add_parser('cpu-reg', aliases=['reg'], help='Read a single CPU register')
    p.add_argument('name', help='Register name (e.g. pc, sp, mepc)')
    p = sub.add_parser('cpu-reg-write', help='Write a single CPU register')
    p.add_argument('name', help='Register name (e.g. pc, ra, a0)')
    p.add_argument('value', help='Value to write (hex or decimal)')

    # Flash
    p = sub.add_parser('flash', help='Flash firmware via JTAG')
    p.add_argument('build_dir', help='Build directory path')
    p.add_argument('--app-only', action='store_true')

    p = sub.add_parser('flash-and-run', help='Flash firmware, reset, and wait for boot')
    p.add_argument('build_dir', help='Build directory path')
    p.add_argument('--app-only', action='store_true')
    p.add_argument('--settle', type=float, default=2.0)

    sub.add_parser('erase', help='Erase entire flash')

    # Raw passthrough
    p = sub.add_parser('raw', help='Send raw OpenOCD command')
    p.add_argument('command', nargs='+')

    # Info
    sub.add_parser('memmap', help='Show chip memory map')
    sub.add_parser('info', help='Show project configuration')

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return

    # Load project config
    config_path = find_project_config(args.config)
    try:
        config = ProjectConfig(config_path)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        sys.exit(1)

    # Load SVD if available
    svd = None
    svd_path = config.svd_path
    if svd_path and svd_path.exists():
        if load_svd_cached is None:
            print(f"Warning: svd_parser.py not found, SVD features disabled", file=sys.stderr)
        else:
            try:
                svd = load_svd_cached(svd_path)
            except Exception as e:
                print(f"Warning: could not parse SVD: {e}", file=sys.stderr)

    # Commands that require SVD
    SVD_CMDS = {'list-periph', 'list-regs', 'read-reg', 'write-reg', 'decode', 'inspect'}
    if args.cmd in SVD_CMDS and svd is None:
        if svd_path and not svd_path.exists():
            print(f"Error: SVD file not found: {svd_path}", file=sys.stderr)
        else:
            print(f"Error: command '{args.cmd}' requires an SVD file.", file=sys.stderr)
            print(f"Set the 'svd' field in {config_path}", file=sys.stderr)
        sys.exit(1)

    # Offline commands (no OpenOCD needed)
    if args.cmd == 'memmap':
        print(f"Chip: {config.chip.name} ({config.chip.arch})")
        for region_name, region in config.chip.memory_map.items():
            start = region.get('start', '?')
            size = region.get('size', '?')
            desc = region.get('description', '')
            print(f"  {region_name:20s} {start} ({size})  {desc}")
        return

    if args.cmd == 'info':
        print(f"Config:       {config_path}")
        print(f"Chip:         {config.chip.name} ({config.chip.arch})")
        print(f"SVD:          {svd_path or 'not configured'}")
        print(f"Board config: {config.board_cfg}")
        print(f"Tcl port:     {config.tcl_port}")
        print(f"GDB port:     {config.gdb_port}")
        print(f"Toolchain:    {config.toolchain_prefix or '(system)'}")
        print(f"GDB:          {config.gdb_executable}")
        print(f"Flash cmd:    {config.flash_command}")
        print(f"Flash method: {config.flash_method}")
        if config.flash_method == 'serial':
            s = config.flash_serial
            print(f"Flash serial: port={s.get('port')} baud={s.get('baud', 460800)}")
        print(f"Logging:      {config.logging_method}")
        return

    if args.cmd == 'list-periph':
        for p in svd.list_peripherals():
            print(f"  {p['name']:20s} {p['base']}  ({p['registers']:3d} regs)  {p['description'][:60]}")
        return

    if args.cmd == 'list-regs':
        for r in svd.list_registers(args.peripheral):
            print(f"  {r['name']:30s} {r['address']}  {r['access']:12s}  {r['description'][:40]}")
        return

    # All remaining commands need OpenOCD
    target = Target(config, svd)
    target.ocd.host = args.host
    if args.ocd_timeout is not None:
        target.ocd.timeout = args.ocd_timeout
    try:
        target.connect()
    except OpenOCDError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        _dispatch(target, args)
    finally:
        target.close()


def _dispatch(target, args):
    """Route CLI command to target method."""

    if args.cmd == 'health':
        result = target.health_check()
        print(json.dumps(result, indent=2))

    elif args.cmd == 'state':
        s = target.state()
        if isinstance(s, list):
            for c in s:
                marker = '*' if c['selected'] else ' '
                print(f"  {marker} {c['name']}: {c['state']}")
        else:
            print(s)

    elif args.cmd == 'halt':
        resp = target.halt()
        if resp:
            print(resp)

    elif args.cmd == 'resume':
        resp = target.resume()
        if resp:
            print(resp)

    elif args.cmd == 'reset':
        print(target.reset(args.mode))

    elif args.cmd == 'wait-halt':
        try:
            print(target.wait_halt(args.timeout, args.poll_interval))
        except OpenOCDError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.cmd == 'read-reg':
        value = target.read_reg(args.path)
        print(f"{value:#010x}  ({value})")

    elif args.cmd == 'write-reg':
        val = int(args.value, 0)
        target.write_reg(args.path, val)
        readback = target.read_reg(args.path)
        print(f"Wrote {val:#010x}, readback: {readback:#010x}")

    elif args.cmd == 'decode':
        result = target.decode_reg(args.path)
        print(result['formatted'])

    elif args.cmd == 'inspect':
        results = target.inspect_peripheral(args.peripheral)
        for rname, info in results.items():
            if 'error' in info:
                print(f"  {rname:30s} ERROR: {info['error']}")
            else:
                print(f"  {rname:30s} {info['address']}  =  {info['value']}  {info['description'][:40]}")

    elif args.cmd == 'read':
        addr = int(args.addr, 0)
        vals = target.read_memory(addr, args.count, args.width)
        bytes_per = args.width // 8
        for i, v in enumerate(vals):
            fmt_width = args.width // 4 + 2
            print(f"  {addr + i * bytes_per:#010x}: {v:#0{fmt_width}x}")

    elif args.cmd == 'write':
        addr = int(args.addr, 0)
        vals = [int(v, 0) for v in args.values]
        target.write_memory(addr, vals, args.width)

    elif args.cmd in ('cpu-regs', 'regs'):
        cores = target._parse_targets()
        if len(cores) <= 1:
            regs = target.read_registers()
            if not regs:
                print("No registers returned. Is the target halted?", file=sys.stderr)
                print("Run: esp_target.py halt  (then retry)", file=sys.stderr)
            else:
                for name in target._reg_names_for_arch():
                    if name in regs:
                        print(f"  {name:12s} = {regs[name]:#010x}")
        else:
            all_regs = target.read_all_cores_registers()
            for core_name, data in all_regs.items():
                print(f"[{core_name}]")
                if data['state'] == 'unavailable':
                    print("  (unavailable)")
                elif not data['registers']:
                    print("  (no registers returned)")
                else:
                    for name in target._reg_names_for_arch():
                        if name in data['registers']:
                            print(f"  {name:12s} = {data['registers'][name]:#010x}")
                print()

    elif args.cmd in ('cpu-reg', 'reg'):
        try:
            val = target.read_register(args.name)
            print(f"  {args.name:12s} = {val:#010x}")
        except OpenOCDError as e:
            print(f"Error: {e}", file=sys.stderr)

    elif args.cmd == 'cpu-reg-write':
        try:
            val = target.write_register(args.name, int(args.value, 0))
            print(f"  {args.name:12s} = {val:#010x}")
        except OpenOCDError as e:
            print(f"Error: {e}", file=sys.stderr)

    elif args.cmd == 'flash':
        results = target.flash_project(args.build_dir, args.app_only)
        for part, status, resp in results:
            print(f"  {part}: {status}")

    elif args.cmd == 'flash-and-run':
        result = target.flash_and_run(
            args.build_dir, args.app_only, args.settle
        )
        for part, status, resp in result['flash']:
            print(f"  {part}: {status}")
        s = result['state']
        if isinstance(s, list):
            for c in s:
                print(f"  {c['name']}: {c['state']}")
        else:
            print(f"  state: {s}")

    elif args.cmd == 'erase':
        print(target.erase_flash())

    elif args.cmd == 'raw':
        print(target.command(' '.join(args.command)))


if __name__ == '__main__':
    main()
