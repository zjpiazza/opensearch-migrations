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

ROOT = Path(os.environ.get("BUILD_WORKSPACE_DIRECTORY", Path(__file__).resolve().parents[2])).resolve()
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

DOCKER_COMPOSE = ["docker-compose-e2e-test"]

AWS_JOBS = [
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
]

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
            export PYTHONPATH="$PWD/testAutomation${PYTHONPATH:+:$PYTHONPATH}"
            unset PYTHONSAFEPATH
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
            export PYTHONPATH="$PWD/testAutomation${PYTHONPATH:+:$PYTHONPATH}"
            unset PYTHONSAFEPATH
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
        r.shell("docker-compose-up", "./gradlew :TrafficCapture:dockerSolution:composeUp -x test -x spotlessCheck --info --stacktrace && docker ps")
        r.shell("docker-compose-e2e", "docker exec $(docker ps --filter 'name=migration-console' -q) pipenv run pytest /root/lib/integ_test/integ_test/replayer_tests.py --unique_id='testindex' -s")
    finally:
        r.shell("docker-compose-logs-and-down", r'''
            set +e
            mkdir -p logs/docker
            for container in $(docker ps -aq); do
              container_name=$(docker inspect --format '{{.Name}}' "$container" | sed 's#^/##')
              docker logs "$container" > "logs/docker/${container_name}_logs.txt" 2>&1 || true
            done
            ./gradlew :TrafficCapture:dockerSolution:composeDown -x test -x spotlessCheck || true
        ''', check=False)


def account_id():
    return subprocess.check_output([
        "aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"
    ], text=True, cwd=ROOT).strip()


def stage_name(default):
    override = os.environ.get("CI_COMPARISON_STAGE")
    if override:
        return override
    suffix = os.environ.get("CI_COMPARISON_STAGE_SUFFIX")
    if not suffix:
        run = os.environ.get("GITHUB_RUN_NUMBER") or os.environ.get("GITHUB_RUN_ID") or str(int(time.time()))
        attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
        suffix = f"p{run}-{attempt}"
    return f"{default}-{suffix}"


def gradle_build(r):
    r.shell("gradle-build-no-tests", "./gradlew clean build -x test --no-daemon --stacktrace --profile",
            env={"OS_MIGRATIONS_GRADLE_SCAN_TOS_AGREE_AND_ENABLED": ""})


def bootstrap(r, build=True, skip_test_images=True, use_general_node_pool=True, load_test_images=False):
    r.shell("assemble-bootstrap", "./deploy/aws/assemble-bootstrap.sh")
    flags = ["--base-dir \"$(pwd)\""]
    if build:
        flags.append("--build")
        if skip_test_images:
            flags.append("--skip-test-images")
        if load_test_images:
            flags.append("--with-load-test-images")
    else:
        flags.append("--version latest")
    if use_general_node_pool:
        flags.append("--use-general-node-pool")
    return {"script": "./deploy/aws/dist/aws-bootstrap.sh", "flags": " ".join(flags)}


def parse_exports_file(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def bootstrap_ma(r, stack_name, stage, region, bootstrap_info, kubectl_context,
                 vpc_id=None, subnet_ids=None, create_vpc_endpoints=False,
                 ma_images_source=None, resource_tags=None, enforce_tags=False,
                 tls_mode=None, use_import_vpc=False):
    acct = account_id()
    deploy_flag = "--deploy-import-vpc-cfn" if (vpc_id or use_import_vpc) else "--deploy-create-vpc-cfn"
    vpc_flags = f"--vpc-id {vpc_id} --subnet-ids {subnet_ids}" if vpc_id else ""
    endpoint_flag = "--create-vpc-endpoints" if create_vpc_endpoints else ""
    image_flag = f"--ma-images-source {ma_images_source}" if ma_images_source else ""
    tag_flag = f"--tags '{resource_tags}'" if resource_tags else ""
    enforce_flag = "--enforce-tags-on-create-for-tests" if enforce_tags else ""
    tls_flag = f"--tls-mode {tls_mode}" if tls_mode else ""
    r.shell("bootstrap-ma", f'''
        set -euo pipefail
        {bootstrap_info["script"]} \
          {deploy_flag} \
          --stack-name "{stack_name}" \
          --stage "{stage}" \
          --eks-access-principal-arn "arn:aws:iam::{acct}:role/JenkinsDeploymentRole" \
          {bootstrap_info["flags"]} \
          {tls_flag} \
          {vpc_flags} \
          {endpoint_flag} \
          {image_flag} \
          {tag_flag} \
          {enforce_flag} \
          --skip-console-exec \
          --skip-setting-k8s-context \
          --kubectl-context "{kubectl_context}" \
          --region "{region}"
        raw=$(aws cloudformation describe-stacks \
          --stack-name "{stack_name}" \
          --query "Stacks[0].Outputs[?OutputKey=='MigrationsExportString'].OutputValue" \
          --output text \
          --region "{region}")
        printf '%s\n' "$raw" | tr ';' '\n' | sed -e 's/^export //' -e '/^$/d' > "{r.out / "ma-exports.env"}"
        aws eks update-kubeconfig --name "$(grep '^MIGRATIONS_EKS_CLUSTER_NAME=' "{r.out / "ma-exports.env"}" | cut -d= -f2-)" \
          --region "{region}" --alias "{kubectl_context}" || true
    ''')
    exports = parse_exports_file(r.out / "ma-exports.env")
    (r.out / "ma-exports.json").write_text(json.dumps(exports, indent=2) + "\n")
    return exports


def sigv4_policy(acct):
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": f"arn:aws:iam::{acct}:root"},
            "Action": "es:*",
            "Resource": "*",
        }],
    }


