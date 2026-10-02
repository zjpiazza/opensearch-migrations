#!/usr/bin/env bash
# Run as root on a dedicated Ubuntu 24.04 VM. Register the runner separately.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl git git-lfs \
    jq openjdk-21-jdk-headless python3 unzip zip xz-utils libicu74 build-essential
id runner >/dev/null 2>&1 || useradd --create-home --shell /bin/bash runner
install -d -o runner -g runner /home/runner/actions-runner /home/runner/bazel-state

if [[ ! -x /home/runner/actions-runner/bin/Runner.Listener ]]; then
    archive=$(mktemp)
    trap 'rm -f "$archive"' EXIT
    curl -fsSL https://github.com/actions/runner/releases/download/v2.337.0/actions-runner-linux-x64-2.337.0.tar.gz -o "$archive"
    echo "70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613  $archive" | sha256sum --check
    tar -xzf "$archive" -C /home/runner/actions-runner
    chown -R runner:runner /home/runner/actions-runner
fi
curl -fsSL https://releases.bazel.build/8.4.2/release/bazel-8.4.2-linux-x86_64 -o /usr/local/bin/bazel
echo '4dc8e99dfa802e252dac176d08201fd15c542ae78c448c8a89974b6f387c282c  /usr/local/bin/bazel' | sha256sum --check
chmod 755 /usr/local/bin/bazel

cat > /home/runner/.bazelrc <<'BAZELRC'
startup --output_user_root=/home/runner/bazel-state
startup --output_base=/home/runner/bazel-state/output
startup --max_idle_secs=0
build --repository_cache=/home/runner/bazel-state/repository-cache
build --disk_cache=/home/runner/bazel-state/disk-cache
build --spawn_strategy=local
build --strategy=Javac=worker
build --worker_max_instances=Javac=1
BAZELRC
chown runner:runner /home/runner/.bazelrc

workspace=/home/runner/actions-runner/_work/opensearch-migrations/opensearch-migrations
if [[ ! -d "$workspace/.git" ]]; then
    runuser -u runner -- git clone --depth=1 --single-branch \
        --branch experimental \
        https://github.com/zjpiazza/opensearch-migrations.git "$workspace"
fi

# Start Bazel outside any job's process cleanup scope; the output base and
# workspace must match those used by actions/checkout and the benchmark.
cat > /etc/systemd/system/bazel-warm.service <<'UNIT'
[Unit]
Description=Persistent Bazel server for the CI experiment
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
User=runner
Group=runner
Environment=HOME=/home/runner
WorkingDirectory=/home/runner/actions-runner/_work/opensearch-migrations/opensearch-migrations
ExecStart=/usr/local/bin/bazel info server_pid
ExecStop=/usr/local/bin/bazel shutdown
TimeoutStartSec=120
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now bazel-warm.service
echo 'Installation complete. Register the runner, then install its service as user runner.'
