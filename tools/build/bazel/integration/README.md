# Kubernetes integration benchmark

Runs the existing `Test0001SingleDocumentBackfill`, including real Elasticsearch,
OpenSearch, LocalStack, Argo, the migration console and snapshot migration worker.
Each execution creates a fresh kind cluster and deletes it in `finally`.
It does not touch the default kubeconfig or existing clusters.
The benchmark uses native nftables kube-proxy mode: the host's rootless Docker
failed to apply the default iptables-nft ruleset (`Message too long`). This
cluster-local setting differs from Jenkins; no host networking settings change.
Pod data and local PVCs use fresh directories under `/tmp` (a separate tmpfs
on this host). Otherwise ES8 rejects shard allocation because the workspace
filesystem exceeds its disk watermark. This is not a storage-throughput benchmark.
Cleanup removes these directories through the same rootless Docker user namespace.
Kubelet's root stays on the normal disk so its advertised node capacity can
accommodate the unchanged 200 GiB RFS ephemeral-storage request. A preflight
check rejects insufficient advertised capacity before installing the charts.

The normal target is `//tests/automation:backfill_integration_test`.
It has the `external` tag because Helm currently downloads charts and container
images during installation. It deliberately does not reuse test results.

`//tests/automation:backfill_cache_experiment` is a **same-session cache
experiment**, not a CI-ready hermetic test. Both targets require Docker and local
kind, Helm and kubectl tools; remote execution and remote result caching are disabled.

## Preparation

From the repository root, install kind v0.31.0 at
`build/bazel-integration/tools/kind`, verifying the official release checksum.
The node image is pinned to the digest used in Jenkins in `prepare.py`.
Create dedicated benchmark resources (these names must be unused):

```sh
docker network create migrations-bazel-benchmark
docker run -d --name migrations-bazel-registry \
  --network migrations-bazel-benchmark --network-alias docker-registry \
  -p 127.0.0.1:5017:5000 \
  -v migrations-bazel-registry-data:/var/lib/registry registry:2
docker buildx create --name migrations-bazel-benchmark \
  --driver docker-container --driver-opt network=migrations-bazel-benchmark \
  --config buildImages/buildkitd.toml
docker buildx inspect migrations-bazel-benchmark --bootstrap
./gradlew :buildImages:buildImagesToRegistry_amd64 \
  :buildKit_customElasticsearch81914_amd64 \
  -Pbuilder=migrations-bazel-benchmark -PregistryEndpoint=localhost:5017 \
  -x test --max-workers=4 --console=plain
python3 tools/build/bazel/integration/prepare.py --record-build
```

Do not edit product sources while building or recording the build fingerprint.
Run `prepare.py` before every subsequent invocation; it refuses changes to tracked
sources until images are rebuilt. Generated `runtime.json` includes source, image
manifest, tool and host fingerprints. It is machine-specific and ignored by Git.

## Measurement

```sh
python3 tools/build/bazel/integration/benchmark.py
```

This measures an ES8 execution, an identical invocation, and an ES7 execution after
changing the declared scenario input. The scenario file is restored in `finally`.
A unique test environment value prevents reuse across benchmark sessions. Raw
logs, wall times and Bazel build events go to `build/bazel-integration/<timestamp>`;
the test emits reports, cluster logs and lifecycle timing as undeclared outputs.
Do not compare the two Elasticsearch versions as an execution-speed benchmark.

For a forced execution use the normal target:

```sh
python3 tools/build/bazel/integration/prepare.py
./bazelw test //tests/automation:backfill_integration_test
```

## What the experiment can establish

An unchanged result can avoid the entire cluster lifecycle and migration. A
changed scenario must execute again. This does not accelerate migration execution
itself, estimate cache hit rates across commits, or measure network remote-cache
performance. Fresh-node image pulls and host contention also affect execution time.
The harness skips Helm teardown and deletes the whole private cluster instead;
its wall time is therefore not identical to Jenkins' lifecycle.

The 2026-10-01 run measured **707.424 seconds** for the ES8 target's full
lifecycle and **0.107 seconds** for an identical cached invocation. Bazel's
build-event report confirms zero and one cached targets respectively. These
are single observations with dependencies already downloaded and images already
built. Fingerprint preparation and archival of output logs are outside those
wall times. The Python migration scenario within the first run took 494.01
seconds. This demonstrates avoiding execution, not accelerating execution, and
does not estimate a PR-wide cache hit rate or a production remote-cache latency.
Raw evidence is under `build/bazel-integration/20261001-150919`.

Before enabling CI result caching:

* Build OCI images as declared dependencies; the current Gradle/fingerprint bridge
  requires preparation and is not automatic dependency tracking.
