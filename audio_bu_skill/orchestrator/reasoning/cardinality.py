"""Cardinality Authority (Track C / WP-C) — pure, target-agnostic, diagnostic-only.

Consumes the per-element-class instance counts the reasoning pass already
produced (``generated_case["audio_topology"]["element_counts"]``, schema 1.3.0 /
Fix A) and cross-checks the independent enumeration lanes (C.2) against each
other, emitting one diagnostic verdict per class (C.3/C.6).

It introduces **no new evidence**, reads only counts already on the case,
changes **no onboarding decision, promotion, or gating path**, and renders as an
additive report section exactly like the Confidence Ledger. A false positive
costs a reviewer one glance, never a blocked pipeline (C.9 asymmetry).

Design (FRAMEWORK_ARTIFACT_SPECIFICATION.md Track C):
  * C.1/C.8 element classes + which lanes are applicable per class live entirely
    in ``cardinality_config.py`` — this core is class-agnostic.
  * C.3 comparison: authority (``catalog``) present → compare every other lane
    against it; no authority (pre-SWI) → pairwise-agreement among available
    lanes. Output ``{class, counts:{source→n}, verdict, ...}``.
  * C.4 warning verdicts (``disagree`` / ``disagree_with_authority``) map to
    NEEDS_REVIEW; never hard-fail.
  * C.5 informational: a single usable lane → ``not_cross_checkable``; a KB
    legitimate-divergence rule downgrades a mismatch to ``benign_divergence``.
  * C.6 pre-SWI verdict vocabulary: agree / disagree / not_cross_checkable
    (+ benign_divergence); C.7 post-SWI adds disagree_with_authority / agree.

Two correctness rules the real Nord/Eliza data forced (see
docs/WP_C_PREFLIGHT_GAP_ANALYSIS.md):
  1. ``dt_applied: false`` with ``dt: 0`` means "audio scaffolding is unapplied
     at the pinned kernel HEAD", NOT "zero instances on the silicon". Such a dt
     lane is **not** a usable independent count — using it would emit a false
     ``disagree`` on every unapplied Nord/Eliza class. It is dropped from the
     cross-check (reported, with a note).
  2. ``ambiguous: true`` marks a count the reasoning pass itself could not
     resolve to a single integer (e.g. Eliza "1 or 2 masters"). A class flagged
     ambiguous is ``not_cross_checkable`` regardless of the lane integers — we
     must not manufacture agreement or disagreement from a number the source
     disowned.

Everything here is pure (no I/O) and deterministic: identical input → identical
rows, so it is unit-testable in isolation and safe to render.
"""

from __future__ import annotations

from typing import Any

from orchestrator.reasoning import cardinality_config as cfg

# ── C.6/C.7 verdict vocabulary ──
VERDICT_AGREE = "agree"
VERDICT_DISAGREE = "disagree"
VERDICT_NOT_CROSS_CHECKABLE = "not_cross_checkable"
VERDICT_BENIGN_DIVERGENCE = "benign_divergence"          # C.5 KB-registered divergence
VERDICT_DISAGREE_WITH_AUTHORITY = "disagree_with_authority"  # C.7 post-SWI only

# Verdicts that are a C.4 warning (→ NEEDS_REVIEW in the reviewer work list).
# benign_divergence and not_cross_checkable are informational (C.5), agree is clean.
_WARNING_VERDICTS: frozenset[str] = frozenset(
    {VERDICT_DISAGREE, VERDICT_DISAGREE_WITH_AUTHORITY}
)


def _usable_lanes(item: dict) -> tuple[dict[str, int], list[str]]:
    """Extract the lanes that are a legitimate independent count for this class.

    Returns ``(counts, notes)`` where ``counts`` maps C.2 source name → integer
    for every lane that is (a) applicable to the class per config, (b) present as
    a non-null integer, and (c) not disqualified by the dt_applied rule. ``notes``
    records why any lane was excluded, for transparent reporting.
    """
    element_class = item.get("element_class")
    applicable = cfg.applicable_sources(element_class)
    dt_applied = item.get("dt_applied")

    counts: dict[str, int] = {}
    notes: list[str] = []
    for lane in cfg.LANE_KEYS:
        source = cfg.SOURCE_NAME[lane]
        val = item.get(lane)
        if lane not in applicable:
            # Lane exists in the data but doctrine says it is not an authority for
            # this class (e.g. dt for soundwire_master — SWR-P1 not-DT-inferred).
            if isinstance(val, int):
                notes.append(f"{source}={val} present but not an authority for this class")
            continue
        if val is None:
            continue  # null = lane not consulted (distinct from an affirmative 0)
        if not isinstance(val, int):
            continue  # schema guarantees int|null, but stay defensive
        # Correctness rule 1: dt=0 under dt_applied=false is "unapplied at HEAD",
        # not "zero instances". Not a usable count.
        if lane == "dt" and val == 0 and dt_applied is False:
            notes.append("dt_count=0 is unapplied-at-HEAD (dt_applied=false), not an instance count")
            continue
        counts[source] = val
    return counts, notes


