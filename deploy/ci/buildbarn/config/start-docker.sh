#!/bin/sh
# Keep nested containers under this sidecar's Kubernetes CPU/memory ceilings.
set -eu
container_cgroup=$(awk -F: '$1 == "0" {print $3}' /proc/self/cgroup)
case "$container_cgroup" in
  /kubepods/*) ;;
  *) echo "Refusing unexpected cgroup: $container_cgroup" >&2; exit 1 ;;
esac
base="/sys/fs/cgroup$container_cgroup"
# cgroup v2 requires an empty parent before enabling domain controllers.
mkdir -p "$base/daemon"
while read -r process_id; do
  echo "$process_id" > "$base/daemon/cgroup.procs" 2>/dev/null || true
done < "$base/cgroup.procs"
printf '+cpu +memory +pids\n' > "$base/cgroup.subtree_control"
mkdir -p "$base/children"
set --
if [ -n "${DOCKER_REGISTRY_MIRROR:-}" ]; then
  set -- --registry-mirror="$DOCKER_REGISTRY_MIRROR" \
    --insecure-registry="${DOCKER_REGISTRY_MIRROR#http://}"
fi
exec dockerd --host=tcp://127.0.0.1:2375 --host=unix:///var/run/docker.sock \
  --storage-driver=overlay2 --log-level=warn \
  --exec-opt=native.cgroupdriver=cgroupfs \
  --cgroup-parent="$container_cgroup/children" "$@"
