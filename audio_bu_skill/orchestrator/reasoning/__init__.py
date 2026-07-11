"""QGenie/Claude reasoning seam (v1.2).

Makes QGenie/Claude the mandatory reasoning engine for the intelligent parts of the
workflow (onboarding analysis today; generation later). Local Python stays
orchestration-only. Strict, no silent fallback: if QGenie is unavailable the client
raises ``ReasoningUnavailableError`` rather than substituting a local heuristic.

See ``client.py`` (the QGenie subprocess client + strict env validation),
``schemas.py`` (the structured-output contract), and ``result.py`` (the result +
reproducibility fingerprints).
"""

from __future__ import annotations

from orchestrator.reasoning.client import (
    DEFAULT_IPCAT_MCP_CONFIG,
    QGenieReasoningClient,
    ReasoningClient,
    ReasoningUnavailableError,
    build_prompt,
    get_reasoning_client,
)
from orchestrator.reasoning.result import ReasoningResult, reasoning_fingerprints
from orchestrator.reasoning.schemas import (
    ANALYSIS_SCHEMA,
    ANALYSIS_SCHEMA_VERSION,
    GENERATION_SCHEMA,
)

__all__ = [
    "ReasoningClient",
    "QGenieReasoningClient",
    "ReasoningUnavailableError",
    "get_reasoning_client",
    "build_prompt",
    "DEFAULT_IPCAT_MCP_CONFIG",
    "ReasoningResult",
    "reasoning_fingerprints",
    "ANALYSIS_SCHEMA",
    "ANALYSIS_SCHEMA_VERSION",
    "GENERATION_SCHEMA",
]
