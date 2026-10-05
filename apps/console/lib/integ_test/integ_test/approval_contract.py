"""Approval scenario assertions shared by real and dependency-isolated tests.

These functions inspect observations. They never advance workflows or synthesize
migration results; the runtime under test must produce those observations.
"""


def approval_gate_names(snapshot_migration_name):
    return [
        "begin",
        "captureproxysetup.capture-proxy",
        f"evaluatemetadata.{snapshot_migration_name}",
        f"migratemetadata.{snapshot_migration_name}",
        f"documentbackfill.{snapshot_migration_name}",
    ]


def assert_capture_proxy_not_started(capture_proxy):
    status = capture_proxy.get("status", {})
    phase = status.get("phase")
    if phase != "Created":
        raise AssertionError(
            f"CaptureProxy phase before begin approval was {phase!r}, expected 'Created': {status}"
        )
    if status.get("configChecksum"):
        raise AssertionError(f"CaptureProxy configChecksum was set before begin approval: {status}")
    if status.get("serviceEndpoint") or status.get("loadBalancerEndpoint"):
        raise AssertionError(f"CaptureProxy endpoint was set before begin approval: {status}")


def assert_capture_proxy_setup_pending(capture_proxy):
    phase = capture_proxy.get("status", {}).get("phase")
    if phase != "Pending":
        raise AssertionError(
            f"CaptureProxy phase before proxy setup approval was {phase!r}, expected 'Pending': "
            f"{capture_proxy.get('status')}"
        )


def assert_workflow_output_reference(task_name, snapshot_migration):
    output_name = {
        "evaluatemetadata": "metadataEvaluate",
        "migratemetadata": "metadataMigrate",
    }[task_name]
    ref = snapshot_migration.get("status", {}).get("outputs", {}).get(output_name)
    if not isinstance(ref, dict) or not ref.get("s3Key"):
        raise AssertionError(f"Expected retained {task_name} output reference, got {ref!r}")


def assert_workflow_show_output_available(task_name, result):
    if result.returncode != 0:
        raise AssertionError(
            f"Expected workflow show to find {task_name} output before its approval gate "
            f"(rc={result.returncode}). stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    if not result.stdout.strip():
        raise AssertionError(f"Expected workflow show {task_name} output to be non-empty")


def assert_document_backfill_not_started(snapshot_migration):
    backfill_status = snapshot_migration.get("status", {}).get("documentBackfill")
    if backfill_status:
        raise AssertionError(
            "Document backfill status was set before the document backfill step ran: "
            f"{backfill_status}"
        )


def assert_document_backfill_completed(snapshot_migration):
    status = snapshot_migration.get("status", {})
    backfill_status = status.get("documentBackfill")
    if not isinstance(backfill_status, dict):
        raise AssertionError(f"SnapshotMigration documentBackfill status was not set: {status}")
    if status.get("phase") != "Completed":
        raise AssertionError(f"SnapshotMigration phase was not Completed after backfill: {status}")
    if backfill_status.get("phase") != "Completed":
        raise AssertionError(f"Document backfill phase was not Completed: {backfill_status}")
    if not backfill_status.get("updatedAt"):
        raise AssertionError(f"Document backfill status did not include updatedAt: {backfill_status}")
    summary = backfill_status.get("summary", {})
    if summary.get("shardsTotal", 0) < 1:
        raise AssertionError(f"Document backfill status did not report any shards: {backfill_status}")
    if summary.get("shardsMigrated") != summary.get("shardsTotal"):
        raise AssertionError(f"Document backfill did not migrate all shards: {backfill_status}")
