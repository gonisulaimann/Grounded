"""Markdown checkers: the shared CommonMark fence walk, stale-doc-ref
(experimental) and unclosed-fence.
"""
from __future__ import annotations

import re

from ..models import FileFacts, Finding
from ..repo_index import RepoIndex
from ._shared import (
    JS_GLOBALS,
    _GO_STDLIB_PACKAGES,
    _ILLUSTRATIVE,
    _STDLIB_MODULES,
    _dedupe,
    _is_dunder,
    _is_reserved,
    _suggest,
)
from .contracts import (
    _loose_dist,
)
from .phantom import (
    _NODE_BUILTINS,
)


# ---------------------------------------------------------------- stale-doc-ref
# EXPERIMENTAL, opt-in only (see OPT_IN_CHECKERS). Doc examples are dense
# with illustrative, pseudo, and version-skewed code; this checker stays
# narrow on purpose: fenced blocks with an explicit supported language
# tag, calls only, illustrative blocks skipped wholesale.

_DOC_FENCE_LANGS = {
    "python": "python", "py": "python", "pycon": "python", "python3": "python",
    "js": "javascript", "javascript": "javascript", "jsx": "javascript",
    "ts": "javascript", "typescript": "javascript", "tsx": "javascript",
    "go": "go", "golang": "go",
    "c": "c",
}

# CommonMark fenced-code line: up to three spaces of indent, a run of at
# least three backticks or tildes, then the info string.
_FENCE_LINE = re.compile(r"^(?P<indent> {0,3})(?P<fence>`{3,}|~{3,})(?P<info>.*)$")


def _fence_scan(lines: list[str]) -> tuple[list[dict], int]:
    """One CommonMark fenced-code walk, shared by every fence consumer.

    Returns `(blocks, open_at)`: `blocks` holds one record per block —
    `open`/`close` are 1-based fence lines (`close` is None when the block
    runs to EOF), `info` is the raw info string, `char`/`len` the fence run —
    and `open_at` is the opener line of a block still open at EOF (0 if
    none). A block closes only on a run of the same character, at least as
    long, with no info string; a fence-looking line inside a block is
    content, which is exactly where the old per-checker toggles went wrong.
    A backtick fence whose info string contains a backtick is not a fence.
    """
    blocks: list[dict] = []
    open_char = ""
    open_len = 0
    for lineno, raw in enumerate(lines, start=1):
        m = _FENCE_LINE.match(raw)
        if not blocks or blocks[-1]["close"] is not None:
            if not m:
                continue
            fence, info = m.group("fence"), m.group("info")
            if fence[0] == "`" and "`" in info:
                continue
            blocks.append({"open": lineno, "close": None, "info": info,
                           "char": fence[0], "len": len(fence)})
            open_char, open_len = fence[0], len(fence)
            continue
        if m:
            fence, info = m.group("fence"), m.group("info")
            if fence[0] == open_char and len(fence) >= open_len and not info.strip():
                blocks[-1]["close"] = lineno
    open_at = blocks[-1]["open"] if blocks and blocks[-1]["close"] is None else 0
    return blocks, open_at


def _fence_info_word(info: str) -> str:
    """The info string's first word, lowercased (CommonMark's language tag)."""
    parts = info.strip().split()
    return parts[0].lower() if parts else ""
_DOC_CALL = re.compile(r"(?<![A-Za-z0-9_$.])([A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)*)\s*\(")

_DOC_PLACEHOLDER_NAMES = {
    "foo", "bar", "baz", "blah", "qux", "quux", "example", "sample", "demo",
    "placeholder", "something", "anything", "whatever", "todo",
}

_DOC_PLACEHOLDER_RES = [
    re.compile(r"\b(my|your|our|test|testing|dummy|mock|fake)[A-Za-z_]*\b", re.IGNORECASE),
    re.compile(r"<[^<>\n]*>"),  # <placeholder>, <your-key>
]

