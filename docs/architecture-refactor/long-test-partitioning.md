# Splitting the long integration tests

Status: experiment in progress. The uncached class-level run is still active;
these are completed-target observations, not the final ranking or a measured
sharding speedup. Per the user's narrowed scope, subsequent experiments select
only long integration classes. Hardware benchmarks, npm upload failures and
shorter tests are deferred.

## Completed observations

All rows below executed without Bazel test-result reuse. Precompiled runtimes,
worker input blobs and some Docker images were already available. Time is the
reported test-action duration, excluding queue wait. Cases include their own
container startup and teardown.

| Module / class | Class time | Cases | Longest case | Proposed boundary |
| --- | ---: | ---: | ---: | --- |
| RFS / WorkCoordinatorTest | 30m19s | 70 | 1m02s | Target version, retaining sequential methods per process |
| Backfill / SnapshotConfigurationTest | 26m22s | 30 | 1m45s | Independent source/configuration cases |
| Metadata / SnapshotConfigurationTest | 25m26s | 30 | 1m56s | Independent source/configuration cases |
| Backfill / PipelineEndToEndTest | 19m47s | 28 | 2m16s | Version pair, keeping its four methods together |
| Backfill / SolrSnapshotToOpenSearchTest | 16m22s | 22 | 1m11s | Independent method/version cases |
| SolrReader / SolrToOpenSearchEndToEndTest | 15m57s | 31 | 1m04s | Independent method/version cases |
| Solr transformations / TransformationShimE2ETest | 15m34s | 2 dynamic groups | 7m50s | Requires fixture ownership refactor first |
| Backfill / RoutingShardColocationTest | 15m22s | 15 | 2m13s | Independent scenario cases |
| Backfill / EndToEndCompressionTest | 15m12s | 10 | 3m49s | Independent version/codec cases |
| Backfill / DeltaSnapshotRestoreTest | 14m44s | 11 | 3m04s | Version cases; keep each snapshot sequence intact |
| Metadata / CustomTransformationTest | 13m23s | 11 | 1m46s | Independent method/version cases |
| SnapshotReader / LuceneSnapshotSourceEndToEndTest | 13m05s | 88 | 1m24s | Source version, keeping all eight methods together |

Backfill and metadata `EndToEndTest`, `NoStoredSourceMigrationTest`,
`SnapshotReaderEndToEndTest`, and `LeaseExpirationTest`
were still running during this checkpoint. Do not rank unfinished actions using
their elapsed duration as if it were their final duration. LeaseExpirationTest
was observed restarting on a different worker after its previous Docker sidecar
was OOMKilled; final wall time must distinguish work from infrastructure retries.

## Why these boundaries

[PipelineEndToEndTest](../../apps/backfill/src/test/java/org/opensearch/migrations/bulkload/PipelineEndToEndTest.java)
has four methods over seven migration pairs. Its source snapshot cache is keyed
by source version and scenario. Keeping the four methods for a pair together
preserves reuse within that pair, although three pairs share an Elasticsearch
7.10 source and will regenerate some fixtures across actions. Splitting every
method independently would discard substantially more reuse. The slowest case
was 136 seconds; the 19.8-minute class duration is not one indivisible operation.

[LuceneSnapshotSourceEndToEndTest](../../libs/snapshot/search/src/test/java/org/opensearch/migrations/bulkload/pipeline/adapter/LuceneSnapshotSourceEndToEndTest.java)
is the strongest example of why method-only splitting can be counterproductive.
Its initial ordinary snapshot construction accounts for about 527 seconds and
its delta snapshots for about 250 seconds across versions. Six other method
groups together take only a few seconds after fixture reuse. Run one source
version's checks together, with a private filesystem cache per action. Do not
share the mutable fixture cache directory across workers.

The two `SnapshotConfigurationTest` classes each create and close their source
and target clusters inside each parameterized invocation. Partitioning those
invocations adds process/input preparation, but does not inherently multiply
their existing per-case container starts. Preserve both EVALUATE and MIGRATE
within each metadata scenario.

[WorkCoordinatorTest](../../libs/migration-engine/src/test/java/org/opensearch/migrations/bulkload/workcoordination/WorkCoordinatorTest.java)
uses a per-class test instance and mutable container fields, with cleanup after
each invocation. Separate Bazel processes isolate those fields. Enabling JUnit
method concurrency inside the same instance would require additional changes.
Retain real lease-expiry and recovery sequences inside each case.

[TransformationShimE2ETest](../../libs/traffic/SolrTransformations/src/test/java/org/opensearch/migrations/transform/solr/TransformationShimE2ETest.java)
hides many TypeScript-defined scenarios inside two dynamic tests. It starts one
shared OpenSearch container in the factory and stops it only in the last Solr
version's case. Filtering dynamic cases without changing that ownership can
leak containers or break shared state. Refactor into independently owned
version/transform-binding batches, retain each cursor/request sequence, and
report individual scenario identities before applying sharding. The compiled
catalog currently contains 226 scenarios for each of Solr 8 and Solr 9, or 452
scenario executions. Each version has four binding groups of 218, 5, 2 and 1
scenarios. Splitting only the binding groups would leave the 218-scenario group
as a bottleneck; that group needs bounded batches with independently owned
containers. A generic
parameterized-test adapter must reject this class until that work is done.

