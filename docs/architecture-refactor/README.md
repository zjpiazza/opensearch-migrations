# Architecture refactor: design and evidence record

Started: 2026-10-01. Status: exploratory fork work, not an upstream RFC.

`experimental` is the shared integration branch for this work. The original PRs
and Buildbarn branch are consolidated here with their histories preserved. See
[the consolidation record](experimental-branch.md) for included commits, conflict
resolutions, validation, and the workflow for future RFCs.

The objective is to build and measure an ideal version of OpenSearch Migrations,
then extract independently useful proposals for upstream review. Repository
structure, component boundaries, orchestration, build tooling, and test strategy
are separate decisions. A successful experiment does not automatically justify
adopting its entire implementation.

The user accepted the proposed top-level layout on 2026-10-01 and requested
documentation at every step so recommendations can be traced back to evidence.
The operator implementation, language choices, Bazel adoption, and retirement of
existing deployment paths remain proposals.

- [Decisions](decisions.md): accepted directions, alternatives, and open choices.
- [Journal](journal.md): dated checkpoints, evidence, limitations, and next steps.
- [Evidence](evidence/): compact benchmark records retained beyond CI artifact expiry.
- [Buildbarn experiment](../../deploy/ci/buildbarn/README.md): dedicated Kubernetes
  execution pool, placement, reproduction, and E-006 validation.

## Implemented checkpoint: source layout

