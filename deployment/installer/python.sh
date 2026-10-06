#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

python_version_string() {
  local python_bin="$1"
  "$python_bin" -c 'import sys; print(".".join(str(part) for part in sys.version_info[:3]))'
}

python_is_supported() {
  local python_bin="$1"
  "$python_bin" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

detect_python_interpreter() {
  local candidate=""

  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && python_is_supported "$candidate"; then
      PYTHON_BIN="$candidate"
      return
    fi
  done

  if command -v python3 >/dev/null 2>&1; then
    die "KlipperAI requires Python ${MIN_PYTHON_VERSION}+ but python3 is $(python_version_string python3). Install Python ${MIN_PYTHON_VERSION}+ and the matching venv module, or run ./deployment/python/install-python310.sh, then rerun."
  fi

  die "KlipperAI requires Python ${MIN_PYTHON_VERSION}+. Install it manually or run ./deployment/python/install-python310.sh."
}

python_venv_package_name() {
  local python_bin="$1"
  case "$python_bin" in
    python3.[0-9]|python3.[0-9][0-9])
      printf '%s-venv' "$python_bin"
      ;;
    *)
      printf '%s' "python3-venv"
      ;;
  esac
}

have_python_command() {
  local candidate=""

  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      return 0
    fi
  done

  return 1
}

maybe_install_python_packages() {
  if have_python_command; then
    return
  fi

  if command -v apt-get >/dev/null 2>&1; then
    if confirm "No Python 3 interpreter was found. Install the distro default python3, python3-venv, and python3-pip packages with apt? KlipperAI will verify that the version is ${MIN_PYTHON_VERSION}+." "Y"; then
      run_root apt-get update
      run_root apt-get install -y python3 python3-venv python3-pip
      return
    fi
  fi

  die "Python ${MIN_PYTHON_VERSION}+ is required."
}

ensure_python_venv() {
  local venv_package=""

  if run_as_user "$PYTHON_BIN" -m venv --help >/dev/null 2>&1; then
    PYTHON_VENV_MODULE="venv"
    return
  fi

  if run_as_user "$PYTHON_BIN" -m virtualenv --help >/dev/null 2>&1; then
    PYTHON_VENV_MODULE="virtualenv"
    return
  fi

  venv_package="$(python_venv_package_name "$PYTHON_BIN")"
  if command -v apt-get >/dev/null 2>&1; then
    if confirm "Python venv support is missing for $PYTHON_BIN. Install $venv_package with apt?" "Y"; then
      run_root apt-get update
      run_root apt-get install -y "$venv_package"
      if run_as_user "$PYTHON_BIN" -m venv --help >/dev/null 2>&1; then
        PYTHON_VENV_MODULE="venv"
        return
      fi
    fi
  fi

  if run_as_user "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    if confirm "Python venv support is missing for $PYTHON_BIN. Install virtualenv with pip and use that to create .venv?" "Y"; then
      run_as_user "$PYTHON_BIN" -m pip install --user virtualenv
      if run_as_user "$PYTHON_BIN" -m virtualenv --help >/dev/null 2>&1; then
        PYTHON_VENV_MODULE="virtualenv"
        return
      fi
    fi
  fi

  die "Python venv support is required for $PYTHON_BIN. Install the distro venv package, or install virtualenv with: $PYTHON_BIN -m pip install --user virtualenv"
}

create_python_virtual_environment() {
  case "$PYTHON_VENV_MODULE" in
    venv)
      run_as_user "$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv"
      ;;
    virtualenv)
      run_as_user "$PYTHON_BIN" -m virtualenv "$INSTALL_DIR/.venv"
      ;;
    *)
      die "No Python virtual environment creator was selected."
      ;;
  esac
}
