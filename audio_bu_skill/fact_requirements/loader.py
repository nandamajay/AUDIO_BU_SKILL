"""Phase-3A WP-D — loader for the Fact Family Catalog + Freshness Policy.

Only I/O in the WP-D surface. Two entry points:

  * :func:`load_catalog` — merge per-domain family lists into a validated
    :class:`Catalog`. ``soc_override`` is accepted for forward-compat but is
    a no-op in Phase-3A (Nord and Eliza both use the same audio catalog).
  * :func:`load_freshness_policy` — parse ``fact_freshness.yaml`` and return
    a validated :class:`FreshnessPolicy`.

Both functions are pure w.r.t. side effects beyond reading the yaml file.
Callers must **not** mutate the returned objects (they are frozen).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from audio_bu_skill.fact_requirements.catalog import audio as _audio_catalog
from audio_bu_skill.fact_requirements.catalog import generic as _generic_catalog
from audio_bu_skill.fact_requirements.schema import (
    Authority,
    AuthorityTTL,
    Catalog,
    FreshnessPolicy,
    merge_families,
)

_DEFAULT_FRESHNESS_YAML = Path(__file__).with_name("fact_freshness.yaml")


def load_catalog(soc_override: str | None = None) -> Catalog:
    """Return the merged, validated fact-family catalog.

    ``soc_override`` is accepted for forward-compat with per-SoC catalog
    subsets but is unused in Phase-3A — every Phase-3A target reads the
    same Audio + Generic catalog. Passing an override is silently a no-op;
    a future WP may switch on it.
    """
    _ = soc_override  # reserved; no branch in Phase-3A
    families = merge_families(_audio_catalog.FAMILIES, _generic_catalog.FAMILIES)
    return Catalog(families=families)


def load_freshness_policy(path: os.PathLike[str] | str | None = None) -> FreshnessPolicy:
    """Parse ``fact_freshness.yaml`` (or the given path) into a policy object.

    File shape::

        version: 1
        ttls:
          ipcat_live:
            fresh_seconds: 3600
            stale_seconds: 86400
            expired_seconds: 604800
          ipcat_cached:
            ...

    Every :class:`Authority` enum value must appear as a key. ``null`` is
    accepted for each TTL field (interpreted as "never expires").
    """
    resolved = Path(path) if path is not None else _DEFAULT_FRESHNESS_YAML
    if not resolved.is_file():
        raise FileNotFoundError(f"freshness policy file not found: {resolved}")
    with resolved.open("r", encoding="utf-8") as handle:
        data: Any = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(
            f"freshness policy {resolved}: top-level must be a mapping, got {type(data).__name__}"
        )
    if data.get("version") != 1:
        raise ValueError(
            f"freshness policy {resolved}: unsupported version {data.get('version')!r} "
            f"(WP-D expects version: 1)"
        )
    raw_ttls = data.get("ttls")
    if not isinstance(raw_ttls, dict):
        raise ValueError(
            f"freshness policy {resolved}: 'ttls' must be a mapping, got {type(raw_ttls).__name__}"
        )

    known_authorities = {a.value: a for a in Authority}
    ttls: list[AuthorityTTL] = []
    seen: set[Authority] = set()
    for auth_key, ttl_spec in raw_ttls.items():
        if not isinstance(auth_key, str) or auth_key not in known_authorities:
            raise ValueError(
                f"freshness policy {resolved}: unknown authority key {auth_key!r}"
            )
        if not isinstance(ttl_spec, dict):
            raise ValueError(
                f"freshness policy {resolved}: TTL spec for {auth_key!r} must be a mapping"
            )
        allowed_fields = {"fresh_seconds", "stale_seconds", "expired_seconds"}
        unknown = set(ttl_spec) - allowed_fields
        if unknown:
            raise ValueError(
                f"freshness policy {resolved}: unknown TTL field(s) for {auth_key!r}: "
                f"{sorted(unknown)}"
            )
        for field_name in allowed_fields:
            if field_name not in ttl_spec:
                raise ValueError(
                    f"freshness policy {resolved}: TTL spec for {auth_key!r} "
                    f"missing field {field_name!r}"
                )
        auth = known_authorities[auth_key]
        seen.add(auth)
        ttls.append(
            AuthorityTTL(
                authority=auth,
                fresh_seconds=ttl_spec["fresh_seconds"],
                stale_seconds=ttl_spec["stale_seconds"],
                expired_seconds=ttl_spec["expired_seconds"],
            )
        )
    missing = set(Authority) - seen
    if missing:
        names = ", ".join(sorted(a.value for a in missing))
        raise ValueError(
            f"freshness policy {resolved}: missing TTL entries for authorities: {names}"
        )
    return FreshnessPolicy(ttls=tuple(ttls))


__all__ = ["load_catalog", "load_freshness_policy"]
