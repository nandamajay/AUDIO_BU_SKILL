"""WP G-3A.9: candidate .dts codec-node reader (pure parser).

Purpose
=======
Read audio codec nodes from a candidate device-tree source file and
emit a deterministic list of bare codec facts. This module is the
*source-of-facts* half of G-3A.9; the runner (``target_onboarding_runner``)
decorates each fact with the honest-label ``provenance_tag`` and
``source`` marker and gates injection into ``analysis["codecs"]``. This
separation is structural:

  * Reader knows nothing about provenance tags, source markers, or the
    injection gate. It cannot be tricked into producing a "clean" codec
    by any caller — the tag+source contract is enforced strictly by the
    runner.
  * Runner knows nothing about DT syntax. It cannot produce a codec
    fact without going through this reader; a monkey-patched reader
    returning tag-less facts still fails the runner's hard-fail guard.

Contract
========
``read_codecs_from_dts(dts_path: str) -> list[dict[str, Any]]``:

  * On success — a sorted list of ``{"label": <str>, "compatible":
    <str>, "part": <str>}`` dicts, one per audio-codec node found in
    the file. ``part`` is the ``vendor,part`` token verbatim (e.g.
    ``"ti,pcm1681"``) — kept as a single string so the runner can pass
    it through ``resolve_codec_verdicts`` unchanged.
  * On any failure (missing path, unreadable file, malformed syntax,
    zero codec nodes matched) — ``[]``. Never raises. The runner
    interprets ``[]`` as "no candidate source usable" and leaves
    ``analysis["codecs"]`` unchanged (backwards-compat guarantee).

Extraction strategy
===================
Regex-based scan of labelled audio-codec node blocks of the form::

    <label>: audio-codec@<addr> {
        compatible = "<vendor>,<part>";
        ...
    };

Full DTS parsing (includes, preprocessor, phandle resolution) is
deliberately out of scope. The candidate .dts payload verified at
commit 5267b2e1 uses this exact node style with clean quoted
compatible strings, so a naive brace-matched regex sweep is
sufficient for the G-3A.9 north-star flip.

Determinism
===========
Results are sorted by ``(label, compatible)`` before return. Repeat
invocations on byte-identical input yield byte-identical output.

Generality
==========
No Nord token appears in this module. Every fact is derived from the
input file's own contents. A synthetic non-Nord .dts with a codec
node bearing a synthetic compatible (``xyz,fake-1234``) yields a
fact carrying exactly that compatible — mirrors the
WP-SRC-B2-GENERALITY guard.

Signed-off-by: Ajay Kumar Nandam <ajay.nandam@oss.qualcomm.com>
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Matches ``<label>: audio-codec@<addr> {`` — the labelled audio-codec
# node header. Case-insensitive on the ``audio-codec`` keyword.
# ``<label>`` is a bare identifier (letters/digits/underscore); ``<addr>``
# is a hex or decimal literal — captured but not consumed downstream.
_CODEC_NODE_RE = re.compile(
    r"(\w+)\s*:\s*audio-codec@[0-9a-fA-F]+\s*\{",
    flags=re.IGNORECASE,
)

# Extracts the quoted ``vendor,part`` inside a ``compatible = "..."``
# property. Anchored to the property keyword to reject unrelated
# quoted strings inside the same node body. Multi-value compatibles
# (``compatible = "a,b", "c,d";``) — the first value wins by regex
# greediness on the leading quoted token.
_COMPATIBLE_RE = re.compile(
    r'compatible\s*=\s*"([a-z0-9]+,[a-z0-9_\-]+)"',
    flags=re.IGNORECASE,
)


def _find_matching_brace(text: str, start: int) -> int:
    """Return the index of the ``}`` matching ``text[start] == '{'``.

    Naive depth-counted brace matcher — same shape as
    ``dt_reader._find_matching_brace``. DTS codec node bodies don't
    contain string literals or comments in the payloads we care about,
    so the depth counter is safe. Returns ``-1`` on unbalanced input,
    which cascades to a caller-visible "node skipped" outcome — the
    reader keeps scanning past unbalanced blocks.
    """
    if start >= len(text) or text[start] != "{":
        return -1
    depth = 1
    i = start + 1
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _extract_codecs(text: str) -> list[dict[str, Any]]:
    """Scan ``text`` for audio-codec nodes and return bare codec facts.

    Iterates labelled ``audio-codec@`` blocks in document order; for
    each block, looks up the first ``compatible = "..."`` property
    inside the balanced body. A node without a well-formed compatible
    is skipped (not a reader error — just not a usable fact).
    """
    results: list[dict[str, Any]] = []
    pos = 0
    while pos < len(text):
        m = _CODEC_NODE_RE.search(text, pos)
        if not m:
            break
        label = m.group(1)
        brace_start = m.end() - 1
        brace_end = _find_matching_brace(text, brace_start)
        if brace_end < 0:
            # Unbalanced — advance past the opening brace and keep
            # scanning. Prevents an infinite loop on malformed input.
            pos = brace_start + 1
            continue
        body = text[brace_start + 1 : brace_end]
        compatible_m = _COMPATIBLE_RE.search(body)
        if compatible_m:
            compatible = compatible_m.group(1).lower()
            results.append(
                {
                    "label": label,
                    "compatible": compatible,
                    "part": compatible,
                }
            )
        pos = brace_end + 1
    return results


def read_codecs_from_dts(dts_path: str) -> list[dict[str, Any]]:
    """Read audio-codec node facts from a candidate .dts file.

    Args:
      dts_path: Filesystem path to a .dts / .dtsi file (candidate
        source, not necessarily merged in-tree).

    Returns:
      * On success — a sorted list of ``{"label", "compatible",
        "part"}`` dicts.
      * On any failure (missing file, unreadable, non-file, malformed,
        zero codec nodes) — ``[]``. Never raises.

    Determinism: results are sorted by ``(label, compatible)`` so
    repeat invocations on byte-identical input yield byte-identical
    output.
    """
    try:
        path = Path(dts_path)
    except (TypeError, ValueError):
        return []
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    codecs = _extract_codecs(text)
    codecs.sort(key=lambda c: (c["label"], c["compatible"]))
    return codecs


__all__ = ["read_codecs_from_dts"]
