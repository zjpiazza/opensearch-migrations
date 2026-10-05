#!/usr/bin/env python3
"""Terminal monitor for a focused Buildbarn test run. Closing it never stops tests."""
import argparse
import curses
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

from monitor_state import Monitor


def duration(seconds):
    if seconds is None:
        return '—'
    seconds = max(0, int(seconds))
    return f'{seconds // 3600}h{seconds % 3600 // 60:02}m' if seconds >= 3600 else f'{seconds // 60}m{seconds % 60:02}s'


def rows_for(data, view, query):
    if view == 'active':
        rows = [dict(r, status='RUNNING') for r in data['workers']['running']]
        rows.sort(key=lambda r: -r['seconds'])
    else:
        rows = list(data['tests'])
        if view == 'failures':
            rows = [r for r in rows if r['status'] not in ('PASSED', 'PENDING', 'RUNNING', 'IN_PROGRESS')]
        rank = {'RUNNING': 0, 'IN_PROGRESS': 1, 'FAILED': 2, 'TIMEOUT': 2, 'INCOMPLETE': 2, 'PENDING': 3, 'PASSED': 4}
        rows.sort(key=lambda r: (rank.get(r['status'], 2), -(r.get('seconds') or 0), r['target']))
    return [r for r in rows if query.lower() in (r['target'] + ' ' + r.get('worker', '')).lower()]


def overview(data):
    counts = data['counts']
    failures = sum(n for status, n in counts.items()
                   if status not in ('PASSED', 'PENDING', 'RUNNING', 'IN_PROGRESS'))
    return (f"{data['phase'].upper()}  {duration(data['elapsed_seconds'])}  |  "
            f"Classes {data['completed']}/{data['total']}  Passed {counts.get('PASSED', 0)}  Failed/incomplete {failures}  |  "
            f"Shards {data['shards_completed']}/{data['shards_total']}  "
            f"Running {len(data['workers']['running'])}  Cached {data['cached_shards']}")


def row_text(row, active):
    name = row.get('class', row['target']).split('.')[-1]
    module = row.get('task', '').strip(':').split(':')[0]
    shard = (f"{row['shard_index'] + 1}/{row['shard_count']}" if active else
             f"{row['shards_completed']}/{row['shard_count']}")
    worker = row.get('worker', '')
    return f"{row['status']:<12} {duration(row.get('seconds')):>7} {shard:>7}  {module}/{name}" + (f'  {worker}' if active else '')


def plain(data):
    print(data['run_label'])
    print(overview(data))
    if data['workers']['checked_at'] is None:
        print('Live workers not sampled in --once mode; running counts are unavailable.')
    else:
        for name, pool in sorted(data['pools'].items()):
            print(f"{name}: {pool['ready']}/{pool['total']} ready, {pool.get('running_actions', 0)} active")
    for row in rows_for(data, 'classes', ''):
        print(row_text(row, False))
    if data['workers']['error']:
        print('Worker observation error:', data['workers']['error'])