def deploy_clusters(r, stage, context_name, clusters, region="us-east-1", vpc_id=None, vpc_subnet_ids=None):
    ctx = {"stage": stage, "clusters": clusters}
    if vpc_id:
        ctx["vpcId"] = vpc_id
        if vpc_subnet_ids:
            ctx["vpcSubnetIds"] = vpc_subnet_ids
    else:
        ctx["vpcAZCount"] = 2
    if isinstance(vpc_subnet_ids, str) and "," in vpc_subnet_ids:
        ctx["vpcSubnetIds"] = [s.strip() for s in vpc_subnet_ids.split(",") if s.strip()]
    context_rel = Path("tmp") / context_name
    context_path = ROOT / "tests/e2e" / context_rel
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(json.dumps(ctx, indent=2) + "\n")
    vpc_arg = f"--vpc-id {vpc_id}" if vpc_id else ""
    r.shell("deploy-clusters", f'./awsDeployCluster.sh --stage "{stage}" --context-file "{context_rel.as_posix()}" {vpc_arg}',
            cwd=ROOT / "tests/e2e")
    details = json.loads((ROOT / "tests/e2e/tmp" / f"cluster-details-{stage}.json").read_text())
    (r.out / "cluster-details.json").write_text(json.dumps(details, indent=2) + "\n")
    return details, context_rel.as_posix()


def expand_version(value):
    prefix, version = value.split("_", 1)
    major, minor = version.split(".", 1)
    name = {"ES": "elasticsearch", "OS": "opensearch", "SOLR": "solr"}[prefix]
    return f"{name}-{major}-{minor}"


def apply_cluster_configmaps(r, kube_context, region, source_version=None, source=None, target_version=None, target=None):
    if source_version and source:
        cfg = {"endpoint": source["endpoint"], "allow_insecure": True,
               "sigv4": {"region": region, "service": "es"}, "version": source_version}
        p = r.out / "source-cluster-config.json"; p.write_text(json.dumps(cfg))
        r.shell("source-configmap", f'''
            kubectl --context="{kube_context}" create configmap source-{expand_version(source_version)}-migration-config \
              --from-file=cluster-config="{p}" --namespace ma --dry-run=client -o yaml | \
              kubectl --context="{kube_context}" apply -f -
        ''')
    if target_version and target:
        cfg = {"endpoint": target["endpoint"], "allow_insecure": True,
               "sigv4": {"region": region, "service": "es"}}
        p = r.out / "target-cluster-config.json"; p.write_text(json.dumps(cfg))
        r.shell("target-configmap", f'''
            kubectl --context="{kube_context}" create configmap target-{expand_version(target_version)}-migration-config \
              --from-file=cluster-config="{p}" --namespace ma --dry-run=client -o yaml | \
              kubectl --context="{kube_context}" apply -f -
        ''')


def run_automation(r, name, command, duration_seconds=3600):
    r.shell(name, f'''
        set -euo pipefail
        cd tests/automation
        pipenv install --deploy
        {command}
    ''')


def delete_stack(r, name, region, step):
    if not name:
        return
    r.shell(step, f'''
        set +e
        aws cloudformation describe-stacks --stack-name "{name}" --region "{region}" >/dev/null 2>&1 || exit 0
        aws cloudformation delete-stack --stack-name "{name}" --region "{region}" || true
        aws cloudformation wait stack-delete-complete --stack-name "{name}" --region "{region}" || true
    ''', check=False)


