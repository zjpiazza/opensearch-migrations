#!/usr/bin/env python3
"""Run Jenkins deployment E2E jobs natively in GitHub Actions.

This intentionally does not call Jenkins. It translates repository-local Jenkins
shared-library commands where they are already explicit. Live AWS jobs fail
closed until their shared-library stages are translated one-for-one.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "build/ci-comparison/jenkins-native"

LOCAL_KIND = {
    "k8s-local-elasticsearch1x-test": ("ES_1.5", "OS_3.1", "0001,0002,0003"),
    "k8s-local-elasticsearch2x-test": ("ES_2.4", "OS_3.1", "0001,0002,0003"),
    "k8s-local-elasticsearch5x-test": ("ES_5.6", "OS_3.1", "0001,0002,0003,0004,0005"),
    "k8s-local-elasticsearch6x-test": ("ES_6.8", "OS_3.1", "0001,0002,0003,0006"),
    "k8s-local-elasticsearch7x-test": ("ES_7.10", "OS_3.1", "0001,0002,0003,0006,0008,0020"),
    "k8s-local-elasticsearch8x-test": ("ES_8.19", "OS_3.1", "0001,0002,0003,0020,0035,0040"),
    "k8s-local-opensearch1x-test": ("OS_1.3", "OS_3.1", "0001,0002,0003"),
    "k8s-local-solr8x-test": ("SOLR_8.11", "OS_2.19", "0071,0070"),
    "k8s-local-solr-other-test": ("SOLR_9.8", "OS_2.19", "0071,0070"),
}

DOCKER_COMPOSE = {"docker-compose-e2e-test"}

AWS_JOBS = {
    "full-es68-e2e-aws-test",
    "eks-integ-test",
    "eks-aoss-integ-test",
    "eks-byos-integ-test",
    "eks-cdc-full-e2e-test",
    "eks-cdc-aoss-e2e-test",
    "eks-cdc-k6-load-test",
    "eks-cfn-create-vpc-test",
    "eks-cfn-import-vpc-test",
    "eks-full-e2e-isolated-vpc-test",
}

ALL_JOBS = [*LOCAL_KIND.keys(), *DOCKER_COMPOSE, *AWS_JOBS]


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Runner:
    def __init__(self, job, backend, trial):
        self.job = job
        self.backend = backend
        self.trial = trial
        self.out = EVIDENCE / job
        self.out.mkdir(parents=True, exist_ok=True)
        self.steps = []

    def record(self, name, start, code):
        item = {
            "job": self.job,
            "backend": self.backend,
            "trial": self.trial,
            "step": name,
            "seconds": round(time.monotonic() - start, 3),
            "exit_code": code,
            "timestamp_utc": now(),
        }
        self.steps.append(item)
        (self.out / "timings.json").write_text(json.dumps(self.steps, indent=2) + "\n")
        print(json.dumps(item, sort_keys=True), flush=True)

    def run(self, name, command, cwd=ROOT, env=None, check=True):
        print(f"::group::{name}", flush=True)
        print("+ " + " ".join(map(str, command)), flush=True)
        start = time.monotonic()
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        with (self.out / f"{name}.log").open("w") as log:
            proc = subprocess.Popen(
                list(map(str, command)),
                cwd=cwd,
                env=merged_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                print(line, end="")
                log.write(line)
            code = proc.wait()
        self.record(name, start, code)
        print("::endgroup::", flush=True)
        if check and code:
            raise subprocess.CalledProcessError(code, command)
        return code

    def shell(self, name, script, cwd=ROOT, env=None, check=True):
        return self.run(name, ["bash", "-lc", script], cwd=cwd, env=env, check=check)


def write_summary(runner, status, error=None):
    payload = {
        "job": runner.job,
        "backend": runner.backend,
        "trial": runner.trial,
        "status": status,
        "error": error,
        "timestamp_utc": now(),
        "steps": runner.steps,
    }
    (runner.out / "summary.json").write_text(json.dumps(payload, indent=2) + "\n")


def ensure_tool(name):
    if shutil.which(name) is None:
        raise RuntimeError(f"Required tool is not on PATH: {name}")


def setup_kind_host(r):
    r.shell("configure-kind-host", "./tools/ci/jenkins/configureKindHost.sh")
    r.shell("install-kind", 'KIND_INSTALL_DIR="$PWD/.ci-bin" ./tools/ci/jenkins/installKind.sh')
    r.shell("recreate-kind", r'''
        set -euo pipefail
        export WORKSPACE="$PWD"
        export KIND_VERSION="${KIND_VERSION:-v0.31.0}"
        export KIND_NODE_IMAGE="${KIND_NODE_IMAGE:-kindest/node:v1.35.1@sha256:05d7bcdefbda08b4e038f644c4df690cdac3fba8b06f8289f30e10026720a1ab}"
        . ./tools/build/images/backends/dockerHostedBuildkit.sh
        teardown_registry_container || true
        "$WORKSPACE/.ci-bin/kind" delete cluster --name ma || true
        "$WORKSPACE/.ci-bin/kind" create cluster --name ma --config ./deploy/kubernetes/kindClusterConfigSingleNode.yaml --image "$KIND_NODE_IMAGE"
        ECR_PULL_THROUGH_ENDPOINT="${ECR_PULL_THROUGH_ENDPOINT:-}" \
          KIND_BIN="$WORKSPACE/.ci-bin/kind" \
          KIND_CLUSTER_NAME=ma \
          ./tools/ci/jenkins/configureKindCluster.sh
    ''')


def build_kind_images(r, test_ids):
    load_target = " :buildImages:buildKitLoadTestAll_amd64" if any(
        part.strip().startswith("008") for part in test_ids.split(",")
    ) else ""
    r.shell("build-kind-images", f'''
        set -euo pipefail
        export WORKSPACE="$PWD"
        kubectl config unset current-context || true
        . ./tools/build/images/backends/dockerHostedBuildkit.sh
        KUBE_CONTEXT=kind-ma setup_build_backend
        kind_nodes=()
        while IFS= read -r node; do
          [ -n "$node" ] && kind_nodes+=("$node")
        done < <("$WORKSPACE/.ci-bin/kind" get nodes --name ma)
        connect_cluster_to_registry_network kind "${{kind_nodes[@]}}"
        pull_arg=""
        if [ -n "${{ECR_PULL_THROUGH_ENDPOINT:-}}" ]; then
          pull_arg="-PpullThroughCacheEndpoint=${{ECR_PULL_THROUGH_ENDPOINT}}"
        fi
        ./gradlew :buildImages:buildImagesToRegistry_amd64 :buildImages:buildKitTestAll_amd64{load_target} \
          -Pbuilder=builder-kind-ma -PregistryEndpoint=localhost:5001 \
          -x test --info --stacktrace --profile $pull_arg
    ''', env={"OS_MIGRATIONS_GRADLE_SCAN_TOS_AGREE_AND_ENABLED": ""})


def run_local_kind(r):
    source, target, test_ids = LOCAL_KIND[r.job]
    setup_kind_host(r)
    build_kind_images(r, test_ids)
    try:
        source_arg = source.replace(",", " ")
        r.shell("python-e2e", f'''
            set -euo pipefail
            cd tests/automation
            pipenv install --deploy
            mkdir -p ./reports
            kubectl config unset current-context || true
            pipenv run app \
              --source-version {source_arg} \
              --target-version={target} \
              --test-ids='{test_ids}' \
              --test-reports-dir='./reports' \
              --copy-logs \
              --registry-prefix='docker-registry:5001/' \
              --kube-context=kind-ma \
              --capture-proxy-service-type=ClusterIP
        ''')
    finally:
        r.shell("cleanup-local-kind", r'''
            set +e
            cd tests/automation
            pipenv install --deploy
            kubectl config unset current-context || true
            if kubectl config get-contexts -o name | grep -qx kind-ma; then
              pipenv run app --delete-only --kube-context=kind-ma
            fi
        ''', check=False)


def run_docker_compose(r):
    r.shell("install-docker-compose", r'''
        set -euo pipefail
        PLUGIN_DIR="$HOME/.docker/cli-plugins"
        mkdir -p "$PLUGIN_DIR"
        if ! docker compose version >/dev/null 2>&1; then
          ARCH="$(uname -m)"
          curl -fsSL -o "$PLUGIN_DIR/docker-compose" "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-${ARCH}"
          chmod +x "$PLUGIN_DIR/docker-compose"
        fi
        docker compose version
    ''')
    try:
        r.shell("build-docker-images", r'''
            set -euo pipefail
            ./deploy/distributions/aws-cdk/opensearch-service-migration/buildDockerImages.sh
        ''')
        r.shell("docker-compose-up", "./gradlew -p TrafficCapture dockerSolution:composeUp -x test -x spotlessCheck --info --stacktrace && docker ps")
        r.shell("docker-compose-e2e", "docker exec $(docker ps --filter 'name=migration-console' -q) pipenv run pytest /root/lib/integ_test/integ_test/replayer_tests.py --unique_id='testindex' -s")
    finally:
        r.shell("docker-compose-logs-and-down", r'''
            set +e
            mkdir -p logs/docker
            for container in $(docker ps -aq); do
              container_name=$(docker inspect --format '{{.Name}}' "$container" | sed 's#^/##')
              docker logs "$container" > "logs/docker/${container_name}_logs.txt" 2>&1 || true
            done
            ./gradlew -p TrafficCapture dockerSolution:composeDown -x test -x spotlessCheck || true
        ''', check=False)


def run_aws_job(r):
    ensure_tool("aws")
    r.run("aws-caller-identity", ["aws", "sts", "get-caller-identity"])
    raise RuntimeError(
        "Native GitHub Actions translation for AWS Jenkins job "
        f"{r.job!r} is not complete yet. This scaffold runs all local-kind and "
        "docker-compose Jenkins jobs without Jenkins, and fails closed for live "
        "AWS deployment jobs until their Jenkins shared-library stages are "
        "translated one-for-one."
    )


def list_jobs(args):
    jobs = [
        {"job": j, "environment": "local-kind" if j in LOCAL_KIND else "local-docker-compose" if j in DOCKER_COMPOSE else "aws"}
        for j in ALL_JOBS
    ]
    if args.format == "json":
        print(json.dumps({"jobs": jobs}, indent=2))
    else:
        for job in jobs:
            print(job["job"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    p_list = sub.add_parser("list-jobs")
    p_list.add_argument("--format", choices=["text", "json"], default="text")
    p_run = sub.add_parser("run")
    p_run.add_argument("--job", required=True, choices=ALL_JOBS)
    p_run.add_argument("--backend", required=True)
    p_run.add_argument("--trial", default="jenkins-native")
    args = parser.parse_args()

    if args.command == "list-jobs":
        list_jobs(args)
        return 0
    if args.command != "run":
        parser.print_help()
        return 2

    r = Runner(args.job, args.backend, args.trial)
    try:
        if args.job in LOCAL_KIND:
            run_local_kind(r)
        elif args.job in DOCKER_COMPOSE:
            run_docker_compose(r)
        elif args.job in AWS_JOBS:
            run_aws_job(r)
        else:
            raise AssertionError(args.job)
        write_summary(r, "success")
        return 0
    except Exception as exc:
        write_summary(r, "failure", repr(exc))
        raise


if __name__ == "__main__":
    sys.exit(main())
