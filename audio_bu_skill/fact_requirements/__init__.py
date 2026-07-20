"""Phase-3A WP-D — Fact Family Catalog + Requirements Schema.

Static, target-agnostic declaration of what facts the bring-up skill considers
"first-class facts" (domain-scoped families of subjects with per-subject
requiredness), plus a per-authority freshness (TTL) policy.

The catalog is data, not behavior: nothing here performs I/O against evidence,
touches ``case.py``, changes promotion, or emits a report. It exists only so
Phase-3A WP-E (registry) and WP-F (coverage engine) have a single, testable
source of truth for the questions "which subjects are we obligated to have a
fact for?" and "how long does a fact of a given authority stay fresh?".

Public surface (imported by WP-E/WP-F only in later WPs):

    from audio_bu_skill.fact_requirements import (
        Domain, Authority, AuthorityClass, Requiredness,
        FactFamilyDef, SubjectRequirement, FreshnessPolicy,
        load_catalog, load_freshness_policy,
    )

Advisory-only: **no** other module imports from this package in WP-D.
"""

from audio_bu_skill.fact_requirements.schema import (
    Authority,
    AuthorityClass,
    Domain,
    FactFamilyDef,
    FreshnessPolicy,
    Requiredness,
    SubjectRequirement,
)
from audio_bu_skill.fact_requirements.loader import (
    load_catalog,
    load_freshness_policy,
)

__all__ = [
    "Authority",
    "AuthorityClass",
    "Domain",
    "FactFamilyDef",
    "FreshnessPolicy",
    "Requiredness",
    "SubjectRequirement",
    "load_catalog",
    "load_freshness_policy",
]
