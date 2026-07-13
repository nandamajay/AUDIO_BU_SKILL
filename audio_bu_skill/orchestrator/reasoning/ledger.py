"""Confidence Ledger (Track B / WP-B) — pure, target-agnostic, diagnostic-only.

This module derives a per-domain *trust summary* from data the onboarding run
already produced (``generated_case["audio_topology"]`` + ``["needs_review"]``,
optionally the raw ``analysis`` envelope). It introduces **no new evidence
fields** and **no gating** — the ledger is rendered into the onboarding report
purely as a reviewer aid (see ``main._render_confidence_ledger``). Nothing in
the decision or promotion path reads it.

Design (FRAMEWORK_ARTIFACT_SPECIFICATION.md Track B):
  * B.1  Fixed 9-domain enum — every target shows every row (a *gauge*, not a
         per-target artifact). A domain with no evidence renders ``MISSING``.
  * B.2  5-status enum: CORROBORATED / NEEDS_REVIEW / MISSING / VERIFY /
         NOT_APPLICABLE.
  * B.3  Coarse bands (high/medium/low/—) to avoid false precision; the raw
         float is used only for the roll-up.
  * B.4  Min-confidence roll-up (a domain is only as trustworthy as its weakest
         contributing field) + a deterministic status function.
  * B.5  Rendering handled by main.py; this module returns structured rows.

Everything here is pure (no I/O), so it is unit-testable in isolation. Every
access is null-guarded (``or {}`` / ``or []``) exactly like the sibling
``_render_*_section`` code in main.py, so a pre-slice-6 generated_case with no
``audio_topology`` still yields a full, all-MISSING ledger.
"""

from __future__ import annotations

import re
from typing import Any

# ── B.1 Domain enum (framework-fixed, target-agnostic, rendered in this order) ──
DOMAINS: list[str] = [
    "power_model",
    "clocks",
    "dsp_subsystem",
    "lpass_macros",
    "soundwire",
    "codecs",
    "dt_topology",
    "audioreach_ports",
    "sid_iommu",
]

# ── B.2 Status enum ──
STATUS_CORROBORATED = "CORROBORATED"
STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"
STATUS_MISSING = "MISSING"
STATUS_VERIFY = "VERIFY"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"

# ── B.4 static field→domain table (the ONE new mapping) ──
# Keys are dotted ANALYSIS_SCHEMA field paths; values are the owning domain.
# A coverage test (tests/test_confidence_ledger.py) asserts every analyzable
# schema leaf is either mapped here or in FIELD_DOMAIN_EXCLUDED.
FIELD_DOMAIN_MAP: dict[str, str] = {
    "power_model": "power_model",
    "soundwire": "soundwire",
    "codecs": "codecs",
    "amplifiers": "codecs",
    "mics": "codecs",
    "speakers": "codecs",
    "audio_stack.adsp": "dsp_subsystem",
    "audio_stack.lpass": "lpass_macros",
    "audio_stack.audioreach": "audioreach_ports",
    "audio_stack.gpr": "audioreach_ports",
    "audio_stack.apm": "audioreach_ports",
    "audio_stack.q6apm": "audioreach_ports",
    "audio_stack.q6prm": "audioreach_ports",
    "buses": "dt_topology",
    "schematic_nets": "dt_topology",
}

# Schema leaves deliberately NOT tied to a ledger domain (identity/meta fields,
# not audio-subsystem trust domains). Listed so the coverage test is explicit
# about what is excluded rather than silently unmapped.
FIELD_DOMAIN_EXCLUDED: frozenset[str] = frozenset(
    {
        "soc",
        "board",
        "nearest_targets",
        "missing_evidence",
        "overall_confidence",
        "human_review_needed",
        "ipcat_findings",
    }
)

# Domains with no current analysis field — their row always renders (MISSING)
# until a source produces evidence. Logic intentionally deferred (spec §B, the
# "ship the enum fixed, implement roll-up only for domains that appear" rule).
_DERIVED_DOMAINS: frozenset[str] = frozenset({"clocks", "sid_iommu"})

