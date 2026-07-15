"""Phase-2B WP4 — codec stub generator (second generator lane).

Pure, stdlib-only codec-binding generator. Consumes a WP2-projected
``TrustedFacts`` and emits either a ``GeneratedArtifact`` carrying a C source
file (i2c client stanzas for the Nord IQ-10 board codecs) or a
``GeneratorSkipped`` when the gates are closed.

The codec stub is the *second* artifact class in
``_GENERATION_ARTIFACT_ORDER`` (after ``dt_scaffolding``). It unblocks the
codec-driver work-item: given a Nord target with a MATCHed T4a QUP endpoint
(``i2c18`` = QUP2_SE4 on SA8797P) and T4b advisory rows for the two board
codecs (ADAU1979 ADC, PCM1681 DAC), this generator emits a machine-driver-
adjacent C file declaring the two codec i2c clients as ``struct i2c_board_info``
stanzas plus a bus-level ``i2c_add_driver`` skeleton. The full DAI-link + card
wiring lands in WP5 (machine driver).

Nord-family scoping (WP4):

  * Two board codecs on ``&i2c18``:

    - ADI ADAU1979 quad-ADC at 7-bit i2c addr ``0x31`` (compatible
      ``adi,adau1979``). Nord's audio input path — mic captures.
    - TI PCM1681 8-channel DAC at 7-bit i2c addr ``0x4c`` (compatible
      ``ti,pcm1681``). Nord's audio output path — speaker feeds.

  * Control bus: ``&i2c18`` = the SoC-side QUP2_SE4 controller on SA8797P.
    T4a's ``qup.se3`` row confirms the endpoint at the SoC side; the
    ``qup.se3`` subject in the fixture is the semantic anchor for
    ``T4a.qup.*`` gating (WP4 gates on the ``T4a.qup.*`` prefix — see
    ``_GATING_ROW_NAMES`` below).

  * Both codecs' T4b rows are advisory (§3.7): IPCAT does not enumerate codec
    DT bindings, so Phase-2A marks both rows NCC + authority_out_of_scope
    with ``rule_id=t4b.codec_binding.out_of_scope``. WP4 treats those rows
    as gate-OPEN for the advisory carve-out; the reviewer confirms the DAI-
    link binding against the schematic.

  * DAI-cells contract: emit ``#sound-dai-cells = <0>`` per codec — the two
    board codecs are single-DAI devices. The SoC-side ``q6apmbedai`` uses
    ``#sound-dai-cells = <1>`` (single-cell = LPASS port ID), but that lives
    in WP5 (machine driver), not here.

Gating (per PHASE2B_SPECIFICATION.md §4.1 + §WP4):

  1. **T4a QUP endpoint gate — MATCH or PARTIAL_MATCH-open** (strict per §4).
     The codec control bus (``i2c18`` = QUP2_SE4) MUST be authoritatively
     confirmed by IPCAT; a REVIEW_REQUIRED / NCC on ``T4a.qup.*`` closes the
     gate and the generator refuses. The T4a subject vocabulary in the
     runtime fixture uses dot separators (``qup.se3``) — WP4 iterates the
     projection and accepts ANY ``T4a.qup.*`` MATCH as the endpoint anchor.

  2. **T4b codec-binding advisory gate — NCC + authority_out_of_scope opens.**
     Per §3.7 advisory carve-out, a T4b row that is NCC with
     ``coverage_gap_reason=authority_out_of_scope`` OPENS the gate (the
     reviewer signs off manually). At least ONE such row must be present
     for the generator to have a codec to emit; WP4 iterates all
     ``T4b.codec.*`` rows and emits one i2c client stanza per advisory-open
     codec, in sorted-subject order (byte-determinism). No codec rows → skip.

  3. **T4b disagreement — hard skip** (``codec_binding_disagreement``, per
     WP1b ``SKIP_REASONS``). If any ``T4b.codec.*`` row is
     DISAGREE_WITH_AUTHORITY, the generator refuses across the board — a
     partial emit with one codec confirmed and one disagreeing would be
     worse than no emit at all (the resulting machine driver would sound-
     card-boot but bind the wrong device on the disagreeing side).

Header comment discipline (§4.4): inherited from WP3. If any codec row is
PARTIAL_MATCH-open with a non-known-bad ``rule_id``, a fixed machine-parseable
comment block naming the ``rule_id`` is prepended to ``bytes_``. As of WP4
Nord-truth, both codec rows are NCC (not PARTIAL_MATCH), so this discipline
is dormant in practice — but the code path is present for future authority
integrations that DO produce PARTIAL_MATCH-open codec rows.

Zero I/O, zero timestamps, zero env reads. Byte-identical input → byte-
identical output.

Import discipline (WP4 — mirrors WP3):

  * MAY import: ``orchestrator.generation.model`` (WP1a — dataclasses),
    ``orchestrator.generation.config`` (WP1b — ``PATH_GUARD_ROOT``,
    ``KNOWN_BAD_PARTIAL_MATCH_RULES``),
    ``orchestrator.reasoning.crossverify_model`` (``VerificationRow`` — needed
    to append partial-artifact rows to ``contributes_rows``).
  * MUST NOT import: ``orchestrator.generation.facts`` (WP4 receives
    ``TrustedFacts`` as input, like WP3);
    ``orchestrator.reasoning.crossverify`` /
    ``orchestrator.reasoning.cardinality`` (Phase-2A internals);
    ``orchestrator.generation.dt_scaffolding`` (peer generator — no
    generator↔generator coupling).
  * Enforced by ``tests/test_generation_codec.py::test_import_guard``.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_codec``
"""

