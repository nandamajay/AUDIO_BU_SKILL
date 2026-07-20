"""Phase-3A WP-E — Fact Registry on-disk store (RegistryStatus + Registry).

This module is the single read/write path for a per-target fact registry. It
implements:

- :class:`RegistryStatus` — the six-member load-outcome enum with the
  precedence rule ``CORRUPT > UNSUPPORTED_SCHEMA > HASH_MISMATCH > PARTIAL >
  OK`` (plus ``ABSENT``), per §3.1.
- :class:`Registry` — an **immutable** frozen dataclass. ``load()`` never
  raises for missing / corrupt / hash-mismatch / unsupported-schema / partial
  conditions (those surface via ``status``); ``get()`` / ``iter_facts()`` are
  revocation-aware readers; ``append_provenance()`` is the only writer and it
  returns a **fresh** ``Registry`` (§3.2).

Authoritative flows:

- Writer flow (§9 steps 0-9): step 0 stale-tmp cleanup **outside** the lock →
  1 acquire lock → 2 read → 3 mutate → 4 tmp + ``fsync`` → 5 sha256 → 6 rename
  sidecar **FIRST** (C-1) → 7 rename JSONL → 8 ``fsync`` dir → 9 release lock.
- Reader retry (§9, B-3): a hash mismatch triggers exactly one 50 ms,
  strictly read-only re-read; a mismatch that survives it is genuine
  ``HASH_MISMATCH``.
- Serialization (§10): JSONL, UTF-8, LF, header line first, fact records
  sorted by ``(domain, family, subject, attribute)``, ``json.dumps`` with
  ``sort_keys=True`` per record; ``datetime`` → ISO 8601 ``Z``; ``Enum`` →
  ``.value``; ``#``/blank lines tolerated on read, never emitted on write
  (C-4).
- Versioning (§11): ``schema_version`` must be in
  ``SUPPORTED_SCHEMA_VERSIONS`` or the load is ``UNSUPPORTED_SCHEMA``.
- Cap (§3.2, C-2): a chain already at ``MAX_PROVENANCE_CHAIN_LEN`` (100)
  refuses further appends with ``RegistryWriteError``; on-disk state is
  left untouched and the lock is released before the exception surfaces.

Import discipline (§1.8): WP-D types come only through the public
:mod:`audio_bu_skill.fact_requirements` package. Nothing here imports from
``runners`` / ``main`` / ``targets``.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, fields as dc_fields, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Mapping

# ── WP-D public types (§1.8) ──────────────────────────────────────────────────
from audio_bu_skill.fact_requirements import (
    Authority,
    AuthorityClass,
    Domain,
)

# ── WP-E siblings ─────────────────────────────────────────────────────────────
from audio_bu_skill.orchestrator.fact_registry import source_refs as _source_refs
from audio_bu_skill.orchestrator.fact_registry.constants import (
    MAX_PROVENANCE_CHAIN_LEN,
    REGISTRY_HEADER_TYPE,
    SCHEMA_VERSION,
    STALE_TMP_TTL_SEC,
    SUPPORTED_SCHEMA_VERSIONS,
    WRITER_ID,
    default_base_dir,
    hash_sidecar_filename,
    jsonl_filename,
    lock_filename,
)
from audio_bu_skill.orchestrator.fact_registry.errors import (
    RegistryLoadError,
    RegistryWriteError,
)
from audio_bu_skill.orchestrator.fact_registry.hash import (
    parse_sidecar,
    sha256_of_bytes,
    sidecar_line,
)
from audio_bu_skill.orchestrator.fact_registry.locking import registry_write_lock
from audio_bu_skill.orchestrator.fact_registry.models import (
    FactKey,
    FactProvenance,
    FactValue,
)
from audio_bu_skill.orchestrator.fact_registry.review import (
    ReviewDecision,
    ReviewRecord,
)


# ── RegistryStatus (§3.1) ─────────────────────────────────────────────────────

class RegistryStatus(str, Enum):
    """Load outcome. Exactly one per :meth:`Registry.load` call.

    Precedence for compound conditions (§3.1, Checkpoint E0)::

        CORRUPT > UNSUPPORTED_SCHEMA > HASH_MISMATCH > PARTIAL > OK
    """

    OK = "ok"
    ABSENT = "absent"
    PARTIAL = "partial"
    CORRUPT = "corrupt"
    HASH_MISMATCH = "hash_mismatch"
    UNSUPPORTED_SCHEMA = "unsupported_schema"


# Statuses against which append_provenance refuses to write (§3.2).
_REFUSING_STATUSES: frozenset[RegistryStatus] = frozenset(
    {
        RegistryStatus.CORRUPT,
        RegistryStatus.UNSUPPORTED_SCHEMA,
        RegistryStatus.HASH_MISMATCH,
    }
)

# Reader retry policy (§9, B-3).
_HASH_RETRY_SLEEP_SEC: float = 0.050


# ── datetime <-> ISO-8601-Z helpers (§10) ─────────────────────────────────────

def _dt_to_z(dt: datetime) -> str:
    """Serialise a tz-aware UTC datetime as ISO 8601 with a ``Z`` suffix."""
    iso = dt.astimezone(timezone.utc).isoformat()
    # astimezone(utc) yields '+00:00'; the design mandates a literal 'Z'.
    if iso.endswith("+00:00"):
        iso = iso[: -len("+00:00")] + "Z"
    return iso


def _dt_from_z(s: str) -> datetime:
    """Parse an ISO 8601 ``Z`` (or ``+00:00``) string into a tz-aware UTC datetime."""
    if not isinstance(s, str) or not s:
        raise ValueError(f"expected non-empty ISO-8601 datetime string, got {s!r}")
    text = s
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError(f"datetime string {s!r} is missing a timezone")
    return dt.astimezone(timezone.utc)


# ── SourceRef (de)serialisation (§10) ─────────────────────────────────────────

def _source_ref_to_json(sr: Any) -> dict[str, Any]:
    """Serialise any :data:`SourceRef` variant to a JSON-ready mapping.

    Iterates the frozen dataclass fields generically so every current and
    future variant is covered. ``datetime`` fields (e.g. ``IPCATLiveRef.ts``)
    are rendered ISO-Z; ``Mapping`` fields (``args`` / ``inputs``) are shallow
    copied into plain dicts.
    """
    out: dict[str, Any] = {}
    for f in dc_fields(sr):
        v = getattr(sr, f.name)
        if isinstance(v, datetime):
            v = _dt_to_z(v)
        elif isinstance(v, Mapping):
            v = dict(v)
        out[f.name] = v
    return out


def _source_ref_from_json(d: Mapping[str, Any]) -> Any:
    """Rebuild a :data:`SourceRef` from a JSON mapping via ``source_refs.parse``.

    Converts a ``ts`` field (ipcat_live variant) back into a datetime before
    dispatching; all other fields pass through unchanged.
    """
    if not isinstance(d, Mapping):
        raise ValueError(f"source_ref must be a mapping, got {type(d).__name__}")
    d2 = dict(d)
    if d2.get("kind") == "ipcat_live" and "ts" in d2:
        d2["ts"] = _dt_from_z(d2["ts"])
    return _source_refs.parse(d2)


# ── ReviewRecord (de)serialisation (§8, §10) ──────────────────────────────────

def _review_to_json(r: ReviewRecord | None) -> dict[str, Any] | None:
    if r is None:
        return None
    return {
        "reviewer_id": r.reviewer_id,
        "reviewer_role": r.reviewer_role,
        "requested_at": _dt_to_z(r.requested_at),
        "answered_at": _dt_to_z(r.answered_at),
        "question": r.question,
        "answer": r.answer,
        "decision": r.decision.value,
        "ticket_url": r.ticket_url,
        "email_msgid": r.email_msgid,
        "doc_ref": r.doc_ref,
        "expires_at": _dt_to_z(r.expires_at) if r.expires_at is not None else None,
        "supersedes_provenance_index": r.supersedes_provenance_index,
    }


def _review_from_json(d: Mapping[str, Any] | None) -> ReviewRecord | None:
    if d is None:
        return None
    if not isinstance(d, Mapping):
        raise ValueError(f"review must be a mapping or null, got {type(d).__name__}")
    expires_raw = d.get("expires_at")
    return ReviewRecord(
        reviewer_id=d["reviewer_id"],
        reviewer_role=d["reviewer_role"],
        requested_at=_dt_from_z(d["requested_at"]),
        answered_at=_dt_from_z(d["answered_at"]),
        question=d["question"],
        answer=d["answer"],
        decision=ReviewDecision(d["decision"]),
        ticket_url=d.get("ticket_url"),
        email_msgid=d.get("email_msgid"),
        doc_ref=d.get("doc_ref"),
        expires_at=_dt_from_z(expires_raw) if expires_raw is not None else None,
        supersedes_provenance_index=d.get("supersedes_provenance_index"),
    )


# ── FactProvenance (de)serialisation (§6, §10) ────────────────────────────────

def _provenance_to_json(p: FactProvenance) -> dict[str, Any]:
    return {
        "authority": p.authority.value,
        "authority_class": p.authority_class.value,
        "source_ref": _source_ref_to_json(p.source_ref),
        "captured_at": _dt_to_z(p.captured_at),
        "confidence": p.confidence,
        "note": p.note,
        "value": p.value,
        "review": _review_to_json(p.review),
        "is_revocation": p.is_revocation,
    }


def _provenance_from_json(d: Mapping[str, Any]) -> FactProvenance:
    if not isinstance(d, Mapping):
        raise ValueError(
            f"provenance entry must be a mapping, got {type(d).__name__}"
        )
    return FactProvenance(
        value=d["value"],
        authority=Authority(d["authority"]),
        authority_class=AuthorityClass(d["authority_class"]),
        source_ref=_source_ref_from_json(d["source_ref"]),
        captured_at=_dt_from_z(d["captured_at"]),
        confidence=d["confidence"],
        note=d["note"],
        review=_review_from_json(d.get("review")),
        is_revocation=bool(d.get("is_revocation", False)),
    )


# ── FactValue descriptor synthesis (§5, R-1) ──────────────────────────────────

def _factvalue_from_chain(
    chain: tuple[FactProvenance, ...], *, notes: str
) -> FactValue:
    """Build a :class:`FactValue` whose descriptor is derived from ``chain``.

    Mirrors the append writer so a stored record round-trips exactly (R-1):
    the descriptor fields are taken from the chain top, or — when the top is a
    revocation entry — from the last non-revocation entry (per §5 invariant 7).
    ``notes`` is supplied separately because it is free-form and excluded from
    the descriptor-match invariant.
    """
    top = chain[-1]
    if top.is_revocation:
        desc: FactProvenance | None = None
        for entry in reversed(chain):
            if not entry.is_revocation:
                desc = entry
                break
        if desc is None:
            raise ValueError(
                "provenance_chain with a revocation top has no prior "
                "non-revocation entry"
            )
    else:
        desc = top
    return FactValue(
        value=desc.value,
        authority=desc.authority,
        authority_class=desc.authority_class,
        captured_at=desc.captured_at,
        source_ref=desc.source_ref,
        confidence=desc.confidence,
        review=desc.review,
        notes=notes,
        provenance_chain=chain,
    )


# ── record (de)serialisation ──────────────────────────────────────────────────

def _record_to_json(fk: FactKey, fv: FactValue) -> dict[str, Any]:
    return {
        "fact_key": {
            "domain": fk.domain.value,
            "family": fk.family,
            "subject": fk.subject,
            "attribute": fk.attribute,
        },
        "value": {
            "value": fv.value,
            "authority": fv.authority.value,
            "authority_class": fv.authority_class.value,
            "captured_at": _dt_to_z(fv.captured_at),
            "source_ref": _source_ref_to_json(fv.source_ref),
            "confidence": fv.confidence,
            "review": _review_to_json(fv.review),
            "notes": fv.notes,
        },
        "provenance_chain": [_provenance_to_json(p) for p in fv.provenance_chain],
    }


def _record_from_json(obj: Mapping[str, Any]) -> tuple[FactKey, FactValue]:
    if not isinstance(obj, Mapping):
        raise ValueError(f"record must be a mapping, got {type(obj).__name__}")
    fk_raw = obj["fact_key"]
    if not isinstance(fk_raw, Mapping):
        raise ValueError("record.fact_key must be a mapping")
    fk = FactKey(
        domain=Domain(fk_raw["domain"]),
        family=fk_raw["family"],
        subject=fk_raw["subject"],
        attribute=fk_raw["attribute"],
    )
    chain_raw = obj["provenance_chain"]
    if not isinstance(chain_raw, list) or not chain_raw:
        raise ValueError("record.provenance_chain must be a non-empty list")
    chain = tuple(_provenance_from_json(e) for e in chain_raw)
    value_block = obj.get("value") or {}
    notes = value_block.get("notes", "") if isinstance(value_block, Mapping) else ""
    fv = _factvalue_from_chain(chain, notes=notes)
    return fk, fv


# ── sort key (§10) ────────────────────────────────────────────────────────────

def _fact_sort_key(fk: FactKey) -> tuple[str, str, str, str]:
    return (fk.domain.value, fk.family, fk.subject, fk.attribute)


# ── path resolution ───────────────────────────────────────────────────────────

def _resolve_base_dir(base_dir: Path | None) -> Path:
    if base_dir is not None:
        if not isinstance(base_dir, Path):
            raise RegistryLoadError(
                f"base_dir must be a Path or None, got {type(base_dir).__name__}"
            )
        return base_dir
    # store.py: audio_bu_skill/orchestrator/fact_registry/store.py
    #   parents[0]=fact_registry [1]=orchestrator [2]=audio_bu_skill [3]=<repo root>
    repo_root = Path(__file__).resolve().parents[3]
    return default_base_dir(repo_root)


def _validate_target(target: str) -> None:
    if not isinstance(target, str) or not target:
        raise RegistryLoadError(f"target must be a non-empty str, got {target!r}")
    if "/" in target or "\\" in target or target.startswith("."):
        raise RegistryLoadError(f"{target!r} is not a valid target identifier")


# ── hash-state probe (§9, §10) ────────────────────────────────────────────────

def _hash_state(
    sidecar_path: Path, raw_bytes: bytes, target: str
) -> tuple[bool, str | None]:
    """Return ``(mismatch, warning)`` comparing the sidecar to the JSONL bytes.

    A missing or malformed sidecar counts as a mismatch (§12: "Missing sidecar
    → HASH_MISMATCH").
    """
    actual = sha256_of_bytes(raw_bytes)
    try:
        sc_text = sidecar_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return True, "sidecar missing"
    try:
        expected = parse_sidecar(sc_text, target)
    except ValueError as exc:
        return True, f"sidecar malformed: {exc}"
    if expected.lower() != actual.lower():
        return True, f"hash mismatch: sidecar={expected} actual={actual}"
    return False, None


# ── single load attempt (pre-retry) ───────────────────────────────────────────

@dataclass(frozen=True)
class _Attempt:
    status: RegistryStatus
    facts: dict[FactKey, FactValue]
    warnings: tuple[str, ...]
    malformed_lines: tuple[str, ...]


def _load_attempt(target: str, base_dir: Path) -> _Attempt:
    """Read + parse the registry once; resolve status per the §3.1 precedence.

    Never raises for missing / corrupt / hash-mismatch / unsupported-schema /
    partial conditions — every one of those surfaces in the returned status.
    """
    jsonl_path = base_dir / jsonl_filename(target)
    sidecar_path = base_dir / hash_sidecar_filename(target)

    try:
        raw_bytes = jsonl_path.read_bytes()
    except FileNotFoundError:
        return _Attempt(RegistryStatus.ABSENT, {}, (), ())
    except IsADirectoryError:
        return _Attempt(
            RegistryStatus.CORRUPT, {}, ("registry path is a directory",), ()
        )

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return _Attempt(
            RegistryStatus.CORRUPT, {}, ("registry file is not valid UTF-8",), ()
        )

    # Split into content lines, skipping blank and '#'-comment lines (§3, C-4).
    content: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        content.append(line)

    # No content at all — an empty (or comment-only) file is ABSENT (T-E11).
    if not content:
        return _Attempt(RegistryStatus.ABSENT, {}, (), ())

    # Header must be the first content line (§3, §10).
    try:
        header = json.loads(content[0])
    except (ValueError, TypeError):
        return _Attempt(
            RegistryStatus.CORRUPT, {}, ("header line is not valid JSON",), ()
        )
    if not (isinstance(header, dict) and header.get("__type") == REGISTRY_HEADER_TYPE):
        return _Attempt(
            RegistryStatus.CORRUPT,
            {},
            ("first record is not a registry_header",),
            (),
        )

    schema_version = header.get("schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        return _Attempt(
            RegistryStatus.UNSUPPORTED_SCHEMA,
            {},
            (f"unsupported schema_version {schema_version!r}",),
            (),
        )

    # Parse fact records; malformed lines are dropped from _facts, preserved
    # for rewrite, and reported as warnings (PARTIAL).
    facts: dict[FactKey, FactValue] = {}
    warnings: list[str] = []
    malformed: list[str] = []
    for raw in content[1:]:
        try:
            obj = json.loads(raw)
            fk, fv = _record_from_json(obj)
        except Exception as exc:  # noqa: BLE001 — one bad line ≠ dead registry
            warnings.append(f"dropped malformed record: {exc}")
            malformed.append(raw)
            continue
        facts[fk] = fv

    partial = len(malformed) > 0

    mismatch, hwarn = _hash_state(sidecar_path, raw_bytes, target)
    if mismatch:
        combined = tuple(warnings) + ((hwarn,) if hwarn else ())
        return _Attempt(
            RegistryStatus.HASH_MISMATCH, facts, combined, tuple(malformed)
        )

    if partial:
        return _Attempt(
            RegistryStatus.PARTIAL, facts, tuple(warnings), tuple(malformed)
        )
    return _Attempt(RegistryStatus.OK, facts, tuple(warnings), tuple(malformed))


# ── stale-tmp cleanup (§9 step 0, C-5) ────────────────────────────────────────

def _cleanup_stale_tmp(base_dir: Path, target: str) -> tuple[str, ...]:
    """Remove ``<target>.json.tmp.*`` / ``<target>.registry.hash.tmp.*`` older
    than ``STALE_TMP_TTL_SEC``. Best-effort; runs OUTSIDE the write lock.

    An unremovable tmp file is reported (returned) as a load warning but does
    not fail the write.
    """
    warnings: list[str] = []
    if not base_dir.exists():
        return ()
    now = time.time()
    patterns = (
        f"{jsonl_filename(target)}.tmp.*",
        f"{hash_sidecar_filename(target)}.tmp.*",
    )
    for pattern in patterns:
        for tmp in base_dir.glob(pattern):
            try:
                age = now - tmp.stat().st_mtime
                if age > STALE_TMP_TTL_SEC:
                    tmp.unlink()
            except OSError as exc:
                warnings.append(f"could not remove stale tmp {tmp.name}: {exc}")
    return tuple(warnings)


# ── atomic write (§9 steps 4-8) ───────────────────────────────────────────────

def _serialise_registry(
    target: str,
    facts: Mapping[FactKey, FactValue],
    malformed_lines: tuple[str, ...],
    now: datetime,
) -> bytes:
    """Render the full registry file bytes: header, sorted records, preserved
    malformed lines. UTF-8, LF, trailing newline (§10)."""
    header = {
        "__type": REGISTRY_HEADER_TYPE,
        "schema_version": SCHEMA_VERSION,
        "target": target,
        "written_at": _dt_to_z(now),
        "writer": WRITER_ID,
    }
    lines: list[str] = [json.dumps(header, sort_keys=True, ensure_ascii=False)]
    for fk in sorted(facts, key=_fact_sort_key):
        record = _record_to_json(fk, facts[fk])
        lines.append(json.dumps(record, sort_keys=True, ensure_ascii=False))
    # §3.2: preserve malformed lines untouched so an operator can recover them.
    lines.extend(malformed_lines)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _fsync_path(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_registry(
    base_dir: Path,
    target: str,
    facts: Mapping[FactKey, FactValue],
    malformed_lines: tuple[str, ...],
    now: datetime,
) -> None:
    """Perform §9 steps 4-8. Assumes the caller holds the write lock (step 1)."""
    jsonl_path = base_dir / jsonl_filename(target)
    sidecar_path = base_dir / hash_sidecar_filename(target)
    pid = os.getpid()
    jsonl_tmp = base_dir / f"{jsonl_filename(target)}.tmp.{pid}"
    sidecar_tmp = base_dir / f"{hash_sidecar_filename(target)}.tmp.{pid}"

    payload = _serialise_registry(target, facts, malformed_lines, now)

    # Step 4: write JSONL tmp + fsync (do NOT rename yet).
    fd = os.open(str(jsonl_tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)

    # Step 5: sha256 over the tmp bytes.
    digest = sha256_of_bytes(payload)

    # Step 6: sidecar tmp + fsync + replace — sidecar lands FIRST (C-1).
    sidecar_payload = sidecar_line(target, digest).encode("utf-8")
    sfd = os.open(str(sidecar_tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(sfd, sidecar_payload)
        os.fsync(sfd)
    finally:
        os.close(sfd)
    os.replace(str(sidecar_tmp), str(sidecar_path))

    # Step 7: rename JSONL over the canonical name.
    os.replace(str(jsonl_tmp), str(jsonl_path))

    # Step 8: fsync the containing directory so both renames are durable.
    _fsync_path(base_dir)


# ── Registry (§3.2) ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Registry:
    """Immutable in-memory view of a per-target fact registry.

    Every state transition returns a fresh instance; there is no public
    ``save()`` and no in-place mutation. ``_facts`` and ``_malformed_lines``
    are private implementation fields (not part of the public API).
    """

    target: str
    status: RegistryStatus
    load_warnings: tuple[str, ...]
    _facts: Mapping[FactKey, FactValue]
    _malformed_lines: tuple[str, ...] = ()

    # ── read API ──────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, target: str, *, base_dir: Path | None = None) -> "Registry":
        """Load the registry for ``target``; always returns a ``Registry``.

        Never raises for missing / corrupt / hash-mismatch / unsupported-schema
        / partial conditions — those surface via :attr:`status`. Raises
        :class:`RegistryLoadError` only for programmer errors (bad ``target``,
        bad ``base_dir``).
        """
        _validate_target(target)
        resolved = _resolve_base_dir(base_dir)

        attempt = _load_attempt(target, resolved)
        if attempt.status is RegistryStatus.HASH_MISMATCH:
            # §9 / B-3: one strictly read-only retry after a 50 ms sleep.
            time.sleep(_HASH_RETRY_SLEEP_SEC)
            attempt = _load_attempt(target, resolved)

        return cls(
            target=target,
            status=attempt.status,
            load_warnings=attempt.warnings,
            _facts=attempt.facts,
            _malformed_lines=attempt.malformed_lines,
        )

    def get(self, fact_key: FactKey) -> FactValue | None:
        """Return the live :class:`FactValue` for ``fact_key`` or ``None``.

        ``None`` when the fact is absent, when the chain top is a revocation
        entry (§6, §8), or under ``CORRUPT`` / ``UNSUPPORTED_SCHEMA`` (§11).
        """
        if self.status in (
            RegistryStatus.CORRUPT,
            RegistryStatus.UNSUPPORTED_SCHEMA,
        ):
            return None
        fv = self._facts.get(fact_key)
        if fv is None:
            return None
        if fv.provenance_chain[-1].is_revocation:
            return None
        return fv

    def iter_facts(self) -> Iterator[tuple[FactKey, FactValue]]:
        """Iterate live (non-revoked) facts sorted by
        ``(domain, family, subject, attribute)`` (§3.2)."""
        if self.status in (
            RegistryStatus.CORRUPT,
            RegistryStatus.UNSUPPORTED_SCHEMA,
        ):
            return
        for fk in sorted(self._facts, key=_fact_sort_key):
            fv = self._facts[fk]
            if fv.provenance_chain[-1].is_revocation:
                continue
            yield fk, fv

    # ── write API ───────────────────────────────────────────────────────────

    def append_provenance(
        self,
        fact_key: FactKey,
        provenance: FactProvenance,
        *,
        base_dir: Path | None = None,
        timeout_s: float = 5.0,
    ) -> "Registry":
        """Append ``provenance`` to ``fact_key``'s chain; return a fresh Registry.

        Implements the §9 writer flow. Refuses to write against a receiver
        whose status is ``CORRUPT`` / ``UNSUPPORTED_SCHEMA`` / ``HASH_MISMATCH``
        (§3.2). Enforces ``MAX_PROVENANCE_CHAIN_LEN`` (§3.2, C-2) — a chain
        already at the cap refuses further appends with
        :class:`RegistryWriteError` and the on-disk state is left unchanged.
        The receiver instance is never mutated.
        """
        if not isinstance(fact_key, FactKey):
            raise RegistryWriteError(
                f"fact_key must be a FactKey, got {type(fact_key).__name__}"
            )
        if not isinstance(provenance, FactProvenance):
            raise RegistryWriteError(
                "provenance must be a FactProvenance, got "
                f"{type(provenance).__name__}"
            )
        _validate_target(self.target)

        # Refuse against a receiver in a distrusted state (§3.2).
        if self.status in _REFUSING_STATUSES:
            raise RegistryWriteError(
                f"append_provenance refused: registry status is {self.status.value}"
            )

        resolved = _resolve_base_dir(base_dir)

        # Step 0: stale-tmp cleanup runs OUTSIDE the lock (§9, C-5).
        cleanup_warnings = _cleanup_stale_tmp(resolved, self.target)
        resolved.mkdir(parents=True, exist_ok=True)

        lock_path = resolved / lock_filename(self.target)

        # Step 1: acquire the exclusive advisory lock.
        with registry_write_lock(lock_path, timeout_s=timeout_s):
            # Step 2: read the authoritative current state inside the lock.
            fresh = _load_attempt(self.target, resolved)
            if fresh.status is RegistryStatus.HASH_MISMATCH:
                # Re-probe once (read-only) before deciding to refuse.
                time.sleep(_HASH_RETRY_SLEEP_SEC)
                fresh = _load_attempt(self.target, resolved)
            if fresh.status in _REFUSING_STATUSES:
                raise RegistryWriteError(
                    "append_provenance refused: on-disk registry status is "
                    f"{fresh.status.value}"
                )

            # Step 3: mutate (append). Enforce the chain-length cap first.
            existing = fresh.facts.get(fact_key)
            existing_chain: tuple[FactProvenance, ...] = (
                existing.provenance_chain if existing is not None else ()
            )
            if len(existing_chain) >= MAX_PROVENANCE_CHAIN_LEN:
                raise RegistryWriteError(
                    f"append refused: provenance chain for {fact_key.as_string()} "
                    f"is already at MAX_PROVENANCE_CHAIN_LEN "
                    f"({MAX_PROVENANCE_CHAIN_LEN}); raising the cap requires a "
                    "MAJOR schema bump (§11)"
                )

            new_chain = existing_chain + (provenance,)
            try:
                new_fv = _factvalue_from_chain(new_chain, notes=provenance.note)
            except (ValueError, TypeError) as exc:
                # e.g. MANUAL provenance without a review (T-E21) — never
                # persisted; the file and sidecar are untouched.
                raise RegistryWriteError(
                    f"append refused: invalid resulting FactValue: {exc}"
                ) from exc

            updated = dict(fresh.facts)
            updated[fact_key] = new_fv

            # Steps 4-8: atomic write (sidecar-first).
            now = datetime.now(timezone.utc)
            try:
                _write_registry(
                    resolved,
                    self.target,
                    updated,
                    fresh.malformed_lines,
                    now,
                )
            except OSError as exc:
                raise RegistryWriteError(
                    f"append failed during write: {exc}"
                ) from exc
        # Step 9: lock released on context exit.

        # Return a freshly-loaded Registry reflecting the post-write state,
        # carrying forward the step-0 cleanup diagnostics.
        result = Registry.load(self.target, base_dir=resolved)
        if cleanup_warnings:
            result = replace(
                result, load_warnings=result.load_warnings + cleanup_warnings
            )
        return result


__all__ = [
    "Registry",
    "RegistryStatus",
]