def cleanup_eks(r, region, ma_stack=None, cluster_stage=None, cluster_context=None, kube_context=None, extra_stacks=()):
    if kube_context:
        r.shell("cleanup-k8s-context", f'kubectl config delete-context "{kube_context}" || true', check=False)
    if ma_stack:
        delete_stack(r, ma_stack, region, "cleanup-ma-stack")
    if cluster_stage and cluster_context:
        r.shell("cleanup-cluster-stack", f'./awsDeployCluster.sh --stage "{cluster_stage}" --context-file "{cluster_context}" --destroy',
                cwd=ROOT / "tests/e2e", check=False)
    for i, stack in enumerate(extra_stacks):
        delete_stack(r, stack, region, f"cleanup-extra-stack-{i}")


def run_full_es68(r):
    region = os.environ.get("AWS_REGION", "us-east-1")
    stage = os.environ.get("CI_COMPARISON_FULL_ES68_STAGE", "full-es68")
    source_context = {
        "source-single-node-ec2": {
            "suffix": "ec2-source-<STAGE>", "networkStackSuffix": "ec2-source-<STAGE>",
            "distVersion": "6.8.23",
            "distributionUrl": "https://artifacts.elastic.co/downloads/elasticsearch/elasticsearch-oss-6.8.23.tar.gz",
            "captureProxyEnabled": False, "securityDisabled": True, "minDistribution": False,
            "cpuArch": "x64", "isInternal": True, "singleNodeCluster": True,
            "networkAvailabilityZones": 2, "dataNodeCount": 1, "managerNodeCount": 0,
            "serverAccessType": "ipv4", "restrictServerAccessTo": "0.0.0.0/0",
            "enableImdsCredentialRefresh": True, "requireImdsv2": True,
        }
    }
    migration_context = {
        "full-migration": {
            "stage": "<STAGE>", "vpcId": "<VPC_ID>", "engineVersion": "OS_2.19",
            "domainName": "os-cluster-<STAGE>", "dataNodeCount": 2,
            "openAccessPolicyEnabled": True, "domainRemovalPolicy": "DESTROY",
            "artifactBucketRemovalPolicy": "DESTROY", "captureProxyServiceEnabled": True,
            "targetClusterProxyServiceEnabled": True, "trafficReplayerServiceEnabled": True,
            "trafficReplayerExtraArgs": "--speedup-factor 10.0",
            "reindexFromSnapshotServiceEnabled": True,
            "sourceCluster": {"endpoint": "<SOURCE_CLUSTER_ENDPOINT>", "auth": {"type": "none"}, "version": "ES_6.8.23"},
            "tlsSecurityPolicy": "TLS_1_2", "enforceHTTPS": True, "nodeToNodeEncryptionEnabled": True,
            "encryptionAtRestEnabled": True, "vpcEnabled": True, "vpcAZCount": 2, "mskAZCount": 2,
            "migrationAssistanceEnabled": True, "replayerOutputEFSRemovalPolicy": "DESTROY",
            "migrationConsoleServiceEnabled": True, "otelMetricsCollectorEnabled": True, "otelTraceCollectorEnabled": False,
        }
    }
    src = ROOT / "tests/e2e/sourceJenkinsContext.json"
    mig = ROOT / "tests/e2e/migrationJenkinsContext.json"
    src.write_text(json.dumps(source_context, indent=2))
    mig.write_text(json.dumps(migration_context, indent=2))
    gradle_build(r)
    r.shell("deploy-full-es68", f'''
        set -euo pipefail
        cd tests/e2e
        ./awsE2ESolutionSetup.sh \
          --source-context-file './{src.name}' \
          --migration-context-file './{mig.name}' \
          --source-context-id source-single-node-ec2 \
          --migration-context-id full-migration \
          --stage "{stage}"
    ''')
    unique = f"gha_full_{int(time.time())}_{os.environ.get('GITHUB_RUN_ID','local')}"
    test_dir = "/root/lib/integ_test/integ_test"
    test_result = f"{test_dir}/reports/{unique}/report.xml"
    command = (f"pipenv run pytest --log-file={test_dir}/reports/{unique}/pytest.log "
               f"--junitxml={test_result} {test_dir}/full_tests.py "
               f"--source_proxy_alb_endpoint https://alb.migration.{stage}.local:9201 "
               f"--target_proxy_alb_endpoint https://alb.migration.{stage}.local:9202 "
               f"--unique_id {unique} --stage {stage} -s")
    r.shell("run-full-es68-tests", f'''
        cd tests/e2e
        ./awsRunIntegTests.sh --command '{command}' --test-result-file {test_result} --stage "{stage}"
    ''')
    if os.environ.get("CI_COMPARISON_CLEANUP_FULL_ES68") == "true":
        r.shell("cleanup-full-es68", f'''
            cd tests/e2e
            ./awsE2ESolutionSetup.sh --source-context-file './{src.name}' --migration-context-file './{mig.name}' \
              --source-context-id source-single-node-ec2 --migration-context-id full-migration --stage "{stage}" --clean-up-all
        ''', check=False)


