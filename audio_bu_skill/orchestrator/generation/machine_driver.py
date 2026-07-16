"""Phase-2B WP5 — machine driver generator (third generator lane).

Pure, stdlib-only machine-driver generator. Consumes a WP2-projected
``TrustedFacts`` and emits either a ``GeneratedArtifact`` carrying a DTSI
fragment (the Nord IQ-10 AudioReach sound-card node with its two I2S8
DAI-links) or a ``GeneratorSkipped`` when the gates are closed.

The machine driver is the *third* artifact class in
``_GENERATION_ARTIFACT_ORDER`` (after ``dt_scaffolding`` and ``codec_stub``).
It ties the earlier two lanes together: the WP3 pinctrl state node
(``&i2s8_active``) and the WP4 codec stubs (``&pcm1681`` / ``&adau1979``) are
wired through the SoC-side AudioReach DAIs (``q6apmbedai`` CPU DAI, ``q6apm``
platform DAI) into a single ``sound { }`` card with a playback and a capture
DAI-link.

Nord-family scoping (WP5):

  * Sound card node — a NEW root child (``/ { sound { ... }; };``), not a label
    override. Two decisions baked in here (confirmed A/B for Nord IQ-10):

    - **A — board-specific compatible.** ``compatible = "qcom,nord-iq10-sndcard"``
      with ``model = "IQ10-EVK"``. We do NOT reuse ``qcom,qcs9100-sndcard``
      (which the first-pass patch used): reusing the qcs9100 string would
      falsely imply Nord IQ-10 is bit-compatible with the qcs9100 reference
      board. ``qcom,nord-iq10-sndcard`` is NOT in the upstream sc8280xp.c
      match table (``snd_sc8280xp_dt_match[]``, sound/soc/qcom/sc8280xp.c:166),
      so a driver-side match-table extension is required before the card will
      probe — surfaced as the ``sound_card.driver_match.nord_iq10``
      partial-artifact row in ``contributes_rows``.

    - **B — port-ID placeholder + FIXME.** The AudioReach *logical* port that
      the ADSP routes I2S8 to is not confirmed: ``qcom,q6dsp-lpass-ports.h``
      enumerates only PRIMARY..QUINARY (there is no ``OCTONARY_TDM_*`` /
      literal ``I2S8`` macro). We emit ``QUATERNARY_TDM_{RX,TX}_0`` as an
      explicit PLACEHOLDER with a machine-parseable ``FIXME(i2s8_port_id)``
      comment on each DAI-link (invariant #3: never emit a fabricated port ID
      silently), plus one ``dai_link.port_id.i2s8_{playback,capture}``
      partial-artifact row per link in ``contributes_rows``.

  * DAI-links (fixed emit order — playback then capture, deterministic):

    - Playback: ``link-name = "I2S8 Playback"``, codec ``&pcm1681`` (TI DAC),
      cpu ``&q6apmbedai QUATERNARY_TDM_RX_0`` (placeholder), platform ``&q6apm``.
    - Capture: ``link-name = "I2S8 Capture"``, codec ``&adau1979`` (ADI ADC),
      cpu ``&q6apmbedai QUATERNARY_TDM_TX_0`` (placeholder), platform ``&q6apm``.

    The codec phandles ``&pcm1681`` / ``&adau1979`` are the WP4 codec-stub
    devices; their DT existence is carried by WP4 + the T4b advisory rows.
    Gate 3 below (T4b DISAGREE hard-skip) guarantees we never emit a card that
    references a codec whose binding the authority disputes.

Gating (per PHASE2B_SPECIFICATION.md §4.1 + GATING_ROWS["machine_driver"] =
(("T1","gpio.i2s.*"), ("T4a","qup.*"), ("T4b","*"), ("T2","*"))):

  1. **T1 pinctrl gate — at least one ``T1.gpio.i2s.*`` open.** The card's
     ``pinctrl-0 = <&i2s8_active>`` reference is only meaningful if the I2S8
     pinmux is confirmed. WP5 gates file-wise (the pinctrl STATE node lives in
     WP3 and is referenced by label here), so ANY open ``T1.gpio.i2s.*`` row
     satisfies the gate. No open pin → skip.

  2. **T4a QUP endpoint gate — at least one ``T4a.qup.*`` open** (strict, no
     advisory carve-out; T4a is not in ``ADVISORY_ROWS``). The codec control
     bus must be authoritatively confirmed. Same shape as WP4 Gate 1.

  3. **T4b codec gate.** (a) Any ``T4b.codec.*`` DISAGREE_WITH_AUTHORITY →
     hard skip (``codec_binding_disagreement``): a card that boots but binds
     the wrong device on the disagreeing side is worse than no card. (b) At
     least one advisory-open (§3.7 NCC + authority_out_of_scope) codec row must
     exist, else ``authority_not_in_snapshot``.

  4. **T2 SoundWire gate — DISAGREE hard-skip.** ``track_t2`` emits exactly one
     subject, ``soundwire_master``. A DISAGREE_WITH_AUTHORITY on the SoundWire
     bus topology contradicts the I2S-only assumption this I2S8 card is built
     on — emitting an I2S card against a disputed bus topology is an invariant
     #3 violation. Skip with ``gating_row_disagree_on_bus``. An NCC on
     ``soundwire_master`` (SoundWire simply not applicable to this I2S-only
     board) does NOT close the gate.

Zero I/O, zero timestamps, zero env reads. Byte-identical input → byte-
identical output (LF endings, exactly one trailing LF).

Import discipline (WP5 — mirrors WP3/WP4):

  * MAY import: ``orchestrator.generation.model`` (WP1a — dataclasses),
    ``orchestrator.generation.config`` (WP1b — ``PATH_GUARD_ROOT``),
    ``orchestrator.reasoning.crossverify_model`` (``VerificationRow`` — needed
    to append partial-artifact rows to ``contributes_rows``).
  * MUST NOT import: ``orchestrator.generation.facts`` (WP5 receives
    ``TrustedFacts`` as input, like WP3/WP4);
    ``orchestrator.reasoning.crossverify`` /
    ``orchestrator.reasoning.cardinality`` (Phase-2A internals);
    ``orchestrator.generation.dt_scaffolding`` /
    ``orchestrator.generation.codec_stub`` (peer generators — no
    generator↔generator coupling).
  * Enforced by ``tests/test_generation_machine.py::test_import_guard``.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_machine``
"""

