"""H-2 reviewer subsystem — a read-only data-flow leaf over H-1 output.

The reviewer consumes H-1's ``audio_hardware_template.json`` and
``gap_manifest.json`` for a target and projects them into frozen view
objects (:mod:`orchestrator.reviewer.model`) for downstream rendering.

**Firewall posture (matches H-1's leaf discipline):**

  * READS ONLY ``targets/<name>/**/audio_hardware_template.json`` and
    ``gap_manifest.json`` (plus optional ``gap_states.json`` /
    ``attested_findings.md`` in later phases).
  * WRITES ONLY under ``targets/<name>/reviewer/`` (Phase 3+; nothing is
    written in Phase 1).
  * NEVER writes ``gc["cross_verification"]["rows"]``, ``TrustedFacts``,
    or any H-1 artefact — the reviewer is downstream of authority, never
    a source of it (invariant I-1).
  * NEVER imports ``orchestrator.hw_template.*``,
    ``orchestrator.reasoning.*``, ``orchestrator.generation.*``, or
    ``orchestrator.codegen.*`` (invariant I-2). It reads JSON, not Python
    objects.

Phase 1 ships only the foundation: the frozen model and the loader.
Severity, workflow state, attested findings, views, and renderers are
later phases.
"""
