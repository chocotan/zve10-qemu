#!/usr/bin/env bash
# Default: original ZV-E10 menu. A7C2 resources are only used when requested.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$root/scripts/menu_run.py" "$@"
