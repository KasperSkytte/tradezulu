"""Looking at, and restarting, one account's MetaTrader terminal.

    GET  /api/terminal/{id}          -> can this one be watched, and why not
    WS   /api/terminal/{id}/stream   -> its screen, as RFB over a WebSocket
    POST /api/terminal/{id}/restart  -> stop it; the next cycle brings it back

The screen is a VNC server the provisioner runs on that account's own display,
on the host. A browser cannot speak RFB to a TCP socket, so this relays the
two -- which is all websockify does, and it is not worth a second service to
do it.

Watching and driving are different sockets, not a flag. The provisioner runs
two x11vnc servers on each display -- one ``-viewonly``, one not -- and a
viewer that has not asked for control is connected to the first, which will
not accept a click whatever the browser sends. Nothing here inspects the
stream to decide; there is no filter of mine in the path to have a hole in it.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketState

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import Account, User
from ..security import decode_session_token
from ..services.terminalview import viewer_target

log = logging.getLogger(__name__)

router = APIRouter(prefix="/terminal", tags=["terminal"])

#: How much to move at once. A full-screen redraw of a 1400x1000 display is a
#: few hundred KB and arrives in whatever sized pieces the kernel gives us.
CHUNK = 64 * 1024


def _account(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account")
    return account


@router.get("/{account_id}", dependencies=[Depends(get_current_user)])
def viewable(account_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Whether this account's terminal can be watched, and what to say if not.

    Asked before the socket is opened so the page can explain itself. A
    terminal that is still installing, or one on an install whose provisioner
    has no x11vnc, is a perfectly ordinary state and deserves a sentence
    rather than a failed connection.
    """
    account = _account(db, account_id)
    state = account.terminal_state or {}
    target = viewer_target(state)
    return {
        "account_id": account.id,
        "login": account.login,
        "available": target is not None,
        # Whether this install can hand over a keyboard and mouse at all. An
        # older provisioner runs one server per display and it is view-only,
        # so the page has to know not to offer what cannot be given.
        "can_control": viewer_target(state, control=True) is not None,
        "phase": state.get("phase") or "",
        "message_phase": _phase_message(state),
        "display": state.get("display") or "",
        "message": (
            ""
            if target is not None
            else "No screen is being served for this terminal yet. It is either "
            "still being set up, or x11vnc is not installed beside the "
            "provisioner (apt install x11vnc)."
        ),
    }


@router.post("/{account_id}/restart", dependencies=[Depends(get_current_user)])
def restart(account_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Ask for this terminal to be restarted.

    Recorded rather than done: MetaTrader runs on the host and this does not,
    so the provisioner carries it out on its next pass. It stops the terminal
    and the same reconcile that recovers a crashed one starts it again --
    there is no separate restart path to go wrong.
    """
    account = _account(db, account_id)
    state = dict(account.terminal_state or {})
    # The time it was asked for, which doubles as the token the provisioner
    # compares against the last one it acted on.
    state["restart_requested"] = datetime.now(timezone.utc).isoformat()
    account.terminal_state = state
    db.commit()
    return {"account_id": account.id, "queued": True, "at": state["restart_requested"]}


def _authenticated(websocket: WebSocket, db: Session) -> bool:
    """The same session cookie the rest of the site uses.

    A viewer is a window onto a logged-in trading terminal, so an unauthenticated
    one is refused at the handshake -- before the socket is accepted and before
    anything is connected to on the host.
    """
    token = websocket.cookies.get(settings.cookie_name)
    if not token:
        return False
    payload = decode_session_token(token)
    if not payload:
        return False
    user = db.get(User, int(payload.get("sub", 0)))
    return user is not None and user.token_version == payload.get("ver")


async def _pump(read, write, name: str) -> None:
    """Move bytes one way until either end goes quiet."""
    try:
        while True:
            data = await read()
            if not data:
                return
            await write(data)
    except (WebSocketDisconnect, ConnectionResetError, asyncio.IncompleteReadError):
        return
    except Exception as error:  # noqa: BLE001 - a viewer closing is not a fault
        log.debug("terminal view %s ended: %s", name, error)
        return


def _phase_message(state: dict) -> str:
    """What the screen is showing, for a screen that is showing nothing.

    A terminal that has not been installed yet draws on an empty display, and
    an empty display is black. Black with no explanation reads as a broken
    viewer -- it did here -- so the page is given the words to put over it.
    """
    phase = str(state.get("phase") or "")
    return {
        "installing": "This terminal is still being built. The screen stays "
        "empty until MetaTrader is installed on it.",
        "starting": "MetaTrader is starting. Give it a moment to draw.",
        "quiet": "The terminal was reporting and has stopped. What is on its "
        "screen is the best clue why.",
        "failed": "This terminal was given up on. Its screen is the best clue "
        "why.",
    }.get(phase, "")


@router.websocket("/{account_id}/stream")
async def stream(websocket: WebSocket, account_id: int, control: bool = False) -> None:
    """Relay one account's screen to the browser.

    The RFB protocol is a byte stream in both directions and noVNC speaks it
    over binary WebSocket frames, so this is a splice rather than a
    translation. Nothing is parsed: whatever x11vnc sends is what the canvas
    is drawn from.
    """
    # Checked before the socket is accepted rather than after, and checked
    # here because the HTTP dependency wants a Request. The cookie is on the
    # handshake like any other, so it is the same session and the same rules.
    from ..db import SessionLocal

    with SessionLocal() as db:
        if not _authenticated(websocket, db):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        account = db.get(Account, account_id)
        target = viewer_target(account.terminal_state if account else None, control=control)

    if target is None:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    host, port = target
    try:
        reader, writer = await asyncio.open_connection(host, port)
    except OSError as error:
        log.warning("no screen for account %s at %s:%s: %s", account_id, host, port, error)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    await websocket.accept(subprotocol="binary")
    log.info(
        "%s account %s on %s:%s",
        "driving" if control else "watching", account_id, host, port,
    )

    async def to_browser(data: bytes) -> None:
        await websocket.send_bytes(data)

    async def from_terminal() -> bytes:
        return await reader.read(CHUNK)

    async def from_browser() -> bytes:
        return await websocket.receive_bytes()

    async def to_terminal(data: bytes) -> None:
        # Forwarded whole. On the watching port the far end is -viewonly and
        # drops anything that is not a redraw request; on the control port the
        # user asked for it to arrive.
        writer.write(data)
        await writer.drain()

    try:
        await asyncio.gather(
            _pump(from_terminal, to_browser, "terminal->browser"),
            _pump(from_browser, to_terminal, "browser->terminal"),
        )
    finally:
        writer.close()
        with suppress(OSError):
            await writer.wait_closed()
        if websocket.client_state is WebSocketState.CONNECTED:
            await websocket.close()
