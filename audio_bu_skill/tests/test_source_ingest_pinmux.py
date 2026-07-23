"""WP-SRC-A: T-SRC-A-1..4 (red before implementation).

Written test-first per PHASE3A_IMPLEMENTATION_PLAN.md §5a. These tests MUST
be red on the current HEAD (post-WP-MCP-BANNER closure at 958ec02) because
the entire ``orchestrator/source_ingest/`` package does not yet exist —
`_build_audio_topology` (target_onboarding_runner.py:611-636) does not
populate ``pinmux`` today. WP-SRC-A closes the T1 half of G-3A.7 (empty
profile source side blocks generation).

Contract these tests pin down for the implementation:

1. A pure derivation function ``derive_pinmux_from_dt(dt) -> list[PinmuxFact]``
   (or an equivalent name) exists under ``orchestrator.source_ingest.pinmux``.
   Given a DT dict carrying an I2S8 pin group, it returns a non-empty list
   whose entries carry a ``name`` in the ``gpio.i2s.*`` namespace (per §4a-1
   of the plan). The `name` is REQUIRED — a row without it closes the gate
   even if the pin/function match (see G-3A.7 R-SRC-A-1).
2. Unit-level seam: feeding ``derive_pinmux_from_dt``'s output directly
   into ``track_t1(snapshot, source=pinmux)`` (crossverify.py:416) yields
   ≥1 row keyed under ``T1.gpio.i2s.`` and ``facts.is_open("T1", subject)
   == True`` for at least one such row. This test does NOT exercise
   ``_build_audio_topology`` and does NOT prove
   ``profile.audio_topology.pinmux`` populates end-to-end — that is T-SRC-A-5.
3. Underivable pinmux (DT missing I2S8, or ambiguous) yields an explicit
   ``SOURCE_UNRESOLVED`` sentinel/marker — NEVER a silent empty list, never
   a fabricated guess. This is the §5 evidence-doctrine hard rule.
4. Determinism: two independent calls to ``derive_pinmux_from_dt`` with
   byte-identical input produce byte-identical output (sorted-key JSON).
5. End-to-end integration: after the wiring commit lands,
   ``_build_audio_topology`` (target_onboarding_runner.py:602-636) — the
   exact function that assembles ``profile.audio_topology`` on the
   ``--onboard`` path — MUST populate ``topology["pinmux"]`` as a non-empty
   list of dicts, each carrying a ``name`` in the ``gpio.i2s.*`` namespace,
   when handed a Nord-shaped analysis carrying an I2S8-bearing DT. Red on
   this commit (source_ingest exists but is not wired into
   ``_build_audio_topology``); green only after the next WP-SRC-A commit
   threads ``derive_pinmux_from_dt`` into that runner.

Failure discipline: each test guards its import in try/except so the
red-state output names the specific missing surface. Mirrors the idiom
in `tests/test_mcp_banner.py` (WP-MCP-BANNER predecessor).

Constraints on this file (per Message-2 verbatim):
  * Do NOT write ingestion code. This is the red-baseline commit.
  * Do NOT edit any code outside this test file.
  * Signoff Ajay Kumar Nandam <ajayn@qti.qualcomm.com>.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_source_ingest_pinmux``
"""

from __future__ import annotations

import json
from typing import Any


# ── Fixture builders (pure, no I/O) ──────────────────────────────────────────


def _dt_with_i2s8() -> dict[str, Any]:
    """A minimal DT fragment carrying an I2S8 pinctrl group.

    Shaped after the sa8775p Nord I2S8 pinmux (function=1, pins 147-150 per
    the confirmed Nord facts memory entry). Kept as a plain dict so this
    fixture stays parser-agnostic — the ingestion function is free to
    consume whichever DT normalisation shape the runner emits, so long as
    the ``name`` returned lands in the ``gpio.i2s.*`` namespace.
    """
    return {
        "pinctrl": {
            "i2s8_default": {
                "function": "i2s8",
                "pins": [
                    {"pin": 147, "function": 1, "role": "mclk"},
                    {"pin": 148, "function": 1, "role": "sclk"},
                    {"pin": 149, "function": 1, "role": "ws"},
                    {"pin": 150, "function": 1, "role": "data"},
                ],
            },
        },
    }


