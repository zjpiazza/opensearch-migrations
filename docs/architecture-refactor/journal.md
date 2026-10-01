# Experiment and implementation journal

Entries E-001 through E-003 are retrospective checkpoints of prior experiments.
They distinguish historical observations from evidence archived in this branch.
The current architecture baseline is recorded in [README.md](README.md).

## E-001 — Initial Bazel test experiment

- Recorded: 2026-10-01, retrospective.
- Related decision: D-005.
- Implementation: [PR #1](https://github.com/zjpiazza/opensearch-migrations/pull/1),
  `experiment/bazel-test-performance`.
- Question: can a selected test graph run and reuse results through Bazel in CI?
- Scope: selected unit/contract targets. It does not represent the full E2E suite.
- Conclusion: useful tooling feasibility work; insufficient evidence for
  whole-repository adoption or full-suite speedup.
- RFC use: revisit the pinned run, target list, and equivalent baseline before
  promoting any timing claim. No timing from this experiment is archived here.

## E-002 — WireMock sink contracts and preparation isolation

- Recorded: 2026-10-01, retrospective.
- Related decisions: D-002, D-006.
- Implementation: [PR #2](https://github.com/zjpiazza/opensearch-migrations/pull/2),
  `experiment/wiremock-record-replay`, baseline commit
  `1cdb85a222faa77a1b81862caed392c9af4aff8f`.
- Tests: `RFS/src/wiremock/java/org/opensearch/migrations/bulkload/wiremock/SinkWireMockTest.java`.
- Recordings and provenance: `RFS/src/wiremock/resources/wiremock/`.
- Method: `RFS/src/test/wiremock/benchmark.py` separates preparation, forced
  playback, and unchanged Gradle reuse. The focused source set avoids unrelated
  container fixtures and ordinary RFS test compilation. Javadoc remains checked
  separately by the experiment workflow.
- Coverage: six recorded scenarios for index creation, upsert, delete, routing,
  metadata conversion, and partial bulk failure; three negative cases for a
  missing write, duplicate write, and dropped field.
- Limitations: does not verify actual indexing, snapshot migration, Argo,
  Kubernetes, cloud behavior, or complete E2E parity. It is not an equivalent
  real-engine-versus-WireMock CI benchmark.
- Conclusion: production sink behavior can be exercised without a search engine;
  dependency preparation deserves separate measurement from test execution.
- Next: make the focused boundary part of normal production modules and map
  required assertions to contract versus real-engine tests.
- Rollback: the experiment is isolated on its fork branch; fixture/recording
  changes and preparation changes can be reviewed separately in its history.

## E-003 — Persistent VM and Bazel process reuse across GitHub jobs

- Date: 2026-10-01.
- Related decisions: D-005, D-006.
- Implementation: [PR #3](https://github.com/zjpiazza/opensearch-migrations/pull/3),
  `experiment/vm-persistent-runner`, measured commit
  `d42308b0d847a3a522f95806c11cd2673e88d39a`.
- Environment: Ubuntu 24.04 VM, 8 vCPUs, approximately 32 GB RAM, Bazel 8.4.2,
  GitHub runner 2.337.0. GitHub runner and Bazel are on the same VM.
- Method: `deployment/ci/vm/install.sh`, `deployment/ci/vm/benchmark.py`, and
  `.github/workflows/vm-persistent-runner.yml` at the measured commit. Push that
  branch to the fork with the labeled runner online, then rerun the same GitHub
  run to create a second job. Tests are forced for baseline and source-change
  phases. A unique constructor-message edit forces compilation; the unchanged
  phase must return a cached success. Source is restored afterward.
- Setup: Bazel starts in a separate systemd service before the runner accepts
  jobs. Workspace/output-base paths are stable; the runner user is non-root.

| Measurement | First successful job | Second job, same commit |
| --- | ---: | ---: |
| Preparation plus forced nine-test playback | 22.830 s | 2.115 s |
| Source edit, compilation, and forced playback | 2.659 s | 2.575 s |
| Unchanged cached result | 0.166 s | 0.114 s |
| Complete GitHub job | 31 s | 10 s |

- [First job](https://github.com/zjpiazza/opensearch-migrations/actions/runs/36907056869/job/110520123711),
  [second job](https://github.com/zjpiazza/opensearch-migrations/actions/runs/36907056869/job/110520531850).
- Durable evidence: [attempt 1](evidence/vm-run-36907056869-attempt-1.json) and
  [attempt 2](evidence/vm-run-36907056869-attempt-2.json), copied from workflow
  result artifacts. Reproduction code is pinned by the commit above.
- Result: both jobs passed all nine tests with zero skips. Both retained server
  PID 1734 and compiler PID 4429 with matching boot ID/process start times.
  Processes were also checked alive after the second job's cleanup.
- Failed setup attempt: the first run lacked a native compiler needed by Bazel's
  toolchain configuration. The installer now includes `build-essential`.
- Confounders: that failed attempt fetched some Bazel rules; the first successful
  run is not pristine-cold. Cross-job gains combine dependencies, artifacts,
  analysis, and live process reuse. The selected-source Bazel graph is narrower
  than the Gradle module graph. These numbers do not isolate compiler-worker
  gains and do not measure the full E2E suite.
- Conclusion: persistent process reuse across GitHub jobs is demonstrated.
  Whether its incremental benefit warrants Bazel adoption remains open.
- Next: compare equivalent production targets and distinguish work avoidance
  from faster execution of work that must rerun.
- Rollback: remove the fork runner registration, stop/uninstall the runner
  service, and disable `bazel-warm.service`. Disk caches and live processes are
  different resources; reboot retains the former and resets the latter.

## E-004 — Top-level architecture audit and documentation checkpoint

- Date: 2026-10-01.
- Related decisions: D-001 through D-007.
- Input: tracked code at `1cdb85a222faa77a1b81862caed392c9af4aff8f`, Gradle
  dependency declarations, application manifests, orchestration scripts, existing
  architecture/contract documents, and the preceding experiments.
- Change: establish the accepted responsibility-based layout, decision register,
  experiment journal, and durable VM result archive on
  `experiment/architecture-refactor`. No source moves or runtime changes.
- Acceptance: the user explicitly accepted the layout and requested continuous
  documentation. Operator, Go, deployment retirement, and Bazel adoption remain
  hypotheses rather than accepted implementation decisions.
- Validation: tracked-file inventory; source inspection of the concrete
  dependency/lifecycle examples; JSON evidence and local documentation link
  checks. No performance claim is made for directory organization.
- RFC candidates: modularity, lifecycle consolidation, test layering, and build
  tooling can be proposed independently. Initial evidence is strongest for the
  existence of boundary problems and feasibility of focused contract playback.
- Next: implement and document a bounded extraction of migration models and the
  search-client boundary, then compare equivalent tests before extending the
  operator prototype.
- Rollback: documentation-only checkpoint; revert its commit independently of
  the existing experiments. Use this branch's Git history to locate the change.

## Template for subsequent checkpoints

```text
E-NNN — Specific change or experiment
Date / related decision IDs:
Hypothesis and baseline:
Implementation commit or PR:
Before / after behavior and dependencies:
Reproduction command and environment:
Checks and retained evidence:
Measurements (sample count, cold/warm, cache mode, coverage):
Failures, confounders, and untested cases:
Conclusion and whether a previous conclusion is superseded:
Compatibility, rollout, and rollback:
RFC claim supported / still unsupported:
Next question:
```
