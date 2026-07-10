"""Generic audio bring-up skill orchestrator.

Target-agnostic: the state machine and runners drive any audio target's
bring-up; per-target facts live in audio_bu_skill/targets/<name>/case.py.

Standalone package — does not depend on any external checkout. The
skill-invocation state machine, JSONL logger, workspace loader and
validator here re-implement the small set of laei (AURA/laei) patterns
this project decided to reuse (schema-first manifests, evidence-required
validation, an allow-listed per-invocation FSM, secret/raw-content
redaction in logs) after AURA/laei's own runtime became unavailable on
disk. See audio_bu_skill/README.md for the reasoning.
"""
