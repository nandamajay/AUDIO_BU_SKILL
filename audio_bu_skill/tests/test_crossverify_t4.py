"""Unit tests for Phase-2A WP7 — Track T4a (SoC Endpoint Validation) and
Track T4b (Codec Binding, structurally OUT OF SCOPE).

Pure tests over ``orchestrator.reasoning.crossverify.track_t4a`` and
``orchestrator.reasoning.crossverify.track_t4b``. No IPCAT, no collector, no
network — snapshots are built inline as plain dicts matching the WP1
collector's wire shape:

    snapshot["tools"]["chipio_get_qups"] = {
        "status":        "ok" | "unavailable",
        "payload":       [{"engine": "QUPv3_0_SE_5", "se_number": 5, "i2c": True}, ...],
        "result_digest": <sha256|None>,
    }
    snapshot["tools"]["cores_list_core_instances"]    = {...}
    snapshot["tools"]["buses_list_buses"]             = {...}

Covers the thirteen required cases (WP7 requirement 12, a–m):

  T4a
  a. QUP MATCH (DIRECT, high)
  b. QUP present, capability differs → PARTIAL_MATCH (warning=False, medium)
  c. Named core MATCH (DIRECT, high)
  d. Named core absent → DISAGREE_WITH_AUTHORITY (warning=True, high)
  e. Bus MATCH (INDIRECT, medium)
  f. chipio_get_qups unavailable + QUP claim → NCC(authority_unavailable),
     confidence=none
  g. Unknown kind → NCC(authority_out_of_scope) with unknown-kind note

  T4b
  h. Single binding → NCC(authority_out_of_scope), warning=False, confidence=none
  i. Two bindings → 2 NCC rows, deterministic order
  j. Empty/None source → []
  k. No IPCAT tool cited in any T4b row (kb.rule only)

  Cross-track
  l. Determinism (byte-equal to_dict on repeated calls, both tracks)
  m. Regression sentinel — importable alongside the WP1-WP6 tracks

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_crossverify_t4``
"""

from __future__ import annotations

from typing import Any

from orchestrator.reasoning.crossverify import (
    _T4A_AUTH_BUS_ORIGIN,
    _T4A_AUTH_CORE_ORIGIN,
    _T4A_AUTH_QUP_ORIGIN,
    track_t4a,
    track_t4b,
)
from orchestrator.reasoning.crossverify_config import (
    T4A_ENDPOINT_KINDS,
    T4B_OOS_REASON,
    T4B_RULE_ID,
)
from orchestrator.reasoning.crossverify_model import VerificationRow


# ── Snapshot builders (pure helpers, no I/O) ────────────────────────────────

CHIP_ALIAS = "nordschleife_2.0"


def _tool_ok(payload: Any) -> dict[str, Any]:
    """Well-formed ``status=ok`` tool entry (result_digest not consulted by T4a)."""
    return {"status": "ok", "payload": payload, "result_digest": "deadbeef"}


def _tool_unavailable(error_class: str = "TimeoutError") -> dict[str, Any]:
    return {
        "status": "unavailable",
        "payload": None,
        "result_digest": None,
        "error_class": error_class,
    }


def _snap(
    *,
    qups: list[dict[str, Any]] | None = None,
    cores: list[dict[str, Any]] | None = None,
    buses: list[dict[str, Any]] | None = None,
    chip: str | None = CHIP_ALIAS,
) -> dict[str, Any]:
    """Build a minimal snapshot with the three T4a authority tools populated.

    Each of ``qups`` / ``cores`` / ``buses`` may be:
      * ``None`` → the corresponding tool entry is ``unavailable``;
      * a list  → the tool entry is ``ok`` with that payload.

    ``chip=None`` produces a snapshot without the top-level ``chip`` alias.
    """
    tools: dict[str, dict[str, Any]] = {}
    tools["chipio_get_qups"] = (
        _tool_unavailable("RuntimeError") if qups is None else _tool_ok(qups)
    )
    tools["cores_list_core_instances"] = (
        _tool_unavailable("RuntimeError") if cores is None else _tool_ok(cores)
    )
    tools["buses_list_buses"] = (
        _tool_unavailable("RuntimeError") if buses is None else _tool_ok(buses)
    )
    snap: dict[str, Any] = {
        "provenance": {
            "tls": {"verify": True, "ssl_cert_file": "/etc/ssl/certs/ca-certificates.crt"},
            "readonly_tools": [
                "chipio_get_qups",
                "cores_list_core_instances",
                "buses_list_buses",
            ],
        },
        "tools": tools,
    }
    if chip is not None:
        snap["chip"] = chip
    return snap


