#!/usr/bin/env python3
"""Validate saved live boot checks; does not accept a shell prompt as UI success."""
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[1]
clock_path = root / 'evidence/clock-sleep-check.log'
ui_path = root / 'evidence/ui-v2-utm-timers.log'
if not clock_path.exists() or not ui_path.exists():
    print('SKIP: this check validates saved run logs under evidence/, which are not part of the repository')
    sys.exit(0)
clock = clock_path.read_text(errors='replace')
assert all(mark in clock for mark in ('TIMER_CHECK_BEGIN', 'TIMER_SLEEP_1_DONE', 'TIMER_SLEEP_3_DONE'))
ticks = [int(n) for n in re.findall(r'153:\s+(\d+)\s+GIC\s+tick0', clock)]
assert len(ticks) >= 2 and ticks[-1] > ticks[0] + 200, ticks
ui = ui_path.read_text(errors='replace')
assert 'UI_AFTER_SLEEP_3' in ui
assert re.search(r'158:\s+[1-9]\d*\s+GIC\s+hwtimer0', ui)
assert 'DMP.cpu.initialize=0x1' in ui
assert 'BUG: Bad page map' not in ui
if len(sys.argv) > 1:
    thread = Path(sys.argv[1]).read_text(errors='replace')
    assert 'THREAD_CREATE=0' in thread
    assert 'THREAD_WORKER_ENTER' in thread
    assert 'THREAD_JOIN=0 VALUE=0x1234' in thread
    assert 'THREAD_TEST_EXIT=0' in thread
print('PASS: Linux sleep/tick, Sony UTM IRQ, native software-backend initialization' + (' and pthread_join' if len(sys.argv) > 1 else ''))
