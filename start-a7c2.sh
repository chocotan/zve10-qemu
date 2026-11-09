#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$root/start.sh" --a7c2-assets "$root/incoming/a7c2-menu-resources-2.01-v1.zip" "$@"
