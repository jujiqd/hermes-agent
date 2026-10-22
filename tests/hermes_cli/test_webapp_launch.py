"""The private launch ticket crosses a browser launcher's argv, so only the server user may spend it.

Minting the link and opening the browser belong to whatever launches the Webapp; these tests cover
the handoff route the ticket is spent at (``/webapp/window-session``).
"""
import os

import pytest


@pytest.mark.platforms("linux")
def test_launch_ticket_is_spent_only_over_the_server_users_own_connection(monkeypatch):
    """Linux publishes every process's argv, so another local user can read a launch ticket
    out of the browser launcher before the browser spends it. That user's connection is
    refused, and the refusal does not burn the ticket for the operator's browser."""
    from fastapi.testclient import TestClient
    from hermes_cli import web_server as server
    from hermes_cli.web_routers import webapp

    monkeypatch.setattr(server.app.state, "ui_surface", "webapp", raising=False)
    monkeypatch.setattr(server.app.state, "auth_required", False, raising=False)
    monkeypatch.setattr(server.app.state, "bound_host", "127.0.0.1", raising=False)
    monkeypatch.setattr(server.app.state, "webapp_window_tickets", {}, raising=False)
    monkeypatch.setattr(server, "_SESSION_TOKEN", "a" * 43)
    client = TestClient(server.app, base_url="http://127.0.0.1")
    headers = {"Origin": "http://127.0.0.1", "X-Hermes-Window-Ticket": webapp.mint_launch_ticket(server.app.state)}

    own_uid = os.getuid()  # windows-footgun: ok — platforms("linux") test
    monkeypatch.setattr(webapp, "_loopback_peer_uid", lambda client, server: own_uid + 1)
    stolen = client.post("/webapp/window-session", headers=headers)
    assert stolen.status_code == 403 and "a" * 43 not in stolen.text
    monkeypatch.setattr(webapp, "_loopback_peer_uid", lambda client, server: own_uid)
    granted = client.post("/webapp/window-session", headers=headers)
    assert granted.status_code == 200 and granted.json()["token"] == "a" * 43


@pytest.mark.platforms("macos")
def test_macos_launch_handoff_fails_closed_without_consuming_child_window_authority(monkeypatch):
    """An argv launch ticket is unusable until macOS has an authenticated OS handoff.

    This native platform contract makes no claim about cross-account argv visibility.
    Authenticated child-window tickets never pass through a launcher and still work.
    """
    from fastapi.testclient import TestClient
    from hermes_cli import web_server as server
    from hermes_cli.web_routers import webapp

    monkeypatch.setattr(server.app.state, "ui_surface", "webapp", raising=False)
    monkeypatch.setattr(server.app.state, "auth_required", False, raising=False)
    monkeypatch.setattr(server.app.state, "bound_host", "127.0.0.1", raising=False)
    monkeypatch.setattr(server.app.state, "webapp_window_tickets", {}, raising=False)
    monkeypatch.setattr(server, "_SESSION_TOKEN", "a" * 43)
    client = TestClient(server.app, base_url="http://127.0.0.1")
    try:
        launch = webapp.mint_launch_ticket(server.app.state)
        headers = {"Origin": "http://127.0.0.1", "X-Hermes-Window-Ticket": launch}
        for _ in range(2):
            denied = client.post("/webapp/window-session", headers=headers)
            assert denied.status_code == 403 and server._SESSION_TOKEN not in denied.text
            assert launch in server.app.state.webapp_window_tickets

        issued = client.post("/api/webapp/window-ticket", headers={
            server._SESSION_HEADER_NAME: server._SESSION_TOKEN,
        })
        assert issued.status_code == 200
        headers["X-Hermes-Window-Ticket"] = issued.json()["ticket"]
        assert client.post("/webapp/window-session", headers=headers).json() == {"token": server._SESSION_TOKEN}
        assert client.post("/webapp/window-session", headers=headers).status_code == 403
    finally:
        client.close()
