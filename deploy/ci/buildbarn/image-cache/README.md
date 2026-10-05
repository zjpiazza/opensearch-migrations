# Shared Docker Hub image cache

Experimental Distribution 3.1.2 pull-through cache, pinned to its Linux/amd64
manifest. It runs on the existing services node with a 50-GiB persistent volume.
The ClusterIP service is internal to the cluster. The existing namespace network
policy permits namespace-local access; this overlay permits the cache's upstream
HTTPS requests. It contains public images and no upstream credentials.

```bash
kubectl --context do-atl1-bazel apply -k deploy/ci/buildbarn/image-cache
```

This standalone overlay creates the cache only. The
[unified-worker experiment](../../buildbarn-unified/README.md) configures the
mirror persistently on every worker. The earlier pilot below used live reload. The current pilot
configured one idle standard worker through `/etc/docker/daemon.json`:

```json
{
  "registry-mirrors": ["http://buildbarn-image-cache.migrations-buildbarn.svc.cluster.local:5000"],
  "insecure-registries": ["buildbarn-image-cache.migrations-buildbarn.svc.cluster.local:5000"]
}
```

Docker supports live reload of these fields via SIGHUP. The pilot changed only
this internal registry's transport policy and preserved the existing image ID.
Its cache configuration is container-local and is lost on container replacement.
Persisting it in worker startup configuration and enabling it across the pool
remain pending. Do that between benchmark runs and record the cache state.

The registry API probe downloaded all Ryuk 0.14.0 amd64 blobs twice and verified
every SHA-256 and size. A real Docker pull on the idle pilot worker contacted the
mirror and retained the existing image ID. This validates routing and content,
not a test-suite speedup or offline operation. See journal E-032.

This cache reduces repeated public image transfers. It does not cache custom
Elasticsearch image builds or Bazel test results. Docker Hub limits still apply
to upstream requests; tag requests can revalidate upstream and simultaneous cold
pulls can generate multiple requests. Prepare the required image inventory and
measure registry hits before claiming the pull-limit problem is solved.

The StatefulSet's claim persists independently of worker churn and remains after
the StatefulSet is deleted. Preserve it across experiments. Removing the cache
requires first removing the worker mirror configuration (and reloading Docker).
For the pilot, restore the previous daemon configuration before reloading it.

References: [Distribution pull-through caching](https://distribution.github.io/distribution/recipes/mirror/)
and [Docker reloadable options](https://docs.docker.com/reference/cli/dockerd/#configuration-reload-behavior).
