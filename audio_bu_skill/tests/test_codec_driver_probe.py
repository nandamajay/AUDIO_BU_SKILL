"""Slice 1 — unit tests for the read-only kernel codec-driver probe.

Pure, stdlib-only tests over ``orchestrator.generation.codec_driver_probe``.
Mirrors the ``test_generation_source_probe`` discipline: on-disk fixture trees
(no network, no writes), no pytest fixtures, a ``main()`` runner. The probe is
disclosure-only and read-only; these tests pin its ternary observation
contract so downstream codec_stub grounding stays honest.

Fixture trees (``tests/fixtures/kernel_trees/``):

  * ``codec_found_tree`` — ``pcm1681.c`` carries ``ti,pcm1681`` in its
    of_match_table; ``adau1977-spi.c`` carries ``adi,adau1979`` (the adau1979
    identity has NO ``adau1979.c`` upstream — it resolves via the bounded
    family candidate list). Both codecs → FOUND.
  * ``codec_absent_tree`` — both driver files are readable but neither lists a
    matching ``.compatible`` for its codec key → ABSENT.
  * absent tree (``from_tree(None)`` / nonexistent path) → FILE_NOT_FOUND.

Key provenance assertion (Slice 1 hard rule): the attested compatible VALUE is
observed in the KERNEL CODEC DRIVER's of_match_table — an authority
INDEPENDENT of the candidate DTS commit ``5267b2e1``. These tests verify the
probe reads the driver ``.c`` file, never a DTS.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_codec_driver_probe``
"""

from __future__ import annotations

from pathlib import Path

from orchestrator.generation.codec_driver_probe import CodecDriverProbe, ClaimStatus

_AUDIO_BU_ROOT = Path(__file__).resolve().parent.parent
_KERNEL_TREES = _AUDIO_BU_ROOT / "tests" / "fixtures" / "kernel_trees"
_FOUND_TREE = str(_KERNEL_TREES / "codec_found_tree")
_ABSENT_TREE = str(_KERNEL_TREES / "codec_absent_tree")

#: The codec identities Nord's onboarding projects (candidate-derived join
#: keys). REUSED here verbatim — the probe does not recollect identity.
_NORD_CODEC_KEYS = ("adau1979", "pcm1681")


# ── 1. FOUND: compatibles observed in the kernel driver of_match_table ──────


def test_found_tree_compatibles_from_of_match_table() -> None:
    """Both Nord codecs resolve FOUND from the driver of_match_table, not a DTS.

    pcm1681 → ``ti,pcm1681`` from ``pcm1681.c`` (direct filename hit).
    adau1979 → ``adi,adau1979`` from ``adau1977-spi.c`` (family-candidate hit;
    no ``adau1979.c`` exists). The attested value is the of_match_table literal
    and its provenance is the codec DRIVER file — independent of commit
    ``5267b2e1``.
    """
    probe = CodecDriverProbe.from_tree(_FOUND_TREE, _NORD_CODEC_KEYS)

    status_p, compat_p, file_p, line_p = probe.compatible_for("pcm1681")
    assert status_p is ClaimStatus.FOUND, f"pcm1681 status drift: {status_p!r}"
    assert compat_p == "ti,pcm1681", f"pcm1681 compatible drift: {compat_p!r}"
    assert file_p == "sound/soc/codecs/pcm1681.c", f"pcm1681 file drift: {file_p!r}"
    assert line_p is not None and line_p > 0, f"pcm1681 line drift: {line_p!r}"
    # Provenance is a DRIVER .c file, never a .dts / candidate DTS.
    assert file_p.endswith(".c") and "/codecs/" in file_p, (
        f"pcm1681 attested from a non-driver source: {file_p!r}"
    )

    status_a, compat_a, file_a, line_a = probe.compatible_for("adau1979")
    assert status_a is ClaimStatus.FOUND, f"adau1979 status drift: {status_a!r}"
    assert compat_a == "adi,adau1979", f"adau1979 compatible drift: {compat_a!r}"
    assert file_a == "sound/soc/codecs/adau1977-spi.c", (
        f"adau1979 must resolve via the family candidate adau1977-spi.c, "
        f"got {file_a!r}"
    )
    assert line_a is not None and line_a > 0, f"adau1979 line drift: {line_a!r}"

    print(
        "PASS: FOUND — pcm1681→ti,pcm1681 (pcm1681.c), "
        "adau1979→adi,adau1979 (adau1977-spi.c family-candidate)"
    )


def test_found_value_not_sourced_from_candidate_dts() -> None:
    """The FOUND provenance file is a codec driver, never the candidate DTS.

    Slice 1 hard rule: the attested compatible VALUE comes from the kernel
    codec driver of_match_table, NEVER from the unapplied candidate DTS commit
    ``5267b2e1``. Asserts the driver_file for every FOUND observation is under
    ``sound/soc/codecs/`` and is a ``.c`` file (not a ``.dts`` / ``.dtsi``).
    """
    probe = CodecDriverProbe.from_tree(_FOUND_TREE, _NORD_CODEC_KEYS)
    for key in _NORD_CODEC_KEYS:
        status, _compat, driver_file, _line = probe.compatible_for(key)
        assert status is ClaimStatus.FOUND, f"{key} expected FOUND, got {status!r}"
        assert driver_file is not None
        assert driver_file.startswith("sound/soc/codecs/"), (
            f"{key} attested outside the codec driver dir: {driver_file!r}"
        )
        assert driver_file.endswith(".c"), (
            f"{key} attested from a non-driver file (must be a .c driver, "
            f"never a candidate DTS): {driver_file!r}"
        )
        assert not driver_file.endswith((".dts", ".dtsi")), (
            f"{key} attested from a DTS — provenance guard violated: {driver_file!r}"
        )
    print("PASS: FOUND provenance is a codec .c driver, never a candidate DTS")