# Roots that are ambient in JavaScript/TypeScript doc examples, not repo
# symbols. Seen: 400+ such findings on axios docs (Promise.reject,
# document.*, localStorage, .catch chains). Node builtins (_NODE_BUILTINS,
# defined below) are checked alongside at use time. JS_GLOBALS covers
# the rest (Promise, Object, console, test hooks).
_DOC_JS_AMBIENT_ROOTS = frozenset({
    "document", "window", "navigator", "localStorage", "sessionStorage",
    "location", "history", "AbortController", "AbortSignal", "Buffer",
    "URL", "URLSearchParams", "TextEncoder", "TextDecoder", "Blob",
    "File", "FormData", "Headers", "Request", "Response", "crypto",
    "performance", "atob", "btoa", "queueMicrotask", "structuredClone",
    "this", "self", "global", "globalThis", "Symbol", "BigInt", "Map",
    "Set", "WeakMap", "WeakSet", "parseFloat", "parseInt", "isNaN",
    "isFinite", "encodeURI", "decodeURI", "encodeURIComponent",
    "decodeURIComponent", "CustomEvent", "Event", "EventTarget",
    "MessageEvent", "customElements", "CSS", "getComputedStyle",
    "matchMedia", "requestAnimationFrame", "cancelAnimationFrame",
    "IntersectionObserver", "ResizeObserver", "MutationObserver",
    "WebSocket", "DocumentFragment", "Element", "HTMLElement",
    "Node", "NodeList", "DOMException", "BroadcastChannel",
} | set(JS_GLOBALS))

# Bare call names that are JS control syntax, never references
# (`catch (e)` in try/catch examples). Seen across axios docs.
_DOC_JS_CALL_KEYWORDS = frozenset({
    "catch", "if", "for", "while", "switch", "return", "typeof",
    "delete", "void", "in", "of", "do", "else", "try", "finally",
    "throw", "case", "default", "function", "await", "yield",
})


def _doc_fence_blocks(lines: list[str]) -> list[tuple[str, int, int]]:
    """(language, start_lineno_1based, end_lineno_exclusive) for fenced
    code blocks with a supported language tag, per the shared CommonMark
    walk (`_fence_scan`). Unclosed fences are ignored; a shorter inner
    fence is content, so a declared nesting scaffold is one block, not
    three."""
    blocks, _ = _fence_scan(lines)
    out: list[tuple[str, int, int]] = []
    for b in blocks:
        if b["close"] is None:
            continue
        lang = _DOC_FENCE_LANGS.get(_fence_info_word(b["info"]))
        if lang:
            out.append((lang, b["open"] + 1, b["close"]))
    return out


# Documentation-tooling directives that declare an example exempt from
# execution/typechecking (`// @noErrors`, `/// file:` region markers,
# svelte's `---cut---`). The docs themselves state the code is not real
# project surface, so nothing in the block is a claim about the repo.
_DOC_ILLUSTRATIVE_DIRECTIVES = re.compile(
    r"(@noErrors|@errors\b|///\s*file:|---\s*cut\s*---)", re.IGNORECASE)


def _doc_block_is_illustrative(block: list[str]) -> bool:
    text = "\n".join(block)
    if "..." in text or "…" in text:
        return True
    if _DOC_ILLUSTRATIVE_DIRECTIVES.search(text):
        return True
    for line in block:
        s = line.strip()
        if s.startswith("$") or s.startswith("# ") or s.startswith(">>> ") and "Traceback" in text:
            return True
    return False


_DOC_DIFF_MARKER = re.compile(r"\s*[+-]{3}\s*")


def _strip_doc_diff_markers(line: str) -> str:
    """Remove documentation diff/highlight annotations (`+++added+++`,
    `---removed---`). They are presentation markup, not code: left in
    place they corrupt identifier extraction (`function add(+++getA, …)`
    binds nothing) and turn locally bound names into phantom calls.
    Measured: 12 stale-doc-ref lies on svelte's docs, every one of them in
    an annotated block. Applied only when a marker is present, so ordinary
    code lines are passed through untouched.
    """
    if "+++" not in line and "---" not in line:
        return line
    return _DOC_DIFF_MARKER.sub(" ", line)


