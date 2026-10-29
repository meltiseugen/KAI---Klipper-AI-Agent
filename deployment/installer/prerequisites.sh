#!/usr/bin/env bash
# Install application prerequisites before preflight starts requiring them.

prerequisite_nginx_available() {
  bootstrap_command_path nginx >/dev/null && return 0
  local candidate pid
  for candidate in /usr/data/nginx/sbin/nginx /usr/data/nginx/nginx /usr/data/nginx/bin/nginx; do
    [[ ! -x "$candidate" ]] || return 0
  done
  for pid in $(pidof nginx 2>/dev/null || true); do
    candidate="$(readlink "/proc/$pid/exe" 2>/dev/null || true)"
    [[ -z "$candidate" || ! -x "$candidate" ]] || return 0
  done
  return 1
}

prerequisite_python() {
  local candidate
  for candidate in /opt/bin/python3 /opt/bin/python3.13 /opt/bin/python3.12 /opt/bin/python3.11 /opt/bin/python3.10 python3.13 python3.12 python3.11 python3.10 python3; do
    if bootstrap_command_path "$candidate" >/dev/null && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
      PREREQUISITE_PYTHON="$candidate"
      return 0
    fi
  done
  return 1
}

prerequisite_git_https() {
  local helpers
  helpers="$(git --exec-path 2>/dev/null)" && [[ -x "$helpers/git-remote-http" ]]
}

ensure_prerequisites() {
  bootstrap_opt_path
  local -a packages=()
  local manager= command package
  # A usable host needs no package-manager transaction or package-index polling.
  for command in awk find git grep install stat tar; do
    if ! bootstrap_command_path "$command" >/dev/null; then
      [[ -n "$manager" ]] || { bootstrap_manager || die "Could not prepare a package manager."; manager="$KLIPPERAI_PACKAGE_MANAGER"; }
      package="$command"
      case "$manager:$command" in
        opkg:awk) package=gawk;; opkg:find) package=findutils;;
        opkg:install) package=coreutils-install;; opkg:stat) package=coreutils-stat;;
        apt-get:awk) package=gawk;; apt-get:find) package=findutils;;
        apt-get:install|apt-get:stat) package=coreutils;;
        apk:awk) package=gawk;; apk:find) package=findutils;;
        apk:install|apk:stat) package=coreutils;;
      esac
      packages+=("$package")
      if [[ "$manager:$command" == opkg:git ]]; then packages+=(git-http ca-bundle); fi
    fi
  done
  if bootstrap_command_path git >/dev/null && ! prerequisite_git_https; then
    [[ -n "$manager" ]] || { bootstrap_manager || die "Could not prepare a package manager."; manager="$KLIPPERAI_PACKAGE_MANAGER"; }
    if [[ "$manager" == opkg ]]; then packages+=(git-http ca-bundle); else packages+=(git); fi
  fi
  if ! prerequisite_nginx_available; then
    [[ -n "$manager" ]] || { bootstrap_manager || die "Could not prepare a package manager."; manager="$KLIPPERAI_PACKAGE_MANAGER"; }
    if [[ "$manager" == opkg ]]; then packages+=(nginx-ssl); else packages+=(nginx); fi
  fi
  if ! prerequisite_python || ! "$PREREQUISITE_PYTHON" -c 'import ssl, sqlite3, ctypes, asyncio, logging, email, urllib.request, zlib, multiprocessing' >/dev/null 2>&1 || ! "$PREREQUISITE_PYTHON" -m pip --version >/dev/null 2>&1; then
    [[ -n "$manager" ]] || { bootstrap_manager || die "Could not prepare a package manager."; manager="$KLIPPERAI_PACKAGE_MANAGER"; }
    case "$manager" in
      opkg) packages+=(python3 python3-pip python3-openssl python3-sqlite3 python3-ctypes ca-bundle ca-certificates);;
      apt-get) packages+=(python3 python3-venv python3-pip ca-certificates);;
      apk) packages+=(python3 py3-pip py3-virtualenv ca-certificates);;
    esac
  elif ! "$PREREQUISITE_PYTHON" -c 'import ssl; raise SystemExit(not ssl.create_default_context().get_ca_certs())' >/dev/null 2>&1; then
    [[ -n "$manager" ]] || { bootstrap_manager || die "Could not prepare a package manager."; manager="$KLIPPERAI_PACKAGE_MANAGER"; }
    packages+=(ca-certificates)
    [[ "$manager" != opkg ]] || packages+=(ca-bundle)
  fi
  if [[ "${#packages[@]}" -gt 0 ]]; then
    bootstrap_packages "${packages[@]}" || die "Prerequisite installation failed. Existing printer files were preserved."
    hash -r
  fi
  if ! prerequisite_python; then
    if [[ "${manager:-}" == apt-get ]]; then
      log "Installing a supported Python alongside the distro Python."
      run_root env BUILD_JOBS=1 bash "$SCRIPT_DIR/deployment/python/install-python310.sh"
      hash -r
    fi
    prerequisite_python || die "The package feed did not provide Python 3.10 or newer."
  fi
  "$PREREQUISITE_PYTHON" -c 'import ssl, sqlite3, ctypes, asyncio, logging, email, urllib.request, zlib, multiprocessing' || die "Python is missing required standard-library modules."
  "$PREREQUISITE_PYTHON" -m pip --version >/dev/null || die "Python pip setup did not complete."
  "$PREREQUISITE_PYTHON" -c 'import ssl; raise SystemExit(not ssl.create_default_context().get_ca_certs())' || die "Python cannot find trusted HTTPS certificates."
}

ensure_crypto_build_prerequisites() {
  [[ "${KLIPPERAI_SERVICE_MANAGER:-systemd}" == appliance ]] || return 0
  case "$(uname -m)" in mips|mipsel) ;; *) return 0;; esac
  run_as_user "$INSTALL_DIR/.venv/bin/python" -c 'from Cryptodome.Cipher import AES' >/dev/null 2>&1 && return 0
  if ! bootstrap_command_path gcc >/dev/null || ! bootstrap_command_path make >/dev/null || ! "$PYTHON_BIN" -c 'import pathlib,sysconfig; raise SystemExit(not (pathlib.Path(sysconfig.get_path("include"))/"Python.h").is_file())'; then
    bootstrap_manager || die "C build prerequisites require a package manager."
    case "$KLIPPERAI_PACKAGE_MANAGER" in
      opkg) bootstrap_packages gcc make python3-dev || die "C build prerequisite installation failed." ;;
      apt-get) bootstrap_packages build-essential python3-dev || die "C build prerequisite installation failed." ;;
      apk) bootstrap_packages build-base python3-dev || die "C build prerequisite installation failed." ;;
    esac
  fi
  # PyCryptodome is the required C extension; optional Python speedups stay disabled.
  export MAKEFLAGS=-j1
}
