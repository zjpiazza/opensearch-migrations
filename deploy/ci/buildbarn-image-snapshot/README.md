# Serve a prepared image snapshot without Docker Hub revalidation

A pull-through cache still checks upstream when a client requests a mutable tag.
Forty private Docker daemons can therefore exhaust anonymous pull quotas even
after blobs are cached. After `prewarm-images.py` completes successfully, this
overlay serves the same retained filesystem as a read-only ordinary registry,
with no proxy configured and no public HTTPS egress permission for the registry.
Existing namespace-local and DNS access remain permitted by the base policy.

```bash
kubectl --context do-atl1-bazel apply -k deploy/ci/buildbarn-image-snapshot
kubectl --context do-atl1-bazel -n migrations-buildbarn rollout status statefulset/buildbarn-image-cache
```

Before timing tests, verify every prepared tag resolves to its recorded amd64
manifest and that a fresh worker can actually pull and start an image. A missing
image is not magically cached: Docker's mirror fallback can still contact Hub.
This is an explicit benchmark snapshot, not a continuously refreshing registry.
The preparation report records its provenance, but test-result cache safety still
requires image digests to be declared inputs in a future change.

To refresh, reapply `deploy/ci/buildbarn/image-cache`, run preparation into a new
report, then reapply this snapshot overlay. Do this between benchmarks. Applying
the unified-worker overlay also restores pull-through mode; apply snapshot mode
last after preparation. Preserve the 50-GiB registry PVC in both modes.

Source: [Distribution's tag revalidation behavior](https://distribution.github.io/distribution/recipes/mirror/).