def _dt_underivable() -> dict[str, Any]:
    """A DT fragment with NO I2S pinctrl group present.

    The ingestion contract (per §5 evidence doctrine) is: underivable →
    explicit SOURCE_UNRESOLVED marker; never a silent empty list, never a
    fabricated guess.
    """
    return {"pinctrl": {}}


def _t1_snap_matching_i2s8() -> dict[str, Any]:
    """An IPCAT snapshot whose GPIO map MATCHes the I2S8 pin group above.

    Mirrors _t1_snap in test_g3a7_source_gate.py — direct authority
    (gpio_list_gpios_from_map) answers with a payload whose (pin, function,
    name) tuples align with `_dt_with_i2s8`. This lets track_t1 emit
    MATCH verdicts so `is_open` can flip True after ingestion populates
    the source side.
    """
    return {
        "tools": {
            "gpio_get_gpio_map": {"status": "ok", "payload": {"gpio_map_id": 1}},
            "gpio_list_gpios_from_map": {
                "status": "ok",
                "payload": [
                    {"number": 147, "function": 1, "name": "gpio.i2s.mclk"},
                    {"number": 148, "function": 1, "name": "gpio.i2s.sclk"},
                    {"number": 149, "function": 1, "name": "gpio.i2s.ws"},
                    {"number": 150, "function": 1, "name": "gpio.i2s.data"},
                ],
            },
        }
    }


def _open_rows_for_prefix(rows: list, prefix: str) -> list:
    """Project rows and return the subset that are is_open under `prefix`.

    Copied verbatim from tests/test_g3a7_source_gate.py so this test uses
    the same projection idiom as the committed source→gate probe.
    """
    from orchestrator.generation.facts import project_facts
    from orchestrator.generation.machine_driver import (
        _rows_with_prefix as _md_rows_with_prefix,
    )

    facts = project_facts(rows)
    return [
        r
        for r in _md_rows_with_prefix(facts, prefix)
        if facts.is_open(r.track, r.subject)
    ]


# ── T-SRC-A-1: DT with I2S8 → non-empty pinmux with gpio.i2s.* names ─────────


def test_src_a_1_pinmux_derivation_from_i2s8_dt() -> None:
    """DT fragment carrying an I2S8 pin group → non-empty pinmux whose
    entries carry a `name` in the `gpio.i2s.*` namespace.

    Fails on baseline: ``orchestrator.source_ingest`` does not exist.
    """
    try:
        from orchestrator.source_ingest.pinmux import derive_pinmux_from_dt
    except ImportError as exc:
        raise AssertionError(
            "T-SRC-A-1: expected `derive_pinmux_from_dt(dt) -> list[PinmuxFact]` "
            "in `orchestrator.source_ingest.pinmux`. The whole "
            "`orchestrator/source_ingest/` package is missing on baseline "
            "(HEAD @ 958ec02, post-WP-MCP-BANNER). This is WP-SRC-A's "
            f"primary surface to add. ImportError: {exc}"
        ) from exc

    result = derive_pinmux_from_dt(_dt_with_i2s8())

    # Non-empty is the first assertion — silent empty is exactly the
    # failure mode SOURCE_UNRESOLVED is meant to replace (see T-SRC-A-3).
    assert result, (
        "T-SRC-A-1: derive_pinmux_from_dt on a DT carrying an I2S8 pinctrl "
        "group must return a non-empty result; got "
        f"{result!r}. Silent empty on derivable input is a §5 evidence-"
        "doctrine violation — use SOURCE_UNRESOLVED for the underivable case."
    )

    # Iterable-of-facts assumption; support both `list[PinmuxFact]` and
    # `list[dict]` shapes so this test does not overconstrain the
    # implementer's dataclass-vs-dict choice.
    def _name_of(entry: Any) -> str | None:
        if hasattr(entry, "name"):
            return getattr(entry, "name", None)
        if isinstance(entry, dict):
            return entry.get("name")
        return None

    names = [_name_of(e) for e in result]
    assert all(n is not None for n in names), (
        "T-SRC-A-1: every pinmux entry must carry a `name` field (per "
        "§4a-1 of the plan and R-SRC-A-1: a row without `name` closes "
        f"the T1 gate even if pin/function match). Got names={names!r}."
    )

    gpio_i2s_names = [n for n in names if n and n.startswith("gpio.i2s.")]
    assert gpio_i2s_names, (
        "T-SRC-A-1: at least one pinmux entry must carry a `name` under "
        f"the `gpio.i2s.*` namespace (per §4a-1). Got names={names!r}. "
        "Without this namespace prefix, `track_t1` emits rows keyed "
        "under `T1.<something-else>` and the machine_driver gate "
        "(prefix scan `T1.gpio.i2s.`) stays closed."
    )
    print(
        f"PASS: T-SRC-A-1 derive_pinmux_from_dt → {len(result)} entries, "
        f"{len(gpio_i2s_names)} in gpio.i2s.* namespace"
    )


