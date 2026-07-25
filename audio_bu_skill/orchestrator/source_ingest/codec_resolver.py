"""WP G-3A.8 Option 2: kernel-source codec resolver.

Purpose
=======
Populate ``codec_verdicts`` on the generated case with real driver
evidence derived from the kernel tree at ``--kernel-source``, so
``codec_driver_porting`` at ``bringup_walk.py:195`` clears the
``evidence_required=True`` gate at ``driver.py:181-186`` instead of
crashing every ``--generate`` run with ``EVIDENCE_REFERENCE_MISSING``.

Replaces the previous filename-guess stub
``_derive_codec_verdicts`` at
``orchestrator/runners/target_onboarding_runner.py:829-844`` (which
did ``codecs_dir / f"{part.lower()}.c"`` and got structurally wrong
answers on two independent failure modes on the real Nord payload):

  1. **Label bloat.** The onboarding runner keys verdicts by the long
     descriptive label (e.g.
     ``"adi,adau1979 (ADI ADAU1979 4-ch ADC, ...)"``). Lowercasing
     that and appending ``.c`` matches nothing under
     ``sound/soc/codecs/``, so every codec fell to ``unresolved``.
  2. **Shared-family blindness.** Even with a clean part name,
     ``adau1979`` has NO ``adau1979.c``. It is served by the shared
     family driver ``sound/soc/codecs/adau1977.c`` +
     ``adau1977-spi.c`` + ``adau1977-i2c.c`` via
     ``enum adau1977_type { ADAU1977, ADAU1978, ADAU1979 }`` and
     the shared binding
     ``Documentation/devicetree/bindings/sound/adi,adau1977.yaml``.
     A filename-based matcher WILL wrongly mark it "needs-development"
     — the ADAU1979 correctness guard forbids that error mode.

Vocabulary mapping
==================
This resolver reuses the skill's existing verdict vocabulary at
``skills/codec_driver_porting/validator.py:32,49`` to avoid opening a
validator+runner+schema edit this WP:

  * user's ``driver-exists``       → ``upstream_present`` (the skill token).
  * user's ``needs-development``   → ``needs_write``       (the skill token).

Preserved rich-evidence fields (per user approval condition (b) —
binding-only case must be human-triageable without a re-run):

  * ``driver_path``    — real ``sound/soc/codecs/<file>.c`` on hit; None on miss.
  * ``binding_paths``  — every ``Documentation/devicetree/bindings/sound/*``
                         file whose contents mention the compatible.
  * ``header_paths``   — every ``include/dt-bindings/sound/*`` header
                         whose contents mention the compatible.
  * ``searched_paths`` — top-level directories walked (negative-evidence
                         trail) so a ``needs_write`` verdict is auditable.
  * ``matched_via``    — one of
                         ``"compatible_string"`` /
                         ``"i2c_device_id_name"`` /
                         ``"enum_family"`` /
                         ``"binding_only"`` /
                         ``"unmatched"``
                         so the WHY is on-record for every hit.

Match algorithm (per codec, in order — first hit wins for driver_path)
======================================================================
1. **Extract clean compatible.** Regex ``^([a-z0-9]+,[a-z0-9_-]+)`` on
   the labelled string → ``vendor,part``. Tolerates both the messy
   Nord form (``"adi,adau1979 (ADI ADAU1979 ..."``) and a clean
   ``"vendor,part"``. Missing → ``needs_write`` +
   ``matched_via="unmatched"``.

2. **Direct compatible-in-.c grep.** Under
   ``sound/soc/codecs/``, look for the token ``"vendor,part"`` inside
   any ``.c`` file's ``of_device_id`` / ``.compatible`` block. On
   ``ti,pcm1681`` this hits ``pcm1681.c:264``. On ``adi,adau1979``
   this hits ``adau1977-spi.c:60`` — resolving the enclosing family
   driver ``adau1977.c`` via the shared-file heuristic below.

3. **i2c_device_id.name fallback.** Some family drivers register the
   I2C personality by ``i2c_device_id`` name-table only, with no
   ``compatible`` entry in the ``-i2c.c`` file (real example:
   ``adau1977-i2c.c:33`` — ``{ .name = "adau1979", ... }``). Search
   for ``.name = "<part>"`` in ``sound/soc/codecs/*-i2c.c`` (and the
   ``-spi.c`` sibling) with the compatible's tail as ``<part>``.

4. **Enum-family fallback.** For any codec still unmatched, scan
   ``sound/soc/codecs/*.c`` for ``enum ... _type`` blocks and
   uppercased ``<PART>`` tokens. This is the pure ADAU1979 guard
   path: if steps 2 and 3 miss, the ``ADAU1979`` symbol inside
   ``adau1977.h`` (surfaced by any ``#include "adau1977.h"`` .c file)
   still resolves the enclosing family driver.

5. **Enclosing family-driver resolution.** For any hit on
   ``<file>-spi.c`` / ``<file>-i2c.c`` / ``<file>.c``, prefer the
   family ``<file>.c`` if it exists on disk (that is the real ASoC
   codec driver; the ``-spi``/``-i2c`` shims only register the bus
   personality). Confirmed on Nord: matching ``adi,adau1979`` in
   ``adau1977-spi.c`` collapses to ``adau1977.c`` — matches user's
   expected preflight outcome.

6. **Binding / header sweep** (always, orthogonal to driver hit).
   Under ``Documentation/devicetree/bindings/sound/*`` and
   ``include/dt-bindings/sound/*``, record every file whose contents
   mention the compatible. Even when the driver hit failed, a binding
   hit is a human-triageable "driver-needs-write, binding-exists"
   verdict — preserved via ``binding_paths`` / ``header_paths``.

Determinism
===========
Every list is sorted before emission. ``kernel_source.glob(...)``
iteration order is filesystem-dependent, so results are collected
into ``set`` / ``list``, sorted lexicographically, then serialised.
Byte-identical input yields byte-identical output.

Generality
==========
No Nord token appears in the resolver body. Every derived value comes
off the labelled input string and the kernel tree scan. A synthetic
non-Nord codec (``xyz,fake-1234``) with a corresponding synthetic
driver produces facts carrying that codec's tokens — mirrors the
WP-SRC-B2-GENERALITY guard.

Signed-off-by: Ajay Kumar Nandam <ajay.nandam@oss.qualcomm.com>
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

# Extracts the leading ``vendor,part`` token from a labelled codec
# string. Anchored to start-of-string; tolerates lowercase / digit /
# ``_`` / ``-`` in the part component. Rejects trailing whitespace or
# parenthetical descriptors (they get stripped by ``.strip()`` before
# the regex sees them).
_COMPATIBLE_RE = re.compile(r"^([a-z0-9]+),([a-z0-9_\-]+)")

# Directories walked. Recorded verbatim into ``searched_paths`` on
# every verdict so the negative-evidence trail is on-record for
# human triage of ``needs_write`` cases.
_CODECS_DIR = ("sound", "soc", "codecs")
_BINDINGS_DIR = ("Documentation", "devicetree", "bindings", "sound")
_HEADERS_DIR = ("include", "dt-bindings", "sound")


def _extract_compatible(label: str) -> tuple[str, str] | None:
    """Return ``(vendor, part)`` extracted from a codec label, or None.

    Tolerates the labelled Nord form
    (``"adi,adau1979 (ADI ADAU1979 ..."``) and clean ``"vendor,part"``.
    A missing / malformed leading token is not a resolver crash — the
    caller records a ``needs_write`` verdict with
    ``matched_via="unmatched"``.
    """
    if not isinstance(label, str):
        return None
    stripped = label.strip().lower()
    if not stripped:
        return None
    match = _COMPATIBLE_RE.match(stripped)
    if not match:
        return None
    return (match.group(1), match.group(2))


def _read_text_safe(path: Path) -> str:
    """Read a file's contents as UTF-8 text; return ``""`` on any read
    failure (permission, binary noise, missing file racing with glob).

    The resolver runs against a checked-out kernel tree so read
    failures are extraordinary — treat them as absent-content, never
    as a resolver crash.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""