def _doc_block_known(block: list[str], language: str) -> set[str]:
    """Names bound inside the example itself (definitions, assignments,
    imports, destructuring, decorator roots): using them proves nothing
    about the repo."""
    block = [_strip_doc_diff_markers(ln) for ln in block]
    known: set[str] = set()
    pats: list[str] = []
    if language == "python":
        pats = [
            r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)",
            r"^\s*class\s+([A-Za-z_]\w*)",
            r"^\s*([A-Za-z_]\w*)\s*=(?!=)",
            r"^\s*for\s+([A-Za-z_]\w*)\s+in\b",
            r"^\s*@([A-Za-z_][\w.]*)",
            r"\bas\s+([A-Za-z_]\w*)\b",
        ]
    elif language == "javascript":
        pats = [
            r"(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)",
            r"^\s*function\s+([A-Za-z_$][\w$]*)",
            r"^\s*@([A-Za-z_$][\w$.]*)",
            r"^\s*import\s+([A-Za-z_$][\w$]*)\s+from\b",
            r"^\s*import\s*\*\s*as\s+([A-Za-z_$][\w$]*)",
            # method shorthand: `name(args) {` (class bodies, object
            # literals). Keywords (`if(){`) bind harmlessly: never roots.
            r"^\s*(?:async\s+|static\s+|get\s+|set\s+)?([A-Za-z_$][\w$]*)\s*\([^()]*\)\s*\{",
            # arrow/callback params: (req, res) =>, (prom) =>, x =>
            # (incl. TS-annotated `(req: Config) =>`), function params
            r"\(\s*([A-Za-z_$][\w$]*)\s*[:,)]",
            r",\s*([A-Za-z_$][\w$]*)\s*[:,)]",
            r"(?<![A-Za-z_$0-9])([A-Za-z_$][\w$]*)\s*=>",
        ]
    elif language == "go":
        pats = [
            r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)",
            r"^\s*var\s+([A-Za-z_]\w*)",
            r"(?<![A-Za-z0-9_.])([A-Za-z_]\w*)\s*:=",
        ]
    elif language == "c":
        pats = [
            r"^\s*#\s*define\s+([A-Za-z_]\w*)",
            r"^\s*(?:struct|enum|union)\s+([A-Za-z_]\w*)",
            r"^\s*typedef\b.*?([A-Za-z_]\w*)\s*;",
        ]
    for pat in pats:
        for line in block:
            m = re.search(pat, line)
            if m:
                known.add(m.group(1).split(".")[0])
                if language == "javascript" and "." in m.group(1):
                    known.add(m.group(1).split(".")[-1])
    if language == "javascript":
        # function f(a, b) and (a, b) => params, incl. TS `a: Type`
        for line in block:
            for pm in re.finditer(
                    r"function\s+[A-Za-z_$][\w$]*\s*\(([^()]*)\)"
                    r"|\(([^()]*)\)\s*=>", line):
                params = pm.group(1) if pm.group(1) is not None else pm.group(2)
                for p in (params or "").split(","):
                    pname = re.split(r"[:=]", p.strip(), maxsplit=1)[0].strip().lstrip("...")
                    if re.fullmatch(r"[A-Za-z_$][\w$]*", pname or ""):
                        known.add(pname)
    for line in block:
        m = re.match(r"^\s*(?:from\s+(\S+)\s+import\s+(.+)|import\s+(.+))$", line)
        if m and language in ("python", "javascript"):
            for part in [p for p in (m.group(2), m.group(3)) if p]:
                for name in part.split(","):
                    base = name.strip().split(" as ")[-1].strip().split(".")[0]
                    if re.fullmatch(r"[A-Za-z_]\w*", base or ""):
                        known.add(base)
        if language == "javascript":
            mb = re.match(r"^\s*import\s*\{([^}]*)\}\s*from\b", line)
            if mb:
                for part in mb.group(1).split(","):
                    bits = [b.strip() for b in part.split(" as ")]
                    alias = bits[-1] if len(bits) > 1 else bits[0].split(":")[0].strip()
                    if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", alias or ""):
                        known.add(alias)
        if language == "go":
            m2 = re.match(r"^\s*(?:[A-Za-z_.]+\s+)?\"([\w./-]+)\"\s*$", line)
            if m2:
                known.add(m2.group(1).rstrip("/").split("/")[-1])
    if language == "python":
        # Comprehension and mid-line loop targets (`(x.rstrip() for x
        # in input)`, `{k: v for k, v in d.items()}`): the anchored
        # `for` pattern above only sees line-initial loops. Tuple
        # targets split on commas; anything not a bare identifier is
        # ignored rather than guessed.
        for line in block:
            for fm in re.finditer(r"\bfor\s+([A-Za-z_][\w\s,()]*?)\s+in\b", line):
                for part in fm.group(1).replace("(", " ").replace(")", " ").split(","):
                    name = part.strip()
                    if re.fullmatch(r"[A-Za-z_]\w*", name or ""):
                        known.add(name)
    # Destructured bindings: `const { a, b } = x`, `({ page }) =>`,
    # `[first, ...rest] = list`. Test-fixture params are almost always
    # destructured (`async ({ page }) =>`) and were invisible to the
    # paren-param patterns, so Playwright's page navigation calls
    # reported as repo lies (measured: svelte's Playwright testing guide).
    for line in block:
        for dm in re.finditer(r"(?:\{|\[)([^{}\[\]]*)(?:\}|\])", line):
            for part in dm.group(1).split(","):
                name = re.split(r"[:=]", part.strip(), maxsplit=1)[0].strip().lstrip("...")
                if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", name or ""):
                    known.add(name)
    return known


