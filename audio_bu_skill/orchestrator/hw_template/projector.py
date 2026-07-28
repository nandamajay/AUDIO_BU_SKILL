"""H-1 audio hardware template projector.

Data-flow leaf. Reads ``gc["cross_verification"]["rows"]`` (a list of
``VerificationRow.to_dict()`` payloads), plus a small amount of
supplementary shape from other ``gc`` keys (``ipcat``, ``audio_stack``,
``codecs``, ``amplifiers``, ``buses``, ``soundwire``), and emits two
JSON artefacts under the target directory:

  * ``audio_hardware_template.json`` — grouped by entity family, every
    leaf a :class:`FactRecord`.
  * ``gap_manifest.json`` — flattened reviewer view of every NCC /
    NOT_ATTESTED / candidate leaf.

**Architectural invariants (enforced by tests, not by this docstring):**

  * The projector never writes ``gc["cross_verification"]["rows"]`` —
    guarded by :mod:`tests.test_h1_projector_is_data_flow_leaf`.
  * The projector never promotes ``candidate_value`` into an attested
    slot — guarded by
    :mod:`tests.test_h1_projector_never_promotes_candidate` and by the
    :class:`FactRecord` constructor invariant.
  * The projector never opens a gate, never issues a MATCH / PARTIAL
    verdict, never adds a new authority strength.
  * The projector is a pure function: ``project(gc, target, run_id)``
    depends on its inputs only. No global state, no clock, no
    filesystem side-effects until the caller invokes ``write_outputs``.

Import discipline (matches WP-64 firewall):

  * From ``orchestrator.reasoning`` — only ``crossverify_model``
    (via :mod:`orchestrator.hw_template.model`, which re-exports the
    two closed enums this projector cares about). This module itself
    does not import from ``orchestrator.reasoning.*`` directly.
  * From ``orchestrator.generation`` — nothing. The projector does not
    consume generator artefacts, only crossverify rows.

CLI usage (primarily for synthetic fixtures and offline inspection —
real-target validation goes through the in-process API):

    python -m orchestrator.hw_template.projector \\
        --gc-json <path-to-gc.json> \\
        --target <target_name> \\
        --run-id <run_id> \\
        --out-dir <target-dir>

For synthetic fixtures the caller MUST additionally set the
``H1_VALIDATION_ALLOWS_FIXTURES=1`` environment variable, and every row
citation MUST include ``"<fixture: NOT_REAL_TARGET>"`` — the projector
enforces this so a fixture cannot masquerade as an onboarded target.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orchestrator.hw_template.model import (
    AudioHardwareTemplate,
    FactRecord,
    GapManifest,
    SCHEMA_VERSION,
)


# ── Constants ───────────────────────────────────────────────────────────────

_FIXTURE_ENV_FLAG = "H1_VALIDATION_ALLOWS_FIXTURES"
_FIXTURE_CITATION = "<fixture: NOT_REAL_TARGET>"

# The subset of verdicts that make a fact "attested" (i.e. reviewer can
# accept it without further manual crosscheck). PARTIAL_MATCH is
# reviewer-flagged but still attested; the reviewer_required bit
# reflects that.
_ATTESTED_VERDICTS: frozenset[str] = frozenset({"MATCH", "PARTIAL_MATCH"})


@dataclass
class ProjectionResult:
    """Container for the two artefacts the projector produces."""

    template: AudioHardwareTemplate
    gap_manifest: GapManifest


# ── Public API ──────────────────────────────────────────────────────────────


def project(
    gc: dict[str, Any],
    target_name: str,
    run_id: str,
    *,
    allow_fixture_citations: bool | None = None,
    curated_overrides: dict[str, Any] | None = None,
) -> ProjectionResult:
    """Project ``gc`` into a hardware template + gap manifest.

    Parameters
    ----------
    gc :
        The generated-case dict. MUST contain a ``cross_verification``
        key with a ``rows`` list of dicts (or be missing that key
        entirely — an empty-rows result is legal and produces a
        template full of NOT_ATTESTED FactRecords).
    target_name :
        The onboarded target name (e.g. ``"nord-iq10"``). Not
        interpreted; recorded verbatim in the output.
    run_id :
        The orchestrator run id. Not interpreted; recorded verbatim.
    allow_fixture_citations :
        If ``True``, the projector permits ``citations`` to contain
        the ``<fixture: NOT_REAL_TARGET>`` sentinel. If ``False`` and
        such a citation is seen, raises :class:`ValueError`. If
        ``None`` (default), reads the :envvar:`H1_VALIDATION_ALLOWS_FIXTURES`
        environment variable.
    curated_overrides :
        Optional dict of curated human-authority overrides (G-3A.15).
        Schema: ``{"<template_path>": {FactRecord-shaped payload}}``.
        Each entry is validated at load time and applied ONLY to
        NOT_ATTESTED facts (gap-fill). If ``None`` (default), no
        curation is applied — the projector is inert with respect to
        this feature.

    Returns
    -------
    :class:`ProjectionResult`
        Both artefacts, in memory. Call :func:`write_outputs` to
        persist.

    Raises
    ------
    ValueError
        If a fixture citation is encountered without the fixture flag
        set, if the row list is malformed, or if curated_overrides
        fails schema validation.
    """
    if allow_fixture_citations is None:
        allow_fixture_citations = os.environ.get(_FIXTURE_ENV_FLAG) == "1"

    cv = gc.get("cross_verification") or {}
    rows: list[dict[str, Any]] = list(cv.get("rows") or [])
    snapshot_provenance = dict(cv.get("snapshot_provenance") or {})

    _enforce_fixture_discipline(rows, allow_fixture_citations)

    # Index rows by "<track>.<subject>" so entity builders can look them
    # up without re-scanning. Later duplicates overwrite earlier —
    # matches the single-writer semantics at main.py:1192.
    rows_by_ts: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(
                f"cross_verification row must be a dict, got {type(row).__name__}"
            )
        track = row.get("track")
        subject = row.get("subject")
        if not isinstance(track, str) or not isinstance(subject, str):
            raise ValueError(
                f"cross_verification row missing track/subject: {row!r}"
            )
        rows_by_ts[f"{track}.{subject}"] = row

    gaps: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    # ── Build entity groups ────────────────────────────────────────────
    board_metadata = _build_board_metadata(
        gc, rows_by_ts, target_name, gaps, counts
    )
    codecs = _build_codecs(gc, rows_by_ts, gaps, counts)
    amplifiers = _build_amplifiers(gc, rows_by_ts, gaps, counts)
    buses = _build_buses(gc, rows_by_ts, gaps, counts)
    clocks = _build_clocks(gc, rows_by_ts, gaps, counts)
    audio_links = _build_audio_links(gc, rows_by_ts, gaps, counts)

    template = AudioHardwareTemplate(
        target_name=target_name,
        run_id=run_id,
        generated_from=snapshot_provenance,
        board_metadata=board_metadata,
        codecs=codecs,
        amplifiers=amplifiers,
        buses=buses,
        clocks=clocks,
        audio_links=audio_links,
    )

    # ── Apply curated overrides (G-3A.15, gap-fill only) ──────────────
    if curated_overrides is not None:
        _validate_curated_overrides(curated_overrides, target_name)
        _apply_curated_overrides(template, curated_overrides)

    gap_manifest = GapManifest(
        target_name=target_name,
        run_id=run_id,
        gap_count_by_reason=counts,
        gaps=gaps,
    )
    return ProjectionResult(template=template, gap_manifest=gap_manifest)


def write_outputs(result: ProjectionResult, out_dir: str | Path) -> tuple[Path, Path]:
    """Persist ``audio_hardware_template.json`` + ``gap_manifest.json``.

    Returns the two paths written.
    """
    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    template_path = out / "audio_hardware_template.json"
    gap_path = out / "gap_manifest.json"

    template_path.write_text(
        json.dumps(result.template.to_dict(), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    gap_path.write_text(
        json.dumps(result.gap_manifest.to_dict(), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return template_path, gap_path


# ── Fact construction helpers ───────────────────────────────────────────────


def _fact_from_row(
    row: dict[str, Any] | None,
    row_key: str | None,
    *,
    candidate_value: Any = None,
    candidate_derived: bool = False,
) -> FactRecord:
    """Build a :class:`FactRecord` from a crossverify row (or absence).

    * ``row is None`` → NOT_ATTESTED FactRecord with UNAVAILABLE
      authority and, if ``candidate_derived``, a populated
      ``candidate_value``.
    * ``row`` with verdict ∈ {MATCH, PARTIAL_MATCH} and non-UNAVAILABLE
      authority → ATTESTED FactRecord.
    * ``row`` with verdict == NOT_CROSS_CHECKABLE → NOT_CROSS_CHECKABLE
      FactRecord; the row's ``coverage_gap_reason`` is copied into
      ``not_attested_disclosures``.
    * ``row`` with any other verdict (REVIEW_REQUIRED,
      DISAGREE_WITH_AUTHORITY) → NOT_ATTESTED FactRecord with
      ``reviewer_required=True``.
    """
    if row is None:
        auth = {"strength": "UNAVAILABLE", "origin": "none"}
        return FactRecord(
            value=None,
            authority=auth,
            citations=[],
            row_ref=None,
            independently_verified=False,
            candidate_derived=candidate_derived,
            candidate_value=candidate_value,
            reviewer_required=candidate_derived,
            ncc_state="NOT_ATTESTED",
        )

    verdict = row.get("verdict")
    authority = row.get("authority") or {"strength": "UNAVAILABLE", "origin": "none"}
    citations = list(row.get("citations") or [])
    source = row.get("source")

    if verdict in _ATTESTED_VERDICTS and authority.get("strength") != "UNAVAILABLE":
        return FactRecord(
            value=source,
            authority=authority,
            citations=citations,
            row_ref=row_key,
            independently_verified=(verdict == "MATCH"),
            candidate_derived=False,
            candidate_value=None,
            reviewer_required=(verdict == "PARTIAL_MATCH"),
            ncc_state="ATTESTED",
        )

    if verdict == "NOT_CROSS_CHECKABLE":
        disclosure = {
            "reason": row.get("coverage_gap_reason") or "authority_out_of_scope",
            "detail": row.get("rule_id") or "",
            "citations": citations,
        }
        return FactRecord(
            value=None,
            authority={"strength": "UNAVAILABLE", "origin": "none"},
            citations=citations,
            row_ref=row_key,
            independently_verified=False,
            candidate_derived=False,
            candidate_value=source,
            reviewer_required=True,
            ncc_state="NOT_CROSS_CHECKABLE",
            not_attested_disclosures=[disclosure],
        )

    # REVIEW_REQUIRED / DISAGREE_WITH_AUTHORITY / other verdicts land
    # here — treat as NOT_ATTESTED with the candidate exposed for the
    # reviewer.
    return FactRecord(
        value=None,
        authority={"strength": "UNAVAILABLE", "origin": "none"},
        citations=citations,
        row_ref=row_key,
        independently_verified=False,
        candidate_derived=True,
        candidate_value=source,
        reviewer_required=True,
        ncc_state="NOT_ATTESTED",
    )


def _add_to_manifest(
    fact: FactRecord,
    path: str,
    gaps: list[dict[str, Any]],
    counts: dict[str, int],
) -> None:
    """Register a FactRecord in the flat gap manifest if it isn't ATTESTED."""
    if fact.ncc_state == "ATTESTED" and not fact.reviewer_required:
        return

    if fact.ncc_state == "NOT_CROSS_CHECKABLE":
        reason = "authority_out_of_scope"
        if fact.not_attested_disclosures:
            reason = fact.not_attested_disclosures[0].get(
                "reason", "authority_out_of_scope"
            )
    elif fact.candidate_derived:
        reason = "candidate_only"
    elif fact.reviewer_required and fact.ncc_state == "ATTESTED":
        # PARTIAL_MATCH — reviewer must confirm but it IS attested;
        # bucket under a distinct sentinel so counts stay honest.
        reason = "candidate_only"
    else:
        reason = "not_attested"

    counts[reason] = counts.get(reason, 0) + 1
    entry = dict(fact.to_dict())
    entry["path"] = path
    entry["reason"] = reason
    gaps.append(entry)


