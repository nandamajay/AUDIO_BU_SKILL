"""WP-SRC-A commit 2: SOURCE_UNRESOLVED sentinel (Design B — bare singleton).

Marker value emitted by ingestion collectors (currently only ``pinmux``;
``endpoints`` follows in WP-SRC-B) when the source side of cross-verify
cannot be derived from the checked-out kernel tree. Replaces the
`silent-empty` shape (``[]`` / ``{}`` / ``None``) that the T-SRC-A-3
test rejects as a §5 evidence-doctrine violation ("never silent empty,
never fabricated guess" — see ``docs/PHASE3_KNOWN_GAPS.md`` G-3A.7).

Design choices:

  * **Bare singleton, NOT ``str`` subclass.** ``SOURCE_UNRESOLVED`` is a
    plain ``object()``-style singleton. Rationale: a ``str`` subclass
    passes ``isinstance(x, str)`` and ``isinstance(x, list) is False``,
    so any downstream consumer that reflexively gates on
    ``isinstance(v, list)`` (to keep the sentinel out of authoritative
    fact paths) has to spell that guard by hand at every use site. The
    bare-singleton form makes the check ``v is SOURCE_UNRESOLVED`` —
    identity, not type-shape — which cannot be confused with a real
    ``list`` / ``str`` / ``dict`` payload. Callers get exactly one
    correct predicate, and forgetting to write it produces an
    ``AttributeError`` on the sentinel rather than silent leakage.

  * **JSON boundary conversion is caller-side, not encoder-hooked.**
    A bare object is not natively JSON-serialisable, so at every
    JSON serialisation boundary (currently only
    ``target_onboarding_runner._build_audio_topology``) the caller
    swaps the sentinel for the literal string ``"SOURCE_UNRESOLVED"``
    *before* the topology dict is handed to ``json.dumps``. The
    helper ``sentinel_to_json_literal`` centralises that swap so the
    boundary conversion has exactly one implementation.

  * **Singleton identity.** ``SOURCE_UNRESOLVED is SOURCE_UNRESOLVED``
    after re-import is guaranteed by module-caching; ``is`` comparison
    is the canonical check.

  * ``__repr__`` returns the bare identifier ``SOURCE_UNRESOLVED``,
    not ``'SOURCE_UNRESOLVED'``, so tracebacks / logs show it as a
    named constant, distinguishable at a glance from an accidental
    string of the same content.

Contract pinned by T-SRC-A-3 (``tests/test_source_ingest_pinmux.py``):

  * Importable from at least one of
    ``orchestrator.source_ingest``,
    ``orchestrator.source_ingest.models``,
    ``orchestrator.source_ingest.pinmux``
    (this file defines it once; ``__init__`` and ``pinmux`` re-export).
  * ``derive_pinmux_from_dt(underivable_dt) is SOURCE_UNRESOLVED``
    (identity, not equality — the canonical Design-B predicate).

Refs: PHASE3A_IMPLEMENTATION_PLAN.md §4 WP-SRC-A1,
      docs/PHASE3_KNOWN_GAPS.md G-3A.7, G-3A.9.
"""

from __future__ import annotations

from typing import Any


class _SourceUnresolved:
    """Private singleton type. Do NOT instantiate a second copy —
    use the module-level ``SOURCE_UNRESOLVED`` reference.

    Bare object (no ``str`` inheritance) so identity comparison
    ``v is SOURCE_UNRESOLVED`` is the ONLY correct check. Any
    accidental ``isinstance(v, list)`` /  ``isinstance(v, str)`` gate
    on the sentinel returns False, which is the intended safety —
    the sentinel is a signal, not a payload.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        # Bare identifier form for logs / tracebacks — distinguishable
        # at a glance from an accidental literal string of the same
        # content, which would print as ``'SOURCE_UNRESOLVED'``.
        return "SOURCE_UNRESOLVED"

    def __bool__(self) -> bool:
        # Truthy so ``if pinmux_result:`` in caller code cannot silently
        # fall through as if the derivation returned an empty list.
        # Callers MUST use ``is SOURCE_UNRESOLVED`` for the sentinel
        # check; the truthy default protects against the sloppy form.
        return True


SOURCE_UNRESOLVED: _SourceUnresolved = _SourceUnresolved()
"""Module-level singleton. Import this, not the class.

Usage::

    from orchestrator.source_ingest import SOURCE_UNRESOLVED

    result = derive_pinmux_from_dt(dt)
    if result is SOURCE_UNRESOLVED:
        topology["pinmux"] = sentinel_to_json_literal(result)
    else:
        topology["pinmux"] = [f.to_dict() for f in result]
"""


def sentinel_to_json_literal(value: Any) -> Any:
    """JSON-boundary conversion for the ``SOURCE_UNRESOLVED`` sentinel.

    A bare-singleton sentinel is not natively JSON-serialisable, so
    call this immediately before writing a value into a dict that is
    about to be handed to ``json.dumps``. The literal string form
    ``"SOURCE_UNRESOLVED"`` is what lands on disk in ``profile.json``
    and what downstream JSON-only consumers see.

    Returns ``value`` unchanged for anything that isn't the sentinel —
    so this is safe to call unconditionally at the boundary.
    """
    if value is SOURCE_UNRESOLVED:
        return "SOURCE_UNRESOLVED"
    return value


__all__ = ["SOURCE_UNRESOLVED", "sentinel_to_json_literal"]
