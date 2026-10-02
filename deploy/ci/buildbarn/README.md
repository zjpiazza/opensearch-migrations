# Buildbarn remote execution experiment

Context: `do-atl1-bazel`. Namespace: `migrations-buildbarn`.
Branch: `experiment/buildbarn-remote-execution`, based on the architecture layout.

These manifests adapt the [Buildbarn Kubernetes example](https://github.com/buildbarn/bb-deployments/tree/d4a6ca38e5f77959b42fccaa34a3320253683bc2/kubernetes).
Upstream Apache-2.0 license is retained in `LICENSE.buildbarn`.

## Placement and capacity

| Component | Pool | Replicas | Requests per replica |
| --- | --- | ---: | --- |
| Lightweight worker + runner | `workers` | 3–9 | 0.55 CPU, 3 GiB + 128 MiB RAM |
| Standard integration + Docker | `workers` | 2–6 | 1.55 CPU, 9 GiB + 128 MiB RAM |
| Large integration + Docker | `workers` | 1–3 | 2.55 CPU, 9 GiB + 128 MiB RAM |
| Scheduler | `control-plane` | 1 | 100m CPU, 128 MiB RAM |
| Frontend | `control-plane` | 1 | 100m CPU, 128 MiB RAM |
| Storage | `control-plane` | 1 | 200m CPU, 512 MiB RAM |
| Prometheus | `control-plane` | 1 | 100m CPU, 128 MiB RAM |
| Autoscaler job | `control-plane` | at most 1 active | 25m CPU, 64 MiB RAM |

The execution pool has 4-vCPU/16-GB nodes and owner-configured autoscaling from
three to nine nodes. Each worker offers one action slot. The client admits up to 512
in-flight actions (queued plus executing), enough to expose this entire suite to
Buildbarn. The three worker pools cap actual execution at 18 concurrent tests. Each node can
host at most one lightweight pod and one Docker-capable pod; integration
anti-affinity spans both standard and large tiers.

Keep client admission above the worker count: `--jobs` also includes queued
actions. Setting it to 18 starved the lightweight and large queues while standard
integration targets occupied admission slots. Widening admission fixes that
bottleneck, but does not make pools interchangeable. In the mixed-suite run all
101 lightweight targets finished early, leaving nine idle lightweight workers
while Docker tests remained. E-014 records CPU usage and this remaining imbalance.
Two existing Docker workers would request 18.25 GiB on a node with about 13.33 GiB
allocatable, so removing anti-affinity alone cannot increase Docker concurrency.
Measure per-test container memory peaks before defining a smaller Docker tier;
the current runner also needs room for its declared 2-GiB Java heap.

Lightweight runners request half a CPU and can use one CPU. Standard integration
runners request and are limited to one CPU; large runners request and are limited
to two. Every runner has 3 GiB RAM, sufficient for the exported 2-GiB Java heap
plus runtime overhead. Docker sidecars reserve 0.5 CPU / 6 GiB and are capped at
1.5 CPU / 6 GiB. `start-docker.sh` places nested containers below the sidecar's
cgroup so those ceilings include their workloads. The integration runner uses
Buildbarn’s idle/action-boundary cleaner to remove leftover containers, dangling
images and build cache. Tagged images remain until their layers exceed 20 GiB,
then unused images are pruned to leave headroom below the 40-GiB Docker volume.
This bounds accumulation between actions; a single action can still exhaust its
volume and must be measured. Each coordinator separately
requests 50m CPU / 128 MiB. A large + lightweight pair requests 3.10 CPU and
12.25 GiB before node system pods; capacity must include their requests too.

The explicit [routing policy](../../../tools/build/bazel/full-suite/worker-routing.json)
currently sends 101 targets to lightweight workers, 327 to standard integration,
and 11 to large integration. Unknown tests default to standard integration.
Changing platform properties changes action cache keys for affected targets.
See the [full-suite bridge](../../../tools/build/bazel/full-suite/README.md).
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

## Worker autoscaling

`bb-autoscaler` runs once per minute as a CronJob. A private Prometheus instance
scrapes scheduler metrics every 15 seconds. All three worker Deployments are
managed independently, using the bounds in the capacity table. The client
admits up to 512 in-flight actions (`--jobs=512`); worker replicas bound execution.

The demand calculation counts scheduled actions minus completed executions,
retains registered worker capacity while any actions remain, and uses a 15-minute
high-water mark. This avoids shrinking the Deployment simply because a few long
tests are left running. Once the queue is idle for the window, the autoscaler can
return each pool to its configured minimum. Missing scheduler scrape data yields no scaling decision.
This is an idle-window policy, not a general drain-aware termination protocol;
there is still a scrape/reconciliation race if new work arrives during scale-down.

The autoscaler patches only the three named worker Deployments. Its ServiceAccount
has no permission to modify supporting deployments, nodes, or cloud settings. Its
additional network policy permits HTTPS to this cluster's API service and endpoint
addresses; update those addresses if migrating this configuration to a new cluster.
Images are pinned by digest. Prometheus keeps two hours of ephemeral metrics in
512 MiB of local storage; historical RFC evidence is saved separately in the repo.

The owner enabled DigitalOcean autoscaling on the `workers` pool in cluster
`bazel`, minimum 3 / maximum 9. Integration pod anti-affinity makes extra replicas
pending until an additional node is available. Neither the worker autoscaler nor
its ServiceAccount changes the node pool directly.

`spec.replicas` is omitted from all worker manifests so future applies do not
reset the controller's value. During migration, update last-applied annotations before applying manifests to
avoid resetting existing replica counts.
For a new installation the autoscaler establishes the configured minimum after
scheduler metrics become available.

```bash
kubectl --context do-atl1-bazel -n migrations-buildbarn get cronjob bb-autoscaler
kubectl --context do-atl1-bazel -n migrations-buildbarn get deployment worker-integration
kubectl --context do-atl1-bazel -n migrations-buildbarn get jobs --sort-by=.metadata.creationTimestamp
kubectl --context do-atl1-bazel -n migrations-buildbarn exec deploy/buildbarn-prometheus -- \
  env TMPDIR=/prometheus promtool test rules /etc/prometheus/autoscaler-rules.test.yaml
```

The rule tests cover scale-up demand, retaining workers during the tail of a run,
idle-window expiry, and missing-metrics handling. The initial live autoscaler job
successfully requested nine replicas from the real queue. Suspending the CronJob
stops further scaling decisions while preserving current replicas.

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
only when the pool should accept other workloads again. The node autoscaling bounds are owned separately; removing the namespace does
not disable the owner-configured pool autoscaler.
