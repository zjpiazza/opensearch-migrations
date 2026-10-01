#!/bin/bash

set -eo pipefail

MIGRATIONS_REPO_ROOT_DIR=$(git rev-parse --show-toplevel)

kubectl apply -f "${MIGRATIONS_REPO_ROOT_DIR}/apps/console/lib/integ_test/testWorkflows/clusterWorkflows.yaml" -n ma
