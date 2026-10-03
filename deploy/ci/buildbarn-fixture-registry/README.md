# Publish prepared fixture images into the existing registry

This overlay retains the existing 50-GiB registry PVC, prepared public images,
service address, and disabled upstream egress. It enables normal registry writes
so independently built Bazel fixtures can be published under `fixtures/`.
It adds no worker, node, or volume.

Apply between test runs with `kubectl --context do-atl1-bazel apply -k
 deploy/ci/buildbarn-fixture-registry`. Verify registry readiness before publishing.
Reapplying `buildbarn-image-snapshot` disables writes without deleting artifacts.
Do not apply the base pull-through overlay: proxy mode cannot accept fixture pushes.
