import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from tools.research.supervisor_ui import Controls, handler_for, local_origin


class FakeControls:
    token = "safe-session-token"
    settings = {"port": 8891}
    enabled = True
    calls = []

    def view(self):
        return {"enabled": self.enabled, "status": "PROCESS_PRESENT"}

    def action(self, action):
        self.calls.append(action)
        self.enabled = action == "enable"
        return self.view()


@pytest.fixture
def service():
    controls = FakeControls()
    controls.calls = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(controls))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, controls
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def request(service, method, path, *, origin="http://127.0.0.1:8891", token="safe-session-token", headers=None, body=None):
    server, _ = service
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        connection.request(method, path, body=body,
                           headers={"Origin": origin, "X-Supervisor-Token": token, **(headers or {})})
        response = connection.getresponse()
        result = response.read()
        return response.status, json.loads(result) if result else None
    finally:
        connection.close()


def test_matching_frontend_can_disable_and_reenable_without_any_solver_action(service):
    assert request(service, "GET", "/status")[1]["enabled"]
    assert request(service, "POST", "/disable") == (200, {"enabled": False, "status": "PROCESS_PRESENT"})
    assert request(service, "GET", "/status")[1]["enabled"] is False
    assert request(service, "POST", "/enable")[1]["enabled"]
    assert service[1].calls == ["disable", "enable"]


@pytest.mark.parametrize("origin,token,headers", [
    ("https://attacker.example", "safe-session-token", {}),
    ("http://127.0.0.1:8868", "safe-session-token", {}),
    ("null", "safe-session-token", {}),
    ("", "safe-session-token", {}),
    ("http://127.0.0.1:8891", "wrong", {}),
    ("http://127.0.0.1:8891", "safe-session-token", {"Host": "rebind.example"}),
])
def test_write_rejects_cross_controller_foreign_origin_nonce_and_rebinding(service, origin, token, headers):
    assert request(service, "POST", "/disable", origin=origin, token=token, headers=headers)[0] == 403
    assert service[1].calls == []


def test_other_local_frontend_is_read_only(service):
    assert request(service, "GET", "/status", origin="http://127.0.0.1:8868")[0] == 200
    assert request(service, "OPTIONS", "/disable", origin="http://127.0.0.1:8868",
                   headers={"Access-Control-Request-Method": "POST"})[0] == 403


@pytest.mark.parametrize("method", ["GET", "OPTIONS"])
def test_foreign_site_cannot_read_status_even_if_it_knows_nonce(service, method):
    assert request(service, method, "/status", origin="https://attacker.example",
                   headers={"Access-Control-Request-Method": "GET"})[0] == 403


def test_no_arbitrary_command_path_or_request_payload(service):
    assert request(service, "POST", "/restart")[0] == 404
    assert request(service, "POST", "/disable", body='{"operation":"other"}')[0] == 400
    assert service[1].calls == []


def test_failed_action_returns_conflict_not_success(service):
    def blocked(action):
        raise ValueError("blocked settings")
    service[1].action = blocked
    assert request(service, "POST", "/enable") == (409, {"error": "blocked settings"})


@pytest.mark.parametrize("origin", ["http://127.0.0.1.evil:8891", "https://127.0.0.1:8891",
                                   "http://user@127.0.0.1:8891", "http://127.0.0.1:8891/path"])
def test_origin_validation(origin):
    assert not local_origin(origin)


def test_cli_action_has_fixed_program_and_operation(monkeypatch, tmp_path):
    controls = object.__new__(Controls)
    controls.settings = {"python": "configured-python"}
    controls.operation_path = tmp_path / "operation.json"
    controls.view = lambda: {"enabled": False}
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["timeout"] == 20
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("tools.research.supervisor_ui.subprocess.run", run)
    assert controls.action("disable") == {"enabled": False}
    assert calls[0][-3:] == ["disable", "--operation", str(controls.operation_path)]
    with pytest.raises(ValueError):
        controls.action("run")
    assert len(calls) == 1
