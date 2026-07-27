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

  NOT YET TARGET-AGNOSTIC (G-3A.13). Despite taking a ``TrustedFacts``
  argument and gating on target-derived cross-verify rows, this lane emits
  Nord identity from module-level constants (``_SNDCARD_COMPATIBLE`` /
  ``_MODEL_FIXME_LITERAL`` / ``_PINCTRL_LABEL`` at :143/144/147, plus
  ``_DAI_LINKS``), NOT from the target profile. On any non-Nord target it would
  emit Nord's ``qcom,nord-iq10-sndcard`` / ``i2s8_active`` — a silent
  wrong-output, not a crash. Multi-target correctness requires parameterizing
  these from the profile (a deferred generalization WP; see
  ``docs/PHASE3_KNOWN_GAPS.md`` G-3A.13). Until then treat this lane as
  Nord-parameterized, matching the honest scope admission already carried by
  ``dt_scaffolding.py:17`` and ``audioreach_topology.py``.

  * Sound card node — a NEW root child (``/ { sound { ... }; };``), not a label
    override. Two decisions baked in here (confirmed A/B for Nord IQ-10):

    - **A — board-specific compatible + NOT_ATTESTED board_variant (WP-69).**
      ``compatible = "qcom,nord-iq10-sndcard"`` with the ``model`` property
      emitted as the verbatim FIXME literal
      ``"FIXME(board_variant): NOT_ATTESTED"`` (see WP-69,
      ``docs/WP_69_BOARD_VARIANT_AUTHORITY.md``). No independent authority
      attests the board variant name; the prior ``"IQ10-EVK"`` value traced to
      candidate commit ``5267b2e1`` and fails the provenance guard. The gap is
      disclosed via a ``sound_card.model.board_variant`` NOT_CROSS_CHECKABLE
      row in ``contributes_rows``. We do NOT reuse ``qcom,qcs9100-sndcard``
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
from orchestrator.generation.source_probe import ClaimStatus, SourceProbe
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

#: Board-specific sound-card compatible + model FIXME literal (decision A,
#: WP-69). ``_SNDCARD_COMPATIBLE`` is the board-specific compatible string —
#: NOT the qcs9100 reference-board string; see module docstring.
#: ``_MODEL_FIXME_LITERAL`` is the verbatim string emitted for the
#: ``model =`` property: no authority attests the board variant name, so the
#: generator emits a machine-parseable FIXME and discloses the gap via a
#: ``sound_card.model.board_variant`` NOT_CROSS_CHECKABLE row.
_SNDCARD_COMPATIBLE: str = "qcom,nord-iq10-sndcard"
_MODEL_FIXME_LITERAL: str = "FIXME(board_variant): NOT_ATTESTED"

#: T5 partial-artifact subject for the board_variant NOT_ATTESTED disclosure
#: (WP-69). Emitted verbatim into ``contributes_rows`` alongside the two
#: decision-B port-ID rows and the decision-A driver-match row.
_BOARD_VARIANT_CONTRIB_SUBJECT: str = "sound_card.model.board_variant"

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


# ── Template-value accessor (Phase A) ────────────────────────────────────────
#
# Navigates the raw H-1 template dict and extracts an attested value.
# Returns the value ONLY when the leaf's ncc_state is "ATTESTED" and value
# is non-None. All other states (NOT_ATTESTED, NOT_CROSS_CHECKABLE,
# candidate_derived) return None — causing the caller to fall through to the
# existing hardcoded constant. This guarantees byte-identity on targets whose
# template is thin (e.g. Nord).


def _template_value(template: dict | None, *key_path: str) -> object | None:
    """Extract an attested leaf value from the H-1 template dict.

    key_path navigates nested dicts. The final dict is expected to have
    ``ncc_state`` and ``value`` (FactRecord shape). Returns ``value`` only
    when ``ncc_state == "ATTESTED"`` and ``value is not None``.
    """
    if template is None:
        return None
    node: object = template
    for key in key_path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
        if node is None:
            return None
    if not isinstance(node, dict):
        return None
    if node.get("ncc_state") != "ATTESTED":
        return None
    val = node.get("value")
    return val if val is not None else None


# ── Disclosure-note builders (source-grounded, byte-invariant) ──────────────
#
# These build the TEXT of the contributes_rows notes only. They never touch the
# emitted DTSI bytes and never feed a gate. Each degrades honestly: when the
# probe could not read a file the note says UNVERIFIED and cites the missing
# path, never a fabricated FOUND / ABSENT.


