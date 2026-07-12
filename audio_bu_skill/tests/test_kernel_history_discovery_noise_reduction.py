"""Unit tests for Benchmark Readiness Fix #2: kernel_history_discovery noise
reduction (fixture: a real temp git repo).

Confirms:
  - a FROMLIST/RFC-tagged commit is excluded unless it is also audio-relevant
    (whole-word audio keyword in subject/body, audio-shaped changed-file path,
    or audio-shaped compatible string) -- the tag alone is never sufficient,
  - RFCOMM (Bluetooth) commits are never matched merely because "RFCOMM"
    contains the substring "RFC",
  - crypto/cifs/drm-perf-counter FROMLIST/RFC commits are excluded when they
    carry no audio signal,
  - a genuine audio FROMLIST commit is retained,
  - donor_hint="value" (and other generic English-prose artifacts) is
    rejected rather than surfaced as a fake donor-architecture name,
  - exact-duplicate-subject/files commits are deduplicated and reported via
    duplicate_count, and non-audio drops are reported via
    filtered_non_audio_count (never silently truncated),
  - multi-parent merge commits are excluded outright (even when audio-
    relevant by keyword), reported via filtered_merge_count -- these are
    upstream integration merges whose diffstat spans the entire merged
    branch, which is what overflowed the qgenie subprocess argv in
    production before this fix,
  - single-parent commits whose changed-file count exceeds the configurable
    threshold are excluded outright, reported via filtered_oversized_count
    -- a tree-wide sweep commit is exactly as capable of overflowing the
    qgenie subprocess argv as a merge commit, even though it has only one
    parent,
  - a commit with a non-UTF8 byte in its diff never crashes discovery --
    git output is decoded with errors="replace",
  - a genuine audio commit is retained even after all of the above filters
    are added (no regression in the common case),
  - Kernel History Candidate Reduction phase: a raw candidate carrying no
    lightweight signal at all (no tag/audio keyword in its subject, no
    target-name mention in its subject, not found via the path finder) is
    dropped before any expensive git call, reported via
    ``lightweight_filtered_candidate_count`` being smaller than
    ``raw_candidate_count``,
  - the expensive stage (merge check, diffstat, full diff, is_applied) is
    capped to the top ``max_expensive_candidates`` ranked survivors --
    ``expensive_candidate_count`` never exceeds that cap even when the raw
    candidate pool is much larger -- and the top-ranked genuine audio commit
    still survives to the final candidate list even when many low-relevance
    commits are competing for the same capped slots (no quality regression
    from the volume-reduction phase).

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_kernel_history_discovery_noise_reduction
(or: python3 audio_bu_skill/tests/test_kernel_history_discovery_noise_reduction.py)
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


def _commit(repo: Path, filename: str, content: str, subject: str, body: str = "") -> str:
    (repo / filename).write_text(content, encoding="utf-8")
    _git(repo, "add", filename)
    message = subject if not body else f"{subject}\n\n{body}"
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def test_rfcomm_not_included_despite_rfc_substring() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        rfcomm_sha = _commit(
            repo, "rfcomm.c", "// bluetooth rfcomm fix\n",
            "RFC: Bluetooth: RFCOMM: fix use-after-free in disconnect path",
        )

        result = discover_kernel_history(repo, target_name="")
        shas = [c["sha"] for c in result["candidates"]]
        assert rfcomm_sha not in shas, (rfcomm_sha, result["candidates"])
        assert result["filtered_non_audio_count"] >= 1, result
    print("PASS: RFCOMM commit excluded despite containing the 'RFC' substring")


def test_crypto_not_included() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        crypto_sha = _commit(
            repo, "aes.c", "// crypto aes update\n",
            "FROMLIST: crypto: aes - add hardware acceleration support",
        )

        result = discover_kernel_history(repo, target_name="")
        shas = [c["sha"] for c in result["candidates"]]
        assert crypto_sha not in shas, (crypto_sha, result["candidates"])
    print("PASS: crypto FROMLIST commit excluded (no audio signal)")


def test_cifs_not_included() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        cifs_sha = _commit(
            repo, "cifs.c", "// cifs mount fix\n",
            "RFC: cifs: fix mount option parsing for multichannel",
        )

        result = discover_kernel_history(repo, target_name="")
        shas = [c["sha"] for c in result["candidates"]]
        assert cifs_sha not in shas, (cifs_sha, result["candidates"])
    print("PASS: cifs RFC commit excluded (no audio signal)")


def test_drm_perf_not_included_unless_audio_relevant() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        drm_sha = _commit(
            repo, "drm_perf.c", "// gpu perf counters\n",
            "FROMLIST: drm/msm: add GPU performance counter support",
        )

        result = discover_kernel_history(repo, target_name="")
        shas = [c["sha"] for c in result["candidates"]]
        assert drm_sha not in shas, (drm_sha, result["candidates"])
    print("PASS: drm perf-counter FROMLIST commit excluded (no audio signal)")


def test_real_audio_commit_retained() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        audio_sha = _commit(
            repo, "newboard-audio.dtsi",
            'lpass_wsamacro: wsa-macro@1 {\n'
            '    compatible = "vendor,newboard-lpass-wsa-macro";\n'
            '};\n',
            "FROMLIST: arm64: dts: vendor: newboard: Add LPASS macro and SoundWire support",
            "The hardware is similar to the DONORSOC platform.",
        )

        result = discover_kernel_history(repo, target_name="newboard")
        shas = [c["sha"] for c in result["candidates"]]
        assert audio_sha in shas, (audio_sha, result["candidates"])
        candidate = next(c for c in result["candidates"] if c["sha"] == audio_sha)
        assert candidate["donor_hint"] == "DONORSOC", candidate
    print("PASS: genuine audio FROMLIST commit retained with donor hint intact")


def test_donor_hint_value_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        audio_sha = _commit(
            repo, "sound-fixup.c", "// sound fixup\n",
            "FROMLIST: ASoC: newboard: fix sound clock rate",
            "The clock rate is based on the value returned by the parent PLL.",
        )

        result = discover_kernel_history(repo, target_name="")
        candidate = next(c for c in result["candidates"] if c["sha"] == audio_sha)
        assert candidate["donor_hint"] is None, candidate
    print("PASS: donor_hint='value' (generic prose artifact) rejected -> None, not surfaced")


def test_exact_duplicate_subjects_deduplicated() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        base = _git(repo, "rev-parse", "HEAD").stdout.strip()

        _git(repo, "checkout", "-q", "-b", "branch-a")
        sha_a = _commit(repo, "audio-dup.c", "// audio dup a\n", "FROMLIST: ASoC: newboard: add audio codec support")
        _git(repo, "checkout", "-q", base)

        _git(repo, "checkout", "-q", "-b", "branch-b")
        sha_b = _commit(repo, "audio-dup.c", "// audio dup b (same subject+file)\n", "FROMLIST: ASoC: newboard: add audio codec support")
        _git(repo, "checkout", "-q", base)

        result = discover_kernel_history(repo, target_name="")
        shas = [c["sha"] for c in result["candidates"]]
        assert (sha_a in shas) != (sha_b in shas) or len(shas) <= 1, (
            "expected at most one of the exact-duplicate commits to be kept", sha_a, sha_b, shas
        )
        assert result["duplicate_count"] >= 1, result
    print("PASS: exact-duplicate-subject commits deduplicated, reported via duplicate_count")


def test_merge_commit_excluded_even_when_audio_relevant() -> None:
    """Benchmark Readiness Fix #2 follow-up: an upstream integration merge
    (2+ parents) must be excluded outright, even if its subject/body would
    otherwise pass the audio-relevance gate -- its diffstat spans the entire
    merged branch (real-world case: a 'Merge tag drm-next-...' commit with
    1700+ changed files blew past the OS argv-length limit when passed
    through to the qgenie subprocess as a kernel_history candidate)."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        base = _git(repo, "rev-parse", "HEAD").stdout.strip()

        _git(repo, "checkout", "-q", "-b", "audio-topic")
        _commit(repo, "topic-audio.c", "// topic branch audio work\n",
                "FROMLIST: ASoC: newboard: add lpass audio codec support")
        _git(repo, "checkout", "-q", base)

        _git(repo, "checkout", "-q", "-b", "main-line")
        merge_result = subprocess.run(
            ["git", "-C", str(repo), "merge", "--no-ff", "audio-topic",
             "-m", "Merge tag 'newboard-audio-2026' of git://example/newboard into main-line\n\n"
                   "audio soundwire lpass integration for this cycle."],
            capture_output=True, text=True,
        )
        assert merge_result.returncode == 0, merge_result.stderr
        merge_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

        result = discover_kernel_history(repo, target_name="")
        shas = [c["sha"] for c in result["candidates"]]
        assert merge_sha not in shas, (merge_sha, result["candidates"])
        assert result.get("filtered_merge_count", 0) >= 1, result
    print("PASS: multi-parent merge commit excluded outright (never a real FROMLIST donor "
          "patch series), reported via filtered_merge_count, even though its subject/body "
          "carries audio keywords that would otherwise pass the audio-relevance gate")


