"""A finished session's pipe belongs to its reader, not to the finisher (#142193).

``ProcessRegistry._release_finished_handles`` closed the Popen's stdout/stderr as soon as a
session was moved to ``_finished``. A buffered stream's ``close()`` waits for the reader's lock,
and the reader holds that lock for the whole of its blocking ``read()`` — so closing the pipe
from another thread blocks until the read returns. On Windows the read only ends when every
writer of the pipe is gone: a descendant that inherited the pipe (``tail -f`` from a
backgrounded script) keeps it open indefinitely, and the close never returns.

That wedged ``_reconcile_local_exit`` -> ``_move_to_finished`` -> ``_publish_finished`` ->
``_release_finished_handles``, so ``wait_for_pending_completions`` never got past the
reconcile: the bounded one-shot linger never expired, the run never exited, and the
completion notification was never published.

The reader closes its own pipe (via ``_finish_reader``) once its read ends; the finisher must
leave it alone.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time

import pytest


class _Stream:
    """A pipe stand-in that records whether it was closed."""

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _Proc:
    def __init__(self):
        self.stdout = _Stream()
        self.stderr = _Stream()
        self.stdin = _Stream()


def _session(reader):
    import tools.process_registry as pr

    session = pr.ProcessSession(id="proc_reader_pipe", command="stub")
    session.process = _Proc()
    session._reader_thread = reader
    return session


def test_release_finished_handles_leaves_the_reader_its_own_pipe():
    """A live reader owns the pipe: closing it from the finisher blocks on the reader's lock."""
    import tools.process_registry as pr

    registry = pr.ProcessRegistry()
    stop = threading.Event()
    reader = threading.Thread(target=stop.wait, daemon=True)
    reader.start()
    try:
        session = _session(reader)
        registry._release_finished_handles(session)
        assert not session.process.stdout.closed
        assert not session.process.stderr.closed
        # stdin is not the reader's: the write end is released as usual.
        assert session.process.stdin.closed
    finally:
        stop.set()
        reader.join(timeout=5)


def test_release_finished_handles_closes_the_pipe_when_no_reader_holds_it():
    """Without a live reader the pipe is released, as before."""
    import tools.process_registry as pr

    registry = pr.ProcessRegistry()
    session = _session(None)
    registry._release_finished_handles(session)
    assert session.process.stdout.closed
    assert session.process.stderr.closed
    assert session.process.stdin.closed


def test_release_finished_handles_closes_the_pipe_from_the_reader_thread():
    """The reader closes its own pipe when its read ends (the normal exit path)."""
    import tools.process_registry as pr

    registry = pr.ProcessRegistry()
    closed = {}

    def _run():
        session = _session(threading.current_thread())
        registry._release_finished_handles(session)
        closed["stdout"] = session.process.stdout.closed

    reader = threading.Thread(target=_run)
    reader.start()
    reader.join(timeout=5)
    assert closed.get("stdout") is True


@pytest.mark.platforms("windows")
@pytest.mark.live_system_guard_bypass  # the orphan is reparented to init: signalling it is the point
def test_one_shot_linger_completes_with_a_reader_owned_pipe(tmp_path, monkeypatch):
    """The real deadlock: the direct child exits, a descendant keeps the pipe, and the bounded
    one-shot linger must still finish (it never did before #142193 — it blocked inside the
    reconcile, so the run never exited and the completion was never published)."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    import tools.process_registry as pr

    registry = pr.ProcessRegistry()
    # The direct child exits at once and leaves a descendant holding the stdout pipe:
    # the reader is blocked in read() with nothing left to read.
    child = (
        "import subprocess, sys\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "print(p.pid, flush=True)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", child],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace",
    )
    session = registry.adopt_local(proc, command="reader-owned-pipe", cwd=str(tmp_path))
    reader = session._reader_thread
    grandchild_pid = None
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and session.process.poll() is None:
            time.sleep(0.1)
        assert session.process.poll() is not None, "the direct child did not exit"

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not session.output_buffer.strip():
            time.sleep(0.1)
        assert session.output_buffer.strip(), "the reader captured nothing"
        grandchild_pid = int(session.output_buffer.strip().split()[0])
        assert reader is not None and reader.is_alive(), "the reader must still hold the pipe"

        returned = threading.Event()
        result = {}

        def _linger():
            result["value"] = registry.wait_for_pending_completions(timeout=20, poll_interval=0.2)
            returned.set()

        threading.Thread(target=_linger, daemon=True).start()
        assert returned.wait(25), (
            "the one-shot linger blocked closing the reader-owned pipe (#142193)")
        assert session.id in result["value"]["completed"], "the linger must complete the session"
        assert session._completion_event.is_set(), "the completion must be published"
        # The pipe is still the reader's — closing it from the finisher is what deadlocked.
        assert not session.process.stdout.closed
    finally:
        if grandchild_pid:
            try:
                os.kill(grandchild_pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
        if reader is not None:
            deadline = time.monotonic() + 30
            while reader.is_alive() and time.monotonic() < deadline:
                time.sleep(0.1)
