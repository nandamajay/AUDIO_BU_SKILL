"""WP-SRC-B commit 1: endpoint source ingestion (IPCAT → EndpointFact list).

Pure, deterministic derivation function. Consumes an ``analysis`` dict
carrying an ``ipcat.qup_controllers`` list (the shape produced by the
WP-SRC-A2 wiring commit's IPCAT enrichment step) and emits one
:class:`EndpointFact` per active QUP controller so downstream
``track_t4a`` can emit ``T4a.qup.<label>`` rows and open the joint
``machine_driver`` + ``codec_stub`` gates (prefix scan ``T4a.qup.*``
at ``machine_driver.py:229`` and ``codec_stub.py:214``).

Contract pinned by T-SRC-B-1, T-SRC-B-4, T-SRC-B-5 in
``tests/test_source_ingest_endpoints.py``:

  * Function name: ``derive_endpoints_from_ipcat(analysis)``.
  * Signature: ``dict[str, Any] -> list[EndpointFact] | SOURCE_UNRESOLVED``.
  * Non-empty ``qup_controllers`` list → non-empty
    ``list[EndpointFact]`` (T-SRC-B-1).
  * Empty / missing input → the ``SOURCE_UNRESOLVED`` bare-singleton
    sentinel — identity check, NEVER a silent ``[]`` (T-SRC-B-4,
    Design B mirror of WP-SRC-A1 pinmux).
  * Determinism: sorted by ``(kind, label)`` so byte-identical input
    yields byte-identical output under
    ``json.dumps(sort_keys=True)`` (T-SRC-B-5).

Field shape mirrors what the T4a producer at
``crossverify.py:1743-1754`` reads from a claim dict — ``kind`` /
``engine`` / ``instance`` / ``se_number`` / ``group_name`` — so the
consumer wiring commit can hand these facts straight into
``_t4a_subject`` (or its dot-separator-reconciled successor) without
reshaping.

Explicitly out of scope for this commit:
  * T4a producer↔gate separator reconcile (``qup:`` colon vs ``qup.``
    dot) — the next WP-SRC-B commit, with the design decision
    (producer-side vs gate-side) recorded in its commit message.
    T-SRC-B-2 and T-SRC-B-3 stay red until that commit lands.
  * Wiring into ``_build_audio_topology`` /
    ``target_onboarding_runner`` — separate wiring commit.
  * Any change to ``crossverify.py``, ``machine_driver.py``, or
    ``codec_stub.py``.
  * ``codec_driver_porting`` — G-3A.8, deferred out-of-band.
  * DTS / T5 producer (WP-SRC-C).

Refs: PHASE3A_IMPLEMENTATION_PLAN.md §4 WP-SRC-B (commit 1 of ≥2),
      docs/PHASE3_KNOWN_GAPS.md G-3A.7 (T4a half).

Signed-off-by: Ajay Kumar Nandam <ajayn@qti.qualcomm.com>
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
    ``crossverify.py:1743-1754`` which reads ``kind`` /
    ``engine`` / ``name`` / ``instance`` / ``se_number`` /
    ``group_name`` in that fallback order):

      * ``kind``: producer namespace tag — always ``"qup"`` today;
        reserved for ``"slimbus"`` / ``"i2c"`` variants in later WPs.
      * ``label``: canonical short name driving the row subject.
        The T4a producer picks this via a fallback chain; we store it
        explicitly so callers don't have to re-run that chain.
        Currently derived from the ``instance`` field (which for Nord
        is ``qup_0_se5`` / ``qup_1_se2`` — the form the gate prefix
        scan will key on once the separator is reconciled).
      * ``engine``: IPCAT engine-format name (e.g. ``QUPv3_0_SE_5``);
        kept for report readability and cross-check with SWI dumps.
      * ``instance``: IPCAT instance-format name (e.g. ``qup_0_se5``).
      * ``bus``: audio bus this endpoint services — ``i2s`` /
        ``i2c`` today.
      * ``role``: semantic role (e.g. ``primary_i2s`` /
        ``codec_control``). Not currently cross-checked; kept for
        report readability and future subject decomposition.
      * ``se_number``: SE index within the QUP group (kept as-is for
        cross-check with the IPCAT ``se_number`` field).
      * ``group_name``: parent QUP group (e.g. ``qup_0``); kept for
        cross-check with the IPCAT ``group_name`` field.
      * ``name``: canonical subject namespace form
        ``qup.<instance>`` — the dot-separator form the gates at
        ``machine_driver.py:229`` and ``codec_stub.py:214`` scan for.
        Reconcile with producer at ``crossverify.py:1743-1754``
        happens in the next commit.
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

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict shaped for consumption by ``track_t4a``.

        ``asdict`` on a frozen dataclass is deterministic in field
        declaration order — this preserves the T-SRC-B-5 canonical-JSON
        property across the dataclass → dict → JSON path exactly the
        same way ``PinmuxFact.to_dict`` does for T-SRC-A-4.
        """
        return asdict(self)


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