# Governing KB rule IDs per domain (WP-A). The ledger *cites* the rule that
# governs a domain's trust without copying its text. Degrades gracefully to a
# blank cell for any domain with no published governing rule (e.g. codecs).
DOMAIN_RULE_MAP: dict[str, list[str]] = {
    "power_model": ["PROV-002", "ADSP-001"],
    "clocks": ["CLK-001"],
    "dsp_subsystem": ["PROV-001", "ADSP-001"],
    "lpass_macros": ["LPASS-001"],
    "soundwire": ["SWR-D1"],
    "codecs": [],
    "dt_topology": ["PROV-003"],
    "audioreach_ports": ["AR-001"],
    "sid_iommu": ["PROV-001"],
}

# missing_evidence free-text → domain keyword table (substring, lowercase).
_DOMAIN_MISSING_KEYWORDS: dict[str, tuple[str, ...]] = {
    "power_model": ("power", "rpmhpd", "scmi", "rail", "power-domain", "power domain"),
    "clocks": ("clock", "freq", "rate"),
    "dsp_subsystem": ("adsp", "dsp", "pas", "remoteproc", "q6dsp"),
    "lpass_macros": ("lpass", "macro"),
    "soundwire": ("soundwire", "swr"),
    "codecs": ("codec", "amplifier", "amp ", "mic", "speaker"),
    "dt_topology": ("device tree", "devicetree", "dtsi", "topology", " bus", "dt "),
    "audioreach_ports": ("audioreach", "gpr", "apm", "logical port", "logical-port", "q6apm", "q6prm", "port"),
    "sid_iommu": ("sid", "iommu", "smmu"),
}

# needs_review field-name → domain (prefix/substring match, lowercase).
_REVIEW_FIELD_DOMAIN: dict[str, str] = {
    "power_model": "power_model",
    "power_model_source": "power_model",
    "codec": "codecs",
    "soundwire": "soundwire",
    "audioreach": "audioreach_ports",
    "logical_port": "audioreach_ports",
    "clock": "clocks",
    "sid": "sid_iommu",
    "iommu": "sid_iommu",
    "lpass": "lpass_macros",
    "adsp": "dsp_subsystem",
}


def _dedup(seq: list[Any]) -> list[str]:
    """Order-preserving string dedup (deterministic)."""
    out: list[str] = []
    seen: set[str] = set()
    for x in seq or []:
        s = str(x)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _band(confidence: float | None) -> str:
    """B.3 coarse band. None → '—' to avoid false precision."""
    if confidence is None:
        return "—"
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.4:
        return "medium"
    return "low"


def _missing_domains(missing_evidence: list[str]) -> set[str]:
    """Domains named (by keyword) in the free-text missing_evidence list."""
    hit: set[str] = set()
    for note in missing_evidence or []:
        low = str(note).lower()
        for domain, kws in _DOMAIN_MISSING_KEYWORDS.items():
            if any(kw in low for kw in kws):
                hit.add(domain)
    return hit


def _review_domains(needs_review: list[str]) -> set[str]:
    """Domains flagged by the report's needs_review lines ('<field>: <note>')."""
    hit: set[str] = set()
    for line in needs_review or []:
        field = str(line).split(":", 1)[0].strip().lower()
        for key, domain in _REVIEW_FIELD_DOMAIN.items():
            if key in field:
                hit.add(domain)
    return hit


