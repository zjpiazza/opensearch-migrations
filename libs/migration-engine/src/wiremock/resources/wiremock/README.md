# Destination HTTP record/replay experiment

Run the production RFS destination sink and HTTP client against recorded engine
responses, without starting Elasticsearch, OpenSearch, Kubernetes or Docker:

```sh
./gradlew :RFS:wiremockTest
# Force actual playback, even when the task is up to date:
./gradlew :RFS:wiremockTest --rerun
```

The normal `:RFS:test` task also includes the compiled WireMock tests and resources,
preserving ordinary test filtering and CI striping. WireMock 3.13.2 is a test-only
dependency. Its standalone JAR shades dependencies to avoid conflicts with the
application's HTTP and JSON libraries. No production sources or E2E triggers change.

## Coverage

`SinkWireMockTest` executes the real `OpenSearchDocumentSink`,
`OpenSearchMetadataSink`, client version detection, bulk serialization,
HTTP transport, response parsing and terminal document failure classification.

| Recorded scenario | Behavior checked |
| --- | --- |
| CREATE | Index creation, including an index name containing `__` |
| UPSERT | Three documents, including IDs and complete document bodies |
| DELETE | Initial writes followed by deleting one document |
| ROUTING | Routing information included in the bulk request |
| METADATA | Legacy typed mappings unwrapped, `string` converted to `text`, source-only settings stripped |
| PARTIAL_FAILURE | A real `mapper_parsing_exception` response produces a terminal failed-document record for the correct document/session |

Playback matches method, path/query and exact request bodies. It requires every
recorded interaction to occur exactly the recorded number of times, and rejects
unmatched requests. Three negative tests prove that an omitted bulk write, a
duplicate bulk write and a dropped document field cannot pass verification.

The six JSON cassettes contain genuine responses from Elasticsearch 7.10.2.
While recording, a separate client reads the real engine to verify document
counts, contents, deletion, routing, mapping conversion and rejection of the
invalid document. Those verification reads are **not** replayed as proof of a
successful migration; playback verifies the worker's outgoing writes instead.

This is a destination contract slice of the existing sink E2E scenarios. It does
not read snapshots, execute Argo, migrate a complete cluster, verify a live search
engine's indexing behavior during playback, test TLS/SigV4, exercise compressed
requests, or persist failed-document records to S3. It covers one recorded engine
version and serial request patterns. Existing real E2E/compatibility tests remain
necessary. Adding other versions, retries and concurrent flows requires additional
recordings and assertions; the request counts alone do not enforce ordering.

## Refresh recordings deliberately

Use a fresh, disposable, unauthenticated local engine. Recording creates six
`wiremock__*` indices and refuses an engine where any scenario's index already
exists. It also refuses to overwrite an existing output directory. Recording is
a separate JavaExec task; normal tests never record or proxy to the real engine.

For example, with the repository's `custom-elasticsearch:7.10.2` image already
built locally:

```sh
docker run -d --name migrations-wiremock-recording --memory=2g \
  -p 127.0.0.1:19200:9200 \
  --tmpfs /usr/share/elasticsearch/data:rw,uid=1000,gid=1000 \
  -e discovery.type=single-node \
  -e 'ES_JAVA_OPTS=-Xms512m -Xmx512m' \
  -e xpack.security.enabled=false custom-elasticsearch:7.10.2
# Wait until http://127.0.0.1:19200 responds, then record to a NEW directory:
./gradlew :RFS:recordWireMock \
  --args='http://127.0.0.1:19200 /tmp/wiremock-sink-recording'
docker rm -f migrations-wiremock-recording
```

Review the six generated JSON files against `sink/` before replacing them, then
rerun `:RFS:wiremockTest --rerun`. Changes to application behavior may require
intentional fixture updates. Do not automatically accept updated recordings on
PRs: a recording can preserve a bug unless live assertions and review catch it.
The recorder retains response bodies, removes Date headers and assigns stable
mapping IDs. Engine-generated IDs and timing fields can still differ on refresh.

Initial recording provenance (2026-10-01): local image `custom-elasticsearch:7.10.2`,
image ID `sha256:3cd6ab343f4ccd82468813667a59cacf509df97d544fabb8f2e9e2fa37dba93e`.
Each cassette includes the engine's version/build response. Recording used only
synthetic documents and an unauthenticated, isolated local engine.

## Timing experiment

```sh
python3 libs/migration-engine/src/test/wiremock/benchmark.py
```

This separately measures complete runtime classpath preparation (`:RFS:prepareWiremockTest`),
forced playback and unchanged task reuse. Playback fails the benchmark if any other
task still executes or restores outputs: dependency preparation belongs in the first
measurement. Gradle profiles in `build/reports/profile/` expose configuration and task
costs. The dedicated `src/wiremock` source set avoids compiling ordinary RFS tests
and their container fixtures; production RFS dependencies still have to build.
Javadoc is validated separately by the workflow and remains part of `:RFS:check`
and the existing ordinary test tasks. It verifies nine passing tests with no skips. Logs and JSON measurements
are written to `build/wiremock-ci-results/`; JUnit/HTML reports are under
`libs/migration-engine/build/test-results/wiremockTest/` and `libs/migration-engine/build/reports/tests/wiremockTest/`.

The fork-only `WireMock experiment` GitHub workflow runs the same script, uploads
evidence and includes a timing table in its job summary. It points Docker at an
unavailable socket to ensure these scenarios do not require containers. Dependency
downloads and compilation can still dominate a fresh CI job; setup/cache transfer
are outside the script's timings. Playback is not equivalent to the complete E2E
suite and these timings must not be described as a two-hour-to-seconds speedup.

## Preparation audit

The original focused task filtered the ordinary RFS test suite at execution time,
but still compiled that entire suite and its container fixtures. Moving the nine
cases into their own source set removes 51 prerequisites and introduces five tasks
(including the explicit preparation task): the local dry-run graph drops from 162
to 116 tasks, excluding buildSrc. Task count is not a wall-time speedup estimate.
Capture protobuf generation, ordinary test compilation and container test fixtures
are no longer prerequisites. Production snapshot and transformation dependencies
remain; the recordings and production behavior under test are unchanged.

The original GitHub run (36895169894) restored Gradle caches, including a fallback
from the default branch, but preparation still executed 44 tasks and restored 18.
Its 102.545-second preparation measurement omitted runtime-only project builds;
the 18.448-second playback command also compiled transformation providers. Use the
new complete-classpath measurement for future comparisons and compare fresh
runners with equivalent cache state. An unchanged invocation on the same runner
only measures local up-to-date checks, not cross-runner cache reuse.

Further production separation should start with a destination module containing
`OpenSearchDocumentSink`, `OpenSearchMetadataSink`, `OpenSearchIndexCreator`, the
versioned `OpenSearchClient` implementations, bulk serialization/response parsing,
and failed-document interfaces. The S3 implementation should stay in the application
composition layer. Merely moving the test into a new project depending on RFS would
retain the current dependency graph.

A destination module alone will not eliminate all Lucene builds: `RfsHttp` depends
on `RfsCommon`, whose compilation explicitly builds shaded Lucene 9/10 JARs, and
`RfsPipeline` has a compile dependency on `RfsCommon` for its adapters. The HTTP
client also uses `IRfsContexts` from that module. Shared models/tracing contracts
and snapshot-specific types need separate boundaries before destination tests can
avoid snapshot libraries altogether. This is a follow-up refactor, not a reason
to duplicate production sources inside the test build.
