"""Phase-2B WP7 — generation registration framework (decorators + registries).

Composition site for the generator lanes. Replaces the *closed-enumeration
antipattern* — hard-coded artifact-order tuple + gating table living as literals
in ``config.py`` — with decorator-based self-registration:

  * ``@register_generator(artifact_class, order=N, gating_rows=...)`` — a
    generator lane declares its own artifact_class, its position in the
    deterministic emit order, and its conjunctive gating expression. ``config``
    computes ``_GENERATION_ARTIFACT_ORDER`` / ``GATING_ROWS`` *from* this
    registry (see WP1b refactor).
  * ``register_skip_reason(reason)`` — the closed skip-reason vocabulary.
    Registered CENTRALLY by ``config.py`` (not per-generator): the reasons are
    shared across lanes (e.g. ``gating_row_disagree``), and
    ``test_every_skip_reason_documented`` grep-pins each literal to ``config``'s
    source, so the literals must physically live there.
  * ``register_advisory_row`` / ``register_known_bad_rule`` — config-owned
    policy carve-outs (§3.7 / §4.4), registered eagerly by ``config.py``.
  * ``@register_value_flattener(pattern)`` — extension point for a FUTURE
    value-drift verifier. WP7's post-gen check (A1) is gate-consistency, not
    value-drift, so the ``{"count": N} -> str(N)`` flattener registered here
    has NO live consumer today. It exists so a later value-drift lane plugs in
    without touching this framework.

Import discipline (CRITICAL — this module is cycle-free by construction):

  * Zero top-level imports from ``orchestrator.generation.*`` or
    ``orchestrator.reasoning.*``. This module ships the (initially empty)
    registries + the decorators, nothing else.
  * ``ensure_generators_loaded()`` lazily imports the four generator modules on
    first call. It is NEVER called at *this* module's import time and NEVER at
    ``config``'s import time — ``config`` calls it inside its PEP 562
    ``__getattr__`` (i.e. only when ``GATING_ROWS`` / ``_GENERATION_ARTIFACT_ORDER``
    is first *accessed*, by which point ``config`` is fully initialized). The
    generator modules do ``from ...config import PATH_GUARD_ROOT`` at their own
    import time; because that only ever fires *after* ``config`` finished its
    top-level body, the eager config constant is already present. No cycle.
  * Double-registration raises ``ValueError`` — a lane registering twice, or two
    lanes claiming the same ``artifact_class`` / ``order`` / flattener pattern,
    is a bug, not a silent last-wins.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_registry``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


# ── generator registry ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class GeneratorRegistration:
    """One registered generator lane.

    ``order`` is the authoritative position in ``_GENERATION_ARTIFACT_ORDER``;
    it is an explicit integer (NOT registration/import order) so the canonical
    tuple is deterministic no matter which module imported a generator first.

    ``gating_rows`` is the lane's conjunctive gating expression — a tuple of
    ``(track, subject_pattern)`` pairs, reproduced verbatim into ``GATING_ROWS``.
    ``func`` is the generator callable (``(facts, kb=None) -> GenerationResult``).
    """

    artifact_class: str
    order: int
    gating_rows: tuple[tuple[str, str], ...]
    func: Callable[..., object]


_GENERATORS: dict[str, GeneratorRegistration] = {}
_GENERATORS_LOADED: bool = False


def register_generator(
    artifact_class: str,
    *,
    order: int,
    gating_rows: tuple[tuple[str, str], ...],
) -> Callable[[Callable[..., object]], Callable[..., object]]:
    """Decorator: register a generator lane. Returns the function unchanged.

    Raises ``ValueError`` on a duplicate ``artifact_class`` or a duplicate
    ``order`` slot (either is a composition bug).
    """

    def deco(func: Callable[..., object]) -> Callable[..., object]:
        if artifact_class in _GENERATORS:
            raise ValueError(
                f"generator already registered: {artifact_class!r}"
            )
        for existing in _GENERATORS.values():
            if existing.order == order:
                raise ValueError(
                    f"generator order {order} already taken by "
                    f"{existing.artifact_class!r} (registering {artifact_class!r})"
                )
        _GENERATORS[artifact_class] = GeneratorRegistration(
            artifact_class=artifact_class,
            order=order,
            gating_rows=tuple((str(t), str(s)) for (t, s) in gating_rows),
            func=func,
        )
        return func

    return deco


def ensure_generators_loaded() -> None:
    """Import the four generator modules once, so they self-register.

    Idempotent and re-entrancy-safe: the ``_GENERATORS_LOADED`` flag is set
    *before* the imports so a generator module that (transitively) triggers
    this again during its own import does not recurse. Imports are attempted in
    canonical order as a readability hint only — actual ordering is governed by
    each registration's explicit ``order`` index, so ``sys.modules`` caching (a
    generator imported earlier by a test) cannot scramble the emit order.
    """
    global _GENERATORS_LOADED
    if _GENERATORS_LOADED:
        return
    _GENERATORS_LOADED = True
    # Local imports — the whole point of the lazy loader (see module docstring).
    import orchestrator.generation.dt_scaffolding  # noqa: F401
    import orchestrator.generation.codec_stub  # noqa: F401
    import orchestrator.generation.machine_driver  # noqa: F401
    import orchestrator.generation.audioreach_topology  # noqa: F401


def generator_order() -> tuple[str, ...]:
    """The deterministic artifact order, sorted by each lane's ``order`` index."""
    ensure_generators_loaded()
    return tuple(
        reg.artifact_class
        for reg in sorted(_GENERATORS.values(), key=lambda r: r.order)
    )


