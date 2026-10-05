#!/usr/bin/env python3
"""Run fresh-client full-suite cache scenarios, retaining logs and source diffs.

Requires a working Buildbarn tunnel and a successful seed run. Each scenario
requests all targets. Source modifications are temporary and restored on exit.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parents[4]
SCENARIOS={
    'unchanged':None,
    'leaf':('apps/dashboards/src/main/java/org/opensearch/migrations/dashboards/savedobjects/SavedObjectParser.java',
            'Skipping the exported summary line.', 'Skipping the exported dashboard summary line.'),
    'shared':('libs/runtime/src/main/java/org/opensearch/migrations/jcommander/EnvVarParameterPuller.java',
              'Could not access field: {}', 'Could not access parameter field: {}'),
}
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('scenario',choices=SCENARIOS)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--instance',default='migrations-pilot')
args=parser.parse_args()
out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
change=SCENARIOS[args.scenario];source=None;original=None
steps=[]

def run(name,command):
    start=time.monotonic()
    with (out/(name+'.log')).open('w') as log:
        result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    record={'step':name,'seconds':time.monotonic()-start,'exit_code':result.returncode}
    steps.append(record);(out/'timings.json').write_text(json.dumps(steps,indent=2)+'\n')
    print(json.dumps(record),flush=True)
    if result.returncode: raise subprocess.CalledProcessError(result.returncode,command)

try:
    if change:
        path,old,new=change;source=ROOT/path;original=source.read_text()
        if original.count(old)!=1: raise RuntimeError('Scenario source no longer matches: '+path)
        source.write_text(original.replace(old,new))
        (out/'source-change.json').write_text(json.dumps({'path':path,'before':old,'after':new},indent=2)+'\n')
        run('gradle-prepare',['./gradlew','-I','tools/build/bazel/full-suite/export.gradle','exportBazelTestRuntime',
                              '--max-workers=3','-x','spotlessCheck','--console=plain'])
        run('runtime-export',['python3','tools/build/bazel/full-suite/prepare.py'])
    cache_check = ['--experimental_remote_require_cached', '--disk_cache=',
                   '--noremote_upload_local_results'] if args.scenario == 'unchanged' else []
    run('bazel',['./bazelw','--output_base='+str(out/'client'), 'test','--config=buildbarn',
                 '--remote_instance_name='+args.instance,'@full_suite//:all_tests','--keep_going','--test_timeout=7200',
                 '--build_event_json_file='+str(out/'results.bep.json'),
                 '--execution_log_json_file='+str(out/'results.execution.json'), *cache_check])
finally:
    if source is not None and original is not None:
        source.write_text(original)
        print('Source restored; rerun Gradle preparation/export before another scenario.',flush=True)
