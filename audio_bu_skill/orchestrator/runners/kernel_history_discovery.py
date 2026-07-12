"""Kernel git-history / FROMLIST patch discovery for target_onboarding.

Mirrors the manual git-archaeology step done during the independent Eliza
audio bring-up analysis: before proposing a nearest target or donor
architecture from scratch, check whether the kernel's own ``git log --all``
already contains unmerged FROMLIST/RFC patches (visible in history, not
necessarily in the checked-out worktree) that describe the same hardware.

Read-only: every git invocation here is ``log``, ``show``, or
``merge-base --is-ancestor`` -- none of them mutate the working tree, the
index, or any ref. This module never checks anything out, applies a patch,
stages a change, or writes to the kernel source tree.

Used by target_onboarding_runner as a read-only evidence collector: it
runs before nearest-target/donor selection and feeds its findings into
task_spec, but never mutates the kernel worktree, index, or any ref.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

_DEFAULT_KEYWORDS = (
    "FROMLIST", "RFC", "audio", "sound", "lpass", "wsa", "va-macro",
    "va macro", "gpr", "q6apm", "q6prm", "soundwire",
)
# Tag keywords mark a commit as a downstream/vendor patch series (FROMLIST/RFC)
# but say nothing about *subsystem* -- the upstream kernel tags FROMLIST/RFC
# patches for GPU, PCIe, crypto, cifs, Bluetooth (RFCOMM), etc. just as often
# as audio. A tag match alone must never be sufficient for inclusion.
_TAG_KEYWORDS = ("FROMLIST", "RFC")
# Audio keywords are the only signal that makes a commit an audio candidate.
_AUDIO_KEYWORDS = (
    "audio", "sound", "lpass", "wsa", "va-macro", "va macro", "gpr",
    "q6apm", "q6prm", "soundwire",
)
_AUDIO_PATH_RE = re.compile(r"sound[/_]|audio|lpass|soundwire|wsa\d|va[-_ ]?macro", re.IGNORECASE)
_AUDIO_KEYWORD_RES = tuple(
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE) for kw in _AUDIO_KEYWORDS
)
_TAG_KEYWORD_RES = tuple(
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE) for kw in _TAG_KEYWORDS
)
_MAX_CANDIDATES = 30
_GIT_TIMEOUT = 30
# Single-parent commits can still have a diffstat spanning far more files than
# any real FROMLIST/RFC donor patch series -- e.g. a tree-wide header-rename
# sweep that happens to touch one audio-shaped path among 1000+ changed files.
# These are excluded outright, just like merge commits, for the same reason:
# their bloated diffstat is what overflows the qgenie subprocess argv.
_MAX_FILES_CHANGED = 100
# Independently of file count, a commit's raw diff text can itself be huge
# (e.g. a single binary/generated file rewritten wholesale). Cap on decoded
# diff-text length, checked before the diff is used for anything else.
_MAX_DIFF_CHARS = 50_000
# A wide kernel tree's broad `git log --all` finders can surface thousands of
# raw candidate SHAs (measured: 7806 for one real target tree) -- and every
# candidate that reaches the *expensive* per-candidate stage (merge check,
# diffstat, full diff, is_applied -- ~4 git subprocess round-trips each) costs
# roughly 50x what the lightweight subject-only scoring pass costs per
# candidate. Only the top-ranked slice of the lightweight-filtered pool is
# allowed into that expensive stage; this is what keeps kernel history
# discovery inside the onboarding analysis timeout regardless of how large
# the raw candidate pool is. Kept well above ``_MAX_CANDIDATES`` so that
# merge/oversized/non-audio/duplicate losses along the way still leave enough
# survivors for a full final candidate list.
_MAX_EXPENSIVE_CANDIDATES = 200

_COMPATIBLE_STRING_RE = re.compile(r'"([a-zA-Z0-9,._-]+)"')
_DONOR_HINT_RE = re.compile(
    r"(?:similar to|based on|same as|shares .* with)\s+(?:the\s+)?"
    r"([A-Za-z0-9][A-Za-z0-9_\-]{2,30})\s*(?:platform|hardware|design|architecture)?",
    re.IGNORECASE,
)
# Words the donor-hint regex can capture that are not platform/architecture
# names -- e.g. "...is based on the value returned by..." -> "value" is not a
# donor SoC/board, it's an artifact of matching generic English prose.
_DONOR_HINT_STOPWORDS = {
    "value", "values", "platform", "hardware", "design", "architecture",
    "board", "device", "chip", "soc", "target", "system", "hw", "this",
    "that", "same", "similar", "reference", "existing", "current", "above",
    "below", "previous", "following", "other", "way", "logic", "code",
}



def _run_git(kernel_source: Path, args: list[str], timeout: int = _GIT_TIMEOUT) -> subprocess.CompletedProcess | None:
    """Kernel history spans decades of commits, some containing binary blobs
    or non-UTF8-encoded files. Decoding with errors="replace" (not the
    default strict decoding) means a single malformed byte in a diff can
    never crash discovery -- it becomes a replacement character instead."""
    try:
        return subprocess.run(
            ["git", "-C", str(kernel_source), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _is_git_repo(kernel_source: Path) -> bool:
    result = _run_git(kernel_source, ["rev-parse", "--is-inside-work-tree"])
    return bool(result and result.returncode == 0 and result.stdout.strip() == "true")


def _shas_from_log(result: subprocess.CompletedProcess | None) -> list[str]:
    if result is None or result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _log_by_grep(kernel_source: Path, keywords: tuple[str, ...]) -> list[str]:
    """SHAs whose subject/body matches any keyword (case-insensitive, OR'd,
    whole-word only -- e.g. ``RFC`` must never match inside ``RFCOMM``).

    Uses --perl-regexp (not --extended-regexp) because git's POSIX ERE grep
    backend does not reliably support ``\\b`` word-boundary anchors.
    """
    pattern = "|".join(rf"\b{re.escape(k)}\b" for k in keywords)
    return _shas_from_log(_run_git(
        kernel_source,
        ["log", "--all", "-i", "--perl-regexp", f"--grep={pattern}", "--format=%H"],
    ))


def _log_by_target_name(kernel_source: Path, target_name: str) -> list[str]:
    """SHAs whose subject/body mentions target_name (commit-message match, not path)."""
    if not target_name:
        return []
    return _shas_from_log(_run_git(
        kernel_source,
        ["log", "--all", "-i", f"--grep={re.escape(target_name)}", "--format=%H"],
    ))


def _log_by_path(kernel_source: Path, target_name: str) -> list[str]:
    """SHAs of commits touching any path containing target_name (e.g. *eliza*)."""
    if not target_name:
        return []
    return _shas_from_log(_run_git(
        kernel_source,
        ["log", "--all", "--format=%H", "--", f"*{target_name}*"],
    ))


def _subject(kernel_source: Path, sha: str) -> str:
    result = _run_git(kernel_source, ["show", "-s", "--format=%s", sha])
    return result.stdout.strip() if result and result.returncode == 0 else ""


def _body(kernel_source: Path, sha: str) -> str:
    result = _run_git(kernel_source, ["show", "-s", "--format=%B", sha])
    return result.stdout if result and result.returncode == 0 else ""


def _files_changed(kernel_source: Path, sha: str) -> list[str]:
    result = _run_git(kernel_source, ["show", "--stat", "--format=", sha])
    if result is None or result.returncode != 0:
        return []
    files: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        files.append(line.split("|", 1)[0].strip())
    return files


def _is_applied(kernel_source: Path, sha: str) -> bool | None:
    """True if sha is already an ancestor of HEAD, False if not, None if undetermined."""
    result = _run_git(kernel_source, ["merge-base", "--is-ancestor", sha, "HEAD"])
    if result is None or result.returncode not in (0, 1):
        return None
    return result.returncode == 0


def _is_merge_commit(kernel_source: Path, sha: str) -> bool:
    """True if sha has 2+ parents -- an upstream integration merge, never a
    real FROMLIST/RFC donor patch series. Its ``git show --stat`` diffstat is
    the *entire* merged branch (often 1000+ files), which is what overflowed
    the qgenie subprocess argv when one slipped through as a candidate."""
    result = _run_git(kernel_source, ["rev-parse", f"{sha}^2"])
    return bool(result and result.returncode == 0)


def _diff_text(kernel_source: Path, sha: str) -> str:
    result = _run_git(kernel_source, ["show", sha])
    return result.stdout if result and result.returncode == 0 else ""


def _extract_compatible_fallbacks(diff_text: str) -> list[str]:
    """Every quoted string on an added ``compatible = "...", "...";`` diff line."""
    found: list[str] = []
    for line in diff_text.splitlines():
        if not line.startswith("+") or line.startswith("+++") or "compatible" not in line:
            continue
        found.extend(_COMPATIBLE_STRING_RE.findall(line))
    seen: set[str] = set()
    out: list[str] = []
    for f in found:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _extract_donor_hint(message: str) -> str | None:
    match = _DONOR_HINT_RE.search(message)
    if not match:
        return None
    hint = match.group(1)
    if hint.lower() in _DONOR_HINT_STOPWORDS:
        return None
    return hint


def _is_audio_relevant(text: str, files_changed: list[str], compatible_fallbacks: list[str]) -> bool:
    """A commit is audio-relevant only if it actually says so.

    A commit merely tagged FROMLIST/RFC is not audio-relevant on its own --
    upstream tags FROMLIST/RFC patches for GPU, PCIe, crypto, cifs, Bluetooth
    (RFCOMM), PMIC, and interconnect subsystems just as often as audio. This
    gate requires an explicit audio keyword (whole-word, in subject/body), an
    audio-shaped changed-file path, or an audio-shaped compatible string --
    never the FROMLIST/RFC tag alone.
    """
    if any(rx.search(text) for rx in _AUDIO_KEYWORD_RES):
        return True
    if any(_AUDIO_PATH_RE.search(f) for f in files_changed):
        return True
    if any(_AUDIO_PATH_RE.search(c) for c in compatible_fallbacks):
        return True
    return False


def _relevance_score(subject: str, keywords: tuple[str, ...], target_name: str) -> int:
    score = 0
    if any(rx.search(subject) for rx in _TAG_KEYWORD_RES):
        score += 3
    if target_name and target_name.lower() in subject.lower():
        score += 2
    for kw in keywords:
        if re.search(rf"\b{re.escape(kw)}\b", subject, re.IGNORECASE):
            score += 1
    return score


def discover_kernel_history(
    kernel_source: str | Path, target_name: str = "",
    *, keywords: tuple[str, ...] = _DEFAULT_KEYWORDS, max_candidates: int = _MAX_CANDIDATES,
    max_files_changed: int = _MAX_FILES_CHANGED, max_diff_chars: int = _MAX_DIFF_CHARS,
    max_expensive_candidates: int = _MAX_EXPENSIVE_CANDIDATES,
) -> dict[str, Any]:
    """Discover FROMLIST/RFC/audio-subsystem commits anywhere in git history.

    Read-only (log/show/merge-base only). Returns candidate patch series with
    donor hints and compatible-string fallbacks extracted from the diff, plus
    applied/unapplied status against the currently checked-out HEAD. Never
    raises on a missing/invalid git repo -- returns an empty result instead,
    matching run_manifest._kernel_commit's graceful-fallback pattern.

    Candidate-reduction phase (runs before any expensive git call): a wide
    kernel tree's broad git-log finders can surface thousands of raw
    candidate SHAs, and every one of them used to pay the full expensive
    per-candidate cost (merge check, diffstat, full diff, is_applied) before
    the final ``max_candidates`` truncation -- volume, not any single slow
    call, is what pushed real-world discovery past the onboarding analysis
    timeout. So candidates are first scored on cheap, subject-only signals
    (tag keyword, target-name mention, audio keyword -- ``_relevance_score``)
    plus one free signal, path relevance (whether the path-based finder
    ``_log_by_path`` found the SHA at all). A raw candidate carrying none of
    those signals is dropped immediately (``raw_candidate_count`` ->
    ``lightweight_filtered_candidate_count``). Survivors are ranked by score
    (``ranked_candidate_count``), and only the top ``max_expensive_candidates``
    of that ranking enter the expensive stage below (``expensive_candidate_count``)
    -- every drop reason at this phase is reported, never silent.

    Every commit that reaches the expensive stage is then required to pass an
    audio-relevance gate (``_is_audio_relevant``) before becoming a candidate
    -- a FROMLIST/RFC tag alone is never enough. Multi-parent (merge) commits
    are excluded outright before that gate: they are upstream integration
    merges, never a real donor patch series, and their diffstat spans the
    entire merged branch (``filtered_merge_count``). Single-parent commits
    whose changed-file count exceeds ``max_files_changed`` or whose raw diff
    text exceeds ``max_diff_chars`` are excluded the same way -- a tree-wide
    sweep commit (e.g. a header-rename touching 1500+ files) is never a real
    donor patch series either, and is exactly as capable of overflowing the
    qgenie subprocess argv as a merge commit (``filtered_oversized_count``).
    Exact-duplicate commits (same subject + same changed files, e.g. the same
    patch cherry-picked onto two branches) are collapsed to one candidate.
    All drop reasons are reported (never silently) via ``filtered_merge_count``
    / ``filtered_oversized_count`` / ``filtered_non_audio_count`` /
    ``duplicate_count``.

    Git output is decoded with errors="replace" (see ``_run_git``), so a
    binary or non-UTF8-encoded commit diff is never a crash -- at worst it
    surfaces replacement characters in ``compatible_fallbacks``/diff-derived
    fields, which the audio-relevance/size gates then filter normally.
    """
    ks = Path(kernel_source)
    if not ks.is_dir() or not _is_git_repo(ks):
        return {"candidates": [], "dropped_count": 0, "git_available": False}

    seen: set[str] = set()
    shas: list[str] = []
    path_result = _log_by_path(ks, target_name)
    path_matched = set(path_result)
    for finder_result in (
        _log_by_grep(ks, keywords),
        _log_by_target_name(ks, target_name),
        path_result,
    ):
        for sha in finder_result:
            if sha not in seen:
                seen.add(sha)
                shas.append(sha)
    raw_candidate_count = len(shas)

    scored_all = [(_relevance_score(_subject(ks, sha), keywords, target_name), sha) for sha in shas]

    # Lightweight candidate-reduction phase (see docstring): drop raw
    # candidates carrying no cheap signal at all before ranking/capping.
    lightweight = [(score, sha) for score, sha in scored_all if score > 0 or sha in path_matched]
    lightweight_filtered_candidate_count = len(lightweight)

    lightweight.sort(key=lambda item: item[0], reverse=True)
    ranked_candidate_count = len(lightweight)

    scored = lightweight[:max_expensive_candidates]
    expensive_candidate_count = len(scored)

    relevant: list[dict[str, Any]] = []
    filtered_non_audio_count = 0
    filtered_merge_count = 0
    filtered_oversized_count = 0
    dedup_seen: set[tuple[str, tuple[str, ...]]] = set()
    duplicate_count = 0
    for _, sha in scored:
        if _is_merge_commit(ks, sha):
            filtered_merge_count += 1
            continue

        files_changed = _files_changed(ks, sha)
        if len(files_changed) > max_files_changed:
            filtered_oversized_count += 1
            continue

        diff_text = _diff_text(ks, sha)
        if len(diff_text) > max_diff_chars:
            filtered_oversized_count += 1
            continue

        subject = _subject(ks, sha)
        body = _body(ks, sha)
        compatible_fallbacks = _extract_compatible_fallbacks(diff_text)

        if not _is_audio_relevant(f"{subject}\n{body}", files_changed, compatible_fallbacks):
            filtered_non_audio_count += 1
            continue

        dedup_key = (subject.strip().lower(), tuple(sorted(files_changed)))
        if dedup_key in dedup_seen:
            duplicate_count += 1
            continue
        dedup_seen.add(dedup_key)

        relevant.append({
            "sha": sha,
            "subject": subject,
            "files_changed": files_changed,
            "applied": _is_applied(ks, sha),
            "donor_hint": _extract_donor_hint(body),
            "compatible_fallbacks": compatible_fallbacks,
        })

    dropped_count = max(0, len(relevant) - max_candidates)
    candidates = relevant[:max_candidates]

    return {
        "candidates": candidates,
        "dropped_count": dropped_count,
        "git_available": True,
        "filtered_non_audio_count": filtered_non_audio_count,
        "filtered_merge_count": filtered_merge_count,
        "filtered_oversized_count": filtered_oversized_count,
        "duplicate_count": duplicate_count,
        "raw_candidate_count": raw_candidate_count,
        "lightweight_filtered_candidate_count": lightweight_filtered_candidate_count,
        "ranked_candidate_count": ranked_candidate_count,
        "expensive_candidate_count": expensive_candidate_count,
    }