def gating_rows_map() -> dict[str, tuple[tuple[str, str], ...]]:
    """Per-artifact gating table, keyed in canonical (``order``) sequence."""
    ensure_generators_loaded()
    return {
        reg.artifact_class: reg.gating_rows
        for reg in sorted(_GENERATORS.values(), key=lambda r: r.order)
    }


def generator_func(artifact_class: str) -> Callable[..., object]:
    """Return the registered generator callable for ``artifact_class``."""
    ensure_generators_loaded()
    return _GENERATORS[artifact_class].func


# ── skip-reason registry (config-owned, eager) ─────────────────────────────


_SKIP_REASONS: set[str] = set()


def register_skip_reason(reason: str) -> str:
    """Register one skip-reason literal. Returns it. Raises on duplicate.

    Called by ``config.py`` with in-source string literals (so the grep-source
    lint ``test_every_skip_reason_documented`` continues to pass).
    """
    if reason in _SKIP_REASONS:
        raise ValueError(f"skip reason already registered: {reason!r}")
    _SKIP_REASONS.add(reason)
    return reason


def all_skip_reasons() -> frozenset[str]:
    """The closed skip-reason vocabulary as an immutable set."""
    return frozenset(_SKIP_REASONS)


# ── advisory-row registry (config-owned, eager) ────────────────────────────


_ADVISORY_ROWS: set[tuple[str, str]] = set()


def register_advisory_row(track: str, subject: str) -> tuple[str, str]:
    """Register a §3.7 advisory ``(track, subject)`` carve-out. Raises on dup."""
    pair = (track, subject)
    if pair in _ADVISORY_ROWS:
        raise ValueError(f"advisory row already registered: {pair!r}")
    _ADVISORY_ROWS.add(pair)
    return pair


def advisory_rows() -> frozenset[tuple[str, str]]:
    """The advisory-row carve-out set (§3.7)."""
    return frozenset(_ADVISORY_ROWS)


# ── known-bad PARTIAL_MATCH rule registry (config-owned, eager) ────────────


_KNOWN_BAD_RULES: set[str] = set()


def register_known_bad_rule(rule_id: str) -> str:
    """Register a §4.4 donor-residue ``rule_id``. Raises on duplicate."""
    if rule_id in _KNOWN_BAD_RULES:
        raise ValueError(f"known-bad rule already registered: {rule_id!r}")
    _KNOWN_BAD_RULES.add(rule_id)
    return rule_id


def known_bad_rules() -> frozenset[str]:
    """The donor-residue rule_id set (§4.4)."""
    return frozenset(_KNOWN_BAD_RULES)


# ── value-flattener registry (extension point — NO live consumer) ──────────
#
# A value flattener maps a structured authority/proposal value (e.g.
# ``{"count": 4}``) to the flat string a future value-drift verifier would grep
# for in emitted bytes (``"4"``). WP7's post-gen check is gate-consistency, not
# value-drift, so nothing calls ``value_flatteners()`` today. This registry is
# the seam a later drift lane plugs into without editing this framework.


ValueFlattener = Callable[[object], str]

_VALUE_FLATTENERS: dict[str, ValueFlattener] = {}


def register_value_flattener(
    pattern: str,
) -> Callable[[ValueFlattener], ValueFlattener]:
    """Decorator: register a value flattener under ``pattern``. Raises on dup."""

    def deco(fn: ValueFlattener) -> ValueFlattener:
        if pattern in _VALUE_FLATTENERS:
            raise ValueError(
                f"value flattener already registered: {pattern!r}"
            )
        _VALUE_FLATTENERS[pattern] = fn
        return fn

    return deco


def value_flatteners() -> dict[str, ValueFlattener]:
    """A copy of the flattener registry (pattern -> callable)."""
    return dict(_VALUE_FLATTENERS)


@register_value_flattener("count")
def _flatten_count(value: object) -> str:
    """Flatten a ``{"count": N}`` cardinality value to ``str(N)``.

    The canonical example of a structured value a future value-drift verifier
    would compare against emitted bytes (T3 cardinality rows carry
    ``value={"count": N}`` / ``value={"catalog": N, "proposal": M}``). No live
    consumer in WP7 — registered to exercise + document the extension point.
    """
    if isinstance(value, dict) and "count" in value:
        return str(value["count"])
    raise ValueError(f"not a count-shaped value: {value!r}")
