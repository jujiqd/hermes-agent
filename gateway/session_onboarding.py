"""First-run onboarding on the session authority: ``onboarding.start`` and ``onboarding.skip``.

The onboarding chat is an ordinary local Desktop session the authority owns from its first row: the
start creates it here, writes the run record (``agent.onboarding_record``) before any agent is built,
attaches the asking connection and admits the hidden opening turn through the same durable FIFO as a
typed message. The record is what makes it an onboarding chat for every later turn: the ``onboarding``
toolset fold-in (``run_turn``), the scripted greeting and name card and the per-turn note
(``run_turn_runner``), all from ``agent.onboarding_session``.

Before this module the methods fell through to the old sidecar handler (``tui_gateway/
methods_onboarding.py``), which built its own live runtime for the chat, and the window's
``session.resume`` on that chat was refused with ``runtime_coordination_required`` because another
writer held it. ``onboarding.state`` and ``onboarding.set_run`` read and write only config and stay on
the sidecar handler.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from functools import partial

from gateway.session_contract import SessionRef
from hermes_state_runtime import RuntimeStoreError

logger = logging.getLogger(__name__)

ONBOARDING_PROFILE = 'default'  # tui_gateway/methods_onboarding.py::_ONBOARDING_PROFILE


class OnboardingRefusal(RuntimeStoreError):
    """A refusal on the sidecar handler's wire: its JSON-RPC code and human message."""

    def __init__(self, code, message):
        super().__init__('onboarding_refused', detail=message)
        self.wire_code, self.wire_message = code, message


class _NoModelForTheRun(Exception):
    """The claim was blocked and nothing else can carry the run's first chat."""


def handlers(connection):
    return {'onboarding.start': partial(start, connection), 'onboarding.skip': partial(skip, connection)}


def _onboarding_connection(connection):
    """The connection to the profile onboarding runs in: this one, or its sibling on a host-scoped socket."""
    return connection._sibling_for(ONBOARDING_PROFILE) or connection


async def start(connection, ref, params):
    from tui_gateway.contracts.profiles_vault_complete_foreign_subagents import OnboardingStartParams
    from pydantic import ValidationError
    try:
        request = OnboardingStartParams.model_validate(params)
    except ValidationError as exc:
        raise RuntimeStoreError('invalid_params', detail=str(exc)) from exc
    target = _onboarding_connection(connection)
    if target is not connection:
        return await start(target, ref, params)
    if 'session:create' not in connection.actor.capabilities:
        raise RuntimeStoreError('permission_denied')
    authority = connection.authority
    lock = getattr(authority, '_onboarding_start_lock', None)
    if lock is None:
        lock = authority._onboarding_start_lock = asyncio.Lock()
    # Held through the opening's admission: two windows pressing start at once get one chat and one opening.
    async with lock:
        plan = await asyncio.to_thread(_choose_run, authority, request)
        stored = plan['stored'] or await _create_chat(connection)
        await asyncio.to_thread(_settle_runs, authority, request, plan, stored)
        if plan['claimed'] is not None:
            from hermes_cli import free_tier_bootstrap
            await asyncio.to_thread(free_tier_bootstrap.refresh_record)
        _withdraw_setup_cards(authority, [] if request.fresh_launch else plan['replaced'])
        chat = SessionRef(authority.profile_id, stored)
        await connection.resume(chat, {})
        opening = plan['opening'] if plan['stored'] else await asyncio.to_thread(_opening_for, authority, stored)
        if opening is not None:
            # The opening rules ride a hidden user turn; its prelude plays the greeting and the name card.
            run_id = await asyncio.to_thread(_run_id, authority, stored)
            await connection.submit(chat, {'session_id': stored, 'text': opening, 'display_kind': 'hidden',
                                           'submission_id': f'onboarding-opening:{run_id or stored}'})
        return {'session_id': stored, 'stored_session_id': stored, 'resumed': plan['stored'] is not None,
                'run_id': await asyncio.to_thread(_run_id, authority, stored)}


