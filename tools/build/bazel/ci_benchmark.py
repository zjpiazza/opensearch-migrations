#!/usr/bin/env python3
"""Measure CI execution, local reuse, fixture invalidation and fresh-runner reuse."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
COMPONENT = "//tools/build/bazel/components:approval_integration_test"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restored", action="store_true")
    args = parser.parse_args()
    destination = ROOT / "build/bazel-ci-results"
    destination.mkdir(parents=True, exist_ok=True)
    results = []

    def measure(name, target="//:bazel_poc_tests", flags=(), expect_cached=None):
        events_path = destination / (name + ".bep.json")
        command = [os.environ.get("BAZEL_POC_BINARY", "bazel"), "test", target,
                   "--build_event_json_file=" + str(events_path), *flags]
        start = time.perf_counter()
        with (destination / (name + ".log")).open("w") as output:
            completed = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        elapsed = time.perf_counter() - start
        events = [json.loads(line) for line in events_path.read_text().splitlines()]
        summaries = [event["testSummary"] for event in events if "testSummary" in event]
        row = {"phase": name, "wall_seconds": round(elapsed, 3), "targets": len(summaries),
               "cached_targets": sum(s.get("totalNumCached", 0) for s in summaries),
               "exit_code": completed.returncode}
        results.append(row)
        print(json.dumps(row), flush=True)
        (destination / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with open(summary_path, "a") as summary:
                if len(results) == 1:
                    summary.write("| Phase | Bazel wall time | Cached / targets | Exit |\n"
                                  "| --- | ---: | ---: | ---: |\n")
                summary.write(f"| {name} | {elapsed:.3f}s | {row['cached_targets']} / "
                              f"{row['targets']} | {completed.returncode} |\n")
        if completed.returncode:
            print((destination / (name + ".log")).read_text())
            raise SystemExit(completed.returncode)
        assert summaries and all(s["overallStatus"] == "PASSED" for s in summaries), summaries
        if expect_cached == "all":
            assert row["cached_targets"] == row["targets"], row
        elif expect_cached is not None:
            assert row["cached_targets"] == expect_cached, row

    if args.restored:
        measure("fresh-runner-restored", expect_cached="all")
        return
    measure("initial", expect_cached=0)
    measure("force-execution", flags=["--nocache_test_results"], expect_cached=0)
    measure("unchanged", expect_cached="all")
    measure("approval-execution", target=COMPONENT, flags=["--nocache_test_results"], expect_cached=0)
    measure("approval-cached", target=COMPONENT, expect_cached="all")
    fixture = ROOT / "tools/build/bazel/components/approval_scenario.json"
    original = fixture.read_bytes()
    try:
        scenario = json.loads(original)
        scenario["snapshot_migration_name"] = "changed-fixture-migration"
        fixture.write_text(json.dumps(scenario, indent=2) + "\n")
        measure("changed-approval-fixture", target=COMPONENT, expect_cached=0)
    finally:
        fixture.write_bytes(original)
    # Restore the original test result in the cache before the next runner starts.
    measure("restored-original-fixture", target=COMPONENT, expect_cached="all")


if __name__ == "__main__":
    main()