E-005 implements the physical layout on `experiment/architecture-refactor`:
2,926 files moved, with all 3,083 baseline tracked files preserved. Applications,
libraries, deployment assets, shared tests, and tooling now have separate roots.
[The exact move map](layout-map.json) records all 55 directory/file mappings and
56 Gradle project locations. [Validation evidence](evidence/layout-validation.json)
and [the journal](journal.md#e-005--implement-the-source-layout) record the checks.

This is a transitional layout. `apps/orchestration` keeps the existing TypeScript
workspace; `apps/console` and `apps/cli` keep both current interfaces. `api/` points
to existing contracts. The operator, clean library boundaries, and language
consolidation still need implementation and evidence. `libs/migration-engine`
and `libs/runtime` retain existing responsibilities and dependencies.

Gradle task IDs, Java packages, published artifact names, and container identities
remain stable. For example, `./gradlew :RFS:wiremockTest` now builds source in
`libs/migration-engine`. `buildSrc/`, `gradle/`, `vars/`, and `.github/` retain
locations required by their tools. External Jenkins job script paths and Cloud
Build trigger configuration require the changes listed in [tools/README.md](../../tools/README.md).

## Documentation convention

For every meaningful implementation step, update this record in the same change:

1. Identify the decision and hypothesis being tested.
2. Describe the behavior and dependency graph before and after the change.
3. Link the implementation commit or PR, reproduction command, and environment.
4. Record checks, measurements, failures, coverage gaps, and confounding factors.
5. State the conclusion, compatibility cost, rollback path, and next question.

Use stable IDs such as D-003 and E-004 to connect decisions and experiments.
Distinguish measured results, observations, hypotheses, and proposed targets.
Append checkpoints when conclusions change; retain the earlier result and explain
why it was superseded. Record unsuccessful experiments and abandoned approaches
when they inform a decision. Do not record secrets or raw build-event environment
dumps. Preserve compact results here because CI artifacts expire.

This record is the starting point when resuming work. Documentation checkpoints
do not introduce a separate permission or approval requirement.

## Baseline

The top-level audit examined tracked files at
`1cdb85a222faa77a1b81862caed392c9af4aff8f` on
`experiment/wiremock-record-replay`, not a claim about a newer upstream main.
Local build outputs, worktrees, and unrelated untracked files were excluded.

- 38 tracked non-hidden top-level directories.
- 100 tracked `.sh` files distributed across 15 locations, counting root scripts
  as one location.
- Applications, libraries, fixtures, infrastructure, and CI code appear as peers.
- Java, TypeScript/JavaScript, Python, Rust, Groovy, and Bash all participate in
  development or execution; file counts alone do not establish duplication.

Observed boundaries worth changing:

| Observation | Baseline source | Consequence to evaluate |
| --- | --- | --- |
| HTTP code depends on shared code that compiles shaded Lucene artifacts | `RfsHttp/build.gradle`, `RfsCommon/build.gradle` | Narrow HTTP testing inherits snapshot build dependencies |
| Helm chart packaging requires CDK synthesis of AWS templates | `deployment/k8s/build.gradle` | Provider-neutral packaging brings in AWS distribution tooling |
| Status, recovery, and cleanup behavior lives in shell | `orchestrationSpecs/packages/migration-workflow-templates/resources/scripts/rfsMonitorCronJob.sh` | Lifecycle logic requires several runtimes and deployment layers to exercise |
| Resource contracts have multiple representations | `docs/migrationResourceContractCleanupPlan.md` | Schemas, manifests, resolved resources, and checksums must agree |
| Test execution normally depends on Javadoc | `build.gradle` | Documentation work is coupled to test feedback; the WireMock pilot has a narrow exception |
| Build configuration inspects the current Kubernetes context | `buildSrc/src/main/groovy/org/opensearch/migrations/image/RegistryImageBuildUtils.groovy` | Environment dependence and configuration-cache compatibility; the command's runtime has not been shown to be a bottleneck |

Reproduce the inventory with `git ls-files` at the baseline commit. Counts include
tests and tracked generated sources. Do not use filesystem directory counts,
which include local experimental artifacts.

## Accepted target layout

```text
api/                         Versioned migration and worker contracts
apps/
  operator/                  Migration lifecycle management
  cli/                       Submit configuration and display progress
  backfill/                  Snapshot-to-target executable
  metadata/                  Metadata migration executable
  snapshot/                  Snapshot creation executable
  capture-proxy/             Live traffic capture
  replayer/                  Traffic replay
  dashboards/                Dashboard migration/sanitization
libs/
  migration-model/           Domain types without infrastructure dependencies
  migration-pipeline/        Processing stages and their interfaces
  search-client/             HTTP transport, bulk serialization, responses
  snapshot/                  Snapshot formats and Lucene compatibility
  storage/                   Filesystem, S3, GCS implementations
  transforms/                Transformation contracts and implementations
  traffic/                   Capture formats, buffering, and replay support
  telemetry/                 Tracing and metrics
deploy/
  charts/                    Application installation
  terraform/aws/             AWS infrastructure
  terraform/gcp/             GCP infrastructure
  local/                     Local development environment
tests/
  fixtures/                  Shared fixtures, including recorded API exchanges
  scenarios/                 Cross-component behavior specifications
  integration/               Local integration harnesses
  e2e/                       Full deployment/provider scenarios
  performance/               Benchmarks and load generators
tools/
  build/                     Build extensions and toolchain support
  ci/                        CI adapters and runner setup
  release/                   Distribution assembly and publishing
  dev/                       Developer utilities
examples/
docs/
.github/
```

Build manifests, README, legal files, and required tool configuration remain at
the root. Component unit and contract tests stay beside their owning code;
`tests/` holds shared fixtures and cross-component tests. Applications own their
container packaging. Generated artifacts have an explicit source and generator.

Initial responsibility mapping (splits require code review; this is not a bulk
rename prescription):

| Current location | Destination or treatment |
| --- | --- |
| `DocumentsFromSnapshotMigration`, `MetadataMigration`, `CreateSnapshot` | Corresponding `apps/` entries |
| `RFS`, `RfsCommon`, `RfsHttp`, `RfsPipeline` | Split by responsibility among migration model, pipeline, search client, and snapshot libraries |
| `SearchSnapshotExtractor`, `SnapshotReader`, `SnapshotReaderGcs`, `SolrReader` | Snapshot/format and storage adapters; isolate Lucene-version dependencies |
| `TrafficCapture` | Capture/replay applications, reusable traffic libraries, and test/deployment tooling separately |
| `coreUtilities`, `awsUtilities`, `s3Common`, `libraries` | Assign specific capability owners rather than recreating a generic utilities directory |
| `transformation` | `libs/transforms`, preserving supported extension contracts |
| `migrationConsole`, Rust CLI under `deployment/k8s/aws/cli` | Evaluate consolidated user interface; distinguish provisioning from migration commands |
| `orchestrationSpecs` | Contracts in `api/`; lifecycle behavior in proposed operator; generated installation assets in `deploy/` |
| `deployment`, `buildImages`, `buildSrc`, `gradle` | Separate provisioning, packaging, build extensions, and release operations |
| Fixture projects, `libraries/testAutomation`, `migrationConsole/lib/integ_test`, `test` | Component tests or shared `tests/` infrastructure according to scope |
| Custom search images, `DataGenerator`, `solrMigrationDevSandbox` | Test infrastructure, performance tooling, or examples |
| `DashboardsMigration`, `dashboardsSanitizer`, `schema-viewer` | Separate documentation, executable tooling, and any retained UI |
| `jenkins`, `vars`, `.github` | Thin CI adapters around shared targets; retain required framework layout until migration |
| `dev-tools`, hooks, root helper scripts | `tools/dev` with only required root entry points |

Jenkins currently requires its shared-library `vars/` directory at repository
root (see `vars/README.md`). It cannot simply be moved without changing that
integration. Published artifact names and user-facing commands are also distinct
from source directory names; inventory consumers before changing them.

## First proposed implementation slice

Take one snapshot-to-target migration through the proposed architecture:

1. Extract clean model, search-client, snapshot, and storage boundaries.
2. Give the existing WireMock cases a normal production-module test target.
3. Prototype one operator-managed lifecycle with a thin client.
4. Run equivalent local real-engine and controlled-response scenarios.
5. Compare dependency work, feedback latency, correctness, and maintenance cost.

Preserve a scenario-to-test coverage map. Sharing scenario names or fixtures does
not prove that mocks verify actual indexing, Lucene compatibility, Kubernetes
execution, or cloud behavior. Record which assertions require each test layer.

## Turning findings into RFCs

Each candidate RFC should identify a bounded problem, alternatives, implementation
evidence, reproducible measurements, correctness coverage, compatibility and
operational costs, rollout/rollback, and unresolved questions. Link its claims
back to decision and experiment IDs. Separate module cleanup, test strategy,
operator adoption, and build-system adoption when their evidence supports
independent decisions.

No full-suite performance target is established yet. Microbenchmark speedups and
the nine-test WireMock pilot must not be presented as full E2E speedups.
