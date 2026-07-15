"""Phase-2B WP1b — generation policy surface (constants, gates, path guard).

Companion to ``orchestrator/generation/model.py`` (WP1a — types). Keeps *policy*
(what opens a gate, what a skip reason is called, where writes may go) separate
from *types* (what a ``GeneratedArtifact`` looks like) so the two churn
independently.

Public surface (see ``__all__`` at the bottom):

* ``_GENERATION_ARTIFACT_ORDER`` — the deterministic tuple used by the WP7
  post-gen verifier and the WP8 renderer to emit artifacts in a stable order.
* ``GATING_ROWS`` — per-artifact conjunctive gating expressions (§4.1). Each
  ``(track, subject_pattern)`` pair must be OPEN (per §4 rules + §3.7 advisory
  carve-out) for the artifact's generator to run.
* ``SKIP_REASONS`` — the complete, closed enumeration of skip-reason strings
  (§WP1b). Any string outside this set that reaches ``GeneratorSkipped.reason``
  is a policy violation (WP10 lint test enforces this).
* ``ADVISORY_ROWS`` — the T4b-only carve-out (§3.7). Adding a track here is a
  spec change (§3.7 line: "Adding a new advisory row is a spec change").
* ``KNOWN_BAD_PARTIAL_MATCH_RULES`` — donor-residue rule_ids that must NOT
  open a gate even on PARTIAL_MATCH (§4.4). As of spec v1.0 there is exactly
  one member: ``t5.donor.firmware.sa8775p`` (Eliza donor DTSI).
* ``PATH_GUARD_ROOT`` — the only tree the engine may write to. ``is_path_within_guard``
  is the predicate the WP10 runner uses to enforce §5.4.

Import discipline (mirrors WP1a's discipline in reverse):

* This module MAY import from ``orchestrator.reasoning.crossverify_model`` for
  ``VerificationRow`` type parity (adjacent facing).
* This module MUST NOT import from ``orchestrator.generation.model`` — the
  invariant is: model → generic types; config → policy; runner (WP10) is the
  only site that composes both. Enforced by
  ``tests/test_generation_config.py::test_import_guard_no_model_import``.
* No I/O at import time. No timestamps. No env reads. Pure constants + one
  pure predicate.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_config``
"""

from __future__ import annotations

import os
import posixpath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # VerificationRow is not used at runtime here — this module ships only
    # constants + a pure predicate. The type-only import documents the parity
    # (config.py and model.py both anchor on VerificationRow) while keeping
    # the runtime import graph minimal.
    from orchestrator.reasoning.crossverify_model import VerificationRow  # noqa: F401


# ── §WP1b (1) — artifact order ─────────────────────────────────────────────
#
# The canonical ordering used by:
#   * WP7 post-gen verifier — iterates artifacts in this order so the
#     ``cross_verification.rows`` append order is stable across runs.
#   * WP8 renderer — emits the ``## Generated Artifacts`` section in this
#     order, matching the fixture chain from ``tests/fixtures/phase2b/``.
#
# Adding a new artifact class means adding it here AND adding a
# ``GATING_ROWS`` entry (the two are keyed together — enforced by
# ``test_artifact_order_matches_gating_keys``).
_GENERATION_ARTIFACT_ORDER: tuple[str, ...] = (
    "dt_scaffolding",
    "codec_stub",
    "machine_driver",
    "audioreach_topology",
)


