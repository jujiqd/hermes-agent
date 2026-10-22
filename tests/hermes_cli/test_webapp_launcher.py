"""``hermes webapp`` opens the browser-hosted Desktop that the gateway serves.

It builds the Webapp bundle when stale, starts the gateway that serves the current profile (the default
gateway for a profile it serves, else the profile's own), asks that gateway for a one-use launch link
over the control socket and opens it. It never serves anything itself.
"""
from argparse import Namespace
from pathlib import Path

import pytest

from hermes_cli import webapp_launcher as launcher

LINK = "http://127.0.0.1:9120/webapp/launch#ticket=" + "t" * 43


def _home(path: Path, config: str = "") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.yaml").write_text(config, encoding="utf-8")
    return path


def _args(**overrides) -> Namespace:
    values = {"no_open": False, "status": False, "sign_out": False, "build_only": False,
              "force_build": False, "skip_build": False}
    values.update(overrides)
    return Namespace(**values)


@pytest.fixture
def world(monkeypatch, tmp_path):
    """The launcher's side effects, recorded; the control socket answers from ``answers``."""
    calls = {"build": 0, "ensure": [], "control": [], "opened": []}
    answers = {"webapp-launch": {"ok": True, "result": {"url": LINK, "private": False, "expires_in_seconds": 60}},
               "webapp-status": {"ok": True, "result": {"state": "serving", "url": LINK.split("/webapp")[0],
                                                         "reason": None}},
               "webapp-sign-out": {"ok": True, "result": {"signed_out": True}}}

    def build(args):
        calls["build"] += 1
        return tmp_path / "dist-webapp"

    def control(home, verb, params=None):
        calls["control"].append((Path(home), verb))
        calls.setdefault("params", []).append(params or {})
        answer = answers[verb]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(launcher, "_build", build)
    monkeypatch.setattr(launcher, "_ensure", lambda home: calls["ensure"].append(Path(home)))
    monkeypatch.setattr(launcher, "_control", control)
    monkeypatch.setattr(launcher, "_open", lambda url: calls["opened"].append(url) or True)
    root = _home(tmp_path / "root", "webapp:\n  enabled: true\n")
    monkeypatch.setenv("HERMES_HOME", str(root))
    return {"calls": calls, "answers": answers, "root": root, "tmp": tmp_path, "monkeypatch": monkeypatch}


def _use_home(world, home):
    world["monkeypatch"].setenv("HERMES_HOME", str(home))


def test_the_webapp_opens_from_a_one_use_link_its_gateway_mints(world, capsys):
    assert launcher.cmd_webapp(_args()) == 0
    calls = world["calls"]
    assert calls["build"] == 1
    assert calls["ensure"] == [world["root"]]
    assert calls["control"] == [(world["root"], "webapp-launch")]
    assert calls["opened"] == [LINK]
    out = capsys.readouterr().out
    assert "Opened the Webapp in your browser" in out
    assert "ticket=" not in out


def test_a_named_profile_opens_the_webapp_of_the_default_gateway_on_that_profile(world):
    profile = _home(world["root"] / "profiles" / "work")
    _use_home(world, profile)
    assert launcher.cmd_webapp(_args()) == 0
    assert world["calls"]["ensure"] == [world["root"]]
    assert world["calls"]["control"] == [(world["root"], "webapp-launch")]
    assert world["calls"]["params"] == [{"profile": "work"}]


def test_the_default_profile_opens_without_a_profile_choice(world):
    assert launcher.cmd_webapp(_args()) == 0
    assert world["calls"]["params"] == [{}]


def test_a_standalone_profile_opens_the_webapp_of_its_own_gateway(world):
    profile = _home(world["root"] / "profiles" / "solo",
                    "gateway:\n  standalone: true\nwebapp:\n  enabled: true\n")
    _use_home(world, profile)
    assert launcher.cmd_webapp(_args()) == 0
    assert world["calls"]["ensure"] == [profile]


def test_the_launcher_says_how_to_turn_the_webapp_on(world, capsys):
    (world["root"] / "config.yaml").write_text("", encoding="utf-8")
    assert launcher.cmd_webapp(_args()) == 1
    out = capsys.readouterr().out
    assert "webapp.enabled: true" in out and str(world["root"] / "config.yaml") in out
    assert (world["calls"]["build"], world["calls"]["ensure"]) == (0, [])


def test_a_gateway_started_before_the_webapp_was_turned_on_asks_for_a_restart(world, capsys):
    world["answers"]["webapp-launch"] = {"ok": False, "error": "RuntimeError: The Webapp is off. Set ..."}
    world["answers"]["webapp-status"] = {"ok": True, "result": {"state": "off", "url": None, "reason": None}}
    assert launcher.cmd_webapp(_args()) == 1
    out = capsys.readouterr().out
    assert "hermes gateway restart" in out
    assert world["calls"]["opened"] == []


def test_a_webapp_the_gateway_could_not_serve_reports_why_and_how_to_retry(world, capsys):
    # The gateway reads the Webapp's settings and sign-in providers when it starts, so a fix only
    # takes effect after a restart.
    reason = "could not listen on 127.0.0.1:9120 (Address already in use)"
    world["answers"]["webapp-launch"] = {"ok": False, "error": f"RuntimeError: The Webapp is unavailable: {reason}"}
    world["answers"]["webapp-status"] = {"ok": True, "result": {"state": "unavailable", "url": None,
                                                               "reason": reason}}
    assert launcher.cmd_webapp(_args()) == 1
    out = capsys.readouterr().out
    assert reason in out and "hermes gateway restart" in out
    assert launcher.cmd_webapp(_args(status=True)) == 0
    out = capsys.readouterr().out
    assert reason in out and "hermes gateway restart" in out


