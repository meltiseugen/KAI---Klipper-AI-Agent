#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

write_nginx_snippet() {
  local temp_file
  temp_file="$(mktemp)"

  cat >"$temp_file" <<EOF
location ${KLIPPERAI_ROOT_PATH}/ {
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 300s;
    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_pass http://127.0.0.1:${KLIPPERAI_PORT}/;
}
EOF

  backup_file /etc/klipperai/nginx-location.conf
  run_root install -m 644 "$temp_file" /etc/klipperai/nginx-location.conf
  rm -f "$temp_file"
}

ensure_nginx_include() {
  local include_line="include /etc/klipperai/nginx-location.conf;"
  local path="$KLIPPERAI_NGINX_SERVER_BLOCK_PATH"

  [[ -n "$path" ]] || die "nginx server block path is not set."
  [[ -f "$path" ]] || die "nginx server block file not found: $path"

  local temp_file
  temp_file="$(mktemp)"
  if ! awk -v include_line="$include_line" '
    function strip_comments(value) {
      sub(/#.*/, "", value)
      return value
    }
    function count_char(value, char,    i, total) {
      total = 0
      for (i = 1; i <= length(value); i++) {
        if (substr(value, i, 1) == char) {
          total++
        }
      }
      return total
    }
    function trim(value) {
      sub(/^[[:space:]]+/, "", value)
      sub(/[[:space:]]+$/, "", value)
      return value
    }
    {
      raw = $0
      line = strip_comments($0)

      if (!in_server) {
        if (line ~ /^[[:space:]]*server[[:space:]]*\{/) {
          in_server = 1
          server_count++
          server_has_include = 0
          depth = count_char(line, "{") - count_char(line, "}")
          print raw
          next
        }
        print raw
        next
      }

      if (trim(strip_comments(raw)) == include_line) {
        server_has_include = 1
      }

      next_depth = depth + count_char(line, "{") - count_char(line, "}")
      if (depth > 0 && next_depth == 0) {
        if (!server_has_include) {
          print "    " include_line
          inserted = 1
        }
      }
      print raw
      depth = next_depth
      if (in_server && depth == 0) {
        in_server = 0
        server_has_include = 0
      }
    }
    END {
      if (server_count == 0) {
        exit 1
      }
    }
  ' "$path" >"$temp_file"; then
    rm -f "$temp_file"
    die "Could not find a server block to patch in $path"
  fi

  if cmp -s "$temp_file" "$path"; then
    rm -f "$temp_file"
    return
  fi

  local mode
  local owner
  local group
  mode="$(stat -c '%a' "$path")"
  owner="$(stat -c '%u' "$path")"
  group="$(stat -c '%g' "$path")"
  backup_file "$path"
  run_root install -o "$owner" -g "$group" -m "$mode" "$temp_file" "$path"
  rm -f "$temp_file"
  log "Updated $path"
}

reload_nginx() {
  local nginx_bin=""
  local nginx_config=""
  local pid=""
  local exe=""
  local cmdline=""

  for pid in $(pidof nginx 2>/dev/null || true); do
    exe="$(readlink "/proc/$pid/exe" 2>/dev/null || true)"
    if [[ -z "$nginx_bin" ]] && [[ -n "$exe" ]] && [[ -x "$exe" ]]; then
      nginx_bin="$exe"
    fi

    cmdline="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
    if [[ "$cmdline" == *"master process"* ]] && [[ "$cmdline" == *" -c "* ]]; then
      nginx_config="${cmdline#* -c }"
      nginx_config="${nginx_config%% *}"
    fi
  done

  if [[ -z "$nginx_bin" ]]; then
    nginx_bin="$(command -v nginx || true)"
  fi
  [[ -n "$nginx_bin" ]] || die "nginx executable not found."

  if [[ -n "$nginx_config" ]] && [[ -f "$nginx_config" ]]; then
    run_root "$nginx_bin" -t -c "$nginx_config"
    run_root "$nginx_bin" -s reload -c "$nginx_config"
    return
  fi

  run_root "$nginx_bin" -t
  if ! run_root "$nginx_bin" -s reload; then
    run_root systemctl reload nginx
  fi
}
