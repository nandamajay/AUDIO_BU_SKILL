"""WP G-3A.8 Option 2: T-CODEC-RES test suite.

Guards ``orchestrator.source_ingest.codec_resolver.resolve_codec_verdicts``:
the drop-in replacement for the filename-guess stub previously at
``target_onboarding_runner.py:829-844``.

Every test builds its own synthetic minimal kernel tree under ``tmp_path``
so nothing depends on ``./linux-nord/``. No Nord token appears in any
resolver body — only in inputs, so T-CODEC-RES-GENERALITY can prove the
resolver stays fully data-driven.

Test IDs (from prior-turn plan, extended):

  * T-CODEC-RES-1  — compatible extraction from labelled + clean strings
  * T-CODEC-RES-2  — direct compatible-in-.c hit (ti,pcm1681 → pcm1681.c)
  * T-CODEC-RES-3  — shared-family (adi,adau1979 → adau1977.c via enum) — non-negotiable
  * T-CODEC-RES-4  — needs_write on absent codec with searched_paths preserved
  * T-CODEC-RES-5  — bindings-only hit: driver missing, binding_paths populated
  * T-CODEC-RES-DETERMINISM — byte-identical output across runs and inputs
  * T-CODEC-RES-GENERALITY  — non-Nord synthetic compatible → no Nord tokens leak
  * T-CODEC-RES-I2C-NAMETABLE — i2c_device_id.name fallback (i2c-shim path)
  * T-CODEC-RES-EMPTY-INPUT — empty input yields empty dict, no crash
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.source_ingest import resolve_codec_verdicts
from orchestrator.source_ingest.codec_resolver import _extract_compatible


# ---------------------------------------------------------------------------
# Test fixtures: minimal synthetic kernel trees.
# ---------------------------------------------------------------------------


def _make_kernel(tmp_path: Path) -> Path:
    """Create the empty top-level kernel subtree layout expected by the
    resolver (sound/soc/codecs, Documentation/devicetree/bindings/sound,
    include/dt-bindings/sound). Tests populate specific files on top.
    """
    kernel = tmp_path / "kernel"
    (kernel / "sound" / "soc" / "codecs").mkdir(parents=True)
    (kernel / "Documentation" / "devicetree" / "bindings" / "sound").mkdir(parents=True)
    (kernel / "include" / "dt-bindings" / "sound").mkdir(parents=True)
    return kernel


def _write_codec_c(kernel: Path, filename: str, contents: str) -> Path:
    """Drop a synthetic codec driver file at ``sound/soc/codecs/<filename>``.
    Returns the absolute path for optional assertion use.
    """
    path = kernel / "sound" / "soc" / "codecs" / filename
    path.write_text(contents, encoding="utf-8")
    return path


def _write_codec_h(kernel: Path, filename: str, contents: str) -> Path:
    path = kernel / "sound" / "soc" / "codecs" / filename
    path.write_text(contents, encoding="utf-8")
    return path


def _write_binding_yaml(kernel: Path, filename: str, contents: str) -> Path:
    path = kernel / "Documentation" / "devicetree" / "bindings" / "sound" / filename
    path.write_text(contents, encoding="utf-8")
    return path


def _write_header(kernel: Path, filename: str, contents: str) -> Path:
    path = kernel / "include" / "dt-bindings" / "sound" / filename
    path.write_text(contents, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# T-CODEC-RES-1: compatible extraction
# ---------------------------------------------------------------------------


class TestCompatibleExtraction:
    """T-CODEC-RES-1: ``_extract_compatible`` handles clean + labelled forms."""

    def test_clean_compatible(self) -> None:
        assert _extract_compatible("ti,pcm1681") == ("ti", "pcm1681")

    def test_labelled_form_with_paren(self) -> None:
        label = "adi,adau1979 (ADI ADAU1979 4-ch ADC, I2C @0x31 on i2c18)"
        assert _extract_compatible(label) == ("adi", "adau1979")

    def test_uppercase_input_normalised(self) -> None:
        assert _extract_compatible("TI,PCM1681") == ("ti", "pcm1681")

    def test_leading_whitespace_tolerated(self) -> None:
        assert _extract_compatible("   ti,pcm1681   ") == ("ti", "pcm1681")

    def test_empty_returns_none(self) -> None:
        assert _extract_compatible("") is None
        assert _extract_compatible("   ") is None

    def test_no_comma_returns_none(self) -> None:
        assert _extract_compatible("just-a-word") is None

    def test_non_string_returns_none(self) -> None:
        assert _extract_compatible(None) is None  # type: ignore[arg-type]
        assert _extract_compatible(42) is None  # type: ignore[arg-type]

    def test_underscore_and_dash_tolerated_in_part(self) -> None:
        assert _extract_compatible("vendor,part_with-mixed") == ("vendor", "part_with-mixed")


# ---------------------------------------------------------------------------
# T-CODEC-RES-2: direct compatible-in-.c hit
# ---------------------------------------------------------------------------


class TestDirectCompatibleHit:
    """T-CODEC-RES-2: ti,pcm1681 → pcm1681.c via compatible-in-.c grep."""

    def test_pcm1681_resolves_to_pcm1681_c(self, tmp_path: Path) -> None:
        kernel = _make_kernel(tmp_path)
        _write_codec_c(
            kernel,
            "pcm1681.c",
            'static const struct of_device_id pcm1681_dt_ids[] = {\n'
            '\t{ .compatible = "ti,pcm1681", },\n'
            '\t{ }\n};\n',
        )

        result = resolve_codec_verdicts(["ti,pcm1681"], kernel)

        assert "ti,pcm1681" in result
        verdict = result["ti,pcm1681"]
        assert verdict["driver_path"] == "sound/soc/codecs/pcm1681.c"
        assert verdict["status"] == "upstream_present"
        assert verdict["matched_via"] == "compatible_string"
        assert verdict["compatible"] == "ti,pcm1681"
        assert "sound/soc/codecs" in verdict["searched_paths"]

    def test_labelled_ti_pcm1681_still_resolves(self, tmp_path: Path) -> None:
        """Nord's real label form (label bloat) must still resolve."""
        kernel = _make_kernel(tmp_path)
        _write_codec_c(
            kernel,
            "pcm1681.c",
            'static const struct of_device_id pcm1681_dt_ids[] = {\n'
            '\t{ .compatible = "ti,pcm1681", },\n};\n',
        )

        label = "ti,pcm1681 (TI PCM1681 8-ch DAC, I2C @0x4c on i2c18)"
        result = resolve_codec_verdicts([label], kernel)

        assert result[label]["driver_path"] == "sound/soc/codecs/pcm1681.c"
        assert result[label]["status"] == "upstream_present"