def _port_id_notes(
    probe: SourceProbe,
    *,
    node: str,
    port_macro: str,
    port_value: int,
    octonary_macro: str,
    patch_line: int,
) -> list[str]:
    """Notes for one ``dai_link.port_id.*`` row, grounded on the ports header.

    Reports BOTH ordinal ceilings (Option-(iii) ruling): the global name
    ceiling (MI2S-inclusive) and the bind-relevant TDM-family ceiling, plus the
    OCTONARY-TDM-defined observation and the missing TDM rungs — each with the
    observed ``file:line`` when the header was read, or UNVERIFIED otherwise.
    """
    head = (
        f"machine_driver: {node} emits {port_macro} ({port_value}) as a "
        f"PLACEHOLDER for I2S8 (mirrors linux-nord/0004-*.patch:{patch_line}). "
        "Reviewer must confirm the I2S8->AudioReach port mapping and add the "
        "correct binding before bring-up."
    )
    if probe.ports_status is ClaimStatus.FILE_NOT_FOUND:
        return [
            head,
            "UNVERIFIED: could not read "
            f"{probe.ports_file} (no kernel-source tree supplied or file "
            f"missing); the {octonary_macro} gap is asserted from the patch, "
            "not observed from the header.",
        ]

    octo_status, octo_val, octo_line = probe.port_macro(octonary_macro)
    if octo_status is ClaimStatus.ABSENT:
        octo_txt = (
            f"OBSERVED ABSENT: {octonary_macro} is not defined in "
            f"{probe.ports_file}."
        )
    elif octo_status is ClaimStatus.FOUND:
        octo_txt = (
            f"OBSERVED FOUND: {octonary_macro} = {octo_val} at "
            f"{probe.ports_file}:{octo_line} (upstream has caught up — reviewer "
            "should switch the placeholder to the real macro)."
        )
    else:  # FILE_NOT_FOUND already handled; defensive.
        octo_txt = f"UNVERIFIED: {octonary_macro} status unknown."

    gnc = (
        f"{probe.global_name_ceiling} "
        f"({probe.ports_file}:{probe.global_name_ceiling_line})"
        if probe.global_name_ceiling
        else "none observed"
    )
    tfc = (
        f"{probe.tdm_family_ceiling} "
        f"({probe.ports_file}:{probe.tdm_family_ceiling_line})"
        if probe.tdm_family_ceiling
        else "none observed"
    )
    missing = ", ".join(probe.missing_rungs) if probe.missing_rungs else "none"
    return [
        head,
        octo_txt,
        f"OBSERVED global_name_ceiling = {gnc} (MI2S-inclusive).",
        f"OBSERVED tdm_family_ceiling = {tfc} (bind-relevant for *_TDM_RX_0/TX_0).",
        f"OBSERVED octonary_tdm_defined = {probe.octonary_tdm_defined.value}; "
        f"missing_rungs = [{missing}].",
    ]