def run_eks_standard(r, cdc=False):
    region = os.environ.get("AWS_REGION", "us-east-1")
    default = "esoscdc" if cdc else "eksint"
    stage = stage_name(default)
    kube = f"migration-eks-{stage}"
    ma_stack = f"Migration-Assistant-Infra-Create-VPC-eks-{stage}-{region}"
    test_ids = "0031" if cdc else "0001,0002"
    source = "ES_7.10"; target = "OS_1.3"
    gradle_build(r)
    boot = bootstrap(r, build=True, skip_test_images=True, use_general_node_pool=not cdc)
    tags = f"MATestOwner=migrations-ci,MATestStage={stage}" if cdc else None
    exports = bootstrap_ma(r, ma_stack, stage, region, boot, kube, resource_tags=tags, enforce_tags=cdc)
    acct = account_id()
    clusters, ctx = deploy_clusters(r, stage, f"cluster-context-{stage}.json", [
        {"clusterId": "source", "clusterName": f"{stage}-source", "clusterVersion": source,
         "clusterType": "OPENSEARCH_MANAGED_SERVICE", "domainRemovalPolicy": "DESTROY",
         "publicAccess": True, "accessPolicies": sigv4_policy(acct)},
        {"clusterId": "target", "clusterName": f"{stage}-target", "clusterVersion": target,
         "clusterType": "OPENSEARCH_MANAGED_SERVICE", "domainRemovalPolicy": "DESTROY",
         "publicAccess": True, "accessPolicies": sigv4_policy(acct)},
    ])
    try:
        apply_cluster_configmaps(r, kube, region, source, clusters["source"], target, clusters["target"])
        args = f"--source-version={source} --target-version={target} --test-ids='{test_ids}' --reuse-clusters --skip-delete --skip-install --kube-context={kube}"
        if cdc:
            args += f" --speedup-factor=20 --verify-resource-tags --ma-stack-name='{ma_stack}' --aws-region={region} --eks-cluster-name='{exports.get('MIGRATIONS_EKS_CLUSTER_NAME','')}'"
        run_automation(r, "run-eks-tests", f"pipenv run app {args}")
    finally:
        cleanup_eks(r, region, ma_stack, stage, ctx, kube)


def run_aoss(r, cdc=False):
    region = os.environ.get("AWS_REGION", "us-east-1")
    default = "aosscdc" if cdc else "aosss"
    stage = stage_name(default)
    kube = f"migration-eks-{stage}"
    ma_stack = f"{'MA-CDC-AOSS' if cdc else 'MA-Serverless'}-{stage}-{region}"
    gradle_build(r)
    boot = bootstrap(r, build=True, skip_test_images=True, use_general_node_pool=False)
    tags = f"MATestOwner=migrations-ci,MATestStage={stage}"
    exports = bootstrap_ma(r, ma_stack, stage, region, boot, kube, resource_tags=tags, enforce_tags=True)
    acct = account_id()
    pod_role = f"arn:aws:iam::{acct}:role/{exports.get('MIGRATIONS_EKS_CLUSTER_NAME')}-migrations-role"
    clusters_def = [
        {"clusterId": "source", "clusterName": f"{stage}-source", "clusterVersion": "ES_7.10",
         "clusterType": "OPENSEARCH_MANAGED_SERVICE", "domainRemovalPolicy": "DESTROY",
         "publicAccess": True, "accessPolicies": sigv4_policy(acct)}
    ] if cdc else []
    if cdc:
        clusters_def.append({"clusterId": "target", "clusterName": f"{stage}-target",
                             "clusterType": "OPENSEARCH_SERVERLESS", "collectionType": "SEARCH",
                             "standbyReplicas": "DISABLED", "domainRemovalPolicy": "DESTROY",
                             "dataAccessPrincipals": [f"arn:aws:iam::{acct}:role/JenkinsDeploymentRole", pod_role]})
    else:
        for cid, ctype in [("search", "SEARCH"), ("timeseries", "TIMESERIES"), ("vector", "VECTORSEARCH")]:
            clusters_def.append({"clusterId": cid, "clusterName": f"{stage}-{cid}",
                                 "clusterType": "OPENSEARCH_SERVERLESS", "collectionType": ctype,
                                 "standbyReplicas": "DISABLED", "domainRemovalPolicy": "DESTROY",
                                 "dataAccessPrincipals": [f"arn:aws:iam::{acct}:role/JenkinsDeploymentRole", pod_role]})
    clusters, ctx = deploy_clusters(r, stage, f"cluster-context-{stage}.json", clusters_def, vpc_id=exports.get("VPC_ID"))
    try:
        if cdc:
            apply_cluster_configmaps(r, kube, region, "ES_7.10", clusters["source"], None, None)
            r.shell("set-aoss-cdc-env", f'''
                kubectl --context="{kube}" set env statefulset/migration-console -n ma AOSS_CDC_ENDPOINT={clusters["target"]["endpoint"]}
                kubectl --context="{kube}" rollout status statefulset/migration-console -n ma --timeout=120s
            ''')
            run_automation(r, "run-cdc-aoss-tests",
                           f"pipenv run app --source-version=ES_7.10 --target-type=AOSS --test-ids='0034,0041' --reuse-clusters --skip-delete --skip-install --kube-context={kube} --verify-resource-tags --ma-stack-name='{ma_stack}' --aws-region={region} --eks-cluster-name='{exports.get('MIGRATIONS_EKS_CLUSTER_NAME','')}'")
        else:
            r.shell("set-aoss-env", f'''
                kubectl --context="{kube}" set env statefulset/migration-console -n ma \
                  AOSS_SEARCH_ENDPOINT={clusters["search"]["endpoint"]} \
                  AOSS_TIMESERIES_ENDPOINT={clusters["timeseries"]["endpoint"]} \
                  AOSS_VECTOR_ENDPOINT={clusters["vector"]["endpoint"]} \
                  AOSS_SNAPSHOT_NAME=os1x-aoss-osb-data \
                  AOSS_S3_REPO_URI=s3://migrations-snapshots-library-us-east-1/aoss-osb-data/os1x-aoss-osb-data/ \
                  AOSS_S3_REGION={region} \
                  AOSS_MONITOR_RETRY_LIMIT=33
                kubectl --context="{kube}" rollout status statefulset/migration-console -n ma --timeout=120s
            ''')
            run_automation(r, "run-aoss-tests",
                           f"pipenv run app --source-version=OS_1.3 --target-type=AOSS --test-ids='0021' --reuse-clusters --skip-delete --skip-install --kube-context={kube}")
    finally:
        cleanup_eks(r, region, ma_stack, stage, ctx, kube)