def _strip_doc_strings(line: str) -> str:
    scrubbed = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", '""', line)
    return re.sub(r"`(?:[^`\\]|\\.)*`", '""', scrubbed)


def check_stale_doc_ref(facts: FileFacts, index: RepoIndex) -> list[Finding]:
    """Fenced code example calls a symbol defined nowhere in the repo.

    Markdown only, and only fenced blocks with an explicit supported
    language tag. Bare fences, console/shell blocks, data formats, and
    any block containing ellipsis are skipped: examples are illustrative
    by default, and only calls with no local binding and no repo-wide
    definition are reported.
    """
    if facts.language != "markdown":
        return []
    findings: list[Finding] = []
    # Tutorial narrative: later blocks build on names bound earlier in
    # the file (const api = ... in block 1, api.post in block 4).
    # Bindings accumulate in file order; shadowing staleness across
    # distant blocks is the documented trade (suppress-only direction).
    file_known: set[str] = set()
    declared: set[str] | None = None
    for lang, start, end in _doc_fence_blocks(facts.lines):
        block = facts.lines[start - 1:end - 1]
        if _doc_block_is_illustrative(block):
            continue
        # Tutorial narrative lives outside the fence ("Here's an example:"
        # directly above the block, with user-supplied helpers like
        # `do_step(step)` inside — measured: rich's README). Only the
        # immediately preceding non-blank line counts: a wider window
        # would let distant prose launder real staleness. (start is the
        # first content line, so the fence itself is start - 1.)
        k = start - 3
        while k >= 0 and not facts.lines[k].strip():
            k -= 1
        if k >= 0 and _ILLUSTRATIVE.search(facts.lines[k]):
            continue
        known = _doc_block_known(block, lang) | file_known
        if lang == "javascript" and declared is None:
            from ..repo_index import _norm_dist as _nd
            # `declared_dependencies` returns None when no manifest exists
            # anywhere above the file. Iterating that None raised inside the
            # checker, and the scanner swallows checker exceptions — so
            # stale-doc-ref was silently disabled on every manifest-less
            # tree (bare docs repo, fixture). Absence of a manifest is an
            # empty declared set, not a crash: report what is provably
            # missing instead of going dark.
            declared = {_nd(x) for x in (index.declared_dependencies(facts.path) or ())}
            loose_declared = {_loose_dist(x) for x in declared}
        for off, line in enumerate(block):
            lineno = start + off
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("$") or s.startswith("//"):
                continue
            if s.startswith("."):
                continue  # continuation chain (.then/.catch): receiver above
            code = _strip_doc_strings(_strip_doc_diff_markers(line))
            # Trailing prose is not code (`"point": "3 4",  # split into
            # ("3", "4")` — the `into (` inside the comment is English,
            # not a call). Strings are already blanked above, so a `#`
            # (python) or `//` (js/go/c) now always opens a comment.
            # A real call can never live behind one: it would not execute.
            if lang == "python":
                code = code.split("#", 1)[0]
            else:
                code = re.split(r"(?<!:)//", code, maxsplit=1)[0]
            for m in _DOC_CALL.finditer(code):
                full = m.group(1)
                base = full.split(".")[-1].lstrip("$")
                full_root = full.split(".")[0].lstrip("$")
                if len(base) < 3 or _is_dunder(base):
                    continue
                if base.lower() in _DOC_PLACEHOLDER_NAMES:
                    continue
                if any(p.search(full) for p in _DOC_PLACEHOLDER_RES):
                    continue
                if _is_reserved(base, lang):
                    continue
                if lang == "javascript" and (
                        full_root in _DOC_JS_AMBIENT_ROOTS
                        or full_root in _NODE_BUILTINS
                        or base in _DOC_JS_CALL_KEYWORDS
                        or full_root in index.root_package_names
                            or (declared is not None and (
                                _nd(full_root) in declared
                                or _loose_dist(full_root) in loose_declared))):
                    continue  # platform/Node/`this`/documented-package roots
                if full_root in known or base in known:
                    continue
                if lang == "python" and full_root in _STDLIB_MODULES:
                    continue
                if lang == "python" and base == "cls":
                    continue  # classmethod convention (`cls(...)` binds the
                    # class in examples). A repo function literally named
                    # `cls` is out of scope: the convention dwarfs it.
                if lang == "go" and full_root in _GO_STDLIB_PACKAGES:
                    continue  # stdlib (fmt.Printf, time.Now): not repo claims
                if index.has_symbol(full) or index.has_symbol(base):
                    continue
                hint = _suggest(base, index)
                findings.append(Finding(
                    path=facts.path, line=lineno, end_line=lineno,
                    checker="stale-doc-ref", severity="lie",
                    title=f"Doc example calls `{full}()` which is not defined in this repo",
                    claim=f"`{full}()`",
                    evidence=f"`{full_root}` is not bound in the example, and no "
                             f"definition of `{base}` was found in {len(index.files)} indexed source files.",
                    fix=f"Update the example to the current name, or remove the call.{hint}",
                    confidence=0.75,
                ))
        file_known |= known
    return _dedupe(findings)


