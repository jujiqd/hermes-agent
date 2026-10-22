"""OS-handle release for finished ``ProcessRegistry`` sessions.

The reader thread owns a session's pipes. A buffered stream's ``close()`` waits for the
reader's lock, and the reader holds that lock for the whole of its blocking ``read()`` — so
closing the pipe from the finisher blocks until that read returns. On Windows the read only
ends when every writer of the pipe is gone: a descendant that inherited the pipe (``tail -f``
from a backgrounded script) keeps it open indefinitely, and the close never returns. That
wedged ``_reconcile_local_exit`` -> ``_move_to_finished`` -> ``_publish_finished`` -> here, so
the bounded one-shot exit linger never expired, the run never exited, and the completion
notification was never published (#142193).

The reader closes its own pipe (through ``_finish_reader``) once its read ends; the finisher
leaves it alone.
"""

import threading
from contextlib import suppress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.process_registry import ProcessSession


class ProcessHandlesMixin:
    """Release the OS handles of a finished session. The subclass supplies ``session.process``,
    ``session._pty`` and ``session._reader_thread``."""

    def _release_finished_handles(self, session: "ProcessSession"):
        """Close a finished session's OS handles (Popen pipes / PTY master).

        Best-effort and idempotent: the session may have no local Popen (env
        backends, detached recovery), or the handles may already be closed by
        the reader loop / kill path. Closing a Popen's stream objects does not
        kill anything — the child has already exited — it only releases the
        parent's pipe FDs, which is exactly the retained-resource leak.
        """
        proc = session.process
        if proc is not None:
            reader = session._reader_thread
            reader_owns_pipe = (
                reader is not None
                and reader.is_alive()
                and reader is not threading.current_thread()
            )
            for stream in (proc.stdout, proc.stderr):
                if stream is not None and not reader_owns_pipe:
                    with suppress(OSError, ValueError):
                        stream.close()
            # stdin is not the reader's: closing it only releases the write end.
            if proc.stdin is not None:
                with suppress(OSError, ValueError):  # a stdin flush can hit EPIPE
                    proc.stdin.close()
        if session._pty is not None:
            # A live ptyprocess reader sits in a blocking read holding the PTY file
            # object's buffer lock, and that read only ends once every holder of
            # the slave side is gone. A descendant that setsid()s past the kill
            # keeps it open, so close() here would block forever (under _lock on
            # the prune path). The reader closes the PTY itself via
            # _finish_reader once its read ends. pywinpty reads don't block, so
            # Windows closes here as before.
            from tools.process_registry import _IS_WINDOWS

            reader = session._reader_thread
            if (not _IS_WINDOWS and reader is not None and reader.is_alive()
                    and reader is not threading.current_thread()):
                return
            # ptyprocess/pywinpty close() is idempotent (``closed`` flag) and
            # closes the master fd exactly once; it raises only if the child
            # ignores SIGKILL, which we don't want to surface on the finish path.
            with suppress(Exception):
                session._pty.close()
