- [] a second refinement, explore each components individually: mainsail patch, octoeverywhere patch, install script, uninstall script, settings and printer data, agent, UI. see what we are missing, any important bugs, and what we can do better. IF ANY. -> make a new Backlog2.md to track these separately
- [] a second refactor to make the code much more readable and easy to follow: focus on readability and not abstractization, use OOP, split the logic  into more classes, add docstrings and code comments. expand the documentation and make the docs easier to read and to follow, add flow diagrams, and other diagrams


## Performance on constrained printer hosts

- [x] Audit idle work, local reads, history, research, storage and dependencies; record evidence in [docs/performance.md](docs/performance.md).
- [x] Bound current-log reads and file counts, and reject oversized config reads before parsing.
- [x] Load history summaries first, fetch full chats when opened, and pause hidden-tab history polling.
- [x] Avoid evidence JSON work for lease heartbeats; bound retained manual-search candidates.
- [x] Limit complete investigations to one per application process, including recovery.
- [x] Add reproducible synthetic benchmarks and functional resource regression checks.


## Creality / Ender-3 V3 KE

- [x] Audit retained vendor-layout workarounds and add regression checks; see [compatibility audit](docs/creality-compatibility.md).
- [x] Implement native rooted-KE installation, init lifecycle, authenticated host-key credential delivery, fast SSH updates, rollback and uninstall; retain systemd support.
- [x] Automatically detect native Creality hosts and install missing prerequisites, including Bash from BusyBox sh, Entware, supported Python/modules, HTTPS support and MIPS C build tools.
- [ ] Record actual KE firmware acceptance: dependency installation, boot/reboot, automatic evidence reads, provider setup, UI routing, deployment and rollback.

interupptions and asking the user

- we need a model selector
