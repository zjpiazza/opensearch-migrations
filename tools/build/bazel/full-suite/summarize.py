#!/usr/bin/env python3
"""Summarize complete-suite BEP events and compare executed JUnit cases to CI."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('bep',type=Path)
parser.add_argument('--testlogs',type=Path,required=True)
parser.add_argument('--baseline',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
events=[json.loads(s) for s in args.bep.read_text().splitlines() if s.strip()]
results=[e for e in events if 'testResult' in e]
statuses=Counter(e['testResult']['status'] for e in results)
metrics=next((e['buildMetrics'] for e in events if 'buildMetrics' in e),{})
success=set(); actual=set(); outcomes=Counter(); missing_outputs=[]; durations={}
for e in results:
    result=e['testResult']; label=e['id']['testResult']['label']; name=label.split(':',1)[1]
    directory=args.testlogs/name/'test.outputs'
    manifest=directory/'invocation.json'
    if not manifest.exists():
        missing_outputs.append(label)
        continue
    invocation=json.loads(manifest.read_text()); task=invocation['task']
    durations[label]=result.get('testAttemptDurationMillis',0)
    for xml in (directory/'junit').glob('*.xml'):
        for case in ET.parse(xml).getroot().iter('testcase'):
            output=case.findtext('system-out','')
            display=re.search(r'^display-name: (.*)$',output,re.M)
            name=display.group(1) if display else case.attrib['name']
            key=(task,case.attrib['classname'],name)
            state='skipped' if case.find('skipped') is not None else 'failed' if case.find('failure') is not None or case.find('error') is not None else 'passed'
            actual.add(key);outcomes[state]+=1
            if state=='passed':success.add(key)
baseline=json.loads(args.baseline.read_text())
expected={(c['task'],c['class'],c['name']) for c in baseline['baseline_cases'] if 'success' in c['statuses']}
missing=sorted(expected-success)
report={
 'target_statuses':dict(statuses),'target_results':len(results),
 'remote_cached_targets':sum(bool(e['testResult'].get('cachedRemotely')) for e in results),
 'locally_cached_targets':sum(bool(e['testResult'].get('cachedLocally')) for e in results),
 'wall_time_ms':metrics.get('timingMetrics',{}).get('wallTimeInMs'),
 'executed_junit_case_outcomes':dict(outcomes),'unique_passing_junit_cases':len(success),
 'baseline_unique_passing_junit_cases':len(expected),
 'baseline_cases_not_passing':missing,'additional_passing_cases':sorted(success-expected),
 'missing_output_manifests':missing_outputs,
 'longest_target_attempts_ms':sorted(durations.items(),key=lambda item:int(item[1]),reverse=True)[:20],
 'limitation':'Cached XML describes the reused execution; counts do not imply fresh test execution. Gradle/JUnit display-name differences require explicit reconciliation.'}
args.output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('baseline_cases_not_passing','additional_passing_cases','longest_target_attempts_ms')},indent=2))
print('Missing baseline passing cases:',len(missing))
