"""Real approval CLI + service logic + Kubernetes SDK over a fake HTTP API.

The fixture advances observed Argo states explicitly; this does not simulate an
Argo controller, admission, RBAC enforcement, or the migration data plane.
"""
import base64
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlparse

from click.testing import CliRunner
from kubernetes import client
import pytest

from console_link.workflow.commands import approve
from integ_test.approval_contract import approval_gate_names


@pytest.fixture
def api(monkeypatch):
    scenario = json.loads(Path(__file__).with_name("approval_scenario.json").read_text())
    scenario["gates"] = approval_gate_names(scenario["snapshot_migration_name"])
    gates = {
        name: {
            "metadata": {"name": name, "labels": {approve.LABEL_WORKFLOW: scenario["workflow"]}},
            "status": {"phase": "Created"},
        }
        for name in scenario["gates"]
    }
    gates["unrelated"] = {
        "metadata": {"name": "unrelated", "labels": {approve.LABEL_WORKFLOW: "other-workflow"}},
        "status": {"phase": "Created"},
    }
    state = {"scenario": scenario, "gates": gates, "active": scenario["gates"][0],
             "compressed": False, "deny_patch": False, "patches": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, code, body):
            payload = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            parsed = urlparse(self.path)
            prefix = "/apis/migrations.opensearch.org/v1alpha1/namespaces/ma/approvalgates"
            workflow_path = "/apis/argoproj.io/v1alpha1/namespaces/ma/workflows/migration-workflow"
            if parsed.path == prefix:
                selector = parse_qs(parsed.query).get("labelSelector", [""])[0]
                key, _, value = selector.partition("=")
                items = [g for g in gates.values() if g["metadata"]["labels"].get(key) == value]
                self.respond(200, {"items": items})
            elif parsed.path == workflow_path:
                nodes = {"gate": {"phase": "Running", "type": "Resource",
                                  "templateRef": {"template": "waitforuserapproval"},
                                  "inputs": {"parameters": [
                                      {"name": "resourceName", "value": state["active"]}]}}}
                status = {"phase": "Running", "nodes": nodes}
                if state["compressed"]:
                    status.pop("nodes")
                    status["compressedNodes"] = base64.b64encode(
                        gzip.compress(json.dumps(nodes).encode(), mtime=0)).decode()
                self.respond(200, {"metadata": {"name": scenario["workflow"]}, "status": status})
            else:
                self.respond(404, {"reason": "NotFound"})

        def do_PATCH(self):
            parts = urlparse(self.path).path.split("/")
            expected = ["", "apis", "migrations.opensearch.org", "v1alpha1",
                        "namespaces", "ma", "approvalgates"]
            if parts[:7] != expected or len(parts) != 9 or parts[-1] != "status":
                return self.respond(404, {"reason": "NotFound"})
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if state["deny_patch"]:
                return self.respond(403, {"reason": "Forbidden"})
            name = parts[-2]
            if name not in gates:
                return self.respond(404, {"reason": "NotFound"})
            if body != {"status": {"phase": "Approved"}}:
                return self.respond(422, {"reason": "Invalid"})
            gates[name]["status"].update(body["status"])
            state["patches"].append(name)
            self.respond(200, gates[name])

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original = client.Configuration.get_default_copy()
    configuration = client.Configuration()
    configuration.host = f"http://127.0.0.1:{server.server_port}"
    configuration.proxy = None
    client.Configuration.set_default(configuration)
    monkeypatch.setattr(approve, "load_k8s_config", lambda: None)
    try:
        yield state
    finally:
        client.Configuration.set_default(original)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def invoke(*args):
    return CliRunner().invoke(approve.approve_group, ["step", "--namespace", "ma", *args])


@pytest.mark.parametrize("compressed", [False, True])
def test_gate_lifecycle_and_idempotent_approval(api, compressed):
    api["compressed"] = compressed
    # A later gate exists but cannot be approved before the workflow reaches it.
    premature = invoke(api["scenario"]["gates"][-1])
    assert premature.exit_code == 1, premature.output
    assert api["patches"] == []
    for name in api["scenario"]["gates"]:
        api["active"] = name
        result = invoke(name)
        assert result.exit_code == 0, (result.output, result.exception)
        assert api["gates"][name]["status"]["phase"] == "Approved"
        repeated = invoke(name)
        assert repeated.exit_code == 0, repeated.output
        assert "Already approved" in repeated.output
    assert api["patches"] == api["scenario"]["gates"]


def test_all_approval_is_scoped_to_workflow_and_active_gate(api):
    result = invoke("--all")
    assert result.exit_code == 0, (result.output, result.exception)
    assert api["patches"] == [api["scenario"]["gates"][0]]
    assert api["gates"]["unrelated"]["status"]["phase"] == "Created"


def test_api_rejection_is_reported_without_claiming_success(api):
    api["deny_patch"] = True
    result = invoke(api["active"])
    assert result.exit_code == 1, result.output
    assert "Failed to approve" in result.output
    assert api["patches"] == []
    assert api["gates"][api["active"]]["status"]["phase"] == "Created"
