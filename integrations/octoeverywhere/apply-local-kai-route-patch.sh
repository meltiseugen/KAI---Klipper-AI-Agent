#!/bin/sh
# Stable entry point for manual application, read-only inspection and restoration.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec sh "$SCRIPT_DIR/run-maintenance.sh" "$@"
