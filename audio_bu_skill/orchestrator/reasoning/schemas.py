"""JSON Schemas for the QGenie/Claude reasoning seam (v1.2).

Two roles for the same schema:
  1. It is passed to ``qgenie claude ... --json-schema <file>`` so the harness
     *forces* structured output — Claude must return JSON matching this shape.
  2. It is used to re-validate the parsed output on our side (defence in depth:
     the ``--json-schema`` contract is enforced by the harness, but we never trust
     a subprocess blindly — see ``client.QGenieReasoningClient.analyze``).

Style mirrors ``skills/*/schema.json``: plain dicts, ``additionalProperties`` left
open on the finding objects so QGenie may enrich a finding without breaking the
contract, but the *envelope* keys we depend on are ``required``.

``ANALYSIS_SCHEMA`` is the onboarding analysis contract (§7 of the v1.2 plan).
``GENERATION_SCHEMA`` is reserved for the deferred Phase 2 generation lane and is
intentionally minimal — nothing consumes it yet.
"""

from __future__ import annotations

from typing import Any

# Bumped whenever the analysis contract changes shape; recorded in the reasoning
# fingerprints so a schema change surfaces as drift on --rerun.
#
# 1.1.0 (Onboarding Accuracy Upgrade, slice 5): additive only — adds optional
# `schematic_nets` (for pin_crosscheck's GPIO-vs-net comparison) and optional
# `q6apm`/`q6prm` booleans on `audio_stack`. Nothing required changed; a
# 1.0.0-shaped response still validates.
#
# 1.2.0 (Benchmark Readiness Fix #4): additive only — adds optional
# `ipcat_findings` so QGenie can self-report whether it actually queried IPCAT
# live via the qgenie-chat MCP tools this session, and whether the result was
# target-specific or only generic. This is diagnostic/reporting only — the
# orchestrator cannot observe live MCP tool calls itself (see
# target_onboarding_runner._ipcat_evidence_summary), so this is the only place
# that signal can be captured. Nothing required changed.
#
# 1.3.0 (Fix A — element_counts, see docs/FIX_A_ELEMENT_COUNTS_SCHEMA_DESIGN.md):
# additive only — adds optional `element_counts`, per-element-class instance
# counts as typed integers from each independent enumeration lane (dt / evidence
# / proposal / catalog). This gives the counts QGenie already surfaces in prose
# (`"8x DMIC"`, `"2x … Speaker 0/1"`) a machine-countable home, so a future
# Cardinality Authority (WP-C) can compare true instance counts rather than
# list-lengths. `catalog` is declared but always null pre-SWI so the post-SWI
# upgrade stays additive. Nothing required changed; a 1.2.0-shaped response
# (no element_counts) still validates.
#
# 1.4.0: closes schema/validator gap on nearest_targets citations. The validator
# already required non-empty citations on every scored nearest_targets entry
# (FINDING_MISSING_CITATION); the schema now enforces the same contract so
# QGenie's structured-output harness retries before the response reaches the
# validator. `citations` is now required on _NEAREST_TARGET_ITEM with minItems=1.
# Backward-compat: all real stored artifacts and frozen test fixtures already
# carry non-empty citations on nearest_targets (confirmed before this bump).
ANALYSIS_SCHEMA_VERSION = "1.4.0"

