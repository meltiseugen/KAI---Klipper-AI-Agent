#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

write_env_file() {
  local temp_file
  temp_file="$(mktemp)"

  {
    printf 'KLIPPERAI_ENVIRONMENT="%s"\n' "$(escape_env_value "production")"
    printf 'KLIPPERAI_CONFIG_FILE="%s"\n' "$(escape_env_value "$KLIPPERAI_CFG_PATH")"
    printf 'KLIPPERAI_SERVICE_USER="%s"\n' "$(escape_env_value "$INSTALL_USER")"
    printf 'KLIPPERAI_PROJECT_CHECKOUT_PATH="%s"\n' "$(escape_env_value "$INSTALL_DIR")"
    printf 'KLIPPERAI_NGINX_SERVER_BLOCK_PATH="%s"\n' "$(escape_env_value "$KLIPPERAI_NGINX_SERVER_BLOCK_PATH")"
    printf 'KLIPPERAI_HOST="%s"\n' "$(escape_env_value "127.0.0.1")"
    printf 'KLIPPERAI_MOONRAKER_URL="%s"\n' "$(escape_env_value "$KLIPPERAI_MOONRAKER_URL")"
    printf 'KLIPPERAI_MANAGED_CONFIG_DIR_NAME="%s"\n' "$(escape_env_value "$KLIPPERAI_MANAGED_CONFIG_DIR_NAME")"
    printf 'KLIPPERAI_SESSION_TTL_SECONDS="%s"\n' "$(escape_env_value "3600")"
    printf 'KLIPPERAI_MOONRAKER_SERVICE_NAME="%s"\n' "$(escape_env_value "$KLIPPERAI_MOONRAKER_SERVICE_NAME")"
    printf 'KLIPPERAI_KLIPPER_SERVICE_NAME="%s"\n' "$(escape_env_value "$KLIPPERAI_KLIPPER_SERVICE_NAME")"
    printf 'KLIPPERAI_SYSTEM_STATUS_ARTIFACT_CHAR_LIMIT="%s"\n' "$(escape_env_value "$KLIPPERAI_SYSTEM_STATUS_ARTIFACT_CHAR_LIMIT")"
    printf 'KLIPPERAI_JOURNAL_ARTIFACT_CHAR_LIMIT="%s"\n' "$(escape_env_value "$KLIPPERAI_JOURNAL_ARTIFACT_CHAR_LIMIT")"
    printf 'KLIPPERAI_SYSTEM_COMMAND_TIMEOUT_SECONDS="%s"\n' "$(escape_env_value "$KLIPPERAI_SYSTEM_COMMAND_TIMEOUT_SECONDS")"
    printf 'KLIPPERAI_OPENAI_API_KEY="%s"\n' "$(escape_env_value "$KLIPPERAI_OPENAI_API_KEY")"
  } >"$temp_file"

  run_root install -d -m 755 /etc/klipperai
  backup_file /etc/klipperai/klipperai.env
  run_root install -m 600 "$temp_file" /etc/klipperai/klipperai.env
  rm -f "$temp_file"
}

