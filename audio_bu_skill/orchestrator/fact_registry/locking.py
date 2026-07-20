"""Phase-3A WP-E — Fact Registry POSIX advisory write lock.

Every registry writer holds a target-scoped exclusive lock while it mutates
the JSONL + sidecar pair. The lock is:

- **Advisory.** Kernel-level ``fcntl.flock`` on the open file descriptor of
  a zero-byte ``<target>.lock`` sentinel. Advisory over mandatory because
  mandatory locking requires the ``mand`` mount option (often unavailable
  on NFS and CI runners). Since all writers go through
  :mod:`.store`, advisory suffices — see design §9.
- **Exclusive.** ``LOCK_EX`` — only one writer per target at a time.
- **Non-blocking with timeout.** ``LOCK_EX | LOCK_NB`` in a polling loop
  driven by :func:`time.monotonic`; on timeout, raises
  :class:`RegistryLockError`. The default timeout is 5 seconds — long
  enough for a normal single-writer flow, short enough that a wedged
  process surfaces quickly.
- **Automatically released** when the file descriptor closes, either at
  the end of the ``with`` block or on process crash (the kernel drops
  the lock; the sentinel file is left behind but is stateless, so no
  cleanup is required).
- **Single-machine only.** Phase-3A does not support cross-host writers.
  See :ref:`PHASE3_ARCHITECTURE.md` §8 R-E1.

Design contract (WP_E_FACT_REGISTRY_DESIGN.md §9):

- The stale-tmp cleanup runs **outside** the lock (§9 step 0). This module
  provides only the lock itself, not the cleanup.
- The context yields nothing meaningful — callers should not depend on the
  yielded value. The lock is the side effect.
- If :func:`fcntl.flock` returns :class:`BlockingIOError`, the loop sleeps
  a small poll interval and retries until the deadline. Any other
  :class:`OSError` is not caught — it surfaces to the caller as-is,
  because it indicates a filesystem or permissions problem the operator
  needs to see, not a lock contention that should self-heal.
"""

from __future__ import annotations

import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .errors import RegistryLockError


# ── constants ────────────────────────────────────────────────────────────────

DEFAULT_LOCK_TIMEOUT_SEC: float = 5.0
"""Default seconds a writer will poll for the lock before raising.

Chosen per §9 rationale: comfortably longer than a normal write, decisively
shorter than a stuck process's mean time to detection. Not user-tunable at
runtime — override per-call via the ``timeout_s`` argument when needed."""

_POLL_INTERVAL_SEC: float = 0.01
"""Sleep between :func:`fcntl.flock` retries when the lock is held elsewhere.

10 ms keeps the polling loop responsive without spinning CPU."""


# ── context manager ─────────────────────────────────────────────────────────

@contextmanager
def registry_write_lock(
    lock_path: Path,
    timeout_s: float = DEFAULT_LOCK_TIMEOUT_SEC,
) -> Iterator[None]:
    """Acquire an exclusive POSIX advisory lock on ``lock_path``.

    Args:
        lock_path: full path to the ``<target>.lock`` sentinel file. Created
            with mode ``0o644`` if it does not exist. Its parent directory
            **must** already exist — this module does not create directories.
        timeout_s: maximum seconds to wait before giving up. Must be
            non-negative; a value of ``0`` attempts a single non-blocking
            acquisition and fails fast.

    Yields:
        Control to the ``with`` block while the lock is held. The context
        yields no value (``None``); callers should not depend on the yield.

    Raises:
        RegistryLockError: if the lock is not acquired within ``timeout_s``.
        OSError: for any other filesystem or permissions error (surfaces
            unchanged; not translated to :class:`RegistryLockError`).
        TypeError / ValueError: on obviously invalid arguments.
    """
    if not isinstance(lock_path, Path):
        raise TypeError(
            f"registry_write_lock: lock_path must be Path, got {type(lock_path).__name__}"
        )
    if not isinstance(timeout_s, (int, float)) or isinstance(timeout_s, bool):
        raise TypeError(
            f"registry_write_lock: timeout_s must be a real number, got {type(timeout_s).__name__}"
        )
    if timeout_s < 0:
        raise ValueError(
            f"registry_write_lock: timeout_s must be non-negative, got {timeout_s!r}"
        )

    # Open (creating if absent) the sentinel file. The FD carries the lock;
    # the sentinel is stateless — nothing is ever written into it.
    #
    # O_RDWR so flock semantics are correct on filesystems that require the
    # file descriptor to be writable for LOCK_EX; O_CREAT so we make it on
    # first use; 0o644 because it may be read by an operator during debug.
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        deadline = time.monotonic() + float(timeout_s)
        acquired = False
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                # Someone else holds the lock. Sleep and retry until deadline.
                if time.monotonic() >= deadline:
                    break
                time.sleep(_POLL_INTERVAL_SEC)
            # Any other OSError propagates — do not retry a filesystem error.

        if not acquired:
            raise RegistryLockError(
                f"could not acquire lock on {lock_path} within {timeout_s}s"
            )

        try:
            yield
        finally:
            # Release the advisory lock explicitly. Not strictly necessary
            # (close() releases it too), but explicit release makes the
            # test-time semantics deterministic.
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                # If unlock fails (extremely unlikely), the FD close below
                # still releases it. Swallowing keeps the finally block
                # symmetric with the acquire path.
                pass
    finally:
        os.close(fd)


__all__ = [
    "DEFAULT_LOCK_TIMEOUT_SEC",
    "registry_write_lock",
]
