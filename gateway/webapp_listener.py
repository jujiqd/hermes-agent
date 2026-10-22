"""The browser-hosted Desktop (Webapp) on the gateway's own HTTP listener.

``webapp.enabled`` in the gateway home's ``config.yaml`` turns it on. The gateway then binds its one
listener to ``webapp.host``/``webapp.port`` (a stable port, so the browser's URL survives restarts) and
its dashboard mount serves the Webapp bundle. ``webapp.host`` is a loopback address or a wildcard
(``0.0.0.0``/``::``), and a wildcard bind is gated by dashboard sign-in like any non-loopback listener.
Native clients (Desktop, the CLI, Ink) dial the loopback address this module derives from the bind.

The browser's credential is the dashboard session token. With the Webapp on, the gateway keeps that
token in a user-only file in its home, so open tabs keep working across a gateway restart; signing out
replaces the file.
"""
from __future__ import annotations

import ipaddress
import logging
import re
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9120
TOKEN_PATH = Path("webapp") / "session-token"
# secrets.token_urlsafe(32); the launch page refuses any other shape.
_TOKEN_FORMAT = re.compile(r"[A-Za-z0-9_-]{43}")


@dataclass(frozen=True)
class WebappSettings:
    enabled: bool = False
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    @property
    def bind(self) -> tuple[str, int]:
        """The listener's bind address: the configured one with the Webapp on, else a private
        loopback listener on an ephemeral port (main's default)."""
        return (self.host, self.port) if self.enabled else (DEFAULT_HOST, 0)


@dataclass(frozen=True)
class WebappMount:
    """What the gateway's dashboard mount needs to serve the Webapp: the built bundle and the home
    whose browser credential it uses."""
    dist: Path
    home: Path


def _config_document(home: Path) -> dict:
    """*home*'s config: the merged one (managed overlay, ``${ENV}`` expansion) for this process's own
    home, which is always the case in the gateway; otherwise that home's file as written, which only
    ``hermes webapp`` reads, about the gateway it targets, before asking that gateway itself."""
    from hermes_cli.config import load_config_readonly, read_user_config_raw
    from hermes_constants import get_hermes_home
    try:
        own = home.resolve() == Path(get_hermes_home()).resolve()
    except OSError:
        own = False
    return load_config_readonly() if own else read_user_config_raw(home / "config.yaml")


def webapp_settings(home) -> WebappSettings:
    """``webapp:`` from *home*'s config. A missing, unreadable or malformed block reads as off, so a
    typo never exposes the listener."""
    path = Path(home) / "config.yaml"
    from ruamel.yaml.error import YAMLError
    try:
        document = _config_document(Path(home))
    except (OSError, ValueError, YAMLError) as exc:  # the gateway's own config load reports it
        logger.warning("Webapp stays off: %s could not be read (%s)", path, exc)
        return WebappSettings()
    block = document.get("webapp") if isinstance(document, dict) else None
    if block is None:
        return WebappSettings()
    if not isinstance(block, dict):
        logger.warning("Webapp stays off: webapp in %s must be a mapping", path)
        return WebappSettings()
    enabled = block.get("enabled", False)
    if enabled is False:
        return WebappSettings()
    if enabled is not True:
        logger.warning("Webapp stays off: webapp.enabled must be true or false in %s", path)
        return WebappSettings()
    host = block.get("host", DEFAULT_HOST)
    port = block.get("port", DEFAULT_PORT)
    if not isinstance(host, str) or not (_is_loopback(host.strip()) or _is_wildcard(host.strip())):
        logger.warning("Webapp stays off: webapp.host must be a loopback address, 0.0.0.0 or :: in %s", path)
        return WebappSettings()
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        logger.warning("Webapp stays off: webapp.port must be a port number (1-65535) in %s", path)
        return WebappSettings()
    return WebappSettings(enabled=True, host=host.strip(), port=port)


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _is_wildcard(host: str) -> bool:
    return host in {"0.0.0.0", "::"}


def dial_host(bind_host: str) -> str:
    """The loopback address native clients dial for a listener bound to *bind_host*."""
    if _is_loopback(bind_host):
        return bind_host
    return "::1" if bind_host == "::" else "127.0.0.1"


def dial_origin(bind_host: str, port: int) -> str:
    """The ``api_origin`` native clients get for a listener bound to *bind_host*."""
    host = dial_host(bind_host)
    return f"http://[{host}]:{port}" if ":" in host else f"http://{host}:{port}"


