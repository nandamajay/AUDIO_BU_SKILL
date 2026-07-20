"""Phase-3A WP-D — Generic (cross-domain) fact families.

Reserved for facts that don't belong to a single domain (e.g. board-level
identifiers, cross-domain reset lines). **Empty in Phase-3A** — kept as a
placeholder so the loader's structure stays symmetric with per-domain
modules and other domains can add here later without a package-level change.
"""

from __future__ import annotations

from audio_bu_skill.fact_requirements.schema import FactFamilyDef

# Empty in Phase-3A. Do not add "example" or "sample" families — the coverage
# engine walks this list and would treat any entry as authoritative.
FAMILIES: tuple[FactFamilyDef, ...] = ()

__all__ = ["FAMILIES"]