def _verdict(counts: dict[str, int], *, ambiguous: bool, divergence_rule: str | None
             ) -> tuple[str, str | None]:
    """C.3/C.4/C.5 verdict from the usable lane counts. Returns (verdict, rule_id).

    Precedence:
      1. ambiguous:true         → not_cross_checkable (correctness rule 2).
      2. < 2 usable lanes       → not_cross_checkable (C.5 — nothing to compare).
      3. authority present      → compare all vs catalog_count (C.3/C.7):
                                    all match → agree; else disagree_with_authority.
      4. no authority, agree    → agree.
      5. no authority, disagree → benign_divergence (+rule) if a KB divergence
                                    rule is registered (C.5), else disagree (C.4).
    """
    if ambiguous:
        return VERDICT_NOT_CROSS_CHECKABLE, None

    authority = cfg.SOURCE_NAME["catalog"]
    if authority in counts:
        # C.7: catalog is N. Any other usable lane that differs disagrees with it.
        others = {s: n for s, n in counts.items() if s != authority}
        if not others:
            return VERDICT_NOT_CROSS_CHECKABLE, None  # only the authority itself
        if all(n == counts[authority] for n in others.values()):
            return VERDICT_AGREE, None
        return VERDICT_DISAGREE_WITH_AUTHORITY, None

    # Pre-SWI: pairwise agreement among the available independent lanes (C.6).
    if len(counts) < 2:
        return VERDICT_NOT_CROSS_CHECKABLE, None
    values = set(counts.values())
    if len(values) == 1:
        return VERDICT_AGREE, None
    # Mismatch. If a KB legitimate-divergence rule covers this class, downgrade to
    # informational (C.5); otherwise it is a C.4 warning.
    if divergence_rule:
        return VERDICT_BENIGN_DIVERGENCE, divergence_rule
    return VERDICT_DISAGREE, None


def compare_element_counts(gc: dict) -> list[dict]:
    """Return one cardinality row per configured element class present in the run.

    Row shape (C.3 output + diagnostics):
      {element_class, counts:{source→n}, verdict, rule_id, ambiguous,
       ambiguity_note, warning, notes, citations}

    Pure and deterministic. Reads only ``gc["audio_topology"]["element_counts"]``,
    null-guarded like the sibling ledger/section code, so a case with no
    element_counts (pre-1.3.0) yields ``[]`` and the report section is omitted.
    Rows are emitted in ``ELEMENT_CLASSES`` config order for stable rendering,
    regardless of the order the reasoning pass emitted them.
    """
    gc = gc or {}
    at = gc.get("audio_topology") or {}
    items = at.get("element_counts") or []

    # Index the provided items by class (last-wins is irrelevant — the reasoning
    # pass emits at most one row per class; defensive if not).
    by_class: dict[str, dict] = {}
    unknown: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("element_class")
        if cfg.is_known_class(name):
            by_class[name] = item
        elif isinstance(name, str):
            unknown.append(name)

    rows: list[dict] = []
    for name in cfg.known_classes():
        item = by_class.get(name)
        if item is None:
            continue  # class not reported for this target — omit its row
        counts, notes = _usable_lanes(item)
        ambiguous = bool(item.get("ambiguous"))
        verdict, rule_id = _verdict(
            counts, ambiguous=ambiguous, divergence_rule=cfg.divergence_rule(name)
        )
        rows.append(
            {
                "element_class": name,
                "counts": counts,
                "verdict": verdict,
                "rule_id": rule_id,
                "ambiguous": ambiguous,
                "ambiguity_note": item.get("ambiguity_note") if ambiguous else None,
                "warning": verdict in _WARNING_VERDICTS,
                "notes": notes,
                "citations": list(item.get("citations") or []),
            }
        )
    return rows