def run_byos(r):
    region = os.environ.get("AWS_REGION", "us-east-1")
    stage = stage_name("eksbyos")
    kube = f"migration-eks-{stage}"
    ma_stack = f"Migration-Assistant-Infra-Create-VPC-eks-{stage}-{region}"
    source = "ES_7.10"; target = "OS_2.19"
    gradle_build(r)
    boot = bootstrap(r, build=True, skip_test_images=True, use_general_node_pool=True)
    exports = bootstrap_ma(r, ma_stack, stage, region, boot, kube)
    clusters, ctx = deploy_clusters(r, stage, f"cluster-context-{stage}.json", [
        {"clusterId": "target", "clusterName": f"{stage}-target", "clusterVersion": target,
         "clusterType": "OPENSEARCH_MANAGED_SERVICE", "domainRemovalPolicy": "DESTROY",
         "vpcId": exports.get("VPC_ID"), "dataNodeType": "r8g.large.search",
         "dedicatedManagerNodeType": "m6g.large.search", "dataNodeCount": 2,
         "dedicatedManagerNodeCount": 0, "ebsVolumeSize": 100},
    ], vpc_id=exports.get("VPC_ID"))
    try:
        apply_cluster_configmaps(r, kube, region, None, None, target, clusters["target"])
        r.shell("set-byos-env", f'''
            kubectl --context="{kube}" -n ma set env statefulset/migration-console \
              BYOS_SNAPSHOT_NAME='es7x-osb-data' \
              BYOS_S3_REPO_URI='s3://migrations-snapshots-library-us-east-1/ma_osb_data/es7x-osb-data/' \
              BYOS_S3_REGION='{region}' \
              BYOS_POD_REPLICAS='1' \
              BYOS_MONITOR_RETRY_LIMIT='1000000'
            kubectl --context="{kube}" -n ma rollout status statefulset/migration-console --timeout=120s
        ''')
        run_automation(r, "run-byos-tests",
                       f"pipenv run app --source-version={source} --target-version={target} --test-ids='0010' --reuse-clusters --skip-delete --skip-install --kube-context={kube}")
    finally:
        cleanup_eks(r, region, ma_stack, stage, ctx, kube)