def _status_of(
    contribs: list[dict],
    *,
    domain_missing: bool,
    needs_review: bool,
    not_applicable: bool,
) -> str:
    """B.4 deterministic status derivation (pure).

    Precedence (definitive → fallback):
      1. NOT_APPLICABLE — domain provably absent for this target class.
      2. MISSING        — no contribs, or flagged missing with no positive evidence.
      3. NEEDS_REVIEW   — ungated/single-source flagged for review (e.g. power model
                          is never auto-finalized, so it stays NEEDS_REVIEW even if
                          multiply cited — the B.2 "ungated" case).
      4. VERIFY         — from an authoritative-but-unconfirmed source (inert until a
                          catalog source exists; kept per spec §B.4/§B.5).
      5. CORROBORATED   — ≥2 *genuinely independent, non-caveated* sources on the
                          governing (weakest) field. Guarded three ways (WP-B
                          refinement §3.1): (a) a boolean-only domain — no numeric
                          confidence on any contributor — can never reach
                          CORROBORATED on citation count alone; (b) a domain named
                          in missing_evidence is downgraded; (c) caveated citations
                          (e.g. "CAVEAT: none of this exists…") do not count toward
                          corroboration.
      6. NEEDS_REVIEW   — present but single-source / low-confidence.
    """
    if not_applicable:
        return STATUS_NOT_APPLICABLE

    positive = any(
        (c.get("present") is True) or (c.get("confidence") is not None) for c in contribs
    )
    if not contribs or (domain_missing and not positive):
        return STATUS_MISSING

    if needs_review:
        return STATUS_NEEDS_REVIEW

    governing = _governing(contribs)
    if governing.get("authoritative") and not governing.get("confirmed"):
        return STATUS_VERIFY

    # ── CORROBORATED guards (WP-B refinement §3.1: citation count ≠ corroboration) ──
    # (a) Boolean-only domain: no contributor carries a numeric confidence. Two
    #     lines on a single shared citation list (as audio_stack booleans emit)
    #     are not two independent sources. Such a domain is at most NEEDS_REVIEW.
    has_numeric = any(c.get("confidence") is not None for c in contribs)
    # (b) A domain the report itself flags in missing_evidence is not corroborated,
    #     even when a positive boolean is present (the boolean is the thing under
    #     doubt). Scoped to boolean-only domains so a numerically-confident domain
    #     that merely shares a missing_evidence keyword is unaffected.
    if not has_numeric and (domain_missing or _has_caveat(_governing_citations(contribs))):
        return STATUS_NEEDS_REVIEW

    # (c) Corroboration counts only genuine, non-caveated citations.
    trustworthy = _non_caveat(_dedup(governing.get("citations") or []))
    if has_numeric and len(trustworthy) >= 2:
        return STATUS_CORROBORATED

    return STATUS_NEEDS_REVIEW


def _governing(contribs: list[dict]) -> dict:
    """The field that drives the domain's band = the weakest (min-confidence)
    contributor. Ties / all-null → the first contributor (deterministic)."""
    numeric = [c for c in contribs if c.get("confidence") is not None]
    if numeric:
        return min(numeric, key=lambda c: c["confidence"])
    return contribs[0] if contribs else {}


def _governing_citations(contribs: list[dict]) -> list[str]:
    """Deduped citations on the governing contributor (deterministic)."""
    return _dedup(_governing(contribs).get("citations") or [])


# Words that mark a citation as *caveated* — evidence that undercuts, rather
# than supports, the domain it is attached to. Deliberately narrow: only markers
# that say the cited evidence itself is absent / fabricated / explicitly wrong.
# (Weaker qualifiers like "unapplied at HEAD" describe integration state, not
# whether the thing exists, and must NOT disqualify an otherwise-real source —
# e.g. Nord's codec, identified by both an unapplied DT patch *and* the present
# upstream driver, stays corroborated.) A caveated citation must never count
# toward corroboration (WP-B refinement §3.1).
_CAVEAT_RE = re.compile(
    r"caveat"
    r"|none of this exists"
    r"|does\s?n[o']t exist"
    r"|do not exist"
    r"|\bno such\b"
    r"|\bplaceholder\b"
    r"|\bfabricated\b"
    r"|\bwrong for\b",
    re.IGNORECASE,
)


def _has_caveat(cites: list[str]) -> bool:
    """True if any citation carries a caveat marker."""
    return any(_CAVEAT_RE.search(str(c)) for c in cites or [])


def _non_caveat(cites: list[str]) -> list[str]:
    """Citations with the caveated ones removed (for corroboration counting)."""
    return [str(c) for c in cites or [] if not _CAVEAT_RE.search(str(c))]


