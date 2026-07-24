"""WP-SRC-B commit 1: endpoint source ingestion (IPCAT → EndpointFact list).

Pure, deterministic derivation function. Consumes an ``analysis`` dict
carrying an ``ipcat.chipio_get_qups`` flat list (the real IPCAT tool
payload shape produced by the WP-SRC-A2 wiring commit's IPCAT
enrichment step) and emits one :class:`EndpointFact` per QUP SE record
so downstream ``track_t4a`` can emit ``T4a.qup.<label>`` rows and open
the joint ``machine_driver`` + ``codec_stub`` gates (prefix scan
``T4a.qup.*`` at ``machine_driver.py:229`` and ``codec_stub.py:214``).

Real-shape reference (verbatim from ``targets/nord-iq10/evidence/
ipcat/chipio_get_qups.json``): per-entry keys are ``swi`` (dict with
``address`` / ``map`` / ``name``), ``se_number``, ``group``
(``"TLMM"`` / ``"SAIL"``), ``wrapper_id``, capability booleans
(``i2c`` / ``spi`` / ``uart`` / ...), and ``instance``. There is NO
``kind`` / ``engine`` / ``bus`` / ``audio_role`` / ``group_name`` key
in the real shape — those were fictional-fixture inventions the pre-B2
reader consumed.

Contract pinned by T-SRC-B-1, T-SRC-B-4, T-SRC-B-5 in
``tests/test_source_ingest_endpoints.py`` and T-SRC-B2-1 /
T-SRC-B2-2 / T-SRC-B2-GENERALITY in
``tests/test_source_ingest_endpoints_b2.py``:

  * Function name: ``derive_endpoints_from_ipcat(analysis)``.
  * Signature: ``dict[str, Any] -> list[EndpointFact] | SOURCE_UNRESOLVED``.
  * Non-empty ``chipio_get_qups`` list → non-empty
    ``list[EndpointFact]`` (T-SRC-B-1, T-SRC-B2-1).
  * Empty / missing input → the ``SOURCE_UNRESOLVED`` bare-singleton
    sentinel — identity check, NEVER a silent ``[]`` (T-SRC-B-4,
    Design B mirror of WP-SRC-A1 pinmux).
  * Non-Nord payloads yield non-Nord tokens — the reader parses the
    shape generically, never bakes Nord identity (T-SRC-B2-GENERALITY;
    G-3A.13 non-negotiable).
  * Determinism: sorted by ``(kind, label, se_number, group_name,
    instance)`` so byte-identical input yields byte-identical output
    under ``json.dumps(sort_keys=True)`` (T-SRC-B-5). The extra sort
    keys resolve the ``swi.name`` triple-collision on
    ``QUPV3_0_SE4`` (wrapper_id 2/3/4, all TLMM) deterministically
    without collapsing them into one row.

Field shape mirrors what the T4a producer at
``crossverify.py:1745-1768`` reads from a claim dict — ``kind`` /
``engine`` / ``instance`` / ``se_number`` / ``group_name`` / ``cap``
— so the consumer wiring commit can hand these facts straight into
``_t4a_subject`` and ``_t4a_lookup_qup`` without reshaping. The
``cap`` field is populated from the first True capability boolean in
the order ``("i2c", "uart", "spi", "i3c")`` — matching
``crossverify_config._T4A_ENDPOINT_KINDS["qup"].capability_flags`` so
the authoritative cap-divergence rule fires against the derived cap.

Explicitly out of scope for this commit:
  * Wiring into ``_build_audio_topology`` /
    ``target_onboarding_runner`` — separate wiring commit.
  * Any change to ``crossverify.py``, ``machine_driver.py``, or
    ``codec_stub.py``.
  * ``codec_driver_porting`` — G-3A.8, deferred out-of-band.
  * DTS / T5 producer (WP-SRC-C).
  * Wrapper-disambiguation for the QUPV3_0_SE4 triple-collision: all
    three TLMM rows share subject ``qup.QUPV3_0_SE4`` and collapse to
    one row in ``track_t4a`` — acceptable for B2 which asserts
    open-on-PARTIAL, not disambiguated MATCH. Deferrable later WP.

Refs: PHASE3A_IMPLEMENTATION_PLAN.md §4 WP-SRC-B (commit 1 of ≥2),
      docs/PHASE3_KNOWN_GAPS.md G-3A.7 (T4a half) and G-3A.11
      (real-IPCAT plumbing).

Signed-off-by: Ajay Kumar Nandam <ajay.nandam@oss.qualcomm.com>
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Re-exported so callers can perform the ``result is SOURCE_UNRESOLVED``
# identity check via either ``source_ingest`` or ``source_ingest.endpoints``.
# Canonical definition lives in ``models.py``; do NOT redefine it here.
from .models import SOURCE_UNRESOLVED as SOURCE_UNRESOLVED  # noqa: F401


@dataclass(frozen=True)
class EndpointFact:
    """One derived endpoint / controller-side audio-bus owner fact.

    Immutable so the downstream ``track_t4a`` reader can treat source
    facts as authoritative for the source side of the cross-verify
    comparison without defensive copies.

    Fields (chosen to compose with ``_t4a_subject`` at
    ``crossverify.py:1745-1768`` which picks subject via the fallback
    order ``engine > name > instance > se_number > group_name`` and
    with ``_t4a_lookup_qup`` at ``crossverify.py:1637-1701`` which
    aligns on ``engine`` / ``se_number`` / ``instance`` / ``group_name``
    and cross-checks the ``cap`` field against the authority row's
    capability set):

      * ``kind``: producer namespace tag — always ``"qup"`` today for
        every SE derived from ``chipio_get_qups``; reserved for other
        endpoint families in later WPs.
      * ``label``: canonical short name driving the row subject.
        Populated from ``swi.name`` on the real payload (e.g.
        ``QUPV3_0_SE4`` for Nord's codec-control SE); the sort key
        and the ``name`` field both derive from it.
      * ``engine``: identical to ``label`` — the IPCAT engine-format
        name copied from ``swi.name`` so ``_t4a_subject``'s
        first-preferred field is populated and the T4a subject is
        ``qup.<swi.name>`` on any real payload.
      * ``instance``: real ``instance`` string from the payload
        (e.g. ``u_qupv3_wrapper_0``); only used to disambiguate the
        ``QUPV3_0_SE4`` wrapper collision inside the deterministic
        sort — ``_t4a_lookup_qup`` reads it as an alignment fallback.
      * ``bus``: LEGACY field held over from the pre-B2 shape;
        emits ``""`` on the real payload (which has no ``bus`` key).
        Kept in the field list so the dataclass layout stays stable
        for callers persisting ``to_dict`` output.
      * ``role``: LEGACY field (mirror of ``bus``); emits ``""``.
      * ``se_number``: integer SE index copied from the ``se_number``
        payload key; the primary numeric alignment key inside
        ``_t4a_lookup_qup``.
      * ``group_name``: copied from the ``group`` payload key
        (``"TLMM"`` / ``"SAIL"`` on the real shape); trailing
        alignment fallback inside ``_t4a_lookup_qup``.
      * ``name``: canonical subject namespace form ``qup.<label>``
        (dot separator) — the form the gates at
        ``machine_driver.py:230`` (``T4a.qup.*`` prefix scan) and
        ``codec_stub.py`` scan for. Populated for backward
        compatibility; ``_t4a_subject`` prefers ``engine`` so this
        field is a tie-breaker, not the primary carrier.
      * ``cap``: first True capability boolean in the order
        ``("i2c", "uart", "spi", "i3c")`` — matching
        ``crossverify_config._T4A_ENDPOINT_KINDS["qup"].capability_flags``
        so the cap-agrees rule at ``crossverify.py:1701`` fires
        against the derived cap. Empty ``""`` when no capability
        boolean is True; the cap-agrees rule treats an absent claim
        cap as "unconstrained" and defaults to True.
    """

    kind: str
    label: str
    engine: str
    instance: str
    bus: str
    role: str
    se_number: int
    group_name: str
    name: str = field(default="")
    cap: str = field(default="")

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict shaped for consumption by ``track_t4a``.

        ``asdict`` on a frozen dataclass is deterministic in field
        declaration order — this preserves the T-SRC-B-5 canonical-JSON
        property across the dataclass → dict → JSON path exactly the
        same way ``PinmuxFact.to_dict`` does for T-SRC-A-4.
        """
        return asdict(self)


# Capability boolean names in the exact precedence order matching
# ``crossverify_config._T4A_ENDPOINT_KINDS["qup"].capability_flags``.
# The first True entry (if any) becomes the derived ``cap`` field so
# the cap-agrees rule at ``crossverify.py:1701`` fires against the
# authoritative cap set.
_QUP_CAP_FLAGS: tuple[str, ...] = ("i2c", "uart", "spi", "i3c")


def _as_str(value: Any) -> str:
    """Coerce a possibly-None IPCAT field to a stripped string.

    Empty ``""`` is preserved and callers reject rows that need a
    non-empty label.
    """
    if value is None:
        return ""
    return str(value).strip()


def _as_int(value: Any) -> int | None:
    """Coerce an IPCAT integer-ish field, returning None on failure.

    IPCAT sometimes serializes SE indices as strings; the T4a subject
    only depends on ``instance`` / ``engine`` labels so returning None
    here is non-fatal — the caller keeps the row and stores the fallback
    ``-1`` sentinel below rather than dropping an otherwise-derivable
    endpoint over one missing integer.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _derive_cap(entry: dict[str, Any]) -> str:
    """Return the first True capability boolean name in ``_QUP_CAP_FLAGS`` order.

    Empty string if no capability boolean is True. The precedence
    matches ``crossverify_config._T4A_ENDPOINT_KINDS["qup"]``, so the
    ``_t4a_lookup_qup`` cap-agrees rule against the authority
    ``row_caps`` set fires against the same vocabulary.
    """
    for flag in _QUP_CAP_FLAGS:
        if bool(entry.get(flag)):
            return flag
    return ""


def derive_endpoints_from_ipcat(analysis: dict[str, Any]) -> list[EndpointFact] | Any:
    """Derive endpoint facts from an analysis dict's IPCAT payload.

    Expected input shape (verbatim from
    ``targets/nord-iq10/evidence/ipcat/chipio_get_qups.json`` — the
    real IPCAT tool payload)::

        {
          "ipcat": {
            "chipio_get_qups": [
              {
                "swi": {
                  "address": ...,
                  "map": "ARM_ADDRESS_FILE_SW",
                  "name": "QUPV3_0_SE4",
                },
                "se_number": 4,
                "group": "TLMM",
                "wrapper_id": 2,
                "i2c": True,
                "spi": True,
                "uart": True,
                "instance": "u_qupv3_wrapper_0",
              },
              ...
            ],
          },
          ...
        }

    For each entry in ``ipcat.chipio_get_qups`` with a non-empty
    ``swi.name`` label, emits one :class:`EndpointFact`. Malformed
    entries (non-dict, missing / empty ``swi.name``) are skipped at
    the per-entry level.

    Return contract (§5 evidence doctrine, T-SRC-B-4, Design B):
      * At least one derived fact → non-empty
        ``list[EndpointFact]``.
      * Zero derivable facts (missing ``ipcat`` section, missing
        ``chipio_get_qups`` list, empty list, or every entry
        malformed) → the ``SOURCE_UNRESOLVED`` bare-singleton
        sentinel, NEVER a silent ``[]``.

    Downstream consumers gate on **identity**: the canonical predicate
    is ``result is SOURCE_UNRESOLVED``, not ``isinstance(result, list)``
    or ``result == SOURCE_UNRESOLVED``. Same rationale as
    :func:`orchestrator.source_ingest.pinmux.derive_pinmux_from_dt`.

    Determinism (T-SRC-B-5): entries are sorted by
    ``(kind, label, se_number, group_name, instance)`` AFTER
    derivation, so byte-identical input yields byte-identical output.
    The extra sort keys past ``(kind, label)`` disambiguate the
    ``QUPV3_0_SE4`` wrapper-id 2/3/4 triple-collision on the real
    Nord payload without collapsing them into one row here (the
    collapse happens downstream in ``track_t4a`` by shared subject,
    which is acceptable for B2 open-on-PARTIAL). The sort is stable,
    and the field-declaration-order ``asdict`` in
    :meth:`EndpointFact.to_dict` carries the property across the
    JSON boundary.

    Generality (T-SRC-B2-GENERALITY, G-3A.13 non-negotiable): no
    Nord token appears in the reader body. Every derived value comes
    off the payload (``swi.name`` / ``se_number`` / ``group`` /
    ``instance`` / capability booleans); a non-Nord payload of the
    same shape yields facts carrying that payload's tokens.
    """
    if not isinstance(analysis, dict):
        return SOURCE_UNRESOLVED
    ipcat = analysis.get("ipcat")
    if not isinstance(ipcat, dict):
        return SOURCE_UNRESOLVED
    qup_list = ipcat.get("chipio_get_qups")
    if not isinstance(qup_list, list) or not qup_list:
        return SOURCE_UNRESOLVED

    facts: list[EndpointFact] = []
    for entry in qup_list:
        if not isinstance(entry, dict):
            continue
        swi = entry.get("swi")
        swi_name = _as_str(swi.get("name")) if isinstance(swi, dict) else ""
        if not swi_name:
            # No stable label to key the T4a subject on — skip. Every
            # real ``chipio_get_qups`` entry has a populated ``swi.name``.
            continue
        # ``label`` and ``engine`` both take the real ``swi.name`` so
        # ``_t4a_subject`` (engine-first) emits ``qup.<swi.name>`` and
        # the deterministic sort key uses the same token.
        label = swi_name
        engine = swi_name
        instance = _as_str(entry.get("instance"))
        se_number_raw = _as_int(entry.get("se_number"))
        se_number = se_number_raw if se_number_raw is not None else -1
        group_name = _as_str(entry.get("group"))
        cap = _derive_cap(entry)

        facts.append(
            EndpointFact(
                kind="qup",
                label=label,
                engine=engine,
                instance=instance,
                # ``bus`` / ``role`` do not exist on the real payload
                # (fictional-fixture inventions); keep the fields for
                # dataclass-layout stability, emit empty strings.
                bus="",
                role="",
                se_number=se_number,
                group_name=group_name,
                # ``qup.<label>`` is the dot-separator form the joint
                # ``machine_driver`` / ``codec_stub`` gate prefix scan
                # matches on. ``_t4a_subject`` prefers ``engine`` first
                # so this field is a tie-breaker, not the primary
                # subject carrier.
                name=f"qup.{label}",
                cap=cap,
            )
        )

    if not facts:
        return SOURCE_UNRESOLVED
    # Sort key resolves the ``QUPV3_0_SE4`` wrapper_id 2/3/4 triple-
    # collision deterministically: same (kind, label, se_number,
    # group_name) → tie-broken by ``instance`` (``u_qupv3_wrapper_0/1/2``).
    facts.sort(
        key=lambda f: (f.kind, f.label, f.se_number, f.group_name, f.instance)
    )
    return facts
