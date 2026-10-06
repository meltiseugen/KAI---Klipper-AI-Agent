#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

log() {
  printf '[%s] %s\n' "$PROJECT_NAME" "$*"
}

warn() {
  printf '[%s] warning: %s\n' "$PROJECT_NAME" "$*" >&2
}

die() {
  printf '[%s] error: %s\n' "$PROJECT_NAME" "$*" >&2
  exit 1
}

confirm() {
  local prompt="$1"
  local default="${2:-Y}"
  local suffix="[y/N]"
  local reply=""

  if [[ "$default" == "Y" ]]; then
    suffix="[Y/n]"
  fi

  read -r -p "$prompt $suffix " reply
  reply="${reply:-$default}"
  case "${reply,,}" in
    y|yes) return 0 ;;
    n|no) return 1 ;;
    *) warn "Please answer yes or no."; confirm "$prompt" "$default"; return $? ;;
  esac
}

prompt_default() {
  local prompt="$1"
  local default="$2"
  local reply=""
  read -r -p "$prompt [$default]: " reply
  printf '%s' "${reply:-$default}"
}

prompt_secret() {
  local prompt="$1"
  local reply=""
  read -r -s -p "$prompt: " reply
  printf '\n' >&2
  printf '%s' "$reply"
}

trim_whitespace() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

require_linux() {
  [[ "$(uname -s)" == "Linux" ]] || die "This installer only supports Linux hosts."
}

require_cmd() {
  local command_name="$1"
  command -v "$command_name" >/dev/null 2>&1 || die "Required command not found: $command_name"
}

run_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    command -v sudo >/dev/null 2>&1 || die "sudo is required for installation."
    sudo "$@"
  fi
}

run_as_user() {
  if [[ "$(id -un)" == "$INSTALL_USER" ]]; then
    "$@"
    return
  fi

  if [[ "${EUID}" -eq 0 ]] && command -v runuser >/dev/null 2>&1; then
    runuser -u "$INSTALL_USER" -- "$@"
    return
  fi

  if command -v sudo >/dev/null 2>&1; then
    sudo -u "$INSTALL_USER" -H "$@"
    return
  fi

  die "Unable to switch to user '$INSTALL_USER'."
}

backup_file() {
  local path="$1"
  if [[ -e "$path" ]]; then
    run_root cp "$path" "${path}.bak.${TIMESTAMP}"
    log "Backed up $path to ${path}.bak.${TIMESTAMP}"
  fi
}

escape_env_value() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '%s' "$value"
}

ensure_no_spaces() {
  local value="$1"
  local label="$2"
  if [[ "$value" =~ [[:space:]] ]]; then
    die "$label must not contain whitespace."
  fi
}

normalize_root_path() {
  local value="$1"
  value="/${value#/}"
  value="${value%/}"
  if [[ -z "$value" ]]; then
    value="/klipperai"
  fi
  printf '%s' "$value"
}

ensure_numeric_port() {
  local value="$1"
  [[ "$value" =~ ^[0-9]+$ ]] || die "Port must be numeric."
  if (( value < 1 || value > 65535 )); then
    die "Port must be between 1 and 65535."
  fi
}

file_has_trimmed_line() {
  local path="$1"
  local needle="$2"
  [[ -f "$path" ]] || return 1
  awk -v needle="$needle" '
    function trim(value) {
      gsub(/^[ \t]+|[ \t]+$/, "", value)
      return value
    }
    {
      if (trim($0) == needle) {
        found = 1
        exit
      }
    }
    END {
      exit(found ? 0 : 1)
    }
  ' "$path"
}

remove_line_from_file_if_present() {
  local path="$1"
  local line_to_remove="$2"
  [[ -f "$path" ]] || return 0

  if ! file_has_trimmed_line "$path" "$line_to_remove"; then
    return 0
  fi

  local temp_file
  temp_file="$(mktemp)"
  local mode
  local owner
  local group
  mode="$(stat -c '%a' "$path")"
  owner="$(stat -c '%u' "$path")"
  group="$(stat -c '%g' "$path")"
  awk -v needle="$line_to_remove" '
    function trim(value) {
      gsub(/^[ \t]+|[ \t]+$/, "", value)
      return value
    }
    {
      if (trim($0) != needle) {
        print $0
      }
    }
  ' "$path" >"$temp_file"
  backup_file "$path"
  run_root install -o "$owner" -g "$group" -m "$mode" "$temp_file" "$path"
  rm -f "$temp_file"
  log "Updated $path"
}

retire_legacy_file_if_present() {
  local path="$1"
  [[ -e "$path" ]] || return 0
  backup_file "$path"
  run_root rm -f -- "$path"
  log "Removed legacy file $path"
}