# ── T-SRC-A-2: unit seam — derive_pinmux_from_dt → track_t1 opens gate ───────


def test_src_a_2_derive_pinmux_to_track_t1_seam() -> None:
    """Unit-level seam test between ``derive_pinmux_from_dt`` and
    ``track_t1``: feeding the derivation function's output directly to
    ``track_t1(snapshot, source=pinmux)`` produces ≥1 row keyed under
    ``T1.gpio.i2s.`` AND ``facts.is_open("T1", subject) == True`` for at
    least one such row.

    Scope disclaimer (deliberate): this test does NOT exercise
    ``_build_audio_topology`` (target_onboarding_runner.py:602-636), does
    NOT run ``target_onboarding_runner``, and does NOT read
    ``profile.audio_topology.pinmux``. It proves the two functions compose
    correctly at their direct call boundary — nothing more. End-to-end
    integration (``--onboard`` populates ``profile.audio_topology.pinmux``)
    is T-SRC-A-5.

    Rationale for the two-test split: the pure ingestion contract
    (T-SRC-A-1) and the downstream gate contract (this test) can be
    satisfied without any runner wiring; wiring is a separate concern
    covered by T-SRC-A-5. Keeping this test at the seam level makes
    WP-SRC-A commit 1 (pure function) independently landable and
    independently verifiable.

    Fails on baseline for two independent reasons:
      (a) ``orchestrator.source_ingest.pinmux`` is missing entirely; and
      (b) even if we hand-authored source rows, the Nord ``profile.json``
          has ``audio_topology.pinmux=None`` — but end-to-end evidence
          for (b) lives in T-SRC-A-5, not here. See G-3A.7 for the full
          source→gate causal chain.
    """
    try:
        from orchestrator.reasoning.crossverify import track_t1
    except ImportError as exc:  # pragma: no cover — sanity
        raise AssertionError(f"T-SRC-A-2: cannot import track_t1: {exc}") from exc

    try:
        from orchestrator.source_ingest.pinmux import derive_pinmux_from_dt
    except ImportError as exc:
        raise AssertionError(
            "T-SRC-A-2: expected `derive_pinmux_from_dt` in "
            "`orchestrator.source_ingest.pinmux`. Baseline lacks the entire "
            f"source_ingest package. ImportError: {exc}"
        ) from exc

    # 1. Run ingestion on a DT that carries the I2S8 group.
    pinmux = derive_pinmux_from_dt(_dt_with_i2s8())
    assert pinmux, (
        "T-SRC-A-2: ingestion produced empty pinmux for I2S8 DT — "
        "prerequisite for the gate-open assertion below."
    )

    # 2. Adapt to track_t1's `source` shape. Both dataclass-with-to_dict
    # and raw-dict entries are supported so this test doesn't overconstrain
    # the implementer's model choice.
    def _as_entry(e: Any) -> dict[str, Any]:
        if hasattr(e, "to_dict"):
            return e.to_dict()
        if isinstance(e, dict):
            return dict(e)
        raise AssertionError(
            f"T-SRC-A-2: pinmux entry {e!r} is neither a PinmuxFact-like "
            "object (with to_dict) nor a dict — cannot feed track_t1."
        )

    source = [_as_entry(e) for e in pinmux]

    # 3. Feed to track_t1 with a matching authority snapshot; expect ≥1
    # row keyed under `T1.gpio.i2s.` that is is_open.
    rows = list(track_t1(snapshot=_t1_snap_matching_i2s8(), source=source) or [])
    assert rows, (
        "T-SRC-A-2: track_t1 returned zero rows on a populated pinmux + "
        "matching authority snapshot. Baseline short-circuit at "
        "crossverify.py:416-417 (`if not entries: return []`) should be "
        "past by now, since ingestion has just populated `entries`."
    )

    open_rows = _open_rows_for_prefix(rows, "T1.gpio.i2s.")
    assert open_rows, (
        f"T-SRC-A-2: no rows keyed under `T1.gpio.i2s.` opened the gate. "
        f"Emitted rows: {[(r.track, r.subject, r.verdict) for r in rows]!r}. "
        "This is R-SRC-A-1: the pinmux was derived but the `name` field "
        "did not render into the `gpio.i2s.*` namespace, so "
        "`is_open('T1', <subject>)` stays False."
    )
    print(
        f"PASS: T-SRC-A-2 {len(open_rows)} rows opened T1.gpio.i2s.* gate "
        f"({[r.subject for r in open_rows]!r})"
    )