from __future__ import annotations

from orchestrator.generation.config import PATH_GUARD_ROOT
from orchestrator.generation.model import (
    GeneratedArtifact,
    GeneratorSkipped,
    GenerationResult,
    TrustedFacts,
)
from orchestrator.generation.registry import register_generator
from orchestrator.reasoning.crossverify_model import VerificationRow

# ── Nord IQ-10 constants (WP5, Nord-family scoped) ──────────────────────────

#: The artifact class this generator emits. Fixed — matches the WP1b
#: ``_GENERATION_ARTIFACT_ORDER`` third entry.
_ARTIFACT_CLASS: str = "machine_driver"

#: Track-prefixes this generator inspects, in the order the WP1b
#: ``GATING_ROWS["machine_driver"]`` tuple enumerates them. Used verbatim in
#: ``GeneratorSkipped.gating_rows`` so a skipped verdict names its closed gates
#: in a stable order.
_GATING_ROW_NAMES: tuple[str, ...] = (
    "T1.gpio.i2s.*",
    "T4a.qup.*",
    "T4b.codec.*",
    "T2.soundwire_master",
)

#: Board-specific sound-card compatible + model (decision A). NOT the
#: qcs9100 reference-board string — see module docstring.
_SNDCARD_COMPATIBLE: str = "qcom,nord-iq10-sndcard"
_SNDCARD_MODEL: str = "IQ10-EVK"

#: The WP3 pinctrl state-node label this card references.
_PINCTRL_LABEL: str = "i2s8_active"

#: The SoC-side AudioReach DAIs. ``q6apmbedai`` is the CPU (back-end) DAI whose
#: single ``#sound-dai-cells = <1>`` cell is the LPASS port ID; ``q6apm`` is
#: the platform DAI.
_CPU_DAI_LABEL: str = "q6apmbedai"
_PLATFORM_DAI_LABEL: str = "q6apm"

