#!/usr/bin/env python3
"""Refresh declared fingerprints before EVERY integration experiment invocation.

Build project images first. This conservative bridge fingerprints all tracked
source files, image manifests and host tools. It does not make runtime chart
downloads hermetic, and cannot replace building images as Bazel dependencies.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[4]


def output(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def main():
    source_hash = hashlib.sha256()
    for name in sorted(output("git", "ls-files", "-z").split("\0")):
        path = ROOT / name
        if name and not name.startswith("tools/build/bazel/") and path.is_file():
            source_hash.update(name.encode() + b"\0" + path.read_bytes() + b"\0")
    stamp = ROOT / "build/bazel-integration/built-source.sha256"
    if "--record-build" in sys.argv:
        # Call only after a successful Gradle image build, with no concurrent
        # product edits. Subsequent preparation refuses stale product images.
        stamp.write_text(source_hash.hexdigest())
    if not stamp.exists() or stamp.read_text() != source_hash.hexdigest():
        raise SystemExit("Rebuild the integration images, then prepare.py --record-build; source changed.")
    images = {}
    for name, tag in [
        ("migration_console", "latest"),
        ("reindex_from_snapshot", "latest"),
        ("capture_proxy", "latest"),
        ("traffic_replayer", "latest"),
        ("custom-elasticsearch", "8.19.14"),
        ("custom-elasticsearch", "7.10.2"),
    ]:
        req = urllib.request.Request(
            f"http://localhost:5017/v2/migrations/{name}/manifests/{tag}",
            headers={
                "Accept": "application/vnd.oci.image.index.v1+json, "
                "application/vnd.docker.distribution.manifest.list.v2+json, "
                "application/vnd.docker.distribution.manifest.v2+json"
            },
        )
        with urllib.request.urlopen(req) as response:
            images[name + ":" + tag] = "sha256:" + hashlib.sha256(response.read()).hexdigest()
    kind = ROOT / "build/bazel-integration/tools/kind"
    tools = {name: shutil.which(name) for name in ["docker", "kubectl", "helm"]}
    tools["kind"] = str(kind)
    assert all(tools.values()), tools
    docker_host = os.environ.get("DOCKER_HOST") or output(
        "docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"
    )
    runtime = {
        "source_sha256": source_hash.hexdigest(),
        "images": images,
        "tools_sha256": {name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name, path in tools.items()},
        "kind": str(kind),
        "docker_host": docker_host,
        "tool_path": os.pathsep.join(dict.fromkeys(str(Path(p).parent) for p in tools.values())) + ":/usr/bin:/bin",
        "docker_version": output("docker", "version", "--format", "{{.Server.Version}}"),
        "kernel": os.uname().release,
        "data_filesystem": {
            "type": output("stat", "-f", "-c", "%T", "/tmp"),
            "capacity_bytes": shutil.disk_usage("/tmp").total,
        },
        "node_image": "kindest/node:v1.35.1@sha256:05d7bcdefbda08b4e038f644c4df690cdac3fba8b06f8289f30e10026720a1ab",
        "cache_scope": "same-session experiment; runtime Helm charts and third-party tags remain unpinned",
    }
    path = ROOT / "tools/build/bazel/integration/runtime.json"
    path.write_text(json.dumps(runtime, indent=2, sort_keys=True) + "\n")
    print(path)


if __name__ == "__main__":
    main()
