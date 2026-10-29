# Deterministic runtime diagnostics

`collect_diagnostics` and the single-pass LLM workflow share `RuleEngine`.
It recognizes reported errors in collected log/service excerpts and pasted notes,
then returns a code, severity, source label, bounded evidence, explanation and
manual investigation guidance. Recognizing an error does not establish its cause,
prove a fault is still present, or validate the printer's physical configuration.

## Covered families

| Family | Recognized reports |
| --- | --- |
| MCU connection/communication | Unable to connect, lost/interrupted communication and MCU timeouts |
| MCU timing | Timer too close, rescheduled timer in the past and stepper too far in past |
| Homing communication | Communication timeout during homing |
| Config loading | Unable to open a config file, or an explicitly missing include |
| Sensor range | ADC out of range |
| Probe | BLTouch deployment/verification errors and generic probe failure reports; generic reports do not imply BLTouch hardware |
| Heater verification | Heater not heating at the expected rate; the named heater is retained |
| Homing/endstop | No trigger after full movement, or an endstop still triggered after retract; the named endstop/probe is retained |
| TMC drivers | Explicit driver error reports, UART register read/write failures and SPI register write failures; driver identity and register evidence are retained |
| MCU protocol compatibility | MCU Protocol error or an explicit command-format mismatch; versions/builds still need comparison |
| Motion limits | Move out of range, with the reported coordinates in the evidence |
| Homing state | Must home axis first, or must home before probe |
| Extrusion guards | Extrude below minimum temp, move exceeds maximum extrusion, or extrude-only move too long |
| Probe repeatability | Terminal samples_tolerance failure; a retry notice alone is not a failure |
| Services | Failed systemd state/result and repeated startup failures |

Active configuration placeholders are also checked when a config snapshot is
available. Deeper static include/pin/section checks belong to the separate
[Config Assistant](config-assistant.md).

Matched runtime families also receive deterministic manual recovery playbooks
with required evidence, ordered checks, verification and stop conditions. Uploaded
artifacts are checked before the first agent model call without fetching host logs.
See [intelligence quality](intelligence-quality.md).

## Evidence and limits

- Evidence positions are **collected excerpt lines**, never claimed to be original
  log-file lines. They include any collection metadata present in the artifact.
- Repeated findings are deduplicated by code, source label and named component.
  Separate affected heaters/drivers/endstops and separate sources remain visible.
- Matching is case-insensitive and stays within one line. Config-snippet artifacts,
  comment lines and marked Klipper config dumps are excluded from runtime matching.
  An unfinished config dump remains excluded through the end of that excerpt.
- A generic missing-file message is not enough to identify a missing config file.
  Normal heater/driver/status messages are not treated as faults. A bare protocol
  error is not enough to attribute a failure to MCU firmware compatibility.
- These are signature findings over bounded excerpts, not an incident timeline or
  an exhaustive parser of arbitrary quoted text. Findings can describe an older
  failure or a retry. Absence of a finding does not prove a healthy printer.
- The [shutdown investigator](shutdown-investigations.md) separately handles
  incident selection, pre-stop statistics and clock-qualified host correlation.

Guidance keeps heater protections and motion limits intact and calls for manual
version, configuration and physical checks. No printer writes, movement, heater
commands, service restarts or firmware flashing are performed by these rules.

## Source references and validation

Error wording reviewed against Klipper's primary sources on 2026-10-26:

- [Heater verification](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/verify_heater.py)
- [Homing/endstop errors](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/homing.py)
- [TMC error reports](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/tmc.py),
  [UART failures](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/tmc_uart.py)
  and [SPI failures](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/tmc2130.py)
- [MCU protocol reports](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/error_mcu.py)
  and [command-format validation](https://github.com/Klipper3d/klipper/blob/master/klippy/msgproto.py)
- [Motion errors](https://github.com/Klipper3d/klipper/blob/master/klippy/toolhead.py)
- [Config open/include errors and config dump markers](https://github.com/Klipper3d/klipper/blob/master/klippy/configfile.py)
- [BLTouch verification](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/bltouch.py)

`test_runtime_rules.py` covers reported and normal messages, source/evidence
positions, component identity, deduplication, ranking, bounded excerpts and false
positives. `test_rules.py` covers configuration placeholders. Workflow handoff
tests in `test_runtime_diagnostics.py` use automated collectors and scripted models;
they do not establish real printer diagnosis or live provider answer quality.