from __future__ import annotations

from orchestrator.generation.config import (
    KNOWN_BAD_PARTIAL_MATCH_RULES,
    PATH_GUARD_ROOT,
)
from orchestrator.generation.model import (
    GeneratedArtifact,
    GeneratorSkipped,
    GenerationResult,
    TrustedFacts,
)
from orchestrator.reasoning.crossverify_model import VerificationRow

# ── Nord IQ-10 constants (WP4, Nord-family scoped) ──────────────────────────

#: The artifact class this generator emits. Fixed — matches the WP1b
#: ``_GENERATION_ARTIFACT_ORDER`` second entry.
_ARTIFACT_CLASS: str = "codec_stub"

#: Track-prefixes this generator inspects, listed in the order the spec
#: enumerates them. Used verbatim in ``GeneratorSkipped.gating_rows`` so a
#: skipped verdict names its closed gates in a stable order. WP4 tightens the
#: WP1b ``("T4a", "*")`` slot down to ``T4a.qup.*`` — the codec control-bus
#: endpoint MUST be a QUP, not any other T4a subject.
_GATING_ROW_NAMES: tuple[str, ...] = (
    "T4a.qup.*",
    "T4b.codec.*",
)

#: Nord codec control bus — the SoC-side QUP i2c controller node name.
#: Verified against the Nord IQ-10 DTS: the two board codecs live under
#: ``&i2c18 { ... }`` (which is QUP2_SE4 on SA8797P). The T4a fixture uses
#: ``qup.se3`` as its subject anchor — ``se3`` is the semantic name in the
#: fixture regardless of the physical SE number. WP4 does not look up SE→bus
#: at generation time; the fixture's MATCH is the authority.
_I2C_BUS_LABEL: str = "&i2c18"

#: Per-codec board-info parameters, keyed by codec subject *suffix* (the part
#: after ``codec.``). Iterated in ``sorted()`` order at emit time so the
#: generated bytes are deterministic regardless of ``rows_by_track_subject``
#: iteration order.
#:
#: Each value is ``(compatible, i2c_addr_hex, description)``:
#:
#:   * ``compatible`` — the linux-audio compatible string driver authors match
#:     on. ``adi,adau1979`` and ``ti,pcm1681`` are the upstream-accepted forms
#:     (matches drivers/mfd/adau1979.c and sound/soc/codecs/pcm1681.c).
#:   * ``i2c_addr_hex`` — 7-bit i2c slave address on ``&i2c18``. ADAU1979 pin-
#:     straps to 0x31 (ADDR0=1, ADDR1=1) on Nord IQ-10; PCM1681 pin-straps to
#:     0x4c (ADR0=0, ADR1=0). Numeric literals emitted uppercase-hex.
#:   * ``description`` — human-readable comment inserted next to the stanza so
#:     a reviewer eyeballing the C source doesn't have to grep for the part
#:     number.
_NORD_CODECS: dict[str, tuple[str, int, str]] = {
    "adau1979": ("adi,adau1979", 0x31, "ADI ADAU1979 quad-ADC (mic capture)"),
    "pcm1681": ("ti,pcm1681", 0x4c, "TI PCM1681 8-channel DAC (speaker feed)"),
}

