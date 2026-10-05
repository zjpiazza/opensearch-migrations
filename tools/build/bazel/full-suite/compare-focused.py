#!/usr/bin/env python3
"""Compare completed long classes with their unsharded run and original CI cases."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def events(path):
    lines = path.read_text().splitlines()
    for index, line in enumerate(lines):
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            if index != len(lines) - 1:
                raise
            # The producer can be writing the final line during a live read.


def results(records):
    latest = {}
    for event in records:
        if 'testResult' in event:
            ident = event['id']['testResult']
            latest[(ident['label'].split(':', 1)[1], ident.get('shard', 1))] = event['testResult']
    return latest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--unsharded-bep', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    experiment = json.loads((args.run / 'experiment.json').read_text())
    current = list(events(args.run / 'results.bep.json'))
    original = results(events(args.unsharded_bep))
    latest = results(current)
    summaries = {e['id']['testSummary']['label'].split(':', 1)[1]: e['testSummary']
                 for e in current if 'testSummary' in e}
    baseline = json.loads(args.baseline.read_text())['baseline_cases']
    logs = args.run / 'client/execroot/_main/bazel-out/k8-fastbuild/testlogs/external/+_repo_rules+full_suite'
    rows = []
    for target in experiment['selected_targets']:
        name = target['target']
        summary = summaries.get(name)
        row = {'target': name, 'task': target['task'], 'class': target['class'],
               'shards': target['shard_count'], 'complete': summary is not None}
        if summary is None:
            row['completed_shards'] = sum(key[0] == name for key in latest)
            rows.append(row)
            continue
        expected = {(c['task'], c['class'], c['name']) for c in baseline
                    if c['task'] == target['task'] and c['class'] == target['class']
                    and 'success' in c['statuses']}
        counted, outcomes = Counter(), Counter()
        passing = set()
        invocations, builds, missing_outputs = [], [], []
        shard_results = []
        for index in range(target['shard_count']):
            result = latest.get((name, index + 1))
            if result is None:
                missing_outputs.append(index)
                continue
            shard_results.append(result)
            directory = logs / name / f'shard_{index + 1}_of_{target["shard_count"]}' / 'test.outputs'
            manifest = directory / 'invocation.json'
            if not manifest.exists():
                missing_outputs.append(index)
                continue
            invocation = json.loads(manifest.read_text())
            if (invocation['task'], invocation['class'], invocation['shard_index'], invocation['shard_count']) != (
                    target['task'], target['class'], index, target['shard_count']):
                raise ValueError('Output identity mismatch: ' + str(manifest))
            invocations.append(invocation)
            for xml in (directory / 'junit').glob('*.xml'):
                for case in ET.parse(xml).getroot().iter('testcase'):
                    key = (invocation['task'], case.attrib['classname'], case.attrib['name'])
                    state = ('skipped' if case.find('skipped') is not None else 'failed'
                             if case.find('failure') is not None or case.find('error') is not None else 'passed')
                    outcomes[state] += 1
                    if state != 'skipped':
                        counted[key] += 1
                    if state == 'passed':
                        passing.add(key)
            log = directory / 'test-output.log.gz'
            if log.exists():
                with gzip.open(log, 'rt', errors='replace') as stream:
                    for line in stream:
                        if line.startswith('FIXTURE_IMAGE_BUILD_RESULT '):
                            builds.append(json.loads(line.split(' ', 1)[1]))
        cached = sum(bool(r.get('cachedLocally') or r.get('executionInfo', {}).get('cachedRemotely'))
                     for r in shard_results)
        elapsed = (int(summary['lastStopTimeMillis']) - int(summary['firstStartTimeMillis'])) / 1000
        before = original.get((name, 1))
        before_seconds = int(before['testAttemptDurationMillis']) / 1000 if before else None
        duplicates = [key for key, count in counted.items() if count > 1]
        missing = sorted(expected - passing)
        additional = sorted(passing - expected)
        comparable = (before is not None and before['status'] == 'PASSED' and summary['overallStatus'] == 'PASSED'
                      and len(shard_results) == target['shard_count']
                      and not (cached or missing or additional or duplicates or missing_outputs))
        row.update(status=summary['overallStatus'], unsharded_status=before['status'] if before else None,
                   elapsed_seconds=round(elapsed, 3), unsharded_seconds=before_seconds,
                   summed_shard_seconds=round(sum(int(r['testAttemptDurationMillis']) / 1000 for r in shard_results), 3),
                   verified_speedup=round(before_seconds / elapsed, 3) if comparable and elapsed else None,
                   cached_shards=cached, expected_cases=len(expected), passing_cases=len(passing),
                   case_outcomes=dict(outcomes), missing_passing_cases=missing, additional_passing_cases=additional,
                   duplicate_executed_cases=duplicates, missing_outputs=missing_outputs,
                   timing_seconds=[r.get('timing_seconds') for r in invocations], image_builds=builds)
        rows.append(row)
    report = {'finished': any('finished' in e for e in current), 'classes': rows,
              'caveats': ['Completed classes only; unfinished classes have no speedup estimate.',
                          'Ratios require passing baseline and current class, complete case identities, and no cached results.',
                          'Worker image/input cache state and cluster contention differ. Ratios are observations, not isolated causal estimates.',
                          'Image build durations are inside execution time; sums across shards are not class wall time.',
                          'Final whole-run acceptance remains summarize.py --require-complete.']}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    for row in rows:
        if row['complete']:
            print(row['class'].split('.')[-1], row['status'], row['elapsed_seconds'],
                  'seconds; speedup', row['verified_speedup'], 'cases', row['passing_cases'], '/', row['expected_cases'])


if __name__ == '__main__':
    main()