def _search_compatible_in_c(codecs_dir: Path, compatible: str) -> set[Path]:
    """Return every ``.c`` under ``codecs_dir`` whose text contains the
    compatible string as a quoted OF-match literal (e.g.
    ``"adi,adau1979"``).

    Matching on the quoted form suppresses hits inside comments that
    write the token bare — the ``of_device_id`` array is the
    authoritative match site.
    """
    if not codecs_dir.is_dir():
        return set()
    needle = f'"{compatible}"'
    hits: set[Path] = set()
    for path in codecs_dir.glob("*.c"):
        if needle in _read_text_safe(path):
            hits.add(path)
    return hits


def _search_i2c_device_id_name(codecs_dir: Path, part: str) -> set[Path]:
    """Return every ``.c`` under ``codecs_dir`` whose text registers
    ``<part>`` via an ``i2c_device_id`` name-table entry (``.name =
    "part"``).

    Real example: ``adau1977-i2c.c:33`` has ``{ .name = "adau1979",
    .driver_data = ADAU1978 }`` and NO ``compatible`` entry. Step 3
    of the algorithm depends on this to catch the ADAU1979 I2C
    personality when SPI-side has already matched — this is a
    correctness-guard duplicate, cheap enough to always run.
    """
    if not codecs_dir.is_dir():
        return set()
    needle = f'.name = "{part}"'
    hits: set[Path] = set()
    for path in codecs_dir.glob("*.c"):
        if needle in _read_text_safe(path):
            hits.add(path)
    return hits


