"""Phase-2A — Schematic ↔ IPCAT Cross-Verification Engine (pure Comparison Core).

Pure, deterministic. Zero I/O. Consumes a frozen snapshot produced by
``orchestrator/runners/crossverify_collector.py`` and a case dict ``gc``
carrying (a) ``audio_topology.element_counts`` for T3, and (b) the
schematic/design view for the remaining tracks (built in later WPs). Emits
:class:`~orchestrator.reasoning.crossverify_model.VerificationRow` values only.

WP3 in this file is the **regression anchor**: T3 delegates to the committed
WP-C lane (:func:`~orchestrator.reasoning.cardinality.compare_element_counts`,
pinned at commit ``28f2f07``) UNCHANGED, then translates each WP-C row into a
``VerificationRow`` via a total mapping (see :data:`_VERDICT_MAP`). No other
track is implemented here — tracks T1/T2/T4a/T4b/T5 are separate WPs and stay
un-imported until then. Only WP-C's public ``compare_element_counts`` is
touched; ``cardinality.py`` / ``cardinality_config.py`` are not modified.

Track_t3 accepts the WP1 signature ``(snapshot, gc, kb)`` for API parity with
the other tracks even though it consumes only ``gc``. The catalog lane is
already present in ``gc["audio_topology"]["element_counts"]`` at call time —
exactly the shape Phase-1C committed — so this track re-runs Phase-1C's
verdicts byte-for-byte and is the pipeline's regression anchor.
"""

from __future__ import annotations

from typing import Any

from orchestrator.reasoning.cardinality import compare_element_counts
from orchestrator.reasoning.crossverify_model import VerificationRow

# WP-C ``compare_element_counts`` returns ``counts`` keyed by
# :data:`orchestrator.reasoning.cardinality_config.SOURCE_NAME` values
# (``dt_count`` / ``evidence_count`` / ``proposal_count`` / ``catalog_count``),
# not by the raw lane keys. The catalog lane in that mapping is:
_WPC_CATALOG_SOURCE: str = "catalog_count"


def _strip_count(source_name: str) -> str:
    """``proposal_count`` → ``proposal``, ``dt_count`` → ``dt``, ... for reader-facing lane names."""
    return source_name[:-len("_count")] if source_name.endswith("_count") else source_name


# ── WP-C verdict → Phase-2A verdict mapping (total over WP-C's output) ──────
#
# WP-C can emit five verdict strings. The four the WP3 spec lists map 1-1;
# ``disagree`` (pre-SWI pairwise mismatch, no KB rule) is also mapped so the
# translation is total — an unmapped WP-C verdict would silently drop a row.
_VERDICT_MAP: dict[str, str] = {
    "agree": "MATCH",
    "disagree_with_authority": "DISAGREE_WITH_AUTHORITY",
    "not_cross_checkable": "NOT_CROSS_CHECKABLE",
    "benign_divergence": "PARTIAL_MATCH",
    "disagree": "DISAGREE_WITH_AUTHORITY",
}


def _authority(row: dict[str, Any]) -> dict[str, Any]:
    """Build the authority object for a WP-C row.

    When the ``catalog`` lane is present in ``row["counts"]`` the authority
    is the post-SWI IPCAT catalog (``IPCAT_DIRECT``, origin = the WP-C lane
    that surfaced it); otherwise no authority spoke this run and the row
    carries ``UNAVAILABLE``. The catalog value, when present, is copied
    verbatim so the reviewer can see what the authority actually said.
    """
    counts = row.get("counts") or {}
    if _WPC_CATALOG_SOURCE in counts:
        return {
            "strength": "IPCAT_DIRECT",
            "origin": "wp_c.cardinality_catalog",
            "value": counts[_WPC_CATALOG_SOURCE],
        }
    return {"strength": "UNAVAILABLE", "origin": "none"}


def _coverage_gap_reason(row: dict[str, Any]) -> str:
    """Only called when the mapped verdict is NOT_CROSS_CHECKABLE.

    WP-C emits ``not_cross_checkable`` from two precedence branches:
      1. ``ambiguous:true`` on the source → ``source_ambiguous``;
      2. ``< 2 usable lanes`` (nothing to compare) → ``insufficient_lanes``.
    """
    if row.get("ambiguous"):
        return "source_ambiguous"
    return "insufficient_lanes"