* Vendor/digest-pin runtime Helm charts and all third-party images. Current chart
  versions and image tags are fetched at execution time and can change independently.
* Narrow scenario dependencies. The migration-console image currently bundles the
  integration harness, so changes can invalidate many scenarios together. The
  conservative tracked-source fingerprint here intentionally over-invalidates.
* Measure realistic changed commits and keep scheduled forced reruns to expose flakes.

## Cleanup

After all tests stop, remove only the resources created above:

```sh
docker buildx rm migrations-bazel-benchmark
docker rm -f migrations-bazel-registry
docker volume rm migrations-bazel-registry-data
docker network rm migrations-bazel-benchmark
```

An interrupted process may leave a cluster named `ma-bazel-<random suffix>`.
Inspect it before deleting that exact cluster with kind. Never delete other local
clusters or prune the shared Docker daemon.

## Proposed PR test architecture

The intended PR gate is a suite of deterministic component integrations with
fake external services, cached by Bazel. Real Kubernetes, Argo, search clusters
and cloud deployments move to scheduled and explicitly triggered candidate
validation. The experiment above measures reuse of an existing expensive test;
it does not implement that full replacement suite or change existing CI triggers.

### GitHub experiment on the fork

`.github/workflows/bazel-experiment.yml` uses commit-pinned
`bazel-contrib/setup-bazel` 0.19.0 and runs on PRs in
`zjpiazza/opensearch-migrations`. The initial GitHub measurement covered 22
Bazel targets: 121 Java cases, 43 Python mock cases, and four approval component
cases. The suite now has 24 targets, adding 23 approval assertion fault-injection
cases and 12 workflow-output component cases. The original measurements do not
include those additions.

The new `//tools/build/bazel/components:approval_integration_test` exercises
the production approval command, gate discovery/classification and Kubernetes
Python SDK against an HTTP fake. It checks sequential approval, idempotency,
workflow isolation, compressed Argo status and API rejection. Only Kubernetes
configuration and the API server are replaced. Argo status transitions are
explicit test inputs; no fake controller claims to execute a real migration.
This is a control-plane pilot, not coverage equivalence with scenario 0003.

The approval component now uses the same five gate names as the real scenario.
`integ_test/approval_contract.py` holds the prerequisite assertions used by both
the real E2E test and Bazel tests: proxy startup state, retained metadata output,
and backfill completion/shard counts. The fault-injection target checks that
these assertions reject invalid observations; it does not produce a migration.

`//tools/build/bazel/components:workflow_output_integration_test` runs the real
`workflow show` command, Kubernetes SDK and artifact reader against HTTP fakes
and temporary mounted files. It checks both metadata stages, exact returned
artifact content, denied/missing objects, empty artifacts and missing output
references. This caught an E2E assertion gap: a missing reference can produce a
successful CLI exit and a nonempty diagnostic. The shared prerequisite now also
requires the retained artifact reference in the SnapshotMigration resource.

Full mocked E2E replacement remains unimplemented. In particular, these tests
do not execute Argo's generated workflows, produce metadata/backfill results,
run capture/replay, verify search-engine behavior, or cover the full 26-scenario
catalog. The existing E2E triggers remain necessary. Removing local engines
requires production orchestration and migration boundaries that can run in
process; retaining them preserves their execution behavior but retains much of
the existing cold-run cost. Neither choice can be measured by these component
timings alone.

The first CI job starts with a unique disk-cache namespace for each workflow
run/attempt. It measures initial execution, forced test execution, an identical
rerun and changed-fixture invalidation. After its cache upload completes, a
second job on a fresh runner restores that cache and requires all targets to
be cache hits. Repository/Bazelisk download caches can already be warm. The
per-run disk-cache namespace is for controlled measurement; a production gate
would use a stable shared cache namespace and measure changes across commits.

Step summaries contain wall times and cache counts, with raw logs and Bazel
build events uploaded as artifacts. Bazel timings exclude checkout, action
setup, cache transfer and artifact upload; compare the GitHub job durations too.
No credentials or cloud accounts are required. Cache saving is allowed only for
same-repository PRs or manual runs; external PRs cannot populate the shared cache.
The full kind benchmark stays local because its current resource/host assumptions
do not fit an unchanged run on a standard GitHub-hosted runner.

Keep production parsing, transformation, request serialization, coordination
and error handling in the PR tests. Replace dependencies at their interfaces,
using real snapshot fixtures, stateful fakes, scripted protocol responses and
an injected clock. Avoid a test that mocks the migration operation itself and
merely checks that the caller receives success.

