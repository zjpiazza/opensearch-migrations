#!/usr/bin/env python3
"""Run the same 28 scenarios locally; separate compilation, live engines and replay."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
PROJECT = ROOT/'apps/backfill'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixtures', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--phases', nargs='+', default=['prepare','live','prepared-snapshots','replay-1','replay-2','replay-3'])
    args = p.parse_args()
    fixtures = args.fixtures.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    tasks = {'live':'pipelineRealBenchmark', 'prepared-snapshots':'pipelinePreparedSnapshotBenchmark'}
    state = {'scope':'Local single-JVM 28-scenario experiment; no remote execution or result reuse',
             'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
             'fixtures':str(fixtures), 'phases':rows}
    for phase in args.phases:
        task = tasks.get(phase,'pipelineWiremockTest')
        gradle = [str(ROOT/'gradlew')]
        if phase == 'prepare':
            gradle += [':DocumentsFromSnapshotMigration:preparePipelineWiremock', ':DocumentsFromSnapshotMigration:javadoc']
        else:
            gradle += [':DocumentsFromSnapshotMigration:'+task, '--rerun', '--fail-fast']
        command = gradle + ['-PpipelineFixtures='+str(fixtures), '-PpipelineSnapshotCache='+str(output/phase/'snapshot-cache'),
                            '--console=plain','--max-workers=4']
        # Playback must work even if Docker is unreachable; no fallback to engines.
        env = os.environ.copy()
        if phase.startswith('replay'):
            env['DOCKER_HOST'] = 'tcp://127.0.0.1:1'
        started = time.monotonic()
        with (output/(phase+'.log')).open('w') as log:
            child = subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            (output/'status.json').write_text(json.dumps({'phase':phase,'pid':child.pid,'started_epoch':time.time()})+'\n')
            code = child.wait()
        row = {'phase':phase,'wall_seconds':round(time.monotonic()-started,3),'exit_code':code}
        if phase != 'prepare':
            reports = PROJECT/'build/test-results'/task
            shutil.copytree(reports,output/phase/'junit',dirs_exist_ok=True)
            cases=[];test_time=0.0
            for file in reports.glob('TEST-*.xml'):
                suite=ET.parse(file).getroot();test_time+=float(suite.attrib.get('time',0))
                for c in suite.iter('testcase'):
                    cases.append({'name':c.attrib['name'],'seconds':float(c.attrib.get('time',0)),
                                  'passed':c.find('failure') is None and c.find('error') is None and c.find('skipped') is None})
            row.update(test_seconds=round(test_time,3),cases=cases)
            if len(cases)!=28 or not all(c['passed'] for c in cases):
                row['coverage_error']='Expected 28 passing scenarios with no skips'
                code=code or 1
        rows.append(row)
        (output/'results.json').write_text(json.dumps(state,indent=2)+'\n')
        print(json.dumps({k:v for k,v in row.items() if k!='cases'}),flush=True)
        if code:
            (output/'status.json').write_text(json.dumps({'phase':'failed','failed_phase':phase,'exit_code':code})+'\n')
            raise SystemExit(code)
    names=[sorted(c['name'] for c in r['cases']) for r in rows if 'cases' in r]
    if names and any(n!=names[0] for n in names):
        raise RuntimeError('Scenario identities differ between measured phases')
    (output/'status.json').write_text(json.dumps({'phase':'finished','exit_code':0})+'\n')


if __name__ == '__main__':
    main()
