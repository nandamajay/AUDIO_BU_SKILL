"""Phase-2B WP6 — AudioReach topology generator (fourth / final generator lane).

Pure, stdlib-only generator. Consumes a WP2-projected ``TrustedFacts`` and
emits either a ``GeneratedArtifact`` carrying a DTSI fragment (the Nord IQ-10
AudioReach GPR service tree) or a ``GeneratorSkipped`` when the T3 element-count
gates are closed.

AudioReach topology is the *fourth* and final artifact class in
``_GENERATION_ARTIFACT_ORDER`` (after ``dt_scaffolding``, ``codec_stub``,
``machine_driver``). It is where the Track-T3 (Audio Resource Validation /
WP-C cardinality) verdicts gate generation: an LPASS-macro instance-count
divergence — the Eliza production case (catalog=4 vs proposal=2, the
"Rajesh-email" evidence) — CLOSES this gate and no GPR tree is emitted.

Nord-family scoping (WP6) — what this lane does *and does not* emit:

  * **DT-embedded, not XML.** On Nord (as upstream for the qcom AudioReach
    stack) the GPR service tree lives in the device tree; there is no separate
    topology XML. This generator emits a ``.dtsi`` fragment.

  * **Fresh inline node under ``&soc`` — NOT a glink-edge overlay.** An earlier
    draft overrode ``&remoteproc_adsp_glink``; that label does not exist in the
    Nord include chain (it is declared only in ``kodiak.dtsi`` /
    ``glymur.dtsi``, neither of which Nord pulls in), so the overlay would fail
    at DT compile time. On Nord the ADSP remoteproc does not pre-exist at all —
    linux-nord/0003-*.patch *introduces* the whole
    ``remoteproc_adsp: remoteproc@30000000`` node (a fresh child of ``soc``,
    the one label that does resolve — ``nord.dtsi:922``). This generator
    therefore emits a ``&soc { remoteproc_adsp: remoteproc@30000000 { … } };``
    fragment carrying:

      - the ADSP PAS body (``qcom,sa8775p-adsp-pas``, ``reg`` base
        ``0x30000000``, interrupts, XO clock, RPMHPD_LCX/LMX proxy PDs,
        ``hpass_dsp0_mem``, ``aoss_qmp``, smem-states, ``status = "disabled"``)
        — reproduced verbatim from the patch, including its FIXME block (the
        ``reg`` base / SCMI-vs-rpmhpd power-model / interconnect / SMMU-SID
        caveats are known-open items, surfaced not hidden);
      - a ``glink-edge`` child (``label = "lpass"``, ``qcom,remote-pid = <2>``)
        that carries ``fastrpc`` (with its three ``compute-cb@{3,4,5}``
        callback edges) and ``gpr`` (``qcom,gpr``) with ``q6apm``
        (``qcom,q6apm``: ``q6apmbedai`` back-end LPASS DAIs + ``q6apmdai``
        front-end DAIs) and ``q6prm`` (``qcom,q6prm``: ``q6prmcc`` LPASS clock
        controller).

    There is **no ``/delete-node/ apr;``** (APR was never present on Nord — the
    node is authored GPR-native) and **no ``#sound-dai-cells`` on
    ``q6apmdai``** (patch 0003 omits it; the earlier draft's "union" is dropped
    in favour of ground truth).

  * **The topology blob itself is out of DT scope.** The AudioReach APM
    *module graph* — module instance IDs, port wiring, the connection matrix —
    is NOT declared in device tree. It is loaded at runtime by the q6apm
    firmware from an ACDB (Audio Calibration Database) blob and shipped as a
    separate firmware deliverable. This is an architectural boundary, NOT an
    upstream gap. We emit a machine-parseable ``FIXME(audioreach_topology_blob)``
    marker (invariant #3: never imply the DT declares what it cannot) and one
    ``audioreach.topology_blob.nord_iq10`` partial-artifact row in
    ``contributes_rows`` so a reviewer tracks the firmware-bundle dependency.

Gating (per PHASE2B_SPECIFICATION.md §4.1 + GATING_ROWS["audioreach_topology"]
= (("T3","lpass_macro_instance"), ("T3","dsp_subsystem_instance"))):

  1. **T3 LPASS-macro instance-count gate — ``T3.lpass_macro_instance`` MATCH.**
     A DISAGREE here is the Eliza production case: the proposed DT declares a
     different number of LPASS macro instances than the WP-C cardinality
     catalog derives from IPCAT. Emitting a GPR tree against a disputed LPASS
     instance count would bake the divergence into a generated artifact —
     skip with the reserved reason ``gating_row_disagree_on_lpass_count``.
     Checked FIRST (it is the highest-signal gate for this lane).

  2. **T3 DSP-subsystem instance-count gate — ``T3.dsp_subsystem_instance``
     MATCH.** The GPR tree assumes exactly the DSP-subsystem topology the
     catalog confirms; a DISAGREE closes the gate with the generic
     ``gating_row_disagree``.

  A missing gate row is fail-closed (``authority_not_in_snapshot``); a closed
  non-disagree row (warning / NCC / review-required) picks the most-specific
  reason via ``_skip_reason_for_no_open``.

Zero I/O, zero timestamps, zero env reads. Byte-identical input → byte-
identical output (LF endings, exactly one trailing LF).

Import discipline (WP6 — mirrors WP3/WP4/WP5):

  * MAY import: ``orchestrator.generation.model`` (WP1a — dataclasses),
    ``orchestrator.generation.config`` (WP1b — ``PATH_GUARD_ROOT``),
    ``orchestrator.reasoning.crossverify_model`` (``VerificationRow`` — needed
    to append the partial-artifact row to ``contributes_rows``).
  * MUST NOT import: ``orchestrator.generation.facts`` (WP6 receives
    ``TrustedFacts`` as input, like its peers);
    ``orchestrator.reasoning.crossverify`` /
    ``orchestrator.reasoning.cardinality`` (Phase-2A internals);
    ``orchestrator.generation.dt_scaffolding`` /
    ``orchestrator.generation.codec_stub`` /
    ``orchestrator.generation.machine_driver`` (peer generators — no
    generator↔generator coupling).
  * Enforced by ``tests/test_generation_audioreach.py::test_import_guard``.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_audioreach``
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

# ── Nord IQ-10 constants (WP6, Nord-family scoped) ──────────────────────────

#: The artifact class this generator emits. Fixed — matches the WP1b
#: ``_GENERATION_ARTIFACT_ORDER`` fourth (final) entry.
_ARTIFACT_CLASS: str = "audioreach_topology"

#: The two T3 gates this generator consults, in evaluation order. The LPASS
#: instance-count gate is checked first (highest-signal — the Eliza production
#: divergence closes it), then the DSP-subsystem instance-count gate. Each
#: string is used verbatim in ``GeneratorSkipped.gating_rows``.
_GATE_LPASS: str = "T3.lpass_macro_instance"
_GATE_DSP: str = "T3.dsp_subsystem_instance"


@register_generator(
    "audioreach_topology",
    order=3,
    gating_rows=(
        ("T3", "lpass_macro_instance"),
        ("T3", "dsp_subsystem_instance"),
    ),
)
def generate_audioreach_topology(
    facts: TrustedFacts, kb: object | None = None
) -> GenerationResult:
    """Emit an AudioReach-topology artifact or a skipped verdict for one target.

    Pure, deterministic, zero I/O. Byte-identical ``facts.to_dict()`` produces
    byte-identical ``result.to_dict()`` (modulo ``bytes_hex``).

    Parameters
    ----------
    facts:
        Immutable projection of a target's Phase-2A verification rows. The two
        ``T3`` element-count rows (``lpass_macro_instance``,
        ``dsp_subsystem_instance``) are the entire gating input.
    kb:
        Optional knowledge-base handle (reserved for symmetry with the other
        generators). WP6 does not consult a KB — the T3 verdicts are the whole
        policy signal.

    Returns
    -------
    GenerationResult
        Either a ``GeneratedArtifact`` (the GPR service-tree DTSI + one
        ``contributes_rows`` entry) or a ``GeneratorSkipped`` naming its closed
        gate.

    The ``subject`` field on the returned dataclass is the fixed literal
    ``"audioreach_topology"`` — matching ``artifact_class`` — because WP6 emits
    one GPR tree per target.
    """
    del kb  # WP6 does not consult a KB — see docstring.

    # ── Gate 1: T3 LPASS-macro instance count (Eliza production gate) ───────
    skip = _gate_check(facts, _GATE_LPASS, "gating_row_disagree_on_lpass_count")
    if skip is not None:
        return skip

    # ── Gate 2: T3 DSP-subsystem instance count ─────────────────────────────
    skip = _gate_check(facts, _GATE_DSP, "gating_row_disagree")
    if skip is not None:
        return skip

    # ── Gates open — build the artifact ─────────────────────────────────────
    lines: list[str] = []

    # Fixed DTSI preamble.
    lines.append("/*")
    lines.append(" * Generated by Phase-2B WP6 audioreach_topology.")
    lines.append(" * Deterministic. No timestamps.")
    lines.append(" *")
    lines.append(" * Nord IQ-10 AudioReach GPR service tree. Introduces the ADSP")
    lines.append(" * remoteproc PAS node (a fresh child of soc — Nord has no")
    lines.append(" * pre-existing ADSP remoteproc to overlay) carrying the glink-edge")
    lines.append(" * with fastrpc compute-callback edges and the GPR service tree")
    lines.append(" * (q6apm with its front-end/back-end DAIs, q6prm with its LPASS")
    lines.append(" * clock controller). Ported from linux-nord/0003-*.patch.")
    lines.append(" */")
    lines.append("")

    # &soc is the one label that resolves in the Nord include chain
    # (nord.dtsi:922). The whole ADSP remoteproc node is introduced here.
    lines.append("&soc {")

    # ADSP (audio DSP) remoteproc PAS node — reproduced verbatim from the patch,
    # including its FIXME block (reg base / SCMI-vs-rpmhpd / interconnect / SMMU
    # SIDs are known-open items; surfaced, not hidden). status = "disabled".
    lines.append("\t/*")
    lines.append("\t * ADSP (audio DSP) remoteproc + AudioReach service stack.")
    lines.append("\t * Ported from the SA8775P \"lemans\" reference — the qcom_q6v5_pas")
    lines.append("\t * driver already supports the \"qcom,sa8775p-adsp-pas\" compatible")
    lines.append("\t * (firmware adsp.mbn, pas_id 1, proxy PDs lcx/lmx). Placed here")
    lines.append("\t * (not nord.dtsi) because it wires to &rpmhcc / &rpmhpd, which are")
    lines.append("\t * IQ-10-specific; the SCMI-managed sa8797p-ride path must not pull")
    lines.append("\t * these phandles.")
    lines.append("\t *")
    lines.append("\t * TO BE REVIEWED — first-pass draft for SA8797P. Open items:")
    lines.append("\t *   reg base 0x30000000: matches the SA8775P/lemans layout (per IPCAT")
    lines.append("\t *     and the upstream QCS9100 DT series). NOTE: downstream Nord boot")
    lines.append("\t *     logs show the ADSP PAS at \"7000000.remoteproc-adsp\" (base")
    lines.append("\t *     0x07000000), so the upstream base is NOT yet cross-confirmed for")
    lines.append("\t *     SA8797P — reconcile 0x30000000 vs 0x07000000 against the SA8797P")
    lines.append("\t *     memory map before trusting on-board. FIXME(sa8797p-audio).")
    lines.append("\t *   FIXME(sa8797p-audio): power-domains reference RPMHPD_LCX/LMX, but")
    lines.append("\t *     this is WRONG for Nord. \"qcom,nord-rpmhpd\" does NOT expose")
    lines.append("\t *     LCX/LMX; downstream Nord uses SCMI power domains for the ADSP,")
    lines.append("\t *     not rpmhpd. The ADSP PAS will NOT probe as drafted; the")
    lines.append("\t *     SCMI-vs-rpmhpd power model MUST be resolved before enabling.")
    lines.append("\t *   FIXME(sa8797p-audio): the \"interconnects\" LPASS-NoC path is")
    lines.append("\t *     intentionally OMITTED — Nord has no lpass_ag_noc provider.")
    lines.append("\t *   FIXME(sa8797p-audio): apps_smmu stream IDs for fastrpc / q6apmdai")
    lines.append("\t *     assumed on apps_smmu_0 (0x300x SIDs); confirm which SMMU owns")
    lines.append("\t *     the ADSP streams.")
    lines.append("\t */")
    lines.append("\tremoteproc_adsp: remoteproc@30000000 {")
    lines.append("\t\tcompatible = \"qcom,sa8775p-adsp-pas\";")
    lines.append("\t\treg = <0x0 0x30000000 0x0 0x100>;")
    lines.append("")
    lines.append("\t\tinterrupts-extended = <&pdc 6 IRQ_TYPE_EDGE_RISING>,")
    lines.append("\t\t\t\t      <&smp2p_adsp_in 0 IRQ_TYPE_EDGE_RISING>,")
    lines.append("\t\t\t\t      <&smp2p_adsp_in 1 IRQ_TYPE_EDGE_RISING>,")
    lines.append("\t\t\t\t      <&smp2p_adsp_in 2 IRQ_TYPE_EDGE_RISING>,")
    lines.append("\t\t\t\t      <&smp2p_adsp_in 3 IRQ_TYPE_EDGE_RISING>;")
    lines.append("\t\tinterrupt-names = \"wdog\", \"fatal\", \"ready\", \"handover\",")
    lines.append("\t\t\t\t  \"stop-ack\";")
    lines.append("")
    lines.append("\t\tclocks = <&rpmhcc RPMH_CXO_CLK>;")
    lines.append("\t\tclock-names = \"xo\";")
    lines.append("")
    lines.append("\t\tpower-domains = <&rpmhpd RPMHPD_LCX>,")
    lines.append("\t\t\t\t<&rpmhpd RPMHPD_LMX>;")
    lines.append("\t\tpower-domain-names = \"lcx\", \"lmx\";")
    lines.append("")
    lines.append("\t\tmemory-region = <&hpass_dsp0_mem>;")
    lines.append("")
    lines.append("\t\tqcom,qmp = <&aoss_qmp>;")
    lines.append("")
    lines.append("\t\tqcom,smem-states = <&smp2p_adsp_out 0>;")
    lines.append("\t\tqcom,smem-state-names = \"stop\";")
    lines.append("")
    lines.append("\t\tstatus = \"disabled\";")
    lines.append("")

    # glink-edge: the ADSP GLINK transport. Carries fastrpc + the GPR tree.
    lines.append("\t\tglink-edge {")
    lines.append("\t\t\tinterrupts-extended = <&ipcc IPCC_CLIENT_LPASS")
    lines.append("\t\t\t\t\t\t     IPCC_MPROC_SIGNAL_GLINK_QMP")
    lines.append("\t\t\t\t\t\t     IRQ_TYPE_EDGE_RISING>;")
    lines.append("\t\t\tmboxes = <&ipcc IPCC_CLIENT_LPASS")
    lines.append("\t\t\t\t\tIPCC_MPROC_SIGNAL_GLINK_QMP>;")
    lines.append("")
    lines.append("\t\t\tlabel = \"lpass\";")
    lines.append("\t\t\tqcom,remote-pid = <2>;")
    lines.append("")

    # Machine-parseable FIXME: the APM module graph is an ACDB firmware blob,
    # architecturally out of DT scope. Emitted per invocation (invariant #3).
    lines.append("\t\t\t/* FIXME(audioreach_topology_blob): AudioReach APM module")
    lines.append("\t\t\t * graph (module IIDs, port wiring, connection matrix) is NOT")
    lines.append("\t\t\t * declared in device tree — it is loaded at runtime by the")
    lines.append("\t\t\t * q6apm firmware from an ACDB (Audio Calibration Database)")
    lines.append("\t\t\t * blob. This DT node establishes the GPR service entry points")
    lines.append("\t\t\t * only. The topology blob itself is a separate deliverable")
    lines.append("\t\t\t * (firmware bundle).")
    lines.append("\t\t\t */")
    lines.append("")

    # fastrpc compute-callback edges (verbatim from linux-nord/0003-*.patch).
    lines.append("\t\t\tfastrpc {")
    lines.append("\t\t\t\tcompatible = \"qcom,fastrpc\";")
    lines.append("\t\t\t\tqcom,glink-channels = \"fastrpcglink-apps-dsp\";")
    lines.append("\t\t\t\tlabel = \"adsp\";")
    lines.append("\t\t\t\tmemory-region = <&hpass_rpc_remote_heap_mem>;")
    lines.append("\t\t\t\tqcom,vmids = <QCOM_SCM_VMID_LPASS")
    lines.append("\t\t\t\t\t\t  QCOM_SCM_VMID_ADSP_HEAP>;")
    lines.append("\t\t\t\t#address-cells = <1>;")
    lines.append("\t\t\t\t#size-cells = <0>;")
    for cb_reg, cb_sid, cb_extra in (
        (3, "0x3003", None),
        (4, "0x3004", None),
        (5, "0x3005", "\t\t\t\t\tqcom,nsessions = <5>;"),
    ):
        lines.append("")
        lines.append(f"\t\t\t\tcompute-cb@{cb_reg} {{")
        lines.append("\t\t\t\t\tcompatible = \"qcom,fastrpc-compute-cb\";")
        lines.append(f"\t\t\t\t\treg = <{cb_reg}>;")
        lines.append(f"\t\t\t\t\tiommus = <&apps_smmu_0 {cb_sid} 0x0>;")
        if cb_extra is not None:
            lines.append(cb_extra)
        lines.append("\t\t\t\t\tdma-coherent;")
        lines.append("\t\t\t\t};")
    lines.append("\t\t\t};")
    lines.append("")

    # GPR service tree.
    lines.append("\t\t\tgpr {")
    lines.append("\t\t\t\tcompatible = \"qcom,gpr\";")
    lines.append("\t\t\t\tqcom,glink-channels = \"adsp_apps\";")
    lines.append("\t\t\t\tqcom,domain = <GPR_DOMAIN_ID_ADSP>;")
    lines.append("\t\t\t\tqcom,intents = <512 20>;")
    lines.append("\t\t\t\t#address-cells = <1>;")
    lines.append("\t\t\t\t#size-cells = <0>;")
    lines.append("")

    # q6apm audio processing manager + its front-end/back-end DAIs.
    lines.append("\t\t\t\tq6apm: service@1 {")
    lines.append("\t\t\t\t\tcompatible = \"qcom,q6apm\";")
    lines.append("\t\t\t\t\treg = <GPR_APM_MODULE_IID>;")
    lines.append("\t\t\t\t\t#sound-dai-cells = <0>;")
    lines.append(
        "\t\t\t\t\tqcom,protection-domain = \"avs/audio\","
    )
    lines.append("\t\t\t\t\t\t\t\t \"msm/adsp/audio_pd\";")
    lines.append("")
    lines.append("\t\t\t\t\tq6apmbedai: bedais {")
    lines.append("\t\t\t\t\t\tcompatible = \"qcom,q6apm-lpass-dais\";")
    lines.append("\t\t\t\t\t\t#sound-dai-cells = <1>;")
    lines.append("\t\t\t\t\t};")
    lines.append("")
    lines.append("\t\t\t\t\tq6apmdai: dais {")
    lines.append("\t\t\t\t\t\tcompatible = \"qcom,q6apm-dais\";")
    lines.append("\t\t\t\t\t\tiommus = <&apps_smmu_0 0x3001 0x0>;")
    lines.append("\t\t\t\t\t};")
    lines.append("\t\t\t\t};")
    lines.append("")

    # q6prm proxy resource manager + its LPASS clock controller.
    lines.append("\t\t\t\tq6prm: service@2 {")
    lines.append("\t\t\t\t\tcompatible = \"qcom,q6prm\";")
    lines.append("\t\t\t\t\treg = <GPR_PRM_MODULE_IID>;")
    lines.append(
        "\t\t\t\t\tqcom,protection-domain = \"avs/audio\","
    )
    lines.append("\t\t\t\t\t\t\t\t \"msm/adsp/audio_pd\";")
    lines.append("")
    lines.append("\t\t\t\t\tq6prmcc: clock-controller {")
    lines.append("\t\t\t\t\t\tcompatible = \"qcom,q6prm-lpass-clocks\";")
    lines.append("\t\t\t\t\t\t#clock-cells = <2>;")
    lines.append("\t\t\t\t\t};")
    lines.append("\t\t\t\t};")
    lines.append("\t\t\t};")
    lines.append("\t\t};")
    lines.append("\t};")
    lines.append("};")

    # Trailing newline — LF line endings, no BOM. Exactly one LF at EOF.
    bytes_ = ("\n".join(lines) + "\n").encode("utf-8")

    # Partial-artifact row: the topology blob is ACDB-loaded firmware, an
    # architectural boundary (NOT an upstream DT gap). NOT_CROSS_CHECKABLE +
    # authority_out_of_scope so the reviewer tracks the firmware dependency.
    contributes_rows = [
        VerificationRow(
            track="T5",
            subject="audioreach.topology_blob.nord_iq10",
            verdict="NOT_CROSS_CHECKABLE",
            coverage_gap_reason="authority_out_of_scope",
            notes=[
                "audioreach_topology: the DTSI declares the GPR service entry "
                "points (q6apm / q6prm) only. The AudioReach APM module graph "
                "(module IIDs, port wiring, connection matrix) is loaded at "
                "runtime by the q6apm firmware from an ACDB (Audio Calibration "
                "Database) blob and is NOT expressible in device tree. This is "
                "an architectural boundary, not an upstream DT gap: the "
                "topology blob is a separate firmware-bundle deliverable the "
                "reviewer must track independently of this artifact."
            ],
        )
    ]

    return GeneratedArtifact(
        subject=_ARTIFACT_CLASS,
        artifact_class=_ARTIFACT_CLASS,
        path_hint=f"{PATH_GUARD_ROOT}{_ARTIFACT_CLASS}/nord_audioreach.dtsi",
        bytes_=bytes_,
        contributes_rows=contributes_rows,
    )


def _gate_check(
    facts: TrustedFacts, gate_key: str, disagree_reason: str
) -> GeneratorSkipped | None:
    """Return a ``GeneratorSkipped`` if the ``gate_key`` gate is closed, else None.

    ``gate_key`` is a fully-qualified ``"<track>.<subject>"`` string (an exact
    subject — the T3 gates are not glob patterns). Resolution:

      * Missing row → ``authority_not_in_snapshot`` (fail-closed, §4.2).
      * ``DISAGREE_WITH_AUTHORITY`` → ``disagree_reason`` (caller supplies the
        gate-specific reason: ``gating_row_disagree_on_lpass_count`` for the
        LPASS gate, ``gating_row_disagree`` for the DSP gate).
      * Otherwise not open (warning / NCC / review-required) →
        ``_skip_reason_for_no_open`` picks the most-specific tail reason.
      * Open (``MATCH`` / ``PARTIAL_MATCH``, ``warning=False``) → ``None``.
    """
    track, _, subject = gate_key.partition(".")
    row = facts.rows_by_track_subject.get(gate_key)
    if row is None:
        return GeneratorSkipped(
            subject=_ARTIFACT_CLASS,
            artifact_class=_ARTIFACT_CLASS,
            reason="authority_not_in_snapshot",
            gating_rows=[gate_key],
        )
    if row.verdict == "DISAGREE_WITH_AUTHORITY":
        return GeneratorSkipped(
            subject=_ARTIFACT_CLASS,
            artifact_class=_ARTIFACT_CLASS,
            reason=disagree_reason,
            gating_rows=[gate_key],
        )
    if not facts.is_open(track, subject):
        return GeneratorSkipped(
            subject=_ARTIFACT_CLASS,
            artifact_class=_ARTIFACT_CLASS,
            reason=_skip_reason_for_no_open([row]),
            gating_rows=[gate_key],
        )
    return None


def _skip_reason_for_no_open(rows: list[VerificationRow]) -> str:
    """Pick the most-specific skip reason when no row in ``rows`` is open.

    Mirrors ``machine_driver._skip_reason_for_no_open`` (duplicated
    deliberately — WP6 must not import the peer generator; the predicate is
    small and stable).

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


__all__ = ["generate_audioreach_topology"]
