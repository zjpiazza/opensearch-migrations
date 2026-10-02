# VM persistent runner experiment

This branch runs the nine existing WireMock sink contract tests through a focused
Bazel graph on one persistent Linux VM. It measures initial preparation, a real
Java source edit followed by execution, and unchanged test-result reuse. It does
not cover the complete migration E2E suite or establish an E2E speedup.

The GitHub runner and Bazel workers run on the same VM as the unprivileged
`runner` user. `bazel-warm.service` starts the Bazel server before the runner
accepts jobs. A stable checkout and output base preserve both on-disk artifacts
and the live server. `--max_idle_secs=0` keeps the server alive until stopped.
Only the Java compilation action uses a persistent worker; test JVMs still start
for every forced test execution. The focused graph compiles selected production
sources and is not equivalent to the full Gradle dependency graph.

## Installation

Push `experimental` to `zjpiazza/opensearch-migrations` before running `install.sh`
as root on a dedicated Ubuntu 24.04 VM. The script installs pinned, checksum
verified GitHub runner and Bazel distributions, Java 21, a public clone of this
branch, and the Bazel service. It does not provision cloud resources.

Register `/home/runner/actions-runner` as user `runner` with the repository URL,
name `vm-persistent-bazel`, label `vm-persistent-bazel`, and work directory `_work`.
Use a short-lived GitHub registration token; do not save a GitHub personal token
on the VM. Install the runner service with `./svc.sh install runner` as root.
Add a systemd drop-in to that service containing:

```ini
[Unit]
Requires=bazel-warm.service
After=bazel-warm.service
```

Then reload systemd and start the runner service. The experimental workflow runs
only for this fork and owner through manual dispatch, selecting `experimental`.
It does not run automatically on pushes or pull requests. GitHub may require the
workflow on the default branch before offering manual dispatch. The historical
branch used push triggers; consolidation makes this optional benchmark manual.

## Measurements

`benchmark.py` forces test execution in the baseline and source-change phases,
asserts all nine tests pass without skips, requires a real Javac action for the
source change, and requires a cache hit for the unchanged phase. The temporary
constructor message includes the GitHub run and attempt IDs and is restored.
The script also rebuilds original outputs for the following job.

Evidence is uploaded from `build/vm-ci-results/`. Raw Bazel build events are
deleted before upload because they can include the job environment. Summary
state is kept outside the checkout at `/home/runner/benchmark/last-run.json`.
Process identities include Linux boot ID, PID, and process start time, so PID
reuse does not count as process persistence. A second job within the same boot
must retain both the Bazel server and a Javac worker or the benchmark fails.

The first run includes dependency downloads and initial compilation. Later jobs
reuse all of that as well as live processes; the difference is not attributable
to persistent compiler workers alone. CPU, disk, and runner overhead also differ
from GitHub-hosted runners. Keep those comparisons separate.

## Operations

Use `systemctl status bazel-warm.service` and the runner's `svc.sh status` to
inspect services. Stop the runner before restarting Bazel or changing its
startup configuration. A VM reboot clears all live processes but retains disk
caches; both services start again at boot. To retire the experiment, remove the
runner registration in the fork's Actions settings, uninstall its service, and
disable `bazel-warm.service` before deleting the VM.