def check_unclosed_fence(facts: FileFacts, index: RepoIndex) -> list[Finding]:
    """Fenced code blocks that never close, judged by CommonMark.

    Markdown only. Two shapes, one cause — the author wrote a block boundary
    the renderer does not honor, so content lands inside a code block:

    * **never closed**: the fence runs to the end of the file, and every line
      after it renders as code;
    * **swallowed boundary**: a closing fence accepts only a run of the same
      character, at least as long, carrying no info string. A line like
      ```` ```console ```` arriving while a block is still open therefore
      cannot open one: it is content, and the block the author thought they
      had opened does not exist.

    Nesting is not a defect, so the one legitimate shape stays silent: an
    enclosing fence that is **longer** than the inner one *and* carries an
    info string of its own — ` `````markdown ` around ` ```python `, where the
    outer fence declares itself as a nesting scaffold. Everything else is
    reported, because a bare enclosing fence declares nothing, so a block
    header inside it cannot be nesting: the two shapes measured in the wild
    are a repeated header of the same length (a missing close) and a bare
    4-backtick line that the author read as a closer while the renderer read it
    as an opener. A bare inner fence stays silent either way — inside a block
    that is the illustrated closer of a nested example, which is exactly what
    a nesting scaffold is for.

    This is also the shape that disarms the doc checkers. `stale-doc-ref` and
    `stale-cli-ref` used to track fences with a line-by-line toggle that
    flipped on every fence-looking line, so a swallowed boundary inverted
    their view of every line after it — and a fence whose info string was
    not a bare tag (`` ```bash title="x" ``, an indented fence) was ignored
    entirely, leaving blocks analyzed as prose. Both now share the
    CommonMark walk above. Measured 2026-09-22: one missing close in this
    repository's `README.md` made two `stale-cli-ref` corpus plants report
    as phantom recall misses until the fence was fixed.

    Verified against GitHub's own renderer (`POST /markdown`, `mode=gfm`) on
    that README: 24 code blocks before the fix and 25 after, with the
    paragraphs at 220-228 rendered as code before and as prose after.
    """
    if facts.language != "markdown":
        return []
    findings: list[Finding] = []
    lines = facts.lines
    blocks, open_at = _fence_scan(lines)
    for b in blocks:
        last = b["close"] - 1 if b["close"] is not None else len(lines)
        for lineno in range(b["open"] + 1, last + 1):
            m = _FENCE_LINE.match(lines[lineno - 1])
            if not m:
                continue
            fence, info = m.group("fence"), m.group("info")
            if not info.strip():
                continue  # bare inner fence: the illustrated closer of a nested example
            if b["info"].strip() and (b["len"] > len(fence) or fence[0] != b["char"]):
                # Declared nesting scaffold: ````markdown around ```python,
                # or a different fence character (a `~~~` line can never
                # close a backtick block; seen: prettier's changelog showing
                # `~~~~js` inside ````jsx).
                continue
            findings.append(Finding(
                path=facts.path, line=lineno, end_line=lineno,
                checker="unclosed-fence", severity="lie",
                title=f"Code fence is swallowed by the block opened at line {b['open']}",
                claim=lines[lineno - 1].strip()[:60],
                evidence=f"the block opened at line {b['open']} is closed only by a run of "
                         f"at least {b['len']} `{b['char']}` with no info string, so this "
                         f"line is content inside it — and so is everything after it until "
                         f"the next {b['len']}-`{b['char']}` fence on its own line",
                fix=f"Close the block opened at line {b['open']} before this fence.",
                confidence=0.9,
            ))
    if open_at:
        findings.append(Finding(
            path=facts.path, line=open_at, end_line=len(lines),
            checker="unclosed-fence", severity="lie",
            title="Code fence is never closed",
            claim=lines[open_at - 1].strip()[:60],
            evidence=f"this fence has no closer, so the {len(lines) - open_at} "
                     f"line(s) after it render as one code block to the end of the file",
            fix="Add the closing fence.",
            confidence=0.95,
        ))
    return _dedupe(findings)
