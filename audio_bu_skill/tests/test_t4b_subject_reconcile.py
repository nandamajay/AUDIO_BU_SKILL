# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Qualcomm Technologies, Inc. and/or its subsidiaries.
"""WP-SRC-B3 — T4b producer/consumer subject reconcile (closes G-3A.12).

RED BASELINE (test-first per PHASE3A_IMPLEMENTATION_PLAN.md §5a). These
tests encode the *contract* the green commit must satisfy; every one is
expected to FAIL on a clean checkout, each with a named ``AssertionError``
that identifies the missing production surface (no silent skips).

The defect (G-3A.12)
--------------------
``_t4b_row`` (``orchestrator/reasoning/crossverify.py:2167``) emits::

    subject = f"{codec}<->{controller}"

so ``project_facts`` (``orchestrator/generation/facts.py:110``) keys the row
``f"T4b.{subject}"`` → ``T4b.ti,pcm1681<->playback DAC (8-ch)...``. Both
generators gate on the literal prefix ``"T4b.codec."``
(``machine_driver.py:240`` / ``codec_stub.py:230`` via ``_rows_with_prefix``),
so ``startswith("T4b.codec.")`` is False for the arrow form: the LIVE producer
can never open the T4b advisory gate. Only hand-authored fixtures
(``tests/fixtures/phase2b/nord_trusted_facts.json:117,132,137,152``) carry the
gate-shaped ``T4b.codec.<part>`` keys.

The reconcile (Option 1, producer-side, normalization rule (b))
---------------------------------------------------------------
``_t4b_row`` must emit ``subject = f"codec.{_t4b_norm_part(codec)}"`` where
``_t4b_norm_part`` strips a leading ``vendor,`` compatible prefix and
lowercases::

    ti,pcm1681   -> pcm1681
    adi,adau1979 -> adau1979
    PCM1681      -> pcm1681   (no comma -> lowercase only)

This aligns the live producer with the gate prefix AND the existing authority
fixtures (which already speak ``codec.<part>``). The bounded consumer fixups
are the two — and only two — sites that carry the ``<->`` form:

  * site 7 — ``tests/test_crossverify_t4.py`` byte-equality subject assertions
  * site 8 — rendered report display rows (``targets/*/onboarding_report.md``,
    ``tests/fixtures/phase2b/pre_wp10_baseline_report.md``)

Note on the integration keystone (T-SRC-B3-2)
---------------------------------------------
The T4b gate is NOT ``TrustedFacts.is_open`` — every T4b row is
``NOT_CROSS_CHECKABLE`` and ``is_open`` opens only for ``MATCH`` /
``PARTIAL_MATCH`` (``model.py:46``). The advisory-open carve-out lives at the
generator layer: ``_rows_with_prefix(facts, "T4b.codec.")`` +
``_t4b_advisory_open`` (``machine_driver.py:240,397``). T-SRC-B3-2 therefore
exercises that real generator gate, not ``is_open`` — which would be red both
before and after the fix and so is not a valid green target.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: A real-shape Nord IQ-10 codec binding, post-alias-map. The ``part``/``role``
#: -> ``codec``/``controller`` alias mapping happens upstream in
#: ``orchestrator/main.py:1073`` (``_t4b_apply_alias_mapping``); ``track_t4b``
#: consumes the mapped ``codec``/``controller`` keys. ``codec`` is the
#: vendor-prefixed compatible exactly as it appears in the live profile
#: (``targets/nord-iq10/profile.json:94``).
_NORD_BINDING = {
    "codec": "ti,pcm1681",
    "controller": (
        "playback DAC (8-ch line-level) proposed on i2c18 (QUP2_SE4), "
        "driven from LPASS I2S8/TDM"
    ),
}


class T4bSubjectReconcileRedBaseline(unittest.TestCase):
    """WP-SRC-B3 red baseline — producer emits ``codec.<part>``, gate opens."""

    # ── T-SRC-B3-1: producer emits dot-prefix, vendor-stripped subject ──────
    def test_t4b_row_emits_codec_dot_part_subject(self) -> None:
        """T-SRC-B3-1: ``_t4b_row`` subject == ``codec.<part>`` (not ``<->``).

        RED today: the producer emits ``ti,pcm1681<->{controller}``.
        """
        try:
            from orchestrator.reasoning.crossverify import _t4b_row
        except ImportError as exc:  # pragma: no cover - guard
            raise AssertionError(
                "T-SRC-B3-1: prerequisite import of `_t4b_row` from "
                "`orchestrator.reasoning.crossverify` failed; the producer "
                f"must exist to reconcile its subject. ImportError: {exc}"
            ) from exc

        row = _t4b_row(dict(_NORD_BINDING))
        if row.subject != "codec.pcm1681":
            raise AssertionError(
                "T-SRC-B3-1: `_t4b_row` must emit the gate-shaped subject "
                "`codec.pcm1681` (dot-prefix, vendor `ti,` stripped, "
                f"lowercased) for codec `ti,pcm1681`. Got {row.subject!r} "
                "— the `<->` arrow form can never open the `T4b.codec.` gate "
                "(G-3A.12)."
            )

    # ── T-SRC-B3-2: generator T4b gate is reachable end-to-end ──────────────
    def test_t4b_gate_reachable_through_production_seam(self) -> None:
        """T-SRC-B3-2 (keystone): track_t4b -> project_facts -> generator gate.

        Exercises the REAL T4b gate (`_rows_with_prefix("T4b.codec.")` +
        `_t4b_advisory_open`), not `is_open` (which never opens an NCC row).

        RED today: the projected key is `T4b.ti,pcm1681<->...`, so the
        `T4b.codec.` prefix scan finds nothing and the gate is unreachable.
        """
        try:
            from orchestrator.reasoning.crossverify import track_t4b
            from orchestrator.generation.facts import project_facts
            from orchestrator.generation.machine_driver import (
                _rows_with_prefix,
                _t4b_advisory_open,
            )
        except ImportError as exc:  # pragma: no cover - guard
            raise AssertionError(
                "T-SRC-B3-2: prerequisite import of the production seam "
                "(`track_t4b` / `project_facts` / `_rows_with_prefix` / "
                "`_t4b_advisory_open`) failed; the generator T4b gate must "
                f"exist to be exercised. ImportError: {exc}"
            ) from exc

        # snapshot is API-parity only — T4b reads neither snapshot nor kb.
        rows = track_t4b(snapshot={}, source=[dict(_NORD_BINDING)], kb=None)
        facts = project_facts(list(rows))
        keys = sorted(facts.rows_by_track_subject)

        codec_rows = _rows_with_prefix(facts, "T4b.codec.")
        advisory_open = [r for r in codec_rows if _t4b_advisory_open(r)]
        if not advisory_open:
            raise AssertionError(
                "T-SRC-B3-2: a real-shape codec binding cross-verified "
                "through `track_t4b -> project_facts` must leave >=1 "
                "advisory-open row under the `T4b.codec.` gate prefix so the "
                "machine_driver / codec_stub generators can reach it. Found "
                f"none. Projected keys: {keys!r} (the `<->` arrow subject "
                "fails the `T4b.codec.` prefix scan — G-3A.12)."
            )

    # ── T-SRC-B3-3: normalization contract (rule (b)) ───────────────────────
    def test_t4b_norm_part_rule_b_strip_vendor_then_lowercase(self) -> None:
        """T-SRC-B3-3: `_t4b_norm_part` = strip `^[^,]*,` then lowercase.

        RED today: no `_t4b_norm_part` helper exists.
        """
        try:
            from orchestrator.reasoning.crossverify import _t4b_norm_part
        except ImportError as exc:  # pragma: no cover - guard
            raise AssertionError(
                "T-SRC-B3-3: prerequisite import of `_t4b_norm_part` from "
                "`orchestrator.reasoning.crossverify` failed; the "
                "normalization helper (rule (b): strip a leading `vendor,` "
                f"prefix, then lowercase) must exist. ImportError: {exc}"
            ) from exc

        cases = {
            "ti,pcm1681": "pcm1681",      # vendor prefix stripped
            "adi,adau1979": "adau1979",   # vendor prefix stripped
            "PCM1681": "pcm1681",         # no comma -> lowercase only
        }
        for raw, expected in cases.items():
            got = _t4b_norm_part(raw)
            if got != expected:
                raise AssertionError(
                    f"T-SRC-B3-3: `_t4b_norm_part({raw!r})` must be "
                    f"{expected!r} under rule (b) [strip `^[^,]*,` then "
                    f"lowercase]. Got {got!r}. (A `{raw!r}` that keeps its "
                    "vendor prefix or original case would not match the "
                    "`codec.<part>` gate/fixture convention.)"
                )
        # Rule (b) is comma-gated, not "take last token" (rule (a)): a
        # comma-free value must be lowercased WHOLE, never split on spaces.
        expected_b = re.sub(r"^[^,]*,", "", "PCM1681").lower()
        if _t4b_norm_part("PCM1681") != expected_b:
            raise AssertionError(
                "T-SRC-B3-3: rule (b) must be comma-gated — a comma-free "
                "value is lowercased whole (no space-splitting). This "
                "distinguishes rule (b) from rule (a) [take last token]."
            )

    # ── T-SRC-B3-4: blast-radius pin — the two <-> consumers must change ────
    def test_blast_radius_consumers_updated_to_codec_dot_part(self) -> None:
        """T-SRC-B3-4: sites 7 (byte-equality test) and 8 (report display)
        no longer carry the T4b `<->` form; site 7 speaks `codec.<part>`.

        RED today: both still carry the arrow form. This pin forces the green
        commit to land the bounded consumer fixups alongside the producer
        change (repo artifacts, not user-provided input — reading permitted).
        """
        # ── site 7: test_crossverify_t4.py byte-equality subject assertions ─
        site7 = _REPO_ROOT / "tests" / "test_crossverify_t4.py"
        text7 = site7.read_text(encoding="utf-8")
        if "codec.pcm1681" not in text7:
            raise AssertionError(
                "T-SRC-B3-4 (site 7): tests/test_crossverify_t4.py must be "
                "updated so its T4b subject byte-equality assertions use the "
                "reconciled `codec.<part>` form (e.g. `codec.pcm1681`). None "
                "found — the file still pins the `<->` arrow subject that "
                "the green producer no longer emits."
            )

        # ── site 8: rendered report display rows ────────────────────────────
        site8_files = [
            _REPO_ROOT / "targets" / "nord-iq10" / "onboarding_report.md",
            _REPO_ROOT / "targets" / "eliza" / "onboarding_report.md",
            _REPO_ROOT / "tests" / "fixtures" / "phase2b"
            / "pre_wp10_baseline_report.md",
        ]
        offenders: list[str] = []
        for path in site8_files:
            for i, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if "| T4b |" in line and "<->" in line:
                    offenders.append(f"{path.name}:{i}")
        if offenders:
            raise AssertionError(
                "T-SRC-B3-4 (site 8): rendered T4b report rows must display "
                "the reconciled `codec.<part>` subject, not the `<->` arrow "
                f"form. Stale arrow rows remain at: {offenders!r}."
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
