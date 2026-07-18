"""Regression tests for source_intake_runner._glob_root filtering.

Guards the invariant that an evidence root containing only sentinel files
(.gitkeep) or 0-byte placeholders is treated as EMPTY — not as valid
IPCAT evidence. Without this filter, a bare `evidence/ipcat/.gitkeep`
inflates `offline_file_count` to 1 and downstream trust logic misreports
IPCAT status as `target_specific` even though no real evidence exists.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from orchestrator.runners.source_intake_runner import discover_evidence


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_gitkeep_only_ipcat_root_counts_as_empty() -> None:
    """An ipcat root with just .gitkeep must produce zero paths + ambiguity."""
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        ipcat_root = workspace / "targets" / "sample" / "evidence" / "ipcat"
        ipcat_root.mkdir(parents=True)
        (ipcat_root / ".gitkeep").write_bytes(b"")

        result = discover_evidence(
            workspace_root=workspace,
            evidence_roots={"ipcat": "targets/sample/evidence/ipcat"},
            source_choice="ipcat",
        )
        assert result["paths"] == []
        assert any(
            "empty" in a for a in result["ambiguities"]
        ), f"expected empty-directory ambiguity, got {result['ambiguities']}"


def test_zero_byte_file_ignored() -> None:
    """0-byte placeholder files must not inflate the evidence count."""
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        ipcat_root = workspace / "targets" / "sample" / "evidence" / "ipcat"
        ipcat_root.mkdir(parents=True)
        (ipcat_root / "placeholder.json").write_bytes(b"")

        result = discover_evidence(
            workspace_root=workspace,
            evidence_roots={"ipcat": "targets/sample/evidence/ipcat"},
            source_choice="ipcat",
        )
        assert result["paths"] == []


def test_real_file_counted() -> None:
    """A non-empty, non-sentinel file must still be counted."""
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        ipcat_root = workspace / "targets" / "sample" / "evidence" / "ipcat"
        ipcat_root.mkdir(parents=True)
        _write(ipcat_root / "real.json", b'{"chip":"nordschleife_2.0"}')
        (ipcat_root / ".gitkeep").write_bytes(b"")

        result = discover_evidence(
            workspace_root=workspace,
            evidence_roots={"ipcat": "targets/sample/evidence/ipcat"},
            source_choice="ipcat",
        )
        assert len(result["paths"]) == 1
        assert result["paths"][0].endswith("real.json")


def test_gitkeep_only_ipcat_first_falls_back() -> None:
    """With source_choice=ipcat_first, a .gitkeep-only ipcat root triggers offline fallback."""
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        ipcat_root = workspace / "targets" / "sample" / "evidence" / "ipcat"
        ipcat_root.mkdir(parents=True)
        (ipcat_root / ".gitkeep").write_bytes(b"")

        offline_root = workspace / "targets" / "sample" / "evidence" / "offline_documents"
        offline_root.mkdir(parents=True)
        _write(offline_root / "spec.txt", b"real content")

        result = discover_evidence(
            workspace_root=workspace,
            evidence_roots={
                "ipcat": "targets/sample/evidence/ipcat",
                "offline_documents": "targets/sample/evidence/offline_documents",
            },
            source_choice="ipcat_first",
        )
        assert len(result["paths"]) == 1
        assert result["paths"][0].endswith("spec.txt")
        assert result["provenance"]["fell_back"] is True


if __name__ == "__main__":
    test_gitkeep_only_ipcat_root_counts_as_empty()
    test_zero_byte_file_ignored()
    test_real_file_counted()
    test_gitkeep_only_ipcat_first_falls_back()
    print("OK")