def _choose_run(authority, request):
    """Which chat the run lives in (the open one, or None for a new chat), the facts and the trial
    claim a new chat needs. A refused claim (5079) or a blocked one with nothing else to run on (5080)
    leaves no chat, so the install stays due."""
    from agent.onboarding_facts import read_facts
    from agent.onboarding_flow import Facts
    from agent.onboarding_record import load, open_session_ids
    from agent.onboarding_text import opening_prompt
    from hermes_cli.auth_constants import AuthError
    db = authority.db
    open_ids = open_session_ids(db)
    stored = None if request.rerun or request.fresh_launch else next(iter(open_ids), None)
    plan = {'stored': stored, 'open_ids': open_ids, 'claimed': None, 'facts': None, 'opening': None,
            'replaced': [sid for sid in open_ids if sid != stored]}
    if stored is not None:
        facts = Facts.from_stored(load(db, stored)['facts'])
        # A chat with no messages never got its opening (a restart between start and the first turn).
        if not (db.get_session(stored) or {}).get('message_count'):
            plan['opening'] = opening_prompt(facts)
        plan['facts'] = facts
        return plan
    plan['facts'] = read_facts(facts_source=request.facts_source.value, locale=request.locale)
    if not request.rerun:  # a rerun never claims: it runs on the configured model
        try:
            plan['claimed'] = _claim_before_run(assume_fresh=request.assume_fresh)
        except AuthError as exc:
            # The trial claim failed (portal down, rate limited): no guest and no chat, so the next
            # launch is still a first install and tries again.
            logger.info('onboarding.start: welcome trial not claimed: %s', exc)
            raise OnboardingRefusal(5079, str(exc)) from exc
        except _NoModelForTheRun as exc:
            logger.info('onboarding.start: no chat opened: %s', exc)
            raise OnboardingRefusal(5080, str(exc)) from exc
    return plan


def _claim_before_run(*, assume_fresh):
    """``onboarding.run: true`` on disk before the welcome-trial claim, so a crash after the claim still
    opens onboarding next launch (tui_gateway/methods_onboarding.py::_claim_before_run)."""
    from hermes_cli import anon_auth
    from hermes_cli.onboarding_run import set_run
    from hermes_cli.welcome_trial import claim_desktop_free_tier, provider_configured
    set_run(True)
    claimed = claim_desktop_free_tier(assume_fresh=assume_fresh)
    if claimed is None and not (anon_auth.free_inference_active() or provider_configured()):
        raise _NoModelForTheRun('The welcome trial is not available here, and no provider is set up.')
    return claimed


async def _create_chat(connection):
    """A new local Desktop session owned by the authority from its first row."""
    from gateway.session_local import stage_local_session
    from gateway.session_local_recovery import restore_local_session
    from gateway.session_runtime_workers import tracked_write
    from hermes_state_local import commit_local_session
    authority = connection.authority
    staged = stage_local_session(authority, connection.actor, {'source': 'gui', 'request_id': uuid.uuid4().hex},
                                 client_local=connection.native_owner,
                                 desktop_local=getattr(connection.transport, 'desktop_local', False))
    if not (staged['policy'] or {}).get('model'):
        # Nothing to run the chat on (a rerun before any provider is set up): no chat, the way a blocked
        # claim opens none, instead of a row whose launch policy can never be restored.
        raise OnboardingRefusal(5080, 'No model is set up to run onboarding on.')
    await tracked_write(authority, partial(commit_local_session, authority.db, epoch=authority.epoch, receipt=staged))
    return restore_local_session(authority, staged['session_id']).session_id


def _settle_runs(authority, request, plan, stored):
    """The new chat's record and title, and the end of every other open run. One open run at a time:
    the kept run is open before the others end, so the install flag never closes in between."""
    from agent.onboarding_flow import End
    from agent.onboarding_record import advance, start
    from agent.onboarding_text import CHAT_TITLE
    db = authority.db
    if plan['stored'] is None:
        # The record exists before any agent is built, so the first turn already folds the toolset in.
        start(db, stored, plan['facts'])
    if request.fresh_launch:
        _discard_unfinished_runs(authority, plan['replaced'])
    else:
        for old in plan['replaced']:
            advance(db, old, End('replaced'))
    if plan['stored'] is None:
        # After the discard, so a run started over keeps the title its deleted chat had.
        db.set_session_title(stored, db.get_next_title_in_lineage(CHAT_TITLE))


