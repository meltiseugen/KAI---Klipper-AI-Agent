# Config Assistant

Ask **Analyze active printer configuration** in Chat to have the agent investigate
the configuration. An active LLM provider and API key are required. The model can
call the read-only `analyze_config` tool for deterministic evidence. Findings, source file/line
citations and the config revision are saved with the conversation. Analysis only
reads the configured root and active includes; inactive files are not diagnosed.

The audit checks missing explicit includes, empty wildcard matches, recursive
include chains, ambiguous syntax, repeated sections/overrides, incompatible homing
sections, malformed pin descriptions, unknown MCU/extension references, missing
virtual probe definitions, alias-resolution gaps and multiple pin owners.
Empty wildcards are allowed by Klipper. Repeated sections and shared pins require
inspection; they are not automatically firmware errors. Board aliases and virtual
multi-pin outputs use the existing conservative pin-ownership resolver.
Include wildcards stay within each named directory; `**` does not enable recursive
glob expansion in Klipper. Commented section/include headers retain source locations.

This is analysis of files **on disk**, which may differ from the configuration
currently loaded by Klipper. Physical pin existence, wiring, implicit bus pins,
fork-specific objects, macro execution and SAVE_CONFIG values still require
firmware/hardware verification. The analyzer does not run Klipper. Full reads are
bounded to 1 MB per expanded file and 2 MB per audit, with at most 80 findings.
Collection/read gaps produce a partial result instead of a healthy-printer claim.

## Manual file plans

Proposal review prepares line-oriented unified diffs against observed files.
Supplied options are merged; omitted options, unrelated sections and comments
are retained. Replaced option comments may move to adjacent comment lines.
This is an option merge, not a deletion/rename or whole-file replacement system.
The existing proposed-section comparison remains available separately.

New fragments use `klipperai/<feature>.cfg`, relative to the printer config root.
The directory is reserved by convention for assistant-drafted fragments; the user
creates and maintains it in their editor. KlipperAI never creates that directory
or writes printer files. Each plan includes a create/update patch and, if needed,
an explicit include patch relative to the actual root file's directory. Existing
wildcard includes are reused, and includes are inserted before SAVE_CONFIG.
An inactive file at the proposed path is inspected and merged instead of silently
overwritten. Other inactive files are not treated as active section conflicts.

The UI displays **Manual file patch** only for drafts without blocking review
errors. Stale, ambiguous, redacted or incomplete baselines withhold patches;
proposed sections colliding with SAVE_CONFIG also require manual reconciliation.
Rechecks retain the original active revision and individual target digests,
including an absent-file baseline for new fragments. A newly created or edited
inactive target invalidates the old draft. Disagreeing patches to the same file
are withheld with a request for one consolidated proposal. Back up the config and
inspect the complete plan before manually merging it. No apply, approve or restart
endpoint exists.

## Feature drafts

The model can call `get_config_template` with explicit `option=value` or `option: value` parameters
for input shaper, bed mesh and generic probe sections. It keeps other observed
options and targets the existing section's file. Examples:

- `Generate input shaper config with shaper_type_x=mzv shaper_freq_x=43.2 shaper_type_y=ei shaper_freq_y=51.0`
- `Edit bed mesh with mesh_min=20,20 mesh_max=200,200 probe_count=7,7 algorithm=bicubic`
- `Edit probe with samples=3 samples_result=median samples_tolerance=0.01 samples_tolerance_retries=3`
- `Create a printer status macro`

The numbers above demonstrate syntax, not recommended calibration values.
Frequencies/types, probe pins/offsets and mesh bounds must come from measurements
or supplied evidence. Missing values remain explicit placeholders and block
the review. Generation does not derive safe probing bounds from bed dimensions.
The status macro reports printer state, homed axes and available heater readings
using `action_respond_info`; it has no motion/heater commands or RESPOND dependency.
Scaffolds feed the model, which evaluates their assumptions and drafts the final
proposal subject to the same manual review. They are not a separate assistant.

Additional purpose-specific drafts now cover `START_PRINT`, `END_PRINT`,
`KLIPPERAI_PREFLIGHT`, BLTouch and ADXL345/LIS2DW resonance setup. Start requires
explicit slicer temperatures and contains no guessed purge coordinates or mesh
profile. End waits for queued moves and turns off heaters without inventing a
park/retract move. BLTouch retains observed options and keeps unknown pins/offsets
as placeholders. Resonance drafts retain unknown orientation and safe measurement
coordinates as placeholders; no calibration is performed. Examples and limits are
in [hardware knowledge](hardware-knowledge.md).

## References and validation

Semantics checked against upstream sources on 2026-10-22:

- [Klipper include/override parsing](https://github.com/Klipper3d/klipper/blob/master/klippy/configfile.py)
- [Pin description handling](https://github.com/Klipper3d/klipper/blob/master/klippy/pins.py)
- [Configuration reference](https://www.klipper3d.org/Config_Reference.html)
- [Macro actions](https://www.klipper3d.org/Command_Templates.html#actions)

These references are not proof of the installed fork/commit's behavior.
See [manual configuration review](configuration-review.md) for option/version
checks and [investigations](investigations.md) for persistence and revalidation.
Automated tests: `test_config_analysis.py`, `test_config_patches.py`,
`test_config_features.py`, and `config-assistant-ui.test.mjs`.
