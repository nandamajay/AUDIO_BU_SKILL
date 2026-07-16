"""Phase-2B WP10 — generation runner.

Public entry point:  ``_run_generation(gc, facts)``

Wires the four generator lanes (WP3-WP6) into a single fan-out/fan-in call.
Consumes a Phase-2A-populated ``gc["cross_verification"]`` dict and a
``TrustedFacts`` projection, fans out to all registered generators (in the
deterministic canonical order from the WP7 registry), collects results,
runs WP7 post-verification, and stores everything in ``gc["generation"]``.

``gc["generation"]`` is ONLY populated when this function is called.  When the
``--generate`` CLI flag is OFF the caller never calls this function, so the key
is absent and the WP8 renderer's null-guard returns ``[]`` — the report is
byte-identical to the pre-WP10 baseline.

Design contract (PHASE2B_SPECIFICATION.md §WP10 lock-in points a-h):

  (a)  Signature: ``_run_generation(gc: dict, facts: TrustedFacts) -> None``
  (b)  Populates  ``gc["generation"] = {"artifacts": [...], "post_verification": pv.to_dict()}``
  (c)  Pipeline order: crossverify (Phase-2A, do_onboard) →
         project_facts (do_onboard) →
         _run_generation (this module) →
         verify_generation_result (WP7) →
         gc["generation"] populated →
         _render_onboarding_report (WP8)
  (d)  ``project_facts`` is called at the do_onboard dispatch level (BEFORE
       ``_run_generation``); this function receives an already-projected
       ``TrustedFacts`` object.
  (e)  ``--generate`` default OFF; ``gc["generation"]`` absent when OFF.
  (f)  WP7 silently skips artifact_classes absent from results — §WP10(f)
       compliance is built into ``verify_generation_result``.
  (g)  3-state CLI truth table: OFF → runner not called;
       ON + cv present → runs; ON + cv absent → exit 2.
  (h)  Two failure categories:
       * ``GeneratorSkipped`` — NOT a failure.  Included in artifacts list.
       * Unhandled exception — IS a failure.  Logged; absent from artifacts.

Path-guard enforcement (§5.4):

  ``write_artifact_bytes(artifact, base_dir)`` rejects any ``path_hint``
  outside ``PATH_GUARD_ROOT``.  Rejection returns ``None``; the caller
  replaces the ``GeneratedArtifact`` with a ``GeneratorSkipped(
  reason="path_guard_violation")``.  The do_onboard dispatch calls
  ``sys.exit(1)`` if any artifact in results carries that reason.

Import discipline:

  * MAY import: model, config, registry, post_verify (all generation-layer)
  * MUST NOT import individual generator modules directly
    (ensure_generators_loaded() handles lazy loading via registry)
  * MUST NOT import from orchestrator.reasoning.* (except via
    already-imported types passed in as arguments)

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_runner``
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from orchestrator.generation.config import PATH_GUARD_ROOT, is_path_within_guard
from orchestrator.generation.model import (
    GeneratedArtifact,
    GenerationResult,
    GeneratorSkipped,
    TrustedFacts,
)
from orchestrator.generation.post_verify import verify_generation_result
from orchestrator.generation.registry import (
    ensure_generators_loaded,
    generator_func,
    generator_order,
)


class MissingPhase2ASnapshot(Exception):
    """Raised when ``gc["cross_verification"]`` is absent or empty.

    Caught at the do_onboard dispatch level and translated to
    ``sys.exit(2)`` per PHASE2B_SPECIFICATION.md §3.8.
    """


def write_artifact_bytes(
    artifact: GeneratedArtifact,
    base_dir: Path,
) -> Optional[Path]:
    """Write artifact bytes to disk; return Path on success, None on path-guard violation.

    Never raises for path-guard rejection (caller converts None to
    ``GeneratorSkipped(reason="path_guard_violation")``).  Raises
    ``OSError`` / ``IOError`` on genuine I/O failure.

    ``artifact.path_hint`` is joined under ``base_dir``.  The resulting
    path must be within ``PATH_GUARD_ROOT`` (``is_path_within_guard``
    predicate from config.py) — any path escaping the guard root is
    rejected with a ``None`` return.
    """
    if not is_path_within_guard(artifact.path_hint):
        return None
    dest = base_dir / artifact.path_hint
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(artifact.bytes_)
    return dest


def _run_generation(gc: dict, facts: TrustedFacts) -> None:
    """Fan-out to all registered generators; store results in ``gc["generation"]``.

    Parameters
    ----------
    gc:
        The ``generated_case`` dict from ``output["generated_case"]``.
        Must contain ``gc["cross_verification"]`` (non-empty dict); raises
        ``MissingPhase2ASnapshot`` otherwise.
    facts:
        A ``TrustedFacts`` projection of the Phase-2A verification rows,
        produced by ``project_facts`` at the do_onboard dispatch level.

    Side effects
    ------------
    Populates ``gc["generation"]`` in-place with::

        {
            "artifacts": [result.to_dict(), ...],   # GeneratedArtifact | GeneratorSkipped
            "post_verification": pv.to_dict(),       # PostVerificationResult
        }

    where ``artifacts`` is in canonical generator order, each failed
    generator (unhandled exception) is absent from the list (§WP10(h)),
    and each ``GeneratorSkipped`` result (including path-guard violations)
    is included.
    """
    cv = gc.get("cross_verification")
    if not cv:
        raise MissingPhase2ASnapshot(
            "gc[\"cross_verification\"] is absent or empty — "
            "Phase-2A cross-verification must complete before generation can run "
            "(PHASE2B_SPECIFICATION.md §3.8)"
        )

    ensure_generators_loaded()
    order = generator_order()

    results: list[GenerationResult] = []
    for artifact_class in order:
        func = generator_func(artifact_class)
        try:
            result: GenerationResult = func(facts)  # type: ignore[call-arg]
        except Exception as exc:  # noqa: BLE001 — failure isolation per §WP10(h)
            print(
                f"  [generation] {artifact_class}: FAILED "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            continue

        if isinstance(result, GeneratedArtifact):
            if not is_path_within_guard(result.path_hint):
                results.append(
                    GeneratorSkipped(
                        artifact_class=artifact_class,
                        subject=result.subject,
                        reason="path_guard_violation",
                        gating_rows=[],
                    )
                )
                continue

        results.append(result)

    pv = verify_generation_result(results, facts)
    gc["generation"] = {
        "artifacts": [r.to_dict() for r in results],
        "post_verification": pv.to_dict(),
    }