def create_vpc_with_subnets(r, region, stage, prefix="ma-native"):
    out = r.out / f"{prefix}-vpc.json"
    r.shell(f"create-{prefix}-vpc", f'''
        set -euo pipefail
        vpc=$(aws ec2 create-vpc --cidr-block 10.214.0.0/16 --region "{region}" \
          --tag-specifications 'ResourceType=vpc,Tags=[{{Key=Name,Value={prefix}-{stage}}},{{Key=ma-stage,Value={stage}}}]' \
          --query 'Vpc.VpcId' --output text)
        aws ec2 modify-vpc-attribute --vpc-id "$vpc" --enable-dns-hostnames '{{"Value":true}}' --region "{region}"
        aws ec2 modify-vpc-attribute --vpc-id "$vpc" --enable-dns-support '{{"Value":true}}' --region "{region}"
        pub1=$(aws ec2 create-subnet --vpc-id "$vpc" --cidr-block 10.214.0.0/24 --availability-zone "{region}a" --region "{region}" \
          --tag-specifications 'ResourceType=subnet,Tags=[{{Key=Name,Value={prefix}-{stage}-pub-1}},{{Key=ma-stage,Value={stage}}}]' \
          --query 'Subnet.SubnetId' --output text)
        pub2=$(aws ec2 create-subnet --vpc-id "$vpc" --cidr-block 10.214.1.0/24 --availability-zone "{region}b" --region "{region}" \
          --tag-specifications 'ResourceType=subnet,Tags=[{{Key=Name,Value={prefix}-{stage}-pub-2}},{{Key=ma-stage,Value={stage}}}]' \
          --query 'Subnet.SubnetId' --output text)
        igw=$(aws ec2 create-internet-gateway --region "{region}" \
          --tag-specifications 'ResourceType=internet-gateway,Tags=[{{Key=Name,Value={prefix}-{stage}-igw}},{{Key=ma-stage,Value={stage}}}]' \
          --query 'InternetGateway.InternetGatewayId' --output text)
        aws ec2 attach-internet-gateway --internet-gateway-id "$igw" --vpc-id "$vpc" --region "{region}"
        rt=$(aws ec2 create-route-table --vpc-id "$vpc" --region "{region}" \
          --tag-specifications 'ResourceType=route-table,Tags=[{{Key=Name,Value={prefix}-{stage}-pub-rt}},{{Key=ma-stage,Value={stage}}}]' \
          --query 'RouteTable.RouteTableId' --output text)
        aws ec2 create-route --route-table-id "$rt" --destination-cidr-block 0.0.0.0/0 --gateway-id "$igw" --region "{region}"
        aws ec2 associate-route-table --route-table-id "$rt" --subnet-id "$pub1" --region "{region}"
        aws ec2 associate-route-table --route-table-id "$rt" --subnet-id "$pub2" --region "{region}"
        eip=$(aws ec2 allocate-address --domain vpc --region "{region}" \
          --tag-specifications 'ResourceType=elastic-ip,Tags=[{{Key=Name,Value={prefix}-{stage}-eip}},{{Key=ma-stage,Value={stage}}}]' \
          --query 'AllocationId' --output text)
        nat=$(aws ec2 create-nat-gateway --subnet-id "$pub1" --allocation-id "$eip" --region "{region}" \
          --tag-specifications 'ResourceType=natgateway,Tags=[{{Key=Name,Value={prefix}-{stage}-nat}},{{Key=ma-stage,Value={stage}}}]' \
          --query 'NatGateway.NatGatewayId' --output text)
        aws ec2 wait nat-gateway-available --nat-gateway-ids "$nat" --region "{region}"
        priv1=$(aws ec2 create-subnet --vpc-id "$vpc" --cidr-block 10.214.20.0/24 --availability-zone "{region}a" --region "{region}" \
          --tag-specifications 'ResourceType=subnet,Tags=[{{Key=Name,Value={prefix}-{stage}-priv-1}},{{Key=ma-stage,Value={stage}}}]' \
          --query 'Subnet.SubnetId' --output text)
        priv2=$(aws ec2 create-subnet --vpc-id "$vpc" --cidr-block 10.214.21.0/24 --availability-zone "{region}b" --region "{region}" \
          --tag-specifications 'ResourceType=subnet,Tags=[{{Key=Name,Value={prefix}-{stage}-priv-2}},{{Key=ma-stage,Value={stage}}}]' \
          --query 'Subnet.SubnetId' --output text)
        prt=$(aws ec2 create-route-table --vpc-id "$vpc" --region "{region}" \
          --tag-specifications 'ResourceType=route-table,Tags=[{{Key=Name,Value={prefix}-{stage}-priv-rt}},{{Key=ma-stage,Value={stage}}}]' \
          --query 'RouteTable.RouteTableId' --output text)
        aws ec2 create-route --route-table-id "$prt" --destination-cidr-block 0.0.0.0/0 --nat-gateway-id "$nat" --region "{region}"
        aws ec2 associate-route-table --route-table-id "$prt" --subnet-id "$priv1" --region "{region}"
        aws ec2 associate-route-table --route-table-id "$prt" --subnet-id "$priv2" --region "{region}"
        python3 - <<PY > "{out}"
import json
print(json.dumps({{"vpcId":"$vpc","subnetIds":"$priv1,$priv2"}}, indent=2))
PY
    ''')
    return json.loads(out.read_text())