def test_oversized_sweep_commit_excluded_even_when_single_parent() -> None:
    """A single-parent commit whose diffstat spans 1500+ files (e.g. a
    tree-wide header-rename sweep) must be excluded outright, even though it
    has only one parent and is therefore *not* caught by the merge filter.
    This is the real-world commit that survived the merge-commit fix and
    still overflowed the qgenie subprocess argv (995832b2 in the Eliza
    kernel tree: "Replace <linux/mod_devicetable.h> by more specific
    <linux/dev...>", 1526 files changed, 56KB of the 62KB kernel_history
    JSON on its own) -- its subject/body carries no audio keyword, but one of
    its 1500+ changed file paths happens to be audio-shaped, which is enough
    to pass the audio-relevance gate unless the file-count cap runs first."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)

        for i in range(150):
            (repo / f"driver_{i}.h").write_text(f"// driver {i}\n", encoding="utf-8")
        (repo / "sound_core.h").write_text("// audio core header\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m",
             "treewide: replace <linux/foo.h> by more specific headers across drivers")
        sweep_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

        # target_name="sound_core" makes _log_by_path discover this commit via
        # its one audio-shaped changed file, mirroring how the real Eliza
        # sweep commit was discovered despite its subject carrying no
        # audio/FROMLIST/RFC keyword at all.
        result = discover_kernel_history(repo, target_name="sound_core", max_files_changed=100)
        shas = [c["sha"] for c in result["candidates"]]
        assert sweep_sha not in shas, (sweep_sha, result["candidates"])
        assert result.get("filtered_oversized_count", 0) >= 1, result
    print("PASS: 150-file sweep commit excluded via configurable max_files_changed threshold, "
          "reported via filtered_oversized_count, despite having only one parent (so the merge "
          "filter alone would have let it through) and touching one audio-shaped path")


def test_oversized_diff_text_excluded_via_size_threshold() -> None:
    """A commit whose raw diff text exceeds the configurable size threshold
    is excluded outright, independent of file count -- e.g. a single file
    rewritten wholesale with a huge diff."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)

        big_content = "sound_reg_write(x);\n" * 5000
        (repo / "sound_bigfile.c").write_text(big_content, encoding="utf-8")
        _git(repo, "add", "sound_bigfile.c")
        _git(repo, "commit", "-q", "-m", "FROMLIST: ASoC: newboard: rewrite audio register table")
        big_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

        result = discover_kernel_history(repo, target_name="", max_diff_chars=1000)
        shas = [c["sha"] for c in result["candidates"]]
        assert big_sha not in shas, (big_sha, result["candidates"])
        assert result.get("filtered_oversized_count", 0) >= 1, result
    print("PASS: commit with oversized diff text excluded via configurable max_diff_chars "
          "threshold, reported via filtered_oversized_count")


