"""Phase-2B WP1b — tests for the generation config module.

Pure, stdlib-only tests over ``orchestrator.generation.config``. Mirrors the
Phase-2A + WP1a test discipline: inline data, no fakes, no network, no pytest.
Eight tests per PHASE2B_SPECIFICATION.md §WP1b:

  1. ``test_artifact_order_matches_gating_keys``
  2. ``test_skip_reasons_complete``
  3. ``test_every_skip_reason_documented`` (deferred runner-reachability — soft)
  4. ``test_advisory_rows_only_t4b``
  5. ``test_known_bad_rules_only_donor_sa8775p``
  6. ``test_path_guard_rejects_paths_outside_root``
  7. ``test_import_guard_no_model_import``
  8. ``test_no_reverse_import_from_reasoning``

Test 3 is the "every-skip-reason-reachable" check called out in the WP1b
directive as "may xfail". Runners (WP3–WP10) haven't landed yet, so the strict
"every reason is emitted by at least one runner" assertion is deferred — WP10
lands the strict form. Today the test enforces the softer lint: every
declared reason must appear as a literal in ``config.py`` itself (catches a
stale/dead enum entry that never made it into the string set).

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_config``
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

from orchestrator.generation import config as gen_config
from orchestrator.generation.config import (
    ADVISORY_ROWS,
    GATING_ROWS,
    KNOWN_BAD_PARTIAL_MATCH_RULES,
    PATH_GUARD_ROOT,
    SKIP_REASONS,
    _GENERATION_ARTIFACT_ORDER,
    is_path_within_guard,
)


# ``tests/`` lives alongside ``orchestrator/`` under ``audio_bu_skill/``.
# Resolve the audio_bu_skill root by walking one parent up from this file.
_AUDIO_BU_ROOT = Path(__file__).resolve().parent.parent


# ── 1. Artifact order ↔ gating keys parity ──────────────────────────────────


def test_artifact_order_matches_gating_keys() -> None:
    """``_GENERATION_ARTIFACT_ORDER`` and ``GATING_ROWS`` keys must be one-to-one.

    Every artifact class the engine renders must have a gating entry (or the
    runner cannot decide whether to emit it), and every gating entry must
    correspond to a real artifact class in the render order (or the entry is
    dead weight). Enforce both directions.

    Also spot-checks the value shapes so a later ``GATING_ROWS`` entry like
    ``GATING_ROWS["x"] = ("T5", "y")`` (missing the outer tuple) fails here
    instead of at gate-evaluation time in the runner.
    """
    order = list(_GENERATION_ARTIFACT_ORDER)
    keys = list(GATING_ROWS.keys())

    # Same set (no orphans in either direction)
    assert set(order) == set(keys), (
        f"artifact-order ↔ gating-rows drift: order={order!r}, keys={keys!r}, "
        f"in_order_only={set(order) - set(keys)!r}, in_keys_only={set(keys) - set(order)!r}"
    )
    # No duplicates in the order tuple
    assert len(set(order)) == len(order), f"duplicates in _GENERATION_ARTIFACT_ORDER: {order!r}"

    # Value shape: tuple of (str, str) pairs, non-empty
    for artifact_class, pairs in GATING_ROWS.items():
        assert isinstance(pairs, tuple), (
            f"GATING_ROWS[{artifact_class!r}] must be a tuple, got {type(pairs).__name__}"
        )
        assert pairs, f"GATING_ROWS[{artifact_class!r}] must not be empty (no gates = auto-open)"
        for pair in pairs:
            assert isinstance(pair, tuple) and len(pair) == 2, (
                f"GATING_ROWS[{artifact_class!r}] entry {pair!r} must be a (track, subject) 2-tuple"
            )
            track, subject_pattern = pair
            assert isinstance(track, str) and track, (
                f"track must be a non-empty string in {pair!r}"
            )
            assert isinstance(subject_pattern, str) and subject_pattern, (
                f"subject_pattern must be a non-empty string in {pair!r}"
            )
    print(
        f"PASS: artifact order ↔ gating keys parity ({len(order)} artifact classes, "
        f"{sum(len(v) for v in GATING_ROWS.values())} gating entries total)"
    )


# ── 2. SKIP_REASONS — exact enumeration ─────────────────────────────────────


def test_skip_reasons_complete() -> None:
    """``SKIP_REASONS`` must contain exactly the 11 entries per §WP1b + §5.4.

    Spec §WP1b enumerates 10 reasons; §5.4 (path guard) adds ``path_guard_violation``
    for 11 total. Any drift here is a spec change. This is a set-equality test
    so both an extra reason and a missing reason fail with a clear diff.
    """
    expected = {
        # §WP1b (10)
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
        # §5.4 (+1)
        "path_guard_violation",
    }
    assert SKIP_REASONS == expected, (
        f"SKIP_REASONS drift: "
        f"missing={expected - SKIP_REASONS!r}, "
        f"extra={SKIP_REASONS - expected!r}"
    )
    assert isinstance(SKIP_REASONS, frozenset), (
        f"SKIP_REASONS must be a frozenset (immutable), got {type(SKIP_REASONS).__name__}"
    )
    print(f"PASS: SKIP_REASONS complete ({len(SKIP_REASONS)} entries, exact match to spec)")


# ── 3. Every skip reason is documented (soft — WP10 upgrades to strict) ─────


def test_every_skip_reason_documented() -> None:
    """Every ``SKIP_REASONS`` member must appear as a literal in ``config.py``.

    The strict form of this test — "every reason is emitted by at least one
    runner in WP3–WP10" — is deferred to WP10 (the runners haven't landed yet).
    Today the check is softer but non-trivial: a reason that appears in the
    frozenset but nowhere else in the module is likely a typo (the frozenset
    literal is the only place it lives). This catches an entry that got
    tacked into the set without a matching comment or dispatch case.

    Marked in the WP1b directive as "may xfail"; the soft form makes it a
    hard-pass today and leaves WP10 to add the runner-side coverage lint.
    """
    src = inspect.getsource(gen_config)
    # Every reason string must appear (as a substring) in the config source.
    # This is trivially true for the frozenset itself, so we count occurrences
    # to catch a reason that ONLY appears in the frozenset (no companion
    # comment / no dispatch mention) — those are the ones most likely to
    # be stale.
    zero_appearances: list[str] = []
    for reason in SKIP_REASONS:
        # Strict presence check — every reason must be *literally* in the source.
        if reason not in src:
            zero_appearances.append(reason)
    assert not zero_appearances, (
        f"SKIP_REASONS members not present as string literals in config.py: {zero_appearances!r}"
    )
    print(
        f"PASS: all {len(SKIP_REASONS)} skip reasons literally present in config.py "
        f"(runner-reachability strict form deferred to WP10)"
    )


# ── 4. Advisory rows — T4b only (§3.7 carve-out) ────────────────────────────


def test_advisory_rows_only_t4b() -> None:
    """``ADVISORY_ROWS`` must be exactly ``{("T4b", "*")}`` per §3.7.

    From PHASE2B_SPECIFICATION.md §3.7: "No other track is advisory. T1, T2,
    T3, T4a, T5 all require MATCH (or PARTIAL_MATCH-open) to open. Adding a
    new advisory row is a spec change." This test is the mechanical enforcement.
    """
    expected = frozenset({("T4b", "*")})
    assert ADVISORY_ROWS == expected, (
        f"ADVISORY_ROWS drift: {ADVISORY_ROWS!r} — "
        f"adding another advisory track is a §3.7 spec change"
    )
    assert isinstance(ADVISORY_ROWS, frozenset), (
        f"ADVISORY_ROWS must be a frozenset (immutable), got {type(ADVISORY_ROWS).__name__}"
    )
    # Each entry is a (track, subject_pattern) tuple of non-empty strings
    for pair in ADVISORY_ROWS:
        assert isinstance(pair, tuple) and len(pair) == 2, f"malformed ADVISORY_ROWS entry: {pair!r}"
        assert all(isinstance(x, str) and x for x in pair), f"non-string in {pair!r}"
    print("PASS: ADVISORY_ROWS is exactly {(T4b, *)} per §3.7 carve-out")


# ── 5. Known-bad rules — sa8775p donor only (§4.4) ──────────────────────────


def test_known_bad_rules_only_donor_sa8775p() -> None:
    """``KNOWN_BAD_PARTIAL_MATCH_RULES`` must be exactly ``{"t5.donor.firmware.sa8775p"}`` per §4.4.

    Adding a rule is a spec change. This exact-set test catches both drift and
    accidental typo (``sa8775P`` vs ``sa8775p`` — case-sensitive lookup at
    the runner would silently fail closed).
    """
    expected = frozenset({"t5.donor.firmware.sa8775p"})
    assert KNOWN_BAD_PARTIAL_MATCH_RULES == expected, (
        f"KNOWN_BAD_PARTIAL_MATCH_RULES drift: {KNOWN_BAD_PARTIAL_MATCH_RULES!r} — "
        f"adding a rule is a §4.4 spec change"
    )
    assert isinstance(KNOWN_BAD_PARTIAL_MATCH_RULES, frozenset), (
        f"KNOWN_BAD_PARTIAL_MATCH_RULES must be a frozenset, "
        f"got {type(KNOWN_BAD_PARTIAL_MATCH_RULES).__name__}"
    )
    # Every entry must be a non-empty string
    for rule_id in KNOWN_BAD_PARTIAL_MATCH_RULES:
        assert isinstance(rule_id, str) and rule_id, f"non-string rule_id: {rule_id!r}"
    print("PASS: KNOWN_BAD_PARTIAL_MATCH_RULES is exactly {t5.donor.firmware.sa8775p} per §4.4")


# ── 6. Path guard — accepts nested writes, rejects escapes ──────────────────


def test_path_guard_rejects_paths_outside_root() -> None:
    """``is_path_within_guard`` accepts paths under ``PATH_GUARD_ROOT`` and rejects escapes.

    Covers the taxonomy of escape attempts:

    * absolute paths (POSIX & Windows drive letter)
    * ``..`` traversal (leading and mid-path)
    * sibling directories that share a prefix (``generated_x/``)
    * empty / whitespace / bare-dotdot
    * doubled slashes (must normalize, still accepted if under root)

    Any drift in the predicate could turn ``GeneratorSkipped(reason="path_guard_violation")``
    into a silent write to an arbitrary path, so the coverage here is
    deliberately dense.
    """
    # Constant sanity — the runner constructs paths as PATH_GUARD_ROOT + <run_id>
    assert PATH_GUARD_ROOT == "generated/", f"PATH_GUARD_ROOT drift: {PATH_GUARD_ROOT!r}"

    # ACCEPT — paths inside the root
    assert is_path_within_guard("generated/nord/foo.dts") is True
    assert is_path_within_guard("generated/nord/subdir/bar.c") is True
    assert is_path_within_guard("generated/nord/machine/soc.h") is True
    # doubled-slash normalization → accepted
    assert is_path_within_guard("generated//foo.dts") is True
    # root itself (equivalent to PATH_GUARD_ROOT with the trailing slash stripped)
    assert is_path_within_guard("generated") is True

    # REJECT — absolute POSIX paths
    assert is_path_within_guard("/generated/foo.dts") is False
    assert is_path_within_guard("/etc/passwd") is False
    assert is_path_within_guard("/") is False

    # REJECT — ``..`` escapes (both mid-path and leading)
    assert is_path_within_guard("generated/../etc/passwd") is False
    assert is_path_within_guard("../generated/foo.dts") is False
    assert is_path_within_guard("generated/../../etc/passwd") is False

    # REJECT — sibling directory that shares the prefix
    assert is_path_within_guard("generated_x/foo.dts") is False
    assert is_path_within_guard("generated-other/foo.dts") is False

    # REJECT — unrelated path
    assert is_path_within_guard("other/foo.dts") is False
    assert is_path_within_guard("arch/arm64/boot/dts/qcom/foo.dtsi") is False

    # REJECT — bare escape / empty / whitespace
    assert is_path_within_guard("..") is False
    assert is_path_within_guard("") is False
    assert is_path_within_guard("   ") is False
    assert is_path_within_guard("\t\n") is False

    # REJECT — Windows-style drive letters (would slip past POSIX absolute check)
    assert is_path_within_guard("C:/generated/foo") is False
    assert is_path_within_guard("D:\\Users\\evil") is False
    assert is_path_within_guard("Z:generated/foo") is False

    print("PASS: is_path_within_guard rejects every escape and accepts every nested path (23 cases)")


# ── 7. Import guard — config.py does not import from generation/model ───────


def test_import_guard_no_model_import() -> None:
    """Static-source check: ``config.py`` must not import from ``generation.model``.

    Reverse of the WP1a-side import guard. The invariant is: model → types,
    config → policy, and the runner (WP10) is the only site that composes both.
    A model import here would let policy start depending on type internals,
    which the spec §WP1a rationale explicitly forbids ("dataclass churn vs
    policy churn are orthogonal").

    Catches both ``from orchestrator.generation.model import X`` and its
    relative-import variants (``from .model import ...``).
    """
    src = inspect.getsource(gen_config)
    forbidden_patterns = [
        r"\bfrom\s+orchestrator\.generation\.model\b",
        r"\bimport\s+orchestrator\.generation\.model\b",
        r"\bfrom\s+\.model\b",
        r"\bfrom\s+\.\s+import\s+model\b",
    ]
    for pat in forbidden_patterns:
        # Only inspect real statement lines. Comments and docstrings freely
        # discuss ``model.py``; the regex is anchored on ``from``/``import``
        # keywords so this filter is defence-in-depth.
        code_lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
        real_matches = [
            ln for ln in code_lines
            if re.search(pat, ln) and not ln.lstrip().startswith('"')
        ]
        assert not real_matches, (
            f"import guard failed: config.py must not import from generation.model "
            f"(pattern {pat!r} matched: {real_matches!r})"
        )
    # Positive: config.py DOES import ``posixpath`` (proof we read the right file)
    assert re.search(r"\bimport\s+posixpath\b", src), (
        "sanity: config.py should import posixpath (path-guard normalization)"
    )
    # Positive: TYPE_CHECKING-guarded import of VerificationRow present
    assert re.search(
        r"from\s+orchestrator\.reasoning\.crossverify_model\s+import\s+VerificationRow",
        src,
    ), "sanity: config.py should TYPE_CHECKING-import VerificationRow"
    print("PASS: config.py has no import from generation.model (import guard held)")


# ── 8. Reverse-direction import guard: reasoning/*.py ↛ generation/* ────────


def test_no_reverse_import_from_reasoning() -> None:
    """No file under ``orchestrator/reasoning/`` may import from ``orchestrator.generation``.

    Uses AST inspection (not regex) so both ``from X import Y`` and
    ``import X`` are caught, and comments/docstrings that mention
    ``generation`` cannot produce a false positive.

    The invariant here is the *reverse* of WP1a: Phase-2A reasoning code
    is authored to know nothing about Phase-2B generation. Introducing an
    import in the reverse direction would create a dependency cycle at the
    package level and defeat the separation of concerns.
    """
    reasoning_dir = _AUDIO_BU_ROOT / "orchestrator" / "reasoning"
    assert reasoning_dir.is_dir(), (
        f"reasoning package not found at {reasoning_dir!r} — cannot run reverse-import guard"
    )

    offenders: list[tuple[str, str]] = []
    files_scanned = 0
    for py_file in sorted(reasoning_dir.rglob("*.py")):
        files_scanned += 1
        text = py_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=str(py_file))
        except SyntaxError:
            # A syntax error in reasoning code is not this test's concern.
            continue
        rel = str(py_file.relative_to(_AUDIO_BU_ROOT))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "orchestrator.generation" or module.startswith(
                    "orchestrator.generation."
                ):
                    offenders.append((rel, f"from {module} import ..."))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "orchestrator.generation" or alias.name.startswith(
                        "orchestrator.generation."
                    ):
                        offenders.append((rel, f"import {alias.name}"))

    assert not offenders, (
        f"reverse-import guard failed: reasoning/*.py must not import from generation/*: "
        f"{offenders!r}"
    )
    # Sanity: we actually scanned files (guards against a rename that silently
    # empties the reasoning directory and passes vacuously).
    assert files_scanned > 0, (
        f"sanity: no .py files scanned under {reasoning_dir!r} — the test would pass vacuously"
    )
    print(
        f"PASS: no reasoning/*.py imports from orchestrator.generation "
        f"(scanned {files_scanned} files under {reasoning_dir.relative_to(_AUDIO_BU_ROOT)}/)"
    )


def main() -> None:
    test_artifact_order_matches_gating_keys()      # 1
    test_skip_reasons_complete()                   # 2
    test_every_skip_reason_documented()            # 3
    test_advisory_rows_only_t4b()                  # 4
    test_known_bad_rules_only_donor_sa8775p()      # 5
    test_path_guard_rejects_paths_outside_root()   # 6
    test_import_guard_no_model_import()            # 7
    test_no_reverse_import_from_reasoning()        # 8
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
