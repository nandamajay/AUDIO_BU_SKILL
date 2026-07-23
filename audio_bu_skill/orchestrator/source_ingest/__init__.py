"""WP-SRC-A source-fact ingestion package.

Populates the source side of cross-verify (pinmux / endpoints / DTS)
that is empty on Nord and Eliza `profile.json` today — the root
cause behind G-3A.7 (three-of-four generators gated closed).

Exports:

  * ``derive_pinmux_from_dt`` — pure DT → PinmuxFact derivation
    (commit 1, ``pinmux.py``).
  * ``PinmuxFact`` — frozen dataclass for one derived pinmux entry.
  * ``SOURCE_UNRESOLVED`` — bare-singleton sentinel for underivable
    input; §5 evidence doctrine ("never silent empty, never fabricated
    guess"). Design B: identity check ``v is SOURCE_UNRESOLVED`` is
    the canonical predicate. Defined once in ``models.py`` and
    re-exported here and from ``pinmux.py`` so T-SRC-A-3's tri-path
    import contract passes.
  * ``sentinel_to_json_literal`` — JSON-boundary helper that swaps
    the bare singleton for the literal string ``"SOURCE_UNRESOLVED"``
    immediately before ``json.dumps``.

Refs: PHASE3A_IMPLEMENTATION_PLAN.md §4 WP-SRC-A1,
      docs/PHASE3_KNOWN_GAPS.md G-3A.7, G-3A.9.
"""

from .dt_reader import read_dt_pinctrl
from .endpoints import EndpointFact, derive_endpoints_from_ipcat
from .models import SOURCE_UNRESOLVED, sentinel_to_json_literal
from .pinmux import PinmuxFact, derive_pinmux_from_dt

__all__ = [
    "SOURCE_UNRESOLVED",
    "EndpointFact",
    "PinmuxFact",
    "derive_endpoints_from_ipcat",
    "derive_pinmux_from_dt",
    "read_dt_pinctrl",
    "sentinel_to_json_literal",
]
