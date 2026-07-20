"""WP-IPCAT-A C1 — atomic cache materialization (design §4.1).

Inert and self-contained: this module opens no network socket. It performs the
disk write, but only when :func:`write_atomic` is *called* — importing it does
nothing. It deliberately does **not** import from ``orchestrator.fact_registry``
(T-IA-12); instead it carries its own lock / fsync helpers modelled on WP-E's
proven shapes (``locking.registry_write_lock``, ``store.py`` steps 4–8).

Principle (design §4): acquisition either fully succeeds and swaps in a complete
new cache, or it changes nothing on disk. No partial cache is ever observable by
``ipcat_first``.

Atomic write protocol (design §4.1):

  0. **Sweep** stale ``.staging.*`` dirs older than the TTL — *outside* the lock.
  1. **Lock** ``evidence/ipcat/.acquire.lock`` (exclusive advisory ``flock``,
     bounded timeout → :class:`AcquireWriteError` on timeout).
  2. **Stage** every new file into ``evidence/ipcat/.staging.<pid>/``, each
     ``fsync``'d.
  3. **Verify** — sidecars are staged alongside; ``provenance.json`` is staged
     last so it only ever references files that already exist.
  4. **Publish** with ``os.replace`` (atomic rename on POSIX): data files first,
     then their sidecars, ``provenance.json`` **last**. ``fsync`` the directory.
  5. **Cleanup** the staging dir.

Provenance-last ordering means the worst a crash mid-publish can do is leave the
old data with a new ``provenance.json`` — which the reader validates — never a
manifest pointing at a missing file.
"""

from __future__ import annotations

import errno
import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping

from .errors import AcquireWriteError

# ── constants (mirror WP-E rationale) ────────────────────────────────────────

PROVENANCE_NAME = "provenance.json"
LOCK_NAME = ".acquire.lock"
_STAGING_PREFIX = ".staging."
_DEFAULT_LOCK_TIMEOUT_SEC = 5.0
_POLL_INTERVAL_SEC = 0.01
_STALE_STAGING_TTL_SEC = 3600.0  # a crashed writer's staging dir age-out


# ── lock (own copy; does NOT import fact_registry — T-IA-12) ──────────────────

@contextmanager
def _acquire_lock(
    lock_path: Path, timeout_s: float = _DEFAULT_LOCK_TIMEOUT_SEC
) -> Iterator[None]:
    """Exclusive POSIX advisory lock on ``lock_path``; raise on timeout.

    Structurally identical to WP-E ``registry_write_lock`` but re-implemented
    here so the acquisition package stays free of any ``fact_registry`` import
    (advisory-only isolation, T-IA-12). On timeout raises
    :class:`AcquireWriteError` (maps to exit 3, old cache intact).
    """
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
                if time.monotonic() >= deadline:
                    break
                time.sleep(_POLL_INTERVAL_SEC)
        if not acquired:
            raise AcquireWriteError(
                f"could not acquire acquisition lock on {lock_path} "
                f"within {timeout_s}s"
            )
        try:
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        os.close(fd)


# ── fsync helpers ─────────────────────────────────────────────────────────────

def _write_file_fsync(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` and fsync the file (create/truncate)."""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    """fsync a directory so a rename into it is durable."""
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sweep_stale_staging(base_dir: Path, now: float) -> None:
    """Remove ``.staging.*`` dirs older than the TTL. Best-effort, no raise.

    Runs *outside* the lock (design §4.1 step 0) so a crashed writer's leftover
    staging dir is reclaimed by the next writer without blocking on the lock.
    """
    try:
        entries = list(base_dir.glob(f"{_STAGING_PREFIX}*"))
    except OSError:
        return
    for d in entries:
        try:
            if not d.is_dir():
                continue
            age = now - d.stat().st_mtime
            if age <= _STALE_STAGING_TTL_SEC:
                continue
            for child in d.iterdir():
                try:
                    child.unlink()
                except OSError:
                    pass
            d.rmdir()
        except OSError:
            # Best-effort: a race with another sweeper is harmless.
            continue


def write_atomic(
    base_dir: Path,
    data_files: Mapping[str, bytes],
    sidecars: Mapping[str, bytes],
    provenance_bytes: bytes,
    *,
    now: float | None = None,
    lock_timeout_s: float = _DEFAULT_LOCK_TIMEOUT_SEC,
) -> None:
    """Atomically publish a complete IPCAT cache into ``base_dir``.

    Args:
        base_dir: the target's ``evidence/ipcat/`` directory (must exist).
        data_files: ``{filename: canonical_bytes}`` for every data file.
        sidecars: ``{sidecar_filename: bytes}`` (one ``.sha256`` per data file).
        provenance_bytes: the serialised ``provenance.json`` (published last).
        now: monotone-ish wall time for the stale sweep; defaults to
            ``time.time()``. Injectable for hermetic tests.
        lock_timeout_s: seconds to wait for the lock.

    Guarantee: on any failure before publish, no live name is touched; on lock
    timeout / disk error, raises :class:`AcquireWriteError` and the old cache is
    byte-identical to its pre-run state (design §4.2 / §4.3).
    """
    if now is None:
        now = time.time()
    base_dir = Path(base_dir)
    if not base_dir.is_dir():
        raise AcquireWriteError(f"evidence dir does not exist: {base_dir}")

    # Step 0 — stale-staging sweep, outside the lock.
    _sweep_stale_staging(base_dir, now)

    lock_path = base_dir / LOCK_NAME
    with _acquire_lock(lock_path, timeout_s=lock_timeout_s):
        staging = base_dir / f"{_STAGING_PREFIX}{os.getpid()}"
        try:
            # Fresh staging dir (remove a same-pid leftover first).
            if staging.exists():
                for child in staging.iterdir():
                    child.unlink()
                staging.rmdir()
            staging.mkdir(mode=0o755)

            # Step 2/3 — stage data files, then sidecars, then provenance last.
            for name, payload in data_files.items():
                _write_file_fsync(staging / name, payload)
            for name, payload in sidecars.items():
                _write_file_fsync(staging / name, payload)
            _write_file_fsync(staging / PROVENANCE_NAME, provenance_bytes)

            # Step 4 — publish via os.replace: data, then sidecars, then
            # provenance LAST (a racing reader sees a whole old or whole new
            # set; provenance never points at a not-yet-present file).
            for name in data_files:
                os.replace(str(staging / name), str(base_dir / name))
            for name in sidecars:
                os.replace(str(staging / name), str(base_dir / name))
            os.replace(
                str(staging / PROVENANCE_NAME), str(base_dir / PROVENANCE_NAME)
            )
            _fsync_dir(base_dir)
        except AcquireWriteError:
            raise
        except OSError as exc:
            raise AcquireWriteError(
                f"atomic publish failed (errno={errno.errorcode.get(exc.errno, exc.errno)})"
            ) from exc
        finally:
            # Step 5 — cleanup staging (best-effort; leftover is swept next run).
            try:
                if staging.exists():
                    for child in staging.iterdir():
                        try:
                            child.unlink()
                        except OSError:
                            pass
                    staging.rmdir()
            except OSError:
                pass


__all__ = [
    "write_atomic",
    "PROVENANCE_NAME",
    "LOCK_NAME",
]
