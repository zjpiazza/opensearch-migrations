# Buildbarn remote execution experiment

Context: `do-atl1-bazel`. Namespace: `migrations-buildbarn`.
Branch: `experiment/buildbarn-remote-execution`, based on the architecture layout.

These manifests adapt the [Buildbarn Kubernetes example](https://github.com/buildbarn/bb-deployments/tree/d4a6ca38e5f77959b42fccaa34a3320253683bc2/kubernetes).
Upstream Apache-2.0 license is retained in `LICENSE.buildbarn`.

## Placement and capacity

DigitalOcean cluster `bazel` in `atl1` uses these replacement pools:

| Node pool | Node size | Initial count | Autoscaling |
| --- | --- | ---: | --- |
| `bazel-execution` | `g5-16vcpu-64gb-80gb`: 16 vCPU / 64 GB | 3 | 1–8 nodes |
| `build-services` | `g5-4vcpu-16gb-80gb`: 4 vCPU / 16 GB | 1 | Fixed |

Three execution nodes provide nominal 48 vCPU / 192 GB; eight provide
128 vCPU / 512 GB, comparable in nominal allocation to the 30 GitHub runners
(120 vCPU / 480 GB). Per-core and storage performance differ. A new execution
node reports 15.86 CPU and about 57.62 GiB allocatable before pod requests.
The services pool is an ordinary worker pool; DigitalOcean manages the actual
Kubernetes API/control plane separately. One services node is not highly available. Frontend and storage each have
2-CPU/4-GiB limits with `GOMEMLIMIT=3GiB`; their previous 384-MiB/1-GiB
limits were OOM-killed during the full-suite request burst.

| Component | Pool | Replicas | Requests per replica |
| --- | --- | ---: | --- |
| Lightweight worker + runner | `bazel-execution` | 1–12 | 0.55 CPU, 3.125 GiB RAM |
| Standard integration + Docker | `bazel-execution` | 2–32 | 1.55 CPU, 9.125 GiB RAM |
| Large integration + Docker | `bazel-execution` | 1–8 | 2.55 CPU, 9.125 GiB RAM |
| Scheduler | `build-services` | 1 | 100m CPU, 128 MiB RAM |
| Frontend | `build-services` | 1 | 500m CPU, 1 GiB RAM |
| Storage | `build-services` | 1 | 1 CPU, 2 GiB RAM |
| Prometheus | `build-services` | 1 | 100m CPU, 128 MiB RAM |
| Autoscaler job | `build-services` | at most 1 active | 25m CPU, 64 MiB RAM |

Each worker offers one action slot. `--jobs=512` admits the entire 439-target
suite, including queued actions. Worker ceilings allow up to 52 action slots,
including 40 Docker-capable slots; these are ceilings, not guaranteed concurrent
execution. Demand drives worker replicas, and unschedulable pods drive node
scale-up within eight nodes. Preferred spreading replaces the previous required
one-Docker-worker-per-node rule. Kubernetes packs pods using resource requests
and volume attachment limits. A 9.125-GiB reservation still needs profiling;
larger nodes let several such workers fit without cutting memory blindly.

Lightweight runners request half a CPU and can use one CPU. Standard integration
runners request and are limited to one CPU; large runners request and are limited
to two. Every runner has 3 GiB RAM for the exported 2-GiB Java heap and overhead.
Docker sidecars reserve 0.5 CPU / 6 GiB and are capped at 1.5 CPU / 6 GiB, including
nested containers via `start-docker.sh`. Each pod retains its own Docker daemon;
its action-boundary cleaner is unsafe with concurrent actions sharing that daemon.

The v5 nodes still have only an 80-GiB boot disk. Each Docker worker therefore
uses a **12-GiB workspace PVC** and a **40-GiB Docker PVC** (standard) or
**100-GiB Docker PVC** (large-worker template), separate from
node-local storage. The `buildbarn-worker-scratch` StorageClass binds on placement
and deletes backing volumes when their owning pods/PVCs are deleted. Each worker
uses two CSI attachments (the observed driver advertises fifteen per node).
This adds block-storage cost, provisioning delay and different I/O performance;
measure those effects. Existing CAS/action-cache PVCs are retained across migration.
The cleaner removes leftover containers and build cache, then prunes unused tagged
images when retained layers exceed 20 GiB. Single-action peaks can still fill a volume.

The three active long-test Docker PVCs were expanded online from 40 to 100 GiB
after disk exhaustion. The large-worker template now requests 100 GiB, but its
live Deployment rollout is deferred until the active baseline completes to avoid
replacing test workers. Existing other PVCs remain at 40 GiB; changing a pod
template does not resize them. The Docker container's `ephemeral-storage` limit
applies to node-local writable layers/logs, not its mounted block-storage PVC.

The explicit [routing policy](../../../tools/build/bazel/full-suite/worker-routing.json)
sends 101 targets to lightweight workers, 327 to standard integration, and 11 to
large integration. Unknown tests default to integration. Pools are not interchangeable:
lightweight tests may finish while Docker queues remain busy. Platform changes alter
action-cache keys. See E-014/E-015 for the observed imbalance and sizing direction.
Execution nodes carry `workload=bazel:NoSchedule`; their selector and toleration
keep privileged Docker test pods on the dedicated pool without host Docker sockets.

Creation commands (pool size slugs are immutable; migrate workloads before
removing an old pool):

```bash
doctl kubernetes cluster node-pool create bazel --name build-services \
  --size g5-4vcpu-16gb-80gb --count 1 --label workload=build-services
doctl kubernetes cluster node-pool create bazel --name bazel-execution \
  --size g5-16vcpu-64gb-80gb --count 3 --auto-scale --min-nodes 1 --max-nodes 8 \
  --label workload=bazel --taint workload=bazel:NoSchedule
```

## Apply and connect

```bash
doctl kubernetes cluster node-pool update bazel bazel-execution --taint workload=bazel:NoSchedule
kubectl --context do-atl1-bazel taint nodes \
  -l doks.digitalocean.com/node-pool=bazel-execution workload=bazel:NoSchedule --overwrite
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
internal Buildbarn services. Integration pods include privileged Docker sidecars with a private Docker PVC
and shared action directory, but no host socket or host
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