def _rollup(
    domain: str,
    contribs: list[dict],
    *,
    missing_domains: set[str],
    review_domains: set[str],
    not_applicable: bool,
) -> tuple[str, str, list[str], list[str]]:
    """Per-domain roll-up → (band, status, sources, rule_ids).

    band  : min-confidence coarse band (B.3) — weakest field governs.
    status: B.4 truth table.
    sources: deduped union of contributing citations (abbreviated to basenames).
    rule_ids: governing KB rule IDs (DOMAIN_RULE_MAP), blank when unpublished.
    """
    governing = _governing(contribs)
    band = _band(governing.get("confidence")) if contribs else "—"

    status = _status_of(
        contribs,
        domain_missing=domain in missing_domains,
        needs_review=domain in review_domains,
        not_applicable=not_applicable,
    )

    # A band on a NOT_APPLICABLE row is contradictory noise — if the domain does
    # not apply to this target class, there is nothing to be confident about
    # (WP-B refinement §3.4). Force '—'.
    if status == STATUS_NOT_APPLICABLE:
        band = "—"

    all_cites: list[str] = []
    for c in contribs:
        all_cites.extend(c.get("citations") or [])
    sources = _abbrev_citations(_dedup(all_cites))

    rule_ids = list(DOMAIN_RULE_MAP.get(domain, []))
    return band, status, sources, rule_ids


# A path token: two or more segments joined by '/' or '\'. Collapsed to its
# basename wherever it appears (leading, or embedded mid-sentence). This is what
# makes both a bare path citation and a "…present in <abs-path> — <note>" prose
# citation render cleanly.
_PATH_TOKEN = re.compile(r"(?:[\w.+-]*[/\\])+[\w.+-]+")
_PROSE_LIMIT = 60


def _basename(token: str) -> str:
    return token.replace("\\", "/").rstrip("/").split("/")[-1] or token


def _abbrev_one(cite: str) -> str:
    """Abbreviate a single citation for the compact evidence column.

    Real citations come in three shapes (WP-B refinement §3.2):
      * bare path      ``drivers/soc/qcom/apr.c:603``  → basename (+line);
      * prose          ``CAVEAT: none of this exists …`` → clip to a short lead;
      * mixed          ``… present in <abs-path> — <note>`` → collapse the path
                        to its basename, then clip.

    The old ``split('/')[-1]`` sliced an arbitrary trailing fragment from every
    prose citation; this collapses only genuine path tokens and clips the rest
    on a word boundary with an ellipsis.
    """
    s = _PATH_TOKEN.sub(lambda m: _basename(m.group(0)), str(cite).strip())
    if len(s) <= _PROSE_LIMIT:
        return s
    clipped = s[:_PROSE_LIMIT].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return f"{clipped}…"


def _abbrev_citations(cites: list[str], *, limit: int = 3) -> list[str]:
    """Abbreviate citations for a compact, reviewer-readable evidence column.

    Paths collapse to basenames; prose clips to a short lead with an ellipsis
    (WP-B refinement §3.2). Deduped and capped at ``limit`` with a '(+N more)'.
    """
    abbrev = _dedup([_abbrev_one(c) for c in cites])
    if len(abbrev) > limit:
        return abbrev[:limit] + [f"(+{len(abbrev) - limit} more)"]
    return abbrev


