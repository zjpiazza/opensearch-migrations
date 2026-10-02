#!/usr/bin/env python3
"""Compare the same 121 existing Java tests with Gradle and Bazel.

Run: python3 tools/build/bazel/benchmark.py --repetitions 3
Set BAZEL_POC_BINARY to reuse an installed Bazel 8.4.2 executable.
Logs, build events, and JSON results are saved under build/bazel-benchmark.

Dependencies and daemons are warmed before measurement. 'rebuild' forces Gradle
tasks and cleans Bazel outputs with its action cache disabled; neither includes
initial downloads. 'execute' reruns tests but allows compiled outputs to be reused.
'unchanged' permits both systems to reuse successful results. 'edit' temporarily
changes a URIHelper exception message and restores the source in a finally block.

This compares existing Gradle defaults against the experimental Bazel slice, not
identical compiler instrumentation: Gradle includes JaCoCo, custom Error Prone
checks and shared fixture dependencies not yet ported to Bazel. Java vendors can
differ. The Python mock suites are validated separately, outside the Java timings.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
MODULES = [
    "libs/runtime",
    "libs/transforms",
    "libs/transforms/transformationPlugins/jsonMessageTransformers/jsonMessageTransformerInterface",
]
TASKS = [":coreUtilities:test", ":transformation:test",
         ":transformation:transformationPlugins:jsonMessageTransformers:jsonMessageTransformerInterface:test"]
TARGET = "//:bazel_poc_java_tests"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    out = ROOT / "build/bazel-benchmark" / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    subprocess.run(["python3", str(ROOT / "tools/build/bazel/check_dependencies.py")], check=True)
    env = dict(os.environ)
    env.pop("OS_MIGRATIONS_GRADLE_SCAN_TOS_AGREE_AND_ENABLED", None)
    bazel = [str(ROOT / "bazelw"), "--output_user_root=" + str(ROOT / "build/bazel-state")]
    cache = "--disk_cache=" + str(out / "action-cache")
    gradle = [str(ROOT / "gradlew"), "--console=plain", "--max-workers=4"]
    rows = []
    sequence = 0

    def run(tool, scenario, command, measured=True):
        nonlocal sequence
        sequence += 1
        name = f"{sequence:02d}-{tool}-{scenario}"
        if tool == "bazel" and "test" in command:
            command = command + ["--build_event_json_file=" + str(out / (name + ".bep.json"))]
        start = time.perf_counter()
        with (out / (name + ".log")).open("w") as log:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        elapsed = time.perf_counter() - start
        row = {
            "tool": tool,
            "scenario": scenario,
            "seconds": round(elapsed, 3),
            "exit_code": result.returncode,
            "log": name + ".log",
            "command": command,
        }
        if tool == "bazel" and "test" in command and result.returncode == 0:
            events = [json.loads(line) for line in (out / (name + ".bep.json")).read_text().splitlines()]
            tests = [e["testResult"] for e in events if "testResult" in e]
            row["test_targets"] = len(tests)
            row["cached_targets"] = sum(
                bool(t.get("cachedLocally") or t.get("executionInfo", {}).get("cachedRemotely")) for t in tests
            )
        if measured:
            rows.append(row)
            (out / "partial-results.json").write_text(json.dumps(rows, indent=2) + "\n")
        print(f"{tool:7} {scenario:20} {elapsed:7.3f}s exit={result.returncode}", flush=True)
        if result.returncode:
            raise RuntimeError("Command failed; see " + str(out / row["log"]))
        return row

    btest = bazel + ["test", TARGET, cache]
    gtest = gradle + TASKS
    # Explicitly exclude dependency installation and daemon startup from comparisons.
    run("gradle", "warmup", gtest, False)
    run("bazel", "warmup", btest, False)
    for scenario in ["unchanged", "execute", "rebuild"]:
        for i in range(args.repetitions):
            for tool in (["gradle", "bazel"] if i % 2 == 0 else ["bazel", "gradle"]):
                if tool == "bazel":
                    command = btest
                    if scenario == "execute":
                        command = btest + ["--nocache_test_results"]
                    if scenario == "rebuild":
                        run("bazel", "clean", bazel + ["clean"], False)
                        command = bazel + ["test", TARGET, "--disk_cache="]
                else:
                    command = gtest
                    if scenario == "execute":
                        command = gradle + [arg for task in TASKS for arg in (task, "--rerun")]
                    if scenario == "rebuild":
                        command = gtest + ["--rerun-tasks", "--no-build-cache"]
                run(tool, scenario, command)

    run("gradle", "before-edit", gtest, False)
    run("bazel", "before-edit", btest, False)
    source = ROOT / "libs/runtime/src/main/java/org/opensearch/migrations/utils/URIHelper.java"
    original = source.read_bytes()
    needle = b'"Invalid URI: "'
    if original.count(needle) != 1:
        raise RuntimeError("URIHelper changed: update benchmark edit before running")
    try:
        for i in range(args.repetitions):
            replacement = f'"Invalid URI (benchmark {out.name}-{i}): "'.encode()
            source.write_bytes(original.replace(needle, replacement))
            tools = [("gradle", gtest), ("bazel", btest)]
            for tool, command in tools if i % 2 == 0 else reversed(tools):
                run(tool, "edit", command)
    finally:
        source.write_bytes(original)
    assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(original).digest()
    run("gradle", "restored", gtest, False)
    run("bazel", "restored", btest, False)

    # A fresh output base models a new worker reading a populated shared cache.
    # This is a local disk cache, not a measurement of remote network latency.
    fresh = bazel + ["--output_base=" + str(out / "fresh-worker"), "test", TARGET, cache]
    run("bazel", "fresh-output-cache", fresh)
    run("bazel", "mixed-warmup", bazel + ["test", "//:bazel_poc_tests", cache], False)
    run("bazel", "mixed-unchanged", bazel + ["test", "//:bazel_poc_tests", cache])

    # Separate the cost of Gradle's coverage agent from test execution overhead.
    no_coverage = gradle + ["--init-script", str(ROOT / "tools/build/bazel/gradle-no-coverage.init.gradle")]
    no_coverage += [arg for task in TASKS for arg in (task, "--rerun")]
    for _ in range(args.repetitions):
        run("gradle", "execute-no-coverage", no_coverage)
    run("gradle", "restore-coverage", gtest, False)

    gradle_counts = {}
    for module in MODULES:
        files = list((ROOT / module / "build/test-results/test").glob("TEST-*.xml"))
        gradle_counts[module] = sum(int(ET.parse(f).getroot().get("tests", 0)) for f in files)
    bazel_counts = {}
    for path in (ROOT / "bazel-testlogs").glob("**/test.log"):
        match = re.search(r"(\d+) tests successful", path.read_text())
        if match:
            bazel_counts[str(path.relative_to(ROOT / "bazel-testlogs"))] = int(match[1])
    assert sum(gradle_counts.values()) == sum(bazel_counts.values()) == 121, (gradle_counts, bazel_counts)
    summary = {}
    for row in rows:
        key = row["tool"] + ":" + row["scenario"]
        summary[key] = statistics.median(r["seconds"] for r in rows if r["tool"] + ":" + r["scenario"] == key)
    report = {
        "scope": "121 existing Java tests; 43 existing mocked Kubernetes Python tests validated separately",
        "methodology": __doc__,
        "platform": platform.platform(),
        "logical_cpus": os.cpu_count(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "gradle_test_counts": gradle_counts,
        "bazel_test_counts": bazel_counts,
        "median_seconds": summary,
        "runs": rows,
    }
    (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print("Results: " + str(out / "results.json"))


if __name__ == "__main__":
    main()
