# Complete Gradle suite through Bazel remote execution

This experimental bridge exports the **real** `allTests` graph, prepares its
existing Gradle dependencies, and runs each JUnit class/task combination and npm
check as a Bazel test. Test assertions and tag filters are retained. The custom
30-way `BucketTestExtension` striping is omitted, so each selected test executes
without the other 29 shards discovering and skipping it.

Gradle still compiles Java, resolves dependencies, generates fixtures, checks
Javadoc, and installs npm dependencies. Report that preparation separately from
Bazel execution. These results cannot establish a native Bazel compilation gain.
Generated inputs live in ignored `build/full-suite`; they are not checked in.

The bridge also avoids nested Gradle startup for on-demand ES image builds and
removes repeated shard discovery/setup. Those improvements could be implemented
in a Gradle-based CI design too; do not attribute their entire benefit to Bazel.

## Prepare and execute

```bash
./gradlew -I tools/build/bazel/full-suite/export.gradle exportBazelTestRuntime \
  --max-workers=3 -x spotlessCheck --console=plain
python3 tools/build/bazel/full-suite/prepare.py
kubectl --context do-atl1-bazel -n migrations-buildbarn \
  port-forward --address 127.0.0.1 service/frontend 8980:8980
```

From another shell:

```bash
mkdir -p build/full-suite-evidence
./bazelw test --config=buildbarn @full_suite//:all_tests --keep_going \
  --test_timeout=7200 \
  --build_event_json_file=build/full-suite-evidence/full.bep.json \
  --execution_log_json_file=build/full-suite-evidence/full.execution.json
```

The first complete invocation should use an empty action-cache namespace (set
`--remote_instance_name` consistently for seed and reuse runs). Use fresh
`--output_base` directories for cross-client cache measurements. Do not force test
execution when populating a test-result cache: use a fresh instance instead.
Re-export after each source/configuration change before invoking Bazel. Invoking
Bazel alone does **not** rebuild the generated Gradle runtime bundles.

Compare unchanged, leaf-component, and shared-library changes, always requesting
`@full_suite//:all_tests`. Report preparation, Bazel wall time, cache hits, actual
executions, skipped/failed cases, image pulls/builds, and hardware allocations.
A cache hit reuses an earlier result; it is not another test execution.

`benchmark.py unchanged|leaf|shared --output build/full-suite-evidence/NAME`
creates a fresh client output base for each scenario. The leaf scenario changes
a dashboard parser log message; the shared scenario changes a core utility log
message. Both change compiled bytecode without intentionally breaking assertions.
They measure invalidation for those dependency locations, not the distribution
of real PR changes. Source text is restored in a `finally` block; the generated
runtime must then be rebuilt before it represents that restored source again.

For an already-running seed, `finish-benchmark.py` can wait for its BEP and run
all three scenarios sequentially. Supply the seed client's PID, its explicit
output-base testlogs path, the baseline JSON, and a new output directory; see
`--help`. It writes `status.json`, validates complete target/case coverage before
each next phase, and restores the prepared runtime after source-change scenarios.
Keep the authenticated Buildbarn tunnel running. A failed/interrupted seed stops
the driver; it does not turn a partial run into a cache benchmark.

## Live test dashboard

To measure full test execution without result reuse, use a fresh output directory:

```bash
./bazelw --output_base="$PWD/build/full-suite-evidence/uncached-client" test \
  --config=buildbarn-uncached @full_suite//:all_tests --keep_going --test_timeout=7200
```

The opt-in config disables remote action-result reads, test-result reuse and the
disk cache. Pick a previously unused output directory for each measurement.
Compiled runtime export, CAS inputs and worker container images may already be
warm; this measures uncached test execution, not a from-scratch Gradle build or
image-download benchmark. A new remote instance name alone does not establish
zero cache hits. Verify `cachedLocally` and `executionInfo.cachedRemotely` in BEP.
Pass `--label 'Full suite — result caching disabled'` to the monitor for this run.

The local dashboard shows every target, pass/fail status, elapsed test time, cache
hits, active worker assignments, and per-pool capacity and target progress. It
reads Bazel events and polls all worker pools; it does not alter tests or cluster
resources. Running counts observed test processes, excluding input preparation,
cleanup and output upload. Pending includes any target without an observed
process or result, including input-upload failures; it is not scheduler queue depth.

