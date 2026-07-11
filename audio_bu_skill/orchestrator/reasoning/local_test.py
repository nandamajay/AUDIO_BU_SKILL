"""Demoted local comparator — TEST MODE ONLY, never production (v1.2).

The v1.1 local similarity engine (``orchestrator/similarity``) is no longer on the
production reasoning path: it reads only kernel DT text + evidence *filenames*,
never datasheet/IPCAT content, and its closed-form score produced the misleading
low-confidence ``nearest_target=nord-iq10`` result for Eliza. It is kept solely as
a regression comparator, reachable only via ``get_reasoning_client("local-test",
test_mode=True)``.

Every result it produces is stamped ``engine_id="local-test"`` so it can never be
mistaken for a real QGenie analysis, and it emits the same ``ANALYSIS_SCHEMA`` shape
as ``QGenieReasoningClient`` so tests can exercise the runner's mapping code without
a live QGenie.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.reasoning.result import ReasoningResult
from orchestrator.reasoning.schemas import ANALYSIS_SCHEMA_VERSION
from orchestrator.similarity import confidence as compute_confidence
from orchestrator.similarity import extract_profile, rank


class LocalTestReasoningClient:
    """A ReasoningClient-shaped adapter over the local similarity engine.

    Not registered for production; ``get_reasoning_client`` only returns it under
    the explicit ``--test-mode`` gate.
    """

    engine_id = "local-test"
    model_id = "local-similarity"
    cli_version = "local"

    def __init__(self, **_kwargs: Any):
        # Accept and ignore QGenie kwargs so the factory can pass them uniformly.
        pass

    def preflight(self, **_kwargs: Any) -> None:  # no env to validate
        return None

    @property
    def qgenie_cli_home(self) -> str | None:
        # no real QGenie profile backs this engine — stamped, never a real value,
        # so it can never be mistaken for a genuine profile fingerprint.
        return None

    @property
    def config_root(self) -> str | None:
        return None

    @property
    def data_root(self) -> str | None:
        return None

    def analyze(
        self,
        task_spec: dict[str, Any],
        *,
        json_schema: dict[str, Any] | None = None,
        timeout: int = 0,
    ) -> ReasoningResult:
        target_name = task_spec.get("target", "")
        kernel_path = (task_spec.get("kernel") or {}).get("path")
        evidence = task_spec.get("evidence") or {}

        # rebuild an evidence_roots-like dict from the file lists' parents
        evidence_roots: dict[str, str] = {}
        for group_key, root_key in (("ipcat", "ipcat"), ("offline", "offline_documents")):
            files = evidence.get(group_key) or []
            if files:
                evidence_roots[root_key] = str(Path(files[0]).parent)

        new_profile = extract_profile(
            target_name=target_name, kernel_source=kernel_path,
            evidence_roots=evidence_roots or None, case=None,
        )
        db_profiles = _db_profiles_from_task_spec(task_spec, kernel_path)
        ranked = rank(new_profile, db_profiles)
        conf = compute_confidence(ranked)

        parsed = _to_analysis_schema(new_profile, ranked, conf)
        return ReasoningResult(
            parsed=parsed,
            raw_text="(local-test engine — no model output)",
            engine_id=self.engine_id,
            model_id=self.model_id,
            cli_version=self.cli_version,
            schema_version=ANALYSIS_SCHEMA_VERSION,
            argv_fingerprint="local-test",
        )


def _db_profiles_from_task_spec(task_spec: dict[str, Any], kernel_path: Any) -> list:
    """Build DB TargetProfiles from the candidate_targets descriptors."""
    profiles = []
    for cand in task_spec.get("candidate_targets") or []:
        # a tiny shim object carrying the fields extract_profile(case=...) reads
        shim = _CaseShim(cand)
        profiles.append(
            extract_profile(target_name=cand.get("name", ""), kernel_source=kernel_path, case=shim)
        )
    return profiles


class _CaseShim:
    """Minimal stand-in for a BringupCase built from a candidate descriptor."""

    def __init__(self, cand: dict[str, Any]):
        self.target_soc = cand.get("soc", "")
        self.codec_part_numbers = cand.get("codecs", []) or []
        self.codec_verdicts = cand.get("codec_verdicts", {}) or {}


def _to_analysis_schema(new_profile, ranked, conf) -> dict[str, Any]:
    """Map local signals into the ANALYSIS_SCHEMA shape (low confidence by nature)."""
    cites = new_profile.cites or {}
    codecs = [
        {"part": part, "role": "codec", "confidence": 0.4,
         "citations": cites.get("codecs", [])}
        for part in sorted(new_profile.codecs)
    ]
    nearest = [
        {"name": r.target_name, "score": round(max(r.overall, 0.0), 4),
         "rationale": "local weighted similarity (test-only comparator)",
         "citations": []}
        for r in ranked
    ]
    return {
        "soc": {"value": new_profile.soc or "", "confidence": 0.4 if new_profile.soc else 0.0,
                "citations": cites.get("soc", [])},
        "codecs": codecs,
        "amplifiers": [],
        "mics": [],
        "speakers": [],
        "buses": [],
        "soundwire": {"present": bool(new_profile.soundwire.get("present")),
                      "master_count": int(new_profile.soundwire.get("master_count", 0)),
                      "confidence": 0.3, "citations": cites.get("soundwire", [])},
        "audio_stack": {"audioreach": bool(new_profile.audioreach), "citations": cites.get("audioreach", [])},
        "power_model": {"kind": "unknown", "confidence": 0.0,
                        "citations": cites.get("power_domain_providers", []), "needs_review": True},
        "nearest_targets": nearest,
        "missing_evidence": ["local-test engine does not read datasheet/IPCAT content"],
        "overall_confidence": float(conf.get("confidence", 0.0)),
        "human_review_needed": True,
    }