# ---------------------------------------------------------------------------
# T-CODEC-RES-3: shared-family (ADAU1979 correctness guard — non-negotiable)
# ---------------------------------------------------------------------------


class TestSharedFamilyDriver:
    """T-CODEC-RES-3: adi,adau1979 → adau1977.c via shared-family collapse.

    Real Nord kernel layout at pinned HEAD 66b80186:
      sound/soc/codecs/adau1977.c         — shared driver (no compatible)
      sound/soc/codecs/adau1977-spi.c     — SPI shim, has all three .compatible
      sound/soc/codecs/adau1977-i2c.c     — I2C shim, uses i2c_device_id name-table only
      sound/soc/codecs/adau1977.h         — has enum adau1977_type { ..., ADAU1979 }
      Documentation/devicetree/bindings/sound/adi,adau1977.yaml — lists adi,adau1979
    """

    def test_adau1979_via_spi_compatible_collapses_to_family(self, tmp_path: Path) -> None:
        """Match path: adau1977-spi.c has ``.compatible = "adi,adau1979"``.
        Resolver must collapse to the enclosing family driver adau1977.c."""
        kernel = _make_kernel(tmp_path)
        # Shared family driver — the real ASoC driver.
        _write_codec_c(kernel, "adau1977.c", "/* shared code */\n")
        # SPI shim carries the compatible strings.
        _write_codec_c(
            kernel,
            "adau1977-spi.c",
            'static const struct of_device_id adau1977_spi_of_id[] = {\n'
            '\t{ .compatible = "adi,adau1977" },\n'
            '\t{ .compatible = "adi,adau1978" },\n'
            '\t{ .compatible = "adi,adau1979" },\n'
            '\t{ }\n};\n',
        )
        # I2C shim uses i2c_device_id name-table only.
        _write_codec_c(
            kernel,
            "adau1977-i2c.c",
            'static const struct i2c_device_id adau1977_i2c_ids[] = {\n'
            '\t{ .name = "adau1977", .driver_data = ADAU1977 },\n'
            '\t{ .name = "adau1978", .driver_data = ADAU1978 },\n'
            '\t{ .name = "adau1979", .driver_data = ADAU1979 },\n'
            '\t{ }\n};\n',
        )

        result = resolve_codec_verdicts(["adi,adau1979"], kernel)

        verdict = result["adi,adau1979"]
        # The family driver adau1977.c is the correct answer, NOT the shim.
        assert verdict["driver_path"] == "sound/soc/codecs/adau1977.c", (
            f"expected shared family adau1977.c, got {verdict['driver_path']}"
        )
        assert verdict["status"] == "upstream_present"
        assert verdict["matched_via"] == "compatible_string"

    def test_adau1979_via_enum_fallback_when_compatibles_absent(self, tmp_path: Path) -> None:
        """Non-negotiable guard: even if SPI shim didn't have compatible strings,
        the enum-family fallback must still resolve adau1979 → adau1977.c.

        Simulates a hypothetical tree where only the shared code + header
        + i2c name-table exist. The enum ``ADAU1979`` in ``adau1977.h``
        must resolve the family driver."""
        kernel = _make_kernel(tmp_path)
        _write_codec_h(
            kernel,
            "adau1977.h",
            'enum adau1977_type {\n\tADAU1977,\n\tADAU1978,\n\tADAU1979,\n};\n',
        )
        _write_codec_c(
            kernel,
            "adau1977.c",
            '#include "adau1977.h"\n/* shared implementation uses enum adau1977_type */\n'
            'static void probe(enum adau1977_type type) {\n'
            '\tif (type == ADAU1979) { /* ... */ }\n}\n',
        )

        result = resolve_codec_verdicts(["adi,adau1979"], kernel)

        verdict = result["adi,adau1979"]
        assert verdict["driver_path"] == "sound/soc/codecs/adau1977.c", (
            f"adau1979 enum-fallback failed: got {verdict['driver_path']}"
        )
        assert verdict["status"] == "upstream_present"
        assert verdict["matched_via"] == "enum_family"

    def test_labelled_adau1979_nord_form_resolves(self, tmp_path: Path) -> None:
        """The full Nord label form must still resolve to the family driver."""
        kernel = _make_kernel(tmp_path)
        _write_codec_c(kernel, "adau1977.c", "/* shared */\n")
        _write_codec_c(
            kernel,
            "adau1977-spi.c",
            'static const struct of_device_id ids[] = {\n'
            '\t{ .compatible = "adi,adau1979" },\n};\n',
        )

        label = "adi,adau1979 (ADI ADAU1979 4-ch ADC, I2C @0x31 on i2c18, MCLK=AUD_MCLK1/GPIO100)"
        result = resolve_codec_verdicts([label], kernel)

        assert result[label]["driver_path"] == "sound/soc/codecs/adau1977.c"
        assert result[label]["status"] == "upstream_present"


