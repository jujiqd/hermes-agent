"""The browser-hosted Desktop on the gateway's own listener: config, bind address and browser credential.

``webapp.enabled`` in the gateway home's ``config.yaml`` turns it on; the gateway then binds its one HTTP
listener to ``webapp.port`` on a loopback or wildcard ``webapp.host``, and native clients keep dialling a
loopback address.
"""
import asyncio
import errno
import json
import os
import re
import stat
from types import SimpleNamespace

import pytest

from gateway import webapp_listener as webapp


def _home(tmp_path, config=None):
    home = tmp_path / "home"
    home.mkdir(parents=True)
    if config is not None:
        (home / "config.yaml").write_text(config, encoding="utf-8")
    return home


def test_the_webapp_stays_off_until_config_turns_it_on(tmp_path):
    off = webapp.webapp_settings(_home(tmp_path))
    assert (off.enabled, off.bind) == (False, ("127.0.0.1", 0))


def test_an_enabled_webapp_binds_its_configured_address(tmp_path):
    on = webapp.webapp_settings(_home(tmp_path, "webapp:\n  enabled: true\n  host: 0.0.0.0\n  port: 9555\n"))
    assert (on.enabled, on.bind) == (True, ("0.0.0.0", 9555))
    default = webapp.webapp_settings(_home(tmp_path / "d", "webapp:\n  enabled: true\n"))
    assert default.bind == ("127.0.0.1", webapp.DEFAULT_PORT)


@pytest.mark.parametrize("block", [
    "webapp: yes\n",
    "webapp:\n  enabled: true\n  port: 70000\n",
    "webapp:\n  enabled: true\n  port: http\n",
    "webapp:\n  enabled: true\n  host: ''\n",
    "webapp:\n  enabled: 'true'\n",
    "webapp:\n  enabled: true\n  host: 192.168.1.20\n",
    "webapp:\n  enabled: true\n  host: hermes.example.net\n",
])
def test_a_malformed_webapp_block_keeps_the_listener_private(tmp_path, block):
    settings = webapp.webapp_settings(_home(tmp_path, block))
    assert settings.bind == ("127.0.0.1", 0)


@pytest.mark.parametrize(("bind", "dial"), [
    ("127.0.0.1", "127.0.0.1"),
    ("localhost", "localhost"),
    ("::1", "::1"),
    ("0.0.0.0", "127.0.0.1"),
    ("::", "::1"),
])
def test_native_clients_dial_loopback_whatever_the_browser_bind(bind, dial):
    assert webapp.dial_host(bind) == dial


@pytest.mark.parametrize(("bind", "origin"), [
    ("127.0.0.1", "http://127.0.0.1:9120"),
    ("0.0.0.0", "http://127.0.0.1:9120"),
    ("::", "http://[::1]:9120"),
    ("::1", "http://[::1]:9120"),
])
def test_the_advertised_api_origin_is_the_loopback_dial_address(bind, origin):
    assert webapp.dial_origin(bind, 9120) == origin


def test_a_gateway_restart_keeps_the_browser_credential(tmp_path):
    home = _home(tmp_path)
    first = webapp.browser_session_token(home)
    assert len(first) >= 43
    assert webapp.browser_session_token(home) == first
    if os.name != "nt":
        assert stat.S_IMODE((home / webapp.TOKEN_PATH).stat().st_mode) == 0o600


def test_signing_out_replaces_the_browser_credential(tmp_path):
    home = _home(tmp_path)
    first = webapp.browser_session_token(home)
    second = webapp.browser_session_token(home, rotate=True)
    assert second != first
    assert webapp.browser_session_token(home) == second


@pytest.mark.parametrize("stored", ["short", "x" * 60, "not/url+safe" + "a" * 31])
def test_a_credential_the_browser_would_refuse_is_replaced(tmp_path, stored):
    home = _home(tmp_path)
    (home / webapp.TOKEN_PATH).parent.mkdir(parents=True)
    (home / webapp.TOKEN_PATH).write_text(stored + "\n", encoding="utf-8")
    token = webapp.browser_session_token(home)
    assert token != stored
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)


def _start_runtime_api(monkeypatch, tmp_path, config, *, busy=False, refuse=None):
    from gateway import run_api, run_runtime
    home = _home(tmp_path, config)
    monkeypatch.setenv("HERMES_HOME", str(home))
    calls = []

    async def start(runner, *, host="127.0.0.1", port=0, webapp=None):
        calls.append((host, port, webapp))
        if busy and port:
            raise OSError(errno.EADDRINUSE, "Address already in use")
        if refuse is not None and webapp is not None:
            raise refuse
        return SimpleNamespace(api_origin=f"http://127.0.0.1:{port or 50001}")

    monkeypatch.setattr(run_api, "start_gateway_api", start)
    from gateway.control_socket import GatewayControlServer
    runner = SimpleNamespace(session_runtime_descriptor={}, session_authorities=[],
                             session_control_server=GatewayControlServer(home))
    asyncio.run(run_runtime.start_gateway_runtime_api(runner))
    return runner, calls, home


