# Manual configuration review

Every proposal is a draft for the user's editor. The review reads the collected
config and, when available, Moonraker's `/printer/info`; it never executes the
snippet, changes printer files, heats, moves, restarts or applies a proposal.
Public checks and their evidence are saved with the investigation in application
storage. Existing saved reviews remain readable without the new optional fields.

Reviews also include manual file patches and managed include plans when sufficient
evidence is available. See [Config Assistant](config-assistant.md) for option-merge
semantics, inactive-file protection, SAVE_CONFIG handling and local config audits.

## Reading a review

The card shows the firmware basis, **Option and version checks**, **Manual
verification checklist**, and the existing proposed-section comparison.
Checks identify a section, option and snippet line, with a documentation link.
Errors open the check list automatically. A successful scalar check establishes
only that the value matches a bundled reference constraint.

- `needs_information`: resolve blocking syntax, value, dependency or evidence issues.
- `manual_review`: the implemented checks found no blocking issue; verify all
  remaining warnings and physical requirements before editing.
- `stale`: the config revision or observed firmware identity changed, or the
  proposal was already stale. Request a new draft. Rechecking does not renew it.

**Recheck current config** repeats the read-only review. The initial config and
firmware basis remain attached to the proposal. If a previous live version cannot
be reread, the card warns about missing evidence; an older saved profile alone
does not establish that the running firmware changed.

## Bundled checks and their limits

`config/review_parser.py` parses option assignments, comments and indented multiline
macros without evaluating Jinja, Python literals or G-code. Duplicate options and
sections are flagged as ambiguous, even where firmware might allow overrides.
`DEFAULT` inheritance requires manual expansion. Include directives are not
executed by the review parser; the existing collector owns active-tree discovery.

`config/option_rules.py` contains a deliberately partial catalog:

| Sections | Examples of checks |
| --- | --- |
| Printer and steppers | Positive velocity/acceleration/rotation distance, integer microsteps, ordered travel limits |
| Fans and temperature fans | Power/speed fractions, booleans, timing and tachometer values, required pin, speed ordering |
| Heaters, extruders and temperature sensors | Numeric temperature bounds, power, control choice, PID coefficient presence when changing to PID |
| Probe and BLTouch | Offsets, sample counts, tolerances and sample-result choice |
| Bed mesh | Coordinate shapes, probe counts, interpolation choice, ordered rectangular bounds |
| Input shaper | Common shaper choices, nonnegative frequencies and damping ratios |
| Macros, delayed G-code and output pins | Required content/pins, delay, PWM flag and selected numeric settings |

Required fields and cross-option comparisons use proposed values merged with the
same section in a complete observed target file. A partial snippet is not treated
as a replacement for that section. Malformed or truncated observed text cannot
establish missing required values. Defaults, includes, SAVE_CONFIG overrides and
all firmware dependencies are not reconstructed into a complete effective config.

Unknown sections/options produce verification warnings, not claims that extensions
are invalid. Expressions and macro variables require manual inspection. Recognized
pin, sensor and G-code option names are not proof that their contents are valid.
Existing component-knowledge checks still provide separate fan hardware evidence.

## Version evidence

The live version comes from a bounded read of Moonraker `/printer/info`.
Fork identity comes from the saved printer profile and is labeled as such.
On failure, saved context is displayed with an explicit warning. No version string
proves that the installed source matches an upstream release.

`config/review_versions.py` recognizes only exact upstream Klipper `v0.12.0` and
`v0.13.0` tags (also without `v`, or with a zero-commit `-0-g<hash>` suffix).
For these identities, the bundled compatibility checks are:

| Option | 0.12.0 | 0.13.0 |
| --- | --- | --- |
| `[printer] minimum_cruise_ratio` | Unsupported | Present |
| `[printer] max_accel_to_decel` | Present | Deprecated, not yet removed |
| `[bed_mesh] relative_reference_index` | Present | Removed; review `zero_reference_position` |
| `[output_pin] static_value` | Present | Removed; review `value` / `shutdown_value` |
| `[output_pin] maximum_mcu_duration` | Present | Removed; review `pwm_tool` |

Git builds with additional commits, dirty builds, unknown versions and forks receive
commit-specific verification warnings instead of inferred release compatibility.
Kalico's documented heater modes `pid_v`, `mpc` and `dual_loop_pid` are distinguished
from upstream modes; their availability and tuning still require the installed
Kalico commit's documentation. Other version-sensitive options remain outside this
small compatibility table.

## Manual verification

`config/review_guidance.py` chooses steps from the actual proposed sections:
back up and merge the config, check inclusion and duplicates, then inspect relevant
wiring, fan cooling/shutdown behavior, sensor readings and thermal limits,
endstops/probe reach, mesh edges, resonance measurements or macro branches.
The final step asks for supervised checks after manual editing and restoration of
the backup if those checks fail. The checklist links the matching firmware guide;
it does not offer executable commands or a one-click printer action.

## Reference provenance

The catalog was checked on 2026-10-21 against the official
[configuration reference](https://www.klipper3d.org/Config_Reference.html),
[migration history](https://www.klipper3d.org/Config_Changes.html),
[configuration checks](https://www.klipper3d.org/Config_checks.html), and
[Kalico reference](https://docs.kalico.gg/Config_Reference.html).
Release distinctions were checked against tagged
[0.12.0 toolhead code](https://github.com/Klipper3d/klipper/blob/v0.12.0/klippy/toolhead.py),
[0.13.0 toolhead code](https://github.com/Klipper3d/klipper/blob/v0.13.0/klippy/toolhead.py),
and the [0.13.0 migration record](https://github.com/Klipper3d/klipper/blob/v0.13.0/docs/Config_Changes.md).
Current online documentation can describe behavior newer than either tag.

Automated regression tests: `test_review_options.py`, `test_proposal_review.py`,
`test_investigations.py`, and `proposal-review-ui.test.mjs`. They cover range and
relationship failures, partial merges, macro parsing, version uncertainty,
firmware staleness, saved rendering and unchanged printer-config bytes.
They do not prove real printer compatibility or live provider output quality.