# ── T-SRC-A-3: underivable pinmux → SOURCE_UNRESOLVED marker ─────────────────


def test_src_a_3_underivable_pinmux_marks_source_unresolved() -> None:
    """Underivable pinmux (no I2S pinctrl in DT) → explicit
    `SOURCE_UNRESOLVED` sentinel/marker, NEVER a silent empty list, NEVER a
    fabricated guess.

    This is the §5 evidence-doctrine hard rule as it applies to WP-SRC-A:
    the ingestion path must fail loudly and specifically, not silently
    return `[]` (which is indistinguishable from a healthy run that
    genuinely has zero pins to report).

    Fails on baseline: the whole source_ingest package is missing, and no
    SOURCE_UNRESOLVED constant exists.
    """
    try:
        from orchestrator.source_ingest.pinmux import derive_pinmux_from_dt
    except ImportError as exc:
        raise AssertionError(
            "T-SRC-A-3: expected `derive_pinmux_from_dt` in "
            "`orchestrator.source_ingest.pinmux`. Baseline lacks it. "
            f"ImportError: {exc}"
        ) from exc

    # Locate the SOURCE_UNRESOLVED sentinel. Accept either a top-level
    # constant on the source_ingest package or on the pinmux module — do
    # not overconstrain where the implementer puts it.
    sentinel: Any = None
    for modpath in (
        "orchestrator.source_ingest",
        "orchestrator.source_ingest.models",
        "orchestrator.source_ingest.pinmux",
    ):
        try:
            mod = __import__(modpath, fromlist=["SOURCE_UNRESOLVED"])
            sentinel = getattr(mod, "SOURCE_UNRESOLVED", None)
            if sentinel is not None:
                break
        except ImportError:
            continue
    assert sentinel is not None, (
        "T-SRC-A-3: expected a `SOURCE_UNRESOLVED` sentinel exported from "
        "one of `orchestrator.source_ingest`, "
        "`orchestrator.source_ingest.models`, or "
        "`orchestrator.source_ingest.pinmux`. Baseline exports none — this "
        "is the marker WP-SRC-A must introduce to satisfy the §5 evidence-"
        "doctrine 'never silent empty, never fabricated guess' rule."
    )

    result = derive_pinmux_from_dt(_dt_underivable())

    # The contract can be satisfied by (a) returning the sentinel itself,
    # (b) returning a list whose single entry equals/carries the sentinel,
    # or (c) a dict wrapping a `state`/`marker` field. Support all three
    # so the test doesn't dictate the return-shape decision.
    def _contains_sentinel(obj: Any) -> bool:
        if obj is sentinel or obj == sentinel:
            return True
        if isinstance(obj, str) and obj == "SOURCE_UNRESOLVED":
            return True
        if isinstance(obj, (list, tuple)):
            return any(_contains_sentinel(x) for x in obj)
        if isinstance(obj, dict):
            for v in obj.values():
                if _contains_sentinel(v):
                    return True
            for k in ("marker", "state", "reason", "status"):
                v = obj.get(k)
                if v is sentinel or v == sentinel or v == "SOURCE_UNRESOLVED":
                    return True
        if hasattr(obj, "marker"):
            v = getattr(obj, "marker")
            if v is sentinel or v == sentinel or v == "SOURCE_UNRESOLVED":
                return True
        return False

    # Non-empty-or-sentinel: `[]` alone is a §5 violation.
    is_silent_empty = (
        isinstance(result, (list, tuple)) and len(result) == 0
    ) or (isinstance(result, dict) and not result) or result is None
    assert not is_silent_empty, (
        "T-SRC-A-3: derive_pinmux_from_dt on an underivable DT returned a "
        f"silent empty value ({result!r}). This is the exact §5 evidence-"
        "doctrine violation SOURCE_UNRESOLVED is meant to replace. The "
        "ingestion path must fail loudly, not silently."
    )

    assert _contains_sentinel(result), (
        f"T-SRC-A-3: derive_pinmux_from_dt on an underivable DT returned "
        f"{result!r}, which does not carry the SOURCE_UNRESOLVED sentinel "
        "anywhere reachable. The marker must be a first-class value the "
        "downstream reader (track_t1 / is_open / report renderer) can "
        "recognise; a plain empty result is not acceptable."
    )
    print(f"PASS: T-SRC-A-3 underivable DT → SOURCE_UNRESOLVED marker in {type(result).__name__}")


