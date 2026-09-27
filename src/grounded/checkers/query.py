"""check_text: ask the repository whether a stated name or path is real.

A query primitive, not a checker: it takes arbitrary prose (an agent's
plan, a doc paragraph, a rename proposal) and resolves every
code-shaped claim in it against the index, with no file context. No
verdicts about files, no severities, no gates — just known/unknown per
claim with evidence. Agents call this *before* acting (PreToolUse,
planning) instead of discovering a lie after writing it.

Resolution reuses the checker rules (same regexes, same reserved and
placeholder lists), minus everything that needs a claiming file
(imports, same-file use, comment context). Unknown means "no definition
and no file in this snapshot", stated plainly.
"""
from __future__ import annotations

import re

from ..repo_index import RepoIndex
from ._shared import (
    PLACEHOLDER_PATH_HINTS,
    _BACKTICK_SYMBOL,
    _FILE_REF,
    _METASYNTACTIC_CALLS,
    _SYMBOL_CALL,
    _is_reserved,
    _suggest,
)
from .files import _in_repo_scope


# Ubiquitous tool/platform names: never repo-defined (and when a repo
# does define one, the index check above already won). Query-only:
# the checkers keep judging these strictly, because a comment claiming
# `docker()` deserves the full absence proof, not a shrug.
_TOOL_NAMES = frozenset({
    "pip", "npm", "yarn", "pnpm", "brew", "apt", "yum", "dnf", "apk",
    "git", "svn", "hg", "docker", "podman", "kubectl", "helm",
    "curl", "wget", "ssh", "scp", "rsync", "make", "cmake", "gcc",
    "clang", "python", "node", "deno", "bun", "ruby", "cargo",
    "java", "javac", "mvn", "gradle", "dotnet", "php",
    "composer", "terraform", "ansible", "vim", "nano", "emacs",
    "tmux", "screen", "bash", "zsh", "fish", "awk", "sed", "grep",
    "jq", "ffmpeg", "pandoc", "gcloud", "az", "aws",
})


def _clean_call(raw: str) -> tuple[str, str] | None:
    name = raw.strip(".,:;!?")
    is_call = name.endswith("()")
    if is_call:
        name = name[:-2]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*",
                         name or ""):
        return None
    base = name.split(".")[-1]
    return name, base


def check_text_claims(text: str, index: RepoIndex,
                      params: frozenset[str] | None = None) -> list[dict]:
    """[{claim, kind, verdict, detail}] for code-shaped claims in text.

    kind is "symbol" or "file"; verdict is "known" or "unknown".
    Reserved words, placeholders, tool names and short names are
    skipped silently (never claims). Dotted file paths are judged only
    in repo scope, like stale-file-ref.

    `params` (function-parameter names across the tree) answer a third
    question the index cannot: names that exist but are not definitions
    (`log_locals` is `Console.log`'s parameter, not a function). They
    report known with the qualifier, so an agent asking "is X real?"
    gets the truth instead of a miss. Case works the same way: a
    unique case-insensitive hit reports known with the actual casing
    noted. Both are query-only leniency — the checkers stay strict,
    because in code `spinner` and `Spinner` are different names.
    """
    out: list[dict] = []
    seen_set: set[tuple[str, str]] = set()
    params = params or frozenset()

    def add(claim: str, kind: str, verdict: str, detail: str) -> None:
        key = (kind, claim)
        if key not in seen_set:
            seen_set.add(key)
            out.append({"claim": claim, "kind": kind,
                        "verdict": verdict, "detail": detail})

    def judge(display: str, name: str, base: str) -> None:
        if index.has_symbol(name) or index.has_symbol(base):
            add(display, "symbol", "known",
                f"`{base}` is defined in this repo.")
            return
        if base.lower() in _TOOL_NAMES:
            return  # ubiquitous external tool, never a repo claim
        if base in params or name.split(".")[0] in params:
            add(display, "symbol", "known",
                f"`{base}` is a function parameter in this repo "
                f"(not a standalone definition).")
            return
        cased = index.lower_map.get(base.lower(), set())
        if len(cased) == 1:
            (actual,) = cased
            add(display, "symbol", "known",
                f"no `{base}`, but `{actual}` is defined "
                f"(case differs).")
            return
        hint = _suggest(base, index).strip()
        detail = (f"no definition of `{base}` in {len(index.files)} "
                  f"indexed source files."
                  + (f" {hint}" if hint else ""))
        add(display, "symbol", "unknown", detail)

    for m in _BACKTICK_SYMBOL.finditer(text):
        parsed = _clean_call(m.group(1))
        if parsed is None:
            continue
        name, base = parsed
        if len(base) < 3 or "xxx" in base.lower():
            continue
        if base.lower() in _METASYNTACTIC_CALLS:
            continue
        if _is_reserved(base, "python"):
            continue
        judge(f"`{m.group(1)}`", name, base)
    for m in _SYMBOL_CALL.finditer(text):
        full = m.group(1)
        base = full.split(".")[-1]
        if len(base) < 3 or "xxx" in base.lower():
            continue
        if base.lower() in _METASYNTACTIC_CALLS:
            continue
        if _is_reserved(base, "python"):
            continue
        if f"`{full}()`" in text or f"`{base}()`" in text:
            continue  # already judged via the backticked form
        judge(f"{full}()", full, base)
    for m in _FILE_REF.finditer(text):
        ref = m.group(1)
        segs = [s.lower() for s in re.split(r"[/.]", ref)]
        if any(h in segs for h in PLACEHOLDER_PATH_HINTS):
            continue
        if "..." in ref or "…" in ref or "://" in ref:
            continue
        if not _in_repo_scope(ref, index):
            continue
        if index.has_exact_path(ref):
            add(ref, "file", "known", f"`{ref}` exists in this repo.")
        else:
            same = index.same_named(ref)
            detail = "no such file exists in this repo."
            if same:
                shown = ", ".join(f"`{s}`" for s in same[:3])
                detail += f" Same-named files exist: {shown}."
            add(ref, "file", "unknown", detail)
    return out
