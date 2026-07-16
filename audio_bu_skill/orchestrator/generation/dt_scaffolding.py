"""Phase-2B WP3 — DT scaffolding generator (first generator lane).

Pure, stdlib-only DT-scaffolding generator. Consumes a WP2-projected
``TrustedFacts`` and emits either a ``GeneratedArtifact`` carrying DTSI text
(as raw bytes) or a ``GeneratorSkipped`` when the gates are closed.

The DT scaffolding is the *first* artifact class in
``_GENERATION_ARTIFACT_ORDER``. It exists to unblock a downstream reviewer's
work: given a Nord target with clean T1 (I2S pinmux) and T5 (firmware +
compatible) verdicts, this generator emits a ``sound.dtsi`` fragment that
declares the Nord I2S8 pinmux state node and the ADSP remoteproc bindings.
Anything else (sound-card wrapper, codec DAI-link, machine-driver bindings,
AudioReach topology) lands in later WPs (WP4-WP6).

Nord-family scoping (WP3):

  This first generator lane is intentionally scoped to Nord IQ-10 (SA8797P,
  lemans-family). WP3 emits:

    * The pinmux STATE node ``&tlmm { i2s8_active: i2s8-active-state { ... } }``
      with three sub-nodes (clk / ws / data), each carrying the pin number,
      the ``aud_intfc8_*`` mux function name, ``drive-strength`` and
      ``bias-disable``. This is the shape the Nord IQ-10 booting DTB uses
      (arch/arm64/boot/dts/qcom/iq10-evk compiled DT, line 8360+); it is
      NOT the legacy generic ``pinctrl-i2s-*:`` label form.

    * The ADSP remoteproc node ``&remoteproc_adsp { compatible; firmware-name; }``
      with ``compatible = "qcom,sa8775p-adsp-pas"`` and
      ``firmware-name = "qcom/sa8775p/adsp.mbn"``. Nord IQ-10 is SA8797P but
      uses the lemans-family shared ADSP firmware image (verified: the sibling
      lemans-evk.dts also carries ``qcom/sa8775p/adsp.mbn``; Phase-2A KB rule
      ``t5.donor.firmware.sa8775p`` catches the Eliza-target misuse of the
      same string — the rule needs a target-family carve-out, filed as a
      Phase-2A follow-up, does not block WP3).

  Consumer bindings (``pinctrl-0 = <&i2s8_active>`` on the sound-card node,
  DAI-link content, codec references) live inside ``sound{}`` under
  AudioReach's q6apmbedai — that shape is WP4/WP5 territory and is
  deliberately NOT emitted here.

  WP4+ will generalize the pin vocabulary + SoC-family constants; the
  Nord-only literals in this module are the intentional first-lane scope.

Gating (per PHASE2B_SPECIFICATION.md §4.1 + §WP3):

  1. **Known-bad donor residue check (§4.4) — runs first.**
     If ``T5.dts.firmware`` is ``PARTIAL_MATCH`` with a ``rule_id`` inside
     ``KNOWN_BAD_PARTIAL_MATCH_RULES`` (as of v1.0: exactly the sa8775p Eliza
     donor residue), the generator refuses. Emitting a PARTIAL_MATCH-open DTS
     here would bake the donor firmware path into a Nord artifact — this is
     exactly the defect class Phase-2A caught, now guarded at the generator.

  2. **T5.dts.firmware gate must be OPEN** (or PARTIAL_MATCH-open with a
     non-known-bad rule_id). Falling through here means either the row is
     missing (``authority_not_in_snapshot``) or the row carries a closed
     verdict (``DISAGREE_WITH_AUTHORITY`` / ``NOT_CROSS_CHECKABLE`` /
     ``REVIEW_REQUIRED``) — no firmware path, no artifact.

  3. **T5.dts.compatible gate must be OPEN.** Firmware alone is insufficient;
     the compatible string identifies the SoC-family this DTS targets.

  4. **T1 pins (per-pin granularity, per §4.1).** The gating expression
     ``("T1", "gpio.i2s.*")`` is satisfied file-wise as long as *some* pin is
     open; individual pins that are missing become ``FIXME(<pin>)`` markers
     in the emitted bytes AND contribute a partial-artifact
     ``NOT_CROSS_CHECKABLE`` row to ``contributes_rows``. Pins that ARE open
     emit real pin sub-node declarations.

Header comment discipline (§4.4): when ``T5.dts.firmware`` is ``PARTIAL_MATCH``
with a *non-known-bad* rule_id (gate opens, but the reviewer needs to see the
rule_id before merge), a fixed machine-parseable header comment block is
prepended to ``bytes_`` so downstream tooling can grep the artifact for
outstanding review actions.

Zero I/O, zero timestamps, zero env reads. Byte-identical input → byte-
identical output.

Import discipline (WP3):

  * MAY import: ``orchestrator.generation.model`` (WP1a — the four
    dataclasses) and ``orchestrator.generation.config`` (WP1b — policy
    constants: ``GATING_ROWS``, ``KNOWN_BAD_PARTIAL_MATCH_RULES``,
    ``PATH_GUARD_ROOT``); ``orchestrator.reasoning.crossverify_model``
    (``VerificationRow`` type — needed to append partial-artifact rows to
    ``contributes_rows``).
  * MUST NOT import: ``orchestrator.generation.facts`` (WP3 *receives*
    ``TrustedFacts`` as input — it does not call ``project_facts`` itself,
    that composition happens at the runner layer);
    ``orchestrator.reasoning.crossverify`` or
    ``orchestrator.reasoning.cardinality`` (Phase-2A internals).
  * Enforced by ``tests/test_generation_dt.py::test_import_guard``.

Run the tests: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_dt``
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
from orchestrator.generation.registry import register_generator
from orchestrator.reasoning.crossverify_model import VerificationRow

# ── Nord IQ-10 constants (WP3, Nord-family scoped) ──────────────────────────

#: Nord I2S8 pin set in fixed emit order. These are the three lines the IQ-10
#: board actually wires on i2s8 (clk / ws / data) — no MCLK sub-node exists
#: on the IQ-10 i2s8_active state; MCLK would live on a separate aud_mclk*
#: state if the board wired it, which IQ-10 does not. Iterated in this fixed
#: order so the generated bytes are deterministic.
_REQUIRED_I2S_PINS: tuple[str, ...] = ("clk", "ws", "data")

#: TLMM GPIO number per pin — matches PINGROUP(73/74/75) in
#: linux-nord/drivers/pinctrl/qcom/pinctrl-nord.c and the IQ-10 compiled DTB.
_PIN_GPIO: dict[str, int] = {"clk": 73, "ws": 74, "data": 75}

#: Nord aud_intfc8 mux function name per pin. These are the names the Nord
#: pinctrl driver enumerates (msm_mux_aud_intfc8_{clk,ws,data}). Emitting
#: any other function name here would prevent the board from actually taking
#: the pins to their aud_intfc8 alternate function.
_PIN_FUNCTION: dict[str, str] = {
    "clk": "aud_intfc8_clk",
    "ws": "aud_intfc8_ws",
    "data": "aud_intfc8_data",
}

#: ADSP compatible + firmware — lemans-family shared image. Nord IQ-10
#: (SA8797P) uses ``qcom/sa8775p/adsp.mbn`` because it is a lemans-family
#: part sharing the SA8775P ADSP image; verified against
#: linux-nord/arch/arm64/boot/dts/qcom/{iq10-evk,lemans-evk}.dts. Do NOT
#: swap this to a chip-name-based path — that pattern belongs to QUP
#: firmware (which IS chip-specific), not the ADSP.
_ADSP_COMPATIBLE: str = "qcom,sa8775p-adsp-pas"
_ADSP_FIRMWARE: str = "qcom/sa8775p/adsp.mbn"

#: The artifact class this generator emits. Fixed — matches the WP1b
#: ``_GENERATION_ARTIFACT_ORDER`` first entry.
_ARTIFACT_CLASS: str = "dt_scaffolding"

#: The gating rows this generator inspects, in the exact order the spec
#: enumerates them (§4.1). Used verbatim in ``GeneratorSkipped.gating_rows``
#: so a skipped verdict names its closed gates in a stable order.
_GATING_ROW_NAMES: tuple[str, ...] = (
    "T1.gpio.i2s.*",
    "T5.dts.firmware",
    "T5.dts.compatible",
)


@register_generator(
    "dt_scaffolding",
    order=0,
    gating_rows=(
        ("T1", "gpio.i2s.*"),
        ("T5", "dts.firmware"),
        ("T5", "dts.compatible"),
    ),
)
def generate_dt(facts: TrustedFacts, kb: object | None = None) -> GenerationResult:
    """Emit a DT scaffolding artifact or a skipped verdict for one target.

    Pure, deterministic, zero I/O. Byte-identical ``facts.to_dict()`` produces
    byte-identical ``result.to_dict()`` (modulo ``bytes_hex``).

    Parameters
    ----------
    facts:
        Immutable projection of a target's Phase-2A verification rows
        (produced by ``orchestrator.generation.facts.project_facts``).
    kb:
        Optional knowledge-base handle (WP4+ uses this for rule lookup). WP3
        does not consult a KB — the ``rule_id`` field on gating rows is the
        entire policy signal. Accepted for future symmetry so all generators
        share the same ``(facts, kb)`` signature.

    Returns
    -------
    GenerationResult
        Either a ``GeneratedArtifact`` (bytes + contributes_rows) or a
        ``GeneratorSkipped`` naming its closed gates.

    The ``subject`` field on the returned dataclass is the fixed literal
    ``"dt_scaffolding"`` — matching ``artifact_class`` — because WP3 emits
    one artifact per target, not one per pin.
    """
    del kb  # WP3 does not consult a KB — see docstring.

    firmware_row = facts.rows_by_track_subject.get("T5.dts.firmware")

    # ── Gate 1: known-bad donor residue (§4.4) — runs first ─────────────────
    # A PARTIAL_MATCH row whose rule_id is in the known-bad set MUST route
    # to skipped BEFORE the "is gate open" check considers it open.
    if (
        firmware_row is not None
        and firmware_row.verdict == "PARTIAL_MATCH"
        and firmware_row.rule_id in KNOWN_BAD_PARTIAL_MATCH_RULES
    ):
        return GeneratorSkipped(
            subject=_ARTIFACT_CLASS,
            artifact_class=_ARTIFACT_CLASS,
            reason="gating_row_partial_match_donor_residue",
            gating_rows=["T5.dts.firmware"],
        )

    # ── Gate 2: T5.dts.firmware open (MATCH or non-known-bad PARTIAL_MATCH) ─
    if not facts.is_open("T5", "dts.firmware"):
        # Row missing entirely: authority not in snapshot.
        if firmware_row is None:
            return GeneratorSkipped(
                subject=_ARTIFACT_CLASS,
                artifact_class=_ARTIFACT_CLASS,
                reason="authority_not_in_snapshot",
                gating_rows=["T5.dts.firmware"],
            )
        # Row present but gate closed for a warning/verdict reason. Pick the
        # most-specific skip reason: warning=True → gating_row_warning;
        # verdict REVIEW_REQUIRED → gating_row_review_required; verdict
        # DISAGREE_WITH_AUTHORITY → gating_row_disagree; otherwise
        # gating_row_warning as a catch-all.
        return GeneratorSkipped(
            subject=_ARTIFACT_CLASS,
            artifact_class=_ARTIFACT_CLASS,
            reason=_skip_reason_for_closed_gate(firmware_row),
            gating_rows=["T5.dts.firmware"],
        )

    # ── Gate 3: T5.dts.compatible open ──────────────────────────────────────
    compatible_row = facts.rows_by_track_subject.get("T5.dts.compatible")
    if not facts.is_open("T5", "dts.compatible"):
        if compatible_row is None:
            return GeneratorSkipped(
                subject=_ARTIFACT_CLASS,
                artifact_class=_ARTIFACT_CLASS,
                reason="authority_not_in_snapshot",
                gating_rows=["T5.dts.compatible"],
            )
        return GeneratorSkipped(
            subject=_ARTIFACT_CLASS,
            artifact_class=_ARTIFACT_CLASS,
            reason=_skip_reason_for_closed_gate(compatible_row),
            gating_rows=["T5.dts.compatible"],
        )

    # ── Gates open — build the artifact ─────────────────────────────────────
    lines: list[str] = []

    # Header comment discipline (§4.4): non-known-bad PARTIAL_MATCH firmware
    # gate → machine-parseable comment naming the rule_id. Emitted so a
    # downstream grep for ``PARTIAL_MATCH gate`` surfaces every artifact that
    # opened on a KB-downgraded verdict.
    if firmware_row.verdict == "PARTIAL_MATCH":
        lines.append(
            f"// PARTIAL_MATCH gate: T5.dts.firmware (rule_id={firmware_row.rule_id})"
        )
        lines.append(
            "//   The row matched on family but a KB rule downgraded"
        )
        lines.append(
            "//   the verdict to PARTIAL_MATCH; the reviewer must"
        )
        lines.append(
            "//   confirm firmware before this artifact is merged."
        )

    # Fixed DTS preamble. No target-name interpolation — the subject
    # ``dt_scaffolding`` is the only variable, and it is fixed here.
    lines.append("/*")
    lines.append(" * Generated by Phase-2B WP3 dt_scaffolding.")
    lines.append(" * Deterministic. No timestamps.")
    lines.append(" */")
    lines.append("")

    # Pinmux state node under &tlmm: fixed frame ``i2s8_active`` with one
    # sub-node per pin in _REQUIRED_I2S_PINS order.
    lines.append("&tlmm {")
    lines.append("\ti2s8_active: i2s8-active-state {")

    # Emit pin sub-nodes in fixed order. Missing pins get a FIXME sub-node
    # placeholder AND a partial-artifact contributes_rows entry. Blank line
    # separator between sub-nodes for readability (matches the compiled DTB).
    contributes_rows: list[VerificationRow] = []
    for index, pin in enumerate(_REQUIRED_I2S_PINS):
        if index > 0:
            lines.append("")
        pin_row = facts.rows_by_track_subject.get(f"T1.gpio.i2s.{pin}")
        pin_open = (
            pin_row is not None
            and pin_row.verdict == "MATCH"
            and not pin_row.warning
        )
        if pin_open:
            lines.append(f"\t\t{pin}-pins {{")
            lines.append(f"\t\t\tpins = \"gpio{_PIN_GPIO[pin]}\";")
            lines.append(f"\t\t\tfunction = \"{_PIN_FUNCTION[pin]}\";")
            lines.append("\t\t\tdrive-strength = <8>;")
            lines.append("\t\t\tbias-disable;")
            lines.append("\t\t};")
        else:
            # Missing / warning / non-MATCH → FIXME sub-node + partial row.
            lines.append(f"\t\t{pin}-pins {{")
            lines.append(f"\t\t\t// FIXME({pin}): T1 gpio not in snapshot")
            lines.append("\t\t};")
            contributes_rows.append(
                VerificationRow(
                    track="T1",
                    subject=f"gpio.i2s.{pin}",
                    verdict="NOT_CROSS_CHECKABLE",
                    coverage_gap_reason="authority_out_of_scope",
                    notes=[
                        f"dt_scaffolding: pin {pin!r} not in snapshot — "
                        "FIXME marker emitted; reviewer must confirm."
                    ],
                )
            )

    lines.append("\t};")
    lines.append("};")
    lines.append("")

    # ADSP remoteproc node — Phase-2A verified T5.dts.firmware +
    # T5.dts.compatible are MATCH, so the values are downstream-committed
    # (lemans-family shared image; see module docstring for Nord-family
    # scoping rationale).
    lines.append("&remoteproc_adsp {")
    lines.append(f"\tcompatible = \"{_ADSP_COMPATIBLE}\";")
    lines.append(f"\tfirmware-name = \"{_ADSP_FIRMWARE}\";")
    lines.append("};")

    # Trailing newline — LF line endings, no BOM. Exactly one LF at EOF.
    bytes_ = ("\n".join(lines) + "\n").encode("utf-8")

    return GeneratedArtifact(
        subject=_ARTIFACT_CLASS,
        artifact_class=_ARTIFACT_CLASS,
        path_hint=f"{PATH_GUARD_ROOT}{_ARTIFACT_CLASS}/sound.dtsi",
        bytes_=bytes_,
        contributes_rows=contributes_rows,
    )


def _skip_reason_for_closed_gate(row: VerificationRow) -> str:
    """Map a closed row to its most-specific WP1b skip reason.

    Not exhaustive over ``SKIP_REASONS`` — WP3 only emits the four reasons
    below (donor-residue is handled inline above; ``authority_not_in_snapshot``
    is emitted when the row is *missing*, not closed). The specialised
    ``gating_row_disagree_on_bus`` / ``…_on_lpass_count`` /
    ``…_ambiguous_soundwire`` reasons belong to later WPs (WP4/WP5/WP6) whose
    subject vocabulary distinguishes them.
    """
    if row.verdict == "REVIEW_REQUIRED":
        return "gating_row_review_required"
    if row.verdict == "DISAGREE_WITH_AUTHORITY":
        return "gating_row_disagree"
    # warning=True with a verdict that isn't the two above (e.g. an explicit
    # warning override on MATCH/PARTIAL_MATCH) → gating_row_warning.
    return "gating_row_warning"


__all__ = ["generate_dt"]
