"""Approval prerequisites through the real CLI, Kubernetes SDK and S3 reader.

The API fixtures model stored resources/artifacts, not metadata migration or
Argo execution. These tests cover artifact consumption, not artifact production.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import subprocess
import threading
from urllib.parse import urlparse

from click.testing import CliRunner
from kubernetes import client
import pytest

from console_link.workflow.commands import show
from integ_test.approval_contract import (
    assert_workflow_output_reference,
    assert_workflow_show_output_available,
)


@pytest.fixture(params=["evaluatemetadata", "migratemetadata"])
def outputs(request, monkeypatch, tmp_path):
    task = request.param
    output = {"evaluatemetadata": "metadataEvaluate", "migratemetadata": "metadataMigrate"}[task]
    key = f"migration-outputs/snapshotmigration.migration-0/{output}/run-1/stdout"
    content = f"{task}: index test__index, document 1\n"
    resource = {"metadata": {"name": "migration-0"},
                "status": {"outputs": {output: {"s3Key": key}}}}
    state = {"task": task, "output": output, "key": key, "resource": resource,
             "content": content, "status": 200, "requests": [], "mount": tmp_path}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            path = urlparse(self.path).path
            state["requests"].append(path)
            if path == "/apis/migrations.opensearch.org/v1alpha1/namespaces/ma/snapshotmigrations/migration-0":
                status, body, content_type = 200, json.dumps(resource).encode(), "application/json"
            elif path == "/artifacts/" + key:
                status, body, content_type = state["status"], state["content"].encode(), "text/plain"
                if status != 200:
                    code = "AccessDenied" if status == 403 else "NoSuchKey"
                    body = f"<Error><Code>{code}</Code><Message>artifact unavailable</Message></Error>".encode()
                    content_type = "application/xml"
            else:
                status, body, content_type = 404, b"{}", "application/json"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original = client.Configuration.get_default_copy()
    configuration = client.Configuration()
    configuration.host = f"http://127.0.0.1:{server.server_port}"
    configuration.proxy = None
    client.Configuration.set_default(configuration)
    monkeypatch.setattr(show, "load_k8s_config", lambda: None)
    monkeypatch.setenv("REPO_ARTIFACTS_BUCKET", "s3://artifacts")
    monkeypatch.setenv("REPO_ARTIFACTS_ENDPOINT_URL", configuration.host)
    monkeypatch.setenv("REPO_ARTIFACTS_MOUNT_POINT", str(tmp_path))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-aws-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-credentials"))
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    try:
        yield state
    finally:
        client.Configuration.set_default(original)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def invoke(task):
    result = CliRunner().invoke(show.show_command, [
        "--namespace", "ma", "snapshotmigration.migration-0", task, "--clean",
    ])
    return subprocess.CompletedProcess("workflow show", result.exit_code, result.stdout, result.stderr)


@pytest.mark.parametrize("storage", ["mounted", "s3"])
def test_metadata_output_is_read_from_the_cr_reference(outputs, storage):
    if storage == "mounted":
        path = outputs["mount"] / outputs["key"]
        path.parent.mkdir(parents=True)
        path.write_text(outputs["content"])
    assert_workflow_output_reference(outputs["task"], outputs["resource"])
    result = invoke(outputs["task"])
    assert_workflow_show_output_available(outputs["task"], result)
    assert result.stdout == outputs["content"]
    assert ("/artifacts/" + outputs["key"] in outputs["requests"]) == (storage == "s3")


@pytest.mark.parametrize("status", [403, 404])
def test_unreadable_metadata_output_fails_the_e2e_prerequisite(outputs, status):
    outputs["status"] = status
    result = invoke(outputs["task"])
    assert result.returncode != 0
    with pytest.raises(AssertionError, match="Expected workflow show to find"):
        assert_workflow_show_output_available(outputs["task"], result)


def test_empty_metadata_output_fails_the_e2e_prerequisite(outputs):
    outputs["content"] = ""
    result = invoke(outputs["task"])
    with pytest.raises(AssertionError, match="non-empty"):
        assert_workflow_show_output_available(outputs["task"], result)


def test_missing_reference_cannot_masquerade_as_metadata_output(outputs):
    # The CLI currently exits zero and prints a diagnostic for a missing ref.
    # Checking only exit code and nonempty stdout falsely accepts that message.
    outputs["resource"]["status"]["outputs"].clear()
    result = invoke(outputs["task"])
    assert "No managed output" in result.stdout
    with pytest.raises(AssertionError, match="output reference"):
        assert_workflow_output_reference(outputs["task"], outputs["resource"])
    assert not any(path.startswith("/artifacts/") for path in outputs["requests"])
