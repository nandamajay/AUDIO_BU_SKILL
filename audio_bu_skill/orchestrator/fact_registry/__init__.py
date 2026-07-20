"""Phase-3A WP-E — Fact Registry public package surface.

Everything a consumer needs to load, read, and append to a per-target fact
registry, re-exported from one place:

- :class:`Registry`, :class:`RegistryStatus` — the store (:mod:`.store`).
- :class:`FactKey`, :class:`FactValue`, :class:`FactProvenance`,
  :data:`JsonScalar` — the fact model (:mod:`.models`).
- :class:`ReviewRecord`, :class:`ReviewDecision` — manual-review records
  (:mod:`.review`).
- The seven :data:`SourceRef` variants + the :data:`SourceRef` union
  (:mod:`.source_refs`).
- The error hierarchy (:mod:`.errors`).
- The stable constants + path helpers a caller may need (:mod:`.constants`).

Import discipline (§1.8): consumers should import from this package, not from
the private submodules. WP-D types (Authority, AuthorityClass, Domain) live in
:mod:`audio_bu_skill.fact_requirements` and are intentionally **not**
re-exported here — import them from their own package.
"""

from __future__ import annotations

from audio_bu_skill.orchestrator.fact_registry.constants import (
    MAX_PROVENANCE_CHAIN_LEN,
    MIN_TOLERABLE_MINOR,
    REGISTRY_HEADER_TYPE,
    SCHEMA_VERSION,
    STALE_TMP_TTL_SEC,
    SUPPORTED_SCHEMA_VERSIONS,
    WRITER_ID,
    default_base_dir,
    hash_sidecar_filename,
    jsonl_filename,
    lock_filename,
)
from audio_bu_skill.orchestrator.fact_registry.errors import (
    RegistryError,
    RegistryLoadError,
    RegistryLockError,
    RegistryWriteError,
)
from audio_bu_skill.orchestrator.fact_registry.models import (
    FactKey,
    FactProvenance,
    FactValue,
    JsonScalar,
)
from audio_bu_skill.orchestrator.fact_registry.review import (
    ReviewDecision,
    ReviewRecord,
)
from audio_bu_skill.orchestrator.fact_registry.source_refs import (
    ACDBRef,
    IPCATCachedRef,
    IPCATLiveRef,
    InferredRef,
    KernelRef,
    ManualRef,
    SchematicRef,
    SourceRef,
)
from audio_bu_skill.orchestrator.fact_registry.store import (
    Registry,
    RegistryStatus,
)

__all__ = [
    # store
    "Registry",
    "RegistryStatus",
    # models
    "FactKey",
    "FactValue",
    "FactProvenance",
    "JsonScalar",
    # review
    "ReviewRecord",
    "ReviewDecision",
    # source refs
    "SourceRef",
    "IPCATLiveRef",
    "IPCATCachedRef",
    "KernelRef",
    "SchematicRef",
    "ACDBRef",
    "ManualRef",
    "InferredRef",
    # errors
    "RegistryError",
    "RegistryLoadError",
    "RegistryLockError",
    "RegistryWriteError",
    # constants + path helpers
    "SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "MIN_TOLERABLE_MINOR",
    "MAX_PROVENANCE_CHAIN_LEN",
    "STALE_TMP_TTL_SEC",
    "REGISTRY_HEADER_TYPE",
    "WRITER_ID",
    "default_base_dir",
    "jsonl_filename",
    "hash_sidecar_filename",
    "lock_filename",
]
