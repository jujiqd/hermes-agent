"""Each Webapp socket ticket opens only the socket it was minted for.

The browser never puts its session token in a socket URL. An authenticated request mints a one-use,
short-lived ticket instead: ``POST /api/webapp/gateway-ticket`` for the chat socket (``/api/ws``) and
``POST /api/webapp/terminal-ticket`` for the host terminal (``/api/host-terminal``). A host shell opens
only with a terminal ticket, a chat ticket opens no host shell, a terminal ticket opens no chat socket,
and a ticket minted with a session token that has since been replaced opens nothing.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.hermes_cli.test_web_host_terminal_persistence import IdleBridge, metadata

_TOKEN = "a" * 43
_SESSION = {"X-Hermes-Session-Token": _TOKEN}


def serve_webapp(tmp_path, monkeypatch):
    """The loopback Webapp: ``web_server.app`` mints tickets, a small app serves the host terminal,
    and ``shells`` lists the idle stand-ins it spawns for host shells."""
    from hermes_cli import web_host_terminal, web_server, web_server_chat
    from hermes_cli.web_host_terminal_sessions import host_terminal_lifespan
    from hermes_cli.web_routers.webapp import router

    home = tmp_path / ".hermes"
    home.mkdir()
    (home / "config.yaml").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(web_server.app.state, "ui_surface", "webapp", raising=False)
    monkeypatch.setattr(web_server.app.state, "bound_host", "localhost", raising=False)
    monkeypatch.setattr(web_server.app.state, "auth_required", False, raising=False)
    monkeypatch.setattr(web_server, "_SESSION_TOKEN", _TOKEN)
    monkeypatch.setattr(web_server, "_DASHBOARD_EMBEDDED_CHAT_ENABLED", True)
    monkeypatch.setattr(web_host_terminal, "shell_spec", lambda: (["/bin/sh", "-i"], "sh"))
    shells = []

    def spawn(*_args, **_kwargs):
        shells.append(IdleBridge())
        return shells[-1]

    monkeypatch.setattr(web_server_chat.PtyBridge, "spawn", spawn)
    host = FastAPI(lifespan=host_terminal_lifespan)
    host.include_router(router)
    return SimpleNamespace(server=web_server, client=TestClient(web_server.app, base_url="http://localhost"),
                           host=host, shells=shells)


@pytest.fixture
def webapp(tmp_path, monkeypatch):
    return serve_webapp(tmp_path, monkeypatch)


def _mint(client, kind, headers=_SESSION):
    response = client.post(f"/api/webapp/{kind}-ticket", headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"ticket", "ttl_seconds"} and 0 < body["ttl_seconds"] <= 60
    return body["ticket"]


def _refused(client, url, code=4401, **kwargs):
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(url, **kwargs) as ws:
            ws.receive_text()
    assert closed.value.code == code


def test_a_terminal_ticket_opens_one_host_shell_once(webapp):
    client, host = webapp.client, webapp.host
    assert client.post("/api/webapp/terminal-ticket").status_code == 401
    ticket = _mint(client, "terminal")
    with TestClient(host) as shells:
        with shells.websocket_connect(f"ws://localhost/api/host-terminal?ticket={ticket}") as ws:
            assert metadata(ws)["terminalId"]
        _refused(shells, f"ws://localhost/api/host-terminal?ticket={ticket}")
    assert len(webapp.shells) == 1


def test_the_host_terminal_refuses_the_session_token_and_every_other_ticket(webapp):
    from hermes_cli.dashboard_auth.ws_tickets import mint_ticket

    client, host = webapp.client, webapp.host
    others = [_mint(client, "gateway"), mint_ticket(user_id="legacy-token-owner", provider="session-token")]
    with TestClient(host) as shells:
        _refused(shells, f"ws://localhost/api/host-terminal?token={_TOKEN}")
        for ticket in others:
            _refused(shells, f"ws://localhost/api/host-terminal?ticket={ticket}")
        protocols = ["hermes-gateway-v1", f"hermes-gateway-ticket.{_mint(client, 'gateway')}"]
        _refused(shells, "ws://localhost/api/host-terminal", subprotocols=protocols)
    assert webapp.shells == []


def test_a_terminal_ticket_does_not_open_the_chat_socket(webapp):
    client = webapp.client
    protocols = ["hermes-gateway-v1", f"hermes-gateway-ticket.{_mint(client, 'terminal')}"]
    _refused(client, "ws://localhost/api/ws?native_dial=browser", subprotocols=protocols)
    _refused(client, f"ws://localhost/api/ws?ticket={_mint(client, 'terminal')}")


def test_tickets_minted_before_the_session_token_changed_open_nothing(webapp, monkeypatch):
    server, client, host = webapp.server, webapp.client, webapp.host
    terminal, chat = _mint(client, "terminal"), _mint(client, "gateway")
    monkeypatch.setattr(server, "_SESSION_TOKEN", "b" * 43)
    with TestClient(host) as shells:
        _refused(shells, f"ws://localhost/api/host-terminal?ticket={terminal}")
    _refused(client, f"ws://localhost/api/ws?ticket={chat}")
    assert webapp.shells == []


@pytest.mark.parametrize("surface", ["dashboard", "serve"])
def test_other_surfaces_do_not_mint_terminal_tickets(webapp, monkeypatch, surface):
    server, client = webapp.server, webapp.client
    monkeypatch.setattr(server.app.state, "ui_surface", surface)
    assert client.post("/api/webapp/terminal-ticket", headers=_SESSION).status_code == 404


def test_a_signed_in_browser_opens_its_host_shell_with_a_terminal_ticket(webapp, monkeypatch):
    """Wildcard host: the dashboard's cookie sign-in mints the ticket, and the shell is that login's."""
    from hermes_cli.dashboard_auth import clear_providers, register_provider
    from hermes_cli.dashboard_auth.ws_tickets import _reset_for_tests
    from tests.hermes_cli.conftest_dashboard_auth import StubAuthProvider
    from tests.hermes_cli.test_dashboard_auth_ws_auth import _logged_in

    server, host = webapp.server, webapp.host
    _reset_for_tests()
    clear_providers()
    register_provider(StubAuthProvider())
    monkeypatch.setattr(server.app.state, "bound_host", "fly-app.fly.dev")
    monkeypatch.setattr(server.app.state, "bound_port", 443, raising=False)
    monkeypatch.setattr(server.app.state, "auth_required", True)
    try:
        anonymous = TestClient(server.app, base_url="https://fly-app.fly.dev")
        assert anonymous.post("/api/webapp/terminal-ticket", headers=_SESSION,
                              follow_redirects=False).status_code in (302, 401)
        gated = TestClient(server.app, base_url="https://fly-app.fly.dev")
        _logged_in(gated)
        ticket = _mint(gated, "terminal", headers={})
        generic = gated.post("/api/auth/ws-ticket").json()["ticket"]
        with TestClient(host, base_url="https://fly-app.fly.dev") as shells:
            url = "wss://fly-app.fly.dev/api/host-terminal?ticket="
            with shells.websocket_connect(url + ticket) as ws:
                shell = metadata(ws)["terminalId"]
                assert host.state.host_terminals.owners[shell].identity[0] == "stub"
            _refused(shells, url + generic)
        assert len(webapp.shells) == 1
    finally:
        clear_providers()
        _reset_for_tests()
