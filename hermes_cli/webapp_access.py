"""Remote access to the gateway-served Webapp, for Desktop's Web Access pane.

The gateway serves the Webapp (``gateway.webapp_listener``) from the ``webapp:`` block of its home's
``config.yaml``, read when it starts, so this writes that home's config and the caller restarts the
gateway. Sign-in is the user's Nous account (a self-hosted portal client registered with the right
callback); a gated bind without it would keep the Webapp off. Two shapes:

- ``lan``: ``webapp.host: 0.0.0.0``, opened at ``http://<this machine's LAN address>:<port>``; the
  wildcard bind engages the sign-in gate and the callback is rebuilt from each request.
- ``public``: an HTTPS URL the user already runs that forwards to ``127.0.0.1:<port>``.
  ``dashboard.public_url`` engages the gate on the loopback bind and fixes the callback.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from gateway.webapp_listener import DEFAULT_PORT

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_PUBLIC_URL_ENV = "HERMES_DASHBOARD_PUBLIC_URL"
_CLIENT_ID_ENV = "HERMES_DASHBOARD_OAUTH_CLIENT_ID"


class WebappAccessError(RuntimeError):
    """Remote access cannot be set up as asked; ``str(exc)`` is the user-facing reason."""


def lan_address() -> Optional[str]:
    """This machine's primary LAN IPv4 address, or None. Connecting a UDP socket only asks the kernel
    which interface routes to a non-local address; no packet is sent."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            address = probe.getsockname()[0]
    except OSError:
        return None
    return None if address.startswith("127.") or address == "0.0.0.0" else address


def _public_url(raw: Optional[str]) -> str:
    """``https://host[:port][/prefix]`` without a trailing slash, or WebappAccessError."""
    value = (raw or "").strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.hostname in _LOOPBACK_HOSTS:
        raise WebappAccessError("The public URL must be an https:// address other devices use.")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise WebappAccessError("The public URL cannot carry credentials, a query or a fragment.")
    return value


def gateway_home() -> Path:
    """The home whose gateway serves the current one; its config holds the Webapp's settings."""
    from hermes_cli.webapp_launcher import _gateway_home
    from hermes_constants import get_hermes_home

    return _gateway_home(get_hermes_home())


def nous_signed_in() -> bool:
    """Whether this home holds a Nous account to register sign-in under (a free-tier guest has none).
    Refresh-free: it reads the auth store and never spends a refresh token."""
    from hermes_cli.auth_nous import get_nous_auth_status_local

    status = get_nous_auth_status_local()
    return bool(status.get("logged_in") and not status.get("free_tier"))


def _register_nous_sign_in(callback_url: str) -> None:
    """Register (or update in place) this home's portal client with *callback_url*, as
    ``hermes dashboard register --redirect-uri`` does."""
    from hermes_cli.auth import resolve_nous_access_token
    from hermes_cli.config import save_env_value
    from hermes_cli.dashboard_register import (
        _env_value,
        _generate_dashboard_name,
        _register_self_hosted_client,
        _resolve_portal_base_url,
    )

    existing = (_env_value(_CLIENT_ID_ENV) or "").strip() or None
    try:
        result = _register_self_hosted_client(
            access_token=resolve_nous_access_token(),
            portal_base_url=_resolve_portal_base_url(os.environ.get("HERMES_DASHBOARD_PORTAL_URL")),
            name=None if existing else _generate_dashboard_name(),
            custom_redirect_uri=callback_url, existing_client_id=existing)
    except Exception as exc:
        raise WebappAccessError(f"Couldn't register Nous sign-in: {exc}") from exc
    save_env_value(_CLIENT_ID_ENV, str(result["client_id"]))


def register(mode: str, public_url: Optional[str] = None) -> tuple[str, str]:
    """Register Nous sign-in for *mode*; returns the ``(host, public_url)`` for :func:`serve`.

    Re-registered on every start, so the callback follows a changed LAN address or URL. Writes no
    config: it waits on the portal, so callers do it before taking the config lock."""
    if mode == "lan":
        address = lan_address()
        if address is None:
            raise WebappAccessError("This machine has no network address other devices can reach.")
        host, url, pinned = "0.0.0.0", f"http://{address}:{DEFAULT_PORT}", ""
    elif mode == "public":
        host, url = "127.0.0.1", _public_url(public_url)
        pinned = url
    else:
        raise WebappAccessError(f"Unknown access mode {mode!r}.")
    if not nous_signed_in():
        raise WebappAccessError("Sign in to your Nous account under Providers first.")
    _register_nous_sign_in(f"{url}/auth/callback")
    return host, pinned


def serve(host: str, public_url: str) -> None:
    """Serve the Webapp on *host* from the gateway's next start. Call :func:`register` first."""
    _write_config(enabled=True, host=host, public_url=public_url)


def turn_off() -> None:
    """Stop serving the Webapp from the gateway's next start."""
    _write_config(enabled=False)


def _write_config(*, enabled: bool, host: str = "", public_url: str = "") -> None:
    """The ``webapp:`` block and ``dashboard.public_url``, which gates the gateway's listener and so goes
    with the Webapp. A ``.env`` copy of the URL would shadow it (env wins), so that goes too."""
    from hermes_cli.config import load_config, remove_env_value, save_config

    cfg = load_config()
    webapp = cfg.get("webapp") if isinstance(cfg.get("webapp"), dict) else {}
    webapp.update(enabled=enabled, **({"host": host, "port": DEFAULT_PORT} if enabled else {}))
    cfg["webapp"] = webapp
    dashboard = cfg.setdefault("dashboard", {})
    if public_url:
        dashboard["public_url"] = public_url
    else:
        dashboard.pop("public_url", None)
    save_config(cfg)
    remove_env_value(_PUBLIC_URL_ENV)


def _gateway_state(home: Path) -> dict:
    """What *home*'s gateway serves now (``serving``, ``off``, ``unavailable`` with a ``reason``, or
    ``stopped`` when none answers). It reads the config at start, so it can lag until a restart."""
    from hermes_cli.webapp_launcher import GatewayUnreachable, _control

    try:
        response = _control(home, "webapp-status")
    except GatewayUnreachable:
        return {"state": "stopped", "url": None, "reason": None}
    if not response.get("ok"):
        return {"state": "unavailable", "url": None, "reason": str(response.get("error") or "")}
    return dict(response["result"])


def access_status() -> dict:
    """Everything the Web Access pane shows, read for the gateway home in scope."""
    from gateway.webapp_listener import _is_wildcard, webapp_settings
    from hermes_cli.dashboard_auth.prefix import resolve_public_url

    home = gateway_home()
    settings = webapp_settings(home)
    public_url = resolve_public_url()
    return {
        "enabled": settings.enabled,
        "mode": ("lan" if _is_wildcard(settings.host) else "public") if settings.enabled else None,
        "port": settings.port,
        "gateway": _gateway_state(home),
        "lan_address": lan_address(),
        "public_url": public_url,
        "nous_signed_in": nous_signed_in(),
    }
