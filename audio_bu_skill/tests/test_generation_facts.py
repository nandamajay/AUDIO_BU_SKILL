"""Phase-2B WP2 — tests for the fact projector (regression anchor).

Pure, stdlib-only tests over ``orchestrator.generation.facts``. Mirrors the
Phase-2A + WP1a + WP1b test discipline: inline data, no fakes, no network,
no pytest markers. Six tests total (five spec + one import guard) per
PHASE2B_SPECIFICATION.md §WP2:

  (a) ``test_empty_rows_yields_empty_facts``
  (b) ``test_phase2a_fixture_projects_to_expected_facts`` — fixture chain
      root: Phase-2A ``expected_rows.json`` → WP2 ``nord_trusted_facts.json``
      byte-equality
  (c) ``test_warning_true_row_projects_but_gates_closed``
  (d) ``test_unknown_track_subject_ignored_not_raised``
  (e) ``test_regression_anchor_byte_hash`` — sha256 assertion on the fixture
      (§WP2 acceptance criterion (e))
  (f) ``test_facts_import_guard`` — AST scan: facts.py has no forbidden
      imports; reasoning/*.py has no import from generation/*
  (g) ``test_regenerate_flag_not_accepted_by_test_modules`` — CI guardrail
      per §8.4: no ``--regenerate-fixtures`` flag in the pytest discovery
      path (regeneration lives at ``tests/regenerate/`` outside discovery).

Test (b) uses a Phase-2A fixture rehydrator. The Phase-2A fixture at
``tests/fixtures/phase2a/expected_rows.json`` currently emits a T4b row with
``verdict=REVIEW_REQUIRED`` **and** ``coverage_gap_reason=authority_out_of_scope``.
That combination is rejected by ``VerificationRow.__post_init__`` — the model
invariant is ``coverage_gap_reason ⇔ NOT_CROSS_CHECKABLE``, and spec §3.7
says T4b advisory rows are ``NCC + authority_out_of_scope`` (not REVIEW_REQUIRED
+ authority_out_of_scope). The Phase-2A fixture is under-strict here; we
correct the T4b verdict to ``NOT_CROSS_CHECKABLE`` at rehydrate time so the
row typechecks. WP2 flag; Phase-2A fixture is not modified under the
"no-Phase-2A-touch" constraint.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_facts``
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import re
from pathlib import Path

from orchestrator.generation import facts as gen_facts
from orchestrator.generation.facts import project_facts
from orchestrator.generation.model import TrustedFacts
from orchestrator.reasoning.crossverify_model import VerificationRow


_AUDIO_BU_ROOT = Path(__file__).resolve().parent.parent
_PHASE2A_FIXTURE = _AUDIO_BU_ROOT / "tests" / "fixtures" / "phase2a" / "expected_rows.json"
_PHASE2B_FIXTURE = _AUDIO_BU_ROOT / "tests" / "fixtures" / "phase2b" / "nord_trusted_facts.json"

# The regression anchor per §WP2(e). If you regenerated the fixture legitimately
# (via ``tests/regenerate/regenerate_phase2b_fixtures.py --wp 2``), update this
# constant AND the fixture in the same commit; both signals must agree.
_EXPECTED_FIXTURE_SHA256 = "55f1ca8fd1db3c74fe12ac2dd676d49e703003a80fe1e1bfe766881b87e90e4a"


# ── Fixture rehydration helper ──────────────────────────────────────────────


#: Nord IQ-10 codec fan-out for the T4b advisory row.
#:
#: The Phase-2A source fixture at ``tests/fixtures/phase2a/expected_rows.json``
#: emits a single T4b row on the donor's ``codec.wsa883x`` subject — Eliza's
#: codec, not Nord's. The Nord IQ-10 audio path routes to two board codecs:
#: ADI ADAU1979 (ADC) and TI PCM1681 (DAC), both on ``&i2c18``. Neither has an
#: IPCAT authority (T4b binding is out-of-scope per §3.7), so both are the same
#: shape as the donor row: NCC + authority_out_of_scope + warning=true.
#:
#: The rehydrator fans the single donor row out into these two Nord-truth
#: rows so ``nord_trusted_facts.json`` reflects Nord's actual codec inventory.
_NORD_T4B_CODEC_SUBJECTS: tuple[str, ...] = ("codec.adau1979", "codec.pcm1681")


#: Nord IQ-10 T2 SoundWire-master subject alignment.
#:
#: The Phase-2A source fixture emits the T2 row on the legacy subject
#: ``swr.mstr.tx``. Phase-2A's ``track_t2`` verifier actually emits exactly one
#: subject — ``soundwire_master`` (crossverify.py) — so the frozen fixture had
#: drifted. WP5's machine_driver gates on ``T2.*`` (DISAGREE → hard-skip), and
#: its gating-row vocabulary uses ``soundwire_master``; the WP2 fixture is
#: refreshed to match (decision C2). The Phase-2A source fixture is NOT touched
#: (no-Phase-2A-touch constraint); instead the rehydrator renames the source
#: subject here, the same shape as the T4b fan-out above.
_NORD_T2_SOURCE_SUBJECT: str = "swr.mstr.tx"
_NORD_T2_SUBJECT: str = "soundwire_master"


#: Nord IQ-10 T3 audio-resource cardinality rows (WP6 audioreach_topology gate).
#:
#: WP6's ``audioreach_topology`` generator gates on two T3 subjects —
#: ``lpass_macro_instance`` and ``dsp_subsystem_instance`` (``config.GATING_ROWS``).
#: The Phase-2A source fixture at ``tests/fixtures/phase2a/expected_rows.json``
#: carries only ``T3.clocks.count`` — the two element-count subjects the WP6
#: gate consults are absent from it. This is the same shape as the T4b codec
#: fan-out above: Phase-2A's frozen fixture predates the WP-C element_counts
#: schema (1.3.0) and does not enumerate these classes, so the rehydrator
#: synthesizes the two Nord-truth rows from this constant rather than reading
#: them out of ``expected_rows.json`` (which carries no ``element_counts`` block).
#:
#: The verdicts and authority shape mirror what ``crossverify.track_t3`` emits
#: for a post-SWI catalog-MATCH row (``IPCAT_DIRECT`` +
#: ``origin=wp_c.cardinality_catalog`` + the catalog count carried verbatim):
#:
#:   * ``dsp_subsystem_instance`` MATCH, count 1 — Nord's single ADSP (q6apm).
#:   * ``lpass_macro_instance``  MATCH, count 0 — Nord is I2S-only; it declares
#:     no LPASS macro instances (the divergence Eliza's snapshot disputes lives
#:     on this very subject — see ``test_generation_audioreach``).
#:
#: NOTE (fixture-provenance gap, filed separately post-WP6): this seeds the WP2
#: fixture rather than projecting it from a live Nord Phase-2A run. A full WP2
#: fixture regeneration against live Nord Phase-2A is deferred until bespoke
#: tooling exists — the same class of gap as the WP5 ``T2`` subject rename
#: (decision C2).
_NORD_T3_ROWS: tuple[dict, ...] = (
    {
        "track": "T3",
        "subject": "dsp_subsystem_instance",
        "source": {},
        "authority": {
            "strength": "IPCAT_DIRECT",
            "origin": "wp_c.cardinality_catalog",
            "value": {"count": 1},
        },
        "verdict": "MATCH",
        "confidence": "high",
        "coverage_gap_reason": None,
        "rule_id": None,
        "warning": False,
        "review_actions": [],
        "citations": [],
        "notes": [],
    },
    {
        "track": "T3",
        "subject": "lpass_macro_instance",
        "source": {},
        "authority": {
            "strength": "IPCAT_DIRECT",
            "origin": "wp_c.cardinality_catalog",
            "value": {"count": 0},
        },
        "verdict": "MATCH",
        "confidence": "high",
        "coverage_gap_reason": None,
        "rule_id": None,
        "warning": False,
        "review_actions": [],
        "citations": [],
        "notes": [],
    },
)


def _rehydrate_phase2a_rows() -> list[VerificationRow]:
    """Load ``expected_rows.json`` as ``list[VerificationRow]`` with Nord codec fan-out.

    Two corrections happen here — both driven by the "no-Phase-2A-touch"
    constraint, see module docstring:

      1. The Phase-2A T4b row's ``verdict=REVIEW_REQUIRED`` +
         ``coverage_gap_reason=authority_out_of_scope`` combination is rejected
         by the WP1a model invariant (``coverage_gap_reason ⇔ NOT_CROSS_CHECKABLE``).
         Spec §3.7 requires ``NCC + authority_out_of_scope`` for T4b advisory
         rows; we swap the verdict to ``NOT_CROSS_CHECKABLE`` at rehydrate
         time.
      2. The donor's ``codec.wsa883x`` subject is Eliza-truth, not Nord-truth.
         Nord IQ-10 wires two codecs on ``&i2c18`` (ADAU1979 ADC + PCM1681 DAC),
         so we fan the single donor row out into two Nord-truth rows keyed by
         ``_NORD_T4B_CODEC_SUBJECTS``. Both keep the same shape (NCC, authority
         UNAVAILABLE, ``rule_id=t4b.codec_binding.out_of_scope``,
         ``review_actions=["confirm codec DAI-link binding with schematic"]``).
    """
    raw = json.loads(_PHASE2A_FIXTURE.read_text(encoding="utf-8"))
    rows: list[VerificationRow] = []
    for r in raw:
        if (
            r.get("track") == "T4b"
            and r.get("verdict") == "REVIEW_REQUIRED"
            and r.get("coverage_gap_reason")
        ):
            base = dict(r)
            base["verdict"] = "NOT_CROSS_CHECKABLE"
            for nord_subject in _NORD_T4B_CODEC_SUBJECTS:
                nord_row = dict(base)
                nord_row["subject"] = nord_subject
                rows.append(VerificationRow(**nord_row))
            continue
        if r.get("track") == "T2" and r.get("subject") == _NORD_T2_SOURCE_SUBJECT:
            # Decision C2: align the T2 subject to the single ``soundwire_master``
            # subject Phase-2A's track_t2 actually emits. Verdict, warning,
            # authority, and rule_id are untouched.
            renamed = dict(r)
            renamed["subject"] = _NORD_T2_SUBJECT
            rows.append(VerificationRow(**renamed))
            continue
        rows.append(VerificationRow(**r))
    # WP6: synthesize the two T3 element-count rows the audioreach_topology gate
    # consults. Phase-2A's frozen fixture predates the WP-C element_counts schema
    # and carries only ``T3.clocks.count``; the two gate subjects
    # (dsp_subsystem_instance, lpass_macro_instance) are fabricated here from
    # ``_NORD_T3_ROWS`` — same idiom as the T4b codec fan-out above.
    for t3_row in _NORD_T3_ROWS:
        rows.append(VerificationRow(**t3_row))
    return rows


def _row(
    *,
    track: str = "T1",
    subject: str = "gpio.i2s.mclk",
    verdict: str = "MATCH",
    warning: bool | None = None,
    coverage_gap_reason: str | None = None,
    confidence: str = "high",
) -> VerificationRow:
    """Minimal, valid VerificationRow. NCC auto-supplies coverage_gap_reason."""
    if verdict == "NOT_CROSS_CHECKABLE" and coverage_gap_reason is None:
        coverage_gap_reason = "authority_out_of_scope"
    return VerificationRow(
        track=track,
        subject=subject,
        verdict=verdict,
        source={},
        authority={"strength": "IPCAT_DIRECT", "origin": "test", "value": {}},
        confidence=confidence,
        warning=warning,
        coverage_gap_reason=coverage_gap_reason,
    )


# ── (a) empty input ────────────────────────────────────────────────────────


def test_empty_rows_yields_empty_facts() -> None:
    """``project_facts([])`` returns an empty ``TrustedFacts`` — no crash, no NULL.

    An empty input is a valid state (Phase-2A ran but every verifier returned
    an empty row list — e.g. all verifiers were skipped due to lack of
    authority). The projection must not raise and must produce a valid
    ``TrustedFacts`` whose ``to_dict()`` serializes byte-stably.
    """
    tf = project_facts([])
    assert isinstance(tf, TrustedFacts)
    assert tf.rows_by_track_subject == {}
    # to_dict is byte-stable across repeated calls
    d1 = tf.to_dict()
    d2 = tf.to_dict()
    assert d1 == d2 == {"rows_by_track_subject": {}}
    # is_open on empty TrustedFacts fails closed for every query
    assert tf.is_open("T5", "dts.firmware") is False
    assert tf.is_open("T4b", "codec.pcm1681") is False
    print("PASS: (a) empty rows → empty TrustedFacts, byte-stable, fails closed")


# ── (b) Phase-2A fixture chain → WP2 fixture (byte equality) ───────────────


def test_phase2a_fixture_projects_to_expected_facts() -> None:
    """Phase-2A ``expected_rows.json`` projects to the frozen WP2 fixture.

    This is the WP2 regression anchor per §WP2 acceptance criterion (b):
    Phase-2A's frozen fixture (six rows) → byte-deterministic ``TrustedFacts``
    matching ``tests/fixtures/phase2b/nord_trusted_facts.json``. Every
    downstream WP (WP3–WP7, WP10) builds against this fixture rather than a
    live projection, so a drift in the projection here breaks the entire
    generation chain.

    Assertion is byte-equality on the JSON serialization form (sorted keys,
    2-space indent, trailing newline) — not just a Python-dict equality check
    — because downstream WPs' fixture chains compare byte contents.
    """
    rows = _rehydrate_phase2a_rows()
    assert len(rows) == 9, (
        f"Phase-2A fixture must yield 9 rows after Nord fan-out "
        f"(5 non-T4b + 2 Nord codec rows from the single donor T4b row "
        f"+ 2 synthesized T3 element-count rows for the WP6 gate); got {len(rows)}"
    )
    tf = project_facts(rows)
    got_payload = json.dumps(tf.to_dict(), sort_keys=True, indent=2) + "\n"
    expected_payload = _PHASE2B_FIXTURE.read_text(encoding="utf-8")
    assert got_payload == expected_payload, (
        "Phase-2A → WP2 projection drift. If the change is intentional, "
        "regenerate via ``tests/regenerate/regenerate_phase2b_fixtures.py --wp 2`` "
        "and update _EXPECTED_FIXTURE_SHA256 in this test.\n"
        f"---got ({len(got_payload)} bytes)---\n{got_payload!r}\n"
        f"---expected ({len(expected_payload)} bytes)---\n{expected_payload!r}"
    )
    # Every Phase-2A row lands in the projection — no silent dropping
    keys = set(tf.rows_by_track_subject)
    expected_keys = {
        "T1.gpio.i2s.mclk",
        "T2.soundwire_master",
        "T3.clocks.count",
        "T3.dsp_subsystem_instance",
        "T3.lpass_macro_instance",
        "T4a.qup.se3",
        "T4b.codec.adau1979",
        "T4b.codec.pcm1681",
        "T5.dts.firmware",
    }
    assert keys == expected_keys, f"projection dropped or renamed keys: {keys ^ expected_keys!r}"
    print("PASS: (b) Phase-2A expected_rows.json → WP2 nord_trusted_facts.json byte-equal")


# ── (c) warning=True projects but is_open closes the gate ──────────────────


def test_warning_true_row_projects_but_gates_closed() -> None:
    """A ``warning=True`` row still appears in ``rows_by_track_subject``.

    The projection is inclusive so the runner can *see* the row and produce
    a ``GeneratorSkipped(reason="gating_row_warning", ...)`` with an accurate
    ``gating_rows`` reference. If the row were dropped, the skip verdict
    would say "row missing" (a fail-closed default, §4.2) instead of the
    correct "warning" reason — a diagnostic downgrade the runner cannot
    recover from.

    ``is_open()`` returns False regardless (WP1a invariant: ``warning=True``
    is always closed) — proving projection is a separate concern from gating.
    """
    # MATCH + warning=True — verdict alone would open, warning closes it
    warning_row = _row(
        track="T3",
        subject="speaker",
        verdict="MATCH",
        warning=True,
    )
    # A normal MATCH row for contrast
    healthy_row = _row(track="T1", subject="gpio.i2s.mclk", verdict="MATCH")
    tf = project_facts([warning_row, healthy_row])

    # BOTH rows must be present in the projection
    assert "T3.speaker" in tf.rows_by_track_subject, (
        "warning=True row must project (else runner cannot produce the correct skip reason)"
    )
    assert "T1.gpio.i2s.mclk" in tf.rows_by_track_subject
    # is_open closes on the warning row, opens on the healthy row
    assert tf.is_open("T3", "speaker") is False, (
        "warning=True must close the gate at is_open() layer (WP1a §4)"
    )
    assert tf.is_open("T1", "gpio.i2s.mclk") is True

    # DISAGREE_WITH_AUTHORITY carries warning=True by default (WP1a
    # _WARNING_DEFAULT_TRUE). Same rules apply: projected, gate closed.
    disagree_row = _row(
        track="T2",
        subject="swr.mstr.tx",
        verdict="DISAGREE_WITH_AUTHORITY",
        confidence="high",
    )
    tf2 = project_facts([disagree_row])
    assert "T2.swr.mstr.tx" in tf2.rows_by_track_subject
    assert tf2.is_open("T2", "swr.mstr.tx") is False
    print("PASS: (c) warning=True rows project into rows_by_track_subject; is_open closes them")


# ── (d) unknown (track, subject) is projected, not raised ──────────────────


def test_unknown_track_subject_ignored_not_raised() -> None:
    """Unknown ``(track, subject)`` combinations project silently.

    The projection is unopinionated about which pairs are "known" — that
    concern belongs to WP1b's ``GATING_ROWS``. An unknown row still lands
    in ``rows_by_track_subject``; the runner's gate evaluator simply never
    queries it, so it has no effect on downstream artifact generation.

    A silent projection is preferable to raising: Phase-2A can emit new
    ``(track, subject)`` pairs (e.g. a new verifier landing in a future
    version) without breaking Phase-2B until WP1b's ``GATING_ROWS`` is
    updated to reference them. Fail-open at the type layer, fail-closed at
    the policy layer — the standard bicameral pattern.
    """
    # A completely fabricated (track, subject) — T7 does not exist in
    # crossverify_model.TRACKS. But VerificationRow *would* reject it. We
    # exercise the projector's tolerance against a *shape*-valid but
    # gating-unknown pair: T3.unknown_signal (T3 exists but WP1b's
    # GATING_ROWS lists only lpass_macro_instance / dsp_subsystem_instance
    # under T3, so "T3.unknown_signal" is unknown to gating).
    unknown_row = _row(track="T3", subject="unknown_signal", verdict="MATCH")
    known_row = _row(track="T5", subject="dts.firmware", verdict="MATCH")
    tf = project_facts([unknown_row, known_row])

    # Both project. project_facts does not filter, does not raise.
    assert "T3.unknown_signal" in tf.rows_by_track_subject
    assert "T5.dts.firmware" in tf.rows_by_track_subject
    # is_open on the unknown pair returns True here (verdict=MATCH, no warning).
    # The gate STAYS OPEN at the type layer — the runner is responsible for
    # checking WP1b's GATING_ROWS before consulting is_open.
    assert tf.is_open("T3", "unknown_signal") is True
    # A row genuinely missing from the projection fails closed (§4.2)
    assert tf.is_open("T99", "totally_absent") is False
    print("PASS: (d) unknown (track, subject) is projected silently; no raise")


# ── (e) Regression anchor byte hash ────────────────────────────────────────


def test_regression_anchor_byte_hash() -> None:
    """SHA256 of ``nord_trusted_facts.json`` matches the embedded literal.

    Per §WP2 acceptance criterion (e). Any byte-drift in the fixture — a
    trailing whitespace, a re-ordered key, a hex-encoding change in
    VerificationRow.authority — causes this test to fail *before* any
    downstream test (WP3–WP10) exercises the fixture chain, so the failure
    point is diagnostic rather than propagated.

    Regeneration is legitimate (spec §8.3) via
    ``tests/regenerate/regenerate_phase2b_fixtures.py --wp 2`` — update the
    literal and the fixture in the SAME commit. See §8.4 for the CI
    guardrail that keeps regeneration out of the pytest discovery path.
    """
    payload = _PHASE2B_FIXTURE.read_text(encoding="utf-8").encode("utf-8")
    got = hashlib.sha256(payload).hexdigest()
    assert got == _EXPECTED_FIXTURE_SHA256, (
        f"nord_trusted_facts.json byte-hash drift.\n"
        f"  expected: {_EXPECTED_FIXTURE_SHA256}\n"
        f"  got:      {got}\n"
        f"  bytes:    {len(payload)}\n"
        f"If change is intentional, regenerate via "
        f"tests/regenerate/regenerate_phase2b_fixtures.py --wp 2 "
        f"and update _EXPECTED_FIXTURE_SHA256."
    )
    # Sanity: fixture format matches §8.5 (sorted keys, 2-space indent, trailing newline)
    text = _PHASE2B_FIXTURE.read_text(encoding="utf-8")
    assert text.endswith("\n"), "fixture must end with a trailing newline (§8.5)"
    parsed = json.loads(text)
    reserialized = json.dumps(parsed, sort_keys=True, indent=2) + "\n"
    assert text == reserialized, (
        "fixture format drift: not (sort_keys=True, indent=2, trailing newline) canonical form"
    )
    print(f"PASS: (e) regression anchor sha256 matches ({len(payload)} bytes)")


# ── (f) Import guard — bidirectional AST scan ──────────────────────────────


def test_facts_import_guard() -> None:
    """Bidirectional AST-based import guard for facts.py and reasoning/*.py.

    Forward: ``orchestrator/generation/facts.py`` may NOT import from
    ``orchestrator.reasoning.crossverify`` or ``orchestrator.reasoning.cardinality``.
    Projection is unopinionated about the verification internals; it consumes
    ``VerificationRow`` only.

    Reverse: no file under ``orchestrator/reasoning/`` may import from
    ``orchestrator.generation`` (reverse dependency = cycle at package layer).

    AST-based (not regex) so ``import X`` and ``from X import Y`` are both
    caught and comments/docstrings that mention module names cannot produce
    a false positive.
    """
    # ── forward guard: facts.py imports ───────────────────────────────────
    facts_file = _AUDIO_BU_ROOT / "orchestrator" / "generation" / "facts.py"
    tree = ast.parse(facts_file.read_text(encoding="utf-8"), filename=str(facts_file))
    forbidden_forward_prefixes = (
        "orchestrator.reasoning.crossverify",
        "orchestrator.reasoning.cardinality",
    )
    # crossverify_model IS permitted — it's the VerificationRow type source.
    allowed_reasoning_imports = {"orchestrator.reasoning.crossverify_model"}
    offenders_forward: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module in allowed_reasoning_imports:
                continue
            for prefix in forbidden_forward_prefixes:
                if module == prefix or module.startswith(prefix + "."):
                    offenders_forward.append(f"from {module} import ...")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in allowed_reasoning_imports:
                    continue
                for prefix in forbidden_forward_prefixes:
                    if alias.name == prefix or alias.name.startswith(prefix + "."):
                        offenders_forward.append(f"import {alias.name}")
    assert not offenders_forward, (
        f"facts.py import guard failed: forbidden reasoning imports {offenders_forward!r}"
    )
    # Positive: facts.py DOES import from generation.model and crossverify_model
    src = inspect.getsource(gen_facts)
    assert re.search(
        r"\bfrom\s+orchestrator\.generation\.model\s+import\s+TrustedFacts\b", src
    ), "sanity: facts.py should import TrustedFacts from generation.model"
    assert re.search(
        r"\bfrom\s+orchestrator\.reasoning\.crossverify_model\s+import\s+VerificationRow\b", src
    ), "sanity: facts.py should import VerificationRow from reasoning.crossverify_model"

    # ── reverse guard: reasoning/*.py imports ─────────────────────────────
    reasoning_dir = _AUDIO_BU_ROOT / "orchestrator" / "reasoning"
    assert reasoning_dir.is_dir(), f"reasoning package not found at {reasoning_dir!r}"
    offenders_reverse: list[tuple[str, str]] = []
    files_scanned = 0
    for py_file in sorted(reasoning_dir.rglob("*.py")):
        files_scanned += 1
        try:
            r_tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError:
            continue
        rel = str(py_file.relative_to(_AUDIO_BU_ROOT))
        for node in ast.walk(r_tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "orchestrator.generation" or module.startswith(
                    "orchestrator.generation."
                ):
                    offenders_reverse.append((rel, f"from {module} import ..."))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "orchestrator.generation" or alias.name.startswith(
                        "orchestrator.generation."
                    ):
                        offenders_reverse.append((rel, f"import {alias.name}"))
    assert not offenders_reverse, (
        f"reverse-import guard failed: reasoning/*.py imports from generation: "
        f"{offenders_reverse!r}"
    )
    assert files_scanned > 0, "sanity: no reasoning/*.py scanned — vacuous pass"
    print(
        f"PASS: (f) facts.py has no forbidden reasoning imports; "
        f"{files_scanned} reasoning/*.py files scanned, no reverse imports"
    )


# ── (g) CI guardrail — --regenerate-fixtures not accepted by tests/ ────────


def test_regenerate_flag_not_accepted_by_test_modules() -> None:
    """Per §8.4: no test module under ``tests/`` accepts ``--regenerate-fixtures``.

    Regeneration is legitimate — but it lives at
    ``tests/regenerate/regenerate_phase2b_fixtures.py``, which is intentionally
    *not* on pytest's discovery path (no ``test_`` prefix, no ``conftest.py``
    picks it up). This test enforces the "regeneration is opt-in, out-of-band"
    guardrail by AST-scanning every ``tests/test_*.py`` for the string
    ``--regenerate-fixtures``. A test module that grew such a flag would
    silently allow ``pytest --regenerate-fixtures`` to rewrite fixtures on a
    normal test run — the exact scenario §8.4 forbids.
    """
    tests_dir = _AUDIO_BU_ROOT / "tests"
    assert tests_dir.is_dir(), f"tests/ dir not found at {tests_dir!r}"
    offenders: list[str] = []
    files_scanned = 0
    for py_file in sorted(tests_dir.rglob("test_*.py")):
        # Skip files under tests/regenerate/ (the sanctioned regeneration path)
        try:
            rel = py_file.relative_to(_AUDIO_BU_ROOT)
        except ValueError:
            continue
        if "regenerate" in rel.parts:
            continue
        files_scanned += 1
        text = py_file.read_text(encoding="utf-8")
        if "--regenerate-fixtures" in text:
            # A doc-mention in a comment/docstring is acceptable only if the
            # substring appears in a string-literal context that doesn't hook
            # argparse. We take the conservative reading: any occurrence is
            # an offense, since docs can name the flag via prose ("--regenerate‑fixtures"
            # with a non-hyphen) instead.
            # Exception: this very test file mentions the flag as part of its
            # own assertion machinery; skip self-reference.
            if py_file.name == "test_generation_facts.py":
                continue
            offenders.append(str(rel))
    assert not offenders, (
        f"§8.4 CI guardrail failed: --regenerate-fixtures found in test modules "
        f"under pytest discovery: {offenders!r}. Regeneration lives at "
        f"tests/regenerate/regenerate_phase2b_fixtures.py — not in the test path."
    )
    assert files_scanned > 0, "sanity: no test_*.py files scanned — vacuous pass"
    print(
        f"PASS: (g) --regenerate-fixtures absent from {files_scanned} test modules "
        f"under pytest discovery (regeneration is out-of-band per §8.4)"
    )


def main() -> None:
    test_empty_rows_yields_empty_facts()                   # (a)
    test_phase2a_fixture_projects_to_expected_facts()      # (b)
    test_warning_true_row_projects_but_gates_closed()      # (c)
    test_unknown_track_subject_ignored_not_raised()        # (d)
    test_regression_anchor_byte_hash()                     # (e)
    test_facts_import_guard()                              # (f)
    test_regenerate_flag_not_accepted_by_test_modules()    # (g)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