#: The two DAI-links in fixed emit order. Each entry:
#:
#:   * ``node`` — the DT sub-node name under ``sound { }``.
#:   * ``link_name`` — the ``link-name`` property value.
#:   * ``codec_label`` — the WP4 codec-stub device phandle (no leading ``&``).
#:   * ``port_macro`` — the QUATERNARY placeholder macro actually emitted.
#:   * ``port_value`` — the numeric value of that placeholder macro.
#:   * ``octonary_macro`` — the (non-existent-upstream) macro the FIXME says
#:     the correct binding needs.
#:   * ``patch_line`` — the line in linux-nord/0004-*.patch the placeholder
#:     mirrors (so the FIXME cites a real anchor, not a fabricated one).
#:   * ``contributes_subject`` — the ``dai_link.port_id.*`` subject for the
#:     partial-artifact row (decision B).
_DAI_LINKS: tuple[dict[str, object], ...] = (
    {
        "node": "playback-dai-link",
        "link_name": "I2S8 Playback",
        "codec_label": "pcm1681",
        "port_macro": "QUATERNARY_TDM_RX_0",
        "port_value": 72,
        "octonary_macro": "OCTONARY_TDM_RX_0",
        "patch_line": 77,
        "contributes_subject": "dai_link.port_id.i2s8_playback",
    },
    {
        "node": "capture-dai-link",
        "link_name": "I2S8 Capture",
        "codec_label": "adau1979",
        "port_macro": "QUATERNARY_TDM_TX_0",
        "port_value": 73,
        "octonary_macro": "OCTONARY_TDM_TX_0",
        "patch_line": 93,
        "contributes_subject": "dai_link.port_id.i2s8_capture",
    },
)