# ── 2. ABSENT: driver readable but no matching compatible → fallback signal ──


def test_absent_tree_is_absent_not_fabricated() -> None:
    """Readable driver files with no matching compatible → ABSENT (honest gap).

    A half-written driver whose of_match_table lacks the codec's compatible
    must NOT fabricate a FOUND. The probe reports ABSENT so codec_stub falls
    back to the hardcoded value marked NOT kernel-attested.
    """
    probe = CodecDriverProbe.from_tree(_ABSENT_TREE, _NORD_CODEC_KEYS)
    for key in _NORD_CODEC_KEYS:
        status, compat, driver_file, line = probe.compatible_for(key)
        assert status is ClaimStatus.ABSENT, (
            f"{key} expected ABSENT (file readable, no match), got {status!r}"
        )
        assert compat is None, f"{key} ABSENT must carry no compatible: {compat!r}"
        assert driver_file is None, f"{key} ABSENT must carry no file: {driver_file!r}"
        assert line is None, f"{key} ABSENT must carry no line: {line!r}"
    print("PASS: ABSENT — readable driver, no matching compatible, nothing fabricated")


# ── 3. FILE_NOT_FOUND: no tree / nonexistent path → honest degradation ───────


def test_none_tree_is_file_not_found() -> None:
    """``from_tree(None)`` yields FILE_NOT_FOUND for every key, no raise."""
    probe = CodecDriverProbe.from_tree(None, _NORD_CODEC_KEYS)
    for key in _NORD_CODEC_KEYS:
        status, compat, driver_file, line = probe.compatible_for(key)
        assert status is ClaimStatus.FILE_NOT_FOUND, (
            f"{key} with no tree expected FILE_NOT_FOUND, got {status!r}"
        )
        assert (compat, driver_file, line) == (None, None, None)
    print("PASS: from_tree(None) → FILE_NOT_FOUND, no exception")


def test_nonexistent_path_is_file_not_found() -> None:
    """A path that does not exist / is not a directory → FILE_NOT_FOUND, no raise."""
    bogus = str(_KERNEL_TREES / "does_not_exist_9d3f")
    probe = CodecDriverProbe.from_tree(bogus, _NORD_CODEC_KEYS)
    for key in _NORD_CODEC_KEYS:
        status, *_rest = probe.compatible_for(key)
        assert status is ClaimStatus.FILE_NOT_FOUND, (
            f"{key} on nonexistent tree expected FILE_NOT_FOUND, got {status!r}"
        )
    print("PASS: nonexistent tree path → FILE_NOT_FOUND, no exception")


def test_unprobed_key_is_file_not_found() -> None:
    """Querying a key the probe never resolved → FILE_NOT_FOUND (defensive)."""
    probe = CodecDriverProbe.from_tree(_FOUND_TREE, ("pcm1681",))
    status, compat, driver_file, line = probe.compatible_for("never_asked")
    assert status is ClaimStatus.FILE_NOT_FOUND
    assert (compat, driver_file, line) == (None, None, None)
    print("PASS: unprobed key → FILE_NOT_FOUND")


# ── 4. Determinism + read-only ───────────────────────────────────────────────


def test_probe_is_deterministic_and_key_order_independent() -> None:
    """Same tree + same key set (any input order) → identical observations."""
    a = CodecDriverProbe.from_tree(_FOUND_TREE, ("adau1979", "pcm1681"))
    b = CodecDriverProbe.from_tree(_FOUND_TREE, ("pcm1681", "adau1979"))
    assert a.observations == b.observations, (
        "probe observations are not order-independent / deterministic:\n"
        f"  a={a.observations!r}\n  b={b.observations!r}"
    )
    print("PASS: probe deterministic and key-order-independent")


def test_probe_does_not_mutate_tree() -> None:
    """Building the probe leaves the fixture tree byte-identical (read-only)."""
    root = Path(_FOUND_TREE)
    before = {
        p: p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    }
    CodecDriverProbe.from_tree(_FOUND_TREE, _NORD_CODEC_KEYS)
    after = {
        p: p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    }
    assert before == after, "CodecDriverProbe mutated the kernel fixture tree"
    print(f"PASS: probe is read-only ({len(before)} fixture files unchanged)")


def main() -> None:
    test_found_tree_compatibles_from_of_match_table()          # 1
    test_found_value_not_sourced_from_candidate_dts()          # 1b
    test_absent_tree_is_absent_not_fabricated()                # 2
    test_none_tree_is_file_not_found()                         # 3
    test_nonexistent_path_is_file_not_found()                  # 3b
    test_unprobed_key_is_file_not_found()                      # 3c
    test_probe_is_deterministic_and_key_order_independent()    # 4
    test_probe_does_not_mutate_tree()                          # 4b
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
