#!/usr/bin/env python3
"""Summarize complete-suite BEP events and compare executed JUnit cases to CI."""
import argparse
from collections import Counter
import json
from pathlib import Path
import xml.etree.ElementTree as ET

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('bep',type=Path)
parser.add_argument('--testlogs',type=Path,required=True)
parser.add_argument('--baseline',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--inventory',type=Path,default=Path('build/full-suite/inventory.json'))
parser.add_argument('--target',action='append',default=[],help='Validate only this exported target; repeat for a focused experiment')
parser.add_argument('--require-complete',action='store_true',help='Fail unless all targets and baseline cases pass')
args=parser.parse_args()
events=[json.loads(s) for s in args.bep.read_text().splitlines() if s.strip()]
attempts=[e for e in events if 'testResult' in e]
latest={}
for event in attempts:
    ident=event['id']['testResult']
    latest[(ident['label'],ident.get('run',1),ident.get('shard',1))]=event
results=list(latest.values())
summaries={e['id']['testSummary']['label']:e['testSummary']['overallStatus'] for e in events if 'testSummary' in e}
statuses=Counter(summaries.values())
shard_statuses=Counter(e['testResult']['status'] for e in results)
metrics=next((e['buildMetrics'] for e in events if 'buildMetrics' in e),{})
success=set(); actual=set(); outcomes=Counter(); fresh_outcomes=Counter(); missing_outputs=[]; durations={}; executed=Counter()
for e in results:
    result=e['testResult']; label=e['id']['testResult']['label']; name=label.split(':',1)[1]
    base=args.testlogs/name
    directory=base/'test.outputs'
    if not (directory/'invocation.json').exists():
        shard=e['id']['testResult'].get('shard',1)
        candidates=list(base.glob(f'shard_{shard}_of_*/test.outputs'))
        if len(candidates)==1:
            directory=candidates[0]
    manifest=directory/'invocation.json'
    if not manifest.exists():
        missing_outputs.append(label)
        continue
    invocation=json.loads(manifest.read_text()); task=invocation['task']
    durations[label+'#shard='+str(e['id']['testResult'].get('shard',1))]=result.get('testAttemptDurationMillis',0)
    for xml in (directory/'junit').glob('*.xml'):
        for case in ET.parse(xml).getroot().iter('testcase'):
            name=case.attrib['name']
            key=(task,case.attrib['classname'],name)
            state='skipped' if case.find('skipped') is not None else 'failed' if case.find('failure') is not None or case.find('error') is not None else 'passed'
            if state!='skipped':executed[key]+=1
            actual.add(key);outcomes[state]+=1
            if not result.get('cachedLocally') and not result.get('executionInfo',{}).get('cachedRemotely'):
                fresh_outcomes[state]+=1
            if state=='passed':success.add(key)
baseline=json.loads(args.baseline.read_text())
expected={(c['task'],c['class'],c['name']) for c in baseline['baseline_cases'] if 'success' in c['statuses']}
inventory=json.loads(args.inventory.read_text())['targets'] if args.inventory.exists() else []
selected={target.split(':',1)[-1] for target in args.target}
if selected:
    selected_inventory=[t for t in inventory if t['target'] in selected]
    if {t['target'] for t in selected_inventory}!=selected:
        raise SystemExit('Focused targets must all be present in the supplied inventory')
    pairs={(t['task'],t.get('class','')) for t in selected_inventory}
    expected={key for key in expected if key[:2] in pairs}
    expected_targets=len(selected)
    expected_shards=sum(t.get('shard_count',1) for t in selected_inventory)
else:
    expected_targets=baseline['exported_class_task_pairs']+len(baseline['exported_npm_checks'])
    expected_shards=sum(t.get('shard_count',1) for t in inventory) if inventory else expected_targets
missing=sorted(expected-success)
duplicate_cases=sorted(key for key,count in executed.items() if count>1)
by_target={}
for event in results:by_target.setdefault(event['id']['testResult']['label'],[]).append(event['testResult'])
observed_targets={label.split(':',1)[-1] for label in by_target}
unexpected_targets=sorted(observed_targets-selected) if selected else []
report={
 'target_statuses':dict(statuses),'target_results':len(by_target),
 'shard_statuses':dict(shard_statuses),'shard_results':len(results),'attempt_results':len(attempts),
 'expected_targets':expected_targets,'expected_shards':expected_shards,
 'remote_cached_targets':sum(all(r.get('executionInfo',{}).get('cachedRemotely') for r in rs) for rs in by_target.values()),
 'locally_cached_targets':sum(all(r.get('cachedLocally') for r in rs) for rs in by_target.values()),
 'wall_time_ms':metrics.get('timingMetrics',{}).get('wallTimeInMs'),
 'build_finished':any('finished' in e for e in events),
 'build_exit_code':next((e['finished'].get('exitCode',{}).get('code',0) for e in events if 'finished' in e),None),
 'reported_junit_case_outcomes':dict(outcomes),
 'freshly_executed_junit_case_outcomes':dict(fresh_outcomes),
 'unique_passing_junit_cases':len(success),
 'baseline_unique_passing_junit_cases':len(expected),
 'baseline_cases_not_passing':missing,'additional_passing_cases':sorted(success-expected),
 'missing_output_manifests':missing_outputs,
 'duplicate_executed_cases':duplicate_cases,
 'unexpected_targets':unexpected_targets,
 'longest_target_attempts_ms':sorted(durations.items(),key=lambda item:int(item[1]),reverse=True)[:20],
 'limitation':'Cached XML describes the reused execution; counts do not imply fresh test execution. Case identity is Gradle task, class, method and parameter index. Coverage uses the latest attempt of each shard.'}
args.output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('baseline_cases_not_passing','additional_passing_cases','longest_target_attempts_ms')},indent=2))
print('Missing baseline passing cases:',len(missing))

if args.require_complete:
    if (not report['build_finished'] or report['build_exit_code'] != 0 or
            len(by_target) != expected_targets or statuses.get('PASSED',0) != expected_targets or
            len(results) != expected_shards or shard_statuses.get('PASSED',0) != expected_shards or
            missing or missing_outputs or duplicate_cases or unexpected_targets):
        raise SystemExit('Full-suite validation is incomplete or failed')