# ── T-SRC-A-4: determinism — two runs → byte-identical pinmux ───────────────


def test_src_a_4_determinism_across_two_runs() -> None:
    """Two independent calls to `derive_pinmux_from_dt` with byte-identical
    input MUST produce byte-identical output under
    `json.dumps(sort_keys=True)`.

    This mirrors the Phase-2A/2B determinism doctrine (see
    `crossverify_collector.py:401` — snapshot is JSON-serialisability-
    checked at construction, and every result_digest is
    sha256(canonical-json)). Ingestion inherits the same discipline; a
    non-deterministic derivation would leak into every downstream
    result_digest and break replay integrity.

    Fails on baseline: the module doesn't exist. When the module IS
    implemented, this test regression-guards against ordering leaks
    (dict-insertion-dependent iteration, non-canonical timestamp
    interpolation, random-order set iteration, etc.).
    """
    try:
        from orchestrator.source_ingest.pinmux import derive_pinmux_from_dt
    except ImportError as exc:
        raise AssertionError(
            "T-SRC-A-4: expected `derive_pinmux_from_dt` in "
            "`orchestrator.source_ingest.pinmux`. Baseline lacks it. "
            f"ImportError: {exc}"
        ) from exc

    # Two independent inputs, structurally identical. If the implementer's
    # function mutates its argument, this catches it too.
    dt_1 = _dt_with_i2s8()
    dt_2 = _dt_with_i2s8()

    result_1 = derive_pinmux_from_dt(dt_1)
    result_2 = derive_pinmux_from_dt(dt_2)

    def _canonical(obj: Any) -> str:
        """Reduce PinmuxFact / list / dict to sorted-key canonical JSON.

        Mirrors _canonical_json_bytes in crossverify_collector.py:115.
        """
        def _reduce(o: Any) -> Any:
            if hasattr(o, "to_dict"):
                return _reduce(o.to_dict())
            if isinstance(o, (list, tuple)):
                return [_reduce(x) for x in o]
            if isinstance(o, dict):
                return {k: _reduce(v) for k, v in o.items()}
            return o

        return json.dumps(_reduce(obj), sort_keys=True, ensure_ascii=True, default=str)

    canon_1 = _canonical(result_1)
    canon_2 = _canonical(result_2)
    assert canon_1 == canon_2, (
        "T-SRC-A-4: two runs of derive_pinmux_from_dt on equivalent input "
        "produced different canonical JSON output. This breaks the Phase-"
        "2A/2B determinism doctrine — every downstream result_digest is "
        "sha256(canonical-json), so non-determinism here poisons every "
        "artifact hash. First run:\n"
        f"  {canon_1!r}\n"
        f"Second run:\n"
        f"  {canon_2!r}"
    )
    print(f"PASS: T-SRC-A-4 determinism holds across two runs ({len(canon_1)} chars)")