def interact(screen, monitor):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        for pair, color in enumerate((curses.COLOR_CYAN, curses.COLOR_GREEN, curses.COLOR_RED, curses.COLOR_YELLOW), 1):
            curses.init_pair(pair, color, -1)
    screen.timeout(200)
    view, query, editing, selected, detail = 'active', '', False, 0, False
    data, error, next_read = None, None, 0

    def put(y, text, color=0, bold=False):
        h, w = screen.getmaxyx()
        if not 0 <= y < h or w < 2:
            return
        # Logs and test names must not inject terminal control characters.
        text = ''.join(c if c.isprintable() else ' ' for c in str(text))
        attr = (curses.color_pair(color) if curses.has_colors() else 0) | (curses.A_BOLD if bold else 0)
        try:
            screen.addnstr(y, 0, text, w - 1, attr)
        except curses.error:
            pass

    while True:
        if time.monotonic() >= next_read:
            try:
                data = monitor.snapshot()
                error = None
            except (OSError, ValueError) as exc:
                error = f'Results temporarily unavailable: {exc}'
            next_read = time.monotonic() + 2
        screen.erase()
        h, w = screen.getmaxyx()
        put(0, 'BUILDBARN  /  ' + (data['run_label'] if data else 'Waiting for results'), 1, True)
        if data:
            counts = data['counts']
            failures = sum(n for status, n in counts.items()
                           if status not in ('PASSED', 'PENDING', 'RUNNING', 'IN_PROGRESS'))
            put(1, f"{data['phase'].upper()}  {duration(data['elapsed_seconds'])}  |  "
                   f"Classes {data['completed']}/{data['total']}  Passed {counts.get('PASSED', 0)}  Failed/incomplete {failures}")
            put(2, f"Shards {data['shards_completed']}/{data['shards_total']}  "
                   f"Running {len(data['workers']['running'])}  Cached {data['cached_shards']}")
            y = 3
            for name, pool in sorted(data['pools'].items()):
                put(y, f"{name:<19} {pool['ready']:>2}/{pool['total']:<2} workers ready   "
                       f"{pool.get('running_actions', 0):>2} active test processes")
                y += 1
            observed = data['workers']['checked_at']
            age = f'{time.time() - observed:.0f}s ago' if observed else 'not yet available'
            put(y, f'Workers observed {age}. Active counts exclude input transfer and cleanup.', 4 if not observed else 0)
            y += 1
            warning = error or data['workers']['error'] or data.get('driver_error')
            if warning:
                put(y, warning, 4)
                y += 1
            put(y + 1, f"[1] Active shards  [2] Classes  [3] Failures    View: {view}    Filter: {query}" + ('_' if editing else ''), 1)
            y += 3
            rows = rows_for(data, view, query)
            selected = min(selected, max(0, len(rows) - 1))
            if detail and rows:
                row = rows[selected]
                fields = [('Target', row['target']), ('Status', row['status']),
                          ('Task', row.get('task', '')), ('Class', row.get('class', '')),
                          ('Elapsed', duration(row.get('seconds'))), ('Worker', row.get('worker', ''))]
                if view == 'active':
                    fields.append(('Shard', f"{row['shard_index'] + 1}/{row['shard_count']}"))
                else:
                    fields.append(('Completed shards', f"{row['shards_completed']}/{row['shard_count']}"))
                logpath = Path(data['source']).parent / 'client/execroot/_main/bazel-out/k8-fastbuild/testlogs/external/+_repo_rules+full_suite' / row['target']
                fields.append(('Test outputs', str(logpath)))
                for title, value in fields:
                    put(y, title + ':', 1)
                    y += 1
                    # Wrap long paths without losing their copyable text.
                    for start in range(0, len(value), max(1, w - 3)):
                        if y >= h - 2:
                            break
                        put(y, '  ' + value[start:start + max(1, w - 3)])
                        y += 1
            else:
                put(y, 'STATUS          ELAPSED  SHARDS  TEST' + (' / WORKER' if view == 'active' else ''), 1)
                y += 1
                capacity = max(1, h - y - 2)
                start = max(0, selected - capacity + 1)
                if not rows:
                    put(y, 'No matching active tests.' if view == 'active' else 'No matching results.')
                for index, row in enumerate(rows[start:start + capacity], start):
                    color = 2 if row['status'] == 'PASSED' else 1 if row['status'] in ('RUNNING', 'IN_PROGRESS') else 4 if row['status'] == 'PENDING' else 3
                    put(y, ('> ' if index == selected else '  ') + row_text(row, view == 'active'), color, index == selected)
                    y += 1
            put(h - 2, f"{selected + 1 if rows else 0}/{len(rows)} rows  |  {data['source']}")
        elif error:
            put(2, error, 4)
        put(h - 1, 'q quit monitor (tests continue)  1/2/3 views  ↑/↓ or j/k select  Enter details  / filter  Esc clear/back', 1)
        screen.refresh()
        key = screen.getch()
        if editing:
            if key in (10, 13, 27):
                editing = False
                if key == 27:
                    query = ''
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                query = query[:-1]
            elif 32 <= key <= 126:
                query += chr(key)
            selected = 0
        elif key in (ord('q'), 3):
            return
        elif key in (ord('1'), ord('2'), ord('3')):
            view = {'1': 'active', '2': 'classes', '3': 'failures'}[chr(key)]
            selected, detail = 0, False
        elif key in (curses.KEY_DOWN, ord('j')):
            selected += 1
        elif key in (curses.KEY_UP, ord('k')):
            selected = max(0, selected - 1)
        elif key == curses.KEY_NPAGE:
            selected += max(1, h - 12)
        elif key == curses.KEY_PPAGE:
            selected = max(0, selected - max(1, h - 12))
        elif key in (10, 13):
            detail = not detail
        elif key == ord('/'):
            editing, detail = True, False
        elif key == 27:
            query, detail = '', False
        elif key == ord('r'):
            next_read = 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path, help='Evidence directory from run-focused.py')
    parser.add_argument('--label', default='Long integration tests')
    parser.add_argument('--once', action='store_true', help='Print results once without opening a terminal UI')
    args = parser.parse_args()
    if not (args.run / 'experiment.json').is_file():
        parser.error('--run must point to an existing run-focused.py evidence directory')
    if not args.once and not (sys.stdin.isatty() and sys.stdout.isatty()):
        parser.error('Interactive mode requires a terminal; use --once for a text snapshot')
    monitor = Monitor(SimpleNamespace(seed=args.run / 'results.bep.json', comparisons=args.run,
                                      label=args.label, target=[]))
    try:
        if args.once:
            # Keep the batch snapshot fast and independent of cluster availability.
            plain(monitor.snapshot())
        else:
            monitor.start()
            curses.wrapper(interact, monitor)
    except KeyboardInterrupt:
        pass
    finally:
        monitor.close()


if __name__ == '__main__':
    main()
