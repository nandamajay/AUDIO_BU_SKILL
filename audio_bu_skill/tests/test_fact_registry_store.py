"""Phase-3A WP-E — tests for the Fact Registry store (load/append/status) —
T-E11..T-E22 plus variants T-E14b, T-E14c, T-E15b, T-E22c, T-E22d.

Runs entirely in-process against per-test tempdirs; does not touch case.py,
case.generated.py, WP7, onboarding, or any runtime flow. Advisory-only per
PHASE3_ARCHITECTURE.md.

Run:
    PYTHONPATH=.:audio_bu_skill python3 -m tests.test_fact_registry_store
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from audio_bu_skill.fact_requirements import Authority, AuthorityClass, Domain
from audio_bu_skill.orchestrator.fact_registry import (
    FactKey,
    FactProvenance,
    KernelRef,
    ManualRef,
    Registry,
    RegistryLockError,
    RegistryStatus,
    RegistryWriteError,
    ReviewDecision,
    ReviewRecord,
    SchematicRef,
    hash_sidecar_filename,
    jsonl_filename,
    lock_filename,
)
from audio_bu_skill.orchestrator.fact_registry.hash import (
    sha256_of_bytes,
    sidecar_line,
)

UTC = timezone.utc
_TS = datetime(2026, 7, 15, 10, 0, 0, tzinfo=UTC)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "fact_registry"


def _assert_raises(fn, exc, message_substring=None):
    try:
        fn()
    except exc as e:
        if message_substring is not None and message_substring not in str(e):
            raise AssertionError(
                f"expected {exc.__name__} containing {message_substring!r}, "
                f"got {exc.__name__} with message {e!r}"
            )
        return
    raise AssertionError(f"expected {exc.__name__} to be raised, but nothing raised")


def _tmp_base() -> Path:
    return Path(tempfile.mkdtemp(prefix="wpe-store-"))


def _kernel_ref(commit: str = "b" * 40) -> KernelRef:
    return KernelRef(
        kind="kernel", kernel_ref_kind="dts", repo="kernel/msm-5.15",
        commit=commit, path="a.dts", line_start=10, line_end=12,
    )


def _prov(value=42, confidence=0.9, captured_at=_TS, note="obs",
          authority=Authority.KERNEL_DTS, source_ref=None) -> FactProvenance:
    return FactProvenance(
        value=value,
        authority=authority,
        authority_class=AuthorityClass.PRIMARY,
        source_ref=source_ref if source_ref is not None else _kernel_ref(),
        captured_at=captured_at,
        confidence=confidence,
        note=note,
    )


def _fk() -> FactKey:
    return FactKey(Domain.AUDIO, "codec", "wcd9395", "reset_gpio")


def _install_fixture(base: Path, fixture_name: str, target: str, *,
                     with_sidecar: bool = True) -> None:
    """Copy a fixture JSONL into ``base`` under the store's naming, and
    (optionally) synthesise a matching sidecar at runtime."""
    raw = (FIXTURES / fixture_name).read_bytes()
    (base / jsonl_filename(target)).write_bytes(raw)
    if with_sidecar:
        sc = sidecar_line(target, sha256_of_bytes(raw))
        (base / hash_sidecar_filename(target)).write_text(sc)


# ── T-E11 — empty file → ABSENT ─────────────────────────────────────────────

def test_te11_empty_file_absent() -> None:
    base = _tmp_base()
    # No file at all → ABSENT.
    r = Registry.load("t", base_dir=base)
    assert r.status is RegistryStatus.ABSENT
    # A zero-byte file → still ABSENT.
    (base / jsonl_filename("t")).write_bytes(b"")
    r2 = Registry.load("t", base_dir=base)
    assert r2.status is RegistryStatus.ABSENT
    assert r2.get(_fk()) is None
    assert list(r2.iter_facts()) == []


# ── T-E12 — write one fact, reload byte-identical (golden fixture) ──────────

def test_te12_write_load_byte_identical() -> None:
    base = _tmp_base()
    _install_fixture(base, "golden_registry_v1.jsonl", "golden-target")
    r = Registry.load("golden-target", base_dir=base)
    assert r.status is RegistryStatus.OK
    assert sum(1 for _ in r.iter_facts()) == 3

    # Record lines are deterministic: re-serialising the same facts by
    # appending nothing and reading back keeps every record line identical.
    on_disk = (base / jsonl_filename("golden-target")).read_text().splitlines()
    record_lines = [ln for ln in on_disk if '"fact_key"' in ln]
    assert len(record_lines) == 3
    # Records are sorted by the full fact-key tuple (family first): amp < codec < i2s.
    families = [ln.split('"family": "', 1)[1].split('"', 1)[0] for ln in record_lines]
    assert families == ["amp", "codec", "i2s"]


# ── T-E13 — append 2nd provenance grows chain, top updates, earlier kept ────

def test_te13_append_grows_chain() -> None:
    base = _tmp_base()
    fk = _fk()
    r = Registry.load("t", base_dir=base).append_provenance(fk, _prov(value=42), base_dir=base)
    assert r.get(fk).value == 42
    assert len(r.get(fk).provenance_chain) == 1

    r2 = r.append_provenance(
        fk,
        _prov(value=99, source_ref=SchematicRef(kind="schematic", doc_id="D",
                                                 revision="A", page=1),
              authority=Authority.SCHEMATIC_PDF, confidence=0.6),
        base_dir=base,
    )
    fv = r2.get(fk)
    assert fv.value == 99  # top updated
    assert len(fv.provenance_chain) == 2
    assert fv.provenance_chain[0].value == 42  # earlier entry unchanged
    assert fv.provenance_chain[1].value == 99


# ── T-E14 — sidecar matches after write; external mutation → HASH_MISMATCH ──

def test_te14_external_mutation_hash_mismatch() -> None:
    base = _tmp_base()
    fk = _fk()
    r = Registry.load("t", base_dir=base).append_provenance(fk, _prov(), base_dir=base)
    assert r.status is RegistryStatus.OK

    # Corrupt the JSONL out-of-band so it no longer matches the sidecar.
    jsonl = base / jsonl_filename("t")
    data = jsonl.read_bytes()
    jsonl.write_bytes(data + b'{"fact_key": "tampered"}\n')

    r2 = Registry.load("t", base_dir=base)
    assert r2.status is RegistryStatus.HASH_MISMATCH


# ── T-E14b — transient mismatch recovered by the 50 ms retry ───────────────

def test_te14b_transient_mismatch_recovered() -> None:
    base = _tmp_base()
    fk = _fk()
    Registry.load("t", base_dir=base).append_provenance(fk, _prov(), base_dir=base)

    jsonl = base / jsonl_filename("t")
    sidecar = base / hash_sidecar_filename("t")
    good_bytes = jsonl.read_bytes()
    good_sidecar = sidecar.read_text()

    # Write a bad sidecar now; a background thread restores the good one during
    # the load's 50 ms retry window, so the retried read observes agreement.
    sidecar.write_text(sidecar_line("t", "0" * 64))

    def _heal():
        time.sleep(0.010)
        sidecar.write_text(good_sidecar)

    th = threading.Thread(target=_heal)
    th.start()
    try:
        r = Registry.load("t", base_dir=base)
    finally:
        th.join()
    assert r.status is RegistryStatus.OK


# ── T-E14c — persistent mismatch → HASH_MISMATCH with delta in warnings ────

def test_te14c_persistent_mismatch_reports_delta() -> None:
    base = _tmp_base()
    fk = _fk()
    Registry.load("t", base_dir=base).append_provenance(fk, _prov(), base_dir=base)
    # Permanently wrong sidecar.
    (base / hash_sidecar_filename("t")).write_text(sidecar_line("t", "0" * 64))
    r = Registry.load("t", base_dir=base)
    assert r.status is RegistryStatus.HASH_MISMATCH
    assert r.load_warnings, "expected a hash-mismatch delta warning"


# ── T-E15 — truncated JSONL → PARTIAL ──────────────────────────────────────

def test_te15_truncated_partial() -> None:
    base = _tmp_base()
    _install_fixture(base, "malformed_missing_review.jsonl", "malformed-target")
    r = Registry.load("malformed-target", base_dir=base)
    assert r.status is RegistryStatus.PARTIAL
    assert sum(1 for _ in r.iter_facts()) == 0
    assert r.load_warnings


# ── T-E15b — hand-edited '#'/blank lines survive load but not the next save ─

def test_te15b_comment_lines_dropped_on_save() -> None:
    base = _tmp_base()
    fk = _fk()
    r = Registry.load("t", base_dir=base).append_provenance(fk, _prov(), base_dir=base)

    jsonl = base / jsonl_filename("t")
    lines = jsonl.read_text().splitlines()
    lines.insert(1, "# a hand-added comment")
    lines.insert(2, "")
    new_text = "\n".join(lines) + "\n"
    jsonl.write_bytes(new_text.encode("utf-8"))
    # Refresh the sidecar so the comment-bearing file still loads clean.
    (base / hash_sidecar_filename("t")).write_text(
        sidecar_line("t", sha256_of_bytes(new_text.encode("utf-8")))
    )

    r2 = Registry.load("t", base_dir=base)
    assert r2.status is RegistryStatus.OK
    assert r2.get(fk) is not None

    # Next save rewrites canonical output — comment/blank lines are gone.
    r3 = r2.append_provenance(
        fk,
        _prov(value=7, source_ref=SchematicRef(kind="schematic", doc_id="D",
                                               revision="A", page=1),
              authority=Authority.SCHEMATIC_PDF, confidence=0.6),
        base_dir=base,
    )
    assert r3.status is RegistryStatus.OK
    after = jsonl.read_text()
    assert "# a hand-added comment" not in after


# ── T-E16 — missing header → CORRUPT, file unmodified, get() → None ─────────

def test_te16_missing_header_corrupt() -> None:
    base = _tmp_base()
    # A JSONL with a record line but no registry_header first line.
    bad = (
        '{"fact_key": {"attribute": "reset_gpio", "domain": "Audio", '
        '"family": "codec", "subject": "wcd9395"}}\n'
    )
    jsonl = base / jsonl_filename("t")
    jsonl.write_text(bad)
    before = jsonl.read_bytes()

    r = Registry.load("t", base_dir=base)
    assert r.status is RegistryStatus.CORRUPT
    assert r.get(_fk()) is None
    assert list(r.iter_facts()) == []
    # Load must not have modified the file.
    assert jsonl.read_bytes() == before


# ── T-E17 — newer schema → UNSUPPORTED_SCHEMA (fixture) ────────────────────

def test_te17_newer_schema_unsupported() -> None:
    base = _tmp_base()
    _install_fixture(base, "newer_schema.jsonl", "golden-target")
    r = Registry.load("golden-target", base_dir=base)
    assert r.status is RegistryStatus.UNSUPPORTED_SCHEMA
    assert r.get(_fk()) is None
    assert list(r.iter_facts()) == []


# ── T-E18 — two sequential writers ok; a contending writer times out ───────

def test_te18_lock_timeout() -> None:
    base = _tmp_base()
    fk = _fk()
    # Two sequential writes both succeed.
    r = Registry.load("t", base_dir=base).append_provenance(fk, _prov(value=1), base_dir=base)
    r = r.append_provenance(
        fk,
        _prov(value=2, source_ref=SchematicRef(kind="schematic", doc_id="D",
                                               revision="A", page=1),
              authority=Authority.SCHEMATIC_PDF, confidence=0.6),
        base_dir=base,
    )
    assert len(r.get(fk).provenance_chain) == 2

    # Hold the lock in a background thread; a foreground append with a short
    # timeout must raise RegistryLockError.
    from audio_bu_skill.orchestrator.fact_registry.locking import registry_write_lock

    lock_path = base / lock_filename("t")
    holding = threading.Event()
    release = threading.Event()

    def _hold():
        with registry_write_lock(lock_path):
            holding.set()
            release.wait(2.0)

    th = threading.Thread(target=_hold)
    th.start()
    try:
        assert holding.wait(2.0)
        _assert_raises(
            lambda: r.append_provenance(
                fk,
                _prov(value=3, source_ref=SchematicRef(kind="schematic",
                     doc_id="D", revision="A", page=1),
                     authority=Authority.SCHEMATIC_PDF, confidence=0.6),
                base_dir=base, timeout_s=0.1,
            ),
            RegistryLockError,
        )
    finally:
        release.set()
        th.join()


# ── T-E19 — stale tmp from a crashed writer is cleaned by the next writer ──

def test_te19_stale_tmp_cleanup() -> None:
    base = _tmp_base()
    fk = _fk()
    r = Registry.load("t", base_dir=base).append_provenance(fk, _prov(), base_dir=base)

    # Simulate a crashed writer's leftover tmp files, aged past the TTL.
    stale_jsonl = base / f"{jsonl_filename('t')}.tmp.999999"
    stale_sidecar = base / f"{hash_sidecar_filename('t')}.tmp.999999"
    stale_jsonl.write_text("garbage")
    stale_sidecar.write_text("garbage")
    old = time.time() - 3600  # 1 hour old
    os.utime(stale_jsonl, (old, old))
    os.utime(stale_sidecar, (old, old))

    # The load itself is unaffected (stale tmp does not corrupt).
    assert Registry.load("t", base_dir=base).status is RegistryStatus.OK

    # The next writer runs step-0 cleanup and removes the aged tmp files.
    r2 = r.append_provenance(
        fk,
        _prov(value=5, source_ref=SchematicRef(kind="schematic", doc_id="D",
                                               revision="A", page=1),
              authority=Authority.SCHEMATIC_PDF, confidence=0.6),
        base_dir=base,
    )
    assert r2.status is RegistryStatus.OK
    assert not stale_jsonl.exists()
    assert not stale_sidecar.exists()


# ── T-E20 — records are sorted on write; byte-identical re-serialisation ───

def test_te20_records_sorted_on_write() -> None:
    base = _tmp_base()
    # Insert three facts out of sorted order.
    fk_i2s = FactKey(Domain.AUDIO, "i2s", "prim_mi2s", "sclk_hz")
    fk_amp = FactKey(Domain.AUDIO, "amp", "spk_left", "i2c_addr")
    fk_codec = FactKey(Domain.AUDIO, "codec", "wcd9395", "reset_gpio")
    r = Registry.load("t", base_dir=base)
    r = r.append_provenance(fk_i2s, _prov(value=1536000), base_dir=base)
    r = r.append_provenance(
        fk_amp,
        _prov(value="0x34", source_ref=SchematicRef(kind="schematic", doc_id="D",
                                                    revision="A", page=1),
              authority=Authority.SCHEMATIC_PDF, confidence=0.7),
        base_dir=base,
    )
    r = r.append_provenance(fk_codec, _prov(value=42), base_dir=base)

    on_disk = (base / jsonl_filename("t")).read_text().splitlines()
    record_lines = [ln for ln in on_disk if '"fact_key"' in ln]
    families = [ln.split('"family": "', 1)[1].split('"', 1)[0] for ln in record_lines]
    assert families == ["amp", "codec", "i2s"]  # sorted regardless of insert order


# ── T-E21 — MANUAL fact without a review is rejected at save ───────────────

def test_te21_manual_without_review_rejected() -> None:
    base = _tmp_base()
    fk = _fk()
    # A MANUAL-class provenance with review=None: FactValue inv4 fires while
    # append_provenance builds the new value → RegistryWriteError.
    bad = FactProvenance(
        value=42,
        authority=Authority.MANUAL,
        authority_class=AuthorityClass.MANUAL,
        source_ref=ManualRef(kind="manual", note="n",
                             ticket_url="https://t.example.com/A-1"),
        captured_at=_TS,
        confidence=0.3,
        note="n",
        review=None,
    )
    _assert_raises(
        lambda: Registry.load("t", base_dir=base).append_provenance(fk, bad, base_dir=base),
        RegistryWriteError,
    )
    # Nothing was written.
    assert not (base / jsonl_filename("t")).exists()


# ── T-E22 — revoked MANUAL loads but get() → None; chain remains on disk ────

def test_te22_revocation_hides_but_preserves_chain() -> None:
    base = _tmp_base()
    fk = _fk()
    r = Registry.load("t", base_dir=base).append_provenance(fk, _prov(value=42), base_dir=base)

    rev_review = ReviewRecord(
        reviewer_id="a", reviewer_role="lead",
        requested_at=_TS, answered_at=_TS,
        question="q", answer="reject",
        decision=ReviewDecision.REJECT,
        supersedes_provenance_index=0,
        ticket_url="https://t.example.com/A-1",
    )
    revocation = FactProvenance(
        value=42,
        authority=Authority.MANUAL,
        authority_class=AuthorityClass.MANUAL,
        source_ref=ManualRef(kind="manual", note="revoke",
                             ticket_url="https://t.example.com/A-1"),
        captured_at=_TS,
        confidence=0.2,
        note="revoke it",
        review=rev_review,
        is_revocation=True,
    )
    r2 = r.append_provenance(fk, revocation, base_dir=base)
    assert r2.status is RegistryStatus.OK
    assert r2.get(fk) is None            # revoked → hidden
    assert list(r2.iter_facts()) == []   # omitted from iteration

    # But both chain entries persist on disk.
    raw = (base / jsonl_filename("t")).read_text()
    assert raw.count('"is_revocation"') == 2

    # And a fresh load sees the same hidden-but-present state.
    r3 = Registry.load("t", base_dir=base)
    assert r3.status is RegistryStatus.OK
    assert r3.get(fk) is None


# ── T-E22c — append at chain length 100 is refused; unchanged; lock freed ──

def test_te22c_cap_refuses_at_100() -> None:
    base = _tmp_base()
    fk = _fk()
    r = Registry.load("t", base_dir=base)
    # Build a chain of exactly 100 entries (all non-revocation, same descriptor
    # is fine since each append updates the top).
    for i in range(100):
        r = r.append_provenance(fk, _prov(value=i), base_dir=base)
    assert len(r.get(fk).provenance_chain) == 100

    jsonl = base / jsonl_filename("t")
    before = jsonl.read_bytes()

    # The 101st append is refused (cap is inclusive at 100).
    _assert_raises(
        lambda: r.append_provenance(fk, _prov(value=999), base_dir=base),
        RegistryWriteError,
    )
    # File unchanged.
    assert jsonl.read_bytes() == before
    # Lock was released — a fresh writer on a *different* fact still works.
    fk2 = FactKey(Domain.AUDIO, "i2s", "prim_mi2s", "sclk_hz")
    r2 = r.append_provenance(fk2, _prov(value=1536000), base_dir=base)
    assert r2.status is RegistryStatus.OK


# ── T-E22d — append at length 99 accepts (→100); next is refused ───────────

def test_te22d_cap_boundary_inclusive() -> None:
    base = _tmp_base()
    fk = _fk()
    r = Registry.load("t", base_dir=base)
    for i in range(99):
        r = r.append_provenance(fk, _prov(value=i), base_dir=base)
    assert len(r.get(fk).provenance_chain) == 99

    # 100th accepted.
    r = r.append_provenance(fk, _prov(value=99), base_dir=base)
    assert len(r.get(fk).provenance_chain) == 100

    # 101st refused.
    _assert_raises(
        lambda: r.append_provenance(fk, _prov(value=100), base_dir=base),
        RegistryWriteError,
    )


def main() -> None:
    # T-E11..T-E13  load/append basics
    test_te11_empty_file_absent()
    test_te12_write_load_byte_identical()
    test_te13_append_grows_chain()
    # T-E14 / T-E14b / T-E14c  hash sidecar + retry
    test_te14_external_mutation_hash_mismatch()
    test_te14b_transient_mismatch_recovered()
    test_te14c_persistent_mismatch_reports_delta()
    # T-E15 / T-E15b  partial + comment survival
    test_te15_truncated_partial()
    test_te15b_comment_lines_dropped_on_save()
    # T-E16..T-E17  corrupt + unsupported schema
    test_te16_missing_header_corrupt()
    test_te17_newer_schema_unsupported()
    # T-E18..T-E20  lock, stale-tmp cleanup, sorting
    test_te18_lock_timeout()
    test_te19_stale_tmp_cleanup()
    test_te20_records_sorted_on_write()
    # T-E21  manual-without-review save refusal
    test_te21_manual_without_review_rejected()
    # T-E22 / T-E22c / T-E22d  revocation + chain cap
    test_te22_revocation_hides_but_preserves_chain()
    test_te22c_cap_refuses_at_100()
    test_te22d_cap_boundary_inclusive()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