def cleanup_vpc(r, region, vpc_id, stage):
    if not vpc_id:
        return
    r.shell("cleanup-vpc", f'''
        set +e
        vpc="{vpc_id}"
        for nat in $(aws ec2 describe-nat-gateways --filter Name=vpc-id,Values="$vpc" --query "NatGateways[?State!='deleted'].NatGatewayId" --output text --region "{region}" 2>/dev/null); do
          aws ec2 delete-nat-gateway --nat-gateway-id "$nat" --region "{region}" || true
          aws ec2 wait nat-gateway-deleted --nat-gateway-ids "$nat" --region "{region}" || true
        done
        for alloc in $(aws ec2 describe-addresses --filters Name=tag:ma-stage,Values="{stage}" --query 'Addresses[*].AllocationId' --output text --region "{region}" 2>/dev/null); do
          aws ec2 release-address --allocation-id "$alloc" --region "{region}" || true
        done
        for igw in $(aws ec2 describe-internet-gateways --filters Name=attachment.vpc-id,Values="$vpc" --query 'InternetGateways[*].InternetGatewayId' --output text --region "{region}" 2>/dev/null); do
          aws ec2 detach-internet-gateway --internet-gateway-id "$igw" --vpc-id "$vpc" --region "{region}" || true
          aws ec2 delete-internet-gateway --internet-gateway-id "$igw" --region "{region}" || true
        done
        main_rt=$(aws ec2 describe-route-tables --filters Name=vpc-id,Values="$vpc" Name=association.main,Values=true --query 'RouteTables[0].RouteTableId' --output text --region "{region}" 2>/dev/null || echo "")
        for rt in $(aws ec2 describe-route-tables --filters Name=vpc-id,Values="$vpc" --query 'RouteTables[*].RouteTableId' --output text --region "{region}" 2>/dev/null); do
          [ "$rt" = "$main_rt" ] && continue
          for assoc in $(aws ec2 describe-route-tables --route-table-ids "$rt" --query 'RouteTables[0].Associations[?!Main].RouteTableAssociationId' --output text --region "{region}" 2>/dev/null); do
            aws ec2 disassociate-route-table --association-id "$assoc" --region "{region}" || true
          done
          aws ec2 delete-route-table --route-table-id "$rt" --region "{region}" || true
        done
        for ep in $(aws ec2 describe-vpc-endpoints --filters Name=vpc-id,Values="$vpc" --query 'VpcEndpoints[*].VpcEndpointId' --output text --region "{region}" 2>/dev/null); do
          aws ec2 delete-vpc-endpoints --vpc-endpoint-ids "$ep" --region "{region}" || true
        done
        for subnet in $(aws ec2 describe-subnets --filters Name=vpc-id,Values="$vpc" --query 'Subnets[*].SubnetId' --output text --region "{region}" 2>/dev/null); do
          aws ec2 delete-subnet --subnet-id "$subnet" --region "{region}" || true
        done
        for sg in $(aws ec2 describe-security-groups --filters Name=vpc-id,Values="$vpc" --query "SecurityGroups[?GroupName!='default'].GroupId" --output text --region "{region}" 2>/dev/null); do
          aws ec2 delete-security-group --group-id "$sg" --region "{region}" || true
        done
        aws ec2 delete-vpc --vpc-id "$vpc" --region "{region}" || true
    ''', check=False)


def run_cfn(r, import_vpc=False):
    region = os.environ.get("AWS_REGION", "us-east-1")
    stage = stage_name("eksivpc" if import_vpc else "ekscvpc")
    template = "Migration-Assistant-Infra-Import-VPC-eks" if import_vpc else "Migration-Assistant-Infra-Create-VPC-eks"
    stack = f"{template}-{stage}-{region}"
    gradle_build(r)
    boot = bootstrap(r, build=True, skip_test_images=False, use_general_node_pool=True)
    vpc = None
    try:
        deploy_flag = "--deploy-create-vpc-cfn"
        vpc_args = ""
        if import_vpc:
            vpc = create_vpc_with_subnets(r, region, stage, prefix="ma-import")
            deploy_flag = "--deploy-import-vpc-cfn"
            vpc_args = f"--vpc-id {vpc['vpcId']} --subnet-ids {vpc['subnetIds']}"
        r.shell("deploy-cfn", f'''
            set -euo pipefail
            {boot["script"]} {deploy_flag} \
              {vpc_args} \
              --stack-name "{stack}" --stage "{stage}" --region "{region}" \
              --skip-console-exec \
              --eks-access-principal-arn "arn:aws:iam::{account_id()}:role/JenkinsDeploymentRole" \
              {boot["flags"]}
            kubectl wait --namespace ma --for=condition=ready pod/migration-console-0 --timeout=600s
            kubectl exec -n ma migration-console-0 -- /bin/bash -lc 'console --version'
        ''')
    finally:
        cleanup_eks(r, region, stack, None, None, f"migration-eks-cluster-{stage}-{region}")
        if vpc:
            cleanup_vpc(r, region, vpc["vpcId"], stage)