write_cfg_file() {
  local temp_file
  temp_file="$(mktemp)"

  cat >"$temp_file" <<EOF
# KlipperAI runtime configuration
#
# This file is intended to be easy to edit from Mainsail.
#
# Notes:
# - Restart klipperai-agent after editing this file.
# - Hidden install metadata is stored in /etc/klipperai/klipperai.env.
# - Keep API keys in /etc/klipperai/klipperai.env, not in this file.

[install]
printer_data_root: $KLIPPERAI_PRINTER_DATA_ROOT  # Printer data root. Example: /home/biqu/printer_data
mainsail_config_dir: $KLIPPERAI_MAINSAIL_CONFIG_DIR  # Config dir that contains the managed klipperai/ folder. Example: /home/biqu/printer_data/config

[printer_identity]
firmware_flavor:  # Main firmware flavor. Examples: Kalico, Klipper
firmware_version:  # Firmware version string. Examples: v2026.05.00-4, v0.13.0-221
host_model:  # Host computer / SBC model. Examples: BigTreeTech CB1, Raspberry Pi 4 Model B
host_distribution:  # Linux distribution on the host. Examples: Debian GNU/Linux 11 (bullseye) 11, Armbian 24.2 Bookworm
mainboard:  # Printer controller board model. Examples: BTT Manta E3EZ, BTT Octopus Pro
toolhead:  # Toolhead board / electronics model. Examples: BTT EBB36, FYSETC H36 Combo, Orbiter Nitehawk

[printer_capabilities]
probe_type: none  # Probe family. Examples: none, bltouch, beacon, eddy
accelerometer: none  # Accelerometer family. Examples: none, adxl345, lis2dw
filament_sensor: none  # Filament sensor family. Examples: none, switch, motion
bed_mesh_configured: false  # Whether bed mesh is configured. Examples: true, false
input_shaper_configured: false  # Whether input shaper is configured. Examples: true, false
canbus_enabled: false  # Whether the printer uses CAN anywhere. Examples: true, false
addons:  # Comma-separated addons. Examples: OctoEverywhere, KAMP, KlipperScreen

[config_context]
root_config_file:  # Root Klipper config entry point. Examples: printer.cfg, machines/voron/printer-main.cfg
ignore_globs:  # Comma-separated exclude globs. Examples: backups/**, archive/**, timelapse/**

[server]
port: $KLIPPERAI_PORT  # Local agent port. Examples: 8811, 9911
root_path: $KLIPPERAI_ROOT_PATH  # Public reverse-proxy path. Examples: /klipperai, /ai
data_dir: $KLIPPERAI_DATA_DIR  # Local runtime data directory. Examples: /var/lib/klipperai, /srv/klipperai/data
checkpoint_db: $KLIPPERAI_CHECKPOINT_DB  # Legacy reserved path; investigation storage uses data_dir/investigations.sqlite3. Examples: /var/lib/klipperai/checkpoints.sqlite, /srv/klipperai/checkpoints.sqlite
enable_write_actions: $KLIPPERAI_ENABLE_WRITE_ACTIONS  # Compatibility setting; runtime always keeps printer writes disabled.

[chat]
conversation_history_pairs: 10  # Previous user/assistant pairs sent with each request. Use 0 to disable. Examples: 0, 5, 10
memory_cross_chat: true  # Reuse dated evidence from other chats about this printer.
memory_retention_days: 90  # Retain application-owned investigation records for this many days.

[llm]
llm_provider: $KLIPPERAI_LLM_PROVIDER  # Chat backend provider. Examples: stub, openai
openai_model: $KLIPPERAI_OPENAI_MODEL  # OpenAI model when provider = openai. Examples: gpt-5.4-mini, gpt-5.5

[agent]
agent_enabled: true  # Use iterative tool calling with the OpenAI provider.
web_search_enabled: true  # Allow public documentation search; uses provider credits.
web_search_domains:  # Optional comma-separated domains without https://.
agent_max_steps: 8
agent_max_tool_calls: 12
agent_tool_timeout_seconds: 30
agent_run_timeout_seconds: 180
agent_max_context_chars: 120000
agent_max_result_chars: 16000
agent_max_output_tokens: 6000

[logs]
collect_host_logs: $KLIPPERAI_COLLECT_HOST_LOGS  # Whether to collect host logs. Examples: true, false
logs_dir_path: $KLIPPERAI_LOGS_DIR_PATH  # Directory that contains Klipper, Moonraker, and KlipperAI logs. Examples: /home/biqu/printer_data/logs, /srv/printer_data/logs
agent_log_file_name: $KLIPPERAI_AGENT_LOG_FILE_NAME  # KlipperAI runtime log filename. Examples: klipperai.log, ai-agent.log
agent_log_level: $KLIPPERAI_AGENT_LOG_LEVEL  # Runtime log verbosity. Examples: INFO, DEBUG, WARNING
log_tail_lines_default: $KLIPPERAI_LOG_TAIL_LINES_DEFAULT  # Default tail length when no override exists. Examples: 100, 200
excluded_logs:  # Comma-separated denylist by name, stem, or glob. Examples: klipperai.log, crowsnest, *_debug.log

[log_tail_lines]
klippy: 100  # Tail lines for klippy.log
moonraker: 200  # Tail lines for moonraker.log
klipperai: 100  # Tail lines for klipperai.log

[system]
collect_systemd_diagnostics: $KLIPPERAI_COLLECT_SYSTEMD_DIAGNOSTICS  # Whether to collect systemctl and journal diagnostics. Examples: true, false
journal_lines: $KLIPPERAI_JOURNAL_LINES  # Journal lines to include per service. Examples: 100, 200, 400
EOF

  run_root install -d -o "$INSTALL_USER" -g "$INSTALL_GROUP" -m 755 "$KLIPPERAI_MANAGED_CONFIG_DIR_PATH"
  backup_file "$KLIPPERAI_CFG_PATH"
  run_root install -o "$INSTALL_USER" -g "$INSTALL_GROUP" -m 664 "$temp_file" "$KLIPPERAI_CFG_PATH"
  rm -f "$temp_file"
}
