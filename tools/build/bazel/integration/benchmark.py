#!/usr/bin/env python3
"""Measure real backfill, same-session reuse, and ES8 -> ES7 invalidation."""
import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent


def main():
    dest = ROOT / "build/bazel-integration" / datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest.mkdir(parents=True)
    scenario = HERE / "scenario.json"
    original = scenario.read_bytes()
    session = uuid.uuid4().hex
    results = []
    try:
        for phase in ["execute-es8", "cached-es8", "changed-input-es7"]:
            if phase == "changed-input-es7":
                changed = json.loads(original)
                changed["source_version"] = "ES_7.10"
                scenario.write_text(json.dumps(changed, indent=2) + "\n")
            subprocess.run([sys.executable, str(HERE / "prepare.py")], check=True)
            command = [str(ROOT / "bazelw"), "--output_user_root=" + str(ROOT / "build/bazel-state"),
                       "test", "//tests/automation:backfill_cache_experiment",
                       "--test_env=BAZEL_INTEGRATION_EXPERIMENT_SESSION=" + session,
                       "--build_event_json_file=" + str(dest / (phase + ".bep.json"))]
            print(f"Starting {phase}; log: {dest / (phase + '.log')}", flush=True)
            start = time.monotonic()
            with (dest / (phase + ".log")).open("w") as log:
                completed = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            elapsed = time.monotonic() - start
            events = [json.loads(line) for line in (dest / (phase + ".bep.json")).read_text().splitlines()]
            summaries = [e["testSummary"] for e in events if "testSummary" in e]
            for summary in summaries:
                for passed in summary.get("passed", []):
                    path = Path(passed["uri"].removeprefix("file://"))
                    if path.exists():
                        shutil.copytree(path.parent, dest / (phase + "-test-outputs"), dirs_exist_ok=True)
            cached = sum(s.get("totalNumCached", 0) for s in summaries)
            results.append({"phase": phase, "wall_seconds": elapsed,
                            "exit_code": completed.returncode, "cached_targets": cached,
                            "test_summaries": summaries})
            (dest / "results.json").write_text(json.dumps(results, indent=2) + "\n")
            print(results[-1], flush=True)
            if completed.returncode:
                raise SystemExit(completed.returncode)
            assert len(summaries) == 1 and summaries[0]["overallStatus"] == "PASSED", summaries
            assert cached == (1 if phase == "cached-es8" else 0), summaries
    finally:
        scenario.write_bytes(original)


if __name__ == "__main__":
    main()
