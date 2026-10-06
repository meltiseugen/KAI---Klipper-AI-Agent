#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

write_systemd_service() {
  local temp_file
  local unit_dir="/etc/systemd/system"
  local unit_path="$unit_dir/${SERVICE_NAME}.service"
  temp_file="$(mktemp)"

  cat >"$temp_file" <<EOF
[Unit]
Description=KlipperAI agent
After=network-online.target moonraker.service
Wants=network-online.target

[Service]
Type=simple
User=$INSTALL_USER
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=-/etc/klipperai/klipperai.env
ExecStart=$INSTALL_DIR/.venv/bin/klipperai-agent
Restart=on-failure
RestartSec=3
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF

  run_root install -d -m 755 "$unit_dir"
  backup_file "$unit_path"
  run_root install -m 644 "$temp_file" "$unit_path"
  rm -f "$temp_file"
}
