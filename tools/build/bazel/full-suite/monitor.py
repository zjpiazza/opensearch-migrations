#!/usr/bin/env python3
"""Local, read-only live dashboard for the Buildbarn full-suite experiment."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[4]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--seed', type=Path, required=True, help='Seed BEP file')
parser.add_argument('--comparisons', type=Path, required=True)
parser.add_argument('--port', type=int, default=8765)
args = parser.parse_args()
args.seed = args.seed.resolve()
args.comparisons = args.comparisons.resolve()
inventory = json.loads((ROOT / 'build/full-suite/inventory.json').read_text())['targets']
workers = {'running': [], 'checked_at': None, 'error': None}
lock = threading.Lock()

# Inspect only the exported wrapper's declared spec and process start time.
# Do not expose environments or complete JVM command lines.
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
  rows.append({'target':spec.stem+('__'+a[3] if a[3] else ''),'task':data['task'],'class':a[3],'seconds':max(0,uptime-start)})
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


def poll_workers():
    while True:
        try:
            pods = json.loads(kubectl('get', 'pods', '-l', 'app=worker,instance=integration', '-o', 'json'))
            with ThreadPoolExecutor(max_workers=3) as pool:
                result = list(pool.map(probe, [p['metadata']['name'] for p in pods['items']]))
            with lock:
                workers.update(running=[row for group in result for row in group], checked_at=time.time(), error=None)
        except Exception as error:
            with lock:
                workers['error'] = type(error).__name__ + ': worker polling unavailable'
        time.sleep(10)


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


def snapshot():
    phase = {'phase': 'waiting-for-seed'}
    status = args.comparisons / 'status.json'
    if status.exists():
        phase = json.loads(status.read_text())
    current = phase['phase']
    candidates = [args.seed, *args.comparisons.glob('*/results.bep.json')]
    bep = max((p for p in candidates if p.exists()), key=lambda p: p.stat().st_mtime)
    run_label = 'Initial full test run' if bep == args.seed else bep.parent.name.capitalize() + ' comparison'
    events = read_events(bep)
    results = {}
    for event in events:
        if 'testResult' not in event:
            continue
        result = event['testResult']
        target = event['id']['testResult']['label'].split(':', 1)[1]
        results[target] = {'status': result['status'],
                           'seconds': int(result.get('testAttemptDurationMillis', 0)) / 1000,
                           'cached': bool(result.get('cachedLocally') or result.get('executionInfo', {}).get('cachedRemotely'))}
    with lock:
        live = json.loads(json.dumps(workers))
    active = {row['target']: row for row in live['running']}
    rows = []
    for item in inventory:
        target = item['target']
        row = dict(item, status='PENDING', seconds=None, cached=False)
        if target in results:
            row.update(results[target])
        elif target in active:
            row.update(active[target], status='RUNNING')
        rows.append(row)
    counts = Counter(row['status'] for row in rows)
    start = next((e['started'].get('startTimeMillis') for e in events if 'started' in e), None)
    end = next((e['finished'].get('finishTimeMillis') for e in events if 'finished' in e), None)
    return {'phase': current, 'run_label': run_label, 'source': str(bep.relative_to(ROOT)), 'total': len(rows),
            'completed': len(results), 'counts': dict(counts),
            'cached': sum(r['cached'] for r in rows), 'tests': rows,
            'elapsed_seconds': ((int(end) / 1000 if end else time.time()) - int(start) / 1000) if start else None,
            'finished': any('finished' in e for e in events), 'workers': live,
            'driver_error': phase.get('error'), 'updated_at': time.time()}


HTML = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Buildbarn · Live tests</title><style>
body{font:15px system-ui,sans-serif;background:#111827;color:#e5e7eb;margin:30px auto;max-width:1250px;padding:0 20px}h1{font-size:26px;margin-bottom:5px}p{color:#aeb9cb}.cards{display:flex;gap:14px;flex-wrap:wrap}.card{background:#1f2937;padding:16px 23px;border-radius:10px;min-width:105px}.card b{display:block;font-size:29px}.card span{color:#aeb9cb}progress{width:100%;height:14px;margin:22px 0;accent-color:#34d399}table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:11px 9px;text-align:left;border-bottom:1px solid #374151;vertical-align:top}small{display:block;color:#9ca3af;word-break:break-word}td.name{overflow-wrap:anywhere}th{color:#9ca3af}input,select{background:#1f2937;color:white;border:1px solid #4b5563;border-radius:6px;padding:9px;margin:10px 10px 12px 0}.PASSED{color:#34d399}.RUNNING{color:#60a5fa}.FAILED,.TIMEOUT,.INCOMPLETE{color:#fb7185}.PENDING{color:#9ca3af}#error{color:#fbbf24}#running{background:#18263c;border-radius:10px;padding:6px 16px;margin-bottom:20px}#running li{padding:6px 0;overflow-wrap:anywhere}.muted{color:#9ca3af;font-size:13px}</style>
<h1>Buildbarn · Live tests</h1><p id="phase">Connecting…</p><div class="cards" id="cards"></div><progress id="progress" max="439" value="0"></progress>
<div id="running"><strong>Executing on the integration workers</strong><ul id="active"></ul><div class="muted" id="worker-time"></div></div>
<div id="error"></div><input id="search" placeholder="Search test or Gradle task" size="38"><select id="filter"><option value="all">All tests</option><option value="RUNNING">Running</option><option value="failures">Failures</option><option value="PASSED">Passed</option><option value="PENDING">Pending</option></select>
<table><thead><tr><th>Status</th><th>Test class / Gradle task</th><th>Duration</th><th>Result reuse</th></tr></thead><tbody id="tests"></tbody></table><p class="muted" id="updated"></p>
<script>
let data;const $=id=>document.getElementById(id);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const duration=s=>s==null?'—':`${Math.floor(s/60)}m ${Math.floor(s%60)}s`;
function render(){if(!data)return;const c=data.counts;const bad=data.completed-(c.PASSED||0);$('phase').textContent=data.run_label+' · '+duration(data.elapsed_seconds)+' elapsed'+(data.finished?' · finished':'');
$('cards').innerHTML=[[data.completed+'/'+data.total,'Completed'],[c.PASSED||0,'Passed'],[bad,'Failed / incomplete'],[c.RUNNING||0,'Running'],[data.cached,'Cached results']].map(([n,l])=>`<div class="card"><b>${esc(n)}</b><span>${l}</span></div>`).join('');$('progress').value=data.completed;$('progress').max=data.total;
$('active').innerHTML=data.workers.running.map(r=>`<li><b>${esc(r.class||r.task)}</b> · ${duration(r.seconds)}<small>${esc(r.task)} · ${esc(r.worker)}</small></li>`).join('')||'<li>No active test process reported.</li>';
$('worker-time').textContent=data.workers.checked_at?'Workers checked '+new Date(data.workers.checked_at*1000).toLocaleTimeString()+' · every 10 seconds':'';
$('error').textContent=[data.driver_error,data.workers.error].filter(Boolean).join(' · ');
const q=$('search').value.toLowerCase(),f=$('filter').value;const rank=s=>s==='RUNNING'?0:s==='PASSED'?3:s==='PENDING'?2:1;
const rows=data.tests.filter(r=>(f==='all'||(f==='failures'?!['RUNNING','PASSED','PENDING'].includes(r.status):r.status===f))&&(r.target+' '+r.task).toLowerCase().includes(q)).sort((a,b)=>rank(a.status)-rank(b.status)||(a.class||a.task).localeCompare(b.class||b.task));
$('tests').innerHTML=rows.map(r=>`<tr><td class="${esc(r.status)}">${esc(r.status)}</td><td class="name">${esc(r.class||r.task)}<small>${esc(r.task)}</small></td><td>${duration(r.seconds)}</td><td>${r.cached?'Cache hit':r.status==='PASSED'?'Executed':'—'}</td></tr>`).join('');$('updated').textContent='Results refreshed '+new Date(data.updated_at*1000).toLocaleTimeString()+' · '+data.source;}
async function refresh(){try{let r=await fetch('/api/status');if(!r.ok)throw new Error('HTTP '+r.status);data=await r.json();render()}catch(e){$('error').textContent='Monitor connection lost: '+e.message}}
$('search').oninput=render;$('filter').onchange=render;refresh();setInterval(refresh,3000);
</script></html>'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if self.path == '/api/status':
                body = json.dumps(snapshot()).encode()
                content_type = 'application/json'
            elif self.path == '/':
                body = HTML.encode()
                content_type = 'text/html; charset=utf-8'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (OSError, ValueError):
            self.send_error(503, 'Results are temporarily unavailable')

    def log_message(self, *_args):
        pass


if __name__ == '__main__':
    threading.Thread(target=poll_workers, daemon=True).start()
    print(f'Live tests: http://127.0.0.1:{args.port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
