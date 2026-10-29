# Changelog

Release entries use the package version and an ISO date. Keep unreleased changes
here until an actual release is prepared. No release has been published by this
change.

## Unreleased

### Added

- Native rooted Creality/KE init-service installation, authenticated host-key
  encryption with RAM-only master delivery, root SSH updates and code rollback.
- Automatic prerequisite setup from BusyBox sh, native Creality detection, preserved
  Entware bootstrap, supported Python/modules, HTTPS support and MIPS C build tools.
- Linux CI for supported Python versions, full coverage, browser module tests,
  generated architecture checks and installed-package smoke tests.
- Installer configuration integration checks and real nginx routing checks.
- Synthetic printer-failure examples with expected evidence findings.
- Operator SSH deployment of the current workspace, build identification,
  readiness checks and code rollback for printer testing.
- Release artifact validation, checksums and release conventions.

### Compatibility

- Python 3.10 or newer; Pydantic v1 remains supported.
- Deployment updates application code using the printer's existing dependencies.
  Dependency changes require separate maintenance.
- Printer access remains read-only. Configuration proposals require manual edits.