# ── Entity-group builders ───────────────────────────────────────────────────


def _derive_pinctrl_state(gc: dict[str, Any]) -> FactRecord:
    """Derive ``pinctrl_state`` from ``gc["audio_topology"]["pinmux"]``.

    Rule (A-narrow): if exactly ONE distinct ``state_label`` appears across
    all I2S-typed pinmux facts, emit an ATTESTED FactRecord with that label
    as value, authority ``{"strength": "IPCAT_DERIVED", "origin": "kernel_dt"}``.
    Zero or more-than-one distinct labels → NOT_ATTESTED (no guessing).
    """
    topology = gc.get("audio_topology") if isinstance(gc, dict) else None
    if not isinstance(topology, dict):
        return _not_attested_pinctrl()
    pinmux = topology.get("pinmux")
    if not isinstance(pinmux, list):
        return _not_attested_pinctrl()

    labels: set[str] = set()
    for entry in pinmux:
        if not isinstance(entry, dict):
            continue
        label = entry.get("state_label")
        if isinstance(label, str) and label:
            labels.add(label)

    if len(labels) != 1:
        return _not_attested_pinctrl()

    derived_label = next(iter(labels))
    return FactRecord(
        value=derived_label,
        authority={"strength": "IPCAT_DERIVED", "origin": "kernel_dt"},
        citations=["kernel DT pinctrl state derivation (A-narrow)"],
        row_ref=None,
        independently_verified=False,
        candidate_derived=False,
        candidate_value=None,
        reviewer_required=False,
        ncc_state="ATTESTED",
    )