def test_binary_non_utf8_diff_does_not_crash_discovery() -> None:
    """A commit whose diff contains a non-UTF8 byte (real-world case: a
    107MB diff in the nord-iq10 kernel tree raised UnicodeDecodeError inside
    git show's stdout decoding, crashing discovery outright) must never crash
    -- git output is decoded with errors="replace" so a malformed byte
    becomes a replacement character instead of an exception."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)

        non_utf8_path = repo / "sound_firmware_table.c"
        non_utf8_path.write_bytes(
            b"/* audio firmware table */\nstatic const char table[] = {\n"
            b"0x41, 0x\xc0\xc1, 0x42,\n};\n"
        )
        _git(repo, "add", "sound_firmware_table.c")
        _git(repo, "commit", "-q", "-m", "FROMLIST: ASoC: newboard: add audio firmware table")
        non_utf8_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

        result = discover_kernel_history(repo, target_name="")
        assert result["git_available"] is True, result
    print("PASS: non-UTF8 byte in a commit diff never raises -- decoded with errors=\"replace\"")


def test_real_audio_commit_retained_alongside_size_filters() -> None:
    """A genuine, reasonably-sized audio commit must still be retained after
    the merge/file-count/diff-size filters are added -- no regression in the
    common case."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        audio_sha = _commit(
            repo, "newboard-audio2.dtsi",
            'lpass_wsamacro: wsa-macro@2 {\n'
            '    compatible = "vendor,newboard-lpass-wsa-macro";\n'
            '};\n',
            "FROMLIST: arm64: dts: vendor: newboard: Add second LPASS macro and SoundWire support",
        )

        result = discover_kernel_history(repo, target_name="newboard", max_files_changed=100, max_diff_chars=50_000)
        shas = [c["sha"] for c in result["candidates"]]
        assert audio_sha in shas, (audio_sha, result["candidates"])
    print("PASS: genuine audio commit retained alongside merge/file-count/diff-size filters")


