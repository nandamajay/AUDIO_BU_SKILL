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


# ─────────────────────────────────────────────────────────────────────────────
# WP5 — Track T2 (Bus / SoundWire-Master Validation)
# ─────────────────────────────────────────────────────────────────────────────
#
# T2 cross-checks the schematic's SoundWire-master count against the IPCAT SWI
# catalog. The Phase-2A V2 spec (§2/T2, §3.1, §4) says:
#
#   * source ``soundwire.present == false`` AND catalog union count == 0
#       → MATCH (Nord's I2S-only case; both sides agree there is no SWR block);
#   * source ``master_count`` == catalog union count (both > 0) → MATCH;
#   * counts differ → DISAGREE_WITH_AUTHORITY (warning=True by default);
#   * source self-flagged ``ambiguous == true`` → NOT_CROSS_CHECKABLE
#       (coverage_gap_reason=source_ambiguous);
#   * any SWI term hit its result cap → verdict marked *provisional*
#       (confidence downgraded, caveat recorded in ``notes``/``review_actions``);
#   * ``swi_search_swi`` unavailable in the snapshot → NOT_CROSS_CHECKABLE
#       with coverage_gap_reason=authority_unavailable.
#
# Counting discipline (W4): the union counter draws on the three soundwire-
# relevant terms {SOUNDWIRE_MASTER, SWR_MSTR, SWR}. For each term whose per-term
# entry has status="ok", the counter walks the payload's ``results`` list and
# adds each distinct named block (by ``name``/``symbol``/``module`` — first non-
# empty key wins) into a set. ``len(set)`` is the count. ``total_hits`` is
# **never** consulted; ``len()`` of a mislabeled field is **never** used;
# per-term entries whose status != "ok" are ignored for counting (but their
# ``queries`` are still recorded in the citation for full provenance).
#
# The snapshot wire shape (produced by ``crossverify_collector.py``):
#
#     snapshot["tools"]["swi_search_swi"] = {
#         "status": "ok" | "unavailable",
#         "payload": {
#             "SOUNDWIRE_MASTER": {"status": "ok", "payload": {...}},
#             "SWR_MSTR":         {"status": "ok" | "unavailable", ...},
#             "SWR":              {"status": "ok" | "unavailable", ...},
#             "LPASS_MACRO":      {...},   # not consumed by T2
#             "LPASS":            {...},   # not consumed by T2
#         },
#         "result_digest": <sha256 hex | None>,
#         "queries":       ["SOUNDWIRE_MASTER", "SWR_MSTR", "SWR", "LPASS_MACRO", "LPASS"],
#         # status == "unavailable" also carries "error_class": "all_swi_queries_failed"
#     }

_T2_AUTH_ORIGIN: str = "ipcat.swi_search_swi"
_T2_SOUNDWIRE_TERMS: tuple[str, ...] = ("SOUNDWIRE_MASTER", "SWR_MSTR", "SWR")

#: A per-term result list at/above this many rows is treated as *possibly*
#: truncated by the SWI backend's search cap. Downstream the verdict is marked
#: provisional and confidence is downgraded. Chosen to match the SWI backend's
#: default page size; the exact cap is opaque to us so we conservatively assume
#: any full-page response could be capped.
_T2_SWI_RESULT_CAP: int = 25


def _t2_source_view(source: Any) -> dict[str, Any]:
    """Unwrap a schematic-side source view for T2.

    Accepts either the raw soundwire dict at the top level, or a wrapper dict
    with keys like ``soundwire`` / ``buses`` / ``audio_topology``. Returns
    ``{}`` for anything unusable — the caller then falls back to policy
    defaults (present unknown, master_count unknown, ambiguous unknown).
    """
    if source is None:
        return {}
    if not isinstance(source, dict):
        return {}
    # explicit wrapping keys — first non-empty wins
    for key in ("soundwire", "buses", "audio_topology"):
        wrapped = source.get(key)
        if isinstance(wrapped, dict) and wrapped:
            # audio_topology sometimes wraps soundwire under another key
            inner = wrapped.get("soundwire")
            if isinstance(inner, dict) and inner:
                return inner
            return wrapped
    return source


