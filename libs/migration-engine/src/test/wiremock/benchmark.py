#!/usr/bin/env python3
"""Measure Gradle preparation, actual WireMock playback, and unchanged reuse."""
import json
import os
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[5]
OUTPUT = ROOT / "build/wiremock-ci-results"
REPORT = ROOT.joinpath("libs/migration-engine/build/test-results/wiremockTest",
                       "TEST-org.opensearch.migrations.bulkload.wiremock.SinkWireMockTest.xml")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results = []
    phases = [
        ("prepare", [":RFS:prepareWiremockTest"]),
        ("playback", [":RFS:wiremockTest", "--rerun"]),
        ("unchanged", [":RFS:wiremockTest"]),
    ]
    for name, tasks in phases:
        log_path = OUTPUT / (name + ".log")
        start = time.perf_counter()
        with log_path.open("w") as output:
            completed = subprocess.run(
                [str(ROOT / "gradlew"), *tasks, "--max-workers=4", "--console=plain", "--profile"],
                cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
            )
        row = {"phase": name, "wall_seconds": round(time.perf_counter() - start, 3),
               "exit_code": completed.returncode}
        log = log_path.read_text()
        if completed.returncode:
            print(log)
            raise SystemExit(completed.returncode)
        if name != "prepare":
            # A playback measurement must not hide unfinished dependency preparation.
            unfinished = re.findall(r"^> Task (\S+)(?: ([^\n]+))?$", log, re.MULTILINE)
            unfinished = [(task, state) for task, state in unfinished
                          if task != ":RFS:wiremockTest" and
                          state not in ("UP-TO-DATE", "NO-SOURCE", "SKIPPED")]
            assert not unfinished, f"Preparation missed tasks: {unfinished}"
            match = re.search(r"^> Task :RFS:wiremockTest(?: ([^\n]+))?$", log, re.MULTILINE)
            assert match, "Missing WireMock task result"
            row["task_result"] = match.group(1) or "EXECUTED"
            report = ET.parse(REPORT).getroot()
            row["tests"] = int(report.attrib["tests"])
            row["test_seconds"] = float(report.attrib["time"])
            assert row["tests"] == 9, row
            assert all(int(report.attrib[key]) == 0 for key in ("failures", "errors", "skipped")), report.attrib
            if name == "playback":
                assert row["task_result"] == "EXECUTED", row
            else:
                assert row["task_result"] in ("UP-TO-DATE", "FROM-CACHE"), row
                # This report was reused; its duration is not a new execution measurement.
                row.pop("test_seconds")
        results.append(row)
        (OUTPUT / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(row), flush=True)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a") as output:
                if name == "prepare":
                    output.write("| Phase | Gradle wall seconds | Test seconds | Result |\n"
                                 "| --- | ---: | ---: | --- |\n")
                output.write(f"| {name} | {row['wall_seconds']} | {row.get('test_seconds', '—')} | "
                             f"{row.get('task_result', 'Prepared')} |\n")


if __name__ == "__main__":
    main()
