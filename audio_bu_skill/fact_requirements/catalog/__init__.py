"""Phase-3A WP-D — catalog subpackage.

Per-domain fact-family declarations. Each module in this package exposes a
module-level ``FAMILIES: tuple[FactFamilyDef, ...]`` which the loader merges
into the final :class:`Catalog`.

Phase-3A ships only ``audio`` populated; ``generic`` is a stub reserved for
cross-domain families in a later phase.
"""

from audio_bu_skill.fact_requirements.catalog import audio, generic

__all__ = ["audio", "generic"]
