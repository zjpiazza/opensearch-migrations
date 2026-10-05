FROM buildbarn-image-cache.migrations-buildbarn.svc.cluster.local:5000/library/amazonlinux@sha256:2851878b108218cccbe7af6ab7dfb87a5883a725623384e19e6256f4072027a3
RUN dnf install -y --allowerasing tar gzip findutils curl && dnf clean all
