#!/usr/bin/env python3
"""Run real contract playback and prove Bazel process reuse across GitHub jobs."""
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "build/vm-ci-results"
STATE = Path.home() / "benchmark/last-run.json"
TARGET = "//libs/migration-engine:sink_wiremock_test"
SOURCE = ROOT / "libs/migration-engine/src/main/java/org/opensearch/migrations/bulkload/pipeline/adapter/OpenSearchDocumentSink.java"


def process_identity(pid):
    # PID alone can be reused, including across reboots.
    stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return f"{pid}:{stat[19]}"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    previous = json.loads(STATE.read_text()) if STATE.exists() else None
    run_marker = os.environ["GITHUB_RUN_ID"] + "-" + os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    original = SOURCE.read_text()
    assert original.count("this.client = client;") == 1
    server_pid = int(subprocess.check_output(["bazel", "info", "server_pid"], cwd=ROOT, text=True).strip())
    rows = []
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    server_identity = process_identity(server_pid)
    same_boot = bool(previous and previous.get("boot_id") == boot_id)
    for phase in ("baseline", "source-change", "unchanged"):
        if phase == "source-change":
            SOURCE.write_text(original.replace(
                "this.client = client;",
                'this.client = java.util.Objects.requireNonNull(client, "CI-' + run_marker + '");'))
        events_file = OUTPUT / (phase + ".bep.json")
        command = ["bazel", "test", TARGET, "--build_event_json_file=" + str(events_file)]
        if phase != "unchanged":
            command += ["--nocache_test_results"]
        start = time.perf_counter()
        try:
            with (OUTPUT / (phase + ".log")).open("w") as log:
                result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            elapsed = time.perf_counter() - start
            assert result.returncode == 0, (phase, (OUTPUT / (phase + ".log")).read_text()[-12000:])
            events = [json.loads(line) for line in events_file.read_text().splitlines()]
            summary = next(e["testSummary"] for e in events if "testSummary" in e)
            metrics = next(e["buildMetrics"] for e in events if "buildMetrics" in e)
            test = next(e["testResult"] for e in events if "testResult" in e)
            assert summary["overallStatus"] == "PASSED", summary
            cached = bool(summary.get("totalNumCached", 0))
            assert cached == (phase == "unchanged"), summary
            uri = next(x["uri"] for x in test["testActionOutput"] if x["name"] == "test.log")
            text = Path(unquote(urlparse(uri).path)).read_text()
            text = re.sub(r"\x1b\[[0-9;]*m", "", text)
            assert re.search(r"\b9 tests successful", text), text
            assert re.search(r"\b0 tests skipped", text), text
            workers = [w["processId"] for w in metrics.get("workerMetrics", [])
                       if w.get("mnemonic") == "Javac" and w.get("workerStatus") == "ALIVE"]
            actions = metrics.get("actionSummary", {}).get("actionData", [])
            javac_count = sum(int(a.get("actionsExecuted", 0)) for a in actions if a["mnemonic"] == "Javac")
            if phase == "source-change":
                assert javac_count > 0 and workers, "Expected a real compilation on a persistent worker"
            rows.append({"phase": phase, "wall_seconds": round(elapsed, 3), "cached": cached,
                         "tests": 9, "worker_pids": workers, "worker_identities": [process_identity(p) for p in workers],
                         "javac_actions": javac_count})
        finally:
            # Keep raw build events private: they contain the job's environment.
            events_file.unlink(missing_ok=True)
            if phase == "unchanged" or len(rows) < ("baseline", "source-change", "unchanged").index(phase) + 1:
                SOURCE.write_text(original)
    # Restore compiled original code so subsequent jobs start from the same baseline.
    subprocess.run(["bazel", "build", TARGET], cwd=ROOT, check=True)
    worker_pids = rows[1]["worker_pids"]
    report = {
        "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "server_pid": server_pid, "server_identity": server_identity,
        "worker_pids": worker_pids, "worker_identities": rows[1]["worker_identities"],
        "boot_id": boot_id, "phases": rows,
        "previous_run": previous,
        "server_reused_across_jobs": bool(same_boot and previous["server_identity"] == server_identity),
        "workers_reused_across_jobs": bool(same_boot and set(previous["worker_identities"]) & set(rows[1]["worker_identities"])),
    }
    (OUTPUT / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    persisted_keys = ("run_id", "run_attempt", "server_pid", "server_identity", "worker_pids", "worker_identities", "boot_id")
    STATE.write_text(json.dumps({k: report[k] for k in persisted_keys}))
    if same_boot:
        assert report["server_reused_across_jobs"], "Bazel server did not survive between jobs"
        assert report["workers_reused_across_jobs"], "Javac worker did not survive between jobs"
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as summary:
            summary.write("| Phase | Wall seconds | Cached | Tests |\n| --- | ---: | --- | ---: |\n")
            for row in rows:
                summary.write(f"| {row['phase']} | {row['wall_seconds']} | {row['cached']} | 9 |\n")
            summary.write(f"\nServer retained across jobs: {report['server_reused_across_jobs']}. "
                          f"Compiler retained: {report['workers_reused_across_jobs']}.\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
