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

## E-007 — Full-suite hardware baseline

- Date: 2026-10-01. This supersedes E-006's proposed representative-group scope:
  the user requested the coverage of **all 30 Gradle shards** for comparison.
- Baseline: [fork CI run 36907315958](https://github.com/zjpiazza/opensearch-migrations/actions/runs/36907315958).
  All 30 Gradle jobs succeeded and started within three seconds of each other.
  The longest job took 68m54s, including 57m37s in the Gradle test step. Total
  allocated job time was 24.09 runner-hours; this is not CPU utilization.
- GitHub specification: this is a public repository using `ubuntu-22.04`.
  [GitHub's current reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
  lists 4 vCPU, 16 GB RAM and 14 GB SSD per runner. Initial aggregate allocation
  was therefore 120 vCPU and 480 GB RAM. The workflow sets Gradle's maximum
  workers to `nproc - 1`; runner CPU allocation is not a test JVM count.
- Buildbarn hardware: three `g5-4vcpu-16gb-80gb` execution nodes provide nominal
  totals of 12 vCPU and 48 GB RAM. Each exposes 3.89 CPU and about 13.33 GiB RAM
  as Kubernetes allocatable resources, before pod requests are subtracted.
  Nine execution containers each have a 1 CPU / 3 GiB limit: 9 CPU / 27 GiB total,
  with three containers per node. Worker coordinators and system pods consume
  additional resources. Three separate 1-vCPU/2-GB support nodes host services.
- Interpretation: GitHub had ten times the nominal execution-node CPU capacity,
  or about 13.3 times the CPU allocated to current Buildbarn test containers.
  Nine worker pods are not nine independent machines. CPU models, actual CPU
  utilization and storage performance have not been matched or measured.
- Benchmark method: compare the full Gradle shard coverage and Bazel execution
  on the same hardware/resource budget; retain the existing GitHub run as the
  operational baseline. Report preparation, forced test execution, cached-result
  reuse, total wall time, failures and coverage separately. Hold source revision,
  test configuration and dependency versions constant. Coverage includes the
  non-Java tests invoked by `allTests`, not only the Java test classes.
- Remaining work: export or port the complete test graph, reconcile test reports
  across all shards, and provide container support and suitable memory budgets
  for the real search-engine/Testcontainers tests. Current execution containers
  lack Docker support. No full-suite Bazel run or full-suite speedup is claimed.
- Evidence: [hardware and per-shard timings](evidence/full-suite-hardware-baseline.json),
  reduced from GitHub Jobs API results and live Kubernetes node/deployment data.
  Raw API responses remain in ignored `build/full-suite-evidence/`.
- This checkpoint changes documentation only; no cloud capacity or worker limits
  were changed. Rollback is removal of this checkpoint and its evidence file.
- Clarification following user feedback: equal hardware is a diagnostic control,
  not a prerequisite for demonstrating better CI. The primary practical question
  is whether the existing smaller Buildbarn pool can match or beat the GitHub
  baseline by reusing results and executing only affected work. CPU ratios alone
  cannot answer that question, and do not predict warm-cache latency.
- Incremental benchmark cases: populate the remote cache once, then use fresh
  clients for an unchanged revision, a leaf implementation change, and a shared
  dependency change. Request the entire suite in every case. Compare wall time,
  execution counts, the time represented by reused actions, and the longest
  uncached dependency chain; raw action hit percentage alone is insufficient.
  Also retain a full execution run for correctness and worst-case capacity.
  Changes must be substantive and representative; an unchanged rerun alone
  cannot establish typical pull-request latency.
- Existing Gradle baseline already enables `org.gradle.caching=true` and restores
  Gradle state with `setup-gradle`, plus Docker image caches. Pull-request jobs
  use read-only Gradle cache access; main-branch pushes may write. Any claimed
  improvement must account for this existing caching. Fine-grained targets and
  correctly declared inputs determine how much additional reuse Bazel achieves.

## E-008 — Execute the complete Gradle test workload through Bazel

- Date: 2026-10-01. Scope explicitly includes all 30 shards' coverage.
- Implementation: opt-in [Gradle runtime export and Bazel bridge](../../tools/build/bazel/full-suite/README.md).
  Gradle prepares existing compiled runtimes, Javadoc, resources, npm dependencies
  and the generated GraalPy fixture. Bazel receives declared runtime inputs and
  schedules individual JUnit class/task combinations and the six npm checks.
  This measures test scheduling/result reuse; it is not a native Bazel build of
  the full Java/polyglot dependency graph. Preparation remains separately timed.
- Discovery: 123 Gradle JVM task definitions, 112 with candidate class files;
  JUnit filters select 433 class/task combinations across 55 tasks. Six npm checks
  bring the complete request to 439 Bazel test targets. Normal/slow tag settings,
  memory-leak settings, isolated tasks and the additional WireMock task retain
  separate configurations. Striping parameters are omitted so every case runs.
- Coverage baseline: downloaded reports from all 30 successful fork jobs. Their
  HTML union has 4,794 distinct successful cases, 5,055 reported successful
  executions and 138,856 skipped entries. All 433 successful class/task pairs
  exactly match discovery, with no missing or extra pairs. This is discovery
  parity, not yet successful runtime/parameterized-case parity. See
  [discovery evidence](evidence/full-suite-discovery.json).
- Runtime placement: six lightweight 1-CPU/1-GiB runners and three integration
  1-CPU/3-GiB runners, each integration runner paired with a Docker daemon limited
  to 1 CPU/6 GiB. Two lightweight and one integration pod per dedicated node;
  no new nodes. Initial bridge targets use integration slots conservatively.
  Each Docker daemon has a separate 40-GiB emptyDir, localhost API and the same
  action-volume path as its runner, enabling Testcontainers bind mounts.
- Authorization: automatic review initially rejected privileged Docker sidecars
  and public HTTP/HTTPS egress. The user explicitly approved the prepared
  configuration before deployment. No host socket/host filesystem mounts or
  execution credentials were added. All three sidecars ran a disposable Alpine
  container successfully. This remains trusted-code infrastructure.
- Preparation findings: fixed an exporter cross-project task-state-lock error;
  full prerequisites then passed (486 tasks, 480 up-to-date on the retry).
  Fixed replacement of read-only copied JDK files. The bridge's JUnit console
  version matches the Gradle runtime (Platform 1.14.0/Jupiter 5.14.0).
- Fixture compatibility: snapshot paths now use `project.root` with the relocated
  `libs/migration-engine` path. An optional `test.image.builder` hook runs the
  existing ES Dockerfile/version/build arguments without nested Gradle startup;
  ordinary Gradle behavior remains the default. These are fixture changes, not
  replacement assertions or mocked search engines.
- Infrastructure findings: Buildbarn requires lexicographically ordered platform
  properties. Fixed integration-worker registration and set rolling updates to
  allow one unavailable pod (required with one integration pod per node).
  Integration configuration has a separate ConfigMap to avoid restarting the
  scheduler/cache when tuning those workers. Local kubectl forwarding dropped
  connections during setup; a supervised tunnel is used for this experiment.
- Cache limitations: existing Docker tags, ES downloads and unpinned Pydantic
  preparation are external state. Declared runtime artifacts capture the prepared
  Python/npm/Java contents, but container-image immutability is not yet enforced.
  Container test-result reuse is experimental; production needs pinned inputs or
  exclusion of affected actions, alongside scheduled forced executions.
- Execution and performance: the complete 439-target run has started. Record
  final success/failure, case comparison and cache/incremental measurements below
  when available. No full-suite speedup is established by this checkpoint yet.

- Validation follow-up: compare Gradle's method-name column (including parameter
  index) with JUnit XML method names. Display labels merged distinct methods; the
  corrected baseline is 4,794 passing cases plus five disabled cases. The 5,055
  successful executions include 261 redundant WireMock executions (nine cases
  repeated across the other 29 shards). Class/task discovery remains unchanged.
- Reporting overhead: a passing replay class produced 126 MiB of stdout, then
  Bazel duplicated it into a 126 MiB synthetic XML report. The wrapper now retains
  complete gzip-compressed diagnostics and supplies the actual compact JUnit XML.
  This is a harness/reporting improvement, not faster test execution.
- Interrupted validation: full-4 stopped intentionally after 72 passing targets
  for the reporting fix; full-5 was interrupted before completion. Neither is a
  complete timing result. GraalPython failed when Java used the worker UID's
  unwritable default home. A diagnostic with writable user.home passed; the
  wrapper now sets Java user.home to the same action-local directory as HOME.
- Baseline duration analysis: summing successful case durations across the 30
  reports (median for duplicate executions) gives 45,331.1 seconds, about 12.6
  hours. This is aggregate case time, not elapsed CI time or CPU consumption.
  It excludes outside-case setup; class-local fixture reuse and different worker
  hardware prevent converting it directly into a forecast for this run.
- Dependency prediction before incremental measurement: the dashboard output is
  on seven discovered targets' classpaths; the shared runtime output is on 404
  of 439 targets' classpaths. These are graph-derived affected sets, not observed
  cache misses. A broad runtime-library change can therefore invalidate most of
  this bridge. Splitting shared utilities into smaller dependency targets is a
  separate architectural proposal; remote caching alone cannot remove that cost.
- Recovery: the first interruption stopped full-5; a later server restart left
  full-6 and its tunnel alive, so no replacement run was started. Saved the
  harness fixes on the fork at `080c1bef1`. A driver now waits for complete seed
  coverage before running fresh-client unchanged, leaf and shared scenarios; it
  records status and restores generated runtimes after temporary source changes.
- Monitoring follow-up: added a loopback-only dashboard at `localhost:8765`
  showing the actual 439 targets, results, durations, cached results and active
  worker assignments. It reads the BEP and inspects wrapper process names/specs
  every ten seconds; it does not expose process environments or change workers.
  Verified HTTP responses against live results and checked browser-script syntax.


## E-009 — Scale Buildbarn integration workers from scheduler load

- Date: 2026-10-01. User requested `bb-autoscaler` and enabled cluster autoscaling.
  Verified pool `workers` in cluster `bazel`: minimum 3, maximum 9 nodes. Each node
  remains `g5-4vcpu-16gb-80gb`. Recommended nine because the current Bazel client
  submits at most nine concurrent actions and integration pods require separate
  nodes. This is an initial experimental cap, not an established optimal size.
- Added the official pinned autoscaler, a small private Prometheus deployment,
  scheduler metrics service, scoped Role/ServiceAccount and API egress policy.
  Controller authorization is limited to patching `worker-integration`; it cannot
  change other deployments, nodes or DigitalOcean settings.
- Autoscaler source/image: `9e8d8bec87763a812f3817a8df57155314e9688a`;
  Prometheus `v3.15.0`; both container images pinned by registry digest.
- Policy: integration replicas 3–9, one action each; six lightweight replicas
  remain fixed. Queue demand retains registered capacity while actions remain,
  then permits downscaling after a 15-minute idle window. Failed scheduler scrapes
  suppress scaling decisions. This does not replace a drain-aware termination
  design for arbitrary new-work/scale-down races.
- Validation: Kubernetes server dry-run passed; Prometheus configuration and eight
  PromQL assertions passed. RBAC checks permit patching the integration deployment
  and deny patching the frontend. At 21:17:43 UTC the initial live autoscaler job
  read demand 9 and successfully changed the deployment from three to nine.
- Existing worker pod templates were not changed or restarted. Removed replicas
  from the source manifest and updated only its last-applied annotation so future
  applies do not fight the autoscaler. New worker replicas await node capacity.
- Benchmark consequence: full-6 is now a run with changing capacity, initially
  three integration slots and subsequently up to nine. Preserve the transition
  timing and do not label its elapsed time a fixed-three-worker baseline. Cache
  reuse and source-change comparisons remain meaningful with allocation reported.
- Rollback: suspend the `bb-autoscaler` CronJob to stop decisions. Remove its
  resources/configmaps only after workloads finish; worker replicas and the
  separately owner-configured node autoscaling bounds need explicit restoration.
- End-to-end scale-up: Kubernetes emitted `TriggeredScaleUp` for all six new
  worker pods, requesting pool growth from 3 to 9 (maximum 9). Recurring controller
  jobs subsequently completed successfully. One job retried while Prometheus was
  being recreated for the updated rule-test fixture; no worker count was reduced.
- Live dashboard now separates ready worker capacity from active test processes
  and reports pods waiting for capacity; pending workers do not suppress live
  observations from the ready workers.
- Capacity evidence: [worker autoscaling](evidence/worker-autoscaling.json)
  records the validated bounds and scale-up events. DigitalOcean confirmed nine
  desired nodes: three running and six provisioning at this checkpoint.
- Scale-up verified at 2026-10-01T21:24:12.753503+00:00: all nine integration workers and all nine
  execution nodes were Ready. Existing three worker pods retained zero restarts.
  A full-manifest server dry-run confirmed subsequent applies preserve the
  autoscaler-owned nine replicas. The benchmark continued to 61 passing targets.

## E-010 — Measure worker density before changing resource allocations

- Date: 2026-10-01. User asked whether more, smaller workers would help and whether
  the execution pool was saturated. Read-only sampling during full-6; no worker
  configuration changes or benchmark restarts.
- Kubernetes Metrics API was unavailable. Collected three kubelet summary and
  cAdvisor snapshots approximately 30 seconds apart on all nine execution nodes.
  Counter timestamp intervals were 60–71 seconds, around 21:33–21:34 UTC.
  [Measurement evidence](evidence/worker-utilization.json) includes per-node CPU,
  memory working sets, throttling and limitations.
- Pool CPU averaged about 12.84 of 36 nominal cores (35.7%). Individual node
  averages ranged from 0.21 to 2.36 cores. Total node memory working set ranged
  from 30.3 to 35.4 GiB across the three snapshots. This is substantial aggregate
  headroom during this window, not evidence of whole-suite peak requirements.
- Integration runner limits are one CPU each. Several runners experienced CPU
  throttling despite pool headroom; one had throttling in 84.6% of its active CFS
  periods. That percentage does not measure lost wall time. Six lightweight
  workers were effectively idle because the bridge routes all targets to the
  integration platform. Client concurrency is capped at nine actions, and required
  anti-affinity restricts integration pods to one per node.
- Resource-accounting finding: inspected live nested Docker containers in pod
  `worker-integration-7b5c4c8659-s8f6d`. Their cgroups were `/docker/...`, outside
  the daemon's `/kubepods/burstable/...` cgroup, with `cpu.max = max 100000` and
  `memory.max = max`. Docker inspect also reported no explicit CPU/memory limits.
  Thus the sidecar's one-CPU/six-GiB limits cannot be treated as limits for the
  entire test workload. Verify and enforce nested-container accounting before
  increasing integration-pod density; node measurements are the better capacity
  evidence for this setup.
- Recommendation: classify Docker-independent tests and route them to lightweight
  slots; measure throughput with additional small slots and an increased client
  concurrency cap. Keep a separate container-test tier, verify cgroup isolation,
  and compare CPU bursting and two-slot-per-node placement at fixed node count.
  Do not reduce integration memory limits based on this short sample. Any density
  experiment must adjust placement, client concurrency and autoscaler bounds
  together, and report elapsed time, peak memory, throttling and failures.
- Full-6 has reported failures in `KafkaRestartingTrafficReplayerTest` and
  `LuceneDocumentsReaderTest`. Timing/parallel scheduling may matter, but resource
  causation is unconfirmed. Resolve successful full coverage before interpreting
  cache comparisons as a valid replacement for the Gradle baseline.
- Sequencing decision: user requested cache validation before concurrency work.
  Keep current worker sizing, placement and client concurrency unchanged. First
  establish complete passing coverage, then repeat unchanged inputs from a fresh
  Bazel output base against the same remote instance. Confirm all 439 successful
  test results are remote cache hits, no locally cached test results or fresh test
  executions are counted as remote reuse, and cached reports retain all 4,794
  baseline passing cases. Inspect execution evidence for any unexpected misses.
  Then use the already prepared leaf/shared scenarios to check invalidation of
  changed inputs. Record preparation and Bazel times separately. The queued driver
  deliberately stops on a failed seed; full-6 had three failed targets at this
  checkpoint, so an all-green cache result is not yet established.

## E-011 — Explain the 43-minute PipelineEndToEndTest target

- Date: 2026-10-01. Inspected completed full-6 JUnit reports and source without
  changing the running suite. The dashboard entry is a whole class/task target:
  four parameterized methods across seven migration pairs, 28 cases in total.
- JUnit launcher elapsed time was 2,595.981 seconds (43 minutes 16 seconds).
  Twenty-five passing cases accounted for 794.404 seconds (13 minutes 14 seconds).
  Three `pipelineWithComplexData` invocations, indexes 3, 6 and 7, each exhausted
  the existing ten-minute timeout, accounting for 30 minutes. The longest passing
  case took 131.452 seconds. [Per-case evidence](evidence/pipeline-e2e-duration.json).
- All 28 cases have successful executions in the Gradle baseline. The current
  43-minute failure is therefore not a demonstrated healthy execution cost.
  Timeout stacks show interrupted Reactor blocking waits; their root cause is
  still unresolved. Do not equate a timeout stack with proof of CPU starvation.
- When this target must execute, adding workers cannot divide it automatically:
  the current bridge schedules a class/task as one action. After fixing the
  timeouts and verifying remote cache behavior, evaluate smaller targets grouped
  by migration pair or method. Preserve all assertions and parameter coverage,
  and measure duplicated image/fixture setup: the class currently shares a
  snapshot fixture cache, which can make overly fine splitting more expensive.
- A successful remote cache hit can avoid execution of the whole target on
  unchanged inputs. A cache miss still pays its execution cost. Keep concurrency
  unchanged as requested; this entry records a later optimization candidate,
  not an achieved speedup or a decision to alter this run.
- Diagnosis follow-up: all three failures stop inside snapshot unpacking. The
  failing pairs are OS 1.3.20 → OS 2.19.4, ES 7.10.2 → OS 3.7.0, and ES 6.8.23 →
  OS 3.7.0. Target containers started and accepted index creation before each
  stall. The unpacker logged 9/10, 9/10, and 12/13 individual file starts, then
  stopped progressing until the enclosing test timeout.
- `SnapshotShardUnpacker.unpackFilesInParallel` schedules file tasks on the shared
  Reactor bounded-elastic scheduler, then blocks its caller on `latch.await()`.
  Here that caller already occupies a thread of the same scheduler. Reactor can
  queue a child task behind the blocked caller when the backing-thread cap is
  reached; idle threads elsewhere do not necessarily rescue that assigned task.
  The live runner JVM reports one effective CPU, giving the default pool ten
  backing threads. The unpacker permits sixteen concurrent file tasks.
- Reproduced the defect with the **unchanged exported production unpacker**, the
  same JDK and dependency jars, and thirteen synthetic one-byte inline snapshot
  files. No Docker, network, cloud provider, or source changes were involved.
  With `-XX:ActiveProcessorCount=1`, one of three attempts remained stuck after
  twelve files; its thread dump points at the unpacker's `latch.await()` on
  `boundedElastic-1`. With four visible CPUs (pool cap forty), all three attempts
  completed. A three-second diagnostic watchdog interrupts the stuck attempt;
  this is not a modified production timeout. Timing affects reproduction.
- [Reproducer and recorded logs](evidence/unpack-starvation/run.py). Run with an
  existing full-suite export using `python3
  docs/architecture-refactor/evidence/unpack-starvation/run.py`.
  [Reactor scheduler documentation](https://projectreactor.io/docs/core/3.7.2/api/reactor/core/scheduler/Schedulers.html)
  describes the processor-derived cap and fixed assignment of backing threads.
- Conclusion: a reproduced production scheduling defect is the strong explanation
  for these three stalls, exposed by the experiment's smaller JVM CPU allocation.
  Original failing-process thread dumps were not captured, and a corrected full
  E2E rerun is still required for definitive case-level confirmation. Four-CPU
  diagnostic success is not a complete E2E comparison or a guaranteed workaround.
  The robust fix should remove the wait for child work on the caller's own shared
  pool (for example, asynchronous composition); simply lengthening timeouts does
  not resolve the dependency cycle. No live sizing/concurrency changes made.

## E-012 — Verify remote cache replay before concurrency changes

- Date: 2026-10-01. User requested cache validation first. Live process inspection
  found that full-6, its continuation driver and local tunnel had stopped. The
  saved BEP contains 429 passing targets and three failing targets, without a
  build-finished event. The previous `waiting-for-seed` status was stale; corrected
  it to report interruption. No completed full-suite result is inferred.
- Selected exactly the 429 recorded passing targets. This deliberately tests
  cache mechanics independently of repairing the seed's failures. Ten of the
  439 targets remain unvalidated; their identities are retained in the evidence.
- Restored the authenticated frontend tunnel and ran an unchanged-input replay
  with a fresh, previously nonexistent Bazel output base, disabled disk cache,
  the same `migrations-pilot` instance and `--experimental_remote_require_cached`.
  Kept `--config=buildbarn`, nine client jobs, `--test_timeout=7200`, and disabled
  local fallback. A cache miss must fail instead of executing or seeding a result.
  Target patterns, full command, BEP, execution log and timing are retained under
  ignored `build/full-suite-evidence/cache-validation-2/`.
- Result: **429/429 remote cache hits, zero local test-result hits, zero fresh
  test executions**, exit code zero. End-to-end client elapsed time was **29.280
  seconds**; Bazel reported 27.289 seconds. Fresh-client analysis/runfiles setup
  and downloaded reports are included; Gradle compilation/runtime export are not.
- Independent checks: all 429 execution records identify `remote cache hit`.
  Compared 2,566 output files (233,003,630 bytes) against seed outputs using SHA-256:
  zero mismatches. Reports contain 4,414 unique passing JUnit cases and three
  skipped cases. The other 380 baseline passing cases are outside this validation;
  cached XML does not mean those 4,414 cases executed again.
- Negative control: requested the already-cached `UnboundVersionMatchersTest`
  from another fresh client with an added declared test environment variable.
  The action missed the cache and was rejected with `EXECUTION_DENIED` and
  `Action must be cached due to --experimental_remote_require_cached but it is not`.
  No test ran. This establishes invalidation for that declared input; the earlier
  leaf/shared source-change scenarios remain pending.
- Connection failures are excluded from the result: the first positive attempt
  found no local tunnel, and the first negative attempt hit a tunnel reset.
  Retried each from a new output base after restoring connectivity. The successful
  negative control managed its tunnel for the duration of the command.
- [Compact evidence and target coverage](evidence/remote-cache-validation.json).
  Cache reuse works for the validated set, including container integration tests.
  This is not yet an all-green 439-target benchmark, nor proof that mutable Docker
  image tags/other external state are fully represented in cache keys. Worker
  sizing, placement, concurrency, test code and timeouts were unchanged.

## E-013 — Deploy mixed worker sizes and increase concurrent actions

- Date: 2026-10-01. User authorized increasing concurrency and adding differently
  sized workers after cache validation. Raised the Buildbarn client limit from
  nine to eighteen actions. Worker pools now autoscale independently: lightweight
  3–9, standard integration 2–6, large integration 1–3, one action per pod.
  The owner's node-pool bounds remain 3–9 four-vCPU/16-GB nodes.
- Lightweight runners request 0.5 CPU and can use one CPU; standard integration
  runners request/limit one CPU; large integration runners request/limit two.
  All runners have 3 GiB RAM. Docker sidecars reserve 0.5 CPU/6 GiB and have
  1.5-CPU/6-GiB limits. Both integration tiers share required anti-affinity, so
  no node hosts two Docker workers. Lightweight pods also require separate nodes;
  one large plus one lightweight pod requests 3.10 CPU/12.25 GiB before system pods.
- Corrected nested Docker accounting: `start-docker.sh` places daemon processes in
  a child cgroup, enables cgroup-v2 controllers, and starts Docker with a parent
  beneath the sidecar's Kubernetes cgroup. A disposable container verified that
  ancestor limits are 150000/100000 CPU quota and 6,442,450,944 bytes memory.
  No host Docker socket or host filesystem mounts were introduced.
- Diagnosed earlier lost workers as eviction after the Docker emptyDir exceeded
  40 GiB. Added Buildbarn's `runCommandCleaner` at idle/action boundaries to remove
  leftover containers, dangling images and build cache. Retain tagged images
  until their layers exceed 20 GiB, then prune unused images. This removes
  cross-action accumulation; per-action peaks can still exceed the volume limit.
- Explicit `worker-routing.json` policy retains all 439 targets: 101 lightweight,
  327 standard integration, 11 large integration. Reviewed lightweight source
  roots for Docker fixture usage; unclassified tasks default to integration.
  Large classes include the long E2E tests and CPU-sensitive reader/replayer tests.
  Runtime export and an idempotent routing-only update share the same policy;
  compiled code, fixture archives and test assertions were unchanged.
- Applied only worker, worker-config, network-policy and autoscaler resources.
  Saved pre-change resources under ignored `mixed-workers/rollback-resources.yaml`.
  Used a single large-worker canary before rolling the existing pools. Corrected
  its missing read-only config mount during startup. Server dry-run passed; all
  three Deployments completed rollout. Existing Prometheus rule assertions passed.
  Autoscaler RBAC allows the three worker Deployments and denies the frontend.
- Smoke validation: three real remote actions, zero result-cache hits, all passed
  in 22.653 seconds including cold worker input setup. JUnit reports identify the
  expected lightweight, standard and large pod hostnames. Notably the previously
  failing isolated `LuceneDocumentsReaderTest` passed on the large tier in a
  5.6-second action. This is not proof that every timing-sensitive failure is fixed.
- Started **all 439 targets** as full-7 with eighteen jobs and fresh action-cache
  namespace `migrations-mixed-workers-1`. Shared input/CAS caches may be warm;
  nodes and worker counts grow during this run. A supervised private tunnel
  restarts after port-forward resets. The localhost:8765 dashboard now polls all
  worker pools and excludes terminated/failed pods from current capacity.
- Queued an unchanged-input fresh-client replay in that same namespace, gated on
  complete passing target/case coverage. Added explicit instance/scenario options
  to the continuation driver so it cannot accidentally compare against the old
  namespace. Leaf/shared source-change scenarios are not queued for this run.
- [Configuration and validation evidence](evidence/mixed-workers.json). Full-run
  outcome and timings remain pending. Rollback: suspend the autoscaler, wait for
  work to finish, restore worker/config/autoscaler resources from the saved state,
  remove the new large Deployment, and restore the prior routing plus `--jobs=9`.
  Do not restore old replica ownership or roll workers while tests are active.
- Capacity verified after scale-up: all nine execution nodes were Ready, with
  nine lightweight, six standard integration and two large integration workers
  Ready (17 total). The large tier can grow to three when its queue demands it.
  Autoscaling selected those counts from live full-7 demand. The unchanged replay
  now explicitly requires remote cache hits and disables disk cache/local-result
  uploads, so misses fail rather than silently rerunning tests.

### E-014 — Remove client admission starvation and expose pool imbalance

- User observed five executing tests despite seventeen Ready workers. Live checks
  found six standard integration test processes, with nine lightweight and two
  large workers idle. The client admitted only eighteen actions, counting queued
  work as well as execution; standard-platform requests occupied those slots.
- Raised opt-in `build:buildbarn --jobs` from 18 to 512 so all 439 targets can reach
  their matching queues. This is admission, not 512 concurrent containers: the
  existing worker deployments still cap execution at 9 lightweight + 6 standard
  + 3 large slots. No node bounds, container limits or test assertions changed.
- Started full-8 from a fresh client in the same `migrations-mixed-workers-1`
  namespace. Confirmed 21 scheduler `OtherInvocation` in-flight deduplications and
  recovered 83 cached results before retiring full-7 with SIGINT (exit 8 is an
  intentional handoff). This continuation is not a new cold timing benchmark.
  Repointed the localhost:8765 monitor and gated unchanged-cache replay to full-8;
  stopped the old replay driver to prevent a second comparison from starting.
- All three pools received work after admission widened. The third large worker
  became Ready, giving eighteen total. A subsequent dashboard validation observed
  six standard and three large test processes simultaneously, 215 passed targets,
  and all 101 lightweight targets already complete. This reveals a second limit:
  lightweight slots cannot consume the remaining Docker-platform work.
- Kubelet cumulative CPU counter deltas across all nine execution nodes measured
  **6.06 of 36 nominal cores (16.8%)** over 30–31 seconds, after lightweight work
  finished. This is a short workload-phase sample, not a run-wide utilization
  average or speedup result. A prior instantaneous sample was 4.29 cores, but the
  windows/work mix differ and do not support a controlled improvement percentage.
- Full CPU saturation is **not achieved**. Two existing Docker workers request
  18.25 GiB versus approximately 13.33 GiB allocatable per node. Removing their
  anti-affinity or raising the autoscaler ceiling alone will not fit more workers.
  Next experiment should measure per-target runner and nested-container peak
  memory, then validate a smaller Docker tier for eligible targets. Retain room
  for the exported 2-GiB JVM heap. Also review conservative default Docker routing
  at class level; unknown targets currently require Docker even when they may not
  use it. These changes need coverage/failure and elapsed-time comparisons, not
  just higher worker counts. Do not lower reservations based on average memory.
- Added per-pool Ready capacity, running test processes, pending targets and passed
  results to the dashboard. Explain that process counts exclude preparation and
  uploads, and that pending is an observation state rather than queue depth.
  Validation: Python AST parse, JavaScript syntax check, live API consistency for
  all 439 targets and all eighteen workers, and `git diff --check`.
- Four npm targets still fail to upload their shared 240,158,720-byte input blob.
  The coverage gate must prevent claiming a successful whole-suite cache replay
  until those errors and any later failures are resolved. The full run is ongoing.
- [Measurement and handoff evidence](evidence/queue-admission.json). Raw node,
  scheduler and dashboard snapshots remain under ignored
  `build/full-suite-evidence/queue-admission/`. Revert the admission setting to
  roll back; doing so requires a new client and reintroduces the observed limit.