| Existing scenario | Proposed cacheable PR coverage | Scheduled/candidate coverage |
| --- | --- | --- |
| 0001 single-document backfill | Versioned snapshot bytes through real reader and pipeline into a recording sink; index names containing `__`; failed-document stream remains disabled without a bucket | Actual snapshot creation, search indexing, deployment defaults and full workflow |
| 0002 coordinator and failed-document stream | Coordinator lease/state transitions; bulk partial failure response; terminal failure persisted through a fake object store and read by the console; `CompletedWithErrors` | Search-backed concurrency, real mapping rejection and storage/authentication |
| 0003 approval gates | Production approval commands against stateful Kubernetes objects; prerequisite checks, gate ordering, repeated approval and reset; virtual time | Argo actually suspends/resumes the correct tasks and enforces generated resource contracts |
| 0020 GCS snapshot | Production repository adapter against recorded GCS responses/fixture blobs, including pagination, missing objects and retries | Actual GCS credentials, permissions, endpoints and networking |
| 0035 CDC client authentication | Configuration propagation and real TLS client/server behavior with fixed test certificates and a controlled clock where needed | Deployed secret injection, proxy wiring and cloud networking |
| 0040 CDC backfill/replay | Real capture decoding, transformation and replay against deterministic transport fixtures; ordering, duplicates, retries and backpressure | Real broker behavior, concurrent workloads and complete workflow |

These are proposed coverage slices, not claims of equivalent coverage today.
Each migrated scenario needs a checklist of its assertions and known regressions.
In particular, a fake search response does not verify server mapping semantics,
and a fake Kubernetes API does not execute Argo controllers or admission policies.
Keep those checks in the real suite, and use it to verify the fake contracts.

Useful foundations already exist:

* `RfsPipeline/docs/testing-strategy.md` separates source and sink compatibility
  into N+M tests. Extend that boundary with pinned snapshot artifacts and recording
  sinks; retain real adapter compatibility runs on the schedule.
* Console workflow tests already use mocked Kubernetes clients. Compose the
  production command/service layers over shared stateful fakes for scenario tests.
* Terraform AWS tests already use `mock_provider`. Keep infrastructure validation
  in the PR gate without creating cloud resources.
* Argo builder and generated-CRD tests against K3s provide real contract checks
  for the scheduled suite. Do not reproduce Argo's execution engine in a fake.

### Bazel requirements

Declare production libraries, fixtures, schemas, fake implementations and tool
versions as dependencies of separate scenario targets. Do not depend on the
entire migration-console image or repository for every test. Store immutable
snapshot fixtures with source-version/image provenance and checksums; the
existing warm Gradle fixture directory is not a declared Bazel input.

Tests must use private temporary state, fixed seeds, controlled clocks and no
ambient credentials or network dependencies. Small local protocol servers can
be used where serialization or TLS matters; their implementation and inputs
must also be declared. Mocks alone do not make a test cacheable.

Validate cache behavior with cold execution, identical rerun, relevant source
change, fixture change and unrelated source change. The first two changes must
invalidate dependent tests; the unrelated change should preserve their hits.
Measure checkout/dependency/cache-transfer overhead as well as Bazel execution.
Only trusted CI should publish shared cache results; PR jobs need an appropriate
read-only cache policy for untrusted contributions.

### Trigger and release changes

| Trigger | Required work |
| --- | --- |
| PR update and merge queue | Unit tests, deterministic component integrations, schema/configuration and infrastructure validation |
| Scheduled main run | Real local compatibility matrix plus cloud-provider smoke tests; force fresh test execution |
| Explicit candidate validation | Full real provider, migration, upgrade and recovery coverage against immutable staged artifacts |
| Promotion | Require successful candidate validation; promote exactly the tested image digests and artifact checksums |

The current `jenkins_tests.yml` launches the real matrix on PR updates. Its
aggregate accepts skipped jobs, so replacing triggers also requires a required
check that explicitly verifies the new PR suite completed successfully.
Other workflows, including `CI.yml`, launch real cluster tests too; inventory
those before claiming that PRs no longer provision clusters.

Release gating must precede publication: the inspected release Jenkinsfile
reacts to a published GitHub prerelease and publishes Maven artifacts and public
images, including `latest`. Publishing that prerelease is already a promotion
boundary. Stage candidates privately, test them, then publish/promote.

Roll out one scenario first, compare its assertions with the real scenario,
and run both during the evaluation period. Switch the required PR gate only
after the replacement catches the relevant known regressions. A useful initial
performance target is under 10 minutes for the complete PR gate and under one
minute for an unchanged warm-cache rerun; neither target is measured or promised
by this benchmark. Track cold/changed/warm p50 and p95, cache hit rate, flakes
and regressions first discovered by scheduled validation.