def _not_attested_pinctrl() -> FactRecord:
    """Return a NOT_ATTESTED FactRecord for pinctrl_state."""
    return _not_attested_leaf()


def _not_attested_leaf() -> FactRecord:
    """Return a bare NOT_ATTESTED FactRecord (value=null, no candidate).

    This is the default state for a **schematic-attested** leaf
    (WP_SCHEMATIC_ATTESTED_DESIGN.md §3.2): a slot the projector cannot fill
    from any automated authority. It stays NOT_ATTESTED / value=null until a
    curated override with ``origin="schematic"`` gap-fills it at onboarding
    time. ``candidate_derived=False`` deliberately — a schematic slot is NOT a
    candidate value we saw and refused to promote; it is a slot with *no*
    automated source at all. (Contrast the codec ``part_number`` slot, which
    carries the candidate DTS value with ``candidate_derived=True``.)

    Because value is null on Nord, every consumer's ``_template_value`` returns
    ``None`` and the hardcoded generator fallback fires unchanged — byte-identity
    holds until a cited curated file lands (§3.5, §5).
    """
    return FactRecord(
        value=None,
        authority={"strength": "UNAVAILABLE", "origin": "none"},
        citations=[],
        row_ref=None,
        independently_verified=False,
        candidate_derived=False,
        candidate_value=None,
        reviewer_required=False,
        ncc_state="NOT_ATTESTED",
    )


def _build_board_metadata(
    gc: dict[str, Any],
    rows_by_ts: dict[str, dict[str, Any]],
    target_name: str,
    gaps: list[dict[str, Any]],
    counts: dict[str, int],
) -> dict[str, Any]:
    """Assemble the ``board_metadata`` group.

    Fields: ``target_name`` (identity, no envelope), ``soc``,
    ``board_variant``. Both wrapped facts are keyed off Track T5
    (positive attestation, WP-71) or Track T4a (nord/iq10
    board-compatible, WP-71 sibling); the projector reads whatever
    row happens to be present without judging.
    """
    result: dict[str, Any] = {"target_name": target_name}

    # SoC: candidate comes from gc["soc"] / gc["ipcat"]["chip"];
    # authority comes from any T1.soc or T5.soc row if present.
    soc_row_key = None
    soc_row = None
    for candidate_key in ("T5.soc", "T1.soc", "T5.chip", "T1.chip"):
        if candidate_key in rows_by_ts:
            soc_row_key = candidate_key
            soc_row = rows_by_ts[candidate_key]
            break
    soc_candidate = (
        gc.get("soc") if isinstance(gc.get("soc"), str) else None
    ) or (
        gc.get("ipcat", {}).get("chip") if isinstance(gc.get("ipcat"), dict) else None
    )
    soc_fact = _fact_from_row(
        soc_row,
        soc_row_key,
        candidate_value=soc_candidate if soc_row is None else None,
        candidate_derived=(soc_row is None and soc_candidate is not None),
    )
    result["soc"] = soc_fact
    _add_to_manifest(soc_fact, "board_metadata.soc", gaps, counts)

    # board_variant: WP-69 disclosure family. Row keys of interest are
    # T4a/T5 with subject "board_variant" or "sound_card.model".
    variant_row_key = None
    variant_row = None
    for candidate_key in (
        "T5.board_variant",
        "T4a.board_variant",
        "T5.sound_card.model.board_variant",
        "T5.sound_card.model",
    ):
        if candidate_key in rows_by_ts:
            variant_row_key = candidate_key
            variant_row = rows_by_ts[candidate_key]
            break
    variant_candidate = None
    board = gc.get("board")
    if isinstance(board, dict):
        variant_candidate = board.get("variant") or board.get("board_variant")
    elif isinstance(board, str):
        variant_candidate = board
    variant_fact = _fact_from_row(
        variant_row,
        variant_row_key,
        candidate_value=variant_candidate if variant_row is None else None,
        candidate_derived=(variant_row is None and variant_candidate is not None),
    )
    result["board_variant"] = variant_fact
    _add_to_manifest(variant_fact, "board_metadata.board_variant", gaps, counts)

    # pinctrl_state: derived from audio_topology.pinmux (WP-SRC-A2 output).
    # Rule: if exactly ONE distinct state_label appears across all I2S-typed
    # pinmux facts, project it as ATTESTED. Zero or more-than-one → NOT_ATTESTED.
    pinctrl_fact = _derive_pinctrl_state(gc)
    result["pinctrl_state"] = pinctrl_fact
    _add_to_manifest(pinctrl_fact, "board_metadata.pinctrl_state", gaps, counts)

    # Schematic-attested slots (WP_SCHEMATIC_ATTESTED_DESIGN.md §3.2). No
    # automated authority exists for these — they are populated ONLY by a
    # curated override with origin="schematic" at onboarding time. Default
    # NOT_ATTESTED / value=null so every generator falls through to its
    # hardcoded constant on Nord (byte-identity). Inert until step 2+ wires the
    # curated allowlist + live loading; no consumer reads them yet.
    for schematic_field in ("mclk", "global_md_oe", "scmi_index"):
        leaf = _not_attested_leaf()
        result[schematic_field] = leaf
        _add_to_manifest(leaf, f"board_metadata.{schematic_field}", gaps, counts)

    return result


