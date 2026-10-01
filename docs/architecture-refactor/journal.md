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

## E-005 — Implement the source layout

- Date: 2026-10-01. Decisions: D-001, D-007, D-008.
- Baseline: `dc13cadb5`, the documentation checkpoint on
  `experiment/architecture-refactor`; its parent is the WireMock experiment.
- Hypothesis: source roots can reflect application/library/deployment/test/tool
  responsibilities while preserving build identities and current behavior.
- Implementation: `8060ee7a7`, [PR #4](https://github.com/zjpiazza/opensearch-migrations/pull/4);
  [layout-map.json](layout-map.json) records exact relocations. The PR is stacked
  on `experiment/wiremock-record-replay` so that WireMock changes are not repeated.
- Change: move 2,926 files, preserve all 3,083 baseline files, assign 56 explicit
  Gradle locations, update source-dependent CI/packaging/scripts/docs, and add a
  layout check to PR CI. BuildSrc implementation lives in `tools/build/gradle`
  behind the root Gradle shim; Jenkins shared-library `vars/` remains at root.
- Path audit: repaired shell root calculations, Python fixture roots, Rust skill
  lookup, Helm/Terraform paths, Docker build contexts, CI matrix conditions,
  release assets, dependency-update locations, and local documentation links.
  CDK synthesis now declares its actual project tree as inputs, including its
  entry points and configuration rather than a nonexistent nested source path.
- Before/after dependencies: unchanged module graph and public artifact names.
  Existing TypeScript orchestration stays together in `apps/orchestration`.
  Migration model/runtime cleanup and operator implementation remain future work.
- Validation: all Java production/test sources compile; nine WireMock cases pass;
  TypeScript type checks and 50 suites pass (453 tests, two skips); targeted Python
  checks pass; 211 isolated Rust library tests pass; Helm chart packaging and CDK
  synthesis succeed. Mocked AWS bootstrap and Jenkins setup checks pass. All 100
  shell scripts parse, all 167 binary fixtures are byte-identical, and local
  Markdown links that resolved before relocation still resolve. Repository-wide
  Spotless and Python lint pass. Six changed workflows pass structural actionlint.
- Reproduction and compact results: [validation evidence](evidence/layout-validation.json).
  Install Node workspace dependencies with `npm ci --prefix apps/orchestration`;
  use Node 24.3.0 for the recorded npm commands. Python checks used a temporary
  venv with the console Pipfile.lock dependencies and the automation tabulate pin.
  Raw local logs are intentionally excluded from Git.
- Test-environment findings: the first Python pass had 244 successes and ten setup
  errors because the sandbox could not write the existing Gradle distribution
  lock. Running `pytest -q gradle/tests` with cache access passed all 12 cases.
  The initial Rust run unexpectedly attempted live ECR calls from
  `mirror_fails_without_ecr_credentials`: its command mock does not intercept the
  native SDK. Calls were denied and the run was stopped. Re-running with AWS
  credential sources disabled passed all 211 library tests. No successful cloud
  modification was observed. Existing workflow Shellcheck warnings remain;
  structural actionlint is not a claim of clean Shellcheck.
- Rust reproduction: from `apps/cli`, unset AWS access/session keys, profile and
  default profile, web-identity token/role, and container credential URI variables;
  set `AWS_CONFIG_FILE=/dev/null`, `AWS_SHARED_CREDENTIALS_FILE=/dev/null`, and
  `AWS_EC2_METADATA_DISABLED=true`; run `cargo test --offline --locked --lib` in a
  network-restricted environment with the pinned toolchain/dependencies installed.
- Measurement: one warm local WireMock path smoke run took 2.136 s preparation,
  4.738 s forced playback (nine tests, 1.604 s test time), and 2.096 s unchanged
  Gradle reuse. This does not establish a relocation speedup or full-E2E benefit.
- Limits: no full migration E2E, live cloud deployment, image publication, or
  external Jenkins/Cloud Build execution was validated. CI results remain separate
  from these local checks. Existing release-time download URLs retain their
  published artifact names; source-checkout paths change.
- Rollout: update external Jenkins script paths from `jenkins/...` to
  `tools/ci/jenkins/...` and Cloud Build triggers to `tools/ci/cloudbuild.yaml`.
  Update any downstream source-path consumers using the move map. Gradle commands
  such as `:RFS:wiremockTest` stay valid.
- Rollback: revert this source-layout commit and restore external path settings;
  the preceding documentation checkpoint and separate performance experiments
  remain available.
- Conclusion/RFC claim: physical organization is implemented and locally checked.
  The result makes ownership easier to navigate; it does not remove languages,
  isolate provider dependencies, replace Argo, or establish faster test execution.
- Next: extract the migration-model/search-client dependency boundary as a separate
  change, with equivalent tests and before/after preparation measurements.

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

## E-006 — Buildbarn on a dedicated Kubernetes execution pool

- Date: 2026-10-01. Related decisions: D-005, D-006, D-007.
- User supplied context `do-atl1-bazel` and requested use of the dedicated node
  pool with more workers than the initial two-worker proposal.
- Implementation: `experiment/buildbarn-remote-execution`, based on `c172aa63f`.
  Deployment and reproduction: [Buildbarn README](../../deploy/ci/buildbarn/README.md).
- Upstream input: Buildbarn deployment commit
  `d4a6ca38e5f77959b42fccaa34a3320253683bc2`, with pinned container versions.
- Capacity decision: nine single-slot workers across three 4-vCPU/16-GB nodes;
  scheduler/frontend/storage on the other three 1-vCPU/2-GB nodes. Reserve the
  execution node pool using a persistent DigitalOcean NoSchedule taint. Node
  counts and autoscaling are unchanged.
- Configuration: private ClusterIP services, authenticated localhost port-forward,
  namespace network policy, persistent cache volumes, no execution credentials,
  and explicit Bazel remote strategy with local fallback disabled.
- Source scope: port the existing narrow WireMock Bazel graph to the refactored
  layout. This checkpoint establishes remote execution infrastructure; it does
  not migrate the full integration suite or demonstrate a full-suite speedup.
- Validation: manifests render and pass client dry-run; all 12 service/worker
  pods are healthy with zero restarts. Nine execution pods are spread three per
  dedicated node; all three nodes have the NoSchedule taint. The three cache PVCs
  are bound. The relocated Bazel target loads and executes successfully remotely.
- First execution: 117.873 s elapsed, 224 remote actions and no remote cache hits;
  compilation and the nine-test suite execute remotely. This includes first-run
  dependency/toolchain preparation and is not a steady-state benchmark.
- Capacity check: `--nocache_test_results --runs_per_test=9` passes in 9.793 s.
  Worker action metadata confirms nine test executions on nine distinct pods,
  three per node. These are copies of the same nine-test suite, not 81 distinct
  scenarios. Individual suite execution durations range from 4.3 to 5.5 s.
- Cache check: a fresh client output directory takes 18.162 s, reusing 222 remote
  actions and executing the test/report actions. A second fresh client then takes
  11.962 s, with all 224 remote actions cached and zero test execution. Forcing
  tests in the preceding phases did not seed reusable remote test results; the
  normal cache-enabled run did. These timings include fresh client analysis and
  downloads and do not isolate cache lookup latency.
- Evidence: [Buildbarn validation](evidence/buildbarn-validation.json), including
  test success counts, execution strategy, cache counts, and worker identities.
  Raw build events and action logs remain ignored because they can carry client
  environment details. [Reproduction](../../deploy/ci/buildbarn/README.md#validation).
- Setup findings: dropping all worker-coordinator capabilities prevented access
  to the runner-owned Unix socket. Restoring only DAC_OVERRIDE to that sidecar
  fixed it; the test runner still drops all capabilities. The execution platform
  needed an explicit `platforms` module dependency. Startup socket-not-found
  messages stopped after runner initialization. The DigitalOcean pool taint was
  also applied explicitly to existing nodes.
- Limitations: this retains the nine-test source slice, not the full Gradle graph.
  No full-suite speedup, automatic JUnit sharding, high availability, or CPU
  utilization result is established. The new cluster lacks the Metrics API.
  Bazel 8.4.2 reports a deprecated remote API version against this Buildbarn
  version; execution and caching nonetheless pass. GitHub runner integration is
  separate; this validation uses the local client and an authenticated tunnel.
- Conclusion: the dedicated nine-slot Kubernetes execution pool and cross-client
  remote result reuse are demonstrated. Next, migrate a representative expensive
  integration group with unchanged assertions and compare equivalent workloads.
- Rollback: scale workers to zero or remove the experiment namespace/PVCs when
  cache data is no longer wanted. Pool reservation removal is a separate change;
  see the deployment README. No node count or autoscaling settings were changed.