def _by_rule(rows: list[VerificationRow]) -> dict[str, VerificationRow]:
    """Index rows by the ``kb.rule:<id>`` citation each carries (unique per rule)."""
    out: dict[str, VerificationRow] = {}
    for r in rows:
        for c in r.citations:
            if c.startswith("kb.rule:"):
                out[c[len("kb.rule:"):]] = r
                break
    return out


# Rule ids resolved from the KB table so the tests never hard-code them.
_RULE_QUP = str(T4A_ENDPOINT_KINDS["qup"]["rule_id"])
_RULE_CORE = str(T4A_ENDPOINT_KINDS["core"]["rule_id"])
_RULE_BUS = str(T4A_ENDPOINT_KINDS["bus"]["rule_id"])


# ═══════════════════════════════════════════════════════════════════════════
# T4a — SoC Endpoint Validation (tests a–g)
# ═══════════════════════════════════════════════════════════════════════════


# ── (a) QUP MATCH (DIRECT, high) ─────────────────────────────────────────────


def test_a_qup_match_direct_high() -> None:
    """Design QUP claim exactly matches a QUP catalog row → MATCH high."""
    snap = _snap(
        qups=[
            {"engine": "QUPv3_0_SE_5", "se_number": 5, "i2c": True, "instance": "SE_5"},
            {"engine": "QUPv3_0_SE_6", "se_number": 6, "spi": True, "instance": "SE_6"},
        ],
        cores=[],
        buses=[],
    )
    source = [{"kind": "qup", "engine": "QUPv3_0_SE_5", "cap": "i2c"}]
    rows = track_t4a(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.track == "T4a"
    assert row.subject == "qup.QUPv3_0_SE_5"
    assert row.verdict == "MATCH"
    assert row.warning is False
    assert row.coverage_gap_reason is None
    assert row.confidence == "high"  # DIRECT authority
    assert row.authority["strength"] == "IPCAT_DIRECT"
    assert row.authority["origin"] == _T4A_AUTH_QUP_ORIGIN
    assert row.authority["value"]["engine"] == "QUPv3_0_SE_5"
    # WP7 requirement 6 — two citations: <authority_tool>:<chip> + kb.rule:<id>
    assert f"chipio_get_qups:{CHIP_ALIAS}" in row.citations
    assert f"kb.rule:{_RULE_QUP}" in row.citations
    print("PASS: (a) QUP MATCH — QUPv3_0_SE_5 i2c → DIRECT high")


# ── (b) QUP present, capability differs → PARTIAL_MATCH (warning=False, medium) ─


def test_b_qup_partial_match_capability_differs() -> None:
    """QUP engine present but claimed cap differs from authority → PARTIAL_MATCH medium.

    Authority records QUPv3_0_SE_7 as SPI; source claims i2c. The endpoint
    itself is real, but the capability disagrees → PARTIAL_MATCH (warning=False).
    """
    snap = _snap(
        qups=[
            {"engine": "QUPv3_0_SE_7", "se_number": 7, "spi": True, "instance": "SE_7"},
        ],
        cores=[],
        buses=[],
    )
    source = [{"kind": "qup", "engine": "QUPv3_0_SE_7", "cap": "i2c"}]
    rows = track_t4a(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.subject == "qup.QUPv3_0_SE_7"
    assert row.verdict == "PARTIAL_MATCH"
    assert row.warning is False  # WP7 req 4 — PARTIAL_MATCH warning=False
    assert row.coverage_gap_reason is None
    assert row.confidence == "medium"  # WP7 req 5 — PARTIAL_MATCH → medium
    assert row.authority["strength"] == "IPCAT_DIRECT"
    assert row.authority["value"]["engine"] == "QUPv3_0_SE_7"
    # review action names the disagreement
    assert row.review_actions and "capability" in row.review_actions[0].lower()
    assert row.review_actions[0].lower().count("i2c") >= 1
    # citations both present
    assert f"chipio_get_qups:{CHIP_ALIAS}" in row.citations
    assert f"kb.rule:{_RULE_QUP}" in row.citations
    print("PASS: (b) QUP PARTIAL_MATCH — QUPv3_0_SE_7 cap(i2c) vs authority(spi), medium")


# ── (c) Named core MATCH (DIRECT, high) ──────────────────────────────────────


def test_c_named_core_match_direct_high() -> None:
    """A named core claim matches a core-instance row → MATCH high."""
    snap = _snap(
        qups=[],
        cores=[
            {"name": "Audio - QAIF", "id": 421, "group_name": "audio"},
            {"name": "qdsp6ss_0", "id": 512, "group_name": "audio_dsp"},
        ],
        buses=[],
    )
    source = [{"kind": "core", "name": "Audio - QAIF"}]
    rows = track_t4a(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.subject == "core.Audio - QAIF"
    assert row.verdict == "MATCH"
    assert row.warning is False
    assert row.confidence == "high"  # DIRECT
    assert row.authority["strength"] == "IPCAT_DIRECT"
    assert row.authority["origin"] == _T4A_AUTH_CORE_ORIGIN
    assert row.authority["value"]["name"] == "Audio - QAIF"
    assert f"cores_list_core_instances:{CHIP_ALIAS}" in row.citations
    assert f"kb.rule:{_RULE_CORE}" in row.citations
    print("PASS: (c) Named core MATCH — 'Audio - QAIF' → DIRECT high")


# ── (d) Named core absent → DISAGREE_WITH_AUTHORITY (warning=True, high) ────


def test_d_named_core_absent_is_disagree_high() -> None:
    """Named core not present in cores_list_core_instances → DISAGREE high."""
    snap = _snap(
        qups=[],
        cores=[
            {"name": "some_unrelated_core", "id": 999, "group_name": "misc"},
        ],
        buses=[],
    )
    source = [{"kind": "core", "name": "qdsp6ss_0"}]
    rows = track_t4a(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.subject == "core.qdsp6ss_0"
    assert row.verdict == "DISAGREE_WITH_AUTHORITY"
    assert row.warning is True  # WP7 req 4 — DISAGREE warns
    assert row.coverage_gap_reason is None
    assert row.confidence == "high"  # WP7 req 5 — DIRECT authority spoke
    assert row.authority["strength"] == "IPCAT_DIRECT"
    assert row.authority["value"] == {"present": False}
    assert row.review_actions and "qdsp6ss_0" in row.review_actions[0]
    assert f"cores_list_core_instances:{CHIP_ALIAS}" in row.citations
    assert f"kb.rule:{_RULE_CORE}" in row.citations
    print("PASS: (d) Named core absent — 'qdsp6ss_0' → DISAGREE high")


# ── (e) Bus MATCH (INDIRECT, medium) ─────────────────────────────────────────


def test_e_bus_match_indirect_medium() -> None:
    """A named bus claim matches an IPCAT bus row → MATCH medium (INDIRECT)."""
    snap = _snap(
        qups=[],
        cores=[],
        buses=[
            {"name": "audio_core_noc", "id": 12},
            {"name": "config_noc", "id": 13},
        ],
    )
    source = [{"kind": "bus", "name": "audio_core_noc"}]
    rows = track_t4a(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.subject == "bus.audio_core_noc"
    assert row.verdict == "MATCH"
    assert row.warning is False
    assert row.coverage_gap_reason is None
    # WP7 req 5 — bus MATCH (INDIRECT) → medium (not high)
    assert row.confidence == "medium", f"expected medium (INDIRECT), got {row.confidence!r}"
    assert row.authority["strength"] == "IPCAT_DERIVED"  # indirect
    assert row.authority["origin"] == _T4A_AUTH_BUS_ORIGIN
    assert row.authority["value"]["name"] == "audio_core_noc"
    # note must record the INDIRECT rationale
    assert row.notes and any("INDIRECT" in n or "indirect" in n for n in row.notes)
    assert f"buses_list_buses:{CHIP_ALIAS}" in row.citations
    assert f"kb.rule:{_RULE_BUS}" in row.citations
    print("PASS: (e) Bus MATCH — 'audio_core_noc' → INDIRECT medium")


# ── (f) chipio_get_qups unavailable + QUP claim → NCC(authority_unavailable) ─


def test_f_qup_authority_unavailable_is_ncc() -> None:
    """chipio_get_qups unavailable → NCC(authority_unavailable), confidence=none."""
    snap = _snap(qups=None, cores=[], buses=[])  # qups tool unavailable
    source = [{"kind": "qup", "engine": "QUPv3_0_SE_5", "cap": "i2c"}]
    rows = track_t4a(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.subject == "qup.QUPv3_0_SE_5"
    assert row.verdict == "NOT_CROSS_CHECKABLE"
    assert row.coverage_gap_reason == "authority_unavailable"
    assert row.warning is False  # NOT_CROSS_CHECKABLE warning defaults False
    assert row.confidence == "none"
    assert row.authority["strength"] == "UNAVAILABLE"
    assert row.authority["origin"] == "none"
    # citation still records the authority tool (with "<unavailable>" chip placeholder)
    assert "chipio_get_qups:<unavailable>" in row.citations
    assert f"kb.rule:{_RULE_QUP}" in row.citations
    assert row.review_actions and "chipio_get_qups" in row.review_actions[0]
    print("PASS: (f) chipio_get_qups unavailable + QUP claim → NCC(authority_unavailable)")


# ── (g) Unknown kind → NCC(authority_out_of_scope) with unknown-kind note ───


def test_g_unknown_kind_is_ncc_out_of_scope() -> None:
    """kind='pll' (not in T4A_ENDPOINT_KINDS) → NCC(authority_out_of_scope)."""
    snap = _snap(qups=[], cores=[], buses=[])
    source = [{"kind": "pll", "name": "audio_ref_pll_0"}]
    rows = track_t4a(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.verdict == "NOT_CROSS_CHECKABLE"
    assert row.coverage_gap_reason == "authority_out_of_scope"
    assert row.warning is False
    assert row.confidence == "none"
    assert row.authority["strength"] == "UNAVAILABLE"
    assert row.authority["origin"] == "none"
    # unknown-kind note recorded
    assert row.notes and any("unknown endpoint kind" in n for n in row.notes)
    # citations must NOT reference any T4a authority tool for unknown kinds
    for c in row.citations:
        assert not c.startswith("chipio_get_qups:"), c
        assert not c.startswith("cores_list_core_instances:"), c
        assert not c.startswith("buses_list_buses:"), c
    # a kb.rule citation is still present so provenance isn't empty
    assert any(c.startswith("kb.rule:") for c in row.citations)
    print("PASS: (g) Unknown kind 'pll' → NCC(authority_out_of_scope) with unknown-kind note")


# ═══════════════════════════════════════════════════════════════════════════
# T4b — Codec Binding (structurally OUT OF SCOPE) (tests h–k)
# ═══════════════════════════════════════════════════════════════════════════


# ── (h) Single binding → NCC(authority_out_of_scope) ─────────────────────────


def test_h_single_codec_binding_is_ncc_out_of_scope() -> None:
    """Every T4b binding → NCC(authority_out_of_scope), confidence=none, warning=False."""
    snap = _snap(qups=[], cores=[], buses=[])  # T4b never reads snapshot
    source = [{"codec": "PCM1681", "controller": "aud_intfc0"}]
    rows = track_t4b(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.track == "T4b"
    assert row.subject == "PCM1681<->aud_intfc0"
    assert row.verdict == "NOT_CROSS_CHECKABLE"
    assert row.coverage_gap_reason == T4B_OOS_REASON == "authority_out_of_scope"
    assert row.warning is False  # WP7 req 9 — warning=False
    assert row.confidence == "none"
    assert row.authority["strength"] == "UNAVAILABLE"
    assert row.authority["origin"] == "none"
    # WP7 req 9 — review action must name codec, controller, and "schematic/DTS DAI-links"
    assert row.review_actions and len(row.review_actions) == 1
    action = row.review_actions[0]
    assert "PCM1681" in action and "aud_intfc0" in action
    assert "schematic" in action.lower() and "dai-links" in action.lower()
    print("PASS: (h) Single T4b binding — PCM1681<->aud_intfc0 → NCC(authority_out_of_scope)")


# ── (i) Two bindings → 2 NCCs, deterministic order ───────────────────────────


def test_i_two_bindings_two_rows_deterministic_order() -> None:
    """Two codec bindings → 2 rows in source order, byte-equal across calls."""
    snap = _snap(qups=[], cores=[], buses=[])
    source = [
        {"codec": "PCM1681", "controller": "aud_intfc0"},
        {"codec": "ADAU1979", "controller": "aud_intfc1"},
    ]
    a = track_t4b(snapshot=snap, source=source, kb=None)
    b = track_t4b(snapshot=snap, source=source, kb=None)
    assert len(a) == 2 and len(b) == 2
    # deterministic order (matches source order)
    assert a[0].subject == "PCM1681<->aud_intfc0"
    assert a[1].subject == "ADAU1979<->aud_intfc1"
    assert [r.to_dict() for r in a] == [r.to_dict() for r in b]
    for r in a:
        assert r.verdict == "NOT_CROSS_CHECKABLE"
        assert r.coverage_gap_reason == T4B_OOS_REASON
        assert r.warning is False
        assert r.confidence == "none"
    print("PASS: (i) Two T4b bindings → 2 rows in source order, deterministic")


# ── (j) Empty/None source → [] ───────────────────────────────────────────────


def test_j_empty_source_yields_no_rows() -> None:
    """Empty list / None / wrapper with empty list → [] (no rows, no crash)."""
    snap = _snap(qups=[], cores=[], buses=[])
    assert track_t4b(snapshot=snap, source=[], kb=None) == []
    assert track_t4b(snapshot=snap, source=None, kb=None) == []
    assert track_t4b(snapshot=snap, source={"codecs": []}, kb=None) == []
    assert track_t4b(snapshot=snap, source={"codec_bindings": []}, kb=None) == []
    # And a source wrapper key with an actual entry is unwrapped correctly.
    rows = track_t4b(
        snapshot=snap,
        source={"codecs": [{"codec": "TAS5825M", "controller": "aud_intfc2"}]},
        kb=None,
    )
    assert len(rows) == 1 and rows[0].subject == "TAS5825M<->aud_intfc2"
    print("PASS: (j) Empty/None T4b source → [] (wrapper keys accepted)")


# ── (k) NO IPCAT tool cited in any T4b row (kb.rule only) ────────────────────


def test_k_t4b_never_cites_ipcat_tool() -> None:
    """Every T4b row must cite ONLY ``kb.rule:t4b.codec_binding.out_of_scope``.

    T4b is diagnostic-only. Citing any IPCAT tool would misrepresent the
    authority — IPCAT does not model codec bindings.
    """
    snap = _snap(qups=[], cores=[], buses=[])
    source = [
        {"codec": "PCM1681", "controller": "aud_intfc0"},
        {"codec": "ADAU1979", "controller": "aud_intfc1"},
        {"codec": "TAS5825M", "controller": "aud_intfc2"},
    ]
    rows = track_t4b(snapshot=snap, source=source, kb=None)
    assert len(rows) == 3
    # A list of IPCAT tool prefixes T4b must NEVER cite.
    forbidden_prefixes = (
        "chipio_get_qups:",
        "cores_list_core_instances:",
        "buses_list_buses:",
        "swi_search_swi:",
        "gpio_get_gpio_map:",
        "gpio_list_gpios_from_map:",
        "gpio_list_tlmm_gpios:",
        "chips_list_chips:",
    )
    for r in rows:
        # exactly one citation, and it MUST be the T4b kb.rule id
        assert r.citations == [f"kb.rule:{T4B_RULE_ID}"], r.citations
        for c in r.citations:
            for prefix in forbidden_prefixes:
                assert not c.startswith(prefix), (
                    f"T4b row cited forbidden IPCAT tool: {c}"
                )
    print("PASS: (k) T4b never cites any IPCAT tool — kb.rule:t4b.codec_binding.out_of_scope only")


# ═══════════════════════════════════════════════════════════════════════════
# Cross-track (tests l–m)
# ═══════════════════════════════════════════════════════════════════════════


# ── (l) Determinism — byte-equal to_dict on repeated calls, both tracks ──────


def test_l_determinism_both_tracks() -> None:
    """T4a + T4b are pure functions: identical input → byte-equal to_dict output."""
    snap = _snap(
        qups=[
            {"engine": "QUPv3_0_SE_5", "se_number": 5, "i2c": True},
            {"engine": "QUPv3_0_SE_7", "se_number": 7, "spi": True},
        ],
        cores=[{"name": "Audio - QAIF", "id": 421}],
        buses=[{"name": "audio_core_noc"}],
    )
    t4a_src = [
        {"kind": "qup", "engine": "QUPv3_0_SE_5", "cap": "i2c"},   # MATCH
        {"kind": "qup", "engine": "QUPv3_0_SE_7", "cap": "i2c"},   # PARTIAL_MATCH
        {"kind": "core", "name": "Audio - QAIF"},                    # MATCH
        {"kind": "core", "name": "qdsp6ss_0"},                       # DISAGREE
        {"kind": "bus",  "name": "audio_core_noc"},                  # MATCH (medium)
        {"kind": "bus",  "name": "phantom_noc"},                     # DISAGREE
        {"kind": "pll",  "name": "audio_ref_pll_0"},                 # NCC(OOS)
    ]
    t4b_src = [
        {"codec": "PCM1681", "controller": "aud_intfc0"},
        {"codec": "ADAU1979", "controller": "aud_intfc1"},
    ]
    a4a = [r.to_dict() for r in track_t4a(snapshot=snap, source=t4a_src, kb=None)]
    b4a = [r.to_dict() for r in track_t4a(snapshot=snap, source=t4a_src, kb=None)]
    a4b = [r.to_dict() for r in track_t4b(snapshot=snap, source=t4b_src, kb=None)]
    b4b = [r.to_dict() for r in track_t4b(snapshot=snap, source=t4b_src, kb=None)]
    assert a4a == b4a, "T4a must be deterministic across repeated calls"
    assert a4b == b4b, "T4b must be deterministic across repeated calls"
    # Sanity — assert against a non-trivial output shape so determinism-on-
    # empty-output can't be a false positive.
    assert len(a4a) == 7, f"expected 7 T4a rows, got {len(a4a)}"
    assert len(a4b) == 2, f"expected 2 T4b rows, got {len(a4b)}"
    verdicts_4a = [r["verdict"] for r in a4a]
    assert verdicts_4a.count("MATCH") == 3            # QUP+i2c, core, bus
    assert verdicts_4a.count("PARTIAL_MATCH") == 1     # QUP+cap-mismatch
    assert verdicts_4a.count("DISAGREE_WITH_AUTHORITY") == 2  # core absent, bus absent
    assert verdicts_4a.count("NOT_CROSS_CHECKABLE") == 1  # unknown kind
    print("PASS: (l) T4a + T4b deterministic across repeated calls (7 T4a rows, 2 T4b rows)")


# ── (m) Regression sentinel — WP1..WP6 tracks still importable ──────────────


def test_m_regression_wp1_wp6_tracks_still_importable() -> None:
    """T4a/T4b appended without breaking any prior track's public API.

    We don't re-run the T1/T2/T3/T5/collector suites in this test file — those
    each ship their own ``main()``. But WP7 requirement 13 says "regression:
    WP1–WP6 tests must still pass"; the simplest in-file sentinel is that all
    prior track entry points remain importable from ``crossverify`` and that
    the model still admits all six tracks in :data:`TRACKS`.
    """
    from orchestrator.reasoning.crossverify import (
        track_t1,
        track_t2,
        track_t3,
        track_t5,
    )
    from orchestrator.reasoning.crossverify_model import TRACKS

    for fn in (track_t1, track_t2, track_t3, track_t5, track_t4a, track_t4b):
        assert callable(fn), f"{fn.__name__} not callable"
    for t in ("T1", "T2", "T3", "T4a", "T4b", "T5"):
        assert t in TRACKS, f"track {t!r} missing from TRACKS"
    print("PASS: (m) WP1-WP6 track entry points still importable; TRACKS admits T4a/T4b")


# ── Extra contract sanity (not required by WP7 but pattern-parity with T1/T2/T5) ─


def test_t4a_source_wrapper_keys_unwrapped() -> None:
    """T4a source may be wrapped under 'endpoints'/'soc_endpoints'/'audio_endpoints'."""
    snap = _snap(
        qups=[{"engine": "QUPv3_0_SE_5", "se_number": 5, "i2c": True}],
        cores=[],
        buses=[],
    )
    claim = {"kind": "qup", "engine": "QUPv3_0_SE_5", "cap": "i2c"}
    for key in ("endpoints", "soc_endpoints", "audio_endpoints"):
        rows = track_t4a(snapshot=snap, source={key: [claim]}, kb=None)
        assert len(rows) == 1 and rows[0].verdict == "MATCH", (
            f"wrapper {key!r} not unwrapped correctly: {rows}"
        )
    print("PASS: T4a source wrapper keys ('endpoints'/'soc_endpoints'/'audio_endpoints') unwrapped")


def test_t4a_missing_chip_uses_unavailable_placeholder() -> None:
    """If snapshot omits 'chip', T4a citations use '<unavailable>' as placeholder."""
    snap = _snap(
        qups=[{"engine": "QUPv3_0_SE_5", "se_number": 5, "i2c": True}],
        cores=[],
        buses=[],
        chip=None,  # no chip alias in snapshot
    )
    source = [{"kind": "qup", "engine": "QUPv3_0_SE_5", "cap": "i2c"}]
    rows = track_t4a(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    assert "chipio_get_qups:<unavailable>" in rows[0].citations
    print("PASS: T4a missing chip alias → citation uses '<unavailable>' placeholder")


def test_t4a_empty_source_yields_no_rows() -> None:
    """Empty/None T4a source → [] (no rows, no crash)."""
    snap = _snap(qups=[], cores=[], buses=[])
    assert track_t4a(snapshot=snap, source=[], kb=None) == []
    assert track_t4a(snapshot=snap, source=None, kb=None) == []
    assert track_t4a(snapshot=snap, source={"endpoints": []}, kb=None) == []
    print("PASS: empty/None T4a source → [] (no rows, no crash)")


def test_source_fact_accepts_part_role_alias() -> None:
    """Fix 2 — ``_crossverify_source_facts`` must accept ``part``/``role`` as
    aliases for ``codec``/``controller`` in T4b bindings. Preference order:
    primary keys (``codec``/``controller``) win when present; the alias
    fallback only fires when the primary key is absent.

    End-to-end: run the mapped source through ``track_t4b`` and prove the
    resulting rows carry the aliased identity in the subject (never
    ``<unknown_codec>`` / ``<unknown_controller>``).
    """
    from orchestrator.main import _crossverify_source_facts

    gc = {
        "audio_topology": {
            "codecs": [
                # (i) alias-only entry — mirrors Nord/Eliza case.generated.py
                {"part": "TI PCM1681", "role": "DAC (playback, 8-ch)"},
                # (ii) primary-key entry — must not be shadowed by any alias
                {"codec": "WSA883x", "controller": "SwrTx"},
                # (iii) mixed entry — primary key wins over alias
                {"codec": "PrimaryCodec", "part": "AliasCodec",
                 "controller": "PrimaryCtrl", "role": "AliasCtrl"},
            ]
        }
    }
    facts = _crossverify_source_facts(gc)
    t4b_source = facts["t4b"]

    # The mapper preserves list shape and adds primary keys additively.
    assert isinstance(t4b_source, list) and len(t4b_source) == 3
    assert t4b_source[0]["codec"] == "TI PCM1681"
    assert t4b_source[0]["controller"] == "DAC (playback, 8-ch)"
    assert t4b_source[1]["codec"] == "WSA883x"
    assert t4b_source[1]["controller"] == "SwrTx"
    assert t4b_source[2]["codec"] == "PrimaryCodec", (
        "primary 'codec' key must not be overwritten by 'part' alias"
    )
    assert t4b_source[2]["controller"] == "PrimaryCtrl", (
        "primary 'controller' key must not be overwritten by 'role' alias"
    )

    # End-to-end: track_t4b sees the mapped source and never emits <unknown_*>.
    from orchestrator.reasoning.crossverify import track_t4b
    snap = _snap(qups=[], cores=[], buses=[])
    rows = track_t4b(snapshot=snap, source=t4b_source)
    assert len(rows) == 3
    subjects = [r.subject for r in rows]
    assert "TI PCM1681<->DAC (playback, 8-ch)" in subjects
    assert "WSA883x<->SwrTx" in subjects
    assert "PrimaryCodec<->PrimaryCtrl" in subjects
    for s in subjects:
        assert "<unknown_codec>" not in s and "<unknown_controller>" not in s, (
            f"alias mapping failed to reach T4b row builder: {s!r}"
        )
    print("PASS: T4b part/role alias mapping — primary keys preferred, aliases fill gaps")


def main() -> None:
    # WP7 requirement 12 — tests a–m
    # T4a (a–g)
    test_a_qup_match_direct_high()                                 # a
    test_b_qup_partial_match_capability_differs()                  # b
    test_c_named_core_match_direct_high()                          # c
    test_d_named_core_absent_is_disagree_high()                    # d
    test_e_bus_match_indirect_medium()                             # e
    test_f_qup_authority_unavailable_is_ncc()                      # f
    test_g_unknown_kind_is_ncc_out_of_scope()                      # g
    # T4b (h–k)
    test_h_single_codec_binding_is_ncc_out_of_scope()              # h
    test_i_two_bindings_two_rows_deterministic_order()             # i
    test_j_empty_source_yields_no_rows()                           # j
    test_k_t4b_never_cites_ipcat_tool()                            # k
    # Cross-track (l–m)
    test_l_determinism_both_tracks()                               # l
    test_m_regression_wp1_wp6_tracks_still_importable()            # m
    # Extra contract sanity (parity with T1/T2/T5 test files)
    test_t4a_source_wrapper_keys_unwrapped()
    test_t4a_missing_chip_uses_unavailable_placeholder()
    test_t4a_empty_source_yields_no_rows()
    test_source_fact_accepts_part_role_alias()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
