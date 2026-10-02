"""Fault injection for the exact assertions used by Test0003ApprovalGateIntegration.

This validates assertion sensitivity, not a simulated migration or controller.
"""
from copy import deepcopy
from subprocess import CompletedProcess

import pytest

from integ_test import approval_contract as contract


def completed_backfill():
    return {"status": {
        "phase": "Completed",
        "documentBackfill": {
            "phase": "Completed",
            "updatedAt": "2026-01-01T00:00:00Z",
            "summary": {"shardsTotal": 2, "shardsMigrated": 2},
        },
    }}


@pytest.mark.parametrize("fault", ["phase", "configChecksum", "serviceEndpoint", "loadBalancerEndpoint"])
def test_begin_gate_rejects_early_proxy_setup(fault):
    resource = {"status": {"phase": "Created"}}
    contract.assert_capture_proxy_not_started(resource)
    resource["status"][fault] = "unexpected"
    with pytest.raises(AssertionError, match="CaptureProxy"):
        contract.assert_capture_proxy_not_started(resource)


@pytest.mark.parametrize("phase", [None, "Created", "Ready", "Error"])
def test_proxy_setup_gate_requires_pending(phase):
    contract.assert_capture_proxy_setup_pending({"status": {"phase": "Pending"}})
    with pytest.raises(AssertionError, match="expected 'Pending'"):
        contract.assert_capture_proxy_setup_pending({"status": {"phase": phase}})


@pytest.mark.parametrize("task", ["evaluatemetadata", "migratemetadata"])
@pytest.mark.parametrize("exit_code,output", [(1, "some output"), (0, ""), (0, " \n")])
def test_metadata_gate_requires_successful_nonempty_output(task, exit_code, output):
    contract.assert_workflow_show_output_available(task, CompletedProcess([], 0, "{}", ""))
    with pytest.raises(AssertionError, match="Expected workflow show"):
        contract.assert_workflow_show_output_available(task, CompletedProcess([], exit_code, output, "failure"))


def test_metadata_gate_rejects_early_backfill():
    contract.assert_document_backfill_not_started({"status": {}})
    with pytest.raises(AssertionError, match="before the document backfill step ran"):
        contract.assert_document_backfill_not_started({"status": {"documentBackfill": {"phase": "Running"}}})


@pytest.mark.parametrize("fault", [
    "missing_status", "wrong_type", "migration_running", "backfill_running",
    "missing_timestamp", "missing_summary", "no_shards", "incomplete_shards",
])
def test_backfill_gate_rejects_incomplete_migration(fault):
    resource = completed_backfill()
    contract.assert_document_backfill_completed(deepcopy(resource))
    status = resource["status"]
    backfill = status["documentBackfill"]
    if fault == "missing_status":
        status.pop("documentBackfill")
    elif fault == "wrong_type":
        status["documentBackfill"] = "Completed"
    elif fault == "migration_running":
        status["phase"] = "Running"
    elif fault == "backfill_running":
        backfill["phase"] = "Running"
    elif fault == "missing_timestamp":
        backfill.pop("updatedAt")
    elif fault == "missing_summary":
        backfill.pop("summary")
    elif fault == "no_shards":
        backfill["summary"].update(shardsTotal=0, shardsMigrated=0)
    elif fault == "incomplete_shards":
        backfill["summary"]["shardsMigrated"] = 1
    with pytest.raises(AssertionError):
        contract.assert_document_backfill_completed(resource)
