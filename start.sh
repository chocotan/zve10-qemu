#!/usr/bin/env bash
# Ready-to-run Linux x86_64 bundle entry; defaults to the original Sony menu.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"
if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" && " $* " != *" --headless "* ]]; then
    echo '没有图形会话，使用菜单 headless 验收；在桌面终端运行可打开窗口。' >&2
    set -- --headless "$@"
fi
python3 - "$@" <<'PY'
import importlib
import platform
import sys
if platform.system() != 'Linux' or platform.machine() != 'x86_64':
    raise SystemExit('This ready-to-run bundle requires Linux x86_64.')
if sys.version_info < (3, 11):
    raise SystemExit('Python 3.11+ is required.')
for name in ('PIL', 'elftools', 'capstone'):
    try: importlib.import_module(name)
    except ImportError:
        raise SystemExit('Missing Python dependency: ' + name + '\nRun: python3 -m pip install -r requirements.txt')
if '--headless' not in sys.argv:
    try: import tkinter
    except ImportError:
        raise SystemExit('Tk is required for the window; install your distribution Tk package or use --headless.')
PY
exec "$root/start-zve10-menu.sh" "$@"