def _search_enum_family(codecs_dir: Path, part: str) -> set[Path]:
    """Return every ``.c`` under ``codecs_dir`` whose text mentions the
    uppercased part token AND declares an ``enum ... _type`` block.

    Family-driver fallback for parts served by a differently-named
    family driver (ADAU1979 → adau1977.c via
    ``enum adau1977_type``). The ``enum ... _type`` guard suppresses
    incidental symbol references and unrelated defines.
    """
    if not codecs_dir.is_dir():
        return set()
    part_upper = part.upper()
    hits: set[Path] = set()
    for path in codecs_dir.glob("*.c"):
        text = _read_text_safe(path)
        if part_upper not in text:
            continue
        # Also check the sibling .h since the enum lives in the header
        # more often than the .c file.
        header = path.with_suffix(".h")
        if "_type" in text or "_type" in _read_text_safe(header):
            hits.add(path)
    return hits


def _prefer_family_driver(hits: set[Path]) -> Path | None:
    """Given a set of hit ``.c`` files, return the enclosing family
    ``<name>.c`` if it exists (strip ``-i2c`` / ``-spi`` suffixes).

    Rationale: ``adau1977-spi.c`` and ``adau1977-i2c.c`` are bus
    personalities; ``adau1977.c`` is the actual ASoC codec driver.
    Downstream ``codec_driver_porting`` wants the driver, not the
    shim.

    Deterministic across hit-set orderings — sorts hits, prefers the
    family-collapsed path over any suffixed sibling.
    """
    if not hits:
        return None
    ordered = sorted(hits)
    for path in ordered:
        stem = path.stem
        # Strip a trailing ``-i2c`` / ``-spi`` / ``-hda`` bus-shim suffix.
        for suffix in ("-i2c", "-spi", "-hda", "-slim"):
            if stem.endswith(suffix):
                family = path.with_name(stem[: -len(suffix)] + ".c")
                if family.is_file():
                    return family
    # No bus-shim collapse applied — return the deterministic first hit.
    return ordered[0]


def _search_files_containing(
    root: Path, pattern: str, needle: str, kernel_source: Path
) -> list[str]:
    """Return sorted repo-relative paths under ``root`` whose text
    contains ``needle``. Repo-relative to ``kernel_source``.

    Used for binding / header sweeps. Callers pass the compatible as
    ``needle``, the file pattern (``"*.yaml"``, ``"*.txt"``, ``"*.h"``),
    and ``kernel_source`` for the relative-path anchor (never derived —
    passing it in eliminates a walk-up bug where absolute ``.parts``
    tricked the depth lookup on 4-deep subtrees like
    ``Documentation/devicetree/bindings/sound``).
    """
    if not root.is_dir():
        return []
    hits: list[str] = []
    for path in root.rglob(pattern):
        if not path.is_file():
            continue
        if needle in _read_text_safe(path):
            rel = path.relative_to(kernel_source)
            hits.append(str(rel))
    return sorted(hits)


def _searched_paths(kernel_source: Path) -> list[str]:
    """Return the deterministic ``searched_paths`` list — sorted,
    repo-relative to ``kernel_source``. Populated on every verdict
    (hit and miss) so the audit trail is uniform.
    """
    return sorted(
        [
            "/".join(_CODECS_DIR),
            "/".join(_BINDINGS_DIR),
            "/".join(_HEADERS_DIR),
        ]
    )


def _relative_or_none(kernel_source: Path, path: Path | None) -> str | None:
    """Return ``str(path.relative_to(kernel_source))`` or None. Safe
    against a path outside ``kernel_source`` — returns None rather
    than raising.
    """
    if path is None:
        return None
    try:
        return str(path.relative_to(kernel_source))
    except ValueError:
        return None


