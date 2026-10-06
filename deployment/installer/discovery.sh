#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

detect_moonraker_config_path() {
  local home_dir="$1"
  local config_dir="$2"
  local candidate=""

  for candidate in \
    "$config_dir/moonraker.conf" \
    /usr/data/printer_data/config/moonraker.conf \
    "$home_dir/printer_data/config/moonraker.conf" \
    "$home_dir/moonraker.conf"
  do
    if [[ -f "$candidate" ]]; then
      printf '%s' "$candidate"
      return
    fi
  done

  printf '%s' "$config_dir/moonraker.conf"
}

detect_nginx_server_block_path() {
  local candidate=""

  for candidate in \
    /usr/data/nginx/conf.d/mainsail.conf \
    /usr/data/nginx/conf.d/default.conf \
    /usr/data/nginx/nginx.conf \
    /usr/data/nginx/conf/nginx.conf \
    /etc/nginx/conf.d/mainsail.conf \
    /etc/nginx/sites-enabled/mainsail \
    /etc/nginx/sites-available/mainsail
  do
    if [[ -f "$candidate" ]]; then
      printf '%s' "$candidate"
      return
    fi
  done

  candidate="$(
    find /usr/data/nginx -maxdepth 3 -type f \
      \( -name '*.conf' -o -name 'nginx.conf' \) \
      -exec grep -l '^[[:space:]]*server[[:space:]]*{' {} \; 2>/dev/null \
      | sort \
      | head -n1 \
      || true
  )"
  if [[ -n "$candidate" ]]; then
    printf '%s' "$candidate"
    return
  fi

  printf '%s' "/etc/nginx/conf.d/mainsail.conf"
}

detect_printer_data_root() {
  local home_dir="$1"
  local candidate=""

  for candidate in \
    /usr/data/printer_data \
    /usr/data/printer_1_data \
    /usr/data/printer_2_data \
    /usr/data/printer_3_data \
    "$home_dir/printer_data" \
    "$home_dir/printer_1_data" \
    "$home_dir/printer_2_data" \
    "$home_dir/printer_3_data"
  do
    if [[ -d "$candidate" ]]; then
      printf '%s' "$candidate"
      return
    fi
  done

  candidate="$(find "$home_dir" -maxdepth 1 -type d -name 'printer*_data' 2>/dev/null | sort | head -n1 || true)"
  if [[ -n "$candidate" ]]; then
    printf '%s' "$candidate"
    return
  fi

  printf '%s' "$home_dir/printer_data"
}

expand_user_path() {
  local value="$1"
  local home_dir="$2"

  case "$value" in
    "~")
      printf '%s' "$home_dir"
      ;;
    "~/"*)
      printf '%s/%s' "$home_dir" "${value#~/}"
      ;;
    *)
      printf '%s' "$value"
      ;;
  esac
}

extract_update_manager_path() {
  local config_path="$1"
  local home_dir="$2"
  local section_regex="$3"
  local raw_value=""

  [[ -f "$config_path" ]] || return 1
  raw_value="$(awk -v section_regex="$section_regex" '
    function trim(value) {
      gsub(/^[ \t]+|[ \t]+$/, "", value)
      return value
    }
    function strip_comments(value) {
      sub(/[ \t]+#.*/, "", value)
      sub(/^#.*/, "", value)
      return value
    }
    {
      line = $0
      if (line ~ /^[[:space:]]*\[[^]]+\][[:space:]]*$/) {
        gsub(/^[[:space:]]*\[/, "", line)
        gsub(/\][[:space:]]*$/, "", line)
        section = tolower(trim(line))
        in_section = (section ~ ("^update_manager[[:space:]]+(" section_regex ")$"))
        next
      }

      if (!in_section) {
        next
      }

      line = trim(strip_comments($0))
      if (line == "") {
        next
      }

      if (line ~ /^path[[:space:]]*[:=][[:space:]]*/) {
        sub(/^path[[:space:]]*[:=][[:space:]]*/, "", line)
        print trim(line)
        exit
      }
    }
  ' "$config_path")"

  raw_value="$(trim_whitespace "$raw_value")"
  raw_value="${raw_value#\"}"
  raw_value="${raw_value%\"}"
  raw_value="${raw_value#\'}"
  raw_value="${raw_value%\'}"
  [[ -n "$raw_value" ]] || return 1
  expand_user_path "$raw_value" "$home_dir"
}

detect_octoeverywhere_root() {
  local home_dir="$1"
  local candidate=""

  for candidate in \
    "$home_dir/octoeverywhere" \
    "$home_dir/OctoEverywhere" \
    "/usr/data/octoeverywhere" \
    "/usr/data/OctoEverywhere"
  do
    if [[ -f "$candidate/moonraker_octoeverywhere/static/oe-ui.js" ]]; then
      printf '%s' "$candidate"
      return
    fi
  done

  candidate="$(
    {
      find "$home_dir" -maxdepth 3 -type f -path '*/moonraker_octoeverywhere/static/oe-ui.js' 2>/dev/null
      find /usr/data -maxdepth 3 -type f -path '*/moonraker_octoeverywhere/static/oe-ui.js' 2>/dev/null
    } | sort | head -n1 || true
  )"
  if [[ -n "$candidate" ]]; then
    printf '%s' "${candidate%/moonraker_octoeverywhere/static/oe-ui.js}"
  fi
}

detect_octoeverywhere_service_name() {
  local candidate=""

  for candidate in octoeverywhere.service octoeverywhere; do
    if systemd_unit_exists "$candidate"; then
      printf '%s' "${candidate%.service}"
      return
    fi
  done
}

detect_git_origin() {
  if ! command -v git >/dev/null 2>&1; then
    printf '%s' "https://github.com/meltiseugen/KlipperAI.git"
    return
  fi

  local origin=""
  origin="$(git -C "$INSTALL_DIR" remote get-url origin 2>/dev/null || true)"
  if [[ -z "$origin" ]]; then
    printf '%s' "https://github.com/meltiseugen/KlipperAI.git"
    return
  fi

  case "$origin" in
    git@github.com:*)
      origin="${origin#git@github.com:}"
      printf 'https://github.com/%s' "$origin"
      return
      ;;
    ssh://git@github.com/*)
      origin="${origin#ssh://git@github.com/}"
      printf 'https://github.com/%s' "$origin"
      return
      ;;
  esac

  printf '%s' "$origin"
}

detect_git_primary_branch() {
  if ! command -v git >/dev/null 2>&1; then
    printf '%s' "main"
    return
  fi

  local branch=""
  branch="$(git -C "$INSTALL_DIR" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
  branch="${branch#origin/}"
  if [[ -n "$branch" ]]; then
    printf '%s' "$branch"
    return
  fi

  branch="$(git -C "$INSTALL_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  if [[ -n "$branch" ]] && [[ "$branch" != "HEAD" ]]; then
    printf '%s' "$branch"
    return
  fi

  printf '%s' "main"
}