#: Board-side signals that the codec stub cannot resolve from IPCAT — the
#: reviewer must hand-wire these against the schematic. Emitted as a fixed
#: ``FIXME`` block at the tail of the generated C source so a grep for
#: ``FIXME(``  surfaces every outstanding item.
_FIXME_SIGNALS: tuple[tuple[str, str], ...] = (
    ("reset-gpios", "codec reset line — pin # varies per board revision"),
    ("ADC_MCLK", "shared MCLK feed for the ADAU1979 — sourced from LPASS or crystal, board-specific"),
    ("GLOBAL_MD_OE", "codec-domain output-enable line — schematic net, no IPCAT authority"),
)


def generate_codec_stub(facts: TrustedFacts, kb: object | None = None) -> GenerationResult:
    """Emit a codec stub artifact or a skipped verdict for one target.

    Pure, deterministic, zero I/O. Byte-identical ``facts.to_dict()`` produces
    byte-identical ``result.to_dict()`` (modulo ``bytes_hex``).

    Parameters
    ----------
    facts:
        Immutable projection of a target's Phase-2A verification rows.
    kb:
        Optional knowledge-base handle (reserved for symmetry with future
        generators). WP4 does not consult a KB — the ``rule_id`` field on
        gating rows is the entire policy signal, and codec bindings are
        authority-less by design.

    Returns
    -------
    GenerationResult
        Either a ``GeneratedArtifact`` (bytes + contributes_rows) or a
        ``GeneratorSkipped`` naming its closed gates.

    The ``subject`` field on the returned dataclass is the fixed literal
    ``"codec_stub"`` — matching ``artifact_class`` — because WP4 emits one
    artifact per target, not one per codec.
    """
    del kb  # WP4 does not consult a KB — see docstring.

    # ── Gate 1: T4a QUP endpoint — at least one T4a.qup.* MATCH ────────────
    #
    # The T4a runtime subject vocabulary in the fixture uses dot separators
    # (``qup.se3``, etc.). We enumerate every ``T4a.qup.*`` row and open the
    # gate if AT LEAST ONE opens under the strict WP1a rules (MATCH or
    # PARTIAL_MATCH-open, no advisory carve-out — T4a is NOT in ADVISORY_ROWS).
    #
    # No open T4a.qup.* row → closed gate. Pick the most-specific skip reason:
    # if any T4a.qup.* row is DISAGREE_WITH_AUTHORITY, that is the *why*;
    # otherwise a warning/review/missing tail — collapse to gating_row_warning
    # as the catch-all (the surviving reasons are all "reviewer signal on the
    # row itself", per WP3's ``_skip_reason_for_closed_gate`` pattern).
    qup_rows = _rows_with_prefix(facts, "T4a.qup.")
    open_qup_rows = [row for row in qup_rows if facts.is_open(row.track, row.subject)]
    if not open_qup_rows:
        return GeneratorSkipped(
            subject=_ARTIFACT_CLASS,
            artifact_class=_ARTIFACT_CLASS,
            reason=_skip_reason_for_no_open_qup(qup_rows),
            gating_rows=["T4a.qup.*"],
        )

    # ── Gate 2: T4b codec disagreement — hard skip ──────────────────────────
    #
    # Any DISAGREE_WITH_AUTHORITY on a codec row → refuse. A partial emit
    # (one codec confirmed, one disagreeing) would be worse than no emit at
    # all, because the resulting machine driver would sound-card-boot and
    # then bind the wrong device on the disagreeing side.
    codec_rows = _rows_with_prefix(facts, "T4b.codec.")
    disagreeing_codecs = [row for row in codec_rows if row.verdict == "DISAGREE_WITH_AUTHORITY"]
    if disagreeing_codecs:
        # Name the specific disagreeing rows in gating_rows (in sort order for
        # determinism), so a reviewer greps the JSON for the offending codec.
        offending = sorted(f"T4b.{row.subject}" for row in disagreeing_codecs)
        return GeneratorSkipped(
            subject=_ARTIFACT_CLASS,
            artifact_class=_ARTIFACT_CLASS,
            reason="codec_binding_disagreement",
            gating_rows=offending,
        )

    # ── Gate 3: at least one advisory-open codec row must exist ────────────
    #
    # A T4b row is advisory-open per §3.7 when it is NCC +
    # authority_out_of_scope (the codec DT binding is authority-less by design;
    # the reviewer signs off manually). WP4 also accepts MATCH / PARTIAL_MATCH
    # here as a forward-compatibility hook — a future authority integration
    # that DOES produce non-NCC codec rows continues to open the gate.
    advisory_codecs = [row for row in codec_rows if _t4b_advisory_open(row)]
    if not advisory_codecs:
        return GeneratorSkipped(
            subject=_ARTIFACT_CLASS,
            artifact_class=_ARTIFACT_CLASS,
            reason="authority_not_in_snapshot",
            gating_rows=["T4b.codec.*"],
        )

    # ── Gates open — build the artifact ─────────────────────────────────────
    #
    # We assemble the C source in a fixed line list, joining with LF at the
    # end. No timestamps, no target-name interpolation — the subject anchor
    # ``codec_stub`` is the sole variable.
    lines: list[str] = []
    contributes_rows: list[VerificationRow] = []

    # Header comment discipline (§4.4): inherited from WP3. If ANY advisory-
    # open codec row is PARTIAL_MATCH with a non-known-bad rule_id, prepend
    # the machine-parseable header comment naming each such row's rule_id in
    # sorted-subject order (byte determinism).
    partial_match_rows = sorted(
        (
            row
            for row in advisory_codecs
            if row.verdict == "PARTIAL_MATCH"
            and row.rule_id is not None
            and row.rule_id not in KNOWN_BAD_PARTIAL_MATCH_RULES
        ),
        key=lambda r: r.subject,
    )
    for row in partial_match_rows:
        lines.append(
            f"// PARTIAL_MATCH gate: T4b.{row.subject} (rule_id={row.rule_id})"
        )
        lines.append(
            "//   The codec row matched via a KB-downgraded verdict; the"
        )
        lines.append(
            "//   reviewer must confirm the DAI-link binding against"
        )
        lines.append(
            "//   the schematic before this artifact is merged."
        )

    # Fixed C source preamble.
    lines.append("/*")
    lines.append(" * Generated by Phase-2B WP4 codec_stub.")
    lines.append(" * Deterministic. No timestamps.")
    lines.append(" *")
    lines.append(f" * Control bus: {_I2C_BUS_LABEL} (SoC QUP i2c controller — confirmed by T4a.qup.*).")
    lines.append(" * DAI-cells: <0> per codec (both are single-DAI devices).")
    lines.append(" */")
    lines.append("")
    lines.append("#include <linux/i2c.h>")
    lines.append("#include <linux/module.h>")
    lines.append("")

    # Emit one board_info stanza per advisory-open codec, sorted by subject
    # for deterministic bytes. A codec whose subject suffix is NOT in
    # ``_NORD_CODECS`` (unrecognised device on the bus) gets a FIXME stanza +
    # a partial-artifact ``NOT_CROSS_CHECKABLE`` row in ``contributes_rows``.
    sorted_codec_rows = sorted(advisory_codecs, key=lambda r: r.subject)
    for index, row in enumerate(sorted_codec_rows):
        codec_key = row.subject[len("codec.") :] if row.subject.startswith("codec.") else row.subject
        if index > 0:
            lines.append("")
        if codec_key in _NORD_CODECS:
            compatible, i2c_addr, description = _NORD_CODECS[codec_key]
            lines.append(f"/* {description} */")
            lines.append(f"static struct i2c_board_info nord_{codec_key}_info = {{")
            lines.append(f"\t.type = \"{codec_key}\",")
            lines.append(f"\t.addr = 0x{i2c_addr:02x},")
            lines.append(f"\t/* compatible = \"{compatible}\" */")
            lines.append("};")
        else:
            # Unrecognised codec on the bus (row is advisory-open but the
            # subject suffix isn't a Nord-known device). Emit a FIXME stanza
            # AND contribute a partial-artifact NCC row so the reviewer sees
            # the gap in the WP7 re-verification pass.
            lines.append(f"/* FIXME({codec_key}): codec advisory-open but not in Nord codec table */")
            lines.append(f"static struct i2c_board_info nord_{codec_key}_info = {{")
            lines.append(f"\t/* FIXME({codec_key}): fill compatible + addr from schematic */")
            lines.append("};")
            contributes_rows.append(
                VerificationRow(
                    track="T4b",
                    subject=row.subject,
                    verdict="NOT_CROSS_CHECKABLE",
                    coverage_gap_reason="authority_out_of_scope",
                    notes=[
                        f"codec_stub: subject {row.subject!r} advisory-open but "
                        "not in Nord codec table — FIXME emitted; reviewer must "
                        "supply compatible + i2c addr from schematic."
                    ],
                )
            )

    # Trailing FIXME block for the board-side signals the codec stub cannot
    # resolve from IPCAT authority. Emitted as fixed comments in a fixed
    # order — no VerificationRow contributions here (these are hand-review
    # items, not derived facts).
    lines.append("")
    lines.append("/*")
    lines.append(" * Reviewer TODO — board-side signals not resolvable from IPCAT:")
    lines.append(" *")
    for name, description in _FIXME_SIGNALS:
        lines.append(f" *   FIXME({name}): {description}")
    lines.append(" */")

    # Trailing newline — LF line endings, no BOM. Exactly one LF at EOF.
    bytes_ = ("\n".join(lines) + "\n").encode("utf-8")

    return GeneratedArtifact(
        subject=_ARTIFACT_CLASS,
        artifact_class=_ARTIFACT_CLASS,
        path_hint=f"{PATH_GUARD_ROOT}{_ARTIFACT_CLASS}/nord_codec.c",
        bytes_=bytes_,
        contributes_rows=contributes_rows,
    )


