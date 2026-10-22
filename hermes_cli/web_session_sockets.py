"""Browser sockets the dashboard session token opens, and how they end when it is replaced.

A browser on the loopback Webapp never puts the session token in a socket URL. An authenticated
request mints a one-use ticket for one socket instead: ``GATEWAY_SOCKET`` (``/api/ws``) or
``HOST_TERMINAL_SOCKET`` (``/api/host-terminal``). A ticket named for one socket opens no other, and
the host terminal opens only with its own ticket. A ticket minted with the session token records that
token's digest and opens nothing once the token is replaced.

Every socket the session token admits, directly or through such a ticket, is tracked here until it
ends, so ``close_all`` (run when ``hermes webapp --sign-out`` replaces the token) closes them all at
once. Sockets admitted on any other credential (a signed-in login, a native client's grant) are never
tracked.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import logging
import threading
import weakref
from typing import Any, Optional

from starlette.websockets import WebSocketDisconnect

_log = logging.getLogger(__name__)

GATEWAY_SOCKET = "gateway"
HOST_TERMINAL_SOCKET = "host-terminal"
#: Sockets that open only with a ticket minted for them, never with a standing credential.
OWN_TICKET_SOCKETS = frozenset({HOST_TERMINAL_SOCKET})
#: What a signed-out tab's sockets are closed with: the same code a refused credential gets.
SIGNED_OUT_CODE = 4401

_lock = threading.Lock()
_live: dict[int, tuple[weakref.ref, asyncio.AbstractEventLoop]] = {}


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _current_digest() -> str:
    from hermes_cli.web_server import _SESSION_TOKEN
    return token_digest(_SESSION_TOKEN)


def ticket_refusal(info: dict[str, Any], socket: Optional[str], *, auth_required: bool) -> Optional[str]:
    """Why a redeemed ticket may not open *socket*, or None when it may.

    A ticket named for a socket opens only that socket; an unnamed ticket opens any socket except
    one that takes only its own ticket. A ticket minted with the session token opens nothing behind
    the sign-in gate, nor once that token is replaced.
    """
    named = info.get("socket")
    if named != socket and (named is not None or socket in OWN_TICKET_SOCKETS):
        return f"ticket for {named or 'any socket'} presented to {socket or 'an unnamed socket'}"
    minted_with = info.get("session_token")
    if minted_with is not None and (auth_required or not hmac.compare_digest(minted_with, _current_digest())):
        return "ticket minted with a replaced session token"
    return None


def track(ws, admitted_with: str) -> None:
    """Keep *ws*, admitted on the session token whose digest is *admitted_with*, until it ends.

    A socket admitted while that token was being replaced closes at once, so ``close_all`` never
    misses one.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # judged outside a server loop: no live socket to close later
        return
    with _lock:
        # Ended sockets are dropped here rather than from a weakref callback, which garbage
        # collection could run while this thread already holds the lock.
        for key in [key for key, (ref, _loop) in _live.items() if ref() is None]:
            del _live[key]
        _live[id(ws)] = (weakref.ref(ws), loop)
    if not hmac.compare_digest(admitted_with, _current_digest()):
        _close_on(ws, loop)


async def _close(ws) -> None:
    # The socket may already be closing or gone; it ends either way.
    with contextlib.suppress(RuntimeError, OSError, WebSocketDisconnect):
        await ws.close(code=SIGNED_OUT_CODE, reason="Signed out")


def _close_on(ws, loop: asyncio.AbstractEventLoop) -> bool:
    if loop.is_closed():
        return False
    asyncio.run_coroutine_threadsafe(_close(ws), loop)
    return True


def close_all() -> int:
    """Close every live socket the session token admitted, each on its own event loop. Safe from any
    thread; returns how many were asked to close."""
    with _lock:
        live = list(_live.values())
        _live.clear()
    closing = sum(_close_on(ws, loop) for ref, loop in live if (ws := ref()) is not None)
    _log.info("Closing %d browser sockets opened with the replaced session token", closing)
    return closing