def _collect_contribs(at: dict, analysis: dict | None) -> dict[str, list[dict]]:
    """Gather per-domain contribution records from audio_topology (+ optional
    raw analysis for dt_topology fields that audio_topology does not carry)."""
    contribs: dict[str, list[dict]] = {d: [] for d in DOMAINS}

    # power_model
    pm = at.get("power_model") or {}
    if pm:
        contribs["power_model"].append(
            {
                "confidence": pm.get("confidence"),
                "citations": pm.get("citations") or [],
                "present": pm.get("kind") not in (None, "unknown"),
            }
        )

    # soundwire (present is False → NOT_APPLICABLE handled by caller)
    sw = at.get("soundwire") or {}
    if sw:
        contribs["soundwire"].append(
            {
                "confidence": sw.get("confidence"),
                "citations": sw.get("citations") or [],
                "present": sw.get("present"),
            }
        )

    # codecs — aggregate every codec-like list; each item is one source.
    for key in ("codecs", "amplifiers", "mics", "speakers"):
        for item in at.get(key) or []:
            if not isinstance(item, dict):
                continue
            contribs["codecs"].append(
                {
                    "confidence": item.get("confidence"),
                    "citations": item.get("citations") or [],
                    "present": True,
                }
            )

    # audio_stack booleans → dsp_subsystem / lpass_macros / audioreach_ports.
    # Robust to real emitted shapes (WP-B refinement §3.3): accept any truthy
    # value, not strictly ``is True``, and infer a present DSP subsystem from any
    # DSP-indicating signal (the Q6/APR stack — gpr/apm/q6apm/q6prm — runs *on*
    # the ADSP), so a present ADSP under a different key shape (e.g. no explicit
    # ``adsp`` key) is not mis-rendered MISSING.
    stack = at.get("audio_stack") or {}
    stack_cites = stack.get("citations") or []

    def _truthy(*keys: str) -> bool:
        return any(bool(stack.get(k)) for k in keys)

    if _truthy("adsp", "gpr", "apm", "q6apm", "q6prm"):
        contribs["dsp_subsystem"].append(
            {"confidence": None, "citations": stack_cites, "present": True}
        )
    if _truthy("lpass"):
        contribs["lpass_macros"].append(
            {"confidence": None, "citations": stack_cites, "present": True}
        )
    if _truthy("audioreach", "gpr", "apm", "q6apm", "q6prm"):
        contribs["audioreach_ports"].append(
            {"confidence": None, "citations": stack_cites, "present": True}
        )

    # dt_topology — only derivable from the raw analysis envelope (buses /
    # schematic_nets), which is absent at report-render time. When present it
    # contributes; otherwise dt_topology resolves to MISSING.
    src = analysis or {}
    if src.get("buses"):
        contribs["dt_topology"].append(
            {"confidence": None, "citations": [], "present": True}
        )
    for net in src.get("schematic_nets") or []:
        if isinstance(net, dict):
            contribs["dt_topology"].append(
                {"confidence": None, "citations": net.get("citations") or [], "present": True}
            )

    # clocks, sid_iommu — no source field yet (logic deferred): no contribs.
    return contribs


def build_ledger(gc: dict, analysis: dict | None = None) -> list[dict]:
    """Return one ledger row per fixed domain (B.1 order).

    Row shape: {domain, band, status, sources, rule_ids}. Pure and
    deterministic: identical input → identical output.
    """
    gc = gc or {}
    at = gc.get("audio_topology") or {}
    missing_evidence = at.get("missing_evidence") or (analysis or {}).get("missing_evidence") or []
    needs_review = gc.get("needs_review") or []

    missing_domains = _missing_domains(missing_evidence)
    review_domains = _review_domains(needs_review)
    # power_model policy: it is never auto-finalized. Its own needs_review flag
    # forces the NEEDS_REVIEW status (the B.2 "ungated" case) regardless of
    # citation count.
    if (at.get("power_model") or {}).get("needs_review") is True:
        review_domains.add("power_model")

    contribs_by_domain = _collect_contribs(at, analysis)

    rows: list[dict] = []
    for domain in DOMAINS:
        contribs = contribs_by_domain.get(domain, [])
        # NOT_APPLICABLE only for the one unambiguous absent-by-class signal we
        # have today: soundwire explicitly reported present == False.
        not_applicable = domain == "soundwire" and (at.get("soundwire") or {}).get("present") is False
        band, status, sources, rule_ids = _rollup(
            domain,
            contribs,
            missing_domains=missing_domains,
            review_domains=review_domains,
            not_applicable=not_applicable,
        )
        rows.append(
            {
                "domain": domain,
                "band": band,
                "status": status,
                "sources": sources,
                "rule_ids": rule_ids,
            }
        )
    return rows
