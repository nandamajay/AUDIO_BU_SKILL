"""Plain-function skill runners for audio_bu_skill.

These are NOT laei run_fixture(input_envelope) fixtures. Each runner is a
plain Python function with signature (input_envelope: dict) -> dict,
registered onto a BringupOrchestrator via register_runner(skill_id, fn).

source_intake and triage are interactive/judgment skills: in a live run
they should prompt the operator (or call out to an LLM) for the missing
judgment call. The runners here implement the deterministic bookkeeping
around that judgment (assembling evidence_refs, shaping the output
envelope) and accept the judgment itself as part of the input_envelope
rather than hardcoding it, so a human or an LLM can supply it.
"""
