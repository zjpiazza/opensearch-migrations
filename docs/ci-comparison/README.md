# Paired CI experiment: scope and measurement contract

Both comparison branches start at `83e9c4e5ab37cd40393ddc53966f86d9487d6e3c`:

- `experiment/ci-with-bazel`
- `experiment/ci-without-bazel`

The branches currently establish the common baseline and inventory. They do not
yet contain completed full-suite benchmark workflows or new speedup results.
`backend.json` identifies the requested backend without changing product code.

## Implemented workflow entry points

The current branches add manual GitHub Actions entry points for the bounded
**Gradle/JVM allTests** comparison. These workflows intentionally do not claim to
measure the Jenkins deployment E2E jobs.

- Without-Bazel branch: `.github/workflows/ci-comparison-gradle.yml`
- With-Bazel branch: `.github/workflows/ci-comparison-bazel.yml`
- Shared evidence helpers: `tools/ci-comparison/`

The Gradle workflow runs the existing striped `allTests mergeJacocoReports`
path. The Bazel workflow exports the Gradle runtime and then runs the same
exported suite through Bazel. Bazel has two execution modes:

| Mode | What it measures | Notes |
| --- | --- | --- |
| `local` | Bazel scheduling/cache behavior on the GitHub-hosted runner | Uses a local Bazel disk cache namespace and the runner Docker socket. |
| `buildbarn` | Bazel with remote execution/cache against the Kubernetes Buildbarn service | Requires an explicit `BUILDBARN_KUBECONFIG_B64` secret and existing worker capacity. The workflow refuses to scale the cluster. |

For local cache-transfer experiments, run a successful `cold-forced` seed first
and reuse its `cache_namespace` as `seed_cache_namespace` for `warm-forced`,
`unchanged`, `leaf-change`, and `shared-change`. For Buildbarn mode, use an
explicit `remote_instance_name` as the remote cache namespace and keep the live
worker allocation/hardware in the uploaded evidence. The Kubernetes cluster was
left scaled down; restoring remote execution capacity is a separate cost-bearing
operation and is not performed by these workflows.

### Corrected Jenkins-native scope

The actual requested suite is the 20-job Jenkins deployment E2E workflow, but
executed directly in GitHub Actions rather than by triggering Jenkins. New
scaffolding for that path lives in:

- `.github/workflows/ci-comparison-jenkins-native.yml`
- `tools/ci-comparison/jenkins-native-runner.py`

The native runner enumerates all 20 Jenkins workflow jobs. It currently translates
the nine local kind jobs plus the Docker Compose job to repository-local commands.
Live AWS deployment jobs fail closed until their Jenkins shared-library stages
are translated one-for-one and a GitHub Actions AWS role is supplied. Do not use
the earlier Gradle/JVM workflow results as the requested Jenkins-suite comparison.

## Resolve the suite before claiming a comparison

The original linked GitHub job (`110209992296`, run `36812349693`) is
`full-es68-e2e-aws-test`. It triggers Jenkins infrastructure deployment and E2E
execution. This differs from the Gradle `allTests` suite in `CI.yml`.

The checked-in Jenkins workflow defines 20 deployment jobs: nine local kind
jobs, one Docker Compose job, and ten AWS jobs. Some AWS jobs require labels or
run only on main. `jenkins-inventory.json` preserves every job, its trigger job
expression, timeout, and available local source/target/scenario selection.
The inventory counts jobs, not individual test cases.

The fork's existing workflow intentionally skips Jenkins outside the upstream
repository. On 2026-10-04, a read-only query returned no repository secrets on
`zjpiazza/opensearch-migrations`. This does not rule out environment or organization
secrets, but no usable Jenkins/AWS configuration has been established for this
comparison. Do not implicitly select local AWS credentials or an account.

Existing measured experiments cover a different scope:

- The remote 131-shard experiment covers 756 cases in 16 long Gradle classes.
- The local WireMock experiment covers 28 scenarios in `PipelineEndToEndTest`.
- Neither demonstrates a fully mocked replacement for the 20 Jenkins jobs.

A full Jenkins comparison therefore needs either the real deployment account and
execution configuration, or implementation and coverage validation of a broader
mocked suite. A Gradle comparison can proceed independently if that is the
intended scope. Results must always use the exact selected suite name.

## Fair comparison requirements

Both branches must share product sources, assertions, source/target versions,
fixture identities, timeout/retry policy, test-clock optimizations, and any
WireMock substitutions. Keep a real-engine coverage lane separate from mocked
contract tests. Do not give only the Bazel branch the fixture or mock improvements.

Use the same GitHub runner label, architecture, concurrency cap, JVM settings,
and resource limits. Record actual CPU/memory/disk characteristics on every job.
The Buildbarn cluster remains scaled down; no capacity restoration is implied
by creating these branches. Remote execution would be a separately identified
comparison against equivalent allocated compute.

Measure these cases separately:

| Case | What it establishes |
| --- | --- |
| Cold setup and forced execution | End-to-end cost including downloads, builds, fixtures and actual tests |
| Warm preparation, forced execution | Scheduling/execution improvements without test-result reuse |
| Unchanged source on a fresh runner | Cache transfer/restore plus reuse of valid previous results |
| Leaf implementation change | Recompilation and test invalidation for a narrow dependency change |
| Shared-library implementation change | Invalidation for a broad dependency change |

Use isolated cache namespaces with no unintended restore fallback. Give both
backends the same opportunity to save and restore dependency/build caches.
Warm and changed-source jobs must restore the same successful seed and must
not run when that seed fails. Cache hits are reused results, not new executions.
A stale or missing report must never pass case-coverage validation.

Upload test-case inventories, JUnit reports, engine/fixture identities, toolchain
versions, source diffs for invalidation trials, Gradle task outcomes or Bazel
build events, and machine-readable timing records. Summaries must show complete
coverage, setup/build/export/execution/cache-transfer time, total job/wall time,
runner minutes, cache hits, failures, skipped and missing cases. Compare ratios
only for successful runs with matching case identities and coverage mode.

## Tradeoffs the experiment must expose

| Area | Without Bazel | With the existing Bazel prototype |
| --- | --- | --- |
| Build ownership | Existing Gradle, npm and deployment tools | Gradle still compiles/prepares; Bazel schedules exported tests |
| Cached test granularity | Normally Gradle Test-task inputs; finer granularity needs task/configuration work | Exported test class/shard inputs; actual invalidation must be measured |
| Live infrastructure tests | Re-execute; external state is not declared input | Also re-execute; wrapping live cloud APIs does not make results safely cacheable |
| Hermetic replay | Can use Gradle build caching and GitHub cache transport | Can use Bazel action/test caching and declared fixture inputs |
| Distributed execution | GitHub matrices or an additional execution service | A standard remote-execution protocol with a service such as Buildbarn |
| Maintenance | Existing build plus matrix/shard/cache configuration | Bazel definitions, runtime export bridge, dependency correctness, and any remote service |

The prototype is not a native Bazel rebuild of the repository. Its Gradle
preparation, runtime packaging, dependency downloads and cache-transfer costs
must remain visible; an execution-only figure is not the complete CI duration.
