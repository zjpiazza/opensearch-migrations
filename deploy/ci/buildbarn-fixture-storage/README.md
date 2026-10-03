# Approved fixture cache capacity (2026-10-03)

The former CAS was 8 GiB on a 10-GiB PVC. The pinned fixture inputs already exceed
that cache capacity before the complete 64-version matrix and its outputs fit.

Approved and applied: expand `cas-storage-0` from 10 GiB to 64 GiB, then use 48 GiB for
CAS blocks. Retain the old 8-GiB block file and old key map/state for rollback;
new files use the `_fixtures_v1` suffix. AC/FSAC and all worker/node limits stay
unchanged. This adds 54 GiB billed block storage; PVC capacity cannot be shrunk.
The PVC reports 64Gi capacity and the storage StatefulSet is ready. Its existing
immutable volumeClaimTemplate still says 10Gi; the live claim was resized
explicitly. These instructions update an existing cluster, not a fresh install.

Applied commands (only repeat between builds/tests when needed):

```bash
kubectl --context do-atl1-bazel -n migrations-buildbarn patch pvc cas-storage-0 \
  --type=merge -p '{"spec":{"resources":{"requests":{"storage":"64Gi"}}}}'
# Confirm capacity is 64Gi before switching storage configuration.
kubectl --context do-atl1-bazel apply -k deploy/ci/buildbarn-fixture-storage
kubectl --context do-atl1-bazel -n migrations-buildbarn patch statefulset storage \
  --type=strategic --patch-file deploy/ci/buildbarn-fixture-storage/storage-patch.json
kubectl --context do-atl1-bazel -n migrations-buildbarn rollout status statefulset/storage
```

Capture the previous storage StatefulSet before patching. Rollback restores its
`configs` ConfigMap reference and init-container command, selecting the original
CAS files. The expanded PVC persists even after configuration rollback. Existing
AC entries whose blobs were in the old CAS will miss until rebuilt/reuploaded;
retaining the old files preserves rollback, not warm reuse across the two stores.
Only this storage StatefulSet is patched; do not reapply the full worker overlay.
