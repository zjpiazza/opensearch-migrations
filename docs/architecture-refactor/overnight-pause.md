# Overnight pause — 2026-10-01 (America/Chicago)

The owner requested minimizing overnight costs and resuming in the morning.
Both DigitalOcean node pools are set to zero with node autoscaling disabled.
The bb-autoscaler CronJob is suspended. All six Buildbarn Deployments and both
StatefulSets have zero replicas. No tests should be started until resumed.

Verified: all eight execution droplets and all 80 scratch volumes are deleted.
The final services node still reports `deleting` in the provider API and remains
billable until deletion completes. A managed connectivity-agent disruption budget
is delaying its normal drain. Automatic approval review rejected directly deleting
that managed pod; the protection remains intact. Do not claim the cluster has
zero actual droplets until the provider confirms it.

The persistent AC, CAS, filesystem AC and image-cache claims are retained:
1 + 10 + 1 + 50 = 62 GiB. Worker scratch claims use generic ephemeral volumes
and are removed when workers scale down. Their private Docker/image caches and
the one-worker live-reload pilot configuration are disposable. Local test results,
source manifests and exported compiled inputs remain intact.

Persistent volumes and the existing managed HA control plane still incur charges.
This operation applies to the Kubernetes cluster; it does not delete the earlier
standalone runner VM. There is no automatic morning restart.

## Resume deliberately

First restore the services node and wait for it and the cluster's system services
to become ready:

```bash
doctl kubernetes cluster node-pool update bazel build-services --auto-scale=false --count 1
kubectl --context do-atl1-bazel get nodes
```

Then restore Buildbarn's services and verify their rollouts and retained volumes:

```bash
kubectl --context do-atl1-bazel -n migrations-buildbarn scale deployment \
  frontend scheduler-ubuntu22-04 buildbarn-prometheus --replicas=1
kubectl --context do-atl1-bazel -n migrations-buildbarn scale statefulset \
  storage buildbarn-image-cache --replicas=1
```

Review the next worker configuration before restoring test capacity. The former
execution pool used eight 16-vCPU/64-GB nodes at peak, autoscaling bounds 1–8.
It can be brought back with one node initially:

```bash
doctl kubernetes cluster node-pool update bazel bazel-execution \
  --auto-scale=true --min-nodes 1 --max-nodes 8 --count 1
```

Keep the worker autoscaler suspended until the next configuration is selected.
When ready, resume it with:

```bash
kubectl --context do-atl1-bazel -n migrations-buildbarn patch cronjob bb-autoscaler \
  --type=merge -p '{"spec":{"suspend":false}}'
```

It will recreate the configured worker minimums and react to queued work. Before
another run, persist the shared image-cache configuration, address idle standard
capacity stranded behind separate queues, and use a benchmark process that
survives client-session interruption. Do not restart the interrupted benchmark
as if it were a completed timing baseline.

Saved live pre-pause configuration and verification:
`build/full-suite-evidence/overnight-pause/` in the experimental worktree.
DigitalOcean documents [scaling all node pools to zero](https://docs.digitalocean.com/products/kubernetes/how-to/autoscale/#scaling-to-zero).
