# Splitting the long integration tests

Status: the first standard-pool sharded run is complete: 76 actions and all 410
selected cases pass in 18m26s without test-result reuse. The original large-pool
baseline remains active. Standard Docker CPU tuning and finer partitioning are
next; hardware benchmarks, npm upload failures and short tests remain deferred.

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

## Sharding implementation and validation

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
fixture grouping, and skipping setup for cases owned elsewhere. This initially verified
the mechanism; the subsequent standard-pool remote results appear below. Large-pool
sharding performance remains unverified.

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

## Next comparisons

1. Preserve the completed standard-pool run and its whole-run coverage gate.
2. Compare the same 12 classes / 76 shards with standard Docker CPU capped at
   three rather than 1.5. Keep memory and JVM settings fixed. Record replacement
   workers, image/input cache state, startup and concurrent large-pool activity.
3. After that comparison, test the prepared 24-shard NoStoredSource policy to
   shorten the remaining tail without mixing CPU and partition-count changes.
4. When the original large-worker run finishes, validate its sharded long classes
   including PipelineEndToEndTest and the three broad version matrices. Failed
   original classes require full coverage validation and a successful baseline
   before reporting speedup ratios.

Use `buildbarn-rerun-tests`: build caching remains available, while every selected
test executes. Docker image caches are private to workers; image creation is not
yet a separately cached Bazel build action. Compare case identities, failures,
retries, image setup, aggregate worker time and elapsed time. Do not add workers
or lower memory reservations solely to improve a utilization percentage.

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


## First remote comparisons

The standard-pool run has completed LuceneSnapshotSourceEndToEndTest with all
88 original cases passing exactly once across eleven shards. Class elapsed time
is 124.413 seconds versus 785.697 seconds unsharded (6.315x observed speedup).
Summed shard time increases to 836.053 seconds, about 6.4% more aggregate action
time. EndToEndCompressionTest also completes with all ten cases exactly once:
240.449 seconds versus 912.066 seconds (3.793x). Neither reused test results.
These are class results, not completion of the twelve-class experiment.

The old SnapshotReaderEndToEndTest subsequently finished after 82.31 minutes:
74 cases passed and 37 failed while building custom images. Its runtime includes
disk exhaustion and online PVC expansion; it is not a successful speed baseline.
The sharded version must still execute all 111 original cases successfully.

`compare-focused.py` checks each completed class against the original CI case
identities before emitting a ratio. Missing or duplicated reports suppress that
ratio. Validation against copies of the actual 88-case result confirmed both
failure modes. See E-026/E-027 for evidence and measurement caveats.


## Completed standard-pool run

All 12 classes / 76 shards / 410 original cases pass in 1105.691 seconds driver
wall time. No cached results, missing or additional cases, duplicate execution,
or missing output manifests were found. NoStoredSourceMigrationTest is the final
class to finish: 784 seconds from its first shard start to last stop versus
3265.158 seconds unsharded. Driver wall time also includes startup and earlier
queueing; do not equate the 13-minute class span with the 18-minute run.

The original LeaseExpirationTest failed; its six cases now pass, but that is a
reliability observation rather than a valid speedup ratio. Successful class
comparisons range from 2.63x to 6.315x. [Whole-run coverage](evidence/sharded-standard-complete-summary.json)
and [per-class measurements](evidence/sharded-standard-complete-comparison.json).
The earlier partial observations remain above to preserve the experiment trail.


## E-034 follow-up: shared queue and prepared images

The next comparison retains the same 16 reviewed classes / 131 shards as the
interrupted combined run. Both integration tiers now route to one uniform pool,
so available workers can execute any of these long-test shards. The opt-in
[worker overlay](../../deploy/ci/buildbarn-unified/README.md) has up to 40 slots
on eight execution nodes, two-CPU runners, three-CPU/eight-GiB Docker limits,
and private scratch volumes. This changes resource allocation and preparation
as well as queueing; it is not a single-variable speedup experiment.

Public image preparation verified 36 Linux/amd64 images in 335.488 seconds.
The registry then switches to a read-only snapshot to avoid upstream tag
revalidation during tests. This does not prebuild custom Elasticsearch images
or pre-extract every public image into every worker. Both remain inside timed
execution. The supervised launcher records resource utilization and preserves
coverage evidence. [Preflight evidence](evidence/unified-preflight.json).

No new complete-suite or combined long-test speedup is claimed until every
selected original case passes, without missing/duplicate cases or cached test
results. The earlier successful 12-class measurement remains the reference for
those classes, with the usual hardware/preparation/concurrency caveats.
