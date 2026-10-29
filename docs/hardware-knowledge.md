# Hardware evidence, references and manual drafts

Printer knowledge now records source-reviewed bus pinmux, explicit physical
connector observations, exact-commit firmware references and page-scoped PDF
evidence. These features write only KlipperAI application storage. Printer
configuration and physical verification remain manual.

## Hardware buses and component diagnostics

Public component documents can supply quoted `BUS_PINS_<bus>=...` constants or
Klipper `DECL_CONSTANT_STR` declarations. The UI shows candidates and requires
review against the exact hardware and firmware variant. Conflicting definitions
remain unresolved. A review fingerprint includes source identity/content, MCU
assignment and connection; changing the selected firmware commit clears bus review.

For an explicitly named SPI/I2C bus with a matching MCU and reviewed source,
pin-ownership checks reserve its quoted pins. Omitted firmware-default buses,
unknown MCU assignments and unsupported declarations remain gaps. Software bus
pins continue to use explicit config pin/alias resolution. This is not a guessed
pinmux catalog or proof that a pin is physically available.

The read-only `inspect_component` tool supports these fixed families:

| Family | Evidence |
| --- | --- |
| Accelerometer | ADXL345, LIS2DW/LIS3DH, MPU9250, ICM20948 and resonance config; bus/axes/mounting checks |
| Probe | Generic probe, BLTouch, Eddy, mesh and safe homing config; state/offset/clearance checks |
| Driver | Supported TMC config/status objects; UART/SPI, current and documented fault-flag checks |
| Temperature | Configured sensors/heaters/thermistors and available status; ambient/range/wiring checks |
| Filament | Switch/motion sensor config/status; polarity, detection-length and macro-dependency checks |

The tool reads a complete bounded active tree and at most 12 matching status
objects. It never executes calibration, register commands, movements, heaters,
pauses or restarts. Absent live objects do not establish component health.

## Exact-commit firmware references

Optionally enter a public `https://github.com/owner/repository` URL and a complete
40-character commit in Printer knowledge, then Build/Refresh. The cache fetches
`docs/Config_Reference.md`, `docs/Command_Templates.md` and `docs/Config_Changes.md`
at that immutable commit. The documents are searchable with role `firmware` or
`all` and carry source hashes, dates and commit metadata. Commits are separate
cache identities; failures never fall back to a branch or newer documentation.

A live version containing a matching commit prefix is labeled as a prefix match.
It does not prove the repository/fork, MCU builds or command compatibility. Other
repository layouts and unavailable commits produce explicit reference gaps.

## PDF text and diagram index

PDF downloads retain the original and index readable page text, page locators,
diagram captions/labels and counts of image/form references and vector paths.
Search excerpts stay within a page and return page links, source digest and
visual-review flags. Image/form counts identify content to inspect; they are not
interpreted schematics. Image-only scans do not acquire invented text or pin maps.

After viewing the cached page, a user can explicitly confirm a short diagram
description/label note. Notes are bound to document ID, digest and page and are
searchable as user-confirmed observations. Changed documents make old notes
stale; they are excluded from retrieval. Notes never feed automatic pin extraction.

The pure-Python pypdf parser runs in a child process with a 12-second deadline,
8 MiB input, 80-page limit, 2 MB decoded stream cap, 24,000 characters per page and
280,000 characters of indexed output. Linux also caps parser address space at
384 MiB. Encrypted, oversized or unparseable PDFs fail explicitly and retain prior
successful cache copies. No PDF scripts, attachments or embedded URLs execute.
There is no automatic OCR or visual diagram interpretation.

## Physical connector inventory

Use **Record connector observation** only after checking the exact labeled
connector. Record unknown/free/occupied state, the attached device when occupied,
electrical notes and a separate confirmation of those requirements. Explicit
physical confirmation is required. The application supplies the date and identity
fingerprint; a general details save cannot forge or overwrite these records.

Board/model/revision/MCU/connection changes make an observation stale. A current
occupied connector is excluded from available fan examples even when unused in
configuration. A free observation is a dated user statement, not a machine check
or permanent availability guarantee. Source review and electrical/manual checks
continue to apply.

## User-triggered live checks

**Check live printer** uses the deployment's configured Moonraker connection and
reads fixed printer/config/status fields. It stores a dated public report with
reachability, firmware-prefix scope, configured MCU checks, selected status scalars
and missing evidence. Loaded settings are checked for availability but are not
returned as a raw config dump. It does not compare every loaded option or verify
wiring/calibration. Details saves preserve the report; rerun after changes.

**Check live provider response** sends a fixed public JSON-schema probe through
the configured Responses client and its existing usage guard. It sends no printer
data, uses at most 512 output tokens and reports whether the response parsed as
expected. It consumes provider credits and is separate from the existing
non-generating credential/model-access check. No configured client yields an
explicit unavailable result. Neither check is a model tool or an approval to
operate the printer.

Session-protected operations are `/api/knowledge/review-buses`, `/connectors`,
`/diagram-notes`, `/validate`, and `/api/providers/probe`. They accept no arbitrary
host paths, Moonraker methods or command arguments. They cannot edit printer files.

## Additional manual templates

The agent template tool supports these examples alongside parameterized probe, bed
mesh and measured input-shaper values:

- `Create a start print macro`: `START_PRINT` requires `BED_TEMP` and
  `EXTRUDER_TEMP`, checks readiness, sets temperatures, homes and waits. It assumes
  an extruder and heated bed. Review the actual homing/leveling sequence; it adds
  no purge move or guessed mesh profile.
- `Create an end print macro`: `END_PRINT` waits for queued moves, turns off
  heaters and stops the standard fan if present. No park, retract or motor-disable
  behavior is assumed.
- `Create a preflight macro`: a read-only readiness/homing report.
- `Generate BLTouch sensor_pin=^PA1 control_pin=PA2`: explicit supplied pin values
  are illustrative syntax, not recommendations. Unknown offsets remain placeholders.
- `Generate ADXL345 accelerometer cs_pin=th:PA4 spi_bus=spi1 axes_map=x,y,z probe_points=100,100,30`:
  an illustrative accelerometer/resonance draft, also supporting LIS2DW. Physical
  mounting, bus choice and safe measurement coordinates must be verified. It does
  not measure or recommend shaper frequencies.

Observed unique section files are retained as targets. All drafts receive the
existing static/manual review, comparison, patch and stale-revision handling.
No generated macro or calibration command is executed by KlipperAI.

## Validation and provenance

Automated tests cover quoted bus mappings, conflicting/stale evidence, fixed-family
tool arguments and reads, physical confirmation, page-note binding, PDF process
limits, immutable references, API sessions, persistence and manual draft targets.
JavaScript checks cover source review, explicit confirmations, live routes,
history fields and safe text rendering. The wheel is installed and exercised
outside the checkout, including the PDF child process and application startup.

The local checkout's configured Moonraker address returned no service, and its
provider has no active API key. Real printer/provider acceptance
is still pending on a configured deployment; fixtures do not establish it.

Semantics were checked against primary sources:
[Klipper bus reservations](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/bus.py),
[configuration reference](https://www.klipper3d.org/Config_Reference.html),
[macro templates](https://www.klipper3d.org/Command_Templates.html), and
[pypdf extraction limits](https://pypdf.readthedocs.io/en/stable/user/extract-text.html).
Upstream documentation is not proof of an installed firmware fork/commit.