def derive_endpoints_from_ipcat(analysis: dict[str, Any]) -> list[EndpointFact] | Any:
    """Derive endpoint facts from an analysis dict's IPCAT payload.

    Expected input shape::

        {
          "ipcat": {
            "qup_controllers": [
              {
                "kind": "qup",
                "engine": "QUPv3_0_SE_5",
                "instance": "qup_0_se5",
                "bus": "i2s",
                "audio_role": "primary_i2s",
                "se_number": 5,
                "group_name": "qup_0",
              },
              ...
            ],
          },
          ...
        }

    For each entry in ``ipcat.qup_controllers`` with a non-empty
    ``instance`` (or ``engine`` fallback) label, emits one
    :class:`EndpointFact`. Malformed entries (non-dict, missing both
    ``instance`` and ``engine``) are skipped at the per-entry level.

    Return contract (§5 evidence doctrine, T-SRC-B-4, Design B):
      * At least one derived fact → non-empty
        ``list[EndpointFact]``.
      * Zero derivable facts (missing ``ipcat`` section, missing
        ``qup_controllers`` list, empty list, or every entry
        malformed) → the ``SOURCE_UNRESOLVED`` bare-singleton
        sentinel, NEVER a silent ``[]``.

    Downstream consumers gate on **identity**: the canonical predicate
    is ``result is SOURCE_UNRESOLVED``, not ``isinstance(result, list)``
    or ``result == SOURCE_UNRESOLVED``. Same rationale as
    :func:`orchestrator.source_ingest.pinmux.derive_pinmux_from_dt`.

    Determinism (T-SRC-B-5): entries are sorted by ``(kind, label)``
    AFTER derivation, so byte-identical input yields byte-identical
    output. The sort is stable, and the field-declaration-order
    ``asdict`` in :meth:`EndpointFact.to_dict` carries the property
    across the JSON boundary.
    """
    if not isinstance(analysis, dict):
        return SOURCE_UNRESOLVED
    ipcat = analysis.get("ipcat")
    if not isinstance(ipcat, dict):
        return SOURCE_UNRESOLVED
    qup_list = ipcat.get("qup_controllers")
    if not isinstance(qup_list, list) or not qup_list:
        return SOURCE_UNRESOLVED

    facts: list[EndpointFact] = []
    for entry in qup_list:
        if not isinstance(entry, dict):
            continue
        # ``instance`` is preferred as the label because the reconciled
        # gate prefix (``T4a.qup.<instance>``) is what the codec_stub /
        # machine_driver generators scan for; ``engine`` is the fallback
        # for entries missing the instance-format name.
        instance = _as_str(entry.get("instance"))
        engine = _as_str(entry.get("engine"))
        label = instance or engine
        if not label:
            continue
        kind = _as_str(entry.get("kind")) or "qup"
        bus = _as_str(entry.get("bus"))
        # IPCAT calls the field ``audio_role`` in the fixture; keep both
        # spellings as fallbacks so a future schema drift to plain
        # ``role`` does not silently drop the semantic label.
        role = _as_str(entry.get("audio_role")) or _as_str(entry.get("role"))
        se_number_raw = _as_int(entry.get("se_number"))
        se_number = se_number_raw if se_number_raw is not None else -1
        group_name = _as_str(entry.get("group_name"))

        facts.append(
            EndpointFact(
                kind=kind,
                label=label,
                engine=engine,
                instance=instance,
                bus=bus,
                role=role,
                se_number=se_number,
                group_name=group_name,
                # ``qup.<label>`` is the dot-separator form the joint
                # ``machine_driver`` / ``codec_stub`` gate prefix scan
                # matches on. Reconcile with the producer at
                # ``crossverify.py:1743-1754`` (colon form) is the next
                # WP-SRC-B commit — until then T-SRC-B-2 / T-SRC-B-3 stay
                # red by design, so this field is authoritative on the
                # producer output side.
                name=f"{kind}.{label}",
            )
        )

    if not facts:
        return SOURCE_UNRESOLVED
    facts.sort(key=lambda f: (f.kind, f.label))
    return facts