def _confidence(mapped_verdict: str, row: dict[str, Any]) -> str:
    """Confidence policy for T3 (V2 §2/T3, §2/T2 & WP-C asymmetry).

    * post-SWI (catalog lane present) MATCH / DISAGREE_WITH_AUTHORITY = ``high``;
    * pre-SWI pairwise MATCH (no catalog authority) = ``medium``;
    * PARTIAL_MATCH via a KB divergence rule = ``medium`` (rule downgrades it
      from a hard defect to informational, but not to certainty);
    * NOT_CROSS_CHECKABLE has no verdict-bearing signal → ``none``.
    """
    if mapped_verdict == "NOT_CROSS_CHECKABLE":
        return "none"
    counts = row.get("counts") or {}
    catalog_spoke = _WPC_CATALOG_SOURCE in counts
    if mapped_verdict in ("MATCH", "DISAGREE_WITH_AUTHORITY"):
        return "high" if catalog_spoke else "medium"
    # PARTIAL_MATCH
    return "medium"


def _review_actions(mapped_verdict: str, row: dict[str, Any]) -> list[str]:
    """One-line reviewer prompts, tuned to the verdict. Empty for MATCH."""
    cls = row.get("element_class", "?")
    counts = row.get("counts") or {}
    if mapped_verdict == "DISAGREE_WITH_AUTHORITY":
        catalog = counts.get(_WPC_CATALOG_SOURCE)
        others = {_strip_count(s): n for s, n in counts.items() if s != _WPC_CATALOG_SOURCE}
        others_str = ", ".join(f"{s}={n}" for s, n in others.items()) or "no other lanes"
        return [
            f"reconcile {cls}: catalog={catalog} vs {others_str}"
        ]
    if mapped_verdict == "NOT_CROSS_CHECKABLE":
        if row.get("ambiguous"):
            note = row.get("ambiguity_note") or "source flagged ambiguous"
            return [f"resolve source ambiguity on {cls}: {note}"]
        return [
            f"insufficient lanes to cross-check {cls}; add an independent count"
        ]
    if mapped_verdict == "PARTIAL_MATCH":
        rule = row.get("rule_id") or "KB rule"
        return [f"{cls} lane disagreement covered by {rule} (informational)"]
    # MATCH → no action
    return []


def _translate(row: dict[str, Any]) -> VerificationRow:
    """One WP-C row → one VerificationRow.

    ``track`` is always ``T3``. ``subject`` = element_class. ``source``
    carries every non-catalog lane the WP-C row surfaced (dt/evidence/proposal),
    so the reviewer sees exactly what the design side reported. ``authority``
    carries the catalog lane when present.
    """
    wpc_verdict = row.get("verdict")
    mapped = _VERDICT_MAP.get(wpc_verdict)
    if mapped is None:
        raise ValueError(f"unmapped WP-C verdict {wpc_verdict!r}")

    counts = row.get("counts") or {}
    source_lanes = {
        _strip_count(s): n for s, n in counts.items() if s != _WPC_CATALOG_SOURCE
    }

    notes = list(row.get("notes") or [])
    if row.get("ambiguous") and row.get("ambiguity_note"):
        notes.insert(0, f"ambiguous: {row['ambiguity_note']}")

    coverage_gap = _coverage_gap_reason(row) if mapped == "NOT_CROSS_CHECKABLE" else None

    return VerificationRow(
        track="T3",
        subject=row.get("element_class", "?"),
        verdict=mapped,
        source={"lanes": source_lanes} if source_lanes else None,
        authority=_authority(row),
        confidence=_confidence(mapped, row),
        coverage_gap_reason=coverage_gap,
        rule_id=row.get("rule_id"),
        review_actions=_review_actions(mapped, row),
        citations=list(row.get("citations") or []),
        notes=notes,
    )


def track_t3(
    snapshot: dict[str, Any],
    gc: dict[str, Any],
    kb: dict[str, Any] | None = None,
) -> list[VerificationRow]:
    """T3 — Audio Resource Validation via the unchanged WP-C lane.

    Pure delegation: hands ``gc`` to
    :func:`~orchestrator.reasoning.cardinality.compare_element_counts`
    (committed ``28f2f07``, not modified) and maps every emitted row to a
    :class:`VerificationRow`. Consumes only ``gc``; ``snapshot`` and ``kb``
    are accepted for API parity with the other tracks and are unused today
    (a future revision may pull the catalog lane out of the snapshot here).

    Ordering is preserved from WP-C's config-driven order — the anchor is
    a byte-for-byte reproduction of Phase-1C's verdicts.
    """
    del snapshot, kb  # explicitly unused in WP3
    return [_translate(row) for row in compare_element_counts(gc)]