# ── §WP1b (2) — gating tables (per spec §4.1) ──────────────────────────────
#
# Per-artifact gating expressions. Each key is an artifact_class from
# ``_GENERATION_ARTIFACT_ORDER``; each value is a tuple of ``(track, subject_pattern)``
# pairs. All pairs must be OPEN (per §4 gating rules) for the generator to run.
#
# ``subject_pattern`` is a glob-ish string:
#   * ``"gpio.i2s.*"`` — every subject under the ``gpio.i2s`` prefix (WP3 fans
#     out per-pin at runtime).
#   * ``"qup.*"`` — every QUP endpoint.
#   * ``"*"`` — any subject under this track (WP5's ``T4b.*`` and ``T2.*``,
#     WP4's ``T4a.*`` / ``T4b.*``). The runner (WP10) expands these at gate-
#     evaluation time against ``TrustedFacts.rows_by_track_subject``.
#
# Advisory-row handling (§3.7): ``T4b`` entries participate in gating, but a
# ``T4b`` row that is ``NOT_CROSS_CHECKABLE + authority_out_of_scope`` OR
# ``REVIEW_REQUIRED`` is treated as OPEN (the reviewer signs off the binding
# manually — see ``ADVISORY_ROWS`` below).
#
# Known-bad donor residue (§4.4): a ``T5.dts.firmware`` PARTIAL_MATCH row whose
# ``rule_id`` is in ``KNOWN_BAD_PARTIAL_MATCH_RULES`` is downgraded to a skip
# regardless of this table — enforced at the runner, not here.
GATING_ROWS: dict[str, tuple[tuple[str, str], ...]] = {
    "dt_scaffolding": (
        ("T1", "gpio.i2s.*"),
        ("T5", "dts.firmware"),
        ("T5", "dts.compatible"),
    ),
    "codec_stub": (
        ("T4a", "*"),  # codec's SoC-side endpoint confirmed
        ("T4b", "*"),  # codec side; advisory row (see ADVISORY_ROWS)
    ),
    "machine_driver": (
        ("T1", "gpio.i2s.*"),  # pins wired
        ("T4a", "qup.*"),      # SoC endpoints valid
        ("T4b", "*"),          # codec side; advisory row
        ("T2", "*"),           # any DISAGREE on the bus closes this gate
    ),
    "audioreach_topology": (
        ("T3", "lpass_macro_instance"),
        ("T3", "dsp_subsystem_instance"),
    ),
}


# ── §WP1b (3) — skip reasons (closed enumeration) ──────────────────────────
#
# Every ``GeneratorSkipped.reason`` value emitted by WP3–WP10 MUST come from
# this set. A frozenset (not an Enum) so callers can write
# ``GeneratorSkipped(reason="gating_row_warning", ...)`` without a preceding
# ``SkipReason.GATING_ROW_WARNING.value`` — matching Phase-2A's discipline of
# string verdicts.
#
# The spec (§WP1b) lists ten reasons; WP10 (§5.4) adds ``path_guard_violation``
# — the runner emits this when a generator's ``path_hint`` escapes
# ``PATH_GUARD_ROOT``. Eleven total.
SKIP_REASONS: frozenset[str] = frozenset({
    "gating_row_warning",
    "gating_row_review_required",
    "gating_row_disagree",
    "gating_row_partial_match_donor_residue",
    "authority_not_in_snapshot",
    "kb_rule_missing",
    "codec_binding_disagreement",
    "gating_row_disagree_on_bus",
    "gating_row_disagree_on_lpass_count",
    "gating_row_ambiguous_soundwire",
    "path_guard_violation",
})


# ── §WP1b (4) — advisory rows (§3.7 carve-out) ─────────────────────────────
#
# The ONLY track whose ``NOT_CROSS_CHECKABLE + authority_out_of_scope`` (or
# ``REVIEW_REQUIRED``) verdict is treated as OPEN for gating purposes. From
# §3.7: "T4b's authority is 'OOS by design' — IPCAT does not enumerate codec
# DT bindings, and Phase-2A honors that by marking every T4b row NCC with
# ``coverage_gap_reason=authority_out_of_scope``. Phase-2B needs to generate
# against T4b anyway, which requires treating T4b as an advisory row."
#
# Every other track (T1, T2, T3, T4a, T5) requires MATCH (or PARTIAL_MATCH-open
# per §4.4). Adding a new advisory track is a spec change to §3.7 — the
# ``test_advisory_rows_only_t4b`` test fails on any drift.
ADVISORY_ROWS: frozenset[tuple[str, str]] = frozenset({("T4b", "*")})