def test_lightweight_filter_drops_signal_free_candidates_before_expensive_stage() -> None:
    """A raw candidate discovered only via the broad keyword git-log search
    (e.g. matched on a body line, not the subject) but carrying no tag/audio
    keyword in its *subject*, no target-name mention in its subject, and not
    independently found by the path finder, must be dropped by the
    lightweight filter -- before any merge check, diffstat, or full diff is
    ever fetched for it. This is the volume-reduction phase itself: real-world
    kernel trees can surface thousands of raw candidates, and only a fraction
    of those carry any cheap signal at all."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        # Matched by _log_by_grep via the body ("sound"), but the *subject*
        # (what _relevance_score actually scores) carries no tag/audio/
        # target-name keyword, and the changed file is not audio/target
        # shaped -- so _log_by_path won't find it either. Zero lightweight
        # signal on this commit.
        noise_sha = _commit(
            repo, "unrelated_driver.c", "// unrelated change\n",
            "net: fix unrelated packet counter overflow",
            "This also touches the sound level of logging verbosity slightly.",
        )
        audio_sha = _commit(
            repo, "newboard-audio3.dtsi",
            'lpass_wsamacro: wsa-macro@3 {\n'
            '    compatible = "vendor,newboard-lpass-wsa-macro";\n'
            '};\n',
            "FROMLIST: arm64: dts: vendor: newboard: Add third LPASS macro and SoundWire support",
        )

        result = discover_kernel_history(repo, target_name="newboard")
        assert result["raw_candidate_count"] >= 2, result
        assert result["lightweight_filtered_candidate_count"] < result["raw_candidate_count"], result
        shas = [c["sha"] for c in result["candidates"]]
        assert noise_sha not in shas, (noise_sha, result["candidates"])
        assert audio_sha in shas, (audio_sha, result["candidates"])
    print("PASS: signal-free raw candidate dropped by lightweight filter before any expensive "
          "git call; lightweight_filtered_candidate_count < raw_candidate_count")


def test_expensive_stage_capped_to_top_ranked_candidates() -> None:
    """Regardless of how many candidates survive the lightweight filter, only
    the top max_expensive_candidates ranked survivors may enter the expensive
    stage (merge check / diffstat / full diff / is_applied) -- this is what
    keeps discovery inside the onboarding analysis timeout when a kernel
    tree's raw candidate pool is very large. The single highest-ranked
    genuine audio commit must still survive the cap and appear in the final
    candidate list even when many lower-ranked commits are competing for the
    same capped slots (no quality regression from capping)."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)

        # Many low-relevance-but-lightweight-signal-carrying commits (each
        # mentions "sound" in the subject, so each earns a nonzero lightweight
        # score and is not dropped by the lightweight filter) that outnumber
        # the expensive-stage cap.
        for i in range(20):
            (repo / f"noise{i}.c").write_text(f"// noise {i}\n", encoding="utf-8")
            _git(repo, "add", f"noise{i}.c")
            _git(repo, "commit", "-q", "-m", f"sound: minor unrelated cleanup {i}")

        # One clearly top-ranked genuine audio FROMLIST commit -- highest
        # _relevance_score of the pool (tag keyword + audio keyword + target
        # name all present in the subject).
        audio_sha = _commit(
            repo, "newboard-audio4.dtsi",
            'lpass_wsamacro: wsa-macro@4 {\n'
            '    compatible = "vendor,newboard-lpass-wsa-macro";\n'
            '};\n',
            "FROMLIST: arm64: dts: vendor: newboard: Add fourth LPASS sound macro support",
        )

        result = discover_kernel_history(repo, target_name="newboard", max_expensive_candidates=5)
        assert result["expensive_candidate_count"] <= 5, result
        assert result["lightweight_filtered_candidate_count"] > result["expensive_candidate_count"], result
        shas = [c["sha"] for c in result["candidates"]]
        assert audio_sha in shas, (audio_sha, result["candidates"])
    print("PASS: expensive stage capped to max_expensive_candidates; top-ranked genuine audio "
          "commit still survives the cap and reaches the final candidate list")


