"""T-IA-04 + T-IA-11 — materialize.write_atomic publish contract.

T-IA-04: write_atomic with a valid staging environment publishes all data
files, their .sha256 sidecars, and provenance.json atomically.

T-IA-11: write_atomic raises AcquireWriteError on lock timeout, raises on
missing base_dir, and never touches a live name on failure.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_ipcat_acquire_materialize
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
import time
from pathlib import Path

from orchestrator.ipcat_acquire.errors import AcquireWriteError
from orchestrator.ipcat_acquire.materialize import (
    LOCK_NAME,
    PROVENANCE_NAME,
    write_atomic,
)


_DUMMY_SHA = "b" * 64
_PROV = b'{"schema_version": "2.0.0"}\n'


def _data_files() -> dict[str, bytes]:
    return {
        "chips_list_chips.json": b'[{"alias":"nordschleife_2.0"}]\n',
        "cores_list_core_instances.json": b'[]\n',
    }


def _sidecars(data: dict[str, bytes]) -> dict[str, bytes]:
    return {
        name + ".sha256": (hashlib.sha256(payload).hexdigest() + "\n").encode("ascii")
        for name, payload in data.items()
    }


# ── T-IA-04: successful publish ───────────────────────────────────────────────

def test_data_files_published() -> None:
    """All data files appear in base_dir after a successful write_atomic."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        data = _data_files()
        write_atomic(base, data, _sidecars(data), _PROV, now=time.time())
        for name, payload in data.items():
            out = (base / name).read_bytes()
            assert out == payload, f"{name}: content mismatch"
    print("PASS T-IA-04a: data files published with correct content")


def test_sidecars_published() -> None:
    """Each .sha256 sidecar appears beside its data file."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        data = _data_files()
        sc = _sidecars(data)
        write_atomic(base, data, sc, _PROV, now=time.time())
        for name in sc:
            assert (base / name).exists(), f"sidecar {name} missing"
    print("PASS T-IA-04b: .sha256 sidecars published for every data file")


def test_provenance_published_last() -> None:
    """provenance.json appears in base_dir after write_atomic."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        data = _data_files()
        write_atomic(base, data, _sidecars(data), _PROV, now=time.time())
        prov_path = base / PROVENANCE_NAME
        assert prov_path.exists(), "provenance.json not published"
        assert prov_path.read_bytes() == _PROV
    print("PASS T-IA-04c: provenance.json published with correct content")


def test_staging_dir_cleaned_up() -> None:
    """No .staging.* directories remain after a successful write."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        data = _data_files()
        write_atomic(base, data, _sidecars(data), _PROV, now=time.time())
        leftover = list(base.glob(".staging.*"))
        assert not leftover, f"staging dirs remain: {leftover}"
    print("PASS T-IA-04d: .staging.* directories cleaned up after successful write")


def test_idempotent_second_write() -> None:
    """A second write_atomic over an existing cache replaces content cleanly."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        data1 = {"f.json": b'[1]\n'}
        write_atomic(base, data1, _sidecars(data1), _PROV, now=time.time())
        data2 = {"f.json": b'[2]\n'}
        write_atomic(base, data2, _sidecars(data2), _PROV, now=time.time())
        assert (base / "f.json").read_bytes() == b'[2]\n'
    print("PASS T-IA-04e: second write_atomic replaces existing cache correctly")


def test_injectable_now_parameter() -> None:
    """Passing now= does not raise and completes normally (hermetic time)."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        data = _data_files()
        write_atomic(base, data, _sidecars(data), _PROV, now=1_000_000_000.0)
        assert (base / PROVENANCE_NAME).exists()
    print("PASS T-IA-04f: injectable now= parameter accepted for hermetic tests")


# ── T-IA-11: failure modes ────────────────────────────────────────────────────

def test_raises_on_missing_base_dir() -> None:
    """write_atomic raises AcquireWriteError when base_dir does not exist."""
    raised = False
    try:
        write_atomic(
            Path("/tmp/nonexistent_ipcat_dir_12345_test"),
            {"f.json": b"x"},
            {},
            _PROV,
        )
    except AcquireWriteError:
        raised = True
    assert raised, "expected AcquireWriteError for nonexistent base_dir"
    print("PASS T-IA-11a: AcquireWriteError raised for nonexistent base_dir")


def test_lock_timeout_raises_acquire_write_error() -> None:
    """When the lock is held by another thread, write_atomic times out and
    raises AcquireWriteError without touching any live file."""
    import fcntl

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        lock_path = base / LOCK_NAME

        # Pre-create and hold the lock from another thread.
        lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        raised = False
        try:
            write_atomic(
                base,
                {"f.json": b"data"},
                {},
                _PROV,
                lock_timeout_s=0.05,  # very short — must time out
            )
        except AcquireWriteError:
            raised = True
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

        assert raised, "expected AcquireWriteError on lock timeout"
        # No live file should have been created
        assert not (base / "f.json").exists(), "data file must not exist after lock timeout"
    print("PASS T-IA-11b: lock timeout raises AcquireWriteError; no live files touched")


def test_no_partial_publish_on_lock_timeout() -> None:
    """After a lock-timeout AcquireWriteError, the base_dir is unchanged.
    Specifically: if a prior valid cache existed, it is byte-identical."""
    import fcntl

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        # Write a valid prior cache.
        data_old = {"f.json": b"old_data\n"}
        write_atomic(base, data_old, _sidecars(data_old), _PROV, now=time.time())
        old_bytes = (base / "f.json").read_bytes()

        lock_path = base / LOCK_NAME
        lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        try:
            write_atomic(
                base,
                {"f.json": b"new_data\n"},
                {},
                _PROV,
                lock_timeout_s=0.05,
            )
        except AcquireWriteError:
            pass
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

        assert (base / "f.json").read_bytes() == old_bytes, (
            "old cache was mutated during a lock-timeout failure"
        )
    print("PASS T-IA-11c: old cache is byte-identical after lock-timeout AcquireWriteError")


# ── runner ─────────────────────────────────────────────────────────────────────

def main() -> None:
    test_data_files_published()
    test_sidecars_published()
    test_provenance_published_last()
    test_staging_dir_cleaned_up()
    test_idempotent_second_write()
    test_injectable_now_parameter()
    test_raises_on_missing_base_dir()
    test_lock_timeout_raises_acquire_write_error()
    test_no_partial_publish_on_lock_timeout()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