def _ask(runner, verb, peer="same-user-peer", params=None):
    raw = json.dumps({"protocol": 1, "verb": verb, "id": 1, "params": params or {}}).encode()
    return json.loads(runner.session_control_server.handle_request_line(raw, peer))


def test_the_gateway_listens_on_the_webapp_port_when_enabled(monkeypatch, tmp_path):
    runner, calls, home = _start_runtime_api(monkeypatch, tmp_path, "webapp:\n  enabled: true\n  port: 9555\n")
    [(host, port, mount)] = calls
    assert (host, port) == ("127.0.0.1", 9555)
    assert (mount.home, mount.dist.name) == (home, "dist-webapp")
    assert runner.webapp_status == {"state": "serving", "url": "http://127.0.0.1:9555", "reason": None}


def test_a_busy_webapp_port_still_leaves_native_clients_a_listener(monkeypatch, tmp_path):
    runner, calls, _ = _start_runtime_api(
        monkeypatch, tmp_path, "webapp:\n  enabled: true\n  port: 9555\n", busy=True)
    assert [(host, port) for host, port, _ in calls] == [("127.0.0.1", 9555), ("127.0.0.1", 0)]
    assert calls[1][2] is None
    assert runner.session_runtime_descriptor["api_origin"] == "http://127.0.0.1:50001"
    assert runner.webapp_status["state"] == "unavailable"
    assert "127.0.0.1:9555" in runner.webapp_status["reason"]


def test_a_gateway_without_the_webapp_starts_mains_private_listener(monkeypatch, tmp_path):
    runner, calls, _ = _start_runtime_api(monkeypatch, tmp_path, None)
    assert calls == [("127.0.0.1", 0, None)]
    assert runner.webapp_status == {"state": "off", "url": None, "reason": None}


def test_the_launcher_reads_the_webapp_state_from_its_gateway(monkeypatch, tmp_path):
    off, _, _ = _start_runtime_api(monkeypatch, tmp_path / "off", None)
    assert _ask(off, "webapp-status")["result"] == {"state": "off", "url": None, "reason": None}
    busy, _, _ = _start_runtime_api(
        monkeypatch, tmp_path / "busy", "webapp:\n  enabled: true\n  port: 9555\n", busy=True)
    status = _ask(busy, "webapp-status")["result"]
    assert status["state"] == "unavailable" and "127.0.0.1:9555" in status["reason"]


def test_a_gateway_not_serving_the_webapp_mints_no_launch_link(monkeypatch, tmp_path):
    off, _, _ = _start_runtime_api(monkeypatch, tmp_path / "off", None)
    refused = _ask(off, "webapp-launch")
    assert refused["ok"] is False and "webapp.enabled" in refused["error"]
    busy, _, _ = _start_runtime_api(
        monkeypatch, tmp_path / "busy", "webapp:\n  enabled: true\n  port: 9555\n", busy=True)
    refused = _ask(busy, "webapp-launch")
    assert refused["ok"] is False and "127.0.0.1:9555" in refused["error"]


@pytest.mark.parametrize("verb", ["webapp-status", "webapp-launch", "webapp-sign-out"])
def test_webapp_verbs_answer_only_an_authenticated_same_user_peer(monkeypatch, tmp_path, verb):
    runner, _, _ = _start_runtime_api(monkeypatch, tmp_path, "webapp:\n  enabled: true\n  port: 9555\n")
    refused = _ask(runner, verb, peer=None)
    assert refused["ok"] is False and "PermissionError" in refused["error"]


def test_where_one_use_links_cannot_be_redeemed_the_launcher_gets_the_private_link(monkeypatch, tmp_path):
    monkeypatch.setattr(webapp, "_one_use_links_work", lambda: False)  # macOS
    runner, _, _ = _start_runtime_api(monkeypatch, tmp_path, "webapp:\n  enabled: true\n  port: 9555\n")
    # The gateway mounts the dashboard app as the Webapp surface on a private (loopback) listener.
    web = SimpleNamespace(_SESSION_TOKEN="s" * 43, app=SimpleNamespace(state=SimpleNamespace(ui_surface="webapp")))
    runner.session_api.app = SimpleNamespace(web=web)
    result = _ask(runner, "webapp-launch")["result"]
    assert result == {"url": "http://127.0.0.1:9555/#hermes-session=" + "s" * 43, "private": True,
                      "expires_in_seconds": None}
    assert not getattr(web.app.state, "webapp_window_tickets", None)


def test_behind_the_dashboard_sign_in_the_launcher_gets_the_webapp_address(monkeypatch, tmp_path):
    # The page asks for the sign-in itself; a launch link only works on a private (loopback) Webapp.
    runner, _, _ = _start_runtime_api(
        monkeypatch, tmp_path, "webapp:\n  enabled: true\n  host: 0.0.0.0\n  port: 9555\n")
    state = SimpleNamespace(ui_surface="webapp", auth_required=True)
    runner.session_api.app = SimpleNamespace(web=SimpleNamespace(_SESSION_TOKEN="s" * 43, app=SimpleNamespace(state=state)))
    result = _ask(runner, "webapp-launch", params={"profile": "work"})["result"]
    assert result == {"url": "http://127.0.0.1:9555/?profile=work", "private": False,
                      "expires_in_seconds": None, "sign_in": True}
    assert not getattr(state, "webapp_window_tickets", None)


