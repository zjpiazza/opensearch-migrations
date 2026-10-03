# Independently cached Elasticsearch fixtures (in progress)

This experiment extracts the Docker builds formerly performed by
`SearchClusterContainer` into per-version Bazel actions. The Gradle Dockerfile
remains the source of runtime behavior. `offline.py` replaces acquisition steps
with declared files and pinned dependency snapshots, failing if expected source
blocks change. Gradle's original build remains available.

The current pilot covers Elasticsearch 7.10.2. The integration-test consumer,
image publication, complete version matrix, cache-invalidation checks, and the
131-shard comparison are not complete yet. Do not interpret a successful image
build as completion of the experiment.

## Cache boundary

- `refresh_*` targets deliberately disable action caching. They install OS
  packages into six dependency snapshots (utilities, Alpine compiler, and four
  Corretto runtimes). Refreshing is an explicit maintenance operation.
- `toolchains.lock.json` records the resulting image IDs, archive SHA-256 values,
  package inventories, and recipe hashes. Fixture builds consume the frozen
  archive bytes; they do not rerun package managers. Refreshing a snapshot creates
  a new pin. Its original package repository is not asserted to be immutable.
- `fetch.py` explicitly records or verifies Elasticsearch and GCS-plugin download
  checksums in `downloads.lock.json`. Hash capture on first refresh is not a
  claim of independent vendor-signature verification.
- `materialize.py` verifies input bytes and creates `@fixture_images` with one
  `offline_fixture_image` target per version. Each action declares only its
  version's inputs and required toolchain snapshots, plus the shared recipe,
  compatibility source, and builder code. The Docker engine version is declared
  and verified as well; worker runner/tool images remain pinned in deployment.
- `build.py` uses `docker build --network=none --pull=false`, with locally loaded
  and verified toolchain images. It exports image bytes and a small identity
  manifest. Cached success therefore represents actual recoverable output bytes,
  not the side effect of creating a tag in one worker's Docker daemon.
- Inputs and outputs larger than 64 MiB are split into CAS objects. Reassembly
  preserves and checks the full artifact SHA-256. This avoids the existing
  Buildbarn block-size limit without resizing or clearing shared storage.

Image publication will be a separate operation; it must restore or verify the
registry artifacts even when the build action is a cache hit. Tests must verify
immutable image identity rather than trusting a mutable local Docker tag.

## Pilot preparation

Snapshot refresh targets use the existing `integration` execution platform.
Prepare an authenticated frontend tunnel as for the existing experiments:

```bash
./bazelw build --config=buildbarn \
  //tools/build/bazel/fixture-images:refresh_utilities \
  //tools/build/bazel/fixture-images:refresh_compiler8 \
  //tools/build/bazel/fixture-images:refresh_runtime8 \
  //tools/build/bazel/fixture-images:refresh_runtime11 \
  //tools/build/bazel/fixture-images:refresh_runtime17 \
  //tools/build/bazel/fixture-images:refresh_runtime21
python3 tools/build/bazel/fixture-images/fetch.py --refresh-lock 7.10
python3 tools/build/bazel/fixture-images/materialize.py \
  --snapshot-outputs bazel-bin/tools/build/bazel/fixture-images \
  --refresh-toolchain-lock
./bazelw build --config=buildbarn @fixture_images//:es_7_10
```

Do not refresh snapshots to reproduce an existing pin: the package repositories
can change. Distribution downloads can be re-fetched using the committed lock
without `--refresh-lock`. Durable distribution of the pinned toolchain archives
is still to be implemented; current archives are in ignored local experiment
storage and the remote cache.

## Verification remaining

Pilot cache behavior has been verified from fresh clients: a cache hit survives
an unrelated Java-test edit, while a Dockerfile change executes the build and
changes image identity. See E036 for retained execution evidence.

1. Start the resulting Elasticsearch fixture and run a real existing test.
2. Repeat cache validation at the complete version-matrix scale.
3. Integrate publication and test loading, including a worker with no local image.
4. Extend the pins to all versions needed by the same 16 classes / 131 shards.
5. Execute all 756 cases freshly with build caches enabled, recording preparation
   separately and comparing against 1,024.007 seconds.
6. Restore documented minimum execution capacity after measurement.

The live CAS currently has only 8 GiB of configured storage on a 10-GiB PVC.
Check retention under the full image matrix before claiming cache reuse at that
scale. Registry storage is a separate existing 50-GiB PVC.
