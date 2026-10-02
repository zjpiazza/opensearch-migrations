# Controlled worker resource experiments

The standard long-test sharded run observed 32 occupied standard worker slots but
only 46.5 of 112 execution-node CPUs in use. Eight sampled Docker cgroups were
throttled in 64–98% of scheduling periods, with a 1.5-CPU limit. This fraction is
not elapsed time lost. The runner JVMs used 0.008–0.282 CPUs in that interval.
Several Docker groups also reached their 6-GiB memory limit; this CPU experiment
does not resolve memory pressure.

`standard-docker-cpu-3.patch.json` changes only the standard integration Docker
CPU limit, from 1.5 to 3. Requests, memory, JVM sizing, routing, replica bounds,
storage, and large-worker configuration stay unchanged. It is a prepared trial,
not an adopted or deployed default.

Apply only after the current **standard-pool** run has finished and its outputs
have been saved. This triggers a rolling replacement of standard workers and
would interrupt active actions. The separately running large-worker pool does
not need to be restarted or resized.

```bash
kubectl --context do-atl1-bazel -n migrations-buildbarn patch deployment worker-integration \
  --type=strategic --patch-file deploy/ci/buildbarn/experiments/standard-docker-cpu-3.patch.json
kubectl --context do-atl1-bazel -n migrations-buildbarn rollout status deployment/worker-integration
```

Run the same selected long classes through `run-focused.py --pool integration`,
with a new evidence directory and forced test execution. Save live deployment,
node count, cgroup quotas, OOM/restart counters, cases and timing results. A new
pod loses its private Docker cache; record image warm state and run a matching
warm comparison before attributing the difference to CPU limits. Do not rerun
unrelated short tests or the entire suite.

The patch can be reverted by applying the same strategic patch with CPU `1500m`
when the standard pool is idle. Applying the base Deployment also restores the
baseline limit, but review its full diff first. Adopt a new default only after
case completeness, reliability, elapsed time, worker-seconds and node utilization
justify it. No speedup is implied by a higher configured limit.
