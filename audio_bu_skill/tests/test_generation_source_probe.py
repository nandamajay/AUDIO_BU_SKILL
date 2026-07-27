"""Move-2 Slice A — tests for the disclosure-only kernel-source probe.

Pure, stdlib-only tests over ``orchestrator.generation.source_probe`` and its
single consumer (the machine_driver lane + the generation runner). Mirrors the
WP3-WP7 discipline: inline data, no fakes, no network, no pytest.

The load-bearing guarantee this suite defends is the **disclosure firewall**:
the probe may change NOTE TEXT ONLY. It must never change the emitted DTSI
bytes, never reach ``cross_verification`` / ``TrustedFacts``, and never be
consulted by any gate. A missing tree/file degrades honestly to
``FILE_NOT_FOUND`` → UNVERIFIED, never a fabricated FOUND / ABSENT.

Fixture kernel trees (deterministic, NOT the live checkout) live under
``tests/fixtures/kernel_trees/``:

  * ``found_tree``  — driver .c LISTS ``qcom,nord-iq10-sndcard`` (→ FOUND) and
    the ports header defines ``OCTONARY_TDM_*`` (→ octonary FOUND, no missing
    rungs, ceilings at OCTONARY).
  * ``absent_tree`` — mirrors the real Nord observation: driver .c is readable
    but does NOT list the Nord compatible (→ ABSENT); ports header tops out at
    ``QUINARY_TDM`` with a ``SENARY_MI2S_*`` name-ceiling and no OCTONARY, so
    ``tdm_family_ceiling = QUINARY_TDM``, ``global_name_ceiling = SENARY``,
    ``octonary_tdm_defined = ABSENT``, ``missing_rungs =
    (SENARY_TDM, SEPTENARY_TDM)`` (OCTONARY reported separately per the
    Option-(iii) ruling, NOT collapsed into a single ceiling).

The 8 named guarantees (plus two observation-shape checks = 10 total):

  1. ``test_dtsi_bytes_invariant_across_probe_states`` — bytes byte-identical
     across FOUND / ABSENT / absent-tree / no-probe.
  2. ``test_probe_absent_tree_is_file_not_found`` — None / missing / non-dir
     tree → fully-FILE_NOT_FOUND, no raise.
  3. ``test_probe_is_read_only`` — AST proof the probe module has no write /
     glob / walk / network primitives; opens at most the two literal files.
  4. ``test_probe_never_reaches_cross_verification`` — running the lane with a
     probe adds no keys to ``facts.rows_by_track_subject``; the probe is not
     stored on facts.
  5. ``test_no_gate_consults_probe`` — a closed gate skips byte-identically
     whether the probe is FOUND, ABSENT, or absent.
  6. ``test_wp64_disclosure_only_intact`` — every contributes_row stays
     ``NOT_CROSS_CHECKABLE`` / ``authority_out_of_scope`` regardless of probe
     state; only note text moves.
  7. ``test_wp69_not_attested_intact`` — the board_variant NOT_ATTESTED
     disclosure survives every probe state.
  8. ``test_runner_threads_kernel_source_optional`` — ``_run_generation``
     accepts an omitted / ``None`` / fixture ``kernel_source`` and emits
     byte-identical machine_driver bytes in every case.
  9. ``test_found_tree_observed_disclosures`` — shape of the FOUND observation.
 10. ``test_absent_tree_observed_disclosures`` — shape of the ABSENT
     observation (the real Nord anchor).

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_source_probe``
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

from orchestrator.generation.facts import project_facts
from orchestrator.generation.machine_driver import (
    _SNDCARD_COMPATIBLE,
    generate_machine_driver,
)
from orchestrator.generation.model import (
    GeneratedArtifact,
    GeneratorSkipped,
    TrustedFacts,
)
from orchestrator.generation.runner import _run_generation
from orchestrator.generation import source_probe as source_probe_module
from orchestrator.generation.source_probe import ClaimStatus, SourceProbe
from orchestrator.reasoning.crossverify_model import VerificationRow

_AUDIO_BU_ROOT = Path(__file__).resolve().parent.parent
_KERNEL_TREES = _AUDIO_BU_ROOT / "tests" / "fixtures" / "kernel_trees"
_FOUND_TREE = str(_KERNEL_TREES / "found_tree")
_ABSENT_TREE = str(_KERNEL_TREES / "absent_tree")


# ── Helper builders (mirror test_generation_machine._clean_nord_facts) ───────


def _row(
    track: str,
    subject: str,
    verdict: str,
    *,
    rule_id: str | None = None,
    warning: bool | None = None,
    coverage_gap_reason: str | None = None,
    authority_strength: str = "IPCAT_DIRECT",
    authority_origin: str = "ipcat.test",
    authority_value: object | None = None,
) -> VerificationRow:
    authority = {"strength": authority_strength, "origin": authority_origin}
    if authority_value is not None:
        authority["value"] = authority_value
    return VerificationRow(
        track=track,
        subject=subject,
        verdict=verdict,
        authority=authority,
        confidence="high" if verdict == "MATCH" else "medium",
        coverage_gap_reason=coverage_gap_reason,
        rule_id=rule_id,
        warning=warning,
    )


def _clean_nord_facts() -> TrustedFacts:
    """Synthetic clean-Nord facts that open every machine_driver gate."""
    rows = [
        _row("T1", "gpio.i2s.mclk", "MATCH"),
        _row("T4a", "qup.se3", "MATCH"),
        _row(
            "T4b",
            "codec.adau1979",
            "NOT_CROSS_CHECKABLE",
            authority_strength="UNAVAILABLE",
            authority_origin="none",
            coverage_gap_reason="authority_out_of_scope",
            warning=True,
            rule_id="t4b.codec_binding.out_of_scope",
        ),
        _row(
            "T4b",
            "codec.pcm1681",
            "NOT_CROSS_CHECKABLE",
            authority_strength="UNAVAILABLE",
            authority_origin="none",
            coverage_gap_reason="authority_out_of_scope",
            warning=True,
            rule_id="t4b.codec_binding.out_of_scope",
        ),
        _row("T2", "soundwire_master", "MATCH"),
    ]
    return project_facts(rows)


def _missing_pinctrl_facts() -> TrustedFacts:
    """Facts with no open ``T1.gpio.i2s.*`` → closes the machine_driver gate."""
    rows_by_key = {
        "T4a.qup.se3": _row("T4a", "qup.se3", "MATCH"),
        "T4b.codec.adau1979": _row(
            "T4b",
            "codec.adau1979",
            "NOT_CROSS_CHECKABLE",
            authority_strength="UNAVAILABLE",
            authority_origin="none",
            coverage_gap_reason="authority_out_of_scope",
            warning=True,
            rule_id="t4b.codec_binding.out_of_scope",
        ),
    }
    return TrustedFacts(rows_by_track_subject=rows_by_key)


def _artifact_or_die(facts: TrustedFacts, *, source: SourceProbe | None):
    result = generate_machine_driver(facts, source=source)
    assert isinstance(result, GeneratedArtifact), (
        f"expected GeneratedArtifact for open gates, got "
        f"{type(result).__name__}: {result!r}"
    )
    return result


# ── 1. DTSI bytes invariant across every probe state ────────────────────────


def test_dtsi_bytes_invariant_across_probe_states() -> None:
    """Emitted machine_driver bytes are byte-identical across probe states.

    FOUND fixture, ABSENT fixture, absent-tree probe (``from_tree(None)``),
    and an explicit ``source=None`` (lane builds its own null probe) must all
    yield the same bytes. Only the disclosure NOTE TEXT is permitted to move.
    """
    facts = _clean_nord_facts()

    found = _artifact_or_die(facts, source=SourceProbe.from_tree(_FOUND_TREE))
    absent = _artifact_or_die(facts, source=SourceProbe.from_tree(_ABSENT_TREE))
    null_probe = _artifact_or_die(facts, source=SourceProbe.from_tree(None))
    no_source = _artifact_or_die(facts, source=None)

    assert found.bytes_ == absent.bytes_, "FOUND vs ABSENT byte-drift"
    assert absent.bytes_ == null_probe.bytes_, "ABSENT vs absent-tree byte-drift"
    assert null_probe.bytes_ == no_source.bytes_, "absent-tree vs no-source byte-drift"

    # Sanity: the note text DID move (otherwise the invariant is vacuous).
    found_notes = [n for r in found.contributes_rows for n in r.notes]
    absent_notes = [n for r in absent.contributes_rows for n in r.notes]
    assert found_notes != absent_notes, (
        "FOUND and ABSENT probes produced identical notes — the disclosure "
        "conversion is not actually grounding on file contents"
    )
    print(
        f"PASS: machine_driver bytes byte-identical across 4 probe states "
        f"({len(found.bytes_)} bytes); note text differs FOUND vs ABSENT"
    )


# ── 2. Absent tree → fully FILE_NOT_FOUND, no raise ─────────────────────────


def test_probe_absent_tree_is_file_not_found() -> None:
    """None / missing-path / non-directory tree → all-FILE_NOT_FOUND, no raise."""
    nonexistent = str(_KERNEL_TREES / "does_not_exist_ffea0f31")
    a_file = str(
        _KERNEL_TREES / "found_tree" / "sound" / "soc" / "qcom" / "sc8280xp.c"
    )
    for label, tree in (("None", None), ("missing", nonexistent), ("file", a_file)):
        probe = SourceProbe.from_tree(tree)
        assert probe.driver_status is ClaimStatus.FILE_NOT_FOUND, label
        assert probe.ports_status is ClaimStatus.FILE_NOT_FOUND, label
        assert probe.octonary_tdm_defined is ClaimStatus.FILE_NOT_FOUND, label
        assert probe.match_table_compatibles == (), label
        assert probe.port_defs == (), label
        # A per-board query on an unreadable tree is FILE_NOT_FOUND, never a
        # fabricated ABSENT / FOUND.
        status, line = probe.driver_match(_SNDCARD_COMPATIBLE)
        assert status is ClaimStatus.FILE_NOT_FOUND and line is None, label
    print("PASS: absent/None/non-dir tree → fully FILE_NOT_FOUND, no raise")


# ── 3. Read-only: no write / glob / walk / network primitives ───────────────


def test_probe_is_read_only() -> None:
    """AST proof: the probe module contains no write/glob/walk/network calls.

    The probe's read-only contract is structural, not incidental. Forbidden
    attribute calls (``.write_text``, ``.write_bytes``, ``.mkdir``, ``.unlink``,
    ``.rglob``, ``.glob``, ``os.walk`` …) and forbidden module imports
    (``socket``, ``urllib``, ``requests``, ``subprocess``, ``shutil``) must be
    absent. Only ``read_text`` and ``is_file`` / ``is_dir`` are permitted I/O.
    """
    src_path = Path(inspect.getfile(source_probe_module))
    tree = ast.parse(src_path.read_text(encoding="utf-8"), filename=str(src_path))

    forbidden_attrs = {
        "write_text",
        "write_bytes",
        "mkdir",
        "unlink",
        "rmdir",
        "touch",
        "open",  # bare open() could write; probe uses Path.read_text only
        "glob",
        "rglob",
        "walk",
        "iterdir",
        "system",
        "popen",
    }
    forbidden_imports = {
        "socket",
        "urllib",
        "urllib.request",
        "requests",
        "http",
        "subprocess",
        "shutil",
        "os",  # os.walk / os.remove et al. — probe needs none of os
    }

    attr_offenders: list[str] = []
    import_offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr in forbidden_attrs:
                attr_offenders.append(f".{fn.attr}(...) @ line {node.lineno}")
            elif isinstance(fn, ast.Name) and fn.id in forbidden_attrs:
                attr_offenders.append(f"{fn.id}(...) @ line {node.lineno}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in forbidden_imports:
                    import_offenders.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "") in forbidden_imports:
                import_offenders.append(f"from {node.module} import ...")

    assert not attr_offenders, (
        f"probe read-only guard failed: forbidden call(s) present: {attr_offenders!r}"
    )
    assert not import_offenders, (
        f"probe read-only guard failed: forbidden import(s) present: {import_offenders!r}"
    )
    print(
        "PASS: source_probe.py is structurally read-only "
        "(no write/glob/walk/network primitives)"
    )


# ── 4. Probe never reaches cross_verification / TrustedFacts ────────────────


def test_probe_never_reaches_cross_verification() -> None:
    """Running the lane with a probe adds no rows to facts; probe not stored.

    The disclosure firewall requires the probe to flow into ``contributes_rows``
    NOTES only — never back into ``facts.rows_by_track_subject`` (which would
    let a note re-enter cross-verification) and never as an attribute on the
    frozen ``TrustedFacts``.
    """
    facts = _clean_nord_facts()
    keys_before = set(facts.rows_by_track_subject.keys())

    result = _artifact_or_die(facts, source=SourceProbe.from_tree(_ABSENT_TREE))

    keys_after = set(facts.rows_by_track_subject.keys())
    assert keys_before == keys_after, (
        f"probe leaked rows into facts: added {keys_after - keys_before!r}"
    )
    # The T5 contributes_rows are disclosures on the artifact, NOT in facts.
    for r in result.contributes_rows:
        assert f"{r.track}.{r.subject}" not in facts.rows_by_track_subject, (
            f"contributes_row {r.track}.{r.subject} was fed back into facts "
            f"(WP-64 disclosure-only violation)"
        )
    # The probe object is not squirreled away on the facts projection.
    for attr in vars(facts).values() if hasattr(facts, "__dict__") else []:
        assert not isinstance(attr, SourceProbe), "SourceProbe stored on TrustedFacts"
    print("PASS: probe never reaches cross_verification / TrustedFacts")


# ── 5. No gate consults the probe ───────────────────────────────────────────


def test_no_gate_consults_probe() -> None:
    """A closed gate skips byte-identically regardless of probe state.

    The gate decision is a pure function of ``TrustedFacts``. Handing the lane
    a FOUND probe, an ABSENT probe, or no probe on gate-closing facts must
    produce the same ``GeneratorSkipped`` — proving ``is_open`` never consults
    the probe (a probe could otherwise smuggle a filesystem fact into a gate).
    """
    facts = _missing_pinctrl_facts()

    skipped = {
        "found": generate_machine_driver(facts, source=SourceProbe.from_tree(_FOUND_TREE)),
        "absent": generate_machine_driver(facts, source=SourceProbe.from_tree(_ABSENT_TREE)),
        "none": generate_machine_driver(facts, source=None),
    }
    for label, r in skipped.items():
        assert isinstance(r, GeneratorSkipped), f"{label}: expected skip, got {r!r}"

    dicts = {k: v.to_dict() for k, v in skipped.items()}
    assert dicts["found"] == dicts["absent"] == dicts["none"], (
        f"gate decision varied with probe state — a gate consults the probe: {dicts!r}"
    )
    assert dicts["none"]["reason"] == "authority_not_in_snapshot", dicts["none"]
    print("PASS: closed gate skips byte-identically across all probe states")


# ── 6. WP-64 disclosure-only invariant intact ───────────────────────────────


def test_wp64_disclosure_only_intact() -> None:
    """Every contributes_row stays NOT_CROSS_CHECKABLE / out_of_scope.

    Regardless of whether the probe OBSERVED FOUND or ABSENT, the verdict and
    coverage_gap_reason of the disclosure rows are frozen. The probe upgrades
    NOTE TEXT from UNVERIFIED to OBSERVED — it must never upgrade a verdict or
    close a coverage gap.
    """
    facts = _clean_nord_facts()
    for label, tree in (("found", _FOUND_TREE), ("absent", _ABSENT_TREE), ("none", None)):
        result = _artifact_or_die(facts, source=SourceProbe.from_tree(tree))
        assert result.contributes_rows, f"{label}: expected disclosure rows"
        for r in result.contributes_rows:
            assert r.track == "T5", f"{label}: track drift {r.track!r}"
            assert r.verdict == "NOT_CROSS_CHECKABLE", (
                f"{label}: verdict upgraded to {r.verdict!r} — disclosure firewall breached"
            )
            assert r.coverage_gap_reason == "authority_out_of_scope", (
                f"{label}: coverage gap closed to {r.coverage_gap_reason!r}"
            )
    print("PASS: WP-64 disclosure-only invariant intact across probe states")


# ── 7. WP-69 NOT_ATTESTED disclosure intact ─────────────────────────────────


def test_wp69_not_attested_intact() -> None:
    """The board_variant NOT_ATTESTED disclosure survives every probe state."""
    facts = _clean_nord_facts()
    for label, tree in (("found", _FOUND_TREE), ("absent", _ABSENT_TREE), ("none", None)):
        result = _artifact_or_die(facts, source=SourceProbe.from_tree(tree))
        subjects = [r.subject for r in result.contributes_rows]
        assert "sound_card.model.board_variant" in subjects, (
            f"{label}: WP-69 board_variant disclosure row missing: {subjects!r}"
        )
        assert b"FIXME(board_variant): NOT_ATTESTED" in result.bytes_, (
            f"{label}: WP-69 NOT_ATTESTED literal missing from emitted bytes"
        )
    print("PASS: WP-69 NOT_ATTESTED disclosure intact across probe states")


# ── 8. Runner threads kernel_source optionally ──────────────────────────────


def test_runner_threads_kernel_source_optional() -> None:
    """``_run_generation`` accepts omitted / None / fixture ``kernel_source``.

    In all three cases the machine_driver artifact is emitted with identical
    bytes. The kwarg is threaded ONLY to the machine_driver lane and defaults
    to a null probe when absent — a missing tree never changes bytes or gates.
    """

    def _machine_bytes(**kw) -> bytes:
        gc: dict = {"cross_verification": {"_probe": "non-empty"}}
        _run_generation(gc, _clean_nord_facts(), **kw)
        arts = gc["generation"]["artifacts"]
        machine = [
            a for a in arts if a.get("artifact_class") == "machine_driver"
        ]
        assert len(machine) == 1, f"expected 1 machine_driver artifact, got {machine!r}"
        entry = machine[0]
        assert entry.get("kind") == "artifact" or "bytes_hex" in entry, (
            f"machine_driver was skipped, not emitted: {entry!r}"
        )
        return bytes.fromhex(entry["bytes_hex"])

    omitted = _machine_bytes()
    explicit_none = _machine_bytes(kernel_source=None)
    found = _machine_bytes(kernel_source=_FOUND_TREE)
    absent = _machine_bytes(kernel_source=_ABSENT_TREE)

    assert omitted == explicit_none == found == absent, (
        "runner-threaded kernel_source changed the emitted machine_driver bytes"
    )
    print(
        f"PASS: _run_generation threads kernel_source optionally "
        f"(bytes byte-identical across omitted/None/found/absent; {len(omitted)} bytes)"
    )


# ── 9. FOUND-tree observation shape ─────────────────────────────────────────


def test_found_tree_observed_disclosures() -> None:
    """FOUND fixture: driver FOUND, OCTONARY defined, no missing rungs."""
    probe = SourceProbe.from_tree(_FOUND_TREE)
    status, line = probe.driver_match(_SNDCARD_COMPATIBLE)
    assert status is ClaimStatus.FOUND, status
    assert isinstance(line, int) and line > 0
    assert probe.global_name_ceiling == "OCTONARY", probe.global_name_ceiling
    assert probe.tdm_family_ceiling == "OCTONARY_TDM", probe.tdm_family_ceiling
    assert probe.octonary_tdm_defined is ClaimStatus.FOUND
    assert probe.missing_rungs == (), probe.missing_rungs
    print("PASS: FOUND-tree observation shape correct")


# ── 10. ABSENT-tree observation shape (real Nord anchor) ────────────────────


def test_absent_tree_observed_disclosures() -> None:
    """ABSENT fixture mirrors the real Nord observation exactly.

    driver ABSENT; ``global_name_ceiling = SENARY`` (MI2S name); bind-relevant
    ``tdm_family_ceiling = QUINARY_TDM``; ``octonary_tdm_defined = ABSENT``;
    ``missing_rungs = (SENARY_TDM, SEPTENARY_TDM)`` — exactly two, OCTONARY
    reported separately (Option-(iii) ruling: the two are not collapsed).
    """
    probe = SourceProbe.from_tree(_ABSENT_TREE)
    status, line = probe.driver_match(_SNDCARD_COMPATIBLE)
    assert status is ClaimStatus.ABSENT, status
    assert isinstance(line, int) and line > 0, "match-table line should be reported"
    assert probe.global_name_ceiling == "SENARY", probe.global_name_ceiling
    assert probe.tdm_family_ceiling == "QUINARY_TDM", probe.tdm_family_ceiling
    assert probe.octonary_tdm_defined is ClaimStatus.ABSENT
    assert probe.missing_rungs == ("SENARY_TDM", "SEPTENARY_TDM"), probe.missing_rungs
    # QUATERNARY_TDM_RX_0 = 72 grounds the emitted playback port ordinal.
    macro_status, value, macro_line = probe.port_macro("QUATERNARY_TDM_RX_0")
    assert macro_status is ClaimStatus.FOUND and value == 72 and macro_line > 0
    print("PASS: ABSENT-tree observation shape matches real Nord anchor")


def main() -> None:
    test_dtsi_bytes_invariant_across_probe_states()   # 1
    test_probe_absent_tree_is_file_not_found()        # 2
    test_probe_is_read_only()                         # 3
    test_probe_never_reaches_cross_verification()     # 4
    test_no_gate_consults_probe()                     # 5
    test_wp64_disclosure_only_intact()                # 6
    test_wp69_not_attested_intact()                   # 7
    test_runner_threads_kernel_source_optional()      # 8
    test_found_tree_observed_disclosures()            # 9
    test_absent_tree_observed_disclosures()           # 10
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
