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
