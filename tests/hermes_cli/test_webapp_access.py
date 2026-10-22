"""Remote Webapp access (``hermes_cli.webapp_access``, ``/api/webapp-access/*``).

Contracts: a public URL gates the gateway's loopback bind until Web Access is stopped, LAN access
registers the LAN callback and unpins a public URL, and nothing is written or restarted without a
Nous account to sign in with.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from hermes_cli import web_server

    c = TestClient(web_server.app, raise_server_exceptions=False)
    c.headers["Authorization"] = f"Bearer {web_server._SESSION_TOKEN}"
    return c


@pytest.fixture()
def restarts(monkeypatch):
    """Capture the gateway restart that applies the config instead of spawning it."""
    import hermes_cli.web_server_gateway as gw

    calls: list[str] = []

    def _restart(profile, *, what, label):
        calls.append(what)
        return {"restart_started": True}

    monkeypatch.setattr(gw, "_restart_gateway_after", _restart)
    return calls


@pytest.fixture()
def nous(monkeypatch):
    """A signed-in Nous account; portal registration is captured (no network)."""
    from hermes_cli import webapp_access

    callbacks: list[str] = []
    monkeypatch.setattr(webapp_access, "nous_signed_in", lambda: True)
    monkeypatch.setattr(webapp_access, "_register_nous_sign_in", callbacks.append)
    monkeypatch.setattr(webapp_access, "lan_address", lambda: "192.168.1.50")
    return callbacks


def _config() -> dict:
    from hermes_cli.config import load_config

    return load_config()


def test_public_url_gates_the_loopback_bind_until_stopped(client, restarts, nous):
    from hermes_cli.web_server_boundary import _dashboard_public_hosts, listener_auth_required

    response = client.post("/api/webapp-access/start", json={"mode": "public", "public_url": "https://hermes.example.test"})

    assert response.status_code == 200, response.text
    assert _config()["webapp"] == {"enabled": True, "host": "127.0.0.1", "port": 9120}
    assert nous == ["https://hermes.example.test/auth/callback"]
    # What the restarted gateway decides for its listener (gateway.run_api.start_gateway_api).
    assert listener_auth_required("127.0.0.1", _dashboard_public_hosts())

    # Stop takes the public URL with it: it would keep gating the gateway's private listener.
    assert client.post("/api/webapp-access/stop").status_code == 200
    assert _config()["webapp"]["enabled"] is False
    assert not listener_auth_required("127.0.0.1", _dashboard_public_hosts())
    assert restarts == ["turning on Web Access", "turning off Web Access"]


def test_lan_access_registers_the_lan_callback_and_unpins_a_public_url(client, restarts, nous):
    from hermes_cli.config import load_env, save_config, save_env_value
    from hermes_cli.dashboard_auth.prefix import resolve_public_url

    # A public URL from an earlier "own URL" setup, and an older .env pin that would shadow it.
    save_config({**_config(), "dashboard": {"public_url": "https://old.example.test"}})
    save_env_value("HERMES_DASHBOARD_PUBLIC_URL", "https://older.example.test")

    assert client.post("/api/webapp-access/start", json={"mode": "lan"}).status_code == 200

    assert nous == ["http://192.168.1.50:9120/auth/callback"]
    assert _config()["webapp"]["host"] == "0.0.0.0"
    assert resolve_public_url() == ""
    assert "HERMES_DASHBOARD_PUBLIC_URL" not in load_env()


def test_start_without_a_nous_account_writes_and_restarts_nothing(client, restarts, nous, monkeypatch):
    from hermes_cli import webapp_access

    monkeypatch.setattr(webapp_access, "nous_signed_in", lambda: False)

    assert client.post("/api/webapp-access/start", json={"mode": "lan"}).status_code == 400
    assert nous == []
    assert restarts == []
    assert not _config().get("webapp", {}).get("enabled")