```bash
python3 tools/build/bazel/full-suite/monitor.py \
  --seed build/full-suite-evidence/full-6.bep.json \
  --comparisons build/full-suite-evidence/comparison-1
```

Open <http://localhost:8765> on the client machine. Results refresh every three
seconds and worker process observations every ten seconds. The monitor follows
the latest comparison automatically. It binds only to loopback; the local client
needs its existing Kubernetes credentials to inspect active workers. A failed
worker poll is displayed explicitly; its last successful observation may be stale.

## Coverage and runtime fidelity

`export.gradle` derives both JVM and npm checks from the actual `allTests`
dependency graph. `DiscoverTests.java` uses the exported classpath's JUnit engines
and each task's tag/engine filters. Normal, slow, isolated, and WireMock tasks
retain distinct identities, including the TrafficCapture normal/slow overlap and
its different memory-leak settings. Each test process receives the exported heap
settings, system properties, assertion setting, and a JaCoCo agent. JUnit XML and
coverage data are retained in Bazel undeclared outputs.

The generated inventory contains 433 JVM class/task combinations plus six npm
checks at this checkpoint. All 433 combinations match the successful class/task
union from the 30 original GitHub shards. Discovery matching alone does not prove
runtime case equivalence. Baseline HTML reports contain 4,794 distinct successful
cases, keyed by task, class, method and parameter index. Five additional cases
were disabled. Runtime comparison uses the same method identities in JUnit XML.

```bash
python3 tools/build/bazel/full-suite/coverage.py \
  build/full-suite-evidence/github-reports build/full-suite/inventory.json \
  build/full-suite-evidence/coverage-baseline.json
```

The snapshot fixture resolves `project.root` after source relocation. The optional
`test.image.builder` fixture property selects the bridge's image builder. It uses
the same ES Dockerfile, version catalogue and build arguments as Gradle; ordinary
Gradle tests retain the original Gradle image-build entry point.

## Execution environment and limitations

Container tests run in three single-slot integration pods, each with its own
Docker daemon; no test shares a daemon with another concurrently executing test.
Six lightweight slots remain for the original native Bazel graph. The existing
three execution nodes are unchanged. Privileged Docker sidecars and registry
HTTP/HTTPS egress were explicitly approved by the user. This remains a trusted
code experiment, not an environment for arbitrary public PR code.

Toolchains, compiled classes, jars, npm dependencies, generated Python fixture
archives and test resources are declared inputs. Gradle preparation itself is not
hermetic: for example, the existing Pydantic fixture installs unpinned packages.
Docker image tags and on-demand ES image downloads also remain external state.
Cache results from these container tests are experimental and must not be treated
as proof that current external services or changed image tags still work. A
production cache policy needs immutable image/fixture inputs or exclusion of
those actions from test-result caching, plus scheduled forced executions.

The worker image supplies Python and Docker CLI. The exported Amazon Corretto JDK
and Node toolchain match Gradle. Fixed worker image/platform properties separate
these results from the original WireMock-only execution platform. Tests receive
no cloud credentials; image downloads use public registries.

## Worker routing

`worker-routing.json` selects lightweight tasks and larger integration classes
explicitly. Unknown targets retain standard integration workers. All targets
remain in `all_tests`; this changes placement, not coverage. To change routing
without rebuilding runtime archives:

```bash
python3 tools/build/bazel/full-suite/worker_routing.py
```

`prepare.py` also applies the same policy on every export. The Buildbarn config
admits 512 in-flight actions to avoid starving one platform behind another
platform’s queue. Actual execution is capped at 52 slots across independently
autoscaled lightweight (1–12),
standard integration (2–32), and large integration (1–8) pools. Large runners have
two CPUs; other runners have a one-CPU limit. Changing execution properties
invalidates affected action-cache entries. The live monitor inspects all pools.

## Focused long-test sharding experiment