def _build_codecs(
    gc: dict[str, Any],
    rows_by_ts: dict[str, dict[str, Any]],
    gaps: list[dict[str, Any]],
    counts: dict[str, int],
) -> list[dict[str, Any]]:
    """Assemble the ``codecs`` group.

    Each codec entry has: ``part_number`` (fact), ``vendor`` (fact),
    ``role`` (fact — e.g. ``primary``, ``secondary``, ``amplifier`` —
    kept for renderer, always candidate-only in H-1).
    """
    codecs_in = gc.get("codecs")
    if not isinstance(codecs_in, list):
        return []

    out: list[dict[str, Any]] = []
    for idx, item in enumerate(codecs_in):
        part_candidate = _extract_string(item, keys=("part_number", "name", "model"))
        vendor_candidate = _extract_string(item, keys=("vendor", "manufacturer"))
        role_candidate = _extract_string(item, keys=("role", "kind"))

        # Look for a row keyed on the codec's canonical name; H-1
        # doesn't invent authorities for codecs (no generator does
        # today either), so most codecs will land NOT_ATTESTED.
        row_key = None
        row = None
        if part_candidate:
            for candidate_key in (
                f"T2.codec.{part_candidate}",
                f"T5.codec.{part_candidate}",
                f"T4a.codec.{part_candidate}",
            ):
                if candidate_key in rows_by_ts:
                    row_key = candidate_key
                    row = rows_by_ts[candidate_key]
                    break

        part_fact = _fact_from_row(
            row,
            row_key,
            candidate_value=part_candidate if row is None else None,
            candidate_derived=(row is None and part_candidate is not None),
        )
        vendor_fact = _fact_from_row(
            None,
            None,
            candidate_value=vendor_candidate,
            candidate_derived=(vendor_candidate is not None),
        )
        role_fact = _fact_from_row(
            None,
            None,
            candidate_value=role_candidate,
            candidate_derived=(role_candidate is not None),
        )

        entry = {
            "part_number": part_fact,
            "vendor": vendor_fact,
            "role": role_fact,
        }
        # Schematic-attested per-codec slots (WP_SCHEMATIC_ATTESTED_DESIGN.md
        # §3.2). i2c_bus_label / i2c_address have NO independent automated
        # source (the &i2c18 crosswalk was refused — qgenie_analysis.json:219;
        # 0x31/0x4c are candidate-derived, forbidden to promote). Default
        # NOT_ATTESTED / value=null; a curated origin="schematic" override
        # fills them later. codec_stub keeps its hardcoded &i2c18 / 0x31 / 0x4c
        # fallbacks unchanged on Nord (byte-identity). Inert — no consumer yet.
        for schematic_field in ("i2c_bus_label", "i2c_address", "reset_gpios"):
            leaf = _not_attested_leaf()
            entry[schematic_field] = leaf
            _add_to_manifest(
                leaf, f"codecs[{idx}].{schematic_field}", gaps, counts
            )
        out.append(entry)
        _add_to_manifest(part_fact, f"codecs[{idx}].part_number", gaps, counts)
        _add_to_manifest(vendor_fact, f"codecs[{idx}].vendor", gaps, counts)
        _add_to_manifest(role_fact, f"codecs[{idx}].role", gaps, counts)

    return out


def _build_amplifiers(
    gc: dict[str, Any],
    rows_by_ts: dict[str, dict[str, Any]],
    gaps: list[dict[str, Any]],
    counts: dict[str, int],
) -> list[dict[str, Any]]:
    """Assemble the ``amplifiers`` group. Structure mirrors codecs."""
    amps_in = gc.get("amplifiers")
    if not isinstance(amps_in, list):
        return []
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(amps_in):
        part_candidate = _extract_string(item, keys=("part_number", "name", "model"))
        vendor_candidate = _extract_string(item, keys=("vendor", "manufacturer"))
        role_candidate = _extract_string(item, keys=("role", "position", "kind"))

        row_key = None
        row = None
        if part_candidate:
            for candidate_key in (
                f"T2.amplifier.{part_candidate}",
                f"T5.amplifier.{part_candidate}",
                f"T4a.amplifier.{part_candidate}",
            ):
                if candidate_key in rows_by_ts:
                    row_key = candidate_key
                    row = rows_by_ts[candidate_key]
                    break

        part_fact = _fact_from_row(
            row,
            row_key,
            candidate_value=part_candidate if row is None else None,
            candidate_derived=(row is None and part_candidate is not None),
        )
        vendor_fact = _fact_from_row(
            None,
            None,
            candidate_value=vendor_candidate,
            candidate_derived=(vendor_candidate is not None),
        )
        role_fact = _fact_from_row(
            None,
            None,
            candidate_value=role_candidate,
            candidate_derived=(role_candidate is not None),
        )
        entry = {"part_number": part_fact, "vendor": vendor_fact, "role": role_fact}
        out.append(entry)
        _add_to_manifest(part_fact, f"amplifiers[{idx}].part_number", gaps, counts)
        _add_to_manifest(vendor_fact, f"amplifiers[{idx}].vendor", gaps, counts)
        _add_to_manifest(role_fact, f"amplifiers[{idx}].role", gaps, counts)
    return out


