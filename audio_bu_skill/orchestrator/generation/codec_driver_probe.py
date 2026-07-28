"""Slice 1 — read-only kernel codec-driver probe (codec_stub lane).

A ``CodecDriverProbe`` grounds ONE codec_stub disclosure against the actual
kernel tree instead of a hardcoded assertion:

  * codec ``compatible`` — for a given codec identity (e.g. ``adau1979`` /
    ``pcm1681``), what ``.compatible = "..."`` literal does the upstream codec
    driver's ``of_match_table`` actually carry?

Why this source and not the candidate DTS:

  The codec ``compatible`` VALUE is attested from the KERNEL CODEC DRIVER's
  ``of_device_id`` match table — an INDEPENDENT, kernel-source authority that
  does NOT reference the unapplied candidate DTS (commit ``5267b2e1``). The
  codec IDENTITY used to *select* which driver file to read (the join key) is
  itself candidate-derived; that provenance caveat is disclosed by the caller
  in ``contributes_rows`` — the attested value is only as trustworthy as the
  codec selection.

Hard constraints (Slice 1):

  * READ-ONLY. Opens *at most* a small, bounded, deterministic set of codec
    driver ``.c`` files under ``sound/soc/codecs/`` (per-key candidate list —
    no glob, no walk, no writes, no network). Never raises on a missing tree /
    file — a missing input degrades honestly to ``FILE_NOT_FOUND`` (→ NOT
    kernel-attested downstream), never a fabricated FOUND / ABSENT.
  * DISCLOSURE-ONLY. This object flows into ``contributes_rows`` notes and the
    emitted ``compatible`` literal only. It NEVER reaches
    ``cross_verification``, ``TrustedFacts``, or any gate; ``is_open`` does not
    consult it. It cannot promote a candidate or open a closed gate.
  * BYTE-IDENTITY on Nord. The observed of_match_table compatibles
    (``adi,adau1979``, ``ti,pcm1681``) equal the hardcoded ``_NORD_CODECS``
    values, so the emitted bytes are unchanged — only the provenance shifts to
    ``kernel_source``.

The frozen dataclass is deterministic: same tree contents + same codec_keys →
same probe.

Identity → file mapping (bounded, no glob):

  A codec identity does not always map to ``<identity>.c``. ``pcm1681`` lives in
  ``pcm1681.c``; ``adau1979`` has NO ``adau1979.c`` — its compatible lives in the
  shared ``adau1977-spi.c`` of_match_table (alongside adau1977/adau1978). The
  probe therefore tries a fixed per-key candidate list (direct filename first,
  then bounded family variants). Selection within a multi-compatible table is by
  suffix join: the literal whose vendor-stripped part equals the codec key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from orchestrator.generation.source_probe import ClaimStatus, _safe_read

#: Directory (relative to the kernel tree root) that hosts ASoC codec drivers.
_CODEC_DIR = "sound/soc/codecs"

#: Every ``.compatible = "..."`` string literal — the of_match_table entries.
#: Same pattern as SourceProbe so both probes observe compatibles identically.
_COMPATIBLE_RE = re.compile(r'\.compatible\s*=\s*"([^"]+)"')

#: Bounded per-codec-key candidate filename list under ``sound/soc/codecs/``.
#: Direct ``<key>.c`` first, then a fixed set of family variants. This is the
#: ONLY place identity→file knowledge lives; a key absent from this map falls
#: back to the single direct candidate ``<key>.c`` (no glob / walk ever).
#:
#:   * ``adau1979`` — no ``adau1979.c`` exists; its compatible is in the shared
#:     ADAU197x driver. The SPI variant carries the of_match_table on Nord.
#:   * ``pcm1681`` — direct filename hit.
_CODEC_FILE_CANDIDATES: dict[str, tuple[str, ...]] = {
    "adau1979": ("adau1979.c", "adau1977-spi.c", "adau1977-i2c.c", "adau1977.c"),
    "pcm1681": ("pcm1681.c",),
}


def _candidates_for(codec_key: str) -> tuple[str, ...]:
    """Deterministic, bounded candidate filenames for a codec identity.

    Known keys use their explicit family list; unknown keys degrade to the
    single direct candidate ``<key>.c``. Never globs or walks the tree.
    """
    return _CODEC_FILE_CANDIDATES.get(codec_key, (f"{codec_key}.c",))


def _compatible_matches_key(compatible: str, codec_key: str) -> bool:
    """True when a ``vendor,part`` compatible's part equals the codec key.

    ``"adi,adau1979"`` matches key ``"adau1979"``; ``"adi,adau1977"`` does not.
    A compatible with no comma is compared whole (defensive; upstream codec
    compatibles are always ``vendor,part``).
    """
    part = compatible.rsplit(",", 1)[-1].strip()
    return part == codec_key


@dataclass(frozen=True)
class _CodecObservation:
    """Per-codec-key observation of the kernel driver of_match_table.

    ``status`` is the ternary claim state. When ``FOUND``, ``compatible`` /
    ``driver_file`` / ``line`` carry the attested literal and its location.
    When ``ABSENT`` (driver file(s) read but no matching compatible) or
    ``FILE_NOT_FOUND`` (no candidate file readable), those are ``None``.
    """

    codec_key: str
    status: ClaimStatus
    compatible: str | None = None
    driver_file: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class CodecDriverProbe:
    """Immutable, disclosure-only observation of kernel codec driver tables.

    Construct via :meth:`from_tree`; never mutate. Query a codec identity via
    :meth:`compatible_for`. Board-blind beyond the codec_keys it was asked to
    resolve — it records only what it observed in the driver ``.c`` files.
    """

    tree: str | None
    observations: tuple[_CodecObservation, ...] = ()

    @classmethod
    def from_tree(
        cls,
        tree: str | None,
        codec_keys: tuple[str, ...] | list[str],
    ) -> "CodecDriverProbe":
        """Build a probe by reading bounded candidate codec drivers under ``tree``.

        ``tree`` may be ``None`` or a path that does not exist / is not a
        directory — every such case yields a probe whose every observation is
        ``FILE_NOT_FOUND`` with no exception raised. ``codec_keys`` are the codec
        identities (candidate-derived join keys) to resolve, in caller order;
        observations are stored in sorted-key order for determinism.
        """
        keys = tuple(sorted(set(codec_keys)))

        if not tree:
            return cls(
                tree=tree,
                observations=tuple(
                    _CodecObservation(codec_key=k, status=ClaimStatus.FILE_NOT_FOUND)
                    for k in keys
                ),
            )

        root = Path(tree)
        if not root.is_dir():
            return cls(
                tree=tree,
                observations=tuple(
                    _CodecObservation(codec_key=k, status=ClaimStatus.FILE_NOT_FOUND)
                    for k in keys
                ),
            )

        observations = tuple(cls._resolve_key(root, k) for k in keys)
        return cls(tree=tree, observations=observations)

    @staticmethod
    def _resolve_key(root: Path, codec_key: str) -> _CodecObservation:
        """Resolve one codec identity against its bounded candidate drivers.

        Returns FOUND with the first matching ``.compatible`` literal (by suffix
        join), ABSENT if at least one candidate file was readable but none
        carried a matching literal, and FILE_NOT_FOUND if no candidate file
        could be read at all.
        """
        any_readable = False
        for candidate in _candidates_for(codec_key):
            text = _safe_read(root / _CODEC_DIR / candidate)
            if text is None:
                continue
            any_readable = True
            for lineno, line in enumerate(text.splitlines(), start=1):
                m = _COMPATIBLE_RE.search(line)
                if m and _compatible_matches_key(m.group(1), codec_key):
                    return _CodecObservation(
                        codec_key=codec_key,
                        status=ClaimStatus.FOUND,
                        compatible=m.group(1),
                        driver_file=f"{_CODEC_DIR}/{candidate}",
                        line=lineno,
                    )
        if any_readable:
            return _CodecObservation(
                codec_key=codec_key, status=ClaimStatus.ABSENT
            )
        return _CodecObservation(
            codec_key=codec_key, status=ClaimStatus.FILE_NOT_FOUND
        )

    def compatible_for(
        self, codec_key: str
    ) -> tuple[ClaimStatus, str | None, str | None, int | None]:
        """Ground a codec identity's compatible: (status, compatible, file, line).

        ``FILE_NOT_FOUND`` if no candidate driver was readable (or the key was
        never probed); ``FOUND`` with the attested ``.compatible`` literal + its
        driver file/line when the of_match_table lists a matching entry;
        ``ABSENT`` when the driver was read but carries no matching compatible.
        """
        for obs in self.observations:
            if obs.codec_key == codec_key:
                return (obs.status, obs.compatible, obs.driver_file, obs.line)
        return (ClaimStatus.FILE_NOT_FOUND, None, None, None)


__all__ = ["CodecDriverProbe", "ClaimStatus"]