`sharding.json` opts selected long Jupiter classes into native Bazel sharding.
The adapter partitions parameter invocations at runtime, so adding a version
does not require maintaining a frozen selector list. `fixture-index` keeps
matching provider indices together across methods; `independent` hashes the
complete case ID. Only reviewed classes should use these policies. Dynamic
factories require separate fixture ownership changes and are rejected.

Check the adapter locally using the prepared JDK/JUnit:

```bash
python3 tools/build/bazel/full-suite/verify-sharding.py
```

After any active run finishes, use `sharding.py` to configure the selected
classes without repacking compiled runtime archives. `sharding.py --dry-run`
previews the change, and `sharding.py --unsharded` restores class-level execution.
Full `prepare.py` exports also apply the shard policy unless `--unsharded` is
supplied. Do not update the runtime while a benchmark is using it.

For a focused comparison, select an explicit target instead of `all_tests`:

```bash
bazel test --config=buildbarn-rerun-tests \
  @full_suite//:DocumentsFromSnapshotMigration_isolatedTest__org.opensearch.migrations.bulkload.PipelineEndToEndTest
```

Capture BEP, execution logs and a fresh output base as for other measurements.
`buildbarn-rerun-tests` disables test-result reuse while permitting ordinary
build caching. The older `buildbarn-uncached` configuration additionally rejects
all remote action results and disables the disk cache. Neither option disables
Docker's own image/layer cache. Currently those Docker caches are private to
each worker and images are still built on demand inside the tests. Shared,
separately prepared images require additional implementation.

Pass the exported target name with `--target` to both `monitor.py` and
`summarize.py`; repeat the option when comparing several long classes. The
monitor distinguishes completed classes from running/completed shard tasks.
The summarizer's `--require-complete` gate checks all expected shards, all
selected baseline cases, and absence of duplicate executed cases. It preserves
real disabled tests, excluding only cases assigned to a different shard.

See [long-test analysis](../../../../docs/architecture-refactor/long-test-partitioning.md)
for observed durations, fixture constraints, validation and pending cluster
measurements. Local adapter checks are not evidence of integration-test speedup.


To fill the standard integration pool with only configured long-test shards:

```bash
python3 tools/build/bazel/full-suite/run-focused.py --pool integration \
  --instance migrations-mixed-workers-1 \
  --baseline /path/to/coverage-baseline.json \
  --output build/full-suite-evidence/standard-long-sharded-1
```

This currently selects 12 classes / 76 actions and excludes all large-worker
classes. It records a fresh client, routing, target inventory and process status,
forces test execution, then validates complete case coverage without duplicate
executions. Use a new output directory per run. The wrapper records preparation,
execution and reporting durations separately in each `invocation.json`.

A separate exported-runtime copy allows this run to coexist with the earlier
large-pool tail without modifying its inputs. Pools have separate slots but
share nodes, storage services and network capacity; record overlapping activity
when interpreting wall time. Compiled runtime reuse is not a compilation-speed
measurement. Preserve the original runtime and record any refreshed fixture
helpers before running.


Use `compare-focused.py` during or after a run to compare completed classes with
an earlier unsharded BEP and the original case baseline:

```bash
python3 tools/build/bazel/full-suite/compare-focused.py \
  build/full-suite-evidence/standard-long-sharded-1 \
  --unsharded-bep /path/to/unsharded/results.bep.json \
  --baseline /path/to/coverage-baseline.json \
  --output build/full-suite-evidence/standard-long-sharded-1/comparison.json
```

It reports elapsed and summed shard time, per-shard wrapper timing and logged
image builds. A speedup ratio requires both runs to pass, all expected shard
outputs, no cached results, and exactly the original successful case identities
without duplicate executions. An unfinished or failed baseline is not a speed
reference. The driver's whole-run completeness gate remains authoritative.


A focused policy can update only one reviewed class in an idle runtime:

```bash
python3 tools/build/bazel/full-suite/sharding.py \
  --policy tools/build/bazel/full-suite/sharding-no-stored-source-24.json --dry-run
```

Remove `--dry-run` only after the active run and the separate CPU-limit comparison
finish. This prepared trial changes NoStoredSourceMigrationTest from eight to 24
shards, retaining all other configured classes. The current default stays at
eight. Reapply the default policy to restore the initial counts. Do not change
shard counts and worker CPU quotas in the same comparison.