Read-only inspection of the remaining targets at roughly 41 minutes confirmed
ongoing work: SnapshotReaderEndToEndTest was building a custom Elasticsearch
8.2 image (including package installation), while the backfill EndToEndTest was
starting Elasticsearch 8.15. This is preparation inside a test action, not only
migration/assertion time. The fixture image helper now records a structured
`FIXTURE_IMAGE_BUILD_RESULT` with image, duration and exit code for the next
export. This does not alter which image is built. Measure this contribution
before deciding whether separately cached or prebuilt images merit another
change; no image registry or extra worker service has been deployed.

## Implemented preparation, not yet deployed

The exporter now has an explicit allowlist in
[sharding.json](../../tools/build/bazel/full-suite/sharding.json). All other
classes retain one action. Bazel launches the selected class with native
`shard_count`; a Jupiter execution condition partitions actual runtime
invocations. It does not use a frozen case list from a previous run, so newly
added parameter values are still assigned to a worker.

The `fixture-index` policy assigns the same parameter index across methods to
the same shard. Only reviewed classes whose providers have compatible version
ordering use it. The `independent` policy hashes the complete JUnit unique ID.
Each action retains its own JVM, temporary directory and Docker daemon. The
adapter rejects dynamic factories, acknowledges Bazel's shard protocol, and
removes only its own foreign-shard skips from the exported XML. Real disabled
tests and failures remain visible.

The local contract probe exercises the actual JUnit 1.14.0 runtime and Python
wrapper. It verifies exactly-once coverage of 32 executed cases across 2/4/8
shards, failure propagation, legitimate disabled tests, nested/repeated tests,
fixture grouping, and skipping setup for cases owned elsewhere. This verifies
the mechanism; cluster behavior and performance remain unverified.

A separate native Bazel 8.4.2 local probe also passed: one class became four
test actions, with all 27 baseline cases passing exactly once. The focused
summarizer found all four output directories and passed its completeness gate.
Removing one reported case and duplicating another caused the gate to fail as
expected. [Contract evidence](evidence/native-sharding-contract.json).

Bazel requires a shard-aware runner; adding `shard_count` alone is insufficient.
See the [test sharding contract](https://bazel.build/reference/test-encyclopedia#test-sharding).
Jupiter supports conditional execution and extension auto-detection; dynamic
tests have different lifecycle semantics. See the
[JUnit 5.14 guide](https://docs.junit.org/5.14.0/user-guide/).

## Next comparison

1. Finish and preserve the active run, including the final long-target ranking.
2. Run PipelineEndToEndTest's seven shards first with test-result caching disabled,
   then the selected long targets. Keep worker limits unchanged for the first
   comparison to separate task granularity from resource changes.
   Use `buildbarn-rerun-tests`: the user clarified that image/build preparation
   should remain cached. This permits build action reuse while forcing selected
   tests to execute. Docker image caching was already enabled in the baseline,
   but is private to each worker; on-demand image creation is not a separate
   Bazel build action yet. Report worker/image warm state in both comparisons.
3. Compare actual case identity sets, failures, retries, action setup, total
   worker-seconds and elapsed time. Fail on missing or duplicated executed cases.
4. Use the long-target measurements to tune Docker CPU and memory. The current
   1.5-CPU Docker quota and observed OOM kills remain separate concerns. Do not
   add workers or lower reservations solely to improve a utilization percentage.

The sum of unchanged sequential case durations divided among workers is only a
scheduling estimate. Extra fixture generation, image pulls, JVM startup, queueing,
memory pressure and disk contention can all reduce the realized benefit.


## Live tail finding: Docker disk exhaustion

At approximately 65 minutes, all three remaining workers (SnapshotReader,
metadata EndToEndTest, and backfill EndToEndTest) reported their 40-GiB Docker
volumes at 100% usage, zero available bytes, with inodes still available. Each
retained 38–43 images and approximately 3 GB of build cache. Metadata's output
explicitly reports insufficient space while installing image-build packages;
backfill also reports an image-build failure. These are contaminated timings,
not a clean successful migration baseline. [Read-only evidence](evidence/long-test-disk-exhaustion.json).

The current source declares 87 backfill invocations, 120 metadata invocations,
and 111 SnapshotReader invocations (89 distinct source versions plus two checks
across 11 supported sources). These counts are derived from providers and test
methods, not completed-run coverage evidence. Each class currently occupies one
worker while it cycles through versions. Cleanup runs only at action boundaries,
so the 20-GiB image threshold does not bound accumulation within a long action.

The prepared 16-way split for each class creates smaller independently scheduled
batches and more frequent cleanup opportunities. SnapshotReader keeps matching
source-version indices together across methods to retain fixture reuse. Validate
actual shard coverage and disk peaks before treating this as a disk-capacity fix.
Move custom image preparation into separately cached builds backed by shared
image storage; tests should consume content-pinned images rather than independently
rebuild the same versions on private daemons. Image retention and scratch capacity
must then be sized for the largest batch. After correcting preparation and disk
pressure, compare Docker CPU quotas separately. Sharding performance remains
unmeasured, and dividing the current failing elapsed time by 16 is not a forecast.
