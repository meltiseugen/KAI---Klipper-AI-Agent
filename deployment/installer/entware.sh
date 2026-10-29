#!/bin/sh
# Fresh Entware bootstrap only. Existing /opt content is never deleted or replaced.

entware_download() {
  # Only checksum-pinned bootstrap assets may use a downloader without a CA store.
  # The checksum is verified here before the caller can install or execute a byte.
  entware_downloaded=no
  if bootstrap_command_path curl >/dev/null; then
    if curl --fail --location --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 120 "$1" -o "$2" ||
       curl --insecure --fail --location --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 120 "$1" -o "$2"; then entware_downloaded=yes; fi
  fi
  if [ "$entware_downloaded" = no ] && bootstrap_command_path wget >/dev/null; then
    if wget -O "$2" "$1" || wget --no-check-certificate -O "$2" "$1"; then entware_downloaded=yes; fi
  fi
  [ "$entware_downloaded" = yes ] || { bootstrap_error 'No HTTPS downloader could fetch the pinned bootstrap assets.'; return 1; }
  printf '%s  %s\n' "$3" "$2" | sha256sum -c - || { bootstrap_error 'Bootstrap checksum failed; the download was not trusted.'; return 1; }
}

bootstrap_entware() (
  [ "$(id -u)" -eq 0 ] || { bootstrap_error 'Bootstrapping Entware on a Creality host requires root.'; exit 1; }
  case "$(uname -m)" in
    mips|mipsel)
      [ "$(dd if=/bin/sh bs=1 skip=5 count=1 2>/dev/null)" = "$(printf '\001')" ] || {
        bootstrap_error 'The Creality Entware bootstrap requires little-endian MIPS.'; exit 1;
      }
      entware_feed=mipselsf-k3.4
      entware_arch='arch mipsel-3x 150
arch mipsel-3.4 160'
      entware_hash=6a84ba53d2542acb5cc3efa59cc98fd80de883de705ce9bc8a41d58b8345f017
      ;;
    aarch64)
      entware_feed=aarch64-k3.10
      entware_arch='arch aarch64-3.10 160'
      entware_hash=1c59274bd25080b869f376788795f5319d0d22e91f325f74ce98a7d596f68015
      ;;
    *) bootstrap_error 'No reviewed Entware bootstrap exists for this CPU architecture.'; exit 1 ;;
  esac
  if [ -L /usr/data/opt ] || { [ -L /opt ] && [ "$(readlink /opt)" != /usr/data/opt ]; }; then
    bootstrap_error 'Existing /opt layout differs; it was preserved.'; exit 1
  fi
  for entware_directory in /opt /usr/data/opt; do
    if [ -e "$entware_directory" ] && {
      [ ! -d "$entware_directory" ] || [ -n "$(find "$entware_directory/" -mindepth 1 -maxdepth 1 -print -quit)" ];
    }; then
      bootstrap_error 'Existing /opt content has no usable opkg; it was preserved.'; exit 1
    fi
  done
  entware_temp="$(mktemp -d /tmp/klipperai-entware.XXXXXX)" || exit 1
  trap 'rm -f "$entware_temp/opkg" "$entware_temp/curl" "$entware_temp/ca.pem" "$entware_temp/wget"; rmdir "$entware_temp"' EXIT
  entware_download "https://bin.entware.net/$entware_feed/installer/opkg" "$entware_temp/opkg" "$entware_hash" || exit 1
  entware_download https://curl.se/ca/cacert-2026-10-20.pem "$entware_temp/ca.pem" 796f1389bfea13c0ed78f663b765baaff54a508e5483786bd6ece73c5e3e3cbe || exit 1
  ENTWARE_BOOTSTRAP_CURL="$(bootstrap_command_path curl || true)"
  if [ -z "$ENTWARE_BOOTSTRAP_CURL" ] || ! "$ENTWARE_BOOTSTRAP_CURL" --version >/dev/null 2>&1; then
    [ "$entware_feed" = mipselsf-k3.4 ] || { bootstrap_error 'This architecture needs a working curl to bootstrap verified package downloads.'; exit 1; }
    entware_download https://raw.githubusercontent.com/Guilouz/Creality-Helper-Script/7693c29676c0b138ec4f32b90d5c6f82bd2b2e13/files/fixes/curl "$entware_temp/curl" 5f561a490df7053bd36d087b78e11fc61a8cbbc821427aa9625324eb0043045a || exit 1
    chmod 755 "$entware_temp/curl"
    ENTWARE_BOOTSTRAP_CURL="$entware_temp/curl"
  fi
  "$ENTWARE_BOOTSTRAP_CURL" --version >/dev/null || exit 1
  ENTWARE_BOOTSTRAP_CA="$entware_temp/ca.pem"
  export ENTWARE_BOOTSTRAP_CURL ENTWARE_BOOTSTRAP_CA
  # Entware opkg delegates downloads to wget. Use authenticated HTTPS even before
  # its own wget-ssl/CA packages exist; never pass a TLS bypass to package downloads.
  cat > "$entware_temp/wget" <<'EOF'
#!/bin/sh
output=
url=
while [ "$#" -gt 0 ]; do
  case "$1" in
    -O) output=$2; shift 2 ;;
    -q|--quiet|--passive-ftp|--no-cache|-c) shift ;;
    -T|-t) shift 2 ;;
    --timeout=*|--tries=*) shift ;;
    https://*) url=$1; shift ;;
    *) exit 2 ;;
  esac
done
[ -n "$output" ] && [ -n "$url" ] || exit 2
exec "$ENTWARE_BOOTSTRAP_CURL" --fail --location --proto '=https' --cacert "$ENTWARE_BOOTSTRAP_CA" --connect-timeout 15 --max-time 180 "$url" -o "$output"
EOF
  chmod 755 "$entware_temp/wget"
  mkdir -p /usr/data/opt || exit 1
  if [ ! -L /opt ]; then
    [ ! -d /opt ] || rmdir /opt || exit 1
    ln -s /usr/data/opt /opt || exit 1
  fi
  mkdir -p /opt/bin /opt/etc /opt/lib/opkg /opt/tmp /opt/var/lock || exit 1
  cp "$entware_temp/opkg" /opt/bin/opkg && chmod 755 /opt/bin/opkg || exit 1
  cat > /opt/etc/opkg.conf <<EOF
src/gz entware https://bin.entware.net/$entware_feed
dest root /
dest ram /opt/tmp
lists_dir ext /opt/var/opkg-lists
option tmp_dir /opt/tmp
arch all 100
$entware_arch
EOF
  unset LD_LIBRARY_PATH LD_PRELOAD
  PATH="$entware_temp:/opt/bin:/opt/sbin:$PATH"
  export PATH
  /opt/bin/opkg update && /opt/bin/opkg install entware-opt wget-ssl ca-bundle ca-certificates || exit 1
  chmod 1777 /opt/tmp
  for entware_account in passwd group shells shadow gshadow; do
    [ ! -f "/etc/$entware_account" ] || [ -e "/opt/etc/$entware_account" ] ||
      ln -s "/etc/$entware_account" "/opt/etc/$entware_account" || exit 1
  done
  if [ ! -e /etc/init.d/S50unslung ] && [ ! -e /etc/init.d/S49klipperai-entware ]; then
    cat > /etc/init.d/S49klipperai-entware <<'EOF'
#!/bin/sh
# Entware prerequisites installed by KlipperAI; retained when the app is removed.
if [ -x /opt/etc/init.d/rc.unslung ]; then exec /opt/etc/init.d/rc.unslung "$@"; fi
EOF
    chmod 755 /etc/init.d/S49klipperai-entware
  fi
)