def test_behind_the_dashboard_sign_in_the_launcher_opens_the_webapp_to_sign_in(world, capsys):
    url = "http://127.0.0.1:9120/"
    world["answers"]["webapp-launch"] = {"ok": True, "result": {
        "url": url, "private": False, "expires_in_seconds": None, "sign_in": True}}
    assert launcher.cmd_webapp(_args()) == 0
    assert world["calls"]["opened"] == [url]
    assert "sign in" in capsys.readouterr().out.lower()
    assert launcher.cmd_webapp(_args(no_open=True)) == 0
    out = capsys.readouterr().out
    assert url in out and "sign in" in out.lower() and "one-use" not in out


def test_no_open_prints_the_link_instead(world, capsys):
    assert launcher.cmd_webapp(_args(no_open=True)) == 0
    assert world["calls"]["opened"] == []
    out = capsys.readouterr().out
    assert LINK in out and "60 seconds" in out


def test_a_browser_that_will_not_open_leaves_the_link_on_screen(world, capsys):
    world["monkeypatch"].setattr(launcher, "_open", lambda url: False)
    assert launcher.cmd_webapp(_args()) == 0
    assert LINK in capsys.readouterr().out


def test_build_only_builds_without_a_gateway(world):
    assert launcher.cmd_webapp(_args(build_only=True)) == 0
    assert (world["calls"]["build"], world["calls"]["ensure"], world["calls"]["control"]) == (1, [], [])


def test_status_reads_the_running_gateway_without_starting_one(world, capsys):
    assert launcher.cmd_webapp(_args(status=True)) == 0
    assert world["calls"]["ensure"] == []
    assert world["calls"]["control"] == [(world["root"], "webapp-status")]
    assert "http://127.0.0.1:9120" in capsys.readouterr().out


def test_status_with_no_gateway_running_says_so(world, capsys):
    world["answers"]["webapp-status"] = launcher.GatewayUnreachable("no gateway")
    assert launcher.cmd_webapp(_args(status=True)) == 1
    assert "gateway is not running" in capsys.readouterr().out


def test_status_with_no_gateway_running_and_the_webapp_off_says_how_to_turn_it_on(world, capsys):
    (world["root"] / "config.yaml").write_text("", encoding="utf-8")
    world["answers"]["webapp-status"] = launcher.GatewayUnreachable("no gateway")
    assert launcher.cmd_webapp(_args(status=True)) == 1
    out = capsys.readouterr().out
    assert "webapp.enabled: true" in out and str(world["root"] / "config.yaml") in out
    assert "Run hermes webapp" not in out


def test_sign_out_replaces_the_browser_credential_on_the_running_gateway(world, capsys):
    assert launcher.cmd_webapp(_args(sign_out=True)) == 0
    assert world["calls"]["control"] == [(world["root"], "webapp-sign-out")]
    assert world["calls"]["ensure"] == []
    assert "Signed out" in capsys.readouterr().out


def test_a_gateway_that_will_not_start_is_reported(world, capsys):
    def refuse(home):
        raise launcher.GatewayUnreachable("The gateway did not start (inaccessible: lock owned by another user).")

    world["monkeypatch"].setattr(launcher, "_ensure", refuse)
    assert launcher.cmd_webapp(_args()) == 1
    assert "lock owned by another user" in capsys.readouterr().out
    assert world["calls"]["control"] == []


def test_signing_out_with_no_gateway_running_still_replaces_the_stored_credential(world, capsys):
    from gateway.webapp_listener import TOKEN_PATH, browser_session_token
    before = browser_session_token(world["root"])
    world["answers"]["webapp-sign-out"] = launcher.GatewayUnreachable("no gateway")
    assert launcher.cmd_webapp(_args(sign_out=True)) == 0
    assert (world["root"] / TOKEN_PATH).read_text().strip() != before
    assert "Signed out" in capsys.readouterr().out


def test_the_webapp_command_takes_one_action_at_a_time():
    import argparse
    from hermes_cli.subcommands.webapp import build_webapp_parser
    parser = argparse.ArgumentParser()
    seen = []
    build_webapp_parser(parser.add_subparsers(), cmd_webapp=seen.append)
    args = parser.parse_args(["webapp", "--no-open", "--force-build"])
    args.func(args)
    assert vars(seen[0]) | {"func": None} == vars(_args(no_open=True, force_build=True)) | {"func": None}
    for clash in (["--status", "--sign-out"], ["--status", "--build-only"], ["--sign-out", "--build-only"]):
        with pytest.raises(SystemExit):
            parser.parse_args(["webapp", *clash])


def test_a_private_link_is_printed_for_the_user_and_never_handed_to_a_browser_launcher(world, capsys):
    private = "http://127.0.0.1:9120/#hermes-session=" + "s" * 43
    world["answers"]["webapp-launch"] = {"ok": True, "result": {"url": private, "private": True,
                                                                "expires_in_seconds": None}}
    assert launcher.cmd_webapp(_args()) == 0
    assert world["calls"]["opened"] == []
    out = capsys.readouterr().out
    assert private in out and "keep it private" in out
