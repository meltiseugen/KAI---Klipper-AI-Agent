#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

detect_default_install_user() {
  if [[ -n "${SUDO_USER:-}" ]] && [[ "${SUDO_USER}" != "root" ]]; then
    printf '%s' "${SUDO_USER}"
    return
  fi

  local current_user
  current_user="$(id -un)"
  if [[ "$current_user" != "root" ]]; then
    printf '%s' "$current_user"
    return
  fi

  if id pi >/dev/null 2>&1; then
    printf '%s' "pi"
    return
  fi

  printf '%s' "root"
}

home_for_user() {
  local user="$1"
  if command -v getent >/dev/null 2>&1; then
    getent passwd "$user" | awk -F: '{ print $6; exit }'
    return
  fi

  awk -F: -v user="$user" '
    $1 == user {
      print $6
      found = 1
      exit
    }
    END {
      exit(found ? 0 : 1)
    }
  ' /etc/passwd
}

group_for_user() {
  local user="$1"
  local gid=""

  if id -gn "$user" >/dev/null 2>&1; then
    id -gn "$user"
    return
  fi

  if command -v getent >/dev/null 2>&1; then
    gid="$(getent passwd "$user" | awk -F: '{ print $4; exit }')" || return 1
    getent group "$gid" | awk -F: '{ print $1; exit }' || printf '%s' "$gid"
    return
  fi

  gid="$(awk -F: -v user="$user" '
    $1 == user {
      print $4
      found = 1
      exit
    }
    END {
      exit(found ? 0 : 1)
    }
  ' /etc/passwd)" || return 1

  awk -F: -v gid="$gid" '
    $3 == gid {
      print $1
      found = 1
      exit
    }
    END {
      exit(found ? 0 : 1)
    }
  ' /etc/group 2>/dev/null || printf '%s' "$gid"
}

systemd_unit_exists() {
  local unit_name="$1"
  local load_state=""

  load_state="$(systemctl show -p LoadState --value "$unit_name" 2>/dev/null || true)"
  load_state="$(trim_whitespace "$load_state")"
  [[ -n "$load_state" ]] && [[ "$load_state" != "not-found" ]]
}

detect_systemd_unit_user() {
  local unit_name="$1"
  local fallback_user="$2"
  local user_name=""

  if ! systemd_unit_exists "$unit_name"; then
    printf '%s' "$fallback_user"
    return
  fi

  user_name="$(systemctl show -p User --value "$unit_name" 2>/dev/null || true)"
  user_name="$(trim_whitespace "$user_name")"
  printf '%s' "${user_name:-$fallback_user}"
}