# ── T-SRC-A-5: end-to-end integration — _build_audio_topology populates pinmux ─


def test_src_a_5_build_audio_topology_populates_pinmux() -> None:
    """End-to-end integration: after WP-SRC-A wiring lands,
    ``_build_audio_topology`` (target_onboarding_runner.py:602-636) —
    the exact assembler used by ``--onboard`` to build
    ``profile.audio_topology`` — MUST populate ``topology["pinmux"]`` as
    a non-empty list of dicts, each carrying a ``name`` field starting
    with ``gpio.i2s.``, when handed a Nord-shaped analysis whose DT
    carries an I2S8 pinctrl group.

    Why this test exists separately from T-SRC-A-2: T-SRC-A-2 proves
    ``derive_pinmux_from_dt`` and ``track_t1`` compose at their direct
    call boundary. It does NOT prove the runner path threads ingestion
    into ``profile.audio_topology.pinmux``. Without this test, a WP-SRC-A
    wiring commit could add wiring code, pass T-SRC-A-1..4, and still
    leave ``profile.audio_topology.pinmux=None`` on real
    ``--onboard nord-iq10``. This test is the gate that catches that.

    Expected state on the current commit (WP-SRC-A commit 1 — pure
    ingestion function, no runner wiring): RED. ``_build_audio_topology``
    at target_onboarding_runner.py:602-636 does not add ``pinmux`` to
    the returned topology dict — grep confirms:
    ``grep -n '"pinmux"' orchestrator/runners/target_onboarding_runner.py``
    yields zero hits.

    Expected state after the next WP-SRC-A wiring commit: GREEN. The
    wiring commit MUST derive pinmux via ``derive_pinmux_from_dt`` from
    the analysis-carried DT and add the result under
    ``topology["pinmux"]`` in ``_build_audio_topology``.

    Fixture shape rationale: passes a Nord-shaped ``analysis`` dict
    carrying a ``dt`` sub-field with the same I2S8 pinctrl group as
    ``_dt_with_i2s8()``. The other ``_build_audio_topology`` parameters
    (``pm``, ``power_model_hint``, ``pin_crosschecks``, ``ipcat_findings``)
    are handed minimal-but-valid stubs — this test is scoped to the
    ``pinmux`` field, not to the rest of the audio_topology assembly.
    """
    try:
        from orchestrator.runners.target_onboarding_runner import (
            _build_audio_topology,
        )
    except ImportError as exc:  # pragma: no cover — sanity
        raise AssertionError(
            f"T-SRC-A-5: cannot import _build_audio_topology from "
            f"orchestrator.runners.target_onboarding_runner: {exc}"
        ) from exc

    # A Nord-shaped analysis dict whose ``dt`` sub-field carries the same
    # I2S8 pinctrl group as _dt_with_i2s8(). The wiring commit must read
    # the DT from wherever the runner surfaces it in `analysis` and hand
    # it to derive_pinmux_from_dt. Kept parser-agnostic on purpose.
    analysis: dict[str, Any] = {
        "codecs": [],
        "amplifiers": [],
        "mics": [],
        "speakers": [],
        "soundwire": {},
        "audio_stack": {},
        "missing_evidence": [],
        # DT carried on the analysis dict for the runner to consume.
        # Wiring commit is free to relocate this field (e.g. under a
        # separate `source` sub-dict); if it does, this test's fixture
        # updates accordingly. What must not change: the assertion that
        # topology["pinmux"] ends up non-empty with gpio.i2s.* names.
        "dt": _dt_with_i2s8(),
    }
    pm: dict[str, Any] = {"power_model_source": "NEEDS_REVIEW"}
    power_model_hint: dict[str, Any] = {}
    pin_crosschecks: list[dict[str, Any]] = []

    topology = _build_audio_topology(
        analysis=analysis,
        pm=pm,
        power_model_hint=power_model_hint,
        pin_crosschecks=pin_crosschecks,
        ipcat_findings=None,
    )

    assert isinstance(topology, dict), (
        f"T-SRC-A-5: _build_audio_topology returned {type(topology).__name__}, "
        "expected dict."
    )

    pinmux = topology.get("pinmux")
    assert pinmux is not None, (
        "T-SRC-A-5: topology['pinmux'] is None (or missing). "
        "_build_audio_topology at target_onboarding_runner.py:602-636 does "
        "not thread derive_pinmux_from_dt into the returned topology dict. "
        "This is the wiring gap that the next WP-SRC-A commit MUST close: "
        "call derive_pinmux_from_dt on the analysis-carried DT and assign "
        "the result under topology['pinmux'] (or SOURCE_UNRESOLVED marker "
        "when the DT lacks I2S). Until then, --onboard nord-iq10 leaves "
        "profile.audio_topology.pinmux=None and the machine_driver gate "
        "(prefix scan T1.gpio.i2s.*) stays closed regardless of MCP state."
    )
    assert isinstance(pinmux, list), (
        f"T-SRC-A-5: topology['pinmux'] is {type(pinmux).__name__}, expected "
        f"list. Value: {pinmux!r}."
    )
    assert pinmux, (
        "T-SRC-A-5: topology['pinmux'] is empty list. Silent empty on a DT "
        "carrying an I2S8 group is a §5 evidence-doctrine violation — the "
        "wiring commit must either populate pinmux from the DT or emit "
        "SOURCE_UNRESOLVED, never a silent []."
    )

    # Every entry must be a dict shape (the profile is JSON-serialised, so
    # dataclass-style objects need to reduce to dicts before storage).
    for i, entry in enumerate(pinmux):
        assert isinstance(entry, dict), (
            f"T-SRC-A-5: topology['pinmux'][{i}] is {type(entry).__name__}, "
            f"expected dict (profile.audio_topology is JSON-serialised at "
            f"the runner boundary). Value: {entry!r}."
        )
        name = entry.get("name")
        assert isinstance(name, str) and name.startswith("gpio.i2s."), (
            f"T-SRC-A-5: topology['pinmux'][{i}]['name'] = {name!r}. Every "
            "entry must carry a `name` field under the gpio.i2s.* namespace "
            "(per §4a-1 / R-SRC-A-1). Without this, machine_driver's prefix "
            "scan (T1.gpio.i2s.*) stays closed even after wiring lands."
        )

    print(
        f"PASS: T-SRC-A-5 _build_audio_topology → topology['pinmux'] has "
        f"{len(pinmux)} entries, all under gpio.i2s.* namespace"
    )


# ── Runner ───────────────────────────────────────────────────────────────────


def main() -> None:
    """Run each T-SRC-A-* independently so the red state of every test is
    visible in a single invocation. Aggregates AssertionError per test and
    exits non-zero if any failed. Mirrors tests/test_mcp_banner.py:279."""
    import sys

    tests = [
        ("T-SRC-A-1", test_src_a_1_pinmux_derivation_from_i2s8_dt),
        ("T-SRC-A-2", test_src_a_2_derive_pinmux_to_track_t1_seam),
        ("T-SRC-A-3", test_src_a_3_underivable_pinmux_marks_source_unresolved),
        ("T-SRC-A-4", test_src_a_4_determinism_across_two_runs),
        ("T-SRC-A-5", test_src_a_5_build_audio_topology_populates_pinmux),
    ]
    failures: list[tuple[str, AssertionError]] = []
    for label, fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failures.append((label, exc))
            print(f"FAIL: {label}: {exc}")

    if failures:
        print(
            f"\n{len(failures)}/{len(tests)} tests FAILED — see per-test "
            "FAIL lines above."
        )
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
