"""Shared read-only Buildbarn/Bazel monitor state; no UI or server on import."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[4]

# Inspect only the exported wrapper's declared spec and process start time.
# Read only shard coordinates from the environment; do not expose other values
# or complete JVM command lines.
PROBE = '''import json,os,time
from pathlib import Path
rows=[]
uptime=float(Path('/proc/uptime').read_text().split()[0])
for p in Path('/proc').glob('[0-9]*/cmdline'):
 try:
  a=p.read_bytes().decode().split('\\0')
  if len(a)<4 or not a[1].endswith('/full-suite/runner.py'): continue
  spec=Path(a[2]); data=json.loads(spec.read_text())
  start=float((p.parent/'stat').read_text().rsplit(')',1)[1].split()[19])/os.sysconf('SC_CLK_TCK')
  coordinates={}
  for entry in (p.parent/'environ').read_bytes().split(b'\\0'):
   key,_,value=entry.partition(b'=')
   if key in (b'TEST_SHARD_INDEX',b'TEST_TOTAL_SHARDS'): coordinates[key.decode()]=int(value)
  rows.append({'target':spec.stem+('__'+a[3] if a[3] else ''),'task':data['task'],'class':a[3],'seconds':max(0,uptime-start),'shard_index':coordinates.get('TEST_SHARD_INDEX',0),'shard_count':coordinates.get('TEST_TOTAL_SHARDS',1)})
 except (OSError,ValueError,IndexError,UnicodeError): pass
print(json.dumps(rows))
'''


def kubectl(*command):
    return subprocess.check_output(['kubectl', '--context', 'do-atl1-bazel', '-n',
                                    'migrations-buildbarn', *command], text=True,
                                   stderr=subprocess.PIPE, timeout=12)


def probe(pod):
    rows = json.loads(kubectl('exec', pod, '-c', 'runner', '--', 'python3', '-c', PROBE))
    for row in rows:
        row['worker'] = pod
    return rows


def read_events(path):
    if not path.exists():
        return []
    events = []
    for line in path.read_text().splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # The producer may still be writing the last line.
    return events


class Monitor:
    def __init__(self, args):
        self.args = args
        args.seed = args.seed.resolve()
        args.comparisons = args.comparisons.resolve()
        path = args.comparisons / 'inventory.json'
        if not path.exists():
            path = ROOT / 'build/full-suite/inventory.json'
        self.inventory = json.loads(path.read_text())['targets']
        targets = args.target
        experiment = args.comparisons / 'experiment.json'
        if not targets and experiment.exists():
            targets = [t['target'] for t in json.loads(experiment.read_text())['selected_targets']]
        if targets:
            selected = {t.split(':', 1)[-1] for t in targets}
            self.inventory = [t for t in self.inventory if t['target'] in selected]
            if {t['target'] for t in self.inventory} != selected:
                raise ValueError('Unknown focused target')
        self.workers = {'running': [], 'checked_at': None, 'error': None,
                        'ready': 0, 'total': 0, 'pending': [], 'pools': {}}
        self.lock = threading.Lock()
        self.stop = threading.Event()

    def start(self):
        threading.Thread(target=self.poll_workers, daemon=True).start()

    def close(self):
        self.stop.set()

    def poll_workers(self):
        while not self.stop.is_set():
            try:
                pods = json.loads(kubectl('get', 'pods', '-l', 'app=worker', '-o', 'json'))
                items = [p for p in pods['items'] if not p['metadata'].get('deletionTimestamp')
                         and p.get('status', {}).get('phase') not in ('Failed', 'Succeeded')]
                ready = [p for p in items if any(c['type'] == 'Ready' and c['status'] == 'True'
                                                for c in p.get('status', {}).get('conditions', []))]
                pending = [p['metadata']['name'] for p in items if p not in ready]
                pools = {}
                for pod in items:
                    name = pod['metadata']['labels'].get('instance', 'unknown')
                    name = 'lightweight' if name == 'ubuntu22-04' else name
                    pool = pools.setdefault(name, {'ready': 0, 'total': 0})
                    pool['total'] += 1
                    pool['ready'] += int(pod in ready)
                result = []
                errors = []
                with ThreadPoolExecutor(max_workers=32) as pool:
                    futures = [(p['metadata']['name'], pool.submit(probe, p['metadata']['name'])) for p in ready]
                    for name, future in futures:
                        try:
                            result.extend(future.result())
                        except Exception:
                            errors.append(name)
                with self.lock:
                    self.workers.update(running=result, checked_at=time.time(),
                                   error=('Worker polling unavailable: ' + ', '.join(errors)) if errors else None,
                                   ready=len(ready), total=len(items), pending=pending, pools=pools)
            except Exception as error:
                with self.lock:
                    self.workers['error'] = type(error).__name__ + ': worker polling unavailable'
            self.stop.wait(10)


    def snapshot(self):
        phase = {'phase': 'waiting-for-seed'}
        status = self.args.comparisons / 'status.json'
        if status.exists():
            phase = json.loads(status.read_text())
        current = phase['phase']
        candidates = [self.args.seed, *self.args.comparisons.glob('*/results.bep.json')]
        bep = max((p for p in candidates if p.exists()), key=lambda p: p.stat().st_mtime, default=self.args.seed)
        run_label = self.args.label if bep == self.args.seed else bep.parent.name.capitalize() + ' comparison'
        events = read_events(bep)
        interrupted = current in ('interrupted', 'cancelled')
        terminal = interrupted or any('finished' in e for e in events)
        results = {}
        for event in events:
            if 'testResult' not in event:
                continue
            result = event['testResult']
            target = event['id']['testResult']['label'].split(':', 1)[1]
            shard = event['id']['testResult'].get('shard', 1)
            results.setdefault(target, {})[shard] = {'status': result['status'],
                               'seconds': int(result.get('testAttemptDurationMillis', 0)) / 1000,
                               'cached': bool(result.get('cachedLocally') or result.get('executionInfo', {}).get('cachedRemotely'))}
        with self.lock:
            live = json.loads(json.dumps(self.workers))
        selected = {item['target'] for item in self.inventory}
        live['running'] = [row for row in live['running'] if row['target'] in selected]
        active = {}
        for row in live['running']:
            active.setdefault(row['target'], []).append(row)
        summaries = {e['id']['testSummary']['label'].split(':', 1)[1]: e['testSummary']
                     for e in events if 'testSummary' in e}
        rows = []
        for item in self.inventory:
            target = item['target']
            row = dict(item, status='PENDING', seconds=None, cached=False)
            completed = list(results.get(target, {}).values())
            running = active.get(target, [])
            row.update(shards_completed=len(completed), shards_running=len(running),
                       shard_count=item.get('shard_count', 1))
            if completed or running:
                row['seconds'] = max(r['seconds'] for r in completed + running)
            if target in summaries:
                summary = summaries[target]
                row['status'] = summary['overallStatus']
                row['cached'] = bool(completed) and all(r['cached'] for r in completed)
                if summary.get('lastStopTimeMillis') and summary.get('firstStartTimeMillis'):
                    row['seconds'] = (int(summary['lastStopTimeMillis']) - int(summary['firstStartTimeMillis'])) / 1000
            elif running:
                row.update(status='RUNNING', worker=', '.join(r['worker'] for r in running))
            elif completed and not terminal:
                row['status'] = 'IN_PROGRESS'
            elif terminal:
                row['status'] = 'INCOMPLETE'
            rows.append(row)
        counts = Counter(row['status'] for row in rows)
        pools = live['pools']
        for row in rows:
            name = row.get('exec_properties', {}).get('workload', 'lightweight')
            pool = pools.setdefault(name, {'ready': 0, 'total': 0})
            pool[row['status']] = pool.get(row['status'], 0) + 1
            pool['running_actions'] = pool.get('running_actions', 0) + row['shards_running']
        start = next((e['started'].get('startTimeMillis') for e in events if 'started' in e), None)
        end = next((e['finished'].get('finishTimeMillis') for e in events if 'finished' in e), None)
        return {'phase': current, 'run_label': run_label, 'source': str(bep), 'total': len(rows),
                'completed': sum(row['target'] in summaries for row in rows), 'counts': dict(counts),
                'shards_completed': sum(row['shards_completed'] for row in rows),
                'shards_total': sum(row['shard_count'] for row in rows),
                'cached_shards': sum(r['cached'] for target, shards in results.items()
                                     if target in selected for r in shards.values()),
                'cached': sum(r['cached'] for r in rows), 'tests': rows,
                'elapsed_seconds': ((int(end) / 1000 if end else time.time()) - int(start) / 1000)
                                   if start and (end or not interrupted) else None,
                'finished': any('finished' in e for e in events), 'workers': live, 'pools': pools,
                'driver_error': phase.get('error'), 'updated_at': time.time()}
