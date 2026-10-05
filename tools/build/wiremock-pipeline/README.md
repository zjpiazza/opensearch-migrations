# Local pipeline replay experiment

This experiment compares all 28 existing `PipelineEndToEndTest` scenarios (four
methods × seven source/target pairs). The shared test methods exercise the real
snapshot extractor, Lucene reader, metadata/document pipelines, serializers, and
HTTP clients. It runs locally; no Buildbarn worker or remote execution is used.

## What each mode proves

| Mode | Source | Destination | Assertions |
| --- | --- | --- | --- |
| `pipelineRealBenchmark` | Real engine generates snapshots; within-run snapshot reuse | Real engine | Original indexing, counts, routing search, metadata existence |
| `pipelinePreparedSnapshotBenchmark` | Pinned real snapshot ZIPs | Real engine | Same original destination assertions |
| `pipelineWiremockTest` | Same pinned snapshot ZIPs | Embedded WireMock | Exact recorded request bodies/counts, emitted documents/IDs/routing, metadata creation requests, pipeline cursors/batching |

Replay does not prove the destination accepts settings, indexes documents, or
returns correct search results. Its assertions inspect actual outgoing writes;
no canned search result is used to claim persistence. Original real-engine tests
remain intact. Snapshot creation/compatibility still needs live-engine coverage.

All three local comparison modes disable HTTP request compression so the recorder
can match full request bodies. Normal E2E defaults retain compression. This
experiment is not a replacement for the compression tests.

These tasks are opt-in and excluded from `allTests` and aggregate coverage.
Recording cannot be triggered by a normal test run.

## Record deliberately

Preload the required images before timing; retain their exact Docker identities.
The private image registry can be read through a local authenticated tunnel,
without restoring remote execution workers. A recording runs original real-engine
assertions outside the HTTP proxy and saves real snapshots plus compressed HTTP
cassettes. Existing cassette files are never overwritten. Capture disables the older
on-disk snapshot cache so a new recording actually regenerates source snapshots.

```bash
./gradlew :DocumentsFromSnapshotMigration:recordPipelineWiremock \
  -PpipelineFixtures=/absolute/path/to/NEW_DIRECTORY --fail-fast
```

Review all 28 passing scenarios, image provenance, snapshot checksums, and
recorded interactions before adopting a recording. The candidate directory must
be new. Regenerate for intentional external contract/scenario changes or verified
staleness; investigate replay regressions before changing the expectations.

## Run playback locally

```bash
DOCKER_HOST=tcp://127.0.0.1:1 ./gradlew \
  :DocumentsFromSnapshotMigration:pipelineWiremockTest --rerun
```

## Measure locally

```bash
python3 tools/build/wiremock-pipeline/benchmark.py \
  --fixtures apps/backfill/src/wiremock/resources/pipeline \
  --output build/wiremock-pipeline/NEW_BENCHMARK
```

The driver prepares the runtime first, then runs real engines, prepared snapshots
with a real destination, and three forced replay executions. Every phase uses a
single test JVM with the same heap/thread configuration. It records Gradle wall
time separately from JUnit time and requires the same 28 passing scenario names,
without skips. Snapshot caches are isolated by phase. Recording and image pulls
are outside the measured test phases. Replay sets Docker to an unreachable local
endpoint. The replay implementation fails on missing fixtures, starts only the
embedded HTTP server, and rejects proxy mappings; it never calls the live target
start path. This is not an operating-system network sandbox.

Run the negative controls separately:

```bash
./gradlew :DocumentsFromSnapshotMigration:pipelineReplayGuardTest --rerun
```

They verify missing/duplicate writes, dropped fields, and unexpected requests
fail the same request verifier used by replay. Keep these out of the 28-case
performance comparison.

Results are local experiment evidence, not a prediction for the entire 756-case
integration suite or an apples-to-apples comparison with the remote 40-worker
benchmark. Record hardware and background-workload limitations with measurements.

## Observations to preserve in the RFC

The recordings include real error responses, including rejected built-in system
templates. Metadata migration currently retries some of these responses and then
continues; the original test asserts migration of its own index, not success of
every system template. Replay preserves those responses, retry sequences, and
production backoff. It must not turn a recorded failure into success to improve
the benchmark. Timer injection/virtual time would be a separate experiment.

Repeated requests use WireMock scenario states. Stub IDs must identify both the
request and its scenario state; per-state counts are one, not the total number of
identical requests across all states. The fixture provenance records normalization
of the first capture's IDs/counts without changing HTTP payloads or transitions.

## Measured local results (2026-10-03)

All 28 scenario identities passed in every mode, with actual test execution forced.
The real controls each ran once; replay ran three times. Images/dependencies were
already local, and runtime preparation was separate (6.179s).

| Mode | Gradle wall time | JUnit time |
| --- | ---: | ---: |
| Real source and destination | 622.488s (10m22s) | 615.660s |
| Pinned snapshots, real destination | 531.589s (8m52s) | 524.577s |
| Pinned snapshots, WireMock (median) | 301.858s (5m02s) | 295.137s |

Replay wall trials were 296.142s, 307.749s, and 301.858s. The median is 51.5%
shorter than the ordinary real-engine run, and 43.2% shorter than the control
that already reuses snapshots. Observed differences are 90.899s for snapshot
preparation and another 229.731s for substituting the destination with WireMock.
These are differences between runs, not separately instrumented phase durations.

The 21 document/batching cases took 269.080s with ordinary engines, 179.402s
with prepared snapshots and a real destination, and a median 2.108s with replay.
The seven metadata cases dominate replay: median 292.940s. Forty rejected
system-template operations receive four HTTP 500 responses each, producing 120
production retry waits. The next optimization is an injectable retry scheduler
or test clock with assertions that preserve retry behavior, rather than changing
recorded error responses into successes.

Hardware: Ryzen 7 7800X3D (8 cores / 16 threads), approximately 62 GiB reported
RAM, Corretto 21.0.11, Docker 29.7.2, Gradle 8.14.3, WireMock 3.13.2. All modes
use one test JVM, a 2-GiB heap, two Netty/Reactor workers, and disabled JaCoCo.
Existing unrelated local services remained running. Retry jitter and the single
run per real control limit precision. These are Gradle results; Bazel and remote
execution contributed none of this measured speedup.

[Per-scenario evidence and input hashes](../../../docs/architecture-refactor/evidence/local-wiremock-pipeline-comparison.json)
and [RFC experiment journal](../../../docs/architecture-refactor/journal.md#e038--local-full-pipeline-wiremock-comparison-2026-10-03)
retain the methodology and coverage limits.
