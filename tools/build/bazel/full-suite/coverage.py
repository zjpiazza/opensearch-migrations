#!/usr/bin/env python3
"""Reconcile the union of all Gradle HTML shard reports with exported JUnit classes."""
import argparse
from collections import Counter
from html import unescape
import json
from pathlib import Path
import re
import zipfile

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('reports',type=Path)
parser.add_argument('inventory',type=Path)
parser.add_argument('output',type=Path)
args=parser.parse_args()
baseline={}; runs=Counter(); counts=Counter()
for archive in sorted(args.reports.glob('*.zip')):
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            m=re.fullmatch(r'(.+)/build/reports/tests/([^/]+)/classes/(.+)\.html',name)
            if not m: continue
            project,task,cls=m.groups(); task=':'+project.replace('/',':')+':'+task
            html=z.read(name).decode()
            section=html.split('<h2>Tests</h2>',1)[1].split('</table>',1)[0]
            has_method_column = '<th>Method name</th>' in section
            rows=re.findall(r'<tr>(.*?)</tr>',section,re.S)
            for row in rows:
                cells=re.findall(r'<td class="([^"]+)">(.*?)</td>',row,re.S)
                if not cells: continue
                status,test=cells[1 if has_method_column else 0]
                test=unescape(re.sub('<[^>]+>','',test))
                key=(task,cls,test)
                counts[status]+=1
                baseline.setdefault(key,set()).add(status)
                if status=='success': runs[key]+=1
inventory=json.loads(args.inventory.read_text())
exported={(t['task'],c) for t in inventory['java_tasks'] for c in t['classes']}
expected={(task,cls.split('$')[0]) for (task,cls,_),statuses in baseline.items() if 'success' in statuses}
missing=sorted(expected-exported)
result={'shards':len(list(args.reports.glob('*.zip'))),
        'baseline_unique_test_rows':len(baseline),'baseline_unique_successful_test_rows':len(runs),
        'baseline_reported_executions':dict(counts),'baseline_successful_class_task_pairs':len(expected),
        'exported_class_task_pairs':len(exported),'exported_npm_checks':inventory['npm_tasks'],
        'missing_successful_class_task_pairs':missing,
        'additional_class_task_pairs':sorted(exported-expected),
        'limitation':'Discovery class/task coverage only. Successful execution and parameterized case equivalence require runtime reports.',
        'baseline_cases':[{'task':t,'class':c,'name':n,'statuses':sorted(s),'successful_executions':runs[(t,c,n)]} for (t,c,n),s in sorted(baseline.items())]}
args.output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('baseline_cases','additional_class_task_pairs')},indent=2))
if missing: raise SystemExit(1)