def run_isolated(r):
    region = os.environ.get("AWS_REGION", "us-east-1")
    stage = stage_name("isoint")
    build_stage = "isob-" + stage.split("-", 1)[-1]
    build_stack = f"MA-ISO-BUILD-{stage}"
    iso_stack = f"MA-ISO-{stage}"
    build_kube = f"migration-eks-build-{build_stage}"
    kube = f"migration-eks-{stage}"
    source = "ES_7.10"; target = "OS_2.19"
    gradle_build(r)
    vpc = None
    cluster_ctx = None
    try:
        build_boot = bootstrap(r, build=True, skip_test_images=True, use_general_node_pool=False)
        build_exports = bootstrap_ma(r, build_stack, build_stage, region, build_boot, build_kube)
        build_ecr = build_exports.get("MIGRATIONS_ECR_REGISTRY")
        vpc = create_vpc_with_subnets(r, region, stage, prefix="ma-iso")
        r.shell("tag-isolated-subnets", f'aws ec2 create-tags --region "{region}" --resources {vpc["subnetIds"].replace(",", " ")} --tags Key=kubernetes.io/role/internal-elb,Value=1')
        iso_boot = bootstrap(r, build=True, skip_test_images=True, use_general_node_pool=False)
        iso_exports = bootstrap_ma(r, iso_stack, stage, region, iso_boot, kube,
                                   vpc_id=vpc["vpcId"], subnet_ids=vpc["subnetIds"],
                                   create_vpc_endpoints=True, ma_images_source=build_ecr)
        delete_stack(r, build_stack, region, "cleanup-build-stack-early")
        clusters, cluster_ctx = deploy_clusters(r, stage, f"cluster-context-{stage}.json", [
            {"clusterId": "source", "clusterName": f"{stage}-source", "clusterVersion": source,
             "clusterType": "OPENSEARCH_MANAGED_SERVICE", "domainRemovalPolicy": "DESTROY"},
            {"clusterId": "target", "clusterName": f"{stage}-target", "clusterVersion": target,
             "clusterType": "OPENSEARCH_MANAGED_SERVICE", "domainRemovalPolicy": "DESTROY"},
        ], vpc_id=vpc["vpcId"], vpc_subnet_ids=vpc["subnetIds"])
        apply_cluster_configmaps(r, kube, region, source, clusters["source"], target, clusters["target"])
        run_automation(r, "run-isolated-tests",
                       f"pipenv run app --source-version={source} --target-version={target} --test-ids='0040' --reuse-clusters --skip-delete --skip-install --kube-context={kube}")
    finally:
        cleanup_eks(r, region, iso_stack, stage, cluster_ctx, kube)
        delete_stack(r, build_stack, region, "cleanup-build-stack")
        if vpc:
            cleanup_vpc(r, region, vpc["vpcId"], stage)


def run_aws_job(r):
    ensure_tool("aws")
    r.run("aws-caller-identity", ["aws", "sts", "get-caller-identity"])
    if r.job == "full-es68-e2e-aws-test":
        run_full_es68(r)
    elif r.job == "eks-integ-test":
        run_eks_standard(r, cdc=False)
    elif r.job == "eks-aoss-integ-test":
        run_aoss(r, cdc=False)
    elif r.job == "eks-byos-integ-test":
        run_byos(r)
    elif r.job == "eks-cdc-full-e2e-test" or r.job == "eks-cdc-k6-load-test":
        run_eks_standard(r, cdc=True)
    elif r.job == "eks-cdc-aoss-e2e-test":
        run_aoss(r, cdc=True)
    elif r.job == "eks-cfn-create-vpc-test":
        run_cfn(r, import_vpc=False)
    elif r.job == "eks-cfn-import-vpc-test":
        run_cfn(r, import_vpc=True)
    elif r.job == "eks-full-e2e-isolated-vpc-test":
        run_isolated(r)
    else:
        raise AssertionError(r.job)


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
