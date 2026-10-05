"""Run the existing ES8 backfill test in a disposable kind cluster.

Use prepare.py before each invocation. The cache experiment measures only
same-session reuse; runtime-fetched Helm charts/images are not hermetic yet.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def main():
    root = Path(os.environ["TEST_SRCDIR"]) / os.environ["TEST_WORKSPACE"]
    runtime = json.loads((root / "tools/build/bazel/integration/runtime.json").read_text())
    scenario = json.loads((root / "tools/build/bazel/integration/scenario.json").read_text())
    output = Path(os.environ["TEST_UNDECLARED_OUTPUTS_DIR"])
    output.mkdir(parents=True, exist_ok=True)
    (output / "reports").mkdir(parents=True, exist_ok=True)
    scratch = Path(os.environ["TEST_TMPDIR"])
    cluster = "ma-bazel-" + uuid.uuid4().hex[:10]
    os.environ["KUBECONFIG"] = str(scratch / "kubeconfig")
    os.environ["DOCKER_HOST"] = runtime["docker_host"]
    os.environ["PATH"] = runtime["tool_path"]
    # Kubernetes captures KUBECONFIG when its module is imported.
    from testAutomation import test_runner

    kind = runtime["kind"]
    # A fresh filesystem avoids host disk-percentage watermarks preventing ES8
    # shard allocation. /tmp is a separate tmpfs on the benchmark host.
    data_dir = Path(tempfile.mkdtemp(prefix="ma-bazel-data-", dir="/tmp"))
    for name in ["kubelet", "volumes"]:
        (data_dir / name).mkdir()
    kind_config = scratch / "kind.yaml"
    config_text = (root / "tools/build/bazel/integration/kind.yaml").read_text()
    config_text = config_text.replace(
        "  - role: control-plane",
        "  - role: control-plane\n"
        "    extraMounts:\n"
        f"      - hostPath: {data_dir / 'kubelet'}\n"
        "        containerPath: /var/lib/kubelet/pods\n"
        f"      - hostPath: {data_dir / 'volumes'}\n"
        "        containerPath: /var/local-path-provisioner",
    )
    kind_config.write_text(config_text)
    start = time.monotonic()
    try:
        run(
            kind,
            "create",
            "cluster",
            "--name",
            cluster,
            "--kubeconfig",
            os.environ["KUBECONFIG"],
            "--image",
            runtime["node_image"],
            "--config",
            str(kind_config),
        )
        node = cluster + "-control-plane"
        # Keep kubelet's root on the normal disk. Mounting its whole root on
        # tmpfs advertises only 31 GiB and cannot schedule RFS's 200 GiB request.
        from kubernetes.utils.quantity import parse_quantity

        capacity = run(
            "kubectl",
            "get",
            "nodes",
            "-o",
            "jsonpath={.items[0].status.allocatable.ephemeral-storage}",
            capture_output=True,
        ).stdout
        assert parse_quantity(capacity) >= 200 * 1024**3, capacity
        run("docker", "network", "connect", "migrations-bazel-benchmark", node)
        certs = "/etc/containerd/certs.d/docker-registry:5000"
        run("docker", "exec", node, "mkdir", "-p", certs)
        run(
            "docker",
            "exec",
            "-i",
            node,
            "cp",
            "/dev/stdin",
            certs + "/hosts.toml",
            input='server = "http://docker-registry:5000"\n',
        )
        os.chdir(root / "tests/automation")
        sys.argv = [
            "test_runner",
            "--source-version=" + scenario["source_version"],
            "--target-version=" + scenario["target_version"],
            "--test-ids=" + scenario["test_ids"],
            "--registry-prefix=docker-registry:5000/",
            "--kube-context=kind-" + cluster,
            "--capture-proxy-service-type=ClusterIP",
            "--test-reports-dir=" + str(output / "reports"),
            "--skip-delete",
        ]
        # skip-delete avoids redundant Helm teardown; finally removes the entire
        # private cluster, including CRDs, volumes and namespaces.
        test_runner.main()
        reports = list((output / "reports").glob("*.json"))
        assert len(reports) == 1, reports
        report = json.loads(reports[0].read_text())
        assert report["summary"]["passed"] == 1, report
        assert report["summary"]["failed"] == 0, report
    finally:
        try:
            run(kind, "export", "logs", str(output / "cluster-logs"), "--name", cluster)
        finally:
            run(kind, "delete", "cluster", "--name", cluster, "--kubeconfig", os.environ["KUBECONFIG"])
            # Data can be owned by subordinate UIDs from the rootless node.
            # Use the same user namespace to clean only this fresh directory.
            run(
                "docker",
                "run",
                "--rm",
                "--network=none",
                "--entrypoint=/bin/sh",
                "--mount",
                f"type=bind,src={data_dir},dst=/benchmark-data",
                runtime["node_image"],
                "-c",
                "find /benchmark-data -mindepth 1 -delete",
            )
            data_dir.rmdir()
            (output / "timing.json").write_text(json.dumps({"wall_seconds": time.monotonic() - start}))


if __name__ == "__main__":
    main()
