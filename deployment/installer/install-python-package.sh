#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

install_python_package() {
  maybe_install_python_packages
  detect_python_interpreter
  ensure_python_venv
  log "Using Python interpreter: $PYTHON_BIN ($(python_version_string "$PYTHON_BIN"))"

  log "Creating service data directory."
  run_root install -d -m 755 "$KLIPPERAI_DATA_DIR"
  run_root chown "$INSTALL_USER:$INSTALL_GROUP" "$KLIPPERAI_DATA_DIR"

  log "Creating Python virtual environment."
  if [[ -d "$INSTALL_DIR/.venv" ]]; then
    if [[ ! -x "$INSTALL_DIR/.venv/bin/python" ]]; then
      warn "Existing virtual environment at $INSTALL_DIR/.venv is incomplete."
      confirm "Recreate the virtual environment?" "Y" || die "Installation cancelled."
      run_as_user rm -rf "$INSTALL_DIR/.venv"
    elif ! python_is_supported "$INSTALL_DIR/.venv/bin/python"; then
      warn "Existing virtual environment uses Python $(python_version_string "$INSTALL_DIR/.venv/bin/python"), but KlipperAI requires Python ${MIN_PYTHON_VERSION}+."
      confirm "Recreate the virtual environment with $PYTHON_BIN?" "Y" || die "Installation cancelled."
      run_as_user rm -rf "$INSTALL_DIR/.venv"
    fi
  fi
  if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
    create_python_virtual_environment
  fi

  log "Installing Python package into the virtual environment."
  run_as_user "$INSTALL_DIR/.venv/bin/python" -m pip install --upgrade pip
  run_as_user env SKIP_CYTHON=1 MARKUPSAFE_SKIP_SPEEDUPS=1 "$INSTALL_DIR/.venv/bin/python" -m pip install --prefer-binary -e "$INSTALL_DIR"
}