# ─────────────────────────────────────────────────────────────────────────────
# WP4 — Track T1 (GPIO / Pinmux Validation)
# ─────────────────────────────────────────────────────────────────────────────
#
# T1 cross-checks each schematic-declared audio pin against the silicon's TLMM
# pinmux authority. The Phase-2A V2 spec (§2/T1, §3.1, §4) says:
#
#   * pin exists AND claimed function is a valid mux alternate → MATCH
#       (high confidence when the answer came from a direct function-field
#       lookup, i.e. gpio_list_gpios_from_map(function=…); medium when we
#       had to fall back to a name-heuristic scan over gpio_list_tlmm_gpios);
#   * pin exists, function muxable, secondary attribute differs → PARTIAL_MATCH
#       (a mux alternate exists on the same pin but the schematic's function
#       index disagrees with the authority — the historically prolific "wrong
#       fn number" cheerful mistake);
#   * pin exists but silicon cannot mux the claimed function at all →
#       DISAGREE_WITH_AUTHORITY (a hard defect: the pin is not muxable to
#       this function under any alternate);
#   * pin number absent on silicon → DISAGREE_WITH_AUTHORITY escalated to
#       REVIEW_REQUIRED (the design cites a pin the TLMM does not expose);
#   * authority tool absent from the snapshot → NOT_CROSS_CHECKABLE with
#       coverage_gap_reason=authority_unavailable.
#
# Authority-lookup path (see docs/PHASE2A_AUTHORITY_DISCOVERY.md):
#
#     Preferred (DIRECT):
#         gpio_get_gpio_map          → snapshot["tools"]["gpio_get_gpio_map"]
#         gpio_list_gpios_from_map   → snapshot["tools"]["gpio_list_gpios_from_map"]
#         function=<claimed>          (the parameterized function-field lookup
#                                      the collector's WP1 fires today).
#     Fallback (name-heuristic):
#         gpio_list_tlmm_gpios       → snapshot["tools"]["gpio_list_tlmm_gpios"]
#         scan for the pin number and match its `function` field.
#
# Every row's citations list carries the ``gpio_map:<release>`` provenance
# string (from ``snapshot["provenance"]["gpio_map"]["release"]``) so the
# reviewer knows which ChipIO release the authority spoke from.

_T1_AUTH_DIRECT: str = "ipcat.gpio_list_gpios_from_map"
_T1_AUTH_FALLBACK: str = "ipcat.gpio_list_tlmm_gpios"


def _t1_provenance_citation(snapshot: dict[str, Any]) -> list[str]:
    """Return the ``gpio_map:<release>`` citation string (V2 requirement 6).

    Recorded on every T1 row so a reviewer can trace which ChipIO release the
    authority came from. When the release is missing we still emit a placeholder
    so the row's provenance is not silently empty.
    """
    prov = (snapshot.get("provenance") or {}).get("gpio_map") or {}
    release = prov.get("release")
    if release:
        return [f"gpio_map:{release}"]
    return ["gpio_map:<release_unknown>"]


def _t1_authority_available(snapshot: dict[str, Any]) -> tuple[bool, bool]:
    """Return ``(direct_available, fallback_available)`` for a T1 snapshot.

    ``direct_available`` is True iff BOTH ``gpio_get_gpio_map`` and
    ``gpio_list_gpios_from_map`` are ``status == "ok"`` (the parameterized
    path needs the map id → the list result); ``fallback_available`` is True
    iff ``gpio_list_tlmm_gpios`` is ``status == "ok"``.
    """
    tools = snapshot.get("tools") or {}
    gm = tools.get("gpio_get_gpio_map") or {}
    fm = tools.get("gpio_list_gpios_from_map") or {}
    tl = tools.get("gpio_list_tlmm_gpios") or {}
    direct = gm.get("status") == "ok" and fm.get("status") == "ok"
    fallback = tl.get("status") == "ok"
    return direct, fallback