# ---------------------------------------------------------------------------
# T-CODEC-RES-4: needs_write with searched_paths trail
# ---------------------------------------------------------------------------


class TestNeedsWriteVerdict:
    """T-CODEC-RES-4: missing driver → needs_write with searched_paths."""

    def test_absent_codec_yields_needs_write(self, tmp_path: Path) -> None:
        kernel = _make_kernel(tmp_path)
        # No driver, no binding, no header anywhere.

        result = resolve_codec_verdicts(["vendor,made-up-part"], kernel)

        verdict = result["vendor,made-up-part"]
        assert verdict["driver_path"] is None
        assert verdict["status"] == "needs_write"
        assert verdict["matched_via"] == "unmatched"
        assert verdict["binding_paths"] == []
        assert verdict["header_paths"] == []
        # searched_paths is the audit trail — must be populated.
        assert "sound/soc/codecs" in verdict["searched_paths"]
        assert "Documentation/devicetree/bindings/sound" in verdict["searched_paths"]
        assert "include/dt-bindings/sound" in verdict["searched_paths"]


# ---------------------------------------------------------------------------
# T-CODEC-RES-5: binding-only (driver missing, binding exists)
# ---------------------------------------------------------------------------


class TestBindingOnlyVerdict:
    """T-CODEC-RES-5: driver missing but binding present → needs_write
    with binding_paths populated so a human can triage without a re-run."""

    def test_binding_only_yields_needs_write_with_binding_paths(self, tmp_path: Path) -> None:
        kernel = _make_kernel(tmp_path)
        _write_binding_yaml(
            kernel,
            "vendor,orphan-codec.yaml",
            'compatible:\n  const: vendor,orphan-codec\n',
        )

        result = resolve_codec_verdicts(["vendor,orphan-codec"], kernel)

        verdict = result["vendor,orphan-codec"]
        assert verdict["driver_path"] is None
        assert verdict["status"] == "needs_write"
        # Rich-evidence preservation: binding_paths carries the positive
        # evidence that a re-run wouldn't restore.
        assert verdict["binding_paths"] == [
            "Documentation/devicetree/bindings/sound/vendor,orphan-codec.yaml"
        ]
        assert verdict["matched_via"] == "binding_only"

    def test_header_only_also_yields_binding_only(self, tmp_path: Path) -> None:
        """A header-only hit (dt-bindings/sound/*.h) is symmetric."""
        kernel = _make_kernel(tmp_path)
        _write_header(kernel, "vendor,orphan.h", "// #define VENDOR_ORPHAN vendor,orphan-part\n")

        result = resolve_codec_verdicts(["vendor,orphan-part"], kernel)

        verdict = result["vendor,orphan-part"]
        assert verdict["driver_path"] is None
        assert verdict["status"] == "needs_write"
        assert verdict["header_paths"] == ["include/dt-bindings/sound/vendor,orphan.h"]
        assert verdict["matched_via"] == "binding_only"