def test_instrumentation_counts_monotonically_non_increasing() -> None:
    """The four Candidate Reduction phase counts must never increase from one
    stage to the next: raw >= lightweight-filtered == ranked >= expensive."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        _commit(
            repo, "newboard-audio5.dtsi",
            'lpass_wsamacro: wsa-macro@5 {\n'
            '    compatible = "vendor,newboard-lpass-wsa-macro";\n'
            '};\n',
            "FROMLIST: arm64: dts: vendor: newboard: Add fifth LPASS macro and SoundWire support",
        )
        _commit(repo, "irrelevant.c", "// nothing audio here\n", "misc: bump version string")

        result = discover_kernel_history(repo, target_name="newboard")
        assert result["raw_candidate_count"] >= result["lightweight_filtered_candidate_count"] >= 0, result
        assert result["lightweight_filtered_candidate_count"] == result["ranked_candidate_count"], result
        assert result["ranked_candidate_count"] >= result["expensive_candidate_count"] >= 0, result
    print("PASS: raw/lightweight-filtered/ranked/expensive candidate counts are monotonically "
          "non-increasing through the pipeline stages")


def main() -> None:
    test_rfcomm_not_included_despite_rfc_substring()
    test_crypto_not_included()
    test_cifs_not_included()
    test_drm_perf_not_included_unless_audio_relevant()
    test_real_audio_commit_retained()
    test_donor_hint_value_rejected()
    test_exact_duplicate_subjects_deduplicated()
    test_merge_commit_excluded_even_when_audio_relevant()
    test_oversized_sweep_commit_excluded_even_when_single_parent()
    test_oversized_diff_text_excluded_via_size_threshold()
    test_binary_non_utf8_diff_does_not_crash_discovery()
    test_real_audio_commit_retained_alongside_size_filters()
    test_lightweight_filter_drops_signal_free_candidates_before_expensive_stage()
    test_expensive_stage_capped_to_top_ranked_candidates()
    test_instrumentation_counts_monotonically_non_increasing()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
