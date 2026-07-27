"""Phase B — SoC-aware driver source resolution tests.

Tests the resolver (soc_descriptor.py) and the descriptor-aware SourceProbe
integration. Validates:
  1. Successful discovery (DISCOVERED) from a fixture tree
  2. Unresolved case (zero matches → RESOLUTION_FAILED)
  3. Ambiguous case (multiple matches → RESOLUTION_FAILED)
  4. Missing tree / missing hint → RESOLUTION_FAILED
  5. Descriptor threads through to SourceProbe (dynamic path)
  6. Static fallback when descriptor is RESOLUTION_FAILED
  7. Byte-identity preserved regardless of resolution method
  8. Disclosure emission: resolution notes flow into gc["generation"]
  9. No gate modifications (is_open untouched)
  10. Runner threads soc_family_hint correctly
  11. Future-layout compatibility (new driver file in new tree)
  12. WP-64 disclosure-only intact with resolved probe

All fixtures are synthetic (tests/fixtures/kernel_trees/*_tree/).
Results are NOT real-target; labeled accordingly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ── path setup ───────────────────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_FIXTURES = _REPO / "tests" / "fixtures" / "kernel_trees"
_RESOLVED_TREE = str(_FIXTURES / "resolved_tree")
_MULTI_MATCH_TREE = str(_FIXTURES / "multi_match_tree")
_NO_FAMILY_TREE = str(_FIXTURES / "no_family_tree")
_FOUND_TREE = str(_FIXTURES / "found_tree")
_ABSENT_TREE = str(_FIXTURES / "absent_tree")

from orchestrator.generation.soc_descriptor import (
    ResolutionMethod,
    SocDriverDescriptor,
    resolve_driver_source,
)
from orchestrator.generation.source_probe import ClaimStatus, SourceProbe


class TestResolveDriverSource:
    """Test resolve_driver_source() discovery logic."""

    def test_discovered_single_match(self):
        """soc_family_hint='sa8775p' in resolved_tree → DISCOVERED."""
        desc = resolve_driver_source(_RESOLVED_TREE, "sa8775p")
        assert desc.method == ResolutionMethod.DISCOVERED
        assert desc.driver_file == "sound/soc/qcom/sc8280xp.c"
        assert desc.match_table_symbol == "snd_sc8280xp_dt_match"
        assert desc.soc_family_hint == "sa8775p"
        assert any("DISCOVERED" in n for n in desc.resolution_notes)

    def test_resolution_failed_no_match(self):
        """soc_family_hint='sa8775p' in no_family_tree → RESOLUTION_FAILED."""
        desc = resolve_driver_source(_NO_FAMILY_TREE, "sa8775p")
        assert desc.method == ResolutionMethod.RESOLUTION_FAILED
        assert desc.driver_file is None
        assert any("not found" in n for n in desc.resolution_notes)

    def test_resolution_failed_ambiguous(self):
        """soc_family_hint='sa8775p' in multi_match_tree → RESOLUTION_FAILED (multiple)."""
        desc = resolve_driver_source(_MULTI_MATCH_TREE, "sa8775p")
        assert desc.method == ResolutionMethod.RESOLUTION_FAILED
        assert desc.driver_file is None
        assert any("multiple" in n for n in desc.resolution_notes)

    def test_resolution_failed_no_tree(self):
        """tree=None → RESOLUTION_FAILED."""
        desc = resolve_driver_source(None, "sa8775p")
        assert desc.method == ResolutionMethod.RESOLUTION_FAILED
        assert any("no kernel source" in n for n in desc.resolution_notes)

    def test_resolution_failed_no_hint(self):
        """soc_family_hint=None → RESOLUTION_FAILED."""
        desc = resolve_driver_source(_RESOLVED_TREE, None)
        assert desc.method == ResolutionMethod.RESOLUTION_FAILED
        assert any("no soc_family_hint" in n for n in desc.resolution_notes)

    def test_resolution_failed_missing_dir(self):
        """tree exists but has no sound/soc/qcom/ → RESOLUTION_FAILED."""
        desc = resolve_driver_source(str(_FIXTURES), "sa8775p")
        assert desc.method == ResolutionMethod.RESOLUTION_FAILED
        assert any("not found in tree" in n for n in desc.resolution_notes)

    def test_to_dict_roundtrip(self):
        """SocDriverDescriptor.to_dict() has all expected keys."""
        desc = resolve_driver_source(_RESOLVED_TREE, "sa8775p")
        d = desc.to_dict()
        assert d["method"] == "DISCOVERED"
        assert d["driver_file"] == "sound/soc/qcom/sc8280xp.c"
        assert d["match_table_symbol"] == "snd_sc8280xp_dt_match"
        assert d["soc_family_hint"] == "sa8775p"
        assert isinstance(d["resolution_notes"], list)


class TestDescriptorToProbe:
    """Test that SocDriverDescriptor correctly threads into SourceProbe."""

    def test_discovered_descriptor_sets_probe_paths(self):
        """When descriptor=DISCOVERED, probe uses resolved file."""
        desc = resolve_driver_source(_RESOLVED_TREE, "sa8775p")
        probe = SourceProbe.from_tree(_RESOLVED_TREE, descriptor=desc)
        assert probe.driver_match_file == "sound/soc/qcom/sc8280xp.c"
        assert probe.match_table_symbol == "snd_sc8280xp_dt_match"
        assert probe.driver_status == ClaimStatus.FOUND
        assert "qcom,qcs9100-sndcard" in probe.match_table_compatibles

    def test_failed_descriptor_uses_static_fallback(self):
        """When descriptor=RESOLUTION_FAILED, probe falls back to default paths."""
        desc = resolve_driver_source(None, None)
        probe = SourceProbe.from_tree(_FOUND_TREE, descriptor=desc)
        # Uses static defaults → reads found_tree's sc8280xp.c
        assert probe.driver_match_file == "sound/soc/qcom/sc8280xp.c"
        assert probe.match_table_symbol == "snd_sc8280xp_dt_match"
        assert probe.driver_status == ClaimStatus.FOUND

    def test_none_descriptor_uses_static_fallback(self):
        """When descriptor=None (legacy), probe uses static defaults."""
        probe = SourceProbe.from_tree(_FOUND_TREE, descriptor=None)
        assert probe.driver_match_file == "sound/soc/qcom/sc8280xp.c"
        assert probe.driver_status == ClaimStatus.FOUND


class TestByteIdentity:
    """Phase B must not change emitted DTSI bytes."""

    def test_byte_identity_across_resolution_methods(self):
        """Emitted artifact bytes are identical regardless of resolution method.

        This is the Phase B extension of Slice A test 1 (dtsi_bytes_invariant):
        the descriptor changes ONLY the probe's note text, never the bytes.
        NOT real-target — fixture-derived result.
        """
        from tests.test_generation_source_probe import (
            _clean_nord_facts,
        )
        from orchestrator.generation.machine_driver import generate_machine_driver
        from orchestrator.generation.model import GeneratedArtifact

        facts = _clean_nord_facts()

        # (a) No descriptor (legacy static)
        probe_none = SourceProbe.from_tree(None, descriptor=None)
        r_none = generate_machine_driver(facts, source=probe_none)

        # (b) DISCOVERED descriptor
        desc_found = resolve_driver_source(_RESOLVED_TREE, "sa8775p")
        probe_found = SourceProbe.from_tree(_RESOLVED_TREE, descriptor=desc_found)
        r_found = generate_machine_driver(facts, source=probe_found)

        # (c) RESOLUTION_FAILED descriptor (static fallback)
        desc_fail = resolve_driver_source(None, None)
        probe_fail = SourceProbe.from_tree(None, descriptor=desc_fail)
        r_fail = generate_machine_driver(facts, source=probe_fail)

        assert isinstance(r_none, GeneratedArtifact)
        assert isinstance(r_found, GeneratedArtifact)
        assert isinstance(r_fail, GeneratedArtifact)
        assert r_none.bytes_ == r_found.bytes_ == r_fail.bytes_


class TestDisclosureEmission:
    """Resolution notes flow into gc['generation']['source_resolution']."""

    def test_runner_emits_source_resolution(self):
        """_run_generation populates gc['generation']['source_resolution'].

        NOT real-target — fixture-derived result.
        """
        from tests.test_generation_source_probe import (
            _clean_nord_facts,
        )
        from orchestrator.generation.runner import _run_generation

        facts = _clean_nord_facts()
        gc = {"cross_verification": {"rows": [{"track": "T1", "subject": "test"}]}}
        _run_generation(
            gc, facts,
            kernel_source=_RESOLVED_TREE,
            soc_family_hint="sa8775p",
        )
        assert "source_resolution" in gc["generation"]
        sr = gc["generation"]["source_resolution"]
        assert sr["method"] == "DISCOVERED"
        assert sr["driver_file"] == "sound/soc/qcom/sc8280xp.c"

    def test_runner_emits_failed_resolution(self):
        """When resolution fails, gc includes RESOLUTION_FAILED descriptor.

        NOT real-target — fixture-derived result.
        """
        from tests.test_generation_source_probe import (
            _clean_nord_facts,
        )
        from orchestrator.generation.runner import _run_generation

        facts = _clean_nord_facts()
        gc = {"cross_verification": {"rows": [{"track": "T1", "subject": "test"}]}}
        _run_generation(
            gc, facts,
            kernel_source=_NO_FAMILY_TREE,
            soc_family_hint="sa8775p",
        )
        sr = gc["generation"]["source_resolution"]
        assert sr["method"] == "RESOLUTION_FAILED"
        assert any("not found" in n for n in sr["resolution_notes"])


class TestFutureLayoutCompatibility:
    """Resolver supports any new driver file layout."""

    def test_resolves_new_driver_file(self, tmp_path):
        """A hypothetical future_soc.c with MODULE_DEVICE_TABLE is discoverable.

        NOT real-target — synthetic fixture.
        """
        driver_dir = tmp_path / "sound" / "soc" / "qcom"
        driver_dir.mkdir(parents=True)
        (driver_dir / "future_soc.c").write_text(
            '// future\n'
            'static const struct of_device_id snd_future_dt_match[] = {\n'
            '    {.compatible = "qcom,future-sndcard", "future_family"},\n'
            '    {}\n'
            '};\n'
            'MODULE_DEVICE_TABLE(of, snd_future_dt_match);\n'
        )
        desc = resolve_driver_source(str(tmp_path), "future_family")
        assert desc.method == ResolutionMethod.DISCOVERED
        assert desc.driver_file == "sound/soc/qcom/future_soc.c"
        assert desc.match_table_symbol == "snd_future_dt_match"


class TestNoGateModification:
    """Phase B does not modify any gate logic."""

    def test_is_open_does_not_consult_descriptor(self):
        """is_open() is unchanged — descriptor is disclosure-only.

        NOT real-target — fixture-derived result.
        """
        from tests.test_generation_source_probe import (
            _clean_nord_facts,
            _missing_pinctrl_facts,
        )
        from orchestrator.generation.machine_driver import generate_machine_driver
        from orchestrator.generation.model import GeneratedArtifact, GeneratorSkipped

        # Open gate + DISCOVERED descriptor → artifact (gate doesn't care)
        facts = _clean_nord_facts()
        desc = resolve_driver_source(_RESOLVED_TREE, "sa8775p")
        probe = SourceProbe.from_tree(_RESOLVED_TREE, descriptor=desc)
        result = generate_machine_driver(facts, source=probe)
        assert isinstance(result, GeneratedArtifact)

        # Closed gate + DISCOVERED descriptor → skip (descriptor can't open gate)
        closed_facts = _missing_pinctrl_facts()
        result2 = generate_machine_driver(closed_facts, source=probe)
        assert isinstance(result2, GeneratorSkipped)


class TestReadOnlyGuard:
    """soc_descriptor.py is read-only (no writes, no network, no subprocess)."""

    def test_soc_descriptor_is_read_only(self):
        """AST guard: soc_descriptor.py has no write/network/subprocess primitives."""
        import ast

        src = (_REPO / "orchestrator" / "generation" / "soc_descriptor.py").read_text()
        tree = ast.parse(src)

        disallowed_names = {
            "open", "write", "mkdir", "makedirs", "rmdir", "remove", "unlink",
            "rename", "replace", "symlink", "link",
            "socket", "connect", "send", "recv", "urlopen", "request",
            "subprocess", "Popen", "call", "run", "check_output",
            "walk", "rglob",
        }
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in disallowed_names:
                found.add(node.id)
            if isinstance(node, ast.Attribute) and node.attr in disallowed_names:
                found.add(node.attr)

        assert not found, f"soc_descriptor.py uses disallowed primitives: {found}"