# ---------------------------------------------------------------------------
# T-CODEC-RES-DETERMINISM: byte-identical across runs
# ---------------------------------------------------------------------------


class TestDeterminism:
    """T-CODEC-RES-DETERMINISM: same input → byte-identical output."""

    def test_repeated_calls_produce_identical_json(self, tmp_path: Path) -> None:
        kernel = _make_kernel(tmp_path)
        _write_codec_c(
            kernel,
            "pcm1681.c",
            'static const struct of_device_id ids[] = {\n'
            '\t{ .compatible = "ti,pcm1681" },\n};\n',
        )
        _write_codec_c(kernel, "adau1977.c", "/* shared */\n")
        _write_codec_c(
            kernel,
            "adau1977-spi.c",
            '{ .compatible = "adi,adau1979" }\n',
        )
        _write_binding_yaml(
            kernel,
            "adi,adau1977.yaml",
            'compatible:\n  - adi,adau1979\n',
        )

        r1 = resolve_codec_verdicts(["ti,pcm1681", "adi,adau1979"], kernel)
        r2 = resolve_codec_verdicts(["adi,adau1979", "ti,pcm1681"], kernel)
        r3 = resolve_codec_verdicts(["ti,pcm1681", "adi,adau1979"], kernel)

        j1 = json.dumps(r1, sort_keys=True)
        j2 = json.dumps(r2, sort_keys=True)
        j3 = json.dumps(r3, sort_keys=True)
        assert j1 == j2 == j3

    def test_input_order_is_normalised(self, tmp_path: Path) -> None:
        """Different input orderings yield the same dict."""
        kernel = _make_kernel(tmp_path)
        _write_codec_c(kernel, "a.c", '{ .compatible = "x,a" }\n')
        _write_codec_c(kernel, "b.c", '{ .compatible = "x,b" }\n')

        r1 = resolve_codec_verdicts(["x,a", "x,b"], kernel)
        r2 = resolve_codec_verdicts(["x,b", "x,a"], kernel)
        assert list(r1.keys()) == list(r2.keys()) == ["x,a", "x,b"]


