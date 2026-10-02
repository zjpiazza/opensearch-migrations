#!/usr/bin/env python3
"""Legacy local web view; prefer tui.py for terminal monitoring."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from monitor_state import Monitor

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--seed', type=Path, required=True, help='Seed BEP file')
parser.add_argument('--comparisons', type=Path, required=True)
parser.add_argument('--port', type=int, default=8765)
parser.add_argument('--label', default='Initial full test run', help='Label for the seed run')
parser.add_argument('--target', action='append', default=[], help='Show only this exported target; repeat for a focused experiment')
args = parser.parse_args()
monitor = Monitor(args)
HTML = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Buildbarn · Live tests</title><style>
body{font:15px system-ui,sans-serif;background:#111827;color:#e5e7eb;margin:30px auto;max-width:1250px;padding:0 20px}h1{font-size:26px;margin-bottom:5px}p{color:#aeb9cb}.cards{display:flex;gap:14px;flex-wrap:wrap}.card{background:#1f2937;padding:16px 23px;border-radius:10px;min-width:105px}.card b{display:block;font-size:29px}.card span{color:#aeb9cb}progress{width:100%;height:14px;margin:22px 0;accent-color:#34d399}table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:11px 9px;text-align:left;border-bottom:1px solid #374151;vertical-align:top}small{display:block;color:#9ca3af;word-break:break-word}td.name{overflow-wrap:anywhere}th{color:#9ca3af}input,select{background:#1f2937;color:white;border:1px solid #4b5563;border-radius:6px;padding:9px;margin:10px 10px 12px 0}.PASSED{color:#34d399}.RUNNING{color:#60a5fa}.FAILED,.TIMEOUT,.INCOMPLETE{color:#fb7185}.PENDING{color:#9ca3af}#error{color:#fbbf24}#running{background:#18263c;border-radius:10px;padding:6px 16px;margin-bottom:20px}#running li{padding:6px 0;overflow-wrap:anywhere}.muted{color:#9ca3af;font-size:13px}</style>
<h1>Buildbarn · Live tests</h1><p id="phase">Connecting…</p><div class="cards" id="cards"></div><progress id="progress" max="439" value="0"></progress>
<div id="running"><strong>Executing across worker pools</strong><ul id="active"></ul><div class="muted" id="worker-time"></div></div>
<table><thead><tr><th>Worker pool</th><th>Ready workers</th><th>Running tests</th><th>Pending targets</th><th>Passed</th></tr></thead><tbody id="pools"></tbody></table>
<p class="muted">Running counts observed test processes; workers may also be preparing inputs or uploading results. Pending means no test result or live process observed, not necessarily queued in Buildbarn.</p>
<div id="error"></div><input id="search" placeholder="Search test or Gradle task" size="38"><select id="filter"><option value="all">All tests</option><option value="RUNNING">Running</option><option value="failures">Failures</option><option value="PASSED">Passed</option><option value="PENDING">Pending</option></select>
<table><thead><tr><th>Status</th><th>Test class / Gradle task</th><th>Duration</th><th>Result reuse</th></tr></thead><tbody id="tests"></tbody></table><p class="muted" id="updated"></p>
<script>
let data;const $=id=>document.getElementById(id);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const duration=s=>s==null?'—':`${Math.floor(s/60)}m ${Math.floor(s%60)}s`;
function render(){if(!data)return;const c=data.counts;const bad=data.completed-(c.PASSED||0);$('phase').textContent=data.run_label+' · '+duration(data.elapsed_seconds)+' elapsed'+(data.finished?' · finished':'');
$('cards').innerHTML=[[data.completed+'/'+data.total,'Completed'],[c.PASSED||0,'Passed'],[bad,'Failed / incomplete'],[data.workers.running.length,'Running tasks'],[data.shards_completed+'/'+data.shards_total,'Completed tasks'],[data.workers.ready+'/'+data.workers.total,'Ready workers'],[data.cached,'Cached results']].map(([n,l])=>`<div class="card"><b>${esc(n)}</b><span>${l}</span></div>`).join('');$('progress').value=data.completed;$('progress').max=data.total;
$('active').innerHTML=data.workers.running.map(r=>`<li><b>${esc(r.class||r.task)}</b> · ${duration(r.seconds)}<small>${esc(r.task)} · shard ${r.shard_index+1}/${r.shard_count} · ${esc(r.worker)}</small></li>`).join('')||'<li>No active test process reported.</li>';
$('pools').innerHTML=Object.entries(data.pools).sort().map(([name,p])=>`<tr><td>${esc(name)}</td><td>${p.ready}/${p.total}</td><td>${p.running_actions||0}</td><td>${p.PENDING||0}</td><td>${p.PASSED||0}</td></tr>`).join('');
$('worker-time').textContent=data.workers.checked_at?'Workers checked '+new Date(data.workers.checked_at*1000).toLocaleTimeString()+' · every 10 seconds'+(data.workers.pending.length?' · '+data.workers.pending.length+' workers starting or waiting for capacity':''):'';
$('error').textContent=[data.driver_error,data.workers.error].filter(Boolean).join(' · ');
const q=$('search').value.toLowerCase(),f=$('filter').value;const rank=s=>s==='RUNNING'?0:s==='PASSED'?3:s==='PENDING'?2:1;
const rows=data.tests.filter(r=>(f==='all'||(f==='failures'?!['RUNNING','PASSED','PENDING'].includes(r.status):r.status===f))&&(r.target+' '+r.task).toLowerCase().includes(q)).sort((a,b)=>rank(a.status)-rank(b.status)||(a.class||a.task).localeCompare(b.class||b.task));
$('tests').innerHTML=rows.map(r=>`<tr><td class="${esc(r.status)}">${esc(r.status)}</td><td class="name">${esc(r.class||r.task)}<small>${esc(r.task)}${r.shard_count>1?` · ${r.shards_completed}/${r.shard_count} tasks complete`:""}</small></td><td>${duration(r.seconds)}</td><td>${r.cached?'Cache hit':r.status==='PASSED'?'Executed':'—'}</td></tr>`).join('');$('updated').textContent='Results refreshed '+new Date(data.updated_at*1000).toLocaleTimeString()+' · '+data.source;}
async function refresh(){try{let r=await fetch('/api/status');if(!r.ok)throw new Error('HTTP '+r.status);data=await r.json();render()}catch(e){$('error').textContent='Monitor connection lost: '+e.message}}
$('search').oninput=render;$('filter').onchange=render;refresh();setInterval(refresh,3000);
</script></html>'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if self.path == '/api/status':
                body = json.dumps(monitor.snapshot()).encode()
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
    monitor.start()
    print(f'Live tests: http://127.0.0.1:{args.port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
