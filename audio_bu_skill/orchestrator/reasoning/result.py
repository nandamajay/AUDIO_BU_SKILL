"""Reasoning result + reproducibility contract for the QGenie seam (v1.2).

Pure, deterministic dataclasses mirroring ``orchestrator/codegen/models.py``
(``to_dict()``, ``from __future__ import annotations``, stdlib-only).

``ReasoningResult`` is what ``QGenieReasoningClient.analyze`` returns: the raw
model text (artifacted separately, never logged verbatim — it may contain
confidential content), the parsed+validated structured analysis, and the
engine/model/CLI identity that produced it.

``reasoning_fingerprints`` is the *reasoning* reproducibility contract, the
analogue of Phase 2's ``generation_fingerprints`` and distinct from v1.0's
*validation* contract (``run_manifest.compute_fingerprints``). QGenie is not
deterministic, so reproducibility is over *what conditioned the call* — the
task_spec, the engine/model identity, the CLI version, the schema version, and
the IPCAT provenance — never the prose.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReasoningResult:
    """The outcome of one reasoning call.

    ``raw_text`` is the unparsed model output; it is written to a gitignored
    artifact (``qgenie_raw_output.txt``) and must NOT be logged verbatim or put
    into run state (``logger_json`` forbids raw content, and it may be
    confidential). ``parsed`` is the schema-validated structured analysis.
    """

    parsed: dict[str, Any]
    raw_text: str
    engine_id: str
    model_id: str = ""
    cli_version: str = ""
    schema_version: str = ""
    argv_fingerprint: str = ""

    def summary(self) -> str:
        """A short, log-safe one-liner (no raw model prose)."""
        soc = (self.parsed.get("soc") or {}).get("value", "?")
        codecs = self.parsed.get("codecs") or []
        parts = ", ".join(c.get("part", "?") for c in codecs) or "none"
        conf = self.parsed.get("overall_confidence")
        return (
            f"engine={self.engine_id} model={self.model_id or '?'} "
            f"soc={soc} codecs=[{parts}] overall_confidence={conf}"
        )

    def to_dict(self) -> dict[str, Any]:
        # NB: raw_text is deliberately excluded — callers artifact it separately.
        return {
            "engine_id": self.engine_id,
            "model_id": self.model_id,
            "cli_version": self.cli_version,
            "schema_version": self.schema_version,
            "argv_fingerprint": self.argv_fingerprint,
            "parsed": self.parsed,
        }


def _digest(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _ipcat_provenance_id(ipcat_provenance: dict[str, Any] | None) -> str | None:
    """A stable, human-inspectable provenance id, distinct from the full hash.

    Prefers the MCP-written ``doc_ids``/``query`` (see PLAYBOOK.md's
    ``evidence/ipcat/provenance.json`` shape); falls back to the full digest so a
    provenance blob lacking those keys still yields a deterministic id.
    """
    if not ipcat_provenance:
        return None
    doc_ids = ipcat_provenance.get("doc_ids")
    if doc_ids:
        return "doc_ids:" + hashlib.sha256(
            json.dumps(sorted(doc_ids), ensure_ascii=True).encode("utf-8")
        ).hexdigest()[:16]
    query = ipcat_provenance.get("query")
    if query:
        return "query:" + hashlib.sha256(str(query).encode("utf-8")).hexdigest()[:16]
    return "digest:" + _digest(ipcat_provenance)[:16]


def reasoning_fingerprints(
    *,
    task_spec: dict[str, Any],
    engine_id: str,
    model_id: str = "",
    cli_version: str = "",
    schema_version: str = "",
    ipcat_provenance: dict[str, Any] | None = None,
    qgenie_cli_home: str | None = None,
    config_root: str | None = None,
    data_root: str | None = None,
    kernel_commit: str | None = None,
    evidence_sha256: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The reasoning reproducibility contract (distinct from validation).

    Reproducible over what *conditioned* the QGenie call, not the non-deterministic
    prose it returned: the task_spec, the engine/model/CLI/schema identity, the
    QGenie CLI profile in effect (``QGENIE_CLI_HOME`` selects between independently
    provisioned profiles — see client.py's preflight — so which profile answered
    this call is itself a reproducibility fact, not just an env detail), the kernel
    commit, the evidence file hashes, and the IPCAT provenance (doc ids) if any.
    Deterministic — same inputs, same digests (keys sorted before hashing), so
    ``--rerun`` can diff these without re-calling QGenie.
    """
    return {
        "task_spec_sha256": _digest(task_spec),
        "engine_id": engine_id,
        "model_id": model_id,
        "cli_version": cli_version,
        "schema_version": schema_version,
        "qgenie_cli_home": qgenie_cli_home,
        "config_root": config_root,
        "data_root": data_root,
        "kernel_commit": kernel_commit,
        "evidence_sha256": _digest(evidence_sha256) if evidence_sha256 else None,
        "ipcat_provenance_sha256": _digest(ipcat_provenance) if ipcat_provenance else None,
        "ipcat_provenance_id": _ipcat_provenance_id(ipcat_provenance),
    }