# ---------------------------------------------------------------------------
# T-CODEC-RES-GENERALITY: no Nord tokens in resolver body
# ---------------------------------------------------------------------------


class TestGenerality:
    """T-CODEC-RES-GENERALITY: synthetic non-Nord codec → no Nord leak.

    Guards against hard-coding: a synthetic ``xyz,fake-4321`` with a
    synthetic driver produces facts carrying only the input's tokens.
    """

    def test_synthetic_non_nord_codec_resolves_cleanly(self, tmp_path: Path) -> None:
        kernel = _make_kernel(tmp_path)
        _write_codec_c(
            kernel,
            "fake-4321.c",
            'static const struct of_device_id fake_ids[] = {\n'
            '\t{ .compatible = "xyz,fake-4321" },\n};\n',
        )

        result = resolve_codec_verdicts(["xyz,fake-4321"], kernel)

        verdict = result["xyz,fake-4321"]
        assert verdict["driver_path"] == "sound/soc/codecs/fake-4321.c"
        assert verdict["compatible"] == "xyz,fake-4321"

        # No Nord tokens must leak into the returned dict for a
        # non-Nord input.
        serialised = json.dumps(result).lower()
        for nord_token in ("adau", "pcm1681", "nord", "iq10", "1979"):
            assert nord_token not in serialised, (
                f"Nord token '{nord_token}' leaked into synthetic codec result"
            )

    def test_resolver_source_has_no_target_specific_names(self) -> None:
        """Static guard: resolver source must not mention Nord target names."""
        import orchestrator.source_ingest.codec_resolver as mod

        src = Path(mod.__file__).read_text(encoding="utf-8")
        # ``adau1977`` / ``pcm1681`` are OK — they're docstring examples of
        # kernel driver files, not Nord-target specific. But the target
        # names themselves must not appear.
        for target_token in ("nord-iq10", "eliza"):
            assert target_token not in src.lower(), (
                f"Target-specific token '{target_token}' found in resolver source"
            )


# ---------------------------------------------------------------------------
# T-CODEC-RES-I2C-NAMETABLE: fallback for i2c-shim shared drivers
# ---------------------------------------------------------------------------


class TestI2CNameTableFallback:
    """T-CODEC-RES-I2C-NAMETABLE: some codecs register only via
    ``i2c_device_id.name`` name-tables, not ``.compatible``. Resolver
    must fall back to this path when compatible-grep misses."""

    def test_i2c_name_table_hit(self, tmp_path: Path) -> None:
        """Simulate a shared driver where only the -i2c shim exists
        (with a name-table entry, no compatible), and no SPI shim."""
        kernel = _make_kernel(tmp_path)
        # Family driver exists.
        _write_codec_c(kernel, "somechip.c", "/* shared code */\n")
        # -i2c shim carries only a name-table.
        _write_codec_c(
            kernel,
            "somechip-i2c.c",
            'static const struct i2c_device_id somechip_i2c_ids[] = {\n'
            '\t{ .name = "somepart", .driver_data = 0 },\n};\n',
        )

        result = resolve_codec_verdicts(["vendor,somepart"], kernel)

        verdict = result["vendor,somepart"]
        # Family driver preferred over the -i2c shim.
        assert verdict["driver_path"] == "sound/soc/codecs/somechip.c"
        assert verdict["status"] == "upstream_present"
        assert verdict["matched_via"] == "i2c_device_id_name"


