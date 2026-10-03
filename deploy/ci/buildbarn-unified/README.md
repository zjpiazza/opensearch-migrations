# E-034: one queue for long integration tests

This opt-in overlay replaces the 32 standard / 8 large slot split with up to
40 identical Docker-capable workers on the existing execution pool. Both types
of long tests use the `integration` platform. The lightweight and old large
deployments remain at zero; this experiment runs only the 16 reviewed long
classes / 131 shards, not the whole suite.

Each slot requests 2.55 CPU and 11.125 GiB RAM, with limits of 2 CPU for the
runner, 3 CPU for nested Docker workloads, and 0.25 CPU for bb-worker. Docker
has 8 GiB RAM, up from 6 GiB; the JVM runner retains 3 GiB. Five slots request
12.75 CPU and 55.625 GiB per 16-vCPU / 64-GB node. Verify actual allocatable
memory and system reservations before assuming five fit. CPU limits permit
bursting but do not guarantee five CPU per slot when the node is busy.

Workers use private 12-GiB action and 100-GiB Docker ephemeral PVCs. Tagged
Docker images are retained until 60 GiB of image layers. At 40 slots this is
4,480 GiB provisioned scratch storage; worker removal deletes these claims.
The larger scratch volume matches the previous large workers and accommodates
their image builds. Record storage cost alongside wall time and compute use.

The Docker Hub mirror is configured on every worker at startup. It does not
cache images from other registries or custom Elasticsearch build results, and
does not eliminate upstream tag validation/rate limits. Prewarm and verify the
required public images before launching the timed run. Then apply the
[read-only snapshot overlay](../buildbarn-image-snapshot/README.md) and verify
image pulls before timing; this avoids repeated upstream tag checks.

```bash
kubectl --context do-atl1-bazel apply -k deploy/ci/buildbarn-unified
python3 tools/build/bazel/full-suite/worker_routing.py
```

Applying starts one pilot worker and keeps bb-autoscaler suspended. Validate
Docker routing, nested resource accounting, scratch mounts and a real remote
test first. Then scale to the benchmark capacity within the existing eight-node
maximum. Unsuspending bb-autoscaler enables demand-based scaling to 40 workers;
do not reapply during a run because the overlay resets workers to one.

Keep the existing shard counts for the first comparison. Force fresh test
execution with `buildbarn-rerun-tests`, retaining image/build caches. Report
preparation separately and compare the same cases, not only successful shards.
Because sizing, routing and image preparation change together, this is a
throughput experiment, not an isolated estimate of any one change's benefit.

Rollback: set `unified_integration` false in `worker-routing.json`, rerun the
routing updater, and apply the base manifests between runs. Restore desired
replica counts deliberately; old large workers must be present before sending
actions to their platform. Preserve all evidence and the shared registry PVC.