def _serving_runner(monkeypatch, tmp_path):
    runner, _, _ = _start_runtime_api(monkeypatch, tmp_path, "webapp:\n  enabled: true\n  port: 9555\n")
    # The gateway mounts the dashboard app as the Webapp surface on a private (loopback) listener.
    web = SimpleNamespace(_SESSION_TOKEN="s" * 43, app=SimpleNamespace(state=SimpleNamespace(ui_surface="webapp")))
    runner.session_api.app = SimpleNamespace(web=web)
    return runner


def test_a_launch_link_for_a_named_profile_opens_that_profile(monkeypatch, tmp_path):
    from urllib.parse import parse_qs
    runner = _serving_runner(monkeypatch, tmp_path)
    url = _ask(runner, "webapp-launch", params={"profile": "work"})["result"]["url"]
    page, fragment = url.split("#", 1)
    assert page == "http://127.0.0.1:9555/webapp/launch"
    assert parse_qs(fragment)["query"] == ["?profile=work"]
    monkeypatch.setattr(webapp, "_one_use_links_work", lambda: False)
    private = _ask(runner, "webapp-launch", params={"profile": "work"})["result"]["url"]
    assert private == "http://127.0.0.1:9555/?profile=work#hermes-session=" + "s" * 43


@pytest.mark.parametrize("profile", ["../etc", "a b", "", "x" * 65, 7])
def test_a_launch_link_refuses_a_malformed_profile_name(monkeypatch, tmp_path, profile):
    runner = _serving_runner(monkeypatch, tmp_path)
    refused = _ask(runner, "webapp-launch", params={"profile": profile})
    assert refused["ok"] is False and "profile" in refused["error"]


@pytest.mark.parametrize("refusal", [
    # The dashboard's auth gate refuses a gated bind with no sign-in provider by exiting.
    SystemExit("Refusing to bind dashboard to 0.0.0.0 — the auth gate engages on non-loopback binds "
               "(0.0.0.0), but no auth providers are registered."),
    RuntimeError("gateway API lifespan startup failed"),
])
def test_a_webapp_listener_that_cannot_start_still_leaves_native_clients_a_listener(monkeypatch, tmp_path, refusal):
    runner, calls, _ = _start_runtime_api(
        monkeypatch, tmp_path, "webapp:\n  enabled: true\n  host: 0.0.0.0\n", refuse=refusal)
    assert [(host, port) for host, port, _ in calls] == [("0.0.0.0", webapp.DEFAULT_PORT), ("127.0.0.1", 0)]
    assert runner.webapp_status["state"] == "unavailable"
    assert str(refusal) in runner.webapp_status["reason"]
    assert runner.session_runtime_descriptor["api_origin"] == "http://127.0.0.1:50001"


def test_cancelling_the_gateway_while_the_webapp_listener_starts_cancels_it(monkeypatch, tmp_path):
    with pytest.raises(asyncio.CancelledError):
        _start_runtime_api(monkeypatch, tmp_path, "webapp:\n  enabled: true\n", refuse=asyncio.CancelledError())


@pytest.mark.parametrize("posix", [True, False])
def test_only_posix_lets_the_webapps_fixed_port_bind_again_at_once(monkeypatch, posix):
    # A restarted gateway must take the Webapp's port back while the old connections sit in
    # TIME_WAIT. On Windows SO_REUSEADDR would let another process bind the port, so it stays off.
    import socket

    from gateway import run_api
    monkeypatch.setattr(run_api, "_REUSE_FIXED_PORT", posix)
    with run_api._listener_socket(socket.AF_INET, socket.SOCK_STREAM, 0, webapp.DEFAULT_PORT) as fixed, \
            run_api._listener_socket(socket.AF_INET, socket.SOCK_STREAM, 0, 0) as ephemeral:
        assert bool(fixed.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR)) is posix
        assert not ephemeral.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR)  # main's private listener


def test_the_fixed_port_switch_follows_the_platform():
    from gateway import run_api
    assert run_api._REUSE_FIXED_PORT is (os.name != "nt")


def test_a_fixed_port_binds_again_while_the_last_gateways_connections_linger():
    # The server closing first leaves its side of the connection in TIME_WAIT on the fixed port.
    import socket

    from gateway import run_api
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    first = run_api._listener_socket(socket.AF_INET, socket.SOCK_STREAM, 0, port)
    first.bind(("127.0.0.1", port))
    first.listen()
    client = socket.create_connection(("127.0.0.1", port))
    served, _ = first.accept()
    served.close()
    client.recv(1)
    client.close()
    first.close()
    with run_api._listener_socket(socket.AF_INET, socket.SOCK_STREAM, 0, port) as second:
        second.bind(("127.0.0.1", port))