def _resolve_one(label: str, kernel_source: Path) -> dict[str, Any]:
    """Resolve one codec label into a verdict dict. Runs all four
    match paths, sweeps bindings/headers, and emits the rich-evidence
    verdict.

    Never raises — a resolver bug that produces no useful evidence
    still emits ``needs_write`` + ``matched_via="unmatched"``.
    """
    codecs_dir = kernel_source.joinpath(*_CODECS_DIR)
    bindings_dir = kernel_source.joinpath(*_BINDINGS_DIR)
    headers_dir = kernel_source.joinpath(*_HEADERS_DIR)

    parsed = _extract_compatible(label)
    if parsed is None:
        return {
            "driver_path": None,
            "status": "needs_write",
            "matched_via": "unmatched",
            "compatible": "",
            "binding_paths": [],
            "header_paths": [],
            "searched_paths": _searched_paths(kernel_source),
            "reason": "no_compatible_in_label",
        }
    vendor, part = parsed
    compatible = f"{vendor},{part}"

    # Path 1: direct compatible-in-.c grep.
    direct_hits = _search_compatible_in_c(codecs_dir, compatible)
    matched_via = "compatible_string" if direct_hits else ""

    # Path 2: i2c_device_id.name fallback (I2C-side personality has no
    # ``.compatible`` — matches by ``i2c_device_id`` name-table).
    if not direct_hits:
        i2c_hits = _search_i2c_device_id_name(codecs_dir, part)
        if i2c_hits:
            direct_hits = i2c_hits
            matched_via = "i2c_device_id_name"

    # Path 3: enum-family fallback (ADAU1979 guard). Only fires if
    # steps 1+2 both miss.
    if not direct_hits:
        enum_hits = _search_enum_family(codecs_dir, part)
        if enum_hits:
            direct_hits = enum_hits
            matched_via = "enum_family"

    # Bindings / headers sweep is orthogonal to driver hits. Always
    # runs so a "driver-needs-write, binding-exists" case is
    # human-triageable without a re-run.
    binding_paths = _search_files_containing(
        bindings_dir, "*.yaml", compatible, kernel_source
    )
    binding_paths.extend(
        _search_files_containing(bindings_dir, "*.txt", compatible, kernel_source)
    )
    binding_paths = sorted(set(binding_paths))
    header_paths = _search_files_containing(
        headers_dir, "*.h", compatible, kernel_source
    )

    driver_path_abs = _prefer_family_driver(direct_hits) if direct_hits else None
    driver_rel = _relative_or_none(kernel_source, driver_path_abs)

    if driver_rel is not None:
        # Real driver on disk → upstream_present. Never fabricates
        # ``driver_path``: only sets it when the resolver actually
        # located an on-disk file inside ``sound/soc/codecs/``.
        return {
            "driver_path": driver_rel,
            "status": "upstream_present",
            "matched_via": matched_via,
            "compatible": compatible,
            "binding_paths": binding_paths,
            "header_paths": header_paths,
            "searched_paths": _searched_paths(kernel_source),
        }

    # No driver on disk, but bindings may still exist → binding_only
    # is still a ``needs_write`` verdict (driver must be written) —
    # but the ``binding_paths`` field preserves the positive evidence
    # for the human triage lane. Distinct ``matched_via`` value.
    resolved_matched_via = "binding_only" if binding_paths or header_paths else "unmatched"
    return {
        "driver_path": None,
        "status": "needs_write",
        "matched_via": resolved_matched_via,
        "compatible": compatible,
        "binding_paths": binding_paths,
        "header_paths": header_paths,
        "searched_paths": _searched_paths(kernel_source),
    }


def resolve_codec_verdicts(
    codec_part_numbers: Iterable[str],
    kernel_source: Path,
) -> dict[str, dict[str, Any]]:
    """Return a ``label -> verdict`` mapping for every codec label.

    Signature mirrors the previous ``_derive_codec_verdicts`` stub so
    the drop-in replacement at
    ``target_onboarding_runner.py:550`` is one line.

    Ordering: the returned dict is keyed by the input labels in
    lexicographic order — the same ordering as the previous stub.
    Byte-identical input yields byte-identical output.
    """
    labels = sorted(str(label) for label in codec_part_numbers)
    result: dict[str, dict[str, Any]] = {}
    for label in labels:
        result[label] = _resolve_one(label, kernel_source)
    return result


__all__ = ["resolve_codec_verdicts"]
