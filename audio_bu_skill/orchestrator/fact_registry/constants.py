"""Phase-3A WP-E — Fact Registry compile-time constants and path helpers.

All values here are compile-time constants — changing them requires a code
review, not a config knob. Rationale: they encode contract-level invariants
that the design document ties to specific test IDs and behaviors.

Cross-references:

- ``SCHEMA_VERSION`` / ``SUPPORTED_SCHEMA_VERSIONS`` / ``MIN_TOLERABLE_MINOR``
  → WP_E_FACT_REGISTRY_DESIGN.md §11.
- ``MAX_PROVENANCE_CHAIN_LEN`` → §3.2 and §11 MAJOR-bump note (raising this
  cap requires a MAJOR bump, not MINOR).
- ``STALE_TMP_TTL_SEC`` → §9 writer-flow step 0 (C-5).
- Path helpers → §2 file layout.
"""

from __future__ import annotations

from pathlib import Path

# ── Schema versioning (§11) ────────────────────────────────────────────────

SCHEMA_VERSION: str = "1.0.0"
"""Version stamped in the header line of every registry file this build writes."""

SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"1.0.0"})
"""Exact set of schema versions this loader will accept without status downgrade.

Newer-than-known → :class:`RegistryStatus.UNSUPPORTED_SCHEMA` (§11 rejection
surface). No implicit forward-compatibility.
"""

MIN_TOLERABLE_MINOR: str = "1.0"
"""Anchor for the MINOR-tolerance rule: opens ``1.0.x``, refuses ``1.1.x`` and ``2.x.x``.

Documented at §11: "The rule for MINOR is 'loader knows exactly this version
or lower'." Currently identical to ``SCHEMA_VERSION`` minus the patch segment.
"""

# ── Provenance-chain cap (§3.2, §11 MAJOR-bump note) ───────────────────────

MAX_PROVENANCE_CHAIN_LEN: int = 100
"""Hard cap on the number of :class:`FactProvenance` entries per fact.

Raising this cap **requires a MAJOR schema bump**, not MINOR — see §11.
Reason: a MINOR raise would produce a registry that older loaders would open
(MINOR is additive) and still enforce the old cap on append, causing writes
that succeed on new builds to fail on old builds against the same file.
"""

# ── Stale-tmp cleanup (§9 step 0, C-5) ─────────────────────────────────────

STALE_TMP_TTL_SEC: int = 60
"""Age in seconds beyond which a ``<target>.json.tmp.*`` or
``<target>.registry.hash.tmp.*`` file is considered orphaned and removed
before the write lock is acquired (§9 step 0).

Chosen to be longer than any legitimate write on any filesystem WP-E targets
and shorter than any operator's patience. Compile-time constant per §9.
"""

# ── File-name / path helpers (§2, §10) ─────────────────────────────────────

_DEFAULT_STATE_SUBDIR: tuple[str, ...] = ("audio_bu_skill", "state", "fact_registry")
"""Path components under the repository root where per-target JSONL files
live. Kept as a tuple so callers can join it against any repo root."""


def default_base_dir(repo_root: Path) -> Path:
    """Return ``<repo_root>/audio_bu_skill/state/fact_registry`` as a :class:`Path`.

    Registry callers that do not pass an explicit ``base_dir`` to
    ``Registry.load()`` resolve to this location. Used only by tests and by
    :func:`Registry.load` when its ``base_dir`` argument is ``None``.
    """
    return repo_root.joinpath(*_DEFAULT_STATE_SUBDIR)


def jsonl_filename(target: str) -> str:
    """Return the target-scoped JSONL filename (``<target>.json``).

    Per OQ-2 (§16, resolved): filenames are target-scoped only; SoC is stored
    in the header, never in the filename.
    """
    if not target or "/" in target or "\\" in target or target.startswith("."):
        raise ValueError(
            f"jsonl_filename: {target!r} is not a valid target identifier"
        )
    return f"{target}.json"


def hash_sidecar_filename(target: str) -> str:
    """Return the sidecar filename (``<target>.registry.hash``) for ``target``.

    Sidecar shape (§10): a single line ``sha256:<64hex>  <target>.json``.
    Written first in the writer flow (§9 step 6, C-1 sidecar-first).
    """
    if not target or "/" in target or "\\" in target or target.startswith("."):
        raise ValueError(
            f"hash_sidecar_filename: {target!r} is not a valid target identifier"
        )
    return f"{target}.registry.hash"


def lock_filename(target: str) -> str:
    """Return the advisory-lock sentinel filename (``<target>.lock``).

    Zero-byte sentinel; only the kernel-level ``fcntl.flock`` on the open
    file descriptor carries state (§9).
    """
    if not target or "/" in target or "\\" in target or target.startswith("."):
        raise ValueError(
            f"lock_filename: {target!r} is not a valid target identifier"
        )
    return f"{target}.lock"


# ── Registry writer identity (§3 header line) ──────────────────────────────

WRITER_ID: str = "wp-e/store.py"
"""Value stamped into the header's ``writer`` field on every save."""

REGISTRY_HEADER_TYPE: str = "registry_header"
"""Value stamped into the header's ``__type`` field on every save."""


__all__ = [
    "MAX_PROVENANCE_CHAIN_LEN",
    "MIN_TOLERABLE_MINOR",
    "REGISTRY_HEADER_TYPE",
    "SCHEMA_VERSION",
    "STALE_TMP_TTL_SEC",
    "SUPPORTED_SCHEMA_VERSIONS",
    "WRITER_ID",
    "default_base_dir",
    "hash_sidecar_filename",
    "jsonl_filename",
    "lock_filename",
]