def _build_buses(
    gc: dict[str, Any],
    rows_by_ts: dict[str, dict[str, Any]],
    gaps: list[dict[str, Any]],
    counts: dict[str, int],
) -> list[dict[str, Any]]:
    """Assemble the ``buses`` group.

    Buses = I2S / SoundWire / SLIMbus instances. Each entry has
    ``kind`` (fact), ``instance`` (fact), ``role`` (fact).
    """
    out: list[dict[str, Any]] = []

    # I2S buses come from gc["ipcat"]["i2s_instances"] or
    # gc["buses"]["i2s"] depending on lane. Track T1/T4b rows
    # attest specific ``qup_i2s.<n>`` subjects.
    for idx, item in enumerate(_iter_bus_items(gc, "i2s")):
        instance_candidate = _extract_string(
            item, keys=("instance", "id", "name", "port")
        )
        # Match on T4b.qup_i2s.<n> or T1.i2s.<n>
        row_key = None
        row = None
        if instance_candidate:
            for candidate_key in (
                f"T4b.qup_i2s.{instance_candidate}",
                f"T1.i2s.{instance_candidate}",
                f"T4a.i2s.{instance_candidate}",
            ):
                if candidate_key in rows_by_ts:
                    row_key = candidate_key
                    row = rows_by_ts[candidate_key]
                    break

        kind_fact = _fact_from_row(
            None,
            None,
            candidate_value="i2s",
            candidate_derived=True,
        )
        instance_fact = _fact_from_row(
            row,
            row_key,
            candidate_value=instance_candidate if row is None else None,
            candidate_derived=(row is None and instance_candidate is not None),
        )
        role_fact = _fact_from_row(
            None,
            None,
            candidate_value=_extract_string(item, keys=("role", "direction")),
            candidate_derived=(_extract_string(item, keys=("role", "direction")) is not None),
        )
        entry = {"kind": kind_fact, "instance": instance_fact, "role": role_fact}
        out.append(entry)
        base = f"buses[{len(out) - 1}]"
        _add_to_manifest(kind_fact, f"{base}.kind", gaps, counts)
        _add_to_manifest(instance_fact, f"{base}.instance", gaps, counts)
        _add_to_manifest(role_fact, f"{base}.role", gaps, counts)

    # SoundWire — one entry per master.
    swr = gc.get("soundwire")
    if isinstance(swr, dict) and swr.get("present"):
        master_count = swr.get("master_count") or 1
        try:
            master_count = int(master_count)
        except (TypeError, ValueError):
            master_count = 1
        for m in range(master_count):
            row_key = None
            row = None
            for candidate_key in (
                f"T4b.swr.{m}",
                f"T1.soundwire.{m}",
                f"T5.soundwire.{m}",
            ):
                if candidate_key in rows_by_ts:
                    row_key = candidate_key
                    row = rows_by_ts[candidate_key]
                    break
            kind_fact = _fact_from_row(
                None, None, candidate_value="soundwire", candidate_derived=True
            )
            instance_fact = _fact_from_row(
                row,
                row_key,
                candidate_value=str(m) if row is None else None,
                candidate_derived=(row is None),
            )
            role_fact = _fact_from_row(
                None, None, candidate_value="master", candidate_derived=True
            )
            entry = {"kind": kind_fact, "instance": instance_fact, "role": role_fact}
            out.append(entry)
            base = f"buses[{len(out) - 1}]"
            _add_to_manifest(kind_fact, f"{base}.kind", gaps, counts)
            _add_to_manifest(instance_fact, f"{base}.instance", gaps, counts)
            _add_to_manifest(role_fact, f"{base}.role", gaps, counts)

    return out


def _build_clocks(
    gc: dict[str, Any],
    rows_by_ts: dict[str, dict[str, Any]],
    gaps: list[dict[str, Any]],
    counts: dict[str, int],
) -> list[dict[str, Any]]:
    """Assemble the ``clocks`` group.

    H-1 emits clocks only when the crossverify snapshot carried them
    (Track T1 clock rows). No candidate synthesis — clocks are not
    reliably present in schematic-side gc fields today.
    """
    out: list[dict[str, Any]] = []
    for row_key, row in rows_by_ts.items():
        track, subject = row_key.split(".", 1)
        if track != "T1":
            continue
        if not subject.startswith("clock.") and not subject.startswith("clk."):
            continue
        name_fact = _fact_from_row(row, row_key)
        rate_fact = _fact_from_row(None, None)
        entry = {"name": name_fact, "rate_hz": rate_fact}
        out.append(entry)
        base = f"clocks[{len(out) - 1}]"
        _add_to_manifest(name_fact, f"{base}.name", gaps, counts)
        _add_to_manifest(rate_fact, f"{base}.rate_hz", gaps, counts)
    return out


