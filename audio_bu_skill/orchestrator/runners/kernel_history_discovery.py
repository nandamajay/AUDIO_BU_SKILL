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

Not wired into the onboarding runner yet (slice 1 of the Onboarding Accuracy
Upgrade) -- this file is standalone and self-tested only.
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
_MAX_CANDIDATES = 30
_GIT_TIMEOUT = 30

_COMPATIBLE_STRING_RE = re.compile(r'"([a-zA-Z0-9,._-]+)"')
_DONOR_HINT_RE = re.compile(
    r"(?:similar to|based on|same as|shares .* with)\s+(?:the\s+)?"
    r"([A-Za-z0-9][A-Za-z0-9_\-]{2,30})\s*(?:platform|hardware|design|architecture)?",
    re.IGNORECASE,
)


def _run_git(kernel_source: Path, args: list[str], timeout: int = _GIT_TIMEOUT) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", "-C", str(kernel_source), *args],
            capture_output=True, text=True, timeout=timeout,
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
    """SHAs whose subject/body matches any keyword (case-insensitive, OR'd)."""
    pattern = "|".join(re.escape(k) for k in keywords)
    return _shas_from_log(_run_git(
        kernel_source,
        ["log", "--all", "-i", "--extended-regexp", f"--grep={pattern}", "--format=%H"],
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
    return match.group(1) if match else None


def _relevance_score(subject: str, keywords: tuple[str, ...], target_name: str) -> int:
    score = 0
    low = subject.lower()
    if "fromlist" in low or "rfc" in low:
        score += 3
    if target_name and target_name.lower() in low:
        score += 2
    for kw in keywords:
        if kw.lower() in low:
            score += 1
    return score


def discover_kernel_history(
    kernel_source: str | Path, target_name: str = "",
    *, keywords: tuple[str, ...] = _DEFAULT_KEYWORDS, max_candidates: int = _MAX_CANDIDATES,
) -> dict[str, Any]:
    """Discover FROMLIST/RFC/audio-subsystem commits anywhere in git history.

    Read-only (log/show/merge-base only). Returns candidate patch series with
    donor hints and compatible-string fallbacks extracted from the diff, plus
    applied/unapplied status against the currently checked-out HEAD. Never
    raises on a missing/invalid git repo -- returns an empty result instead,
    matching run_manifest._kernel_commit's graceful-fallback pattern.
    """
    ks = Path(kernel_source)
    if not ks.is_dir() or not _is_git_repo(ks):
        return {"candidates": [], "dropped_count": 0, "git_available": False}

    seen: set[str] = set()
    shas: list[str] = []
    for finder_result in (
        _log_by_grep(ks, keywords),
        _log_by_target_name(ks, target_name),
        _log_by_path(ks, target_name),
    ):
        for sha in finder_result:
            if sha not in seen:
                seen.add(sha)
                shas.append(sha)

    scored = [(_relevance_score(_subject(ks, sha), keywords, target_name), sha) for sha in shas]
    scored.sort(key=lambda item: item[0], reverse=True)

    dropped_count = max(0, len(scored) - max_candidates)
    kept = scored[:max_candidates]

    candidates: list[dict[str, Any]] = []
    for _, sha in kept:
        message = _body(ks, sha)
        diff_text = _diff_text(ks, sha)
        candidates.append({
            "sha": sha,
            "subject": _subject(ks, sha),
            "files_changed": _files_changed(ks, sha),
            "applied": _is_applied(ks, sha),
            "donor_hint": _extract_donor_hint(message),
            "compatible_fallbacks": _extract_compatible_fallbacks(diff_text),
        })

    return {"candidates": candidates, "dropped_count": dropped_count, "git_available": True}