def _discard_unfinished_runs(authority, stored_ids):
    """A new launch's start: the runs the app was closed on never count as done. A chat nobody holds
    live is deleted the way ``session.delete`` deletes it, which ends its run (``deleted``) and tells
    every window; a chat still live here (a backend that outlived the app) or one the delete refuses
    keeps its messages, and its run ends as ``replaced`` so it is never resumed."""
    from pathlib import Path
    from agent.onboarding_flow import End
    from agent.onboarding_record import advance, delete_chat
    db = authority.db
    sessions_dir = Path(db.db_path).parent / 'sessions'
    for old in stored_ids:
        deleted = False
        if old not in authority.sessions:
            try:
                deleted = delete_chat(db, old, lambda old=old: db.delete_session(
                    old, sessions_dir=sessions_dir, exclude_active_write_guards=True))
            except Exception:
                logger.exception('onboarding.start could not delete unfinished chat %s', old)
        if not deleted:
            advance(db, old, End('replaced'))


def _withdraw_setup_cards(authority, stored_ids):
    """Close the card still waiting in a chat whose run just ended; its answer would be refused."""
    from gateway.session_server_requests import withdraw
    for sid in stored_ids:
        live = authority.sessions.get(sid)
        if live is not None:
            withdraw(live.event_stream, sid, 'setup_beat')


def _opening_for(authority, stored):
    from agent.onboarding_flow import Facts
    from agent.onboarding_record import load
    from agent.onboarding_text import opening_prompt
    if (authority.db.get_session(stored) or {}).get('message_count'):
        return None
    return opening_prompt(Facts.from_stored(load(authority.db, stored)['facts']))


def _run_id(authority, stored):
    from agent.onboarding_record import load
    return (load(authority.db, stored) or {}).get('run_id') or ''


async def skip(connection, ref, params):
    """Skip setup: end the chat's run and close the card that waits. The card's asker reads the
    skipped record when it wakes (``setup_beat``)."""
    from agent.onboarding_flow import End
    from agent.onboarding_record import advance, load
    from gateway.session_runtime_workers import tracked_write
    from gateway.session_server_requests import withdraw
    if set(params) != {'session_id'} or not isinstance(params.get('session_id'), str) or not params['session_id']:
        raise RuntimeStoreError('invalid_params')
    authority = connection.authority
    authority.authorize(connection.actor, ref, 'session:control')
    db = authority.db
    if load(db, db.get_compression_tip(ref.session_id) or ref.session_id) is None:
        return {'skipped': False}
    step = await tracked_write(authority, partial(advance, db, ref.session_id, End('skipped')))
    live = authority.sessions.get(ref.session_id)
    if live is not None:
        withdraw(live.event_stream, ref.session_id, 'setup_beat')
    return {'skipped': bool(step.result.get('skipped_all'))}


def arm_onboarding_turn(agent, owner, history):
    """The onboarding chat's per-turn inputs on an authority-owned local turn: the turn note (which
    card is closed and how to bring it back) appended to the API-only notes, and the scripted opening
    returned for ``run_conversation(prelude=...)``. Nothing for a chat without ``setup_beat``."""
    from agent.onboarding_session import append_turn_note, builds_onboarding, onboarding_prelude, onboarding_turn_note
    if owner is None or not builds_onboarding(agent):
        return None
    from gateway.session_server_requests import waiting
    authority, session_id, _generation = owner
    live = authority.sessions.get(session_id)
    card_waiting = live is not None and waiting(live.event_stream, session_id, 'setup_beat')
    append_turn_note(agent, onboarding_turn_note(agent, history_empty=not history, card_waiting=card_waiting))
    return onboarding_prelude(agent, history)
