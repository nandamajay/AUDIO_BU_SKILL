"""Phase-3A WP-D — tests for the Fact Family Catalog + Freshness Policy.

Runs entirely in-process; does not touch case.py, case.generated.py, WP7,
or any onboarding output. Advisory-only per PHASE3_ARCHITECTURE.md.

Run:
    PYTHONPATH=audio_bu_skill python3 -m tests.test_fact_requirements_catalog
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from audio_bu_skill.fact_requirements import (
    Authority,
    AuthorityClass,
    Domain,
    FactFamilyDef,
    FreshnessPolicy,
    Requiredness,
    SubjectRequirement,
    load_catalog,
    load_freshness_policy,
)
from audio_bu_skill.fact_requirements.schema import AuthorityTTL, Catalog


# ─── T-D1 ──  Schema rejects malformed SubjectRequirement/FactFamilyDef.


def _assert_raises(fn, exc, message_substring=None):
    try:
        fn()
    except exc as e:
        if message_substring is not None and message_substring not in str(e):
            raise AssertionError(
                f"expected {exc.__name__} containing {message_substring!r}, "
                f"got {exc.__name__} with message {e!r}"
            )
        return
    raise AssertionError(f"expected {exc.__name__} to be raised, but nothing raised")


def test_schema_rejects_empty_subject_pattern() -> None:
    _assert_raises(
        lambda: SubjectRequirement(subject_pattern="", requiredness=Requiredness.MANDATORY),
        ValueError,
        "subject_pattern",
    )


def test_schema_rejects_bad_literal_subject_pattern() -> None:
    # Contains characters not allowed for a literal identifier.
    _assert_raises(
        lambda: SubjectRequirement(
            subject_pattern="INVALID PATTERN WITH SPACES",
            requiredness=Requiredness.MANDATORY,
        ),
        ValueError,
        "literal identifier",
    )


def test_schema_accepts_regex_pattern_when_flagged() -> None:
    sr = SubjectRequirement(
        subject_pattern=r"MI2S[0-9]+_SCK",
        requiredness=Requiredness.MANDATORY,
        is_regex=True,
    )
    assert sr.is_regex is True
    assert sr.subject_pattern == "MI2S[0-9]+_SCK"


def test_schema_rejects_broken_regex_pattern() -> None:
    _assert_raises(
        lambda: SubjectRequirement(
            subject_pattern=r"MI2S[0-9",  # unterminated char class
            requiredness=Requiredness.MANDATORY,
            is_regex=True,
        ),
        ValueError,
        "regex",
    )


def test_schema_rejects_wrong_requiredness_type() -> None:
    _assert_raises(
        lambda: SubjectRequirement(subject_pattern="FOO", requiredness="mandatory"),  # type: ignore[arg-type]
        TypeError,
        "Requiredness",
    )


def test_schema_rejects_family_with_empty_primary_authorities() -> None:
    _assert_raises(
        lambda: FactFamilyDef(
            domain=Domain.AUDIO,
            name="Bad",
            description="x",
            primary_authorities=(),
        ),
        ValueError,
        "primary_authorities",
    )


def test_schema_rejects_family_with_overlapping_primary_and_fallback() -> None:
    _assert_raises(
        lambda: FactFamilyDef(
            domain=Domain.AUDIO,
            name="Bad",
            description="x",
            primary_authorities=(Authority.IPCAT_LIVE,),
            fallback_authorities=(Authority.IPCAT_LIVE,),
        ),
        ValueError,
        "primary and fallback",
    )


def test_schema_rejects_family_with_duplicate_subject_patterns() -> None:
    _assert_raises(
        lambda: FactFamilyDef(
            domain=Domain.AUDIO,
            name="Dup",
            description="x",
            primary_authorities=(Authority.IPCAT_LIVE,),
            subject_requirements=(
                SubjectRequirement(subject_pattern="FOO", requiredness=Requiredness.MANDATORY),
                SubjectRequirement(subject_pattern="FOO", requiredness=Requiredness.ADVISORY),
            ),
        ),
        ValueError,
        "duplicate subject_pattern",
    )


def test_schema_rejects_critical_family_without_any_mandatory_subjects() -> None:
    _assert_raises(
        lambda: FactFamilyDef(
            domain=Domain.AUDIO,
            name="CritButAdvisoryOnly",
            description="x",
            primary_authorities=(Authority.IPCAT_LIVE,),
            critical=True,
            subject_requirements=(
                SubjectRequirement(subject_pattern="FOO", requiredness=Requiredness.ADVISORY),
            ),
        ),
        ValueError,
        "zero MANDATORY",
    )


def test_schema_rejects_family_with_bad_name() -> None:
    _assert_raises(
        lambda: FactFamilyDef(
            domain=Domain.AUDIO,
            name="123bad",  # can't start with digit
            description="x",
            primary_authorities=(Authority.IPCAT_LIVE,),
        ),
        ValueError,
        "name",
    )


# ─── T-D2 ──  Catalog loads and has the expected shape.


def test_catalog_loads_and_has_eleven_audio_families() -> None:
    catalog = load_catalog()
    assert isinstance(catalog, Catalog)
    audio_families = catalog.in_domain(Domain.AUDIO)
    assert len(audio_families) == 11, (
        f"Phase-3A audio catalog should have exactly 11 families, got {len(audio_families)}"
    )


def test_catalog_has_expected_audio_family_names() -> None:
    catalog = load_catalog()
    expected = {
        "Audio.GPIO",
        "Audio.QUP",
        "Audio.CLOCK",
        "Audio.POWER",
        "Audio.SMMU_SID",
        "Audio.ADSP_REG_BASE",
        "Audio.AUDIOREACH_PORT",
        "Audio.INTERCONNECT",
        "Audio.CODEC_BINDING",
        "Audio.DSP_TOPOLOGY",
        "Audio.MBHC_THRESHOLD",
    }
    got = set(catalog.qualified_names())
    assert got == expected, f"catalog mismatch: extra={got - expected}, missing={expected - got}"


def test_catalog_soc_override_is_noop_in_phase3a() -> None:
    a = load_catalog()
    b = load_catalog(soc_override="nordschleife_2.0")
    assert a.qualified_names() == b.qualified_names()


def test_catalog_generic_domain_is_empty_in_phase3a() -> None:
    catalog = load_catalog()
    assert catalog.in_domain(Domain.GENERIC) == ()


# ─── T-D3 ──  Every family in the audio catalog has ≥1 MANDATORY or ADVISORY
# subject requirement (Phase-3A ships no all-optional families).


def test_every_audio_family_has_at_least_one_required_subject() -> None:
    catalog = load_catalog()
    for fam in catalog.in_domain(Domain.AUDIO):
        req = fam.mandatory_requirements() + fam.advisory_requirements()
        assert req, f"family {fam.qualified_name} has no MANDATORY or ADVISORY subjects"


# ─── T-D4 ──  Critical audio families each have ≥1 MANDATORY subject.


def test_every_critical_family_has_at_least_one_mandatory_subject() -> None:
    catalog = load_catalog()
    for fam in catalog.in_domain(Domain.AUDIO):
        if fam.critical:
            assert fam.mandatory_requirements(), (
                f"critical family {fam.qualified_name} lacks any MANDATORY subject"
            )


# ─── T-D5 ──  Every subject pattern compiles (regex or literal shape).


def test_every_subject_pattern_is_valid() -> None:
    catalog = load_catalog()
    literal_re = re.compile(r"^[A-Za-z][A-Za-z0-9_./-]*$")
    for fam in catalog.in_domain(Domain.AUDIO):
        for sr in fam.subject_requirements:
            if sr.is_regex:
                re.compile(f"^(?:{sr.subject_pattern})$")  # must not raise
            else:
                assert literal_re.match(sr.subject_pattern), (
                    f"family {fam.qualified_name} subject {sr.subject_pattern!r} "
                    f"is not a valid literal identifier"
                )


# ─── T-D6 ──  No duplicate FactKey *prefixes* (qualified_name) across the
# entire catalog.


def test_no_duplicate_qualified_names_across_catalog() -> None:
    catalog = load_catalog()
    names = list(catalog.qualified_names())
    assert len(names) == len(set(names)), f"duplicates present in {names}"


# ─── T-D7 ──  Duplicate detection at Catalog construction time.


def test_catalog_rejects_duplicate_family_definitions() -> None:
    fam = FactFamilyDef(
        domain=Domain.AUDIO,
        name="Solo",
        description="x",
        primary_authorities=(Authority.IPCAT_LIVE,),
        subject_requirements=(
            SubjectRequirement(subject_pattern="FOO", requiredness=Requiredness.MANDATORY),
        ),
        critical=True,
    )
    _assert_raises(lambda: Catalog(families=(fam, fam)), ValueError, "duplicate family")


# ─── T-D8 ──  Freshness YAML parses and covers every Authority.


def test_freshness_policy_loads_default() -> None:
    policy = load_freshness_policy()
    assert isinstance(policy, FreshnessPolicy)
    for auth in Authority:
        ttl = policy.ttl_for(auth)
        assert isinstance(ttl, AuthorityTTL)


def test_freshness_policy_has_monotonic_thresholds() -> None:
    policy = load_freshness_policy()
    for auth in Authority:
        ttl = policy.ttl_for(auth)
        # Monotonicity is already enforced by AuthorityTTL.__post_init__,
        # but we re-check to guard against silent policy edits.
        if ttl.fresh_seconds is not None and ttl.stale_seconds is not None:
            assert ttl.fresh_seconds <= ttl.stale_seconds
        if ttl.stale_seconds is not None and ttl.expired_seconds is not None:
            assert ttl.stale_seconds <= ttl.expired_seconds


# ─── T-D9 ──  Freshness loader rejects missing authorities / unknown keys /
# bad version.


def _write_yaml(text: str) -> Path:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    )
    tmp.write(text)
    tmp.close()
    return Path(tmp.name)


def test_freshness_loader_rejects_wrong_version() -> None:
    p = _write_yaml("version: 2\nttls: {}\n")
    try:
        _assert_raises(lambda: load_freshness_policy(p), ValueError, "unsupported version")
    finally:
        p.unlink(missing_ok=True)


def test_freshness_loader_rejects_missing_authority() -> None:
    # Populate only ipcat_live — should fail because the other authorities are missing.
    p = _write_yaml(
        "version: 1\n"
        "ttls:\n"
        "  ipcat_live:\n"
        "    fresh_seconds: 60\n"
        "    stale_seconds: 3600\n"
        "    expired_seconds: 86400\n"
    )
    try:
        _assert_raises(lambda: load_freshness_policy(p), ValueError, "missing TTL entries")
    finally:
        p.unlink(missing_ok=True)


def test_freshness_loader_rejects_unknown_authority() -> None:
    p = _write_yaml(
        "version: 1\n"
        "ttls:\n"
        "  nonsense_authority:\n"
        "    fresh_seconds: 60\n"
        "    stale_seconds: 3600\n"
        "    expired_seconds: 86400\n"
    )
    try:
        _assert_raises(lambda: load_freshness_policy(p), ValueError, "unknown authority key")
    finally:
        p.unlink(missing_ok=True)


def test_freshness_loader_rejects_unknown_ttl_field() -> None:
    body = ["version: 1", "ttls:"]
    for i, auth in enumerate(Authority):
        body.append(f"  {auth.value}:")
        body.append("    fresh_seconds: 60")
        body.append("    stale_seconds: 3600")
        body.append("    expired_seconds: 86400")
        if i == 0:
            body.append("    surprise_extra_field: 1")
    p = _write_yaml("\n".join(body) + "\n")
    try:
        _assert_raises(lambda: load_freshness_policy(p), ValueError, "unknown TTL field")
    finally:
        p.unlink(missing_ok=True)


def test_freshness_loader_missing_file() -> None:
    _assert_raises(
        lambda: load_freshness_policy(Path("/tmp/does-not-exist-abc-987.yaml")),
        FileNotFoundError,
        "not found",
    )


# ─── T-D10 ──  ADSP_REG_BASE forbids MANUAL entries; others allow.


def test_adsp_reg_base_disallows_manual() -> None:
    catalog = load_catalog()
    fam = catalog.by_qualified_name("Audio.ADSP_REG_BASE")
    assert fam.allowed_manual is False


def test_manual_allowed_on_gpio_family() -> None:
    catalog = load_catalog()
    fam = catalog.by_qualified_name("Audio.GPIO")
    assert fam.allowed_manual is True


# ─── T-D11 ──  Enum coverage: AuthorityClass has exactly the four members.


def test_authority_class_has_four_members() -> None:
    got = {c.value for c in AuthorityClass}
    assert got == {"primary", "fallback", "inferred", "manual"}


# ─── T-D12 ──  merge_families rejects duplicate qualified_names across groups.


def test_merge_families_rejects_cross_group_dupes() -> None:
    from audio_bu_skill.fact_requirements.schema import merge_families

    fam = FactFamilyDef(
        domain=Domain.AUDIO,
        name="XYZ",
        description="x",
        primary_authorities=(Authority.IPCAT_LIVE,),
        subject_requirements=(
            SubjectRequirement(subject_pattern="FOO", requiredness=Requiredness.MANDATORY),
        ),
        critical=True,
    )
    _assert_raises(
        lambda: merge_families([fam], [fam]),
        ValueError,
        "duplicate family qualified_name",
    )


# ─── Test harness ──


def main() -> None:
    tests = [
        # T-D1
        test_schema_rejects_empty_subject_pattern,
        test_schema_rejects_bad_literal_subject_pattern,
        test_schema_accepts_regex_pattern_when_flagged,
        test_schema_rejects_broken_regex_pattern,
        test_schema_rejects_wrong_requiredness_type,
        test_schema_rejects_family_with_empty_primary_authorities,
        test_schema_rejects_family_with_overlapping_primary_and_fallback,
        test_schema_rejects_family_with_duplicate_subject_patterns,
        test_schema_rejects_critical_family_without_any_mandatory_subjects,
        test_schema_rejects_family_with_bad_name,
        # T-D2
        test_catalog_loads_and_has_eleven_audio_families,
        test_catalog_has_expected_audio_family_names,
        test_catalog_soc_override_is_noop_in_phase3a,
        test_catalog_generic_domain_is_empty_in_phase3a,
        # T-D3
        test_every_audio_family_has_at_least_one_required_subject,
        # T-D4
        test_every_critical_family_has_at_least_one_mandatory_subject,
        # T-D5
        test_every_subject_pattern_is_valid,
        # T-D6
        test_no_duplicate_qualified_names_across_catalog,
        # T-D7
        test_catalog_rejects_duplicate_family_definitions,
        # T-D8
        test_freshness_policy_loads_default,
        test_freshness_policy_has_monotonic_thresholds,
        # T-D9
        test_freshness_loader_rejects_wrong_version,
        test_freshness_loader_rejects_missing_authority,
        test_freshness_loader_rejects_unknown_authority,
        test_freshness_loader_rejects_unknown_ttl_field,
        test_freshness_loader_missing_file,
        # T-D10
        test_adsp_reg_base_disallows_manual,
        test_manual_allowed_on_gpio_family,
        # T-D11
        test_authority_class_has_four_members,
        # T-D12
        test_merge_families_rejects_cross_group_dupes,
    ]
    for t in tests:
        t()
    print(f"ran {len(tests)} tests")
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