def _build_audio_links(
    gc: dict[str, Any],
    rows_by_ts: dict[str, dict[str, Any]],
    gaps: list[dict[str, Any]],
    counts: dict[str, int],
) -> list[dict[str, Any]]:
    """Assemble the ``audio_links`` group.

    H-1 emits dai-link entries only when a Track T4a/T4b row exists
    for a specific link subject. No candidate synthesis — link
    inference belongs to a generator, not the projector.
    """
    out: list[dict[str, Any]] = []
    for row_key, row in rows_by_ts.items():
        track, subject = row_key.split(".", 1)
        if track not in ("T4a", "T4b"):
            continue
        if not (subject.startswith("dai_link.") or subject.startswith("route.")):
            continue
        subject_fact = _fact_from_row(row, row_key)
        entry = {"subject": subject_fact}
        out.append(entry)
        base = f"audio_links[{len(out) - 1}]"
        _add_to_manifest(subject_fact, f"{base}.subject", gaps, counts)
    return out


# ── Support helpers ─────────────────────────────────────────────────────────


def _extract_string(item: Any, *, keys: tuple[str, ...]) -> str | None:
    """Return the first non-empty string in ``item[keys[i]]``, else ``None``.

    Accepts ``item`` as either a dict or a bare string (a bare string
    is returned as-is regardless of ``keys``).
    """
    if isinstance(item, str) and item.strip():
        return item.strip()
    if not isinstance(item, dict):
        return None
    for key in keys:
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _iter_bus_items(gc: dict[str, Any], kind: str) -> list[Any]:
    """Yield bus items of ``kind`` from wherever ``gc`` stashed them."""
    buses = gc.get("buses")
    if isinstance(buses, dict):
        sub = buses.get(kind)
        if isinstance(sub, list):
            return list(sub)
    ipcat = gc.get("ipcat")
    if isinstance(ipcat, dict):
        candidate_key = f"{kind}_instances"
        sub = ipcat.get(candidate_key)
        if isinstance(sub, list):
            return list(sub)
    return []


def _enforce_fixture_discipline(
    rows: list[dict[str, Any]], allow_fixture_citations: bool
) -> None:
    """Fail loudly if fixture citations appear without the fixture flag.

    A citation containing ``<fixture: NOT_REAL_TARGET>`` is a signal
    the caller is running the projector against a synthetic fixture.
    That is legal iff :envvar:`H1_VALIDATION_ALLOWS_FIXTURES=1` (or
    the equivalent kwarg). If we ever see a fixture citation without
    the flag, refuse to produce output — the projector must not be
    silently coaxed into treating a synthetic as an onboarded target.
    """
    for row in rows:
        if not isinstance(row, dict):
            continue
        citations = row.get("citations") or []
        for c in citations:
            if isinstance(c, str) and _FIXTURE_CITATION in c:
                if not allow_fixture_citations:
                    raise ValueError(
                        f"Row {row.get('track')}.{row.get('subject')} carries a "
                        f"fixture citation ({_FIXTURE_CITATION!r}) but "
                        f"{_FIXTURE_ENV_FLAG}=1 is not set. Refusing to project "
                        "a synthetic fixture as if it were an onboarded target."
                    )
                return  # First hit is enough — flag check is global.


# ── Curated overrides (G-3A.15) ──────────────────────────────────────────

# Legal FLAT (2-part) ``group.field`` template paths a curated override may
# target. The three schematic board leaves (WP_SCHEMATIC_ATTESTED_DESIGN.md
# §3.2) join the original G-3A.15 trio here — all NOT_ATTESTED slots the
# projector cannot fill from any automated authority.
_CURATED_LEGAL_PATHS: frozenset[str] = frozenset({
    "board_metadata.soc",
    "board_metadata.board_variant",
    "board_metadata.pinctrl_state",
    "board_metadata.mclk",
    "board_metadata.global_md_oe",
    "board_metadata.scmi_index",
})

# Per-codec schematic leaf fields, addressed IDENTITY-KEYED as
# ``codecs.<key>.<field>`` (e.g. ``codecs.adau1979.i2c_address``), NOT
# positionally (``codecs[0]``). ``<key>`` is the codec's part_number identity,
# resolved to the matching entry at apply time (§3.4 ruling: identity-keyed is
# stable across reordering and mirrors the ``T2.codec.<key>`` row convention).
_CODEC_SCHEMATIC_FIELDS: frozenset[str] = frozenset({
    "i2c_bus_label",
    "i2c_address",
    "reset_gpios",
})

# Curated-override origins the validator accepts. Both are human-sourced,
# gap-fill-only, disclosure-only. ``schematic`` marks a value transcribed off a
# named schematic sheet (the sheet ref rides in ``attestation.evidence``). It is
# an ORIGIN string ONLY — never a new authority-strength enum value; strength
# stays the closed ``AUTHORITY_STRENGTHS`` set (WP_SCHEMATIC_ATTESTED_DESIGN.md
# §3.1 confirmations).
_CURATED_LEGAL_ORIGINS: frozenset[str] = frozenset({
    "reviewer_curated",
    "schematic",
})

from orchestrator.reasoning.crossverify_model import AUTHORITY_STRENGTHS  # noqa: E402


def _curated_path_kind(path: str) -> str | None:
    """Classify a curated-override path against the two allowlists.

    Returns ``"board"`` for a legal flat ``board_metadata.<field>`` path,
    ``"codec"`` for a legal identity-keyed ``codecs.<key>.<field>`` schematic
    path, or ``None`` when the path is on neither allowlist. Key EXISTENCE is
    deliberately NOT checked here — the validator has no template to resolve
    against; an unknown codec key is caught loudly at apply time.
    """
    parts = path.split(".")
    if len(parts) == 2 and path in _CURATED_LEGAL_PATHS:
        return "board"
    if (
        len(parts) == 3
        and parts[0] == "codecs"
        and parts[1]  # non-empty identity key
        and parts[2] in _CODEC_SCHEMATIC_FIELDS
    ):
        return "codec"
    return None