# A finding that carries per-field confidence + citations. Reused for every
# perception signal QGenie returns so the "cite everything" rule is uniform.
_CITED_FINDING: dict[str, Any] = {
    "type": "object",
    "properties": {
        "value": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "citations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["confidence", "citations"],
    "additionalProperties": True,
}

_CODEC_ITEM: dict[str, Any] = {
    "type": "object",
    "properties": {
        "part": {"type": "string"},
        "role": {"type": "string"},  # e.g. amp | codec | mic | speaker
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "citations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["part", "confidence", "citations"],
    "additionalProperties": True,
}

# New in 1.1.0: a schematic-derived GPIO/net finding, feeding pin_crosscheck.
# Optional on the envelope (not in `required`) so a 1.0.0-style response with
# no schematic_nets at all still validates.
_SCHEMATIC_NET_ITEM: dict[str, Any] = {
    "type": "object",
    "properties": {
        "net_name": {"type": "string"},
        "gpio": {"type": ["integer", "string"]},
        "sheet_ref": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["net_name", "gpio"],
    "additionalProperties": True,
}

# New in 1.2.0: QGenie's own self-report of whether it queried IPCAT live via
# the qgenie-chat MCP tools this session, and whether what came back was
# actually target-specific or only generic (e.g. multi-SoC boilerplate).
# Optional on the envelope — absent means "not reported", not "not queried".
_IPCAT_FINDINGS_ITEM: dict[str, Any] = {
    "type": "object",
    "properties": {
        "queried": {"type": "boolean"},
        "returned_target_specific": {"type": "boolean"},
        "returned_generic_only": {"type": "boolean"},
        "notes": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": True,
}

# New in 1.3.0, optional: per-element-class instance counts from each
# independent enumeration lane, as typed integers (Track C / WP-C input).
# Absent means "not reported" (a pre-1.3.0 response), NOT "count is zero".
# Each lane value is an integer >= 0, OR null when that lane was not consulted /
# cannot produce a count (null is distinct from an affirmative 0). `ambiguous`
# marks a count the model itself could not resolve to a single integer (e.g.
# Eliza "1 or 2 masters"); `dt_applied: false` marks a dt=0 that means "audio
# scaffolding is unapplied at the pinned HEAD" rather than "absent from silicon".
# The element_class string is validated against the known class list downstream
# (never in this schema) so adding a class stays a config change, not a bump.
_ELEMENT_COUNT_ITEM: dict[str, Any] = {
    "type": "object",
    "properties": {
        "element_class": {"type": "string"},
        "dt": {"type": ["integer", "null"], "minimum": 0},
        "evidence": {"type": ["integer", "null"], "minimum": 0},
        "proposal": {"type": ["integer", "null"], "minimum": 0},
        # Declared but always null pre-SWI — present so the post-SWI (Track D)
        # upgrade that fills catalog_count is itself additive (no future bump).
        "catalog": {"type": ["integer", "null"], "minimum": 0},
        "ambiguous": {"type": "boolean"},
        "ambiguity_note": {"type": "string"},
        "dt_applied": {"type": "boolean"},
        "citations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["element_class", "citations"],
    "additionalProperties": True,
}

_NEAREST_TARGET_ITEM: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "rationale": {"type": "string"},
        # minItems=1: a scored ranking with no evidence pointer is not auditable.
        # Mirrors the validator rule (FINDING_MISSING_CITATION) at the schema layer
        # so QGenie's structured-output harness retries before the response reaches
        # the validator. Score=0 entries are exempt (not checked by the validator).
        "citations": {"type": "array", "items": {"type": "string"}, "minItems": 1},
    },
    "required": ["name", "score", "rationale", "citations"],
    "additionalProperties": True,
}

# The structured result QGenie/Claude must return for an onboarding analysis.
ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "soc": _CITED_FINDING,
        "board": _CITED_FINDING,
        "codecs": {"type": "array", "items": _CODEC_ITEM},
        "amplifiers": {"type": "array", "items": _CODEC_ITEM},
        "mics": {"type": "array", "items": _CODEC_ITEM},
        "speakers": {"type": "array", "items": _CODEC_ITEM},
        "buses": {"type": "array", "items": {"type": "string"}},
        "soundwire": {
            "type": "object",
            "properties": {
                "present": {"type": "boolean"},
                "master_count": {"type": "integer", "minimum": 0},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "citations": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["present", "confidence", "citations"],
            "additionalProperties": True,
        },
        "audio_stack": {
            "type": "object",
            "properties": {
                "lpass": {"type": "boolean"},
                "adsp": {"type": "boolean"},
                "audioreach": {"type": "boolean"},
                "gpr": {"type": "boolean"},
                "apm": {"type": "boolean"},
                "q6apm": {"type": "boolean"},
                "q6prm": {"type": "boolean"},
                "citations": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": True,
        },
        "power_model": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["rpmhpd", "scmi", "unknown"]},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "citations": {"type": "array", "items": {"type": "string"}},
                # Never auto-finalized — the Nord SCMI/LCX-LMX policy. Must be True.
                "needs_review": {"type": "boolean"},
            },
            "required": ["kind", "confidence", "citations", "needs_review"],
            "additionalProperties": True,
        },
        "nearest_targets": {"type": "array", "items": _NEAREST_TARGET_ITEM},
        "missing_evidence": {"type": "array", "items": {"type": "string"}},
        "overall_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "human_review_needed": {"type": "boolean"},
        # New in 1.1.0, optional: schematic net/GPIO findings for pin_crosscheck.
        "schematic_nets": {"type": "array", "items": _SCHEMATIC_NET_ITEM},
        # New in 1.2.0, optional: IPCAT MCP query self-report (Fix #4).
        "ipcat_findings": _IPCAT_FINDINGS_ITEM,
        # New in 1.3.0, optional: per-element-class instance counts (Fix A).
        "element_counts": {"type": "array", "items": _ELEMENT_COUNT_ITEM},
    },
    "required": [
        "soc",
        "codecs",
        "power_model",
        "nearest_targets",
        "missing_evidence",
        "overall_confidence",
        "human_review_needed",
    ],
    "additionalProperties": True,
}

# Reserved for the deferred Phase 2 generation lane. Nothing consumes this yet;
# it exists so codegen/engine.py's QGenieEngine can reference a stable name.
GENERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "changes": {"type": "array", "items": {"type": "object"}},
        "summary": {"type": "string"},
        "human_review_needed": {"type": "boolean"},
    },
    "required": ["changes", "human_review_needed"],
    "additionalProperties": True,
}
