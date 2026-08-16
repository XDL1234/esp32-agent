# Hardware safety

## Require confirmation

Obtain explicit user confirmation immediately before:

- erasing all or part of flash;
- writing arbitrary memory, peripheral registers, or CPU registers;
- sending raw OpenOCD Tcl commands that mutate state;
- changing eFuses, secure boot, flash encryption, protection bits, clocking, or power control;
- modifying wiring-dependent GPIO without a trustworthy board description;
- stopping processes not proven to belong to the current project.

Normal compilation, application flashing requested by the user, target health checks, memory reads, register reads, and log capture are expected workflow operations.

## Validate scope

- Resolve the project root and configuration before starting a session.
- Match serial devices by a persistent configured port or unique serial number. If several candidates remain, stop and ask.
- Use only PID files under `agentic/.esp-agent/`; verify a PID before terminating it.
- Quote filesystem paths passed through Bash, Python subprocesses, and OpenOCD Tcl.

## Report failures

Return a nonzero status for failed hardware operations. Do not turn reconnect, reset, or target-health failure into a warning followed by success. Distinguish "firmware written" from "target rebooted and responsive" in results.