def _codec_identity(entry: dict[str, Any]) -> str | None:
    """The identity key of a codec template entry: its part_number value.

    Prefers the attested ``value``; falls back to ``candidate_value`` (the raw
    candidate part number, e.g. ``adau1979``). Mirrors the ``T2.codec.<key>``
    row-key convention so a curated ``codecs.<key>.…`` path resolves to the same
    codec the projector keyed on.
    """
    pn = entry.get("part_number")
    if not isinstance(pn, FactRecord):
        return None
    return pn.value if pn.value is not None else pn.candidate_value


def _is_placeholder_entry(entry: Any) -> bool:
    """True when ``entry`` is a SCHEMA-ONLY placeholder ("not yet curated").

    A placeholder is a dict with ``value`` null (or absent) AND **no**
    ``authority`` and **no** ``attestation`` block — the shape a human writes
    into a skeleton ``curated_overrides.json`` before filling in a real cited
    value (WP_SCHEMATIC_ATTESTED_DESIGN.md §6 step 5). It carries no claim, so
    it is treated as un-curated: skipped at both validation and apply, never
    promoting its leaf to ATTESTED.

    This is deliberately NARROW so it never masks a genuinely-malformed
    attestation: a ``value:null`` entry that DOES carry an ``authority`` or
    ``attestation`` block is NOT a placeholder — it is a null value paired with
    a claim, which stays a loud ValueError (see ``test_null_value_raises``).
    """
    if not isinstance(entry, dict):
        return False
    return (
        entry.get("value") is None
        and "authority" not in entry
        and "attestation" not in entry
    )


def _validate_curated_overrides(
    overrides: dict[str, Any], target_name: str
) -> None:
    """Validate curated_overrides schema. Raises ValueError on any violation.

    SCHEMA-ONLY placeholder entries (:func:`_is_placeholder_entry` — value null,
    no authority, no attestation) pass validation as "not yet curated": their
    path legality is STILL enforced (a typo'd path in a skeleton is still a loud
    error), but the concrete-value / authority / attestation requirements are
    skipped because the entry makes no claim.
    """
    if not isinstance(overrides, dict):
        raise ValueError(
            f"curated_overrides must be a dict, got {type(overrides).__name__}"
        )
    for path, entry in overrides.items():
        if _curated_path_kind(path) is None:
            raise ValueError(
                f"curated_overrides: illegal template path {path!r}; "
                f"legal flat paths are {sorted(_CURATED_LEGAL_PATHS)}, or "
                f"identity-keyed codecs.<key>.<field> where <field> in "
                f"{sorted(_CODEC_SCHEMATIC_FIELDS)}"
            )
        if not isinstance(entry, dict):
            raise ValueError(
                f"curated_overrides[{path!r}]: entry must be a dict, "
                f"got {type(entry).__name__}"
            )
        if _is_placeholder_entry(entry):
            # Un-curated skeleton slot — path already proven legal above. Makes
            # no claim, so the value/authority/attestation checks do not apply.
            continue
        if entry.get("value") is None:
            raise ValueError(
                f"curated_overrides[{path!r}]: null value is not allowed "
                "(a curated override must provide a concrete value)"
            )
        authority = entry.get("authority")
        if not isinstance(authority, dict):
            raise ValueError(
                f"curated_overrides[{path!r}]: authority must be a dict"
            )
        strength = authority.get("strength")
        if strength not in AUTHORITY_STRENGTHS:
            raise ValueError(
                f"curated_overrides[{path!r}]: illegal authority.strength "
                f"{strength!r}; expected one of {sorted(AUTHORITY_STRENGTHS)}"
            )
        if authority.get("origin") not in _CURATED_LEGAL_ORIGINS:
            raise ValueError(
                f"curated_overrides[{path!r}]: authority.origin must be one of "
                f"{sorted(_CURATED_LEGAL_ORIGINS)}, got {authority.get('origin')!r}"
            )
        attestation = entry.get("attestation")
        if not isinstance(attestation, dict):
            raise ValueError(
                f"curated_overrides[{path!r}]: attestation must be a dict"
            )
        if not attestation.get("attested_by"):
            raise ValueError(
                f"curated_overrides[{path!r}]: attestation.attested_by is required"
            )
        if not attestation.get("timestamp"):
            raise ValueError(
                f"curated_overrides[{path!r}]: attestation.timestamp is required"
            )
        if not attestation.get("evidence"):
            raise ValueError(
                f"curated_overrides[{path!r}]: attestation.evidence is required"
            )
        att_target = attestation.get("target")
        if att_target != target_name:
            raise ValueError(
                f"curated_overrides[{path!r}]: attestation.target is "
                f"{att_target!r} but projector target_name is {target_name!r}"
            )