def listener_plan(home) -> tuple[str, int, WebappMount | None]:
    """The gateway listener's ``(host, port, webapp)`` for the gateway serving *home*."""
    settings = webapp_settings(home)
    if not settings.enabled:
        return (*settings.bind, None)
    from hermes_cli.config import get_project_root
    from hermes_cli.webapp import webapp_dist_dir
    return (*settings.bind, WebappMount(dist=webapp_dist_dir(get_project_root()), home=Path(home)))


def browser_session_token(home, *, rotate: bool = False) -> str:
    """The dashboard session token a Webapp browser holds, kept user-only in *home*.

    Created on first use; *rotate* replaces it, which signs every open tab out."""
    from utils import atomic_write_text

    path = Path(home) / TOKEN_PATH
    if not rotate:
        try:
            token = path.read_text(encoding="utf-8-sig").strip()
        except OSError:
            token = ""
        if _TOKEN_FORMAT.fullmatch(token):
            return token
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    atomic_write_text(path, token + "\n", mode=0o600)
    return token


def _one_use_links_work() -> bool:
    """Whether a browser can redeem a one-use launch link here. Redemption needs proof that the
    browser's connection belongs to the gateway's OS user (``web_routers.webapp._peer_is_server_user``),
    which macOS cannot give, and a browser launcher's arguments are not private to the user there."""
    return sys.platform != "darwin"


def register_control_verbs(runner, home) -> None:
    """The private control-socket verbs ``hermes webapp`` uses; only an authenticated same-user peer
    reaches them. ``webapp-launch`` returns a one-use launch link, so the credential crosses neither
    the socket nor a browser's argv; where such a link cannot be redeemed (macOS) it returns the
    private credential link instead, for the user to open by hand. ``webapp-sign-out`` replaces the
    browser credential and closes the browser sockets it opened."""
    server = getattr(runner, "session_control_server", None)
    if server is None:
        return

    def serving():
        status = runner.webapp_status
        if status["state"] == "off":
            raise RuntimeError("The Webapp is off. Set webapp.enabled: true in config.yaml and restart the gateway.")
        if status["state"] != "serving":
            raise RuntimeError(f"The Webapp is unavailable: {status['reason']}")
        web = getattr(getattr(getattr(runner, "session_api", None), "app", None), "web", None)
        if web is None:
            raise RuntimeError("The Webapp is still starting; try again.")
        return status, web

    def webapp_status(_params, _peer):
        return dict(runner.webapp_status)

    def webapp_launch(params, _peer):
        from urllib.parse import urlencode

        from hermes_cli.web_routers.webapp import LAUNCH_TICKET_TTL_SECONDS, mint_launch_ticket
        from hermes_constants import PROFILE_ID_RE
        profile = params.get("profile")
        if profile is not None and not (isinstance(profile, str) and PROFILE_ID_RE.match(profile)):
            raise ValueError("profile must be a profile name")
        query = f"?profile={profile}" if profile else ""  # the page opens on that profile
        status, web = serving()
        from hermes_cli.web_server_surface import private_launch
        if not private_launch(web.app.state):
            # Behind the dashboard's sign-in the page asks for it; a launch link opens only a private Webapp.
            return {"url": f"{status['url']}/{query}", "private": False, "expires_in_seconds": None, "sign_in": True}
        if not _one_use_links_work():
            return {"url": f"{status['url']}/{query}#hermes-session={web._SESSION_TOKEN}", "private": True,
                    "expires_in_seconds": None}
        fragment = urlencode({"ticket": mint_launch_ticket(web.app.state), **({"query": query} if query else {})})
        return {"url": f"{status['url']}/webapp/launch#{fragment}", "private": False,
                "expires_in_seconds": LAUNCH_TICKET_TTL_SECONDS}

    def webapp_sign_out(_params, _peer):
        from hermes_cli import web_server_file_tickets, web_session_sockets
        _, web = serving()
        web._SESSION_TOKEN = browser_session_token(home, rotate=True)
        # Every tab loses access at once: the sockets and media links the old credential opened end
        # now, not when each tab next reconnects. Native clients never held it and stay connected.
        web_session_sockets.close_all()
        web_server_file_tickets.revoke_all()
        return {"signed_out": True}

    server.private_handlers.update({
        "webapp-status": webapp_status, "webapp-launch": webapp_launch, "webapp-sign-out": webapp_sign_out})
