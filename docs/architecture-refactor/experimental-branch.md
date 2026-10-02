# Experimental integration branch

The fork's `experimental` branch combines the repository reorganization, Bazel,
WireMock, persistent VM runner, and Buildbarn experiments. It is the working
baseline for further experiments; fork `main` and upstream remain unchanged.

| Original work | Included head | Pull request |
| --- | --- | --- |
| Bazel caching and mock integration | `237e2b11b` | [#1](https://github.com/zjpiazza/opensearch-migrations/pull/1) |
| WireMock destination tests | `1cdb85a22` | [#2](https://github.com/zjpiazza/opensearch-migrations/pull/2) |
| Persistent VM runner | `d42308b0d` | [#3](https://github.com/zjpiazza/opensearch-migrations/pull/3) |
| Repository layout | `c172aa63f` | [#4](https://github.com/zjpiazza/opensearch-migrations/pull/4) |
| Buildbarn, worker configuration, long-test sharding | `8b8e4bb3d` | No separate PR |

The starting Buildbarn head already contains the WireMock and layout branches.
Merge `0acb08629` incorporates the VM branch; merge `ce869cd29` incorporates the
original Bazel branch. All five heads are ancestors of the consolidated branch.
Original branches remain available for historical comparisons. The abandoned GKE
branch is not part of this consolidation.

## Conflict resolution

- Kept the accepted `apps/`, `libs/`, `deploy/`, `tests/`, and `tools/` layout.
  VM tools live in `deploy/ci/vm`; earlier Bazel tools move from `build-support`
  into `tools/build/bazel`. Updated source paths and Bazel labels while retaining
  the existing Gradle project IDs.
- Combined the mock/Python and Java test targets with WireMock and Buildbarn
  settings. Kept the newer Maven lock, which contains all incoming artifacts;
  regenerated module metadata through Bazel dependency analysis.
- Retained historical benchmark JSON unchanged, including its original paths.
  These records describe their original commits, not a new measurement.
- VM installation now clones `experimental`. Its workflow is manually triggered
  so consolidation does not automatically run the older short-test benchmark.
  The original Bazel PR workflow retains its pull-request/manual triggers.

## Validation and limits

- All files from the incoming Bazel and VM branches survive under the move map.
- Repository layout checker passes: 55 moves and 56 Gradle project mappings.
- Dependency checker passes against Gradle and both Pipenv locks.
- Python syntax, workflow YAML parsing, shell syntax, and whitespace checks pass.
- Bazel 8.4.2 query and `build --nobuild //:bazel_poc_tests //:wiremock_tests`
  succeed: 25 targets analyzed, zero actions executed.

No full suite or short-test benchmark was rerun for consolidation. The active
uncached benchmark remains in its original Buildbarn worktree. Existing Docker
OOM failures and npm input-upload failures are not fixed by merging. Remote
performance validation of the new long-test sharding remains pending.

## Ongoing workflow

Continue experiments on `experimental`. Use short-lived branches only when
isolation or review helps, base them on `experimental`, and merge completed work
back there. Record each change and its evidence in the journal. Extract focused
RFCs and upstream PRs from this record once measurements justify them; merging
into this experimental branch does not imply upstream readiness.

For comparisons or rollback, use the recorded heads in a separate worktree.
Do not rewrite the integrated history or delete historical evidence.
