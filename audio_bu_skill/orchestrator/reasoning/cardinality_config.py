"""Cardinality Authority — element-class configuration (Track C / WP-C, C.1/C.8).

The *only* place the set of enumerable element classes and their per-class rules
live. New classes are added by adding a row here (config), never by touching the
comparison core (``cardinality.py``) — that is the C.8 extensibility contract.

Each row declares:
  * ``applicable_sources`` — which enumeration lanes (C.2) are a *legitimate*
    independent count for this class. This is where domain doctrine lives: e.g.
    a SoundWire master count must NOT be inferred from DT nodes (soundwire.md
    anti-pattern SWR-P1 / provenance "not DT-inferred"), so ``dt`` is omitted for
    ``soundwire_master``. A lane present in the data but not applicable for a
    class is reported but excluded from the cross-check.
  * ``divergence_rule`` — a KB "legitimate divergence" rule ID (C.5). When two
    applicable lanes disagree and the class carries such a rule, the mismatch is
    downgraded to ``benign_divergence`` (informational, cite the rule) instead of
    a NEEDS_REVIEW ``disagree``. ``None`` = no registered benign divergence.
  * ``description`` — the matcher spec's human-readable intent (C.9): *what* one
    instance of this class is. Documented, not executed — WP-C consumes the
    pre-computed ``element_counts`` lanes rather than re-extracting counts, so no
    regex matcher runs here (per spec §7, dmic_line/audioreach_port *matchers*
    are postponed until a run exercises DT/evidence extraction; the *counts* are
    already provided by the reasoning pass).

Everything is a plain literal + pure accessor, so it is trivially unit-testable
and carries no I/O.
"""

from __future__ import annotations

# ── C.2 enumeration lanes, in canonical order (matches ANALYSIS_SCHEMA
# element_counts keys). ``catalog`` is always null pre-SWI (authority arrives in
# Track D / C.7); it is listed so the post-SWI upgrade is purely additive. ──
LANE_KEYS: tuple[str, ...] = ("dt", "evidence", "proposal", "catalog")

# element_count lane key → C.2 source name used in the comparison output.
SOURCE_NAME: dict[str, str] = {
    "dt": "dt_count",
    "evidence": "evidence_count",
    "proposal": "proposal_count",
    "catalog": "catalog_count",
}

# ── C.1 element classes (extensible config; NOT hardcoded per target) ──
# The six spec-canonical classes plus the two additional classes real onboarding
# runs actually emit (``amplifier``, ``speaker`` — discrete parts whose instance
# count is a distinct fact from the codec part-number list length). Adding a
# class is a row here; the core never changes.
ELEMENT_CLASSES: dict[str, dict] = {
    "soundwire_master": {
        # SWR-P1 anti-pattern: master count is NOT DT-inferred (soundwire.md
        # provenance: "enumeration/catalog surface per PROV-003; not DT-inferred").
        # So dt is deliberately excluded as an authority for this class.
        "applicable_sources": ["evidence", "proposal", "catalog"],
        # SWR-D1: master *count* vs master→peripheral *routing* are separate
        # evidence classes; an evidence lane that counted routed peripherals will
        # legitimately diverge from a proposal that counts silicon masters.
        "divergence_rule": "SWR-D1",
        "description": "a physical SoundWire master controller instance on the SoC",
    },
    "lpass_macro_instance": {
        "applicable_sources": ["dt", "evidence", "proposal", "catalog"],
        "divergence_rule": None,
        "description": "an LPASS macro block instance (tx/rx/wsa/va) wired in DT",
    },
    "dai_link": {
        "applicable_sources": ["dt", "evidence", "proposal", "catalog"],
        "divergence_rule": None,
        "description": "a sound-card DAI link (one dai-link node)",
    },
    "dmic_line": {
        # DMIC lines are a schematic/board fact; DT may not enumerate them
        # one-per-line, so dt is not treated as an authoritative count here.
        "applicable_sources": ["evidence", "proposal", "catalog"],
        "divergence_rule": None,
        "description": "a single digital-microphone data line (e.g. DMIC01/23/45/67)",
    },
    "audioreach_port": {
        "applicable_sources": ["dt", "evidence", "proposal", "catalog"],
        "divergence_rule": None,
        "description": "an AudioReach logical port mapped to a physical interface",
    },
    "dsp_subsystem_instance": {
        "applicable_sources": ["dt", "evidence", "proposal", "catalog"],
        "divergence_rule": None,
        "description": "an audio DSP (ADSP/Q6) remoteproc subsystem instance",
    },
    "amplifier": {
        "applicable_sources": ["dt", "evidence", "proposal", "catalog"],
        "divergence_rule": None,
        "description": "a discrete audio amplifier instance (distinct from part count)",
    },
    "speaker": {
        "applicable_sources": ["dt", "evidence", "proposal", "catalog"],
        "divergence_rule": None,
        "description": "a discrete speaker/transducer instance",
    },
}


def known_classes() -> list[str]:
    """The configured element classes, in a deterministic (config) order."""
    return list(ELEMENT_CLASSES.keys())


def is_known_class(name: object) -> bool:
    """True iff ``name`` is a configured element class (C.8: unknown classes are
    ignored by the comparison, surfaced separately rather than silently dropped)."""
    return isinstance(name, str) and name in ELEMENT_CLASSES


def applicable_sources(name: str) -> list[str]:
    """Lane keys that are a legitimate independent count for this class. Empty
    list for an unknown class (caller should have filtered via is_known_class)."""
    row = ELEMENT_CLASSES.get(name) or {}
    return list(row.get("applicable_sources") or [])


def divergence_rule(name: str) -> str | None:
    """KB legitimate-divergence rule ID for this class, or None (C.5)."""
    row = ELEMENT_CLASSES.get(name) or {}
    return row.get("divergence_rule")