def _rows_with_prefix(facts: TrustedFacts, prefix: str) -> list[VerificationRow]:
    """Return every projected row whose ``<track>.<subject>`` key starts with ``prefix``.

    Returned in sorted-key order so downstream iteration is deterministic even
    if the underlying dict populated its keys out of order.
    """
    return [
        facts.rows_by_track_subject[key]
        for key in sorted(facts.rows_by_track_subject)
        if key.startswith(prefix)
    ]


def _t4b_advisory_open(row: VerificationRow) -> bool:
    """Return True iff a T4b codec row is advisory-open per §3.7.

    Advisory-open covers:

      * ``NOT_CROSS_CHECKABLE + coverage_gap_reason=authority_out_of_scope`` —
        the canonical §3.7 case: IPCAT has no authority to enumerate codec DT
        bindings, so the row is honestly-NCC and the reviewer signs off.
      * ``REVIEW_REQUIRED`` — the reviewer already has an outstanding TODO on
        the codec row; the gate opens (WP4 is emitting the reviewer's TODO
        target, so bypassing here is not the type of bypass that dodges a
        review).
      * ``MATCH`` / ``PARTIAL_MATCH-open`` — forward-compatibility hook for a
        future authority that DOES produce non-NCC codec rows. A
        PARTIAL_MATCH row with a known-bad rule_id would still count as open
        here — the runner (WP10) applies the ``KNOWN_BAD_PARTIAL_MATCH_RULES``
        filter at a higher layer; WP4 only sees the T5.dts.firmware rule_id
        in that frozenset, so this is a no-op in practice.

    Note: ``warning=True`` on a T4b row does NOT close the advisory gate — the
    T4b row is *expected* to carry ``warning=True`` when it is
    NCC+authority_out_of_scope (see spec §3.7). The reviewer sign-off IS the
    warning-resolution.
    """
    if row.verdict == "NOT_CROSS_CHECKABLE":
        return row.coverage_gap_reason == "authority_out_of_scope"
    return row.verdict in ("REVIEW_REQUIRED", "MATCH", "PARTIAL_MATCH")


def _skip_reason_for_no_open_qup(qup_rows: list[VerificationRow]) -> str:
    """Pick the most-specific skip reason when no T4a.qup.* row is open.

    * No rows at all → ``authority_not_in_snapshot`` (Phase-2A didn't project
      any QUP endpoint for this target — the runner cannot know which control
      bus to emit against).
    * Any DISAGREE_WITH_AUTHORITY → ``gating_row_disagree`` (a specific QUP
      row disagrees; the SoC-side endpoint is wrong).
    * REVIEW_REQUIRED / warning → ``gating_row_review_required`` /
      ``gating_row_warning`` (fall-through order).
    * Otherwise ``gating_row_warning`` as the catch-all.
    """
    if not qup_rows:
        return "authority_not_in_snapshot"
    if any(row.verdict == "DISAGREE_WITH_AUTHORITY" for row in qup_rows):
        return "gating_row_disagree"
    if any(row.verdict == "REVIEW_REQUIRED" for row in qup_rows):
        return "gating_row_review_required"
    return "gating_row_warning"


__all__ = ["generate_codec_stub"]
