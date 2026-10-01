# Buildbarn remote execution experiment

Context: `do-atl1-bazel`. Namespace: `migrations-buildbarn`.
Branch: `experiment/buildbarn-remote-execution`, based on the architecture layout.

These manifests adapt the [Buildbarn Kubernetes example](https://github.com/buildbarn/bb-deployments/tree/d4a6ca38e5f77959b42fccaa34a3320253683bc2/kubernetes).
Upstream Apache-2.0 license is retained in `LICENSE.buildbarn`.

## Placement and capacity

| Component | Pool | Replicas | Requests per replica |
| --- | --- | ---: | --- |
| Lightweight worker + runner | `workers` | 6 | 1.05 CPU, 1 GiB + 128 MiB RAM |
| Integration worker + runner + Docker | `workers` | 3 | 1.25 CPU, 4 GiB + 128 MiB RAM |
| Scheduler | `control-plane` | 1 | 100m CPU, 128 MiB RAM |
| Frontend | `control-plane` | 1 | 100m CPU, 128 MiB RAM |
| Storage | `control-plane` | 1 | 200m CPU, 512 MiB RAM |

The execution pool currently has three 4-vCPU/16-GB nodes. Each worker pod offers
one action slot; topology spreading places two lightweight workers and one
integration worker on each node. Runner CPU requests and limits are one CPU.
Each integration runner has a 3-GiB memory limit; its Docker sidecar requests
200m CPU / 1 GiB and may use up to 1 CPU / 6 GiB. Worker coordinators have separate
requests. This reserves about 3.35 CPU per node before system requests (measured
at 0.412 CPU/node), against 3.89 allocatable CPU. Nine workers do not mean nine
extra nodes. See the [full-suite bridge](../../../tools/build/bazel/full-suite/README.md).
The three 1-vCPU/2-GB `control-plane` pool nodes are ordinary managed worker nodes
used for supporting services, distinct from DigitalOcean's managed API servers.

The `workers` node pool is reserved with `workload=bazel:NoSchedule`, configured
through DigitalOcean so replacement nodes inherit it. Execution pods tolerate
this taint and require that pool's label. The taint does not evict existing pods;
Kubernetes networking, storage, and monitoring agents still run there.

## Apply and connect

```bash
doctl kubernetes cluster node-pool update bazel workers --taint workload=bazel:NoSchedule
kubectl --context do-atl1-bazel taint nodes \
  -l doks.digitalocean.com/node-pool=workers workload=bazel:NoSchedule --overwrite
kubectl --context do-atl1-bazel apply -k deploy/ci/buildbarn
kubectl --context do-atl1-bazel -n migrations-buildbarn get pods,pvc -o wide
kubectl --context do-atl1-bazel -n migrations-buildbarn \
  port-forward --address 127.0.0.1 service/frontend 8980:8980
```

In another shell, from the repository root:

```bash
./bazelw test --config=buildbarn //libs/migration-engine:sink_wiremock_test
```

The configuration is opt-in. It uses the existing nine-test WireMock source slice
ported to the refactored paths, with pinned dependencies and a matching Linux
execution platform. Local execution fallback is disabled. Bazel dependency
fetching and graph analysis still happen on the client; eligible compile/test
actions execute remotely. The ConsoleLauncher used by this pilot has no Bazel
sharding adapter: do not set `shard_count` and assume it partitions these tests.

## Validation

On 2026-10-01 all 12 pods were healthy without restarts, with three execution
workers on each dedicated node. The nine existing WireMock cases passed remotely.
Nine forced suite repetitions used all nine worker pods concurrently, taking
9.793 seconds total (individual suites 4.3–5.5 seconds). This verifies capacity;
it does not add scenarios or measure the full integration suite.

A fresh client reused 222 build actions and executed its test; a second fresh
client reused all 224 remote actions, including the test result. The first run
used 224 remote actions with no cache hits. Raw logs are ignored; compact results
are in [E-006 evidence](../../../docs/architecture-refactor/evidence/buildbarn-validation.json).

To repeat and retain action evidence:

```bash
mkdir -p build/buildbarn-evidence
./bazelw test --config=buildbarn //libs/migration-engine:sink_wiremock_test \
  --nocache_test_results --runs_per_test=9 \
  --build_event_json_file=build/buildbarn-evidence/concurrent.bep.json \
  --execution_log_json_file=build/buildbarn-evidence/concurrent.execution.json
python3 tools/build/bazel/summarize-remote.py build/buildbarn-evidence/concurrent
```

For a cache test, run without `--nocache_test_results` or `--runs_per_test`, then
repeat using a new `--output_base` (a Bazel startup option, before `test`) to avoid
local action-cache reuse. Record the same event/execution logs under a new prefix.
Bazel's `internal` actions are client bookkeeping; successful remote compilation
and test actions are reported as `remote`. Local execution fallback is disabled.
Forced runs in this configuration did not populate reusable remote test results;
the normal run seeded the result reused by the next fresh client.

The first-run 117.873-second elapsed time includes dependency/toolchain work;
fresh-client cache verification takes 11.962 seconds including client setup.
These samples have no equivalent local baseline and establish no speedup claim.
The pinned Bazel 8.4.2 emits a remote API deprecation warning against this
Buildbarn version. Both execution and result reuse were verified despite it.

## Storage and access

One storage instance has a 10-GiB CAS volume and two 1-GiB metadata-cache volumes;
the CAS block file is 8 GiB. All services are ClusterIP with no public ingress or
load balancer. Kubernetes authentication controls port-forward access. Namespace
network policy permits internal traffic and cluster DNS. Integration pods also
have explicitly approved public HTTP/HTTPS egress for image downloads; private
and link-local destination ranges are excluded from that additional rule. The runner is
unprivileged, with no host mounts or service-account token. The coordinator
sidecar retains `DAC_OVERRIDE` to access the runner-owned socket and action outputs;
the test runner drops all capabilities.

This is a trusted-code experiment, not a multi-tenant execution service. Worker
and runner share a pod and writable build directory; test actions can reach
internal Buildbarn services. Integration pods include privileged Docker sidecars with an isolated 40-GiB
emptyDir image store and shared action directory, but no host socket or host
filesystem mounts. Those privileges weaken host isolation and were explicitly
approved for this experiment. No cloud credentials are supplied to test actions.
A production installation needs its own access/isolation and availability design.
Caches persist across pod restarts; the scheduler and storage are single replicas.

## Rollback

Scale the execution Deployment to zero to stop accepting new work. To remove the
experiment, delete the `migrations-buildbarn` namespace; this also deletes the PVCs
and, with the selected storage class, their backing volumes. Do this only when
cached data is no longer wanted. Clear the `workload=bazel:NoSchedule` pool taint
only when the pool should accept other workloads again. No cluster/node count or
autoscaling changes are part of this experiment.
