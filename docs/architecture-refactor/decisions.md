# Decision register

Status meanings: **accepted direction** is agreed for the experiment;
**proposed** needs evaluation; **demonstrated** describes a measured capability,
not an adoption decision. Acceptance here is not upstream project approval.

## D-001 — Organize by product responsibility

- Status: accepted direction, 2026-10-01.
- Decision: use the top-level layout in [the design record](README.md).
- Reason: make applications, reusable capabilities, deployment, testing, and
  tooling discoverable; align ownership and dependency boundaries.
- Alternatives: rename existing folders only; group everything by language;
  split immediately into multiple repositories.
- Tradeoffs: paths, build labels, CI consumers, docs, and packaging need migration.
- Evidence: E-004 audit and E-005 physical layout implementation. Dependency
  boundary cleanup and performance impact are not established.
- RFC candidate: repository organization and component boundaries.

## D-002 — Separate the migration engine from orchestration and providers

- Status: proposed.
- Proposal: retain Java data-processing capabilities with narrow model,
  search-client, snapshot, storage, transform, and telemetry interfaces.
- Rule to evaluate: pure domain types do not import Lucene, cloud SDKs, or
  Kubernetes APIs; applications assemble adapters; libraries do not depend on
  application entry points. Keep version-specific snapshot dependencies scoped.
- Alternatives: retain existing Gradle module boundaries; only add focused Bazel
  source subsets as in the pilot.
- Required evidence: normal production modules support focused testing, existing
  functionality remains covered, and fewer unrelated targets execute.
- Rollback: retain existing application entry points during extraction; revert
  individual module changes without changing external migration contracts.
- RFC candidate: dependency/module boundary cleanup, independently of Bazel.

## D-003 — Consolidate lifecycle behavior into a Kubernetes operator

- Status: proposed; the user favors exploring an operator.
- Proposal: the operator owns migration dependencies, approvals, retries, status,
  cancellation, and cleanup; workers perform migration work; the CLI is a client.
- Existing resources and lifecycle invariants are inputs to the design, not
  permission to change behavior. Preserve cancellation, approval, recovery,
  identity, and deletion-order semantics explicitly.
- Alternatives: keep Argo and improve its typed orchestration libraries; extract
  reusable lifecycle logic while retaining Argo as the executor.
- Tradeoffs: controller operations, upgrades, API evolution, and state migration;
  a replacement must retire corresponding workflow and shell paths to simplify
  the system. Do not give Argo and a new controller concurrent ownership of the
  same live resources during transition.
- Required evidence: one complete representative migration, failure/restart and
  cleanup tests, operating model, and a behavior-by-behavior compatibility map.
- Testing: pure reconciliation decisions, Kubernetes API integration, and real
  cluster execution have different coverage. Envtest has no kubelet or standard
  controller-manager; it cannot prove pods run or garbage collection completes.
- References: [operator pattern](https://kubernetes.io/docs/concepts/extend-kubernetes/operator/),
  [envtest](https://book.kubebuilder.io/reference/envtest.html).
- RFC candidate: operator architecture, separate from source-tree cleanup.

## D-004 — Reduce implementation languages and deployment tools

- Status: proposed, not a mandate to rewrite all working code.
- Preferred hypothesis: Java for migration workers; Go for operator and unified
  CLI; Terraform for infrastructure; Helm for application installation; shell
  for small launchers. Preserve supported user transformation interfaces.
- Alternatives: Java control plane to avoid introducing Go; retain existing CLI
  and orchestration languages while improving module boundaries.
- Tradeoffs: Go is a new language in this design and only reduces the stack if
  corresponding Python, TypeScript, Rust, and shell paths can be retired.
  Existing Python tests and optional JS/Python transforms have separate value.
- Open constraint: AWS Solutions/CDK/CloudFormation support may require a distinct
  distribution package; it cannot be assumed removable.
- Required evidence: toolchain inventory before/after, replacement effort,
  compatibility, packaging size, and ownership/maintenance cost.

## D-005 — Evaluate Bazel independently of architectural cleanup

- Status: demonstrated for a focused Java/WireMock slice; adoption undecided.
- Hypothesis: explicit inputs and smaller targets allow selective work and
  reproducible cached results. Persistent workers can reduce repeated compiler
  startup; they do not eliminate external-service execution time.
- Alternatives: improve Gradle module boundaries, configuration, caching, and
  daemons; use existing language-native build tools behind consistent commands.
- Evidence: E-001 and E-003. Warm VM jobs retain a Bazel server and Javac worker.
- Limits: the pilot uses selected production sources, a narrower graph than
  Gradle; cross-job improvements include disk caches and analysis reuse.
- Required evidence: equivalent source graphs, affected-test selection,
  maintenance overhead, cold/warm/changed-input measurements, correctness.
- RFC candidate: build tooling only if benefits exceed added maintenance.

## D-006 — Layer tests and preserve a coverage map

- Status: proposed broader strategy; WireMock sink pilot demonstrated.
- Proposal: fast unit/contract/controller feedback; representative local real
  execution; broader compatibility/cloud testing on appropriate triggers.
- Alternatives: current broad E2E execution on PR updates; narrower affected E2E
  selection without introducing more mocks.
- Constraint: recorded API responses validate client behavior, not the real
  service's effects. Do not claim all E2E coverage from a replay suite.
- Evidence: E-002 and E-003 cover nine sink contract cases only.
- Required evidence: scenario/assertion coverage mapping, fixture provenance and
  refresh policy, failure cases, reproducibility, and feedback time.
- RFC candidate: test layering and CI triggers, independently of Bazel.

## D-007 — Keep decisions and evidence versioned with implementation

- Status: accepted direction, 2026-10-01.
- Decision: update this record at meaningful checkpoints and link each proposed
  RFC claim to its experiment and implementation.
- Preserve limitations, failed attempts, and superseded conclusions. Keep a
  compact evidence archive independent of temporary CI artifacts.
- This is a working convention, not an additional approval gate.

## D-008 — Relocate source before changing public identities or behavior

- Status: implemented experiment, 2026-10-01; user authorized implementation and PR.
- Decision: map the current components into the accepted responsibility groups,
  with explicit Gradle project directories and updated CI, deployment, and source
  paths. Keep public Gradle IDs, package names, artifact identities, and commands.
- Alternative: change module identities, dependencies, languages, orchestration,
  and filesystem locations together. That makes failures and RFC claims harder
  to attribute to individual changes.
- Transitional exceptions: `apps/orchestration`, both current interfaces, and
  existing dependency edges remain. The root `buildSrc` shim and Jenkins `vars`
  are framework conventions. `api` documents ownership without duplicating schemas.
- Evidence: E-005 and `layout-map.json`; existing tests compile/run at new paths.
- Compatibility cost: source-path consumers must migrate. External Jenkins job
  script paths and Cloud Build config paths cannot be updated by a repository PR.
- Rollback: revert the source-layout commit, then restore external path settings.
  The preceding documentation checkpoint remains independently reviewable.
- RFC claim supported: the repository can use responsibility-based source roots
  while preserving current build/module identities. No test speedup or dependency
  simplification is attributed to file relocation.