def _apply_curated_overrides(
    template: AudioHardwareTemplate, overrides: dict[str, Any]
) -> None:
    """Apply validated curated overrides to NOT_ATTESTED template facts (gap-fill).

    Two path kinds are honoured (see :func:`_curated_path_kind`):

      * flat ``board_metadata.<field>`` → the board_metadata group;
      * identity-keyed ``codecs.<key>.<field>`` → the codec entry whose
        part_number identity equals ``<key>`` (§3.4 ruling). An unknown ``<key>``
        raises loudly — a curated override that names a codec the target does
        not have is an authoring error, never a silent no-op.

    Gap-fill discipline (unchanged): a FactRecord is replaced ONLY when its
    current ncc_state is NOT_ATTESTED **and** it is not candidate_derived.
    ATTESTED facts (from automation) are never overwritten; a candidate_derived
    leaf is never promoted to attested (the model.py:138 firewall would reject
    the construction anyway — this guard refuses it earlier and explicitly).
    """
    for path, entry in overrides.items():
        if _is_placeholder_entry(entry):
            # Un-curated skeleton slot: no claim to apply. Skipped BEFORE any
            # codec-identity resolution so a placeholder never forces
            # _resolve_codec_entry to raise on a target whose codec identities
            # are still null (e.g. Nord). The leaf stays NOT_ATTESTED → the
            # generation consumer's _template_value returns None → hardcoded
            # fallback fires → byte-identity preserved.
            continue
        kind = _curated_path_kind(path)
        parts = path.split(".")

        if kind == "board":
            group = template.board_metadata
            field_name = parts[1]
        elif kind == "codec":
            codec_key, field_name = parts[1], parts[2]
            group = _resolve_codec_entry(template, codec_key)
        else:
            # Validation already rejected illegal paths; defensive skip.
            continue

        existing = group.get(field_name)
        if not isinstance(existing, FactRecord):
            continue
        if existing.ncc_state != "NOT_ATTESTED":
            continue
        if existing.candidate_derived:
            # Never promote a candidate-derived value to attested. The
            # allowlisted schematic leaves are all candidate_derived=False, so
            # this never fires for them; it hard-stops any future path that
            # points at a candidate slot (e.g. codec part_number).
            continue

        group[field_name] = FactRecord(
            value=entry["value"],
            authority=dict(entry["authority"]),
            citations=list(entry.get("citations") or []),
            row_ref=None,
            independently_verified=False,
            candidate_derived=False,
            candidate_value=None,
            reviewer_required=False,
            ncc_state="ATTESTED",
            # Persist the curated attestation block (validated non-empty above)
            # so a downstream generation consumer can surface the sheet ref in
            # its disclosure comment. Disclosure-only: this never reaches
            # cross_verification / TrustedFacts / any gate.
            attestation=dict(entry["attestation"]),
        )


def _resolve_codec_entry(
    template: AudioHardwareTemplate, codec_key: str
) -> dict[str, Any]:
    """Return the codec template entry whose identity equals ``codec_key``.

    Raises ``ValueError`` (loud) when no codec matches — a curated override
    naming an absent codec is an authoring error, per the step-2 contract.
    """
    for entry in template.codecs:
        if _codec_identity(entry) == codec_key:
            return entry
    known = [_codec_identity(e) for e in template.codecs]
    raise ValueError(
        f"curated_overrides: codec identity {codec_key!r} not found in "
        f"template; known codec identities are {known!r}"
    )


# ── curated-override file loading (WP_SCHEMATIC_ATTESTED_DESIGN §6 step 3) ────


def load_curated_overrides(
    path: str | Path, *, required: bool
) -> dict[str, Any] | None:
    """Load a ``curated_overrides.json`` file for a target.

    This is the single loader shared by every onboarding-time write site
    (the projector ``_cli`` and the H-1 validation harness) so that the
    file-handling contract is identical everywhere:

      * **Missing file** — honest degradation. If ``required`` is False
        (convention-driven auto-load: ``targets/<t>/curated_overrides.json``
        may simply not exist for an un-curated target) return ``None`` so the
        projector runs inert and every schematic leaf stays NOT_ATTESTED. If
        ``required`` is True (an explicit ``--curated-overrides PATH`` was
        given), a missing file is a loud :class:`FileNotFoundError` — the
        caller asked for a specific file and it is not there.
      * **Malformed JSON / non-object** — always a loud :class:`ValueError`,
        regardless of ``required``. A curated file that exists but cannot be
        parsed is never silently ignored: silence there would drop a human's
        attested schematic facts without a trace.

    The returned dict is NOT validated here — validation is
    :func:`_validate_curated_overrides`, invoked inside :func:`project`. This
    function only turns bytes-on-disk into the ``dict | None`` that
    ``project(curated_overrides=...)`` expects.
    """
    p = Path(path)
    if not p.is_file():
        if required:
            raise FileNotFoundError(f"curated overrides file not found: {p}")
        return None
    try:
        loaded = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"malformed curated overrides file {p}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError(
            f"curated overrides file {p} must contain a JSON object, "
            f"got {type(loaded).__name__}"
        )
    return loaded


# ── CLI ─────────────────────────────────────────────────────────────────────


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="orchestrator.hw_template.projector",
        description=(
            "Project gc['cross_verification']['rows'] into an audio hardware "
            "template + gap manifest. Data-flow leaf; never writes back."
        ),
    )
    parser.add_argument(
        "--gc-json",
        required=True,
        help="Path to a JSON file containing the generated-case dict "
             "(must have a top-level 'cross_verification' key).",
    )
    parser.add_argument("--target", required=True, help="target_name to record.")
    parser.add_argument("--run-id", required=True, help="run_id to record.")
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Directory to write audio_hardware_template.json + "
             "gap_manifest.json into.",
    )
    parser.add_argument(
        "--curated-overrides",
        default=None,
        help="Optional path to a curated_overrides.json file "
             "(schematic-attested / reviewer-curated gap-fills). If given, the "
             "file MUST exist and be valid JSON — a missing or malformed file "
             "is a loud error. Overrides are applied gap-fill-only to "
             "NOT_ATTESTED leaves; they never overwrite attested values and "
             "never reach cross_verification.",
    )
    args = parser.parse_args(argv)

    gc = json.loads(Path(args.gc_json).read_text(encoding="utf-8"))
    if not isinstance(gc, dict):
        print(f"error: {args.gc_json} does not contain a JSON object", file=sys.stderr)
        return 2

    # An explicit --curated-overrides PATH means the file is REQUIRED: a
    # missing/malformed file is loud (never silently dropped).
    try:
        curated = (
            load_curated_overrides(args.curated_overrides, required=True)
            if args.curated_overrides is not None
            else None
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        result = project(
            gc,
            target_name=args.target,
            run_id=args.run_id,
            curated_overrides=curated,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    template_path, gap_path = write_outputs(result, args.out_dir)
    print(f"wrote {template_path}")
    print(f"wrote {gap_path}")
    print(f"gaps_by_reason={dict(result.gap_manifest.gap_count_by_reason)}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