# ── §WP1b (5) — known-bad PARTIAL_MATCH rules (§4.4) ───────────────────────
#
# PARTIAL_MATCH rows carry a KB ``rule_id``. Most such rows open their gates
# (the reviewer sees the ``rule_id`` in the artifact header comment). But a
# subset — donor-residue rules — are known-bad, not "review-needed":
#
#   ``t5.donor.firmware.sa8775p`` — Eliza donor DTSI residue. The row matches
#   on SoC family but the firmware path is *known* to be wrong (sa8775p is
#   Nord's SoC). Emitting a PARTIAL_MATCH-open DTS here would bake the donor
#   bug into a generated artifact.
#
# The runner (WP10) checks a PARTIAL_MATCH row's ``rule_id`` against this
# frozenset; a match emits ``GeneratorSkipped(reason=gating_row_partial_match_donor_residue)``
# instead of opening the gate.
#
# Adding a rule to this frozenset is a spec change to §4.4 — enforced by
# ``test_known_bad_rules_only_donor_sa8775p``.
KNOWN_BAD_PARTIAL_MATCH_RULES: frozenset[str] = frozenset({"t5.donor.firmware.sa8775p"})


# ── §WP1b (6) — path guard (§5.4) ──────────────────────────────────────────
#
# The only tree the engine may write to. Every generator's ``path_hint`` must
# be a path under this root; ``is_path_within_guard`` is the pure predicate
# the WP10 runner calls before invoking a generator's ``.write()``.
#
# Slash-terminated so ``PATH_GUARD_ROOT + "<run_id>/foo.dts"`` composes
# without a joining slash and so ``startswith(PATH_GUARD_ROOT)`` is not
# fooled by a sibling directory named ``generated_x/``.
PATH_GUARD_ROOT: str = "generated/"


def is_path_within_guard(path: str) -> bool:
    """Return True iff ``path`` is a location inside ``PATH_GUARD_ROOT``.

    Rules:

    * Absolute paths (starting with ``/``) → False. The engine only writes to
      workspace-relative locations; a bare ``/etc/passwd`` or the like is a
      violation, full stop.
    * Empty / whitespace-only paths → False (would normalize to ``"."`` which
      is definitionally outside).
    * Windows-style drive letters (``C:\\...``) → False. Same rationale.
    * The path is normalized via ``posixpath.normpath`` (collapses ``.``,
      ``..``, doubled slashes). If normalization pushes the path to ``".."``
      or a component of the normalized path escapes ``PATH_GUARD_ROOT``, the
      predicate returns False.
    * Otherwise, the normalized path must start with ``"generated/"``. Bare
      ``"generated"`` is accepted (equals the root); anything else must be
      strictly nested.

    Deliberately does NOT touch the filesystem — no ``os.path.exists``, no
    symlink resolution. Symlink handling is the runner's job (§5.4 line 4:
    "no ``os.system``/subprocess/git" — same discipline, no filesystem side
    effects at policy time).
    """
    if not path or not path.strip():
        return False
    # Windows drive letters (``C:\\``, ``D:/``). ``os.path.isabs`` handles
    # ``/`` on POSIX but not drive letters on POSIX systems, so the explicit
    # check matters even on Linux.
    if len(path) >= 2 and path[1] == ":":
        return False
    # POSIX absolute — never a workspace path.
    if path.startswith("/"):
        return False
    # ``os.path.isabs`` catches ``/etc/passwd`` on POSIX; belt-and-braces.
    if os.path.isabs(path):
        return False
    normalized = posixpath.normpath(path)
    if normalized == ".." or normalized.startswith("../"):
        return False
    # ``"generated"`` → root itself; ``"generated/<run_id>/..."`` → nested.
    root_no_slash = PATH_GUARD_ROOT.rstrip("/")
    if normalized == root_no_slash:
        return True
    return normalized.startswith(root_no_slash + "/")


__all__ = [
    "_GENERATION_ARTIFACT_ORDER",
    "GATING_ROWS",
    "SKIP_REASONS",
    "ADVISORY_ROWS",
    "KNOWN_BAD_PARTIAL_MATCH_RULES",
    "PATH_GUARD_ROOT",
    "is_path_within_guard",
]