def _t1_index_gpios(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """Index a gpio-list payload by pin number.

    Each pin can appear multiple times when the authority enumerates its mux
    alternates (one row per (pin, function) pair). Callers scan the list-per-pin
    to decide MATCH vs PARTIAL_MATCH vs DISAGREE.
    """
    index: dict[int, list[dict[str, Any]]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        number = row.get("number")
        if not isinstance(number, int):
            continue
        index.setdefault(number, []).append(row)
    return index


def _t1_row(
    *,
    subject: str,
    verdict: str,
    source: Any,
    authority: dict[str, Any],
    confidence: str,
    coverage_gap_reason: str | None = None,
    review_actions: list[str] | None = None,
    citations: list[str],
    notes: list[str] | None = None,
) -> VerificationRow:
    """Small factory around :class:`VerificationRow` for T1's five verdict shapes."""
    return VerificationRow(
        track="T1",
        subject=subject,
        verdict=verdict,
        source=source,
        authority=authority,
        confidence=confidence,
        coverage_gap_reason=coverage_gap_reason,
        review_actions=list(review_actions or []),
        citations=list(citations),
        notes=list(notes or []),
    )


def _t1_lookup_pin(
    pin: int,
    claimed_function: int | None,
    direct_index: dict[int, list[dict[str, Any]]] | None,
    fallback_index: dict[int, list[dict[str, Any]]] | None,
) -> tuple[str, list[dict[str, Any]]]:
    """Decide which authority answered for ``pin`` and return its mux alternates.

    Preference order: DIRECT (function-field lookup via gpio_list_gpios_from_map),
    then FALLBACK (name-heuristic scan of gpio_list_tlmm_gpios). Returns
    ``(origin, alternates)`` where ``origin`` is one of ``_T1_AUTH_DIRECT`` /
    ``_T1_AUTH_FALLBACK`` and ``alternates`` is the list of authority rows for
    this pin (possibly empty when the authority has the pin listed nowhere).

    When neither index knows the pin, ``alternates`` is ``[]`` and ``origin``
    reflects the strongest authority we consulted (so the caller can still
    build a well-formed row citing where we looked).
    """
    del claimed_function  # informational — the caller does the actual match
    if direct_index is not None and pin in direct_index:
        return _T1_AUTH_DIRECT, direct_index[pin]
    if fallback_index is not None and pin in fallback_index:
        return _T1_AUTH_FALLBACK, fallback_index[pin]
    # Neither authority listed the pin. Report against whichever we were
    # willing to consult (DIRECT preferred).
    if direct_index is not None:
        return _T1_AUTH_DIRECT, []
    if fallback_index is not None:
        return _T1_AUTH_FALLBACK, []
    # Should not happen — callers gate on availability first.
    return _T1_AUTH_FALLBACK, []


def _t1_secondary_attrs_agree(
    source_entry: dict[str, Any], authority_row: dict[str, Any]
) -> tuple[bool, list[str]]:
    """Compare optional secondary attributes (direction, pad, special_condition).

    Returns ``(agrees, mismatches)`` where ``agrees`` is True when every
    secondary attribute the source declared also matches the authority's value
    (attributes the source did not declare are ignored — a PARTIAL_MATCH is not
    manufactured out of missing schematic data). ``mismatches`` is a list of
    ``"<attr>: source=<x> vs authority=<y>"`` strings for review actions.
    """
    mismatches: list[str] = []
    for attr in ("direction", "pad", "special_condition"):
        if attr not in source_entry:
            continue
        src_val = source_entry[attr]
        auth_val = authority_row.get(attr)
        if auth_val is None:
            continue
        if src_val != auth_val:
            mismatches.append(f"{attr}: source={src_val!r} vs authority={auth_val!r}")
    return not mismatches, mismatches


def _t1_source_iter(source: Any) -> list[dict[str, Any]]:
    """Extract the list of pin-claim dicts from the source view.

    Accepts either a top-level list, or a dict with an ``audio_pins`` /
    ``gpios`` / ``pins`` key. Each entry must carry at least ``pin`` (int) and
    ``function`` (int); other fields (``name``, ``direction``, ``pad``,
    ``special_condition``) are optional.
    """
    if source is None:
        return []
    if isinstance(source, list):
        return [e for e in source if isinstance(e, dict)]
    if isinstance(source, dict):
        for key in ("audio_pins", "gpios", "pins"):
            val = source.get(key)
            if isinstance(val, list):
                return [e for e in val if isinstance(e, dict)]
    return []


def track_t1(
    snapshot: dict[str, Any],
    source: Any,
    kb: dict[str, Any] | None = None,
) -> list[VerificationRow]:
    """T1 — GPIO / pinmux validation against IPCAT TLMM authority.

    Pure. Consumes:
      * ``snapshot["tools"]["gpio_get_gpio_map"]`` /
        ``snapshot["tools"]["gpio_list_gpios_from_map"]`` — the DIRECT
        parameterized path;
      * ``snapshot["tools"]["gpio_list_tlmm_gpios"]`` — the fallback path;
      * ``snapshot["provenance"]["gpio_map"]["release"]`` — recorded on
        every row's ``citations`` list;
      * ``source`` — a list of ``{pin:int, function:int, name?, ...}`` entries,
        or a dict wrapping such a list under ``audio_pins`` / ``gpios`` / ``pins``.

    Emits one :class:`VerificationRow` per source pin. When neither authority
    tool answered, emits a single ``NOT_CROSS_CHECKABLE`` row per pin with
    ``coverage_gap_reason=authority_unavailable``.

    ``kb`` is accepted for API parity with the other tracks and is unused today.
    """
    del kb  # explicitly unused in WP4

    entries = _t1_source_iter(source)
    citations = _t1_provenance_citation(snapshot)
    direct_ok, fallback_ok = _t1_authority_available(snapshot)

    if not entries:
        return []

    # Authority totally unavailable → one NOT_CROSS_CHECKABLE per pin.
    if not direct_ok and not fallback_ok:
        rows: list[VerificationRow] = []
        for entry in entries:
            pin = entry.get("pin")
            name = entry.get("name") or "?"
            subject = f"{name} (GPIO {pin})" if pin is not None else name
            rows.append(
                _t1_row(
                    subject=subject,
                    verdict="NOT_CROSS_CHECKABLE",
                    source=dict(entry),
                    authority={"strength": "UNAVAILABLE", "origin": "none"},
                    confidence="none",
                    coverage_gap_reason="authority_unavailable",
                    review_actions=[
                        "gpio_list_gpios_from_map and gpio_list_tlmm_gpios both "
                        "unavailable; re-run collector once IPCAT answers"
                    ],
                    citations=citations,
                )
            )
        return rows

    # Build authority indices (only when their tool answered).
    tools = snapshot.get("tools") or {}
    direct_index: dict[int, list[dict[str, Any]]] | None = None
    fallback_index: dict[int, list[dict[str, Any]]] | None = None
    if direct_ok:
        direct_payload = tools["gpio_list_gpios_from_map"].get("payload") or []
        direct_index = _t1_index_gpios(direct_payload)
    if fallback_ok:
        fallback_payload = tools["gpio_list_tlmm_gpios"].get("payload") or []
        fallback_index = _t1_index_gpios(fallback_payload)

    rows_out: list[VerificationRow] = []
    for entry in entries:
        pin = entry.get("pin")
        claimed_function = entry.get("function")
        name = entry.get("name") or "?"
        subject = f"{name} (GPIO {pin})" if pin is not None else name
        source_snapshot = dict(entry)

        # Malformed source: missing pin number. Best served as REVIEW_REQUIRED —
        # nothing about the silicon can be said until the schematic clarifies.
        if not isinstance(pin, int):
            rows_out.append(
                _t1_row(
                    subject=subject,
                    verdict="REVIEW_REQUIRED",
                    source=source_snapshot,
                    authority={"strength": "UNAVAILABLE", "origin": "none"},
                    confidence="none",
                    review_actions=[f"source entry has no valid pin number: {entry!r}"],
                    citations=citations,
                )
            )
            continue

        origin, alternates = _t1_lookup_pin(
            pin, claimed_function, direct_index, fallback_index
        )
        # Confidence policy (WP4 requirement 5):
        #   DIRECT lookup answered  → high
        #   fallback lookup answered → medium
        base_confidence = "high" if origin == _T1_AUTH_DIRECT else "medium"

        if not alternates:
            # Pin number absent on silicon → REVIEW_REQUIRED (V2 §2/T1).
            rows_out.append(
                _t1_row(
                    subject=subject,
                    verdict="REVIEW_REQUIRED",
                    source=source_snapshot,
                    authority={
                        "strength": "IPCAT_DIRECT",
                        "origin": origin,
                        "value": None,
                    },
                    confidence=base_confidence,
                    review_actions=[
                        f"pin {pin} not exposed by TLMM authority "
                        f"({origin}); confirm schematic pin number"
                    ],
                    citations=citations,
                    notes=[f"authority listed no rows for pin {pin}"],
                )
            )
            continue

        # Look for an exact (pin, function) match among the mux alternates.
        exact = next(
            (a for a in alternates if a.get("function") == claimed_function), None
        )
        if exact is not None:
            # Name is a primary identity attribute for T1 (not a "secondary"
            # attribute like direction/pad): if the schematic declared a name
            # and the authority's row for this (pin, function) carries a
            # different name, the schematic's function index is aimed at the
            # wrong signal — PARTIAL_MATCH, not MATCH.
            src_name = source_snapshot.get("name")
            auth_name = exact.get("name")
            if (
                src_name is not None
                and auth_name is not None
                and src_name != auth_name
            ):
                rows_out.append(
                    _t1_row(
                        subject=subject,
                        verdict="PARTIAL_MATCH",
                        source=source_snapshot,
                        authority={
                            "strength": "IPCAT_DIRECT",
                            "origin": origin,
                            "value": {
                                "pin": pin,
                                "function": exact.get("function"),
                                "name": auth_name,
                                "alternates": [
                                    {"function": a.get("function"), "name": a.get("name")}
                                    for a in alternates
                                ],
                            },
                        },
                        confidence=base_confidence,
                        review_actions=[
                            f"pin {pin} function {claimed_function} carries name "
                            f"{auth_name!r}, not {src_name!r} — check schematic "
                            f"function index"
                        ],
                        citations=citations,
                    )
                )
                continue

            agrees, mismatches = _t1_secondary_attrs_agree(source_snapshot, exact)
            if agrees:
                rows_out.append(
                    _t1_row(
                        subject=subject,
                        verdict="MATCH",
                        source=source_snapshot,
                        authority={
                            "strength": "IPCAT_DIRECT",
                            "origin": origin,
                            "value": {
                                "pin": pin,
                                "function": exact.get("function"),
                                "name": exact.get("name"),
                            },
                        },
                        confidence=base_confidence,
                        citations=citations,
                    )
                )
            else:
                rows_out.append(
                    _t1_row(
                        subject=subject,
                        verdict="PARTIAL_MATCH",
                        source=source_snapshot,
                        authority={
                            "strength": "IPCAT_DIRECT",
                            "origin": origin,
                            "value": {
                                "pin": pin,
                                "function": exact.get("function"),
                                "name": exact.get("name"),
                            },
                        },
                        confidence=base_confidence,
                        review_actions=[
                            f"secondary attributes disagree on pin {pin}: "
                            + "; ".join(mismatches)
                        ],
                        citations=citations,
                    )
                )
            continue

        # No (pin, function) exact match. Pin is muxable — see all alternates:
        #   * one of them shares the schematic's *name* on a different function
        #     index → PARTIAL_MATCH (wrong fn number, right identity — the
        #     GPIO 61 aud_intfc0_data2 fn1 vs aud_intfc10_clk fn2 shape);
        #   * otherwise → DISAGREE_WITH_AUTHORITY (function not muxable here).
        claimed_name = source_snapshot.get("name")
        name_alt = None
        if claimed_name is not None:
            name_alt = next(
                (a for a in alternates if a.get("name") == claimed_name), None
            )

        if name_alt is not None:
            rows_out.append(
                _t1_row(
                    subject=subject,
                    verdict="PARTIAL_MATCH",
                    source=source_snapshot,
                    authority={
                        "strength": "IPCAT_DIRECT",
                        "origin": origin,
                        "value": {
                            "pin": pin,
                            "function": name_alt.get("function"),
                            "name": name_alt.get("name"),
                            "alternates": [
                                {"function": a.get("function"), "name": a.get("name")}
                                for a in alternates
                            ],
                        },
                    },
                    confidence=base_confidence,
                    review_actions=[
                        f"pin {pin} muxes {claimed_name!r} on function "
                        f"{name_alt.get('function')}, not {claimed_function}"
                    ],
                    citations=citations,
                )
            )
            continue

        # No alternate carried the claimed function OR the claimed name → the
        # silicon cannot mux this pin to the requested signal.
        alt_summary = ", ".join(
            f"fn{a.get('function')}={a.get('name')}" for a in alternates
        )
        rows_out.append(
            _t1_row(
                subject=subject,
                verdict="DISAGREE_WITH_AUTHORITY",
                source=source_snapshot,
                authority={
                    "strength": "IPCAT_DIRECT",
                    "origin": origin,
                    "value": {
                        "pin": pin,
                        "alternates": [
                            {"function": a.get("function"), "name": a.get("name")}
                            for a in alternates
                        ],
                    },
                },
                confidence=base_confidence,
                review_actions=[
                    f"pin {pin} cannot mux function {claimed_function} "
                    f"(claimed name={claimed_name!r}); alternates: {alt_summary}"
                ],
                citations=citations,
            )
        )

    return rows_out
