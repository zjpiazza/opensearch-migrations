# Development Guide

## Table of Contents
- [Table of Contents](#table-of-contents)
- [Prerequisites](#prerequisites)
- [Quick Start](#kubernetes-quick-start)
- [Project Structure](#project-structure)
- [Building the Project](#building-the-project)
- [Running Tests](#running-tests)
- [Code Style](#code-style)
- [Pre-Commit Hooks](#pre-commit-hooks)
- [Publishing](#publishing)
- [Development Environments](#development-environments)
  - [VSCode](#vscode)
    - [Python](#python)

## Prerequisites

- Java Development Kit (JDK) 17+
- Python3
- Docker/Minikube/K3s/etc (for local deployment)
- [Helm](https://helm.sh/docs/intro/install/)
- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html#getting-started-install-instructions) (for AWS deployment)
- Node.js v22 (downloaded automatically by Gradle)
- [AWS Cloud Development Kit (CDK)](https://docs.aws.amazon.com/cdk/v2/guide/getting_started.html) (for AWS deployment, downloaded automatically by Gradle)

## Kubernetes Quick Start

* This [Kubernetes Guide](deploy/kubernetes/README.md) shows you how to create a minikube cluster locally and deploy the Migration Assistant to it.
* This [AWS EKS Guide](deploy/aws/README.md) shows you how to deploy an EKS cluster and deploy the Migration Assistant to it.

See the [project wiki](https://github.com/opensearch-project/opensearch-migrations/wiki)
to learn more about how to use the migration console and its workflow commands.

## Project Structure

| Directory | Responsibility |
| --- | --- |
| `api/` | Contract ownership and schema entry points |
| `apps/` | Runnable workers, CLIs, existing orchestration, and schema viewer |
| `libs/` | Reusable migration, snapshot, HTTP, transform, traffic, and runtime code |
| `deploy/` | Helm charts, Terraform, provider bootstrap, and distribution packaging |
| `tests/` | Shared fixtures, cross-component automation, E2E, and performance tooling |
| `tools/` | Build implementation, CI adapters, release support, and developer scripts |
| `examples/` | Standalone development examples |
| `docs/` | Architecture, user guides, design decisions, and experiment evidence |

Component unit tests remain beside their source. Gradle project IDs and published
artifact names are preserved: for example, `:RFS:wiremockTest` now reads sources
from `libs/migration-engine`. See `settings.gradle` for explicit project paths.
The root `buildSrc/` is a Gradle discovery shim; its implementation lives in
`tools/build/gradle`. `gradle/` retains wrapper/configuration files and `vars/`
remains at the root because Jenkins shared-library discovery requires it.

The existing Argo/TypeScript workspace is in `apps/orchestration`, the Python
console in `apps/console`, and the Rust provisioning CLI in `apps/cli`. These are
source relocations; operator adoption and language consolidation are separate
experiments. The [layout map](docs/architecture-refactor/layout-map.json) records
every old-to-new directory mapping.

Run `python3 tools/dev/check-repository-layout.py` to check layout invariants.

## Building the Project

```bash
./gradlew build
```

Builds use Maven Central and the Gradle Plugin Portal by default. To use a shared
dependency cache, including for Spotless and `buildSrc`, see
[dependency repository configuration](tools/ci/jenkins/DEPENDENCY_CACHE.md#use-another-repository-manager).

## Running Tests

```bash
./gradlew test
```

## Building Images

Build images with buildkit and jib.
See [buildImages](tools/build/images/README-K8s.md) for instructions to set
that up.

```bash
./gradlew :buildImages:buildImagesToRegistry
```

## Running the Project

* Running the project in [Kubernetes](deploy/kubernetes/README.md)
* Running the legacy solution with [Docker Compose](deploy/local/docker-compose/README.md)

## Code Style

We use Spotless for code formatting. To check and apply the code style:

```bash
./gradlew spotlessCheck
./gradlew spotlessApply
```

## Pre-Commit Hooks

Install the pre-commit hooks:

```bash
./tools/dev/install-githooks.sh
```

## Publishing Images

This project can be published to a local Maven repository with:
```sh
./gradlew publishToMavenLocal
```

And subsequently imported into a separate Gradle project with (replacing `name` with any subProject name):
```groovy
repositories {
    mavenCentral()
    mavenLocal()
}

dependencies {
    implementation group: "org.opensearch.migrations.trafficcapture", name: "captureKafkaOffloader", version: "0.1.0-SNAPSHOT"
    //... other dependencies
}
```

The entire list of published subprojects can be viewed as follows:
```sh
./gradlew listPublishedArtifacts
```


To include a test Fixture dependency, define the import similar to the following:

```groovy
testImplementation testFixtures('org.opensearch.migrations.trafficcapture:trafficReplayer:0.1.0-SNAPSHOT')
```

## Development Environments

### VSCode

#### Python

Settings.json files are already set up in the project, make sure that venv environments are created in all folders with pipfile.  Bootstrap your environment by running the following command that creates all the environments.

```bash
find . -name Pipfile -not -path "*/cdk.out/*"  | while read pipfile; do
  dir=$(dirname "$pipfile")
  echo "Setting up .venv in $dir"
  (cd "$dir" && PIPENV_IGNORE_VIRTUALENVS=1 PIPENV_VENV_IN_PROJECT=1 pipenv install)
done
```

## Architecture refactor experiments

The [architecture refactor record](docs/architecture-refactor/README.md) tracks
the proposed repository layout, decision status, experiment checkpoints, and
retained measurements. Update it with each meaningful refactor step so future
RFCs can trace recommendations to implementation and evidence.