@register_generator(
    "machine_driver",
    order=2,
    gating_rows=(
        ("T1", "gpio.i2s.*"),
        ("T4a", "qup.*"),
        ("T4b", "*"),
        ("T2", "*"),
    ),
)
def generate_machine_driver(facts: TrustedFacts, kb: object | None = None) -> GenerationResult:
    """Emit a machine-driver artifact or a skipped verdict for one target.

    Pure, deterministic, zero I/O. Byte-identical ``facts.to_dict()`` produces
    byte-identical ``result.to_dict()`` (modulo ``bytes_hex``).

    Parameters
    ----------
    facts:
        Immutable projection of a target's Phase-2A verification rows.
    kb:
        Optional knowledge-base handle (reserved for symmetry with the other
        generators). WP5 does not consult a KB — the gating-row verdicts are
        the entire policy signal.

    Returns
    -------
    GenerationResult
        Either a ``GeneratedArtifact`` (bytes + contributes_rows) or a
        ``GeneratorSkipped`` naming its closed gates.

    The ``subject`` field on the returned dataclass is the fixed literal
    ``"machine_driver"`` — matching ``artifact_class`` — because WP5 emits one
    card per target.
    """
    del kb  # WP5 does not consult a KB — see docstring.

    # ── Gate 1: T1 pinctrl — at least one T1.gpio.i2s.* open ────────────────
    pin_rows = _rows_with_prefix(facts, "T1.gpio.i2s.")
    open_pin_rows = [row for row in pin_rows if facts.is_open(row.track, row.subject)]
    if not open_pin_rows:
        return GeneratorSkipped(
            subject=_ARTIFACT_CLASS,
            artifact_class=_ARTIFACT_CLASS,
            reason=_skip_reason_for_no_open(pin_rows),
            gating_rows=["T1.gpio.i2s.*"],
        )

    # ── Gate 2: T4a QUP endpoint — at least one T4a.qup.* open ──────────────
    qup_rows = _rows_with_prefix(facts, "T4a.qup.")
    open_qup_rows = [row for row in qup_rows if facts.is_open(row.track, row.subject)]
    if not open_qup_rows:
        return GeneratorSkipped(
            subject=_ARTIFACT_CLASS,
            artifact_class=_ARTIFACT_CLASS,
            reason=_skip_reason_for_no_open(qup_rows),
            gating_rows=["T4a.qup.*"],
        )

    # ── Gate 3a: T4b codec disagreement — hard skip ─────────────────────────
    codec_rows = _rows_with_prefix(facts, "T4b.codec.")
    disagreeing_codecs = [row for row in codec_rows if row.verdict == "DISAGREE_WITH_AUTHORITY"]
    if disagreeing_codecs:
        offending = sorted(f"T4b.{row.subject}" for row in disagreeing_codecs)
        return GeneratorSkipped(
            subject=_ARTIFACT_CLASS,
            artifact_class=_ARTIFACT_CLASS,
            reason="codec_binding_disagreement",
            gating_rows=offending,
        )

    # ── Gate 3b: at least one advisory-open codec row must exist ────────────
    advisory_codecs = [row for row in codec_rows if _t4b_advisory_open(row)]
    if not advisory_codecs:
        return GeneratorSkipped(
            subject=_ARTIFACT_CLASS,
            artifact_class=_ARTIFACT_CLASS,
            reason="authority_not_in_snapshot",
            gating_rows=["T4b.codec.*"],
        )

    # ── Gate 4: T2 SoundWire topology — DISAGREE hard-skip ──────────────────
    t2_rows = _rows_with_prefix(facts, "T2.")
    disagreeing_t2 = [row for row in t2_rows if row.verdict == "DISAGREE_WITH_AUTHORITY"]
    if disagreeing_t2:
        offending = sorted(f"T2.{row.subject}" for row in disagreeing_t2)
        return GeneratorSkipped(
            subject=_ARTIFACT_CLASS,
            artifact_class=_ARTIFACT_CLASS,
            reason="gating_row_disagree_on_bus",
            gating_rows=offending,
        )

    # ── Gates open — build the artifact ─────────────────────────────────────
    lines: list[str] = []
    contributes_rows: list[VerificationRow] = []

    # Fixed DTSI preamble.
    lines.append("/*")
    lines.append(" * Generated by Phase-2B WP5 machine_driver.")
    lines.append(" * Deterministic. No timestamps.")
    lines.append(" *")
    lines.append(" * Nord IQ-10 AudioReach sound card. Wires LPASS I2S8 (pinctrl")
    lines.append(f" * <&{_PINCTRL_LABEL}>, WP3) to the two board codecs (&pcm1681")
    lines.append(" * playback, &adau1979 capture, WP4) through the SoC-side")
    lines.append(f" * {_CPU_DAI_LABEL} / {_PLATFORM_DAI_LABEL} DAIs.")
    lines.append(" */")
    lines.append("")
    lines.append("/ {")
    lines.append("\tsound {")
    lines.append(f"\t\tcompatible = \"{_SNDCARD_COMPATIBLE}\";")
    lines.append(f"\t\tmodel = \"{_SNDCARD_MODEL}\";")
    lines.append("")
    lines.append(f"\t\tpinctrl-0 = <&{_PINCTRL_LABEL}>;")
    lines.append("\t\tpinctrl-names = \"default\";")

    # One DAI-link per _DAI_LINKS entry, in fixed order (playback, capture).
    # Each link carries a FIXME(i2s8_port_id) block (decision B: never emit a
    # placeholder port ID silently) and contributes one partial-artifact row.
    for link in _DAI_LINKS:
        node = str(link["node"])
        link_name = str(link["link_name"])
        codec_label = str(link["codec_label"])
        port_macro = str(link["port_macro"])
        port_value = int(link["port_value"])
        octonary_macro = str(link["octonary_macro"])
        patch_line = int(link["patch_line"])
        contributes_subject = str(link["contributes_subject"])

        lines.append("")
        # Verbatim decision-B FIXME block, indented to the DAI-link's 2-tab
        # level. Cites the real q6dsp-lpass-ports.h gap and the patch anchor.
        lines.append(f"\t\t/* FIXME(i2s8_port_id): {octonary_macro} macro not in")
        lines.append("\t\t * include/dt-bindings/sound/qcom,q6dsp-lpass-ports.h yet.")
        lines.append(f"\t\t * Using {port_macro} ({port_value}) as placeholder to match")
        lines.append(f"\t\t * linux-nord/0004-*.patch:{patch_line}. Correct binding requires an")
        lines.append("\t\t * upstream q6dsp-lpass-ports.h extension for I2S8.")
        lines.append("\t\t */")
        lines.append(f"\t\t{node} {{")
        lines.append(f"\t\t\tlink-name = \"{link_name}\";")
        lines.append("")
        lines.append("\t\t\tcodec {")
        lines.append(f"\t\t\t\tsound-dai = <&{codec_label}>;")
        lines.append("\t\t\t};")
        lines.append("")
        lines.append("\t\t\tcpu {")
        lines.append(f"\t\t\t\tsound-dai = <&{_CPU_DAI_LABEL} {port_macro}>;")
        lines.append("\t\t\t};")
        lines.append("")
        lines.append("\t\t\tplatform {")
        lines.append(f"\t\t\t\tsound-dai = <&{_PLATFORM_DAI_LABEL}>;")
        lines.append("\t\t\t};")
        lines.append("\t\t};")

        contributes_rows.append(
            VerificationRow(
                track="T5",
                subject=contributes_subject,
                verdict="NOT_CROSS_CHECKABLE",
                coverage_gap_reason="authority_out_of_scope",
                notes=[
                    f"machine_driver: {node} emits {port_macro} ({port_value}) as a "
                    f"PLACEHOLDER for I2S8; {octonary_macro} is not in "
                    "include/dt-bindings/sound/qcom,q6dsp-lpass-ports.h upstream "
                    f"(mirrors linux-nord/0004-*.patch:{patch_line}). Reviewer must "
                    "confirm the I2S8->AudioReach port mapping and add the macro "
                    "before bring-up."
                ],
            )
        )

    lines.append("\t};")
    lines.append("};")

    # Driver-match partial-artifact row (decision A): the board-specific
    # compatible has no upstream driver match yet.
    contributes_rows.append(
        VerificationRow(
            track="T5",
            subject="sound_card.driver_match.nord_iq10",
            verdict="NOT_CROSS_CHECKABLE",
            coverage_gap_reason="authority_out_of_scope",
            notes=[
                f"machine_driver: compatible {_SNDCARD_COMPATIBLE!r} is not in the "
                "sc8280xp.c match table (snd_sc8280xp_dt_match[], "
                "sound/soc/qcom/sc8280xp.c:166) upstream; the card will not probe "
                "until a driver-side match-table extension is added. Reviewer must "
                "add the compatible or bind to an existing family match."
            ],
        )
    )

    # Trailing newline — LF line endings, no BOM. Exactly one LF at EOF.
    bytes_ = ("\n".join(lines) + "\n").encode("utf-8")

    return GeneratedArtifact(
        subject=_ARTIFACT_CLASS,
        artifact_class=_ARTIFACT_CLASS,
        path_hint=f"{PATH_GUARD_ROOT}{_ARTIFACT_CLASS}/nord_sound.dtsi",
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

    Mirrors ``codec_stub._t4b_advisory_open`` (duplicated deliberately — WP5
    must not import the peer generator; the predicate is small and stable).
    Advisory-open covers NCC + authority_out_of_scope (the canonical §3.7
    case), REVIEW_REQUIRED, and MATCH / PARTIAL_MATCH (forward-compat hook).
    ``warning=True`` does not close the advisory gate.
    """
    if row.verdict == "NOT_CROSS_CHECKABLE":
        return row.coverage_gap_reason == "authority_out_of_scope"
    return row.verdict in ("REVIEW_REQUIRED", "MATCH", "PARTIAL_MATCH")


def _skip_reason_for_no_open(rows: list[VerificationRow]) -> str:
    """Pick the most-specific skip reason when no row in ``rows`` is open.

    * No rows at all → ``authority_not_in_snapshot``.
    * Any DISAGREE_WITH_AUTHORITY → ``gating_row_disagree``.
    * Any REVIEW_REQUIRED → ``gating_row_review_required``.
    * Otherwise ``gating_row_warning`` (catch-all: warning/NCC tail).
    """
    if not rows:
        return "authority_not_in_snapshot"
    if any(row.verdict == "DISAGREE_WITH_AUTHORITY" for row in rows):
        return "gating_row_disagree"
    if any(row.verdict == "REVIEW_REQUIRED" for row in rows):
        return "gating_row_review_required"
    return "gating_row_warning"


__all__ = ["generate_machine_driver"]
