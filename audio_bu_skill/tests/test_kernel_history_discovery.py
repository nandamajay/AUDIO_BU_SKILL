"""Unit tests for kernel_history_discovery (fixture: a real temp git repo).

Builds a throwaway git repository with a FROMLIST-style commit (adding a new
DT node with compatible fallback strings and a donor-architecture hint in the
commit message) plus an unrelated commit, and asserts discover_kernel_history
finds it, correctly reports applied/unapplied, and extracts the donor hint +
compatible strings.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_kernel_history_discovery
(or: python3 audio_bu_skill/tests/test_kernel_history_discovery.py)
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from orchestrator.runners.kernel_history_discovery import discover_kernel_history


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README")
    _git(repo, "commit", "-q", "-m", "initial: base kernel checkout")


def _add_unrelated_commit(repo: Path) -> str:
    (repo / "Makefile").write_text("# fix typo\n", encoding="utf-8")
    _git(repo, "add", "Makefile")
    _git(repo, "commit", "-q", "-m", "build: fix typo in Makefile")
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _add_fromlist_commit_on_branch(repo: Path, branch: str) -> str:
    """A FROMLIST commit on its own branch, NOT merged into whatever is HEAD later."""
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "checkout", "-q", "-b", branch)
    dts = repo / "newboard-audio.dtsi"
    dts.write_text(
        'lpass_wsamacro: wsa-macro@1 {\n'
        '    compatible = "vendor,newboard-lpass-wsa-macro", "vendor,donorsoc-lpass-wsa-macro";\n'
        '    status = "disabled";\n'
        '};\n',
        encoding="utf-8",
    )
    _git(repo, "add", "newboard-audio.dtsi")
    _git(repo, "commit", "-q", "-m",
         "FROMLIST: arm64: dts: vendor: newboard: Add LPASS macro and SoundWire support\n\n"
         "The hardware is similar to the DONORSOC platform.\n")
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "checkout", "-q", base)
    return sha


def test_discovers_unapplied_fromlist_commit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        fromlist_sha = _add_fromlist_commit_on_branch(repo, "fromlist-topic")
        _add_unrelated_commit(repo)  # advances HEAD (master) without the FROMLIST commit

        result = discover_kernel_history(repo, target_name="newboard")
        assert result["git_available"] is True

        shas = [c["sha"] for c in result["candidates"]]
        assert fromlist_sha in shas, (fromlist_sha, shas)

        candidate = next(c for c in result["candidates"] if c["sha"] == fromlist_sha)
        assert candidate["applied"] is False, candidate
        assert "newboard-audio.dtsi" in candidate["files_changed"], candidate
        assert candidate["donor_hint"] == "DONORSOC", candidate
        assert "vendor,newboard-lpass-wsa-macro" in candidate["compatible_fallbacks"], candidate
        assert "vendor,donorsoc-lpass-wsa-macro" in candidate["compatible_fallbacks"], candidate
        assert "FROMLIST" in candidate["subject"], candidate

        # unrelated commit must not be surfaced as a candidate
        unrelated_subjects = [c["subject"] for c in result["candidates"]]
        assert not any("fix typo" in s for s in unrelated_subjects), unrelated_subjects
    print("PASS: unapplied FROMLIST commit discovered with donor hint + compatible fallbacks")


def test_applied_after_merge() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        fromlist_sha = _add_fromlist_commit_on_branch(repo, "fromlist-topic")
        _git(repo, "merge", "-q", "--no-ff", "-m", "merge fromlist-topic", "fromlist-topic")

        result = discover_kernel_history(repo, target_name="newboard")
        candidate = next(c for c in result["candidates"] if c["sha"] == fromlist_sha)
        assert candidate["applied"] is True, candidate
    print("PASS: FROMLIST commit reports applied=True once merged into HEAD")


def test_no_git_repo_returns_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        not_a_repo = Path(tmp) / "plain_dir"
        not_a_repo.mkdir()
        (not_a_repo / "file.txt").write_text("hello\n", encoding="utf-8")

        result = discover_kernel_history(not_a_repo, target_name="anything")
        assert result == {"candidates": [], "dropped_count": 0, "git_available": False}
    print("PASS: non-git directory returns empty result, no crash")


def test_missing_kernel_source_returns_empty() -> None:
    result = discover_kernel_history("/nonexistent/path/does/not/exist", target_name="x")
    assert result["git_available"] is False
    assert result["candidates"] == []
    print("PASS: nonexistent kernel_source path returns empty result, no crash")


def test_max_candidates_caps_and_reports_dropped() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        for i in range(5):
            (repo / f"soundfile{i}.txt").write_text(f"audio change {i}\n", encoding="utf-8")
            _git(repo, "add", f"soundfile{i}.txt")
            _git(repo, "commit", "-q", "-m", f"FROMLIST: sound: change {i}")

        result = discover_kernel_history(repo, target_name="", max_candidates=2)
        assert len(result["candidates"]) == 2, result["candidates"]
        assert result["dropped_count"] == 3, result
    print("PASS: max_candidates caps results and reports dropped_count (no silent truncation)")


def test_never_mutates_kernel_tree() -> None:
    """Read-only guarantee: HEAD, branches, and working tree are unchanged after discovery."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        _add_fromlist_commit_on_branch(repo, "fromlist-topic")
        _add_unrelated_commit(repo)

        head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()
        branch_before = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        status_before = _git(repo, "status", "--porcelain").stdout

        discover_kernel_history(repo, target_name="newboard")

        assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head_before
        assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == branch_before
        assert _git(repo, "status", "--porcelain").stdout == status_before
    print("PASS: discover_kernel_history never mutates HEAD, branch, or working tree")


def main() -> None:
    test_discovers_unapplied_fromlist_commit()
    test_applied_after_merge()
    test_no_git_repo_returns_empty()
    test_missing_kernel_source_returns_empty()
    test_max_candidates_caps_and_reports_dropped()
    test_never_mutates_kernel_tree()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