def _t2_named_block_id(entry: Any) -> str | None:
    """Return a stable identity string for one SWI result row, or None.

    Set-stability picks the first non-empty key of (name, symbol, module). A
    row with no identifier at all is ignored — we never trust an unlabeled
    hit as a distinct block, since collapsing multiple such hits would
    understate the count and treating each one as distinct would inflate it.
    """
    if not isinstance(entry, dict):
        return None
    for key in ("name", "symbol", "module"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _t2_iter_result_rows(term_payload: Any) -> list[dict[str, Any]]:
    """Yield the per-hit rows from a single SWI term's payload.

    SWI returns a dict with a top-level ``results`` list (see the collector's
    FakeTransport fixture). Any other shape is treated as empty — we never
    ``len()`` a mislabeled field.
    """
    if not isinstance(term_payload, dict):
        return []
    results = term_payload.get("results")
    if isinstance(results, list):
        return [r for r in results if isinstance(r, dict)]
    return []


def _t2_union_count(swi_payload: dict[str, Any]) -> tuple[int, bool, list[str]]:
    """Return ``(distinct_block_count, at_cap, terms_used)`` for the three soundwire terms.

    Walks the per-term breakdown ``swi_payload[term]``; for each term whose
    status is ``ok`` it takes the ``results`` list, extracts a stable identity
    per row, and adds it to a growing set. ``at_cap`` is True iff any *healthy*
    term returned a page at/above ``_T2_SWI_RESULT_CAP`` (possible truncation
    → provisional). ``terms_used`` is the ordered list of terms whose payload
    contributed.
    """
    seen: set[str] = set()
    at_cap = False
    used: list[str] = []
    for term in _T2_SOUNDWIRE_TERMS:
        per_term = swi_payload.get(term) if isinstance(swi_payload, dict) else None
        if not isinstance(per_term, dict):
            continue
        if per_term.get("status") != "ok":
            continue
        used.append(term)
        rows = _t2_iter_result_rows(per_term.get("payload"))
        if len(rows) >= _T2_SWI_RESULT_CAP:
            at_cap = True
        for row in rows:
            block_id = _t2_named_block_id(row)
            if block_id is not None:
                seen.add(block_id)
    return len(seen), at_cap, used


def _t2_provenance_citation(
    snapshot: dict[str, Any], terms_used: list[str]
) -> list[str]:
    """Return the ``swi_search_swi:<terms>`` provenance citation.

    Always recorded (V2 requirement 6 parity with T1's ``gpio_map:`` line) so
    a reviewer can see which SWI terms actually spoke. When no term spoke, the
    citation lists the terms in the snapshot's declared ``queries`` field
    (the three soundwire terms intersected with what the collector actually
    fired) so provenance is never silently empty.
    """
    tools = snapshot.get("tools") or {}
    swi = tools.get("swi_search_swi") or {}
    if terms_used:
        return [f"swi_search_swi:{'+'.join(terms_used)}"]
    # No healthy term spoke — record the declared query set for provenance.
    declared = swi.get("queries") or list(_T2_SOUNDWIRE_TERMS)
    intersected = [t for t in declared if t in _T2_SOUNDWIRE_TERMS] or list(
        _T2_SOUNDWIRE_TERMS
    )
    return [f"swi_search_swi:<none_of:{'+'.join(intersected)}>"]


def _t2_row(
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
    """Small factory around :class:`VerificationRow` for T2's verdict shapes."""
    return VerificationRow(
        track="T2",
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


def track_t2(
    snapshot: dict[str, Any],
    source: Any,
    kb: dict[str, Any] | None = None,
) -> list[VerificationRow]:
    """T2 — Bus / SoundWire-Master validation via ``swi_search_swi``.

    Consumes only ``snapshot["tools"]["swi_search_swi"]`` (per WP5 requirement
    1) and the schematic-side ``source`` view. Emits exactly one row on the
    subject ``"soundwire_master"``. Never touches ``kb`` in this WP.

    Decision tree (WP5 requirement 3, precedence top-down):
      1. ``swi_search_swi.status == "unavailable"`` → NOT_CROSS_CHECKABLE
         (authority_unavailable, confidence=none);
      2. Source self-flagged ``ambiguous: true`` → NOT_CROSS_CHECKABLE
         (source_ambiguous, confidence=none);
      3. Source ``present == false`` AND catalog union count == 0 → MATCH;
      4. Source ``master_count`` == catalog union count (both > 0) → MATCH;
      5. Otherwise counts differ → DISAGREE_WITH_AUTHORITY (warning=True);
      6. Any healthy term at/above ``_T2_SWI_RESULT_CAP`` → verdict marked
         provisional (confidence downgraded from ``high`` to ``provisional``,
         caveat recorded in notes and appended to review_actions).
    """
    del kb  # T2 does not consult the KB in this WP

    subject = "soundwire_master"
    src_view = _t2_source_view(source)
    src_present = src_view.get("present")
    src_master_count_raw = src_view.get("master_count")
    src_master_count = (
        int(src_master_count_raw)
        if isinstance(src_master_count_raw, int)
        else None
    )
    src_ambiguous = bool(src_view.get("ambiguous"))

    tools = snapshot.get("tools") or {}
    swi = tools.get("swi_search_swi") or {}
    swi_status = swi.get("status")

    # 1. authority unavailable
    if swi_status != "ok":
        return [
            _t2_row(
                subject=subject,
                verdict="NOT_CROSS_CHECKABLE",
                source={
                    "present": src_present,
                    "master_count": src_master_count,
                    "ambiguous": src_ambiguous,
                }
                if src_view
                else None,
                authority={"strength": "UNAVAILABLE", "origin": "none"},
                confidence="none",
                coverage_gap_reason="authority_unavailable",
                citations=_t2_provenance_citation(snapshot, terms_used=[]),
                review_actions=[
                    "swi_search_swi unavailable; re-run collector to obtain SWI catalog"
                ],
                notes=["swi_search_swi returned no usable payload for the three soundwire terms"],
            )
        ]

    # Compute catalog union count from the per-term payload
    swi_payload = swi.get("payload") if isinstance(swi.get("payload"), dict) else {}
    catalog_count, at_cap, terms_used = _t2_union_count(swi_payload)
    citations = _t2_provenance_citation(snapshot, terms_used)

    # 2. source ambiguous
    if src_ambiguous:
        ambiguity_note = src_view.get("ambiguity_note") or "source flagged ambiguous"
        return [
            _t2_row(
                subject=subject,
                verdict="NOT_CROSS_CHECKABLE",
                source={
                    "present": src_present,
                    "master_count": src_master_count,
                    "ambiguous": True,
                },
                authority={
                    "strength": "IPCAT_DIRECT",
                    "origin": _T2_AUTH_ORIGIN,
                    "value": {"soundwire_master_count": catalog_count},
                },
                confidence="none",
                coverage_gap_reason="source_ambiguous",
                citations=citations,
                review_actions=[f"resolve source ambiguity on soundwire: {ambiguity_note}"],
                notes=[f"catalog union count = {catalog_count} across {terms_used or 'no terms'}"],
            )
        ]

    # Build the authority object for the count-comparison branches
    authority = {
        "strength": "IPCAT_DIRECT",
        "origin": _T2_AUTH_ORIGIN,
        "value": {"soundwire_master_count": catalog_count},
    }
    source_out = {
        "present": src_present,
        "master_count": src_master_count,
        "ambiguous": False,
    }

    # 3. I2S-only case: source says no SWR AND catalog union is empty
    if src_present is False and catalog_count == 0:
        confidence = "provisional" if at_cap else "high"
        notes = [
            f"soundwire.present=False and catalog union count=0 across {terms_used or 'no terms'} → MATCH (I2S-only)"
        ]
        review_actions: list[str] = []
        if at_cap:
            notes.append(
                f"one or more SWI terms returned {_T2_SWI_RESULT_CAP} rows (result cap possibly hit); "
                "confidence downgraded to provisional"
            )
            review_actions.append(
                "SWI result cap possibly hit; re-run with higher page size to confirm set stability"
            )
        return [
            _t2_row(
                subject=subject,
                verdict="MATCH",
                source=source_out,
                authority=authority,
                confidence=confidence,
                citations=citations,
                review_actions=review_actions,
                notes=notes,
            )
        ]

    # 4./5. count comparison — both sides have a count
    if src_master_count is not None and src_master_count == catalog_count:
        verdict = "MATCH"
        review_actions = []
    else:
        verdict = "DISAGREE_WITH_AUTHORITY"
        review_actions = [
            f"reconcile soundwire_master: source={src_master_count!r} vs catalog={catalog_count} "
            f"(union of {terms_used or _T2_SOUNDWIRE_TERMS})"
        ]

    confidence = "provisional" if at_cap else "high"
    notes = [
        f"catalog union count = {catalog_count} across {terms_used or 'no terms'}; "
        f"source master_count = {src_master_count!r}, present = {src_present!r}"
    ]
    if at_cap:
        notes.append(
            f"one or more SWI terms returned {_T2_SWI_RESULT_CAP} rows (result cap possibly hit); "
            "confidence downgraded to provisional"
        )
        review_actions.append(
            "SWI result cap possibly hit; re-run with higher page size to confirm set stability"
        )

    return [
        _t2_row(
            subject=subject,
            verdict=verdict,
            source=source_out,
            authority=authority,
            confidence=confidence,
            citations=citations,
            review_actions=review_actions,
            notes=notes,
        )
    ]


# ─────────────────────────────────────────────────────────────────────────────
# WP6 — Track T5 (DTS Consistency Validation)
# ─────────────────────────────────────────────────────────────────────────────
#
# T5 cross-checks device-tree fragments against the IPCAT silicon-identity
# authority (``chips_list_chips``). It looks for two failure modes:
#
#   * *donor-family leaks* — a DTS fragment matching a namespace pattern from
#     another silicon family (e.g. ``qcom,sa8775p-adsp-pas`` in a Nord DTS,
#     ``sa8775p/adsp.mbn`` firmware path, rpmhpd LCX/LMX power-domain refs)
#     under a chip whose canonical family is NOT that donor. Each such match
#     emits a DISAGREE_WITH_AUTHORITY row (warning=True by default) with a
#     reviewer-facing review action naming the target-family replacement.
#   * *unpinned revision* — a DTS that declares neither ``qcom,board-id`` nor
#     ``qcom,msm-id`` cannot be cross-checked against a specific silicon
#     revision; a single NOT_CROSS_CHECKABLE row with coverage_gap_reason
#     ``revision_not_pinned`` is emitted so this shows up on the review page.
#
# When ``chips_list_chips`` is unavailable, T5 falls back to the source-declared
# family (attached to the DTS payload dict under ``family``/``silicon_family``/
# ``soc_family``). Donor rules are still evaluated but at *medium* confidence
# and citations carry ``chips_list_chips:<unavailable>`` for provenance. If no
# source family is declared either, a single silicon-identity NOT_CROSS_CHECKABLE
# row is emitted (coverage_gap_reason=authority_unavailable) and donor rules
# are skipped entirely — we won't guess a family from the very DTS the check
# would evaluate, since that lets a donor leak declare itself legal.
#
# The KB rules (donor patterns, target-family expected prefixes, meta-rule ids)
# live in ``orchestrator/reasoning/crossverify_config.py``. This module never
# hard-codes any pattern text — it only reads that config.

import re as _t5_re

from orchestrator.reasoning.crossverify_config import (
    T5_DONOR_RULES as _T5_DONOR_RULES,
    T5_META_RULES as _T5_META_RULES,
    T5_TARGET_IDENTITY as _T5_TARGET_IDENTITY,
)

_T5_AUTH_ORIGIN: str = "ipcat.chips_list_chips"
_T5_SUBJECT_IDENTITY: str = "silicon_identity"
_T5_SUBJECT_REVISION: str = "dts.revision_anchor"

#: Regex that pulls a canonical family token out of an IPCAT chip name. Examples:
#: ``"SA8797P (NordAU) v2"`` → ``"sa8797p"``; ``"SA8775P (LeMans)"`` → ``"sa8775p"``.
_T5_FAMILY_RE = _t5_re.compile(
    r"\b(?P<fam>SA[0-9]{4}P|SM[0-9]{4}|QRB[0-9]+P?|SC[0-9]{4})\b",
    _t5_re.IGNORECASE,
)

#: Regexes that detect the two DTS revision-anchor properties.
_T5_BOARD_ID_RE = _t5_re.compile(r"qcom,board-id\b")
_T5_MSM_ID_RE = _t5_re.compile(r"qcom,msm-id\b")


def _t5_flatten_dts(dts: Any) -> str:
    """Coerce the T5 ``dts`` input into a single string for pattern matching.

    Accepts (WP6 requirement 2):

      * raw string → returned verbatim;
      * dict with ``dts`` / ``text`` / ``content`` key → its string value;
      * list of any of the above (multi-file) → their newline-joined
        concatenation so patterns can match across files;
      * anything else (None, empty, unusable) → ``""``.

    Never raises. The one behavioral choice: multi-file inputs are joined with
    ``"\n"`` so a donor pattern spanning two files would still hit if the raw
    text had spanned them — but the individual patterns in the KB are all
    single-token, so in practice this only ensures no cross-file gap swallows
    a pattern's leading anchor.
    """
    if dts is None:
        return ""
    if isinstance(dts, str):
        return dts
    if isinstance(dts, dict):
        for key in ("dts", "text", "content"):
            value = dts.get(key)
            if isinstance(value, str):
                return value
        return ""
    if isinstance(dts, list):
        parts: list[str] = []
        for item in dts:
            parts.append(_t5_flatten_dts(item))
        return "\n".join(parts)
    return ""


def _t5_source_meta(dts: Any) -> dict[str, Any]:
    """Extract the ``family``/``silicon_family``/``soc_family`` keys from ``dts``.

    Returns ``{}`` when ``dts`` isn't a dict or doesn't declare a family key.
    The source-declared family is the *only* fallback authority — we refuse to
    infer family from the DTS body itself (donor leaks would then legitimize
    themselves).
    """
    if not isinstance(dts, dict):
        return {}
    picked: dict[str, Any] = {}
    for key in ("family", "silicon_family", "soc_family"):
        if key in dts:
            picked[key] = dts[key]
    return picked


def _t5_normalize_family(token: Any) -> str | None:
    """Return a lower-case canonical family token (e.g. ``"sa8797p"``), or None."""
    if not isinstance(token, str) or not token.strip():
        return None
    match = _T5_FAMILY_RE.search(token)
    if match:
        return match.group("fam").lower()
    return None


def _t5_authority_family(snapshot: dict[str, Any]) -> tuple[str | None, str, str]:
    """Read the silicon identity from ``chips_list_chips`` in ``snapshot``.

    Returns ``(canonical_family, chip_name, status)`` where ``status`` is:

      * ``"ok"`` — payload yielded a well-formed family token;
      * ``"empty"`` — tool ran successfully but nothing usable came back;
      * ``"unavailable"`` — tool entry missing or status != "ok".

    ``chip_name`` is a short display label suitable for citations. It's
    ``"<unavailable>"`` whenever ``status != "ok"``.
    """
    tools = snapshot.get("tools") or {}
    entry = tools.get("chips_list_chips")
    if not isinstance(entry, dict):
        return None, "<unavailable>", "unavailable"
    if entry.get("status") != "ok":
        return None, "<unavailable>", "unavailable"
    payload = entry.get("payload")
    rows: list[Any] = []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        for key in ("chips", "results", "items"):
            maybe = payload.get(key)
            if isinstance(maybe, list):
                rows = maybe
                break
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name") or row.get("chip_name") or row.get("alias")
        family = _t5_normalize_family(name)
        if family is not None:
            return family, str(name), "ok"
    return None, "<unavailable>", "empty"


def _t5_has_revision_pin(dts_text: str) -> bool:
    """True iff the DTS text declares ``qcom,board-id`` OR ``qcom,msm-id``."""
    if not dts_text:
        return False
    return bool(_T5_BOARD_ID_RE.search(dts_text)) or bool(_T5_MSM_ID_RE.search(dts_text))


def _t5_matching_donor_rules(
    dts_text: str,
    target_family: str | None,
) -> list[tuple[dict[str, str], list[str]]]:
    """Return ``[(rule, matched_strings)]`` for donor rules that fire against ``dts_text``.

    A rule fires when:

      * its ``pattern`` (regex, compiled with ``re.findall``) returns ≥ 1 hit
        in ``dts_text``; AND
      * its declared ``family`` is NOT ``target_family`` (rules whose family
        matches the target are the target's own namespace, not a donor leak).

    ``matched_strings`` is the ordered list of literal matches (deduped, first
    occurrence preserved). Preserving order matters for determinism: the
    review action quotes the first match, so a fixed order → fixed output.
    """
    if not dts_text:
        return []
    hits: list[tuple[dict[str, str], list[str]]] = []
    for rule in _T5_DONOR_RULES:
        if target_family and rule.get("family") == target_family:
            continue
        pattern = rule.get("pattern") or ""
        try:
            matches = _t5_re.findall(pattern, dts_text)
        except _t5_re.error:
            # A misauthored KB pattern shouldn't crash T5; skip and continue.
            continue
        if not matches:
            continue
        strs: list[str] = []
        for m in matches:
            # Non-capturing groups produce strings; capturing groups would
            # produce tuples — the KB uses only (?:...) but be defensive.
            s = m if isinstance(m, str) else (m[0] if m else "")
            if s and s not in strs:
                strs.append(s)
        if strs:
            hits.append((rule, strs))
    return hits


def _t5_review_action_for(
    rule: dict[str, str],
    strs: list[str],
    target_family: str | None,
) -> str:
    """Compose the reviewer-facing review action for a donor-rule hit.

    Phrasing follows WP6 requirement 6: name the offending fragment, name the
    target family, and (for compatible/firmware) quote the target's expected
    prefix from :data:`T5_TARGET_IDENTITY`.
    """
    kind = rule.get("kind") or "misc"
    donor_family = rule.get("family") or "<donor>"
    example = strs[0] if strs else "<match>"
    target = target_family or "<target-family>"
    target_meta = _T5_TARGET_IDENTITY.get(target) or {}
    if kind == "compatible":
        return (
            f"replace {example!r} with the {target.upper()}-family compatible "
            f"(expected prefix {target_meta.get('expected_compatible_prefix', '<unknown>')!r})"
        )
    if kind == "firmware":
        return (
            f"correct firmware path: change {example!r} to the {target.upper()}-family "
            f"firmware path (expected prefix {target_meta.get('expected_firmware_prefix', '<unknown>')!r})"
        )
    if kind == "power_domain":
        return (
            f"power-domain namespace (LCX/LMX from {donor_family}) is LeMans/rpmhpd-specific; "
            f"target uses {target_meta.get('power_domain_style', 'scmi')} power domains — "
            f"replace {example!r} with scmiN_pd refs"
        )
    return (
        f"remove donor-family fragment {example!r} ({donor_family}/{kind}); "
        f"target family is {target}"
    )


def _t5_citations(chip_name: str, rule_id: str) -> list[str]:
    """Return the two citations every T5 row must carry (WP6 requirement 7)."""
    return [f"chips_list_chips:{chip_name}", f"kb.rule:{rule_id}"]


def _t5_row(
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
    """Small factory around :class:`VerificationRow` for T5's verdict shapes."""
    return VerificationRow(
        track="T5",
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


def track_t5(
    snapshot: dict[str, Any],
    dts: Any,
    kb: dict[str, Any] | None = None,
) -> list[VerificationRow]:
    """T5 — DTS Consistency Validation via ``chips_list_chips``.

    Consumes only ``snapshot["tools"]["chips_list_chips"]`` from the snapshot
    (WP6 requirement 1). Other DTS facts come from ``dts``, which may be
    a string, a dict with a ``dts``/``text``/``content`` key (optionally
    carrying ``family``/``silicon_family``/``soc_family`` for the fallback
    path), a list of such dicts (multi-file, concatenated), or empty/None.

    KB rules (donor patterns, target-family expected prefixes) live in
    :mod:`orchestrator.reasoning.crossverify_config`. ``kb`` is reserved for
    future opt-in overrides and is not consulted here.

    Decision tree (WP6 requirement 4, precedence top-down):

      1. ``chips_list_chips`` available (status == "ok" AND yields a family):

         * emit one ``DISAGREE_WITH_AUTHORITY`` row (confidence=high,
           warning=True) per donor rule that matches the DTS text and whose
           declared family is NOT the authority's target family;
         * donor rules that match AND ARE the target family are ignored
           (they are the target's own namespace, not a leak);
         * if no donor matches and DTS has no ``qcom,board-id`` /
           ``qcom,msm-id`` → one ``NOT_CROSS_CHECKABLE`` row
           (revision_not_pinned, confidence=none). The revision-anchor row
           is emitted alongside any donor rows when both fire.

      2. ``chips_list_chips`` unavailable, and ``dts`` carries a
         source-declared family key:

         * donor rules still evaluated, but confidence downgrades to
           ``medium`` and citations carry ``chips_list_chips:<unavailable>``;
         * authority strength downgrades to ``KB_RULE``;
         * revision-anchor NCC row still emitted when applicable.

      3. ``chips_list_chips`` unavailable AND no source-declared family:

         * one silicon-identity ``NOT_CROSS_CHECKABLE`` row
           (authority_unavailable, confidence=none). Donor rules are skipped
           entirely — we won't infer family from a DTS whose donor leak is
           exactly what T5 is meant to find.
    """
    del kb  # T5 does not consult the KB parameter in this WP

    dts_text = _t5_flatten_dts(dts)
    source_meta = _t5_source_meta(dts)
    authority_family, chip_name, auth_status = _t5_authority_family(snapshot)
    rows: list[VerificationRow] = []

    # ── Path 1: authority available ─────────────────────────────────────────
    if auth_status == "ok":
        target = authority_family  # invariant: not None when auth_status == "ok"
        authority_value = {
            "strength": "IPCAT_DIRECT",
            "origin": _T5_AUTH_ORIGIN,
            "value": {"canonical_family": target, "chip_name": chip_name},
        }
        # Donor rule sweep — one row per matching rule
        for rule, strs in _t5_matching_donor_rules(dts_text, target):
            rows.append(
                _t5_row(
                    subject=f"dts.{rule['kind']}",
                    verdict="DISAGREE_WITH_AUTHORITY",
                    source={
                        "dts_fragments": strs,
                        "donor_family": rule.get("family"),
                    },
                    authority=dict(authority_value),
                    confidence="high",
                    citations=_t5_citations(chip_name, rule["rule_id"]),
                    review_actions=[_t5_review_action_for(rule, strs, target)],
                    notes=[
                        f"donor-family leak: rule {rule['rule_id']} matched "
                        f"{len(strs)} DTS fragment(s); target family is {target}"
                    ],
                )
            )
        # Revision-anchor sweep — one NCC row iff DTS declares neither pin.
        # We only emit this row when there IS DTS text to check; empty DTS
        # input returns [] (nothing to check).
        if dts_text and not _t5_has_revision_pin(dts_text):
            rows.append(
                _t5_row(
                    subject=_T5_SUBJECT_REVISION,
                    verdict="NOT_CROSS_CHECKABLE",
                    source={"dts_fragments": []},
                    authority=dict(authority_value),
                    confidence="none",
                    coverage_gap_reason="revision_not_pinned",
                    citations=_t5_citations(
                        chip_name, _T5_META_RULES["revision_not_pinned"]
                    ),
                    review_actions=[
                        "add qcom,board-id and/or qcom,msm-id to pin this DTS "
                        "to a specific chip revision"
                    ],
                    notes=[
                        "DTS declares neither qcom,board-id nor qcom,msm-id; "
                        "revision cannot be cross-checked"
                    ],
                )
            )
        return rows

    # ── Path 2: authority unavailable, source-declared family present ──────
    fallback_family = None
    for key in ("family", "silicon_family", "soc_family"):
        fallback_family = _t5_normalize_family(source_meta.get(key))
        if fallback_family is not None:
            break

    if fallback_family is not None:
        authority_value = {
            "strength": "KB_RULE",
            "origin": "kb.crossverify_config",
            "value": {
                "canonical_family": fallback_family,
                "chip_name": "<unavailable>",
            },
        }
        for rule, strs in _t5_matching_donor_rules(dts_text, fallback_family):
            rows.append(
                _t5_row(
                    subject=f"dts.{rule['kind']}",
                    verdict="DISAGREE_WITH_AUTHORITY",
                    source={
                        "dts_fragments": strs,
                        "donor_family": rule.get("family"),
                        "family": fallback_family,
                    },
                    authority=dict(authority_value),
                    confidence="medium",
                    citations=_t5_citations("<unavailable>", rule["rule_id"]),
                    review_actions=[
                        _t5_review_action_for(rule, strs, fallback_family)
                    ],
                    notes=[
                        f"chips_list_chips unavailable; donor rule "
                        f"{rule['rule_id']} evaluated against source-declared "
                        f"family {fallback_family} (confidence=medium)"
                    ],
                )
            )
        if dts_text and not _t5_has_revision_pin(dts_text):
            rows.append(
                _t5_row(
                    subject=_T5_SUBJECT_REVISION,
                    verdict="NOT_CROSS_CHECKABLE",
                    source={"dts_fragments": [], "family": fallback_family},
                    authority=dict(authority_value),
                    confidence="none",
                    coverage_gap_reason="revision_not_pinned",
                    citations=_t5_citations(
                        "<unavailable>", _T5_META_RULES["revision_not_pinned"]
                    ),
                    review_actions=[
                        "add qcom,board-id and/or qcom,msm-id to pin this DTS "
                        "to a specific chip revision"
                    ],
                    notes=[
                        "DTS declares neither qcom,board-id nor qcom,msm-id; "
                        "revision cannot be cross-checked"
                    ],
                )
            )
        return rows

    # ── Path 3: authority unavailable AND no source-declared family ────────
    return [
        _t5_row(
            subject=_T5_SUBJECT_IDENTITY,
            verdict="NOT_CROSS_CHECKABLE",
            source=source_meta or None,
            authority={"strength": "UNAVAILABLE", "origin": "none"},
            confidence="none",
            coverage_gap_reason="authority_unavailable",
            citations=_t5_citations(
                "<unavailable>", _T5_META_RULES["silicon_identity"]
            ),
            review_actions=[
                "chips_list_chips unavailable and no source-declared silicon "
                "family; re-run collector or declare family in DTS payload"
            ],
            notes=[
                "silicon identity cannot be established; donor rules skipped "
                "to avoid legitimizing donor leaks by inference"
            ],
        )
    ]
