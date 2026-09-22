"""Delta gating: baselines and changed-line filtering (stdlib only).

Two adoption mechanisms, composable:

- baseline: record today's findings to a committed JSON file; later runs
  report only findings NOT in the file. Fingerprints hash checker + path +
  claim + title (never line numbers), so unrelated edits that shift lines
  do not churn the baseline. Editing the offending line itself changes the
  claim and re-triggers the gate.
- changed lines: `git diff` selects added/modified lines; findings outside
  them are hidden, EXCEPT findings whose claim names a symbol the diff
  touches (rename fallout: the edit renamed it here, the lie lives
  there). The whole tree is still scanned (cross-file resolution
  needs the full index); filtering applies to reporting only. Only
  verified findings are ever shown: expansion changes relevance, never
  truth.

Outside a git repo, or when git cannot resolve the base, changed-line mode
is an error, never a silent full scan: a gate must not quietly change what
it gates.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from .models import Finding

BASELINE_VERSION = 1
DEFAULT_BASELINE_NAME = ".grounded-baseline.json"


def fingerprint(f: Finding) -> str:
    h = hashlib.sha256()
    h.update(b"grounded-baseline-v1\x00")
    h.update(f.checker.encode("utf-8") + b"\x00")
    h.update(f.path.encode("utf-8") + b"\x00")
    h.update(f.title.encode("utf-8") + b"\x00")
    h.update(f.claim.encode("utf-8"))
    return h.hexdigest()[:32]


def write_baseline(path: Path, findings: list[Finding]) -> dict[str, int]:
    """Write sorted, de-duplicated fingerprint entries. Returns
    {"added","removed","total"} relative to the existing file (0/0 when
    creating).

    Two findings can share a fingerprint (same rule, path, title and claim
    text on different lines), so the entries are de-duplicated before
    writing: otherwise the file grows with repeats and its length
    disagrees with the `total` the caller just printed (measured on a
    10k-file tree: 277 unique fingerprints, 284 findings, file of 284).
    """
    old = load_baseline(path) if path.exists() else set()
    newset = {fingerprint(f) for f in findings}
    payload = {"version": BASELINE_VERSION, "fingerprints": sorted(newset)}
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return {"added": len(newset - old), "removed": len(old - newset), "total": len(newset)}


def load_baseline(path: Path) -> set[str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"baseline not readable: {path} ({exc})") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"baseline is not valid JSON: {path}") from exc
    if not isinstance(data, dict) or data.get("version") != BASELINE_VERSION:
        raise ValueError(f"unsupported baseline format: {path}")
    fps = data.get("fingerprints")
    if not isinstance(fps, list) or not all(isinstance(x, str) for x in fps):
        raise ValueError(f"unsupported baseline format: {path}")
    return set(fps)


def split_baselined(findings: list[Finding], fps: set[str]) -> tuple[list[Finding], list[Finding]]:
    """Partition into (new, suppressed)."""
    new = [f for f in findings if fingerprint(f) not in fps]
    suppressed = [f for f in findings if fingerprint(f) in fps]
    return new, suppressed


class GitError(RuntimeError):
    pass


def _git(root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as exc:
        raise GitError("git is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError("git timed out") from exc
    if proc.returncode != 0:
        raise GitError((proc.stderr or proc.stdout or "git failed").strip().splitlines()[0][:160])
    return proc.stdout


def _resolve_base(root: Path, base: str) -> str:
    """Merge-base when both sides exist, else the ref as given. Never guesses."""
    try:
        mb = _git(root, "merge-base", base, "HEAD").strip()
        if mb:
            return mb
    except GitError:
        pass
    # verify the ref itself resolves (no --quiet: the error text is the message)
    _git(root, "rev-parse", "--verify", f"{base}^{{commit}}")
    return base


def _parse_unified0(diff: str) -> dict[str, set[int]]:
    """Added new-file line numbers per path from `git diff -U0` output."""
    hunks: dict[str, set[int]] = {}
    cur: str | None = None
    new_ln = 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:]
            hunks.setdefault(cur, set())
            new_ln = 0
        elif line.startswith("@@") and cur is not None:
            try:
                plus = line.split("+", 1)[1].split(" @@", 1)[0]
                new_ln = int(plus.split(",")[0])
            except (ValueError, IndexError):
                cur = None
        elif cur is not None:
            if line.startswith("+") and not line.startswith("+++"):
                hunks[cur].add(new_ln)
                new_ln += 1
            elif line.startswith("-") and not line.startswith("---"):
                continue
            else:
                new_ln += 1
    return hunks


def changed_lines(root: Path, base: str) -> tuple[dict[str, set[int]], set[str]]:
    """Added lines by rel path, plus fully-changed untracked rel paths.

    Covers committed branch changes (merge-base with BASE through HEAD)
    UNION uncommitted worktree changes, so local edits are always gated.
    Raises GitError outside a repo or when the base cannot be resolved.
    """
    _git(root, "rev-parse", "--show-toplevel")
    ref = _resolve_base(root, base)
    hunks = _parse_unified0(_git(root, "diff", "-U0", "--no-color", "--no-ext-diff", ref, "HEAD", "--"))
    worktree = _parse_unified0(_git(root, "diff", "-U0", "--no-color", "--no-ext-diff", "--"))
    for path, lines in worktree.items():
        hunks.setdefault(path, set()).update(lines)
    try:
        untracked = {p for p in _git(root, "ls-files", "--others", "--exclude-standard").splitlines() if p}
    except GitError:
        untracked = set()
    return hunks, untracked


def _diff_symbols(diff: str) -> set[str]:
    """Identifiers (len>=3) on added/removed diff lines, headers excluded."""
    out: set[str] = set()
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") or line.startswith("-"):
            for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", line[1:]):
                if len(tok) >= 3:
                    out.add(tok)
    return out


def changed_symbols(root: Path, base: str) -> set[str]:
    """Symbols touched by branch changes plus uncommitted worktree edits."""
    ref = _resolve_base(root, base)
    out = _diff_symbols(_git(root, "diff", "-U0", "--no-color", "--no-ext-diff", ref, "HEAD", "--"))
    out |= _diff_symbols(_git(root, "diff", "-U0", "--no-color", "--no-ext-diff", "--"))
    return out


def _claim_symbols(finding: Finding) -> set[str]:
    return {t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", finding.claim or "") if len(t) >= 3}


def filter_changed(findings: list[Finding], hunks: dict[str, set[int]], untracked: set[str],
                   symbols: set[str] | frozenset = frozenset()) -> list[Finding]:
    """Keep findings on added/modified lines, in fully-untracked files, or
    naming a diff-touched symbol (rename fallout on untouched lines)."""
    kept: list[Finding] = []
    for f in findings:
        if f.path in untracked:
            kept.append(f)
            continue
        lines = hunks.get(f.path)
        if lines and any(ln in lines for ln in range(f.line, f.end_line + 1)):
            kept.append(f)
            continue
        if symbols and _claim_symbols(f) & set(symbols):
            kept.append(f)
    return kept