# ---------------------------------------------------------------------------
# T-CODEC-RES-EMPTY-INPUT: empty input yields empty dict, no crash
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Miscellaneous edge cases: empty input, malformed labels."""

    def test_empty_input_yields_empty_dict(self, tmp_path: Path) -> None:
        kernel = _make_kernel(tmp_path)
        assert resolve_codec_verdicts([], kernel) == {}

    def test_malformed_label_yields_needs_write(self, tmp_path: Path) -> None:
        """A label with no ``vendor,part`` prefix → needs_write, matched_via
        ``unmatched``, ``reason=no_compatible_in_label``."""
        kernel = _make_kernel(tmp_path)
        result = resolve_codec_verdicts(["just-a-string"], kernel)
        v = result["just-a-string"]
        assert v["driver_path"] is None
        assert v["status"] == "needs_write"
        assert v["matched_via"] == "unmatched"
        assert v.get("reason") == "no_compatible_in_label"

    def test_missing_kernel_subtrees_do_not_crash(self, tmp_path: Path) -> None:
        """A ``kernel_source`` pointing at an empty directory yields
        needs_write for every codec, never crashes."""
        empty_root = tmp_path / "no_kernel"
        empty_root.mkdir()

        result = resolve_codec_verdicts(["ti,pcm1681"], empty_root)
        assert result["ti,pcm1681"]["driver_path"] is None
        assert result["ti,pcm1681"]["status"] == "needs_write"

    def test_kernel_source_pathlib_input(self, tmp_path: Path) -> None:
        """Signature accepts ``pathlib.Path`` — sanity check."""
        kernel = _make_kernel(tmp_path)
        _write_codec_c(
            kernel,
            "quick.c",
            '{ .compatible = "vendor,quick" }\n',
        )
        assert isinstance(kernel, Path)
        result = resolve_codec_verdicts(["vendor,quick"], kernel)
        assert result["vendor,quick"]["driver_path"] == "sound/soc/codecs/quick.c"


# ---------------------------------------------------------------------------
# T-CODEC-RES-EVIDENCE: rich-evidence fields preserved on every verdict
# ---------------------------------------------------------------------------


class TestRichEvidencePreserved:
    """User approval condition (b): every verdict — hit OR miss —
    preserves ``driver_path`` / ``binding_paths`` / ``header_paths`` /
    ``searched_paths``. Binding-only case must be human-triageable
    without a re-run."""

    def test_hit_verdict_has_all_fields(self, tmp_path: Path) -> None:
        kernel = _make_kernel(tmp_path)
        _write_codec_c(kernel, "pcm1681.c", '{ .compatible = "ti,pcm1681" }\n')
        _write_binding_yaml(kernel, "ti,pcm1681.yaml", 'compatible: ti,pcm1681\n')

        result = resolve_codec_verdicts(["ti,pcm1681"], kernel)
        v = result["ti,pcm1681"]
        for key in ("driver_path", "status", "matched_via", "compatible",
                    "binding_paths", "header_paths", "searched_paths"):
            assert key in v, f"missing field {key} in hit verdict"
        assert v["binding_paths"] == [
            "Documentation/devicetree/bindings/sound/ti,pcm1681.yaml"
        ]

    def test_miss_verdict_has_all_fields(self, tmp_path: Path) -> None:
        kernel = _make_kernel(tmp_path)
        result = resolve_codec_verdicts(["vendor,ghost"], kernel)
        v = result["vendor,ghost"]
        for key in ("driver_path", "status", "matched_via", "compatible",
                    "binding_paths", "header_paths", "searched_paths"):
            assert key in v, f"missing field {key} in miss verdict"
        assert v["binding_paths"] == []
        assert v["header_paths"] == []