def _driver_match_notes(probe: SourceProbe, compatible: str) -> list[str]:
    """Notes for the ``sound_card.driver_match.nord_iq10`` row.

    Grounds the "compatible is not in the match table" assertion on an actual
    read of ``sound/soc/qcom/sc8280xp.c``: OBSERVED ABSENT / FOUND when the
    file was read, UNVERIFIED when it was not. ``compatible`` is the board
    sound-card string; the probe itself is board-blind, so membership is a
    query here rather than baked into the probe.
    """
    tail = (
        "the card will not probe until a driver-side match-table extension is "
        "added. Reviewer must add the compatible or bind to an existing family "
        "match."
    )
    status, match_line = probe.driver_match(compatible)
    if status is ClaimStatus.FILE_NOT_FOUND:
        return [
            f"machine_driver: UNVERIFIED — could not read {probe.driver_match_file} "
            f"(no kernel-source tree supplied or file missing). Whether "
            f"{compatible!r} is in {probe.match_table_symbol}[] is "
            "asserted, not observed; " + tail,
        ]
    table_anchor = (
        f"{probe.match_table_symbol}[], {probe.driver_match_file}:"
        f"{match_line}"
        if match_line is not None
        else f"{probe.match_table_symbol}[] (symbol line not located)"
    )
    if status is ClaimStatus.ABSENT:
        return [
            f"machine_driver: OBSERVED ABSENT — compatible "
            f"{compatible!r} is not in the sc8280xp.c match table "
            f"({table_anchor}); " + tail,
        ]
    # FOUND — upstream already lists it; disclose that the assumption flipped.
    return [
        f"machine_driver: OBSERVED FOUND — compatible "
        f"{compatible!r} IS present in the sc8280xp.c match table "
        f"({table_anchor}); the card should probe against the existing driver. "
        "Reviewer should confirm no board-specific match extension is still "
        "required.",
    ]


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
def generate_machine_driver(
    facts: TrustedFacts,
    kb: object | None = None,
    *,
    source: SourceProbe | None = None,
    template: dict | None = None,
) -> GenerationResult:
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
    source:
        Optional, disclosure-only :class:`SourceProbe` grounding the
        driver-match and port-id notes against the real kernel tree. It is
        keyword-only and defaults to ``None`` so every existing
        ``generate_machine_driver(facts)`` caller is unaffected. The probe
        NEVER reaches ``facts`` / ``cross_verification`` / any gate, and NEVER
        changes the emitted DTSI bytes — it only hardens the provenance of the
        ``contributes_rows`` notes (FOUND/ABSENT observation vs a hardcoded
        assertion; UNVERIFIED when the tree/file is absent).

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

    # Disclosure-only source grounding. When no probe is supplied (the default
    # for every legacy `generate_machine_driver(facts)` caller and every test
    # that does not pass one) synthesise an all-FILE_NOT_FOUND probe so the
    # note-builders below render UNVERIFIED rather than a fabricated
    # observation. The probe influences NOTE TEXT ONLY — never a gate, never
    # the emitted bytes.
    probe = source if source is not None else SourceProbe.from_tree(None)

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

    # Phase A: resolve effective constants from template (attested values) or
    # fall back to module-level hardcoded constants (byte-identity on Nord).
    eff_model = (
        _template_value(template, "board_metadata", "board_variant")
        or _MODEL_FIXME_LITERAL
    )
    eff_pinctrl = (
        _template_value(template, "board_metadata", "pinctrl_state")
        or _PINCTRL_LABEL
    )
    eff_compatible = _SNDCARD_COMPATIBLE  # no template path today
    eff_cpu_dai = _CPU_DAI_LABEL  # kernel-derived, not in template
    eff_platform_dai = _PLATFORM_DAI_LABEL  # kernel-derived, not in template

    # Fixed DTSI preamble.
    lines.append("/*")
    lines.append(" * Generated by Phase-2B WP5 machine_driver.")
    lines.append(" * Deterministic. No timestamps.")
    lines.append(" *")
    lines.append(" * Nord IQ-10 AudioReach sound card. Wires LPASS I2S8 (pinctrl")
    lines.append(f" * <&{eff_pinctrl}>, WP3) to the two board codecs (&pcm1681")
    lines.append(" * playback, &adau1979 capture, WP4) through the SoC-side")
    lines.append(f" * {eff_cpu_dai} / {eff_platform_dai} DAIs.")
    lines.append(" */")
    lines.append("")
    lines.append("/ {")
    lines.append("\tsound {")
    lines.append(f"\t\tcompatible = \"{eff_compatible}\";")
    lines.append(f"\t\tmodel = \"{eff_model}\";")
    lines.append("")
    lines.append(f"\t\tpinctrl-0 = <&{eff_pinctrl}>;")
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
        lines.append(f"\t\t\t\tsound-dai = <&{eff_cpu_dai} {port_macro}>;")
        lines.append("\t\t\t};")
        lines.append("")
        lines.append("\t\t\tplatform {")
        lines.append(f"\t\t\t\tsound-dai = <&{eff_platform_dai}>;")
        lines.append("\t\t\t};")
        lines.append("\t\t};")

        contributes_rows.append(
            VerificationRow(
                track="T5",
                subject=contributes_subject,
                verdict="NOT_CROSS_CHECKABLE",
                coverage_gap_reason="authority_out_of_scope",
                notes=_port_id_notes(
                    probe,
                    node=node,
                    port_macro=port_macro,
                    port_value=port_value,
                    octonary_macro=octonary_macro,
                    patch_line=patch_line,
                ),
            )
        )

    lines.append("\t};")
    lines.append("};")

    # Board-variant NOT_ATTESTED partial-artifact row (WP-69, decision A). The
    # emitted `model =` property is the verbatim FIXME literal because no
    # independent authority attests the board variant name; the prior
    # "IQ10-EVK" value traced to candidate commit `5267b2e1` and fails the
    # provenance guard. Mirrors the sound_card.driver_match row shape.
    contributes_rows.append(
        VerificationRow(
            track="T5",
            subject=_BOARD_VARIANT_CONTRIB_SUBJECT,
            verdict="NOT_CROSS_CHECKABLE",
            coverage_gap_reason="authority_out_of_scope",
            notes=[
                "machine_driver: sound-card `model` field emitted as verbatim "
                f"FIXME literal {_MODEL_FIXME_LITERAL!r} because no independent "
                "authority attests the board variant name.",
                "SCOPE: board-variant name (the string that populates `model =`).",
                "NOT_ATTESTED: board_variant. reviewer_required=true.",
                "Candidates present in evidence: (a) IQ10-EVK — appears only in "
                "candidate DTS at commit 5267b2e1d7a5 and downstream records; "
                "fails provenance guard. (b) IQ10-RRD — attested by schematic "
                "PDFs LD20-94440/94441 and IQ10_RRD_IO_Mapping.xlsx in "
                "audio_bu_skill/targets/nord-iq10/evidence/offline/, but no "
                "ingestion pipeline exists to promote schematic evidence into "
                "an authority row.",
                "Reviewer must edit `model =` before bring-up. Follow-up "
                "authority track queued behind WP_H-1_AUDIO_HARDWARE_TEMPLATE_"
                "PROJECTOR (task #70) and a later board-metadata authority WP.",
            ],
        )
    )

    # Driver-match partial-artifact row (decision A): the board-specific
    # compatible has no upstream driver match yet. The "not in the match table"
    # claim is now grounded on a live read of sc8280xp.c (OBSERVED ABSENT/FOUND)
    # or degraded to UNVERIFIED when no kernel tree was supplied — see
    # _driver_match_notes. The row's subject/verdict/reason are unchanged.
    contributes_rows.append(
        VerificationRow(
            track="T5",
            subject="sound_card.driver_match.nord_iq10",
            verdict="NOT_CROSS_CHECKABLE",
            coverage_gap_reason="authority_out_of_scope",
            notes=_driver_match_notes(probe, eff_compatible),
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
