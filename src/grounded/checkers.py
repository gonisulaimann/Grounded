"""Deterministic reference checks for code comments, v2.

Not covered here, by design: docstring contracts (params, returns, raises)
and commented-out code. Use darglint or pydoclint (Python),
eslint-plugin-jsdoc (JS/TS), and Ruff ERA001 for those; each was compared
head-to-head and is more precise on its surface (see REMOVED_CHECKERS).

Covered here (no exact incumbent found):
- stale-symbol-ref: comment names a call that resolves nowhere
  (not defined, imported, or used in-file; not stdlib/builtin/keyword).
- stale-file-ref: comment claims a path inside this repo's tree that
  does not exist (namespace- and placeholder-aware).
- number-drift: magic number in a comment disagrees with adjacent code.
- fragile-anchor: line anchors and untracked workaround markers.
- stale-doc-ref (EXPERIMENTAL, opt-in only): fenced code example in
  Markdown calls a symbol defined nowhere in the repo. Off by default;
  enable explicitly. Precision is still being measured (see docs).

A finding is emitted only with positive evidence of contradiction.
"""
from __future__ import annotations

import ast
import difflib
import json
import posixpath
import re
import sys

from .models import Comment, FileFacts, Finding
from .repo_index import RepoIndex, _norm_dist

# Directory names the scanner never walks (see config.DEFAULT_IGNORE_DIRS
# plus the always-skipped cache dirs). A relative import pointing under
# one of these has targets the snapshot cannot see: never a missing-module
# verdict (see _js_target_in_ignored_dir).
IGNORED_DIR_NAMES = frozenset({
    ".git", "__pycache__", "node_modules", ".venv", "venv", ".tox",
    "dist", "build", ".next", "out", "coverage", ".nyc_output",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", "vendor", "third_party",
})

# ---------------------------------------------------------------- shared

PYTHON_BUILTINS = {
    "print", "len", "range", "str", "int", "float", "bool", "list", "dict", "set",
    "tuple", "super", "isinstance", "issubclass", "hasattr", "getattr", "setattr",
    "open", "enumerate", "zip", "map", "filter", "sorted", "reversed", "sum",
    "min", "max", "abs", "round", "pow", "divmod", "repr", "type", "id",
    "input", "iter", "next", "callable", "classmethod", "staticmethod",
    "property", "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "AttributeError", "RuntimeError", "NotImplementedError", "StopIteration",
    "AssertionError", "IOError", "OSError", "print_function",
    "object", "file",
    # Python 2 historical builtins still referenced in old comments/docs
    "execfile", "unicode", "long", "xrange", "raw_input", "basestring",
    "reduce", "apply", "intern", "coerce",
}

JS_GLOBALS = {
    "console", "log", "warn", "error", "info", "debug", "assert",
    "fetch", "setTimeout", "setInterval", "clearTimeout", "clearInterval",
    "Promise", "Array", "Object", "String", "Number", "Boolean", "JSON",
    "Math", "Date", "RegExp", "Error", "TypeError", "RangeError",
    "require", "module", "exports", "process", "setImmediate",
    "describe", "it", "test", "expect", "beforeEach", "afterEach",
    "useState", "useEffect", "useRef", "useMemo", "useCallback",
}

# Language keywords must never be mistaken for symbol references,
# even when backticked in prose ("without `function` keyword").
KEYWORDS = {
    "function", "return", "if", "else", "elif", "for", "while", "class",
    "const", "let", "var", "import", "export", "from", "def", "pass",
    "break", "continue", "try", "except", "finally", "with", "as",
    "await", "async", "yield", "new", "this", "self", "true", "false",
    "none", "null", "undefined", "type", "interface", "extends",
}

COMMON_ENGLISH_FUNCWORDS = {
    "example", "todo", "fixme", "note", "warning", "error", "info",
    "something", "nothing", "anything", "everything",
}

GO_BUILTINS = {
    "append", "cap", "clear", "close", "complex", "copy", "delete",
    "imag", "len", "make", "max", "min", "new", "panic", "print",
    "println", "real", "recover", "error", "string", "int", "int8",
    "int16", "int32", "int64", "uint", "uint8", "uint16", "uint32",
    "uint64", "uintptr", "float32", "float64", "complex64", "complex128",
    "bool", "byte", "rune", "any", "comparable", "true", "false", "nil",
    "iota",
}

# Go standard-library package leaf names: doc examples calling
# fmt.Printf or time.Now reference the toolchain, not the repo.
# (Seen: gin docs.) Checked on the call root only.
_GO_STDLIB_PACKAGES = frozenset({
    "fmt", "log", "time", "os", "io", "bytes", "strings", "errors",
    "context", "sync", "sort", "strconv", "regexp", "path", "filepath",
    "math", "net", "http", "url", "json", "template", "sql", "rpc",
    "crypto", "tls", "encoding", "base64", "hex", "mime", "mail",
    "reflect", "runtime", "atomic", "maps", "slices", "cmp", "hash",
    "bufio", "exec", "signal", "unicode", "utf8", "html", "image",
    "compress", "archive", "container", "heap", "list", "ring",
    "testing", "httptest", "plugin", "debug", "expvar", "flag",
    "syscall", "unsafe",
})

GO_KEYWORDS = {
    "break", "case", "chan", "const", "continue", "default", "defer",
    "else", "fallthrough", "for", "func", "go", "goto", "if", "import",
    "interface", "map", "package", "range", "return", "select", "struct",
    "switch", "type", "var",
}

# C standard library functions commonly named in comments without includes
# (printf, malloc, ...). Anything else resolves via #include maps or defs.
C_STDLIB_FUNCS = {
    "printf", "fprintf", "sprintf", "snprintf", "scanf", "puts", "putchar",
    "getchar", "malloc", "calloc", "realloc", "free", "memcpy", "memmove",
    "memset", "memcmp", "strlen", "strcpy", "strncpy", "strcmp", "strncmp",
    "strcat", "strchr", "strstr", "strtok", "atoi", "exit", "abort", "qsort",
    "fopen", "fclose", "fread", "fwrite", "fseek", "ftell", "feof", "perror",
    "assert", "sizeof",
    "isspace", "isdigit", "isalpha", "isalnum", "isxdigit", "isprint",
    "ispunct", "iscntrl", "isgraph", "islower", "isupper", "toupper", "tolower",
    "strpbrk", "strspn", "strcspn", "strerror", "strdup", "strndup",
    "bsearch", "wcspbrk", "wcslen", "va_start", "va_end", "va_arg",
    "offsetof",
    # POSIX / sockets / pthreads, the most-referenced C APIs in comments
    "fork", "execve", "execvp", "waitpid", "pipe", "dup", "dup2", "close",
    "read", "write", "open", "lseek", "fsync", "stat", "fstat", "unlink",
    "link", "symlink", "readlink", "truncate", "ftruncate", "chmod", "chown",
    "getpid", "getuid", "sleep", "usleep", "nanosleep", "mmap", "munmap",
    "socket", "bind", "listen", "accept", "connect", "send", "recv",
    "sendto", "recvfrom", "setsockopt", "getsockopt", "getsockname",
    "getpeername", "htonl", "htons", "ntohl", "ntohs", "inet_ntoa",
    "inet_pton", "getaddrinfo", "freeaddrinfo", "select", "poll", "epoll",
    "pthread_create", "pthread_join", "pthread_mutex_lock",
    "pthread_mutex_unlock", "dlopen", "dlsym", "rand", "srand", "time",
    "gettimeofday", "localtime", "gmtime", "signal", "kill", "madvise",
    "strtol", "strtoul", "strtoll", "strtoull", "strtod", "strtof",
    "atoll", "atof",
}

C_KEYWORDS = {
    "auto", "break", "case", "char", "const", "continue", "default", "do",
    "double", "else", "enum", "extern", "float", "for", "goto", "if",
    "inline", "int", "long", "register", "restrict", "return", "short",
    "signed", "sizeof", "static", "struct", "switch", "typedef", "union",
    "unsigned", "void", "volatile", "while", "define", "include", "ifdef",
    "ifndef", "endif", "pragma",
}


def _is_reserved(base: str, language: str) -> bool:
    """Builtins, keywords, and prose words: never symbol references."""
    if base in PYTHON_BUILTINS or base in JS_GLOBALS or base in KEYWORDS:
        return True
    if base.lower() in COMMON_ENGLISH_FUNCWORDS:
        return True
    if base.lower() in KEYWORDS:
        return True
    if base.lower() in {"true", "false", "none", "null", "undefined", "nil"}:
        return True
    if language == "go" and (base in GO_BUILTINS or base in GO_KEYWORDS):
        return True
    if language == "c" and (base in C_STDLIB_FUNCS or base in C_KEYWORDS):
        return True
    return False

PLACEHOLDER_PATH_HINTS = {"example", "examples", "path", "to", "foo", "bar", "baz",
    "placeholder", "sample", "demo", "<", ">", "...", "xxx",
    "myapp", "mysite", "app_label", "yourproject", "yourdomain", "sitename"}

REFERENCE_VERBS = re.compile(
    r"\b(calls?|invokes?|uses?|using|see|refers?\s+to|delegates?\s+to|wraps?|handled?\s+by|defined\s+in|implemented\s+in)\b",
    re.IGNORECASE,
)

_SYMBOL_CALL = re.compile(r"(?<![A-Za-z0-9_$.])([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\(\)")
_BACKTICK_SYMBOL = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*(?:\(\))?)`")
# v2: explicit alphabetic extension list. A generic `[A-Za-z0-9]{1,5}` class
# matched protocol versions (`HTTP/1.1`) and version strings as "files".
_FILE_EXT = (r"py|pyi|js|jsx|ts|tsx|mjs|cjs|mts|cts|json|yaml|yml|toml|md|rst|"
             r"txt|css|html|htm|sh|c|h|cpp|hpp|cc|go|rs|java|po|pot|sql|xml|"
             r"ini|cfg|vue|svelte|rb|php|swift|kt|graphql|gql|proto")
_FILE_REF = re.compile(
    r"(?<![A-Za-z0-9_/:])"
    r"([A-Za-z0-9_][A-Za-z0-9_\-\.]*(?:/[A-Za-z0-9_\-\.]+)+\.(" + _FILE_EXT + r"))"
    r"(?![A-Za-z0-9_])")
_LINE_ANCHOR = re.compile(r"\b[Ll]ines?\s+\d+(?:\s*[-–:]\s*\d+)?\b")
_SEE_ABOVE_BELOW = re.compile(r"\bsee\s+(above|below)\b", re.IGNORECASE)
_TEMPORAL = re.compile(r"\b(temporarily|temporary\s+fix|for\s+now|currently|at\s+the\s+moment)\b", re.IGNORECASE)
_HACK_UPPER = re.compile(r"\b(HACK|XXX|FIXME)\b")  # case-sensitive by convention; "Xxx" prose must not match
_WORKAROUND_WORD = re.compile(r"\b(workaround|work-around|kludge|magic\s+number)\b", re.IGNORECASE)
_TICKET = re.compile(r"(#[0-9]{1,6}\b|https?://\S+|GH-\d+|JIRA-[A-Z]+-\d+|[A-Z]{2,}-\d+)", re.IGNORECASE)

# v2: negated/alternative contexts discuss external systems, not repo
# existence ("Don't use RANDOM()", "byref() calls are not needed",
# "VALUES() is not supported"). Narrow on purpose (necessity/support
# negations only): a generic "does not <verb>" ("does not cache") must
# NOT suppress, or real rename-refs die with it.
_NEGATED = re.compile(
    r"\b(don'?t|doesn'?t\s+(?:use|need|support|exist|matter)|isn'?t|"
    r"aren'?t|wasn'?t|weren'?t|not\s+(?:needed|supported|required|used|"
    r"necessary|available)|never|no longer|no\s+calls?\b|instead|avoid|avoids|"
    r"unsupported)\b", re.IGNORECASE)

# v2: illustrative-example markers. Docs constantly invent paths
# ("For example ... ``django/templatetags/news/photos.py``"); a file ref
# within ~120 chars after such a marker is an example, not a claim.
# Dotted abbreviations need lookarounds, not \b: after "e.g." comes a
# space (non-word), so a trailing \b never matches in real prose.
_ILLUSTRATIVE = re.compile(
    r"\b(for example|for instance|such as|suppose|imagine|example)\b"
    r"|(?<!\w)e\.g\.(?!\w)|(?<!\w)i\.e\.(?!\w)",
    re.IGNORECASE)


def _workaround_match(text: str):
    m = _HACK_UPPER.search(text)
    if m:
        return m
    return _WORKAROUND_WORD.search(text)


def _strip_strings(text: str) -> str:
    return re.sub(r"(['\"`]).*?\1", r"\1\1", text)


# v2: import- and scope-awareness for stale-symbol-ref.
_STDLIB_MODULES = set(getattr(sys, "stdlib_module_names", ())) | {
    "os", "sys", "re", "json", "tarfile", "http", "urllib", "pathlib",
    "typing", "collections", "functools", "itertools", "io", "ast",
}

# Ubiquitous implicit dunders: never worth flagging.
_DUNDER_OK = {
    "__name__", "__main__", "__doc__", "__dict__", "__class__",
    "__module__", "__slots__", "__weakref__",
}


def _is_dunder(name: str) -> bool:
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def _stdlib_class(root: str) -> bool:
    """Capitalized root whose lowercase is a stdlib module (Tarfile against
    tarfile; repo definitions still take precedence via the index check)."""
    return bool(root) and root[0].isupper() and root.lower() in _STDLIB_MODULES


# Sphinx field-list lines and JSDoc tag lines are *contracts* (the
# incumbents' surface: darglint / eslint-plugin-jsdoc), not references.
# Scanning them for symbol refs yields field-name FPs (:param cookiejar:).
_SPHINX_FIELD_LINE = re.compile(
    r"^\s*:(param|arg|argument|type|return|rtype|returns|raises|except|"
    r"var|ivar|cvar|meta|keyword|key)\b")
_JSDOC_TAG_LINE = re.compile(
    r"^\s*\*?\s*@?(param|arg|argument|returns?|throws?|exception|type|"
    r"typedef|property|prop|template|yields?)\b")


def _scrub_docstring(doc: str, language: str) -> str:
    # Go doc comments carry no contract tags. C uses Doxygen, whose
    # @param/@return lines are contracts like JSDoc.
    if not doc or language == "go":
        return doc
    pat = _JSDOC_TAG_LINE if language in ("javascript", "c") else _SPHINX_FIELD_LINE
    kept = [ln for ln in doc.splitlines() if not pat.match(ln)]
    return "\n".join(kept)


def _comment_lines(facts: FileFacts) -> dict[int, str]:
    """Map of line number to comment text (multi-line blocks expanded)."""
    by_line: dict[int, str] = {}
    for c in facts.comments:
        for ln in range(c.line, c.end_line + 1):
            by_line.setdefault(ln, c.text)
    return by_line


def _nearby_ticket(facts: FileFacts, line: int, end_line: int, by_line: dict[int, str] | None = None) -> bool:
    """Ticket links often sit next to the marker ("See <url>" below a
    "Temporarily ..." comment; "#10355" beside a history note). Markers
    with a ticket within two lines point outside on purpose."""
    if by_line is None:
        by_line = _comment_lines(facts)
    for ln in range(line - 2, end_line + 3):
        if _TICKET.search(by_line.get(ln, "")):
            return True
    return False


def _code_text(facts: FileFacts) -> str:
    """File text minus full-line comments: cheap same-file identifier proxy.

    If a name appears in code (param, local, attribute, import), a comment
    mentioning it is not a dangling reference. Approximate but sound in one
    direction: it only ever suppresses, and trailing-code lines are kept.

    A block-comment *line* may still carry real code after the comment
    closes on the same line (`/** @param {T} x */ (x) => use(x)`).
    Blanking such a line hid the use and produced phantom absences
    (measured: svelte's `html.js` `reg_exp_entity`, called two lines below
    its definition behind an inline `/** @param ... */`, reported as a
    ghost export). The comment span is stripped, the code after it stays.
    """
    skip: set[int] = set()
    keep: dict[int, str] = {}
    for c in facts.comments:
        for ln in range(c.line, c.end_line + 1):
            if 1 <= ln <= len(facts.lines):
                line = facts.lines[ln - 1]
                s = line.strip()
                if facts.language == "python":
                    if s.startswith("#"):
                        skip.add(ln)
                else:
                    if s.startswith("//"):
                        skip.add(ln)
                    elif s.startswith(("/*", "*", "*/")):
                        rest = line.split("*/", 1)[1] if "*/" in line else ""
                        if rest.strip():
                            keep[ln] = rest
                        else:
                            skip.add(ln)
    out: list[str] = []
    for i, ln in enumerate(facts.lines, start=1):
        if i not in skip:
            out.append(keep.get(i, ln))
    return "\n".join(out)


def _appears_in_code(name: str, code: str) -> bool:
    return re.search(r"\b" + re.escape(name) + r"\b", code) is not None


def _appears_as_suffix(base: str, code: str, minimum: int = 6) -> bool:
    """A longer code identifier ends with the claimed name (`je_` wrappers,
    `XXH3_64bits_withSecret` variant families). Such comments name a member
    of a family, not a standalone function. Suffix-only on purpose: prefix
    extensions (`foo` -> `foo_v2`) are the classic rename shape and must
    still fire."""
    if len(base) < minimum:
        return False
    for tok in set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", code)):
        if len(tok) > len(base) and tok.endswith(base):
            return True
    return False


def _suggest(base: str, index: RepoIndex, limit: int = 2) -> str:
    try:
        near = difflib.get_close_matches(
            base, sorted(index.all_symbols), n=limit, cutoff=0.8)
    except Exception:
        near = []
    if near:
        return " Did you mean: " + ", ".join(f"`{n}`" + "()" for n in near)
    return ""


# ---------------------------------------------------------------- suppression machinery

def _looks_like_code_block(body: str, language: str) -> tuple[bool, float]:
    """Kept as suppression machinery: commented-out code blocks must not
    spawn cascading symbol/file/number findings (their contents are code,
    not references). No longer emits findings itself (see REMOVED_CHECKERS:
    use Ruff ERA001)."""
    s = body.strip()
    if not s:
        return False, 0.0
    if language == "python":
        first = s.splitlines()[0].strip()
        if re.match(r"^(type|noqa|pylint|flake8|ruff|pragma|fmt|isort|coding|eslint|ts-|@)", first, re.IGNORECASE):
            return False, 0.0
        if re.match(r"^#?\s*(noqa|type:\s*ignore|pylint:\s*disable|eslint-disable)", s, re.IGNORECASE):
            return False, 0.0
        try:
            tree = ast.parse(s)
        except (SyntaxError, ValueError):
            return False, 0.0
        code_nodes = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import,
                      ast.ImportFrom, ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Return,
                      ast.If, ast.For, ast.While, ast.With, ast.Try, ast.Raise, ast.Assert,
                      ast.Expr)
        if not any(isinstance(n, code_nodes) for n in ast.walk(tree)):
            return False, 0.0
        code_tokens = len(re.findall(r"[(){}\[\];=:.]|^(def|class|import|from|return|if|for|while|with|try|raise|assert)\b", s, re.MULTILINE))
        words = len(re.findall(r"[A-Za-z]+", s))
        density = code_tokens / max(1, words)
        if density < 0.15 and len(s.splitlines()) < 4:
            return False, density
        return True, min(0.95, 0.6 + density)
    else:
        # Suppression-only use (v2): the bar here is intentionally high. This
        # gate only decides whether a comment block reads as code (which
        # suppresses reference claims). Over-firing hides real findings;
        # under-firing only risks extra claims. Prose with a couple of
        # keywords or parens must not qualify.
        if re.match(r"^(eslint|ts-ignore|ts-expect|@|prettier|stylelint)", s.strip(), re.IGNORECASE):
            return False, 0.0
        punct = len(re.findall(r"[;{}()\[\]=><&|]", s))
        chars = max(1, len(re.sub(r"\s", "", s)))
        density = punct / chars
        keywords = len(re.findall(r"\b(const|let|var|function|return|import|export|if|for|while|class|new|await|require)\b", s))
        if density >= 0.12 or (keywords >= 3 and density >= 0.05):
            return True, min(0.9, 0.55 + density + 0.05 * keywords)
        return False, density


def _commented_code_line_set(facts: FileFacts) -> set[int]:
    """Lines belonging to commented-out code blocks (suppression only)."""
    covered: set[int] = set()
    comments = facts.comments
    groups: list[list[Comment]] = []
    cur: list[Comment] = []
    prev_end = -10
    for c in comments:
        if c.is_block:
            if cur:
                groups.append(cur)
                cur = []
            if c.end_line - c.line + 1 >= 3 and "@param" not in c.text:
                ok, _ = _looks_like_code_block(c.text, facts.language)
                if ok and not re.search(r"copyright|license|spdx|warranty", c.text, re.IGNORECASE):
                    for ln in range(c.line, c.end_line + 1):
                        covered.add(ln)
            prev_end = c.end_line
            continue
        if c.line == prev_end + 1:
            cur.append(c)
        else:
            if cur:
                groups.append(cur)
            cur = [c]
        prev_end = c.end_line
    if cur:
        groups.append(cur)
    for g in groups:
        if len(g) < 3:
            continue
        body = "\n".join(c.text for c in g)
        body_lines = [ln for ln in body.splitlines() if not re.fullmatch(r"\s*[=#\-*_~]{4,}\s*", ln)]
        if len(body_lines) < 2:
            continue
        ok, _ = _looks_like_code_block("\n".join(body_lines), facts.language)
        if ok:
            for c in g:
                covered.add(c.line)
    return covered


# ---------------------------------------------------------------- checkers

def check_stale_symbol(facts: FileFacts, index: RepoIndex) -> list[Finding]:
    """Backticked calls, verb-anchored bare calls, and dunder typos only.

    Plain backticked words are usually Sphinx fields, attributes, options,
    or prose, so they are skipped (dunders excepted: a dunder with no
    definition anywhere is almost always a typo). Imported names, stdlib
    names, and names used in the file's own code are skipped: they resolve
    outside snapshot analysis. Bare calls need reference-verb context.
    """
    findings: list[Finding] = []
    dead = _commented_code_line_set(facts)
    code = _code_text(facts)
    texts: list[tuple[str, int, int]] = []  # (text, line, end)
    for c in facts.comments:
        if c.line in dead and c.end_line in dead:
            continue  # commented-out code block, not a reference
        texts.append((c.text, c.line, c.end_line))
    for f in facts.functions:
        if f.docstring:
            scrubbed = _scrub_docstring(f.docstring, facts.language)
            if scrubbed.strip():
                texts.append((scrubbed, f.docstring_lineno or f.lineno, f.docstring_lineno or f.lineno))
    for text, line, end in texts:
        if not text.strip():
            continue
        # backticked symbols
        for m in _BACKTICK_SYMBOL.finditer(text):
            raw = m.group(1)
            name = raw.strip(".,:;!?")
            base = name.split(".")[-1]
            is_call = name.endswith("()")
            if is_call:
                name = name[:-2]
                base = base[:-2] if base.endswith("()") else base
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", name or ""):
                continue
            if len(base) < 3:
                continue
            if "xxx" in base.lower():
                continue  # Xxx placeholder convention (protobuf)
            if _is_reserved(base, facts.language):
                continue
            # v2: non-call backticked names are fields/attrs/prose, except
            # dunders: dunder names are almost always real protocol
            # methods, so a dunder with no definition anywhere is worth
            # flagging (typo class).
            if not is_call:
                if not _is_dunder(base) or base in _DUNDER_OK:
                    continue
            # Negated claims assert absence ("no call to X", "don't use
            # X"): flagging them contradicts a true statement. Same
            # window as the bare-call branch.
            window = text[max(0, m.start() - 60):m.end() + 40]
            if _NEGATED.search(window):
                continue
            root = name.split(".")[0]
            if root in facts.imports:
                continue  # resolves via import; outside snapshot analysis
            if facts.language == "python" and root in _STDLIB_MODULES:
                continue
            if facts.language == "python" and _stdlib_class(root):
                continue  # stdlib class form (Tarfile -> tarfile)
            if _appears_in_code(root, code) or (root != base and _appears_in_code(base, code)):
                continue  # param, local, attribute, or same-file identifier
            if _appears_as_suffix(base, code):
                continue  # variant-family member (je_ wrappers, _withSecret)
            if index.has_symbol(name) or index.has_symbol(base):
                continue
            if "." in name and not is_call:
                continue  # dotted non-call that survived: path/module prose
            hint = _suggest(base, index)
            findings.append(Finding(
                path=facts.path, line=line, end_line=end,
                checker="stale-symbol-ref", severity="lie",
                title=f"Comment references `{name}` which is not defined here",
                claim=f"`{raw}`",
                evidence=f"`{root}` is not defined, imported, or used in this file, "
                         f"and no definition of `{base}` was found in {len(index.files)} indexed source files.",
                fix=f"Update the comment to the current name, or remove the reference.{hint}",
                confidence=0.9 if is_call else 0.85,
            ))
        # bare calls: reference-verb context required (v1's distinctive-only
        # tier produced drift noise on test locals and option names).
        for m in _SYMBOL_CALL.finditer(text):
            full = m.group(1)
            base = full.split(".")[-1]
            if len(base) < 3:
                continue
            if "xxx" in base.lower():
                continue  # Xxx placeholder convention (protobuf)
            if _is_reserved(base, facts.language):
                continue
            if f"`{full}()`" in text or f"`{base}()`" in text:
                continue
            window = text[max(0, m.start() - 60):m.end() + 40]
            has_verb = bool(REFERENCE_VERBS.search(window)) or bool(re.search(r"@deprecated|@see|see\s+`?", window, re.IGNORECASE))
            if not has_verb:
                continue
            # v2: bare claims anchored to a ticket/URL point outside the
            # snapshot on purpose (history, upstream tickets). Backticked
            # claims are still checked.
            if _TICKET.search(text):
                continue
            # v2: acronym-led bare calls are SQL/C/system APIs (VALUES(),
            # JSON_TYPE(), BOX2D_left()), never repo functions in prose.
            # Backticked calls are exempt (explicit code formatting).
            if re.match(r"[A-Z]{2,}", base):
                continue
            # v2: negated contexts discuss other systems, not repo existence.
            if _NEGATED.search(window):
                continue
            root = full.split(".")[0]
            if root in facts.imports:
                continue
            if facts.language == "python" and root in _STDLIB_MODULES:
                continue
            if facts.language == "python" and _stdlib_class(root):
                continue
            if _appears_in_code(root, code) or (root != base and _appears_in_code(base, code)):
                continue
            if _appears_as_suffix(base, code, minimum=4):
                continue
            if index.has_symbol(full) or index.has_symbol(base):
                continue
            hint = _suggest(base, index)
            findings.append(Finding(
                path=facts.path, line=line, end_line=end,
                checker="stale-symbol-ref", severity="lie",
                title=f"Comment references {full}() which is not defined here",
                claim=f"{full}()",
                evidence=f"`{root}` is not defined, imported, or used in this file, "
                         f"and no definition of `{base}` was found in indexed source files.",
                fix=f"Verify the current function name and update the comment.{hint}",
                confidence=0.8,
            ))
    return _dedupe(findings)


def _in_repo_scope(ref: str, index: RepoIndex) -> bool:
    """v2: only judge claims about THIS repo's tree.

    Measured failure: template namespaces (flatpages/default.html),
    external-project sources (Modules/_sqlite/connection.c), dependency
    modules (MySQLdb/cursors.py), i18n patterns (en/LC_MESSAGES/x.po) were
    all flagged as "missing files". Rule: judge a ref only when it is
    explicitly relative (./ ../ /) or its first segment is a repo
    top-level name. Everything else is an external/namespace reference the
    snapshot cannot decide.
    """
    r = ref.strip()
    if r.startswith(("./", "../", "/")):
        return True
    first = r.lstrip("./").split("/")[0]
    return first in index.top_names


def _resolve_py_target(index: RepoIndex, claimer: str, module: str | None, level: int) -> list[str] | None:
    """Candidate module rel paths for an import, or None if unresolvable
    (stdlib, third-party, namespace packages: outside snapshot analysis).

    Relative (level>0) walks up from the claiming file. Absolute requires
    the top segment to be a repo root entry.
    """
    if level:
        base = _resolve_py_base(claimer, level)
        if not base and level - 1 > len(claimer.split("/")[:-1]):
            return None
        if module:
            base = base + module.split(".")
        prefix = "/".join(base)
    else:
        if not module:
            return None
        segs = module.split(".")
        if segs[0] in index.top_names:
            prefix = "/".join(segs)
        elif segs[0] in index.py_prefixes:
            # src/ and lib/ layouts: `import mypkg.x` lives at
            # `src/mypkg/x.py`. Without this, whole layouts resolve as
            # third-party and skip silently.
            prefix = index.py_prefixes[segs[0]] + "/" + "/".join(segs)
        else:
            return None
    if not prefix:
        return None
    return [prefix + ".py", prefix + "/__init__.py"]


def _dynamic_ns(index: RepoIndex, rel: str) -> bool:
    return rel in index.file_dynamic_ns


def _effective_symbols(index: RepoIndex, rel: str, depth: int = 0,
                       seen: frozenset[str] | None = None) -> set[str]:
    """Names a module file provides: defs, assignments, imports, plus one
    star-import hop (`from .models import *` re-exports everything). Depth
    capped with a seen-set; __init__ chains resolve in one hop in practice.
    """
    seen = seen or frozenset()
    if rel in seen or depth > 2:
        return set()
    seen = seen | {rel}
    out = set(index.file_symbols.get(rel, set())) | set(index.file_imports.get(rel, set()))
    for module, level in index.file_stars.get(rel, []):
        targets = _resolve_py_target(index, rel, module, level)
        if targets is None:
            continue
        for t in targets:
            if t in index.rel_paths:
                out |= _effective_symbols(index, t, depth + 1, seen)
    return out


def check_stale_import(facts: FileFacts, index: RepoIndex) -> list[Finding]:
    """Resolvable-import verification (Python; JS/TS relative imports).

    Python `from M import N` / JS `import {N} from './x'`: the module must
    exist, and N must be defined there, re-exported there, or itself a
    submodule. Guarded/conditional imports, bare specifiers (node_modules),
    stdlib, and deps are never flagged. Broken imports fail at load, so
    these are lies. See _check_stale_js_import for the JS/TS rules."""
    if facts.language == "javascript":
        return check_stale_js_import(facts, index)
    if facts.language != "python":
        return []
    findings: list[Finding] = []
    for module, level, names, is_guarded, lineno in facts.from_imports:
        if is_guarded:
            continue
        targets = _resolve_py_target(index, facts.path, module, level)
        if targets is None:
            continue
        existing = [t for t in targets if t in index.rel_paths]
        for name, _asname in names:
            if name == "*":
                continue
            if name.startswith("__") and name.endswith("__"):
                continue  # import system provides dunders (__file__, ...)
            if module is None:
                # `from . import sub`: the name may be a submodule file, a
                # name defined/re-exported by the package __init__ (stars
                # followed), or injected dynamically (`globals().update()`
                # in __init__: unknowable, never flagged — seen: CPython's
                # multiprocessing).
                base = "/".join(_resolve_py_base(facts.path, level))
                pkg_init = (base + "/__init__.py") if base else "__init__.py"
                if (name in index.file_symbols.get(pkg_init, set())
                        or name in index.file_imports.get(pkg_init, set())
                        or name in _effective_symbols(index, pkg_init)):
                    continue
                if _dynamic_ns(index, pkg_init) or not index.knows_symbols(pkg_init):
                    continue
                subs = ([base + "/" + name + ".py", base + "/" + name + "/__init__.py"]
                        if base else [name + ".py", name + "/__init__.py"])
                if any(s in index.rel_paths for s in subs):
                    continue
                findings.append(Finding(
                    path=facts.path, line=lineno, end_line=lineno,
                    checker="stale-import", severity="lie",
                    title=f"`from . import {name}` but no such submodule exists",
                    claim=f"from {'.' * level} import {name}",
                    evidence="No matching submodule file exists in this repo.",
                    fix="Fix the submodule path or remove the import.",
                    confidence=0.85,
                ))
                break
            if not existing:
                findings.append(Finding(
                    path=facts.path, line=lineno, end_line=lineno,
                    checker="stale-import", severity="lie",
                    title=f"`from {module}` imports from a module that does not exist",
                    claim=f"from {'.' * level}{module or ''} import {name}",
                    evidence="No such module file exists in this repo.",
                    fix="Fix the module path or remove the import.",
                    confidence=0.85,
                ))
                break
            if any(not index.knows_symbols(t) for t in existing):
                continue  # unparsed target may provide it: unknowable
            provided = any(name in _effective_symbols(index, t) for t in existing)
            # PEP 562: a module-level __getattr__ means any name may resolve.
            dynamic = any("__getattr__" in index.file_symbols.get(t, set()) for t in existing)
            # Dynamic namespace injection (`globals().update(...)`):
            # names cannot be enumerated statically. Seen: re/_constants.
            dynamic = dynamic or any(t in index.file_dynamic_ns for t in existing)
            home = existing[0].rsplit("/", 1)[0] if "/" in existing[0] else ""
            submod = (home + "/" + name + ".py") if home else (name + ".py")
            subpkg = (home + "/" + name + "/__init__.py") if home else (name + "/__init__.py")
            if provided or dynamic or submod in index.rel_paths or subpkg in index.rel_paths:
                continue
            findings.append(Finding(
                path=facts.path, line=lineno, end_line=lineno,
                checker="stale-import", severity="lie",
                title=f"`{name}` imported from `{existing[0]}` but never defined there",
                claim=f"from {'.' * level}{module or ''} import {name}",
                evidence=f"`{existing[0]}` exists but defines no `{name}`.",
                fix=f"Check for a rename in `{existing[0]}` (or a moved submodule).",
                confidence=0.8,
            ))
    return _dedupe(findings)


def _resolve_py_base(claimer: str, level: int) -> list[str]:
    parts = claimer.split("/")[:-1]
    if level - 1 > len(parts):
        return []
    return parts[:len(parts) - (level - 1)]


_JS_EXTS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts")

# TypeScript module resolution: a relative import written with a JS
# extension (`./suite.js`) resolves the same-named TS file (`suite.ts`)
# when no JS file exists. This is the default emitted by `tsc --init`
# ("Allow importing TS files with .js extensions") and is universal in
# TS test suites and ESM packages compiled from TS (seen: svelte's test
# suites import `../suite.js`, `./shared.js` with only .ts files on
# disk; OmniRoute's tests import `schemas.js` -> schemas.ts).
_JS_TS_SIBLINGS = {
    ".js": (".ts", ".tsx"),
    ".mjs": (".mts",),
    ".cjs": (".cts",),
    ".jsx": (".tsx",),
}


def _js_self_names(index: RepoIndex, claimer: str) -> set[str]:
    """Package names the claimer's own manifests say it ships (normalized).

    Walks every package.json from the scan root down to the claimer's
    directory (monorepo-aware: nearer manifests shadow nothing — a file
    may import any workspace's self-name). A repo that names itself
    (`"name": "svelte"`) resolves those imports through its exports map,
    bundler self-reference, or workspaces — none visible to snapshot
    analysis, so self-name bare imports are outside the decidable set.
    """
    rel = claimer.replace("\\", "/")
    parts = rel.split("/")[:-1]
    names: set[str] = set()
    seen: set[str] = set()
    for i in range(len(parts) + 1):
        d = "/".join(parts[:i]) if i else ""
        if d in seen:
            continue
        seen.add(d)
        try:
            data = json.loads((index.root / d / "package.json").read_text(
                encoding="utf-8", errors="ignore"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        name = data.get("name")
        if isinstance(name, str) and name:
            names.add(_norm_dist(name))
    return names


def _js_bare_externally_resolved(index: RepoIndex, claimer: str, spec: str) -> bool:
    """True when `spec` is a bare specifier whose resolution lies outside
    the snapshot, so stale-import must stay silent.

    A tsconfig/manual alias that maps a bare prefix onto the scanned tree
    is decidable and stays checkable (that is the alias feature). But when
    every replacement for the matched prefix resolves outside the tree,
    or is a types-only `.d.ts` surface that the scan deliberately excludes,
    the import is not falsifiable from a snapshot — most commonly the
    package's own name mapped to its type declarations (seen: svelte maps
    `svelte/*` -> `./src/*.d.ts`, which 1235 self-name imports then hit as
    drift), and node_modules-style mappings. Without node_modules there is
    no way to distinguish a lie from a resolution the scan cannot see.
    """
    for zone_dir, mapping in index.alias_zones:
        if zone_dir and not (claimer == zone_dir or claimer.startswith(zone_dir + "/")):
            continue
        for prefix, repls in mapping:
            if not spec.startswith(prefix):
                continue
            for repl in repls:
                if "node_modules" in repl.split("/"):
                    continue
                base = posixpath.normpath(
                    posixpath.join(zone_dir, repl, spec[len(prefix):])) if zone_dir \
                    else posixpath.normpath(repl + spec[len(prefix):])
                raw = _js_candidates_raw(base)
                if any(c in index.rel_paths for c in raw) or any(
                        not c.endswith(".d.ts") for c in raw):
                    return False
            return True
    return True


def _js_candidates_raw(base: str) -> list[str]:
    """Candidate paths without existence filtering (d.ts visibility)."""
    cands = ([base] if posixpath.splitext(base)[1].lower() in _JS_EXTS else []
             + [base + e for e in _JS_EXTS] + [base + "/index" + e for e in _JS_EXTS])
    stem, ext = posixpath.splitext(base)
    for sibling in _JS_TS_SIBLINGS.get(ext.lower(), ()):
        cands.append(stem + sibling)
    return [(c[2:] if c.startswith("./") else c) for c in cands]


def _file_tsconfig_excluded(index: RepoIndex, claimer: str) -> bool:
    """True when the claimer sits under a tsconfig `exclude` prefix."""
    rel = claimer.replace("\\", "/")
    return any(rel == p or rel.startswith(p + "/") for p in index.tsconfig_excluded)


def _base_in_ignored_dir(base: str) -> bool:
    """True when a candidate module path sits under a directory suffix the
    scan deliberately ignores (vendor, build, dist, coverage, ...). Shared
    by the relative and alias resolution arms: such files are never
    indexed, so their existence cannot be judged and "does not exist" is
    never positive evidence.
    """
    for part in base.split("/")[:-1]:
        if part in IGNORED_DIR_NAMES:
            return True
    return False


def _target_escapes_root(base: str) -> bool:
    """True when a resolved candidate path leaves the scanned tree.

    A specifier that walks above the scan root resolves against files the
    snapshot never indexed (a monorepo's sibling package, the repo root's
    own trees). Their existence cannot be judged from the snapshot, so
    reporting "does not exist" is never positive evidence — the same
    verdict as a scan-ignored directory. Mechanical and suppression-only:
    it can only remove findings, never invent one.

    Measured (OmniRoute, 2026-09-22): scanning `src/` reported 51
    stale-import lies for `../../shared/...` and `../../../open-sse/...`
    specifiers whose targets exist one level above the root; the same
    tree scanned from the repo root reported 3. Sub-tree and single-file
    scans are first-class agent workflows, so a partial snapshot must
    never manufacture absence claims about what it did not look at.
    """
    return base == ".." or base.startswith("../")


def _js_target_in_ignored_dir(index: RepoIndex, claimer: str, spec: str) -> bool:
    """True when a (relative) specifier's candidate targets sit under a
    directory suffix the scan deliberately ignores (vendor, build, dist,
    docs, coverage, ...). Their existence cannot be judged from the
    snapshot: they may or may not be real files, so "does not exist" is
    never positive evidence.
    """
    return _base_in_ignored_dir(posixpath.normpath(
        posixpath.join(posixpath.dirname(claimer), spec)))


def _resolve_js_target(index: RepoIndex, claimer: str, spec: str) -> list[str] | None:
    """Candidate module rel paths for a JS/TS specifier.

    Relative (./, ../) resolves directly. Alias prefixes (@/, ~/ and
    tsconfig/manual mappings) resolve through the longest matching zone;
    a matched-but-unresolvable alias is a missing module (drift), while a
    specifier matching nothing stays silent. Bare imports live in
    node_modules: outside snapshot analysis, always silent. Returns None
    (skip) or a possibly-empty list (empty = module does not exist).
    """
    if spec.startswith("./") or spec.startswith("../"):
        base = posixpath.normpath(
            posixpath.join(posixpath.dirname(claimer), spec))
        if _target_escapes_root(base):
            return None  # above the scan root: outside the snapshot
        return _js_candidates(index, base)
    for zone_dir, mapping in index.alias_zones:
        if zone_dir and not (claimer == zone_dir or claimer.startswith(zone_dir + "/")):
            continue
        for prefix, repls in mapping:
            if not spec.startswith(prefix):
                continue
            rest = spec[len(prefix):]
            found: list[str] = []
            external_only = True
            for repl in repls:
                if "node_modules" in repl.split("/"):
                    continue  # types-only or dep mappings: outside the snapshot
                external_only = False
                base = posixpath.normpath(posixpath.join(zone_dir, repl, rest)) if zone_dir else posixpath.normpath(repl + rest)
                if _base_in_ignored_dir(base) or _target_escapes_root(base):
                    # Alias mapped into a scan-ignored dir (seen: OmniRoute
                    # `@omniroute/open-sse/*` reaching tracked vendor code):
                    # existence is unknowable from the snapshot — never a
                    # finding, same verdict as the relative arm.
                    return None
                found.extend(_js_candidates(index, base))
            if found:
                return found
            if external_only:
                continue  # mapping declares externality: like a bare specifier
            return []
    return None


def _js_candidates(index: RepoIndex, base: str) -> list[str]:
    cands = ([base] if posixpath.splitext(base)[1].lower() in _JS_EXTS else []
             + [base + e for e in _JS_EXTS] + [base + "/index" + e for e in _JS_EXTS])
    # TS-style JS-extension imports: `./x.js` also resolves `./x.ts` when
    # no JS file exists (see _JS_TS_SIBLINGS).
    stem, ext = posixpath.splitext(base)
    for sibling in _JS_TS_SIBLINGS.get(ext.lower(), ()):
        cands.append(stem + sibling)
    # rel_paths stores both `x` and `./x`; every other map (exports,
    # imports, symbols) uses the clean form, so normalize: a `./`-form
    # target otherwise misses every export lookup (seen: express examples).
    return [(c[2:] if c.startswith("./") else c) for c in cands if c in index.rel_paths]


def _effective_js_exports(index: RepoIndex, rel: str, depth: int = 0,
                          seen: frozenset[str] | None = None) -> tuple[set[str], bool]:
    """(exported names, complete?). Bare `export *` makes the set
    unknowable: callers must stay silent rather than guess."""
    seen = seen or frozenset()
    if rel in seen or depth > 2:
        return set(), True
    seen = seen | {rel}
    out = set(index.file_exports.get(rel, set()))
    complete = rel not in index.file_export_unknown
    for spec in index.file_export_stars.get(rel, []):
        targets = _resolve_js_target(index, rel, spec)
        if targets is None:
            complete = False
            continue
        for t in targets:
            names, ok = _effective_js_exports(index, t, depth + 1, seen)
            out |= names
            complete = complete and ok
    return out, complete


def check_stale_js_import(facts: FileFacts, index: RepoIndex) -> list[Finding]:
    """JS/TS relative imports: module must exist; named bindings must be
    exported (star re-exports followed); defaults need a default export."""
    if facts.language != "javascript":
        return []
    # Import statements inside comments are prose, not imports. Line-based
    # extraction cannot know that, so comment-only lines are excluded here.
    comment_lines: set[int] = set()
    for c in facts.comments:
        for ln in range(c.line, c.end_line + 1):
            comment_lines.add(ln)
    self_names = _js_self_names(index, facts.path)
    findings: list[Finding] = []
    for spec, kind, default, named, lineno in facts.js_imports:
        if lineno in comment_lines:
            continue
        ext = posixpath.splitext(spec)[1].lower()
        if ext and ext not in _JS_EXTS:
            continue  # asset imports (css, json, svg): bundler surface
        if not spec.startswith(("./", "../", "/")):
            # Bare specifier: the default case is a node_modules package —
            # outside snapshot analysis, always silent. Two decidable
            # exceptions remain: an alias mapping onto the scanned tree,
            # and the repo's own package name (self-import). Both are
            # suppressed here when their resolution is not visible to the
            # snapshot (types-only targets, external mappings); only the
            # in-tree alias case continues to verdicts below.
            pkg = "/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0]
            if _norm_dist(pkg) in self_names or _js_bare_externally_resolved(
                    index, facts.path, spec):
                continue
        targets = _resolve_js_target(index, facts.path, spec)
        if targets is None:
            continue
        if not targets:
            # Ambient type surface: an extensionless specifier whose exact
            # .d.ts target exists (`./types` -> types.d.ts, seen: svelte's
            # internal client tests) resolves in TypeScript's ambient space.
            # Declaration files are never parsed as source, only tracked
            # (index.decl_paths), so this silence is evidence-based.
            if not posixpath.splitext(spec)[1]:
                base = posixpath.normpath(
                    posixpath.join(posixpath.dirname(facts.path), spec))
                if base + ".d.ts" in index.decl_paths or base + "/index.d.ts" in index.decl_paths:
                    continue
            # The repo excludes the claimer from its own typecheck
            # (tsconfig `exclude`): templates/scaffolds whose relative
            # imports resolve only after codegen transplantation (seen:
            # svelte's excluded scripts/process-messages/templates/).
            # Not a checkable claim — the file is outside the contract.
            if _file_tsconfig_excluded(index, facts.path):
                continue
            # Relative misses are lies (relative paths are always local).
            # Alias misses are drift: the target may be generated at build
            # time (registry outputs) or live outside the scanned tree.
            # Either way they never fail a default gate.
            is_relative = spec.startswith("./") or spec.startswith("../")
            # ...unless the target sits in a directory the scan deliberately
            # ignores (vendor trees, build dirs, dist): then "does not exist"
            # is knowingly wrong — the file is there, the scan just cannot
            # index it (seen: OmniRoute's tracked open-sse/vendor/ and
            # scripts/build/). The .d.ts exception keeps the one case where
            # the checker has positive evidence of a shimmed lie.
            if is_relative and _js_target_in_ignored_dir(index, facts.path, spec) \
                    and not posixpath.splitext(spec)[1].lower() == ".d.ts" \
                    and not spec.endswith((".d.ts", ".d.mts", ".d.cts")):
                continue
            findings.append(Finding(
                path=facts.path, line=lineno, end_line=lineno,
                checker="stale-import",
                severity="lie" if is_relative else "drift",
                title=f"imports from `{spec}`, which does not exist",
                claim=spec,
                evidence="No such module file exists in this repo.",
                fix="Fix the specifier or remove the import.",
                confidence=0.85 if is_relative else 0.6,
            ))
            continue
        if kind in ("sideeffect", "namespace"):
            continue
        provided: set[str] = set()
        complete = True
        for t in targets:
            names, ok = _effective_js_exports(index, t)
            provided |= names
            complete = complete and ok
        if not complete:
            continue  # unknowable export surface: stay silent, never guess
        if default is not None and "default" not in provided:
            if not all(t in index.file_esm for t in targets):
                continue  # CJS/script target: default interop always binds
            if kind == "require" and not facts.path.endswith(
                    (".mts", ".cts", ".mjs", ".cjs")):
                # require() default-shape from a .js file: the require()d
                # module is read at runtime; when the importer itself is
                # not forcibly-ESM (.mjs), the file may run as CJS where
                # `const mod = require('x')` binds any module.exports shape
                # (seen: electron/loginManager.js requiring a TS-compiled
                # service with only named exports). Not falsifiable from a
                # snapshot.
                continue
            findings.append(Finding(
                path=facts.path, line=lineno, end_line=lineno,
                checker="stale-import", severity="lie",
                title=f"default import `{default}` from `{spec}`, which has no default export",
                claim=default,
                evidence=f"`{targets[0]}` exists but exposes no default export.",
                fix=f"Check for a rename in `{targets[0]}` or import a named binding.",
                confidence=0.75,
            ))
        for original, alias in named:
            if kind == "require" and not provided:
                continue  # CJS without visible exports: cannot decide
            if original not in provided:
                findings.append(Finding(
                    path=facts.path, line=lineno, end_line=lineno,
                    checker="stale-import", severity="lie",
                    title=f"`{original}` imported from `{spec}` but never exported there",
                    claim=original if original == alias else f"{original} as {alias}",
                    evidence=f"`{targets[0]}` exists but exports no `{original}`.",
                    fix=f"Check for a rename in `{targets[0]}`.",
                    confidence=0.8,
                ))
    return _dedupe(findings)


def check_stale_file(facts: FileFacts, index: RepoIndex) -> list[Finding]:
    findings: list[Finding] = []
    dead = _commented_code_line_set(facts)

    def _scan(text: str, line: int, end: int, kind: str) -> None:
        if not text.strip():
            return
        text = re.sub(r"https?://\S+", "", text)
        # Ticket-anchored history notes ("used to be in X.py ... See #10355")
        # point outside on purpose, like ticketed symbol claims. The ticket
        # may sit on a neighboring comment line.
        if _TICKET.search(text) or _nearby_ticket(facts, line, end):
            return
        for m in _FILE_REF.finditer(text):
            ref = m.group(1)
            segs = [s.lower() for s in re.split(r"[/.]", ref)]
            if any(h in segs for h in PLACEHOLDER_PATH_HINTS):
                continue
            # Elided paths (`src/.../EndpointPageClient.tsx`) are shorthand the
            # author chose instead of a full path: the `...` IS the
            # placeholder. The segment split above cannot see it ("..."
            # becomes empty segments), so test the raw ref.
            if "..." in ref or "…" in ref:
                continue
            if "://" in ref:
                continue
            if not _in_repo_scope(ref, index):
                continue
            # A path under a directory the scan deliberately ignores (build
            # outputs, vendor trees, coverage) is never indexed, so its
            # existence cannot be judged — the same verdict the import arms
            # already give. These are typically generated or written at
            # runtime, not authored (measured on OmniRoute: `dist/docs/
            # openapi.yaml` named in a CLI's help text and `dist/index.cjs`
            # in a setup command were the dominant `stale-file-ref` shape).
            if _base_in_ignored_dir(ref):
                continue
            # v2: illustrative examples invent paths ("For example ...
            # ``django/templatetags/news/photos.py``"); a file ref
            # within ~120 chars after such a marker is an example, not a claim.
            if _ILLUSTRATIVE.search(text[max(0, m.start() - 120):m.start()]):
                continue
            if index.has_exact_path(ref):
                continue
            same = index.same_named(ref)
            detail = ""
            if same:
                shown = ", ".join(f"`{s}`" for s in same[:3])
                more = f" (+{len(same) - 3} more)" if len(same) > 3 else ""
                detail = f" Same-named files exist: {shown}{more}."
            findings.append(Finding(
                path=facts.path, line=line, end_line=end,
                checker="stale-file-ref", severity="lie",
                title=f"{kind} references missing file `{ref}`",
                claim=ref,
                evidence=f"`{ref}` claims a path inside this repo "
                         f"(first segment matches the repo tree), but no such file exists.{detail}",
                fix="Update the path or remove the reference. List nearby files to find the rename.",
                confidence=0.85,
            ))

    for c in facts.comments:
        if c.line in dead and c.end_line in dead:
            continue
        _scan(c.text, c.line, c.end_line, "Comment")
    # docstrings too
    for f in facts.functions:
        if f.docstring:
            _scan(f.docstring, f.docstring_lineno or f.lineno,
                  f.docstring_lineno or f.lineno, "Docstring")
    return _dedupe(findings)


_NUMBER_CLAIM = re.compile(
    r"\b(timeout|time-out|port|retries|max[_ -]?(?:retries|attempts|connections|size|length|count|workers?|threads?)|"
    r"min[_ -]?(?:size|length|count)?|limit|workers?|threads?|pool[_ -]?size|batch[_ -]?size|"
    r"cache[_ -]?size|ttl|expir\w+|delay|interval|threshold)\b\s*(?:is|of|=|:|→|->)?\s*(\d+(?:\.\d+)?)\s*(ms|s|sec|secs|seconds?|minutes?|mins?|hours?|ms|bytes?|kb|mb|gb|px|%)?",
    re.IGNORECASE,
)
_NUMBER_IN_CODE = re.compile(r"(?<![A-Za-z0-9_.])(\d+(?:\.\d+)?)(?![A-Za-z0-9_.])")


def check_number_drift(facts: FileFacts, index: RepoIndex) -> list[Finding]:
    findings: list[Finding] = []
    lines = facts.lines
    dead = _commented_code_line_set(facts)
    for c in facts.comments:
        if c.line in dead:
            continue
        if len(c.text) > 300:
            continue
        # Example sentences invent numbers ("Example, if we run for 1ms").
        # The marker may sit on a neighboring comment line.
        window_text = c.text
        for ln in range(c.line - 2, c.end_line + 3):
            if 1 <= ln <= len(facts.lines):
                s = facts.lines[ln - 1].strip()
                if s.startswith(("#", "//", "*", "/*")):
                    window_text += "\n" + s
        if _ILLUSTRATIVE.search(window_text):
            continue
        for m in _NUMBER_CLAIM.finditer(c.text):
            keyword = m.group(1).lower().replace("-", "_").replace(" ", "_")
            try:
                claimed = float(m.group(2))
            except ValueError:
                continue
            unit = (m.group(3) or "").lower()
            # bidirectional window: signature defaults live above, assignments below
            key_simple = re.split(r"[_ ]", keyword)[0]  # timeout/max/port/...
            if len(key_simple) < 3:
                continue
            lo = max(0, c.line - 1 - 15)
            hi = min(len(lines), c.line + 15)
            window = "\n".join(lines[lo:hi])
            if key_simple not in window.lower():
                continue
            # find numbers on lines mentioning the keyword
            for j in range(lo, hi):
                if (j + 1) in dead:
                    continue
                code_line = lines[j]
                stripped = code_line.strip()
                if stripped.startswith(("#", "//", "*", "/*")):
                    continue
                if key_simple not in code_line.lower():
                    continue
                # skip the comment's own line(s)
                if c.line <= j + 1 <= c.end_line:
                    continue
                for nm in _NUMBER_IN_CODE.finditer(_strip_strings(code_line)):
                    try:
                        actual = float(nm.group(1))
                    except ValueError:
                        continue
                    # ignore line numbers / indices / years / versions
                    if actual in (claimed,):
                        break
                    if actual > 1900 and actual < 2100 and claimed > 1900 and claimed < 2100:
                        break
                    if actual in (0, 1) and claimed in (0, 1):
                        break
                    # require the code number to be a "config-like" literal (assignment/comparison/call arg)
                    if not re.search(r"[=:(\[,<>]", code_line):
                        continue
                    findings.append(Finding(
                        path=facts.path, line=c.line, end_line=c.end_line,
                        checker="number-drift", severity="drift",
                        title=f"Comment says {key_simple} {m.group(2)}{unit or ''} but code uses {nm.group(1)}",
                        claim=f"{key_simple} = {m.group(2)}{unit or ''}",
                        evidence=f"{facts.path}:{j + 1}: {code_line.strip()[:120]}",
                        fix="Update the comment to the real value, or better: define a named constant and reference it from both.",
                        confidence=0.6,
                    ))
                    break
                else:
                    continue
                break
    return _dedupe(findings)


def check_fragile_anchor(facts: FileFacts, index: RepoIndex) -> list[Finding]:
    # Ticket links often sit on the line next to the marker ("See
    # https://..." below a "Temporarily ..." comment). Judge the marker
    # together with immediately adjacent comment lines.
    by_line = _comment_lines(facts)

    def has_ticket_nearby(c: Comment) -> bool:
        return _nearby_ticket(facts, c.line, c.end_line, by_line)

    findings: list[Finding] = []
    for c in facts.comments:
        text = c.text
        if not text.strip():
            continue
        m = _LINE_ANCHOR.search(text)
        if m:
            findings.append(Finding(
                path=facts.path, line=c.line, end_line=c.end_line,
                checker="fragile-anchor", severity="smell",
                title=f"Comment anchors to `{m.group(0)}` which rots on every edit",
                claim=m.group(0),
                evidence="Line numbers shift on every edit; the anchor is guaranteed to drift.",
                fix="Reference a symbol name (`function_name`) instead of a line number.",
                confidence=0.9,
            ))
            continue
        if _SEE_ABOVE_BELOW.search(text):
            findings.append(Finding(
                path=facts.path, line=c.line, end_line=c.end_line,
                checker="fragile-anchor", severity="smell",
                title="Comment says “see above/below” with no symbol to find",
                claim="see above/below",
                evidence="Positional references break when code moves.",
                fix="Name the symbol or file the reader should look at.",
                confidence=0.65,
            ))
            continue
        if _workaround_match(text) and not _TICKET.search(text) and not has_ticket_nearby(c):
            mm = _workaround_match(text)
            findings.append(Finding(
                path=facts.path, line=c.line, end_line=c.end_line,
                checker="fragile-anchor", severity="smell",
                title=f"Untracked workaround (“{mm.group(0)}”) with no ticket or link",
                claim=mm.group(0),
                evidence="Workarounds without a durable referent can never be safely removed.",
                fix="Add the issue URL or version condition (e.g. `# TODO(#123): remove when …`).",
                confidence=0.7,
            ))
            continue
        if _TEMPORAL.search(text) and not _TICKET.search(text) and not has_ticket_nearby(c):
            # only flag short comments where temporality is the point; avoid prose FPs
            if len(text) < 160 and re.search(r"\b(fix|hack|patch|toggle|flag|skip|disable)\b", text, re.IGNORECASE):
                mm = _TEMPORAL.search(text)
                findings.append(Finding(
                    path=facts.path, line=c.line, end_line=c.end_line,
                    checker="fragile-anchor", severity="smell",
                    title=f"Temporal marker (“{mm.group(0)}”) with no expiry condition",
                    claim=mm.group(0),
                    evidence="“Temporary” without a condition is permanent.",
                    fix="State the removal condition: version, date, or ticket.",
                    confidence=0.6,
                ))
    return _dedupe(findings)


# ---------------------------------------------------------------- stale-contract-ref
# EXPERIMENTAL, opt-in only. Architectural claims in comments that rot
# silently: deprecation targets, lock-holder requirements, env defaults.
# Narrow trigger frames only; backticked names stay with stale-symbol-ref
# (no double-reporting), ticket/URL-anchored claims point outside the
# snapshot on purpose (v2 rule) and are skipped.

_CONTRACT_DEPRECATION = re.compile(
    r"deprecat\w*|\breplac\w*\s+by\b|\bsupersed\w*\s+by\b"
    r"|\bmigrat\w+\s+to\b|\buse\b[^.\n]{0,80}?\binstead\b",
    re.IGNORECASE,
)
_CONTRACT_NAME = re.compile(
    r"(?<![A-Za-z0-9_$.`\"'])([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+"
    r"|[A-Za-z_][A-Za-z0-9_]*\([^()\n]*\))"
)
_CONTRACT_LOCK = re.compile(
    r"(?:must\s+hold|holding|guarded\s+by|protected\s+by|requires?(?:\s+holding)?"
    r"|acquires?|takes?)\s+`?(_?[A-Za-z][\w.]*)`?",
    re.IGNORECASE,
)
_CONTRACT_LOCK_LIKE = re.compile(r"^_|lock|mutex|guard|monitor|semaphore", re.IGNORECASE)
_CONTRACT_ENV_PY = re.compile(
    r"os\.getenv\(\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\s*,\s*([^,)\n]+)\)"
    r"|os\.environ\.get\(\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\s*,\s*([^,)\n]+)\)"
)
_CONTRACT_ENV_JS = re.compile(
    r"process\.env\.([A-Za-z_][A-Za-z0-9_]*)\s*(?:\?\?|\|\|)\s*([^,;)\n]+)"
)
_CONTRACT_ENV_JS_DESTRUCT = re.compile(r"\{\s*([^}]*)\}\s*=\s*process\.env\b")
_CONTRACT_DEFAULT_FRAME = re.compile(
    r"\bdefault(?:s)?(?:\s+(?:is|to|port|of))?\b|\bfallback\b|\bunless\s+set\b|\boverride\b",
    re.IGNORECASE,
)
_CONTRACT_LITERAL = re.compile(r"(\d+(?:\.\d+)?|[\"'][^\"']+[\"'])")


def _contract_norm_literal(raw: str) -> str:
    s = raw.strip().rstrip(",;")
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def _contract_known(root: str, base: str, facts: FileFacts, index: RepoIndex,
                    code: str, language: str) -> bool:
    if root in facts.imports:
        return True
    if language == "python" and (root in _STDLIB_MODULES or _stdlib_class(root)):
        return True
    if _appears_in_code(root, code) or (root != base and _appears_in_code(base, code)):
        return True
    return bool(index.has_symbol(root) or index.has_symbol(base))


def _loose_dist(name: str) -> str:
    """alphanumeric-only lowercase: bodyParser == body-parser."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


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

_DOC_CALL = re.compile(r"(?<![A-Za-z0-9_$.])([A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)*)\s*\(")

_DOC_PLACEHOLDER_NAMES = {
    "foo", "bar", "baz", "qux", "quux", "example", "sample", "demo",
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
    code blocks with a supported language tag. Unclosed fences are
    ignored; inner fences of greater depth are treated as content."""
    out: list[tuple[str, int, int]] = []
    i, n = 0, len(lines)
    while i < n:
        m = re.match(r"^(`{3,}|~{3,})\s*([A-Za-z0-9_+-]*)\s*$", lines[i])
        if not m:
            i += 1
            continue
        fence, tag = m.group(1), m.group(2).lower()
        lang = _DOC_FENCE_LANGS.get(tag)
        j = i + 1
        while j < n and not re.match(r"^" + re.escape(fence[0]) + r"{3,}\s*$", lines[j]):
            j += 1
        if j < n and lang:
            out.append((lang, i + 2, j + 1))
        i = j + 1 if j < n else n
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
    # Destructured bindings: `const { a, b } = x`, `({ page }) =>`,
    # `[first, ...rest] = list`. Test-fixture params are almost always
    # destructured (`async ({ page }) =>`) and were invisible to the
    # paren-param patterns, so `page.goto()` reported as a repo lie
    # (measured: svelte's Playwright testing guide).
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
        known = _doc_block_known(block, lang) | file_known
        if lang == "javascript" and declared is None:
            from .repo_index import _norm_dist as _nd
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


def check_stale_contract_ref(facts: FileFacts, index: RepoIndex) -> list[Finding]:
    """Deprecation targets, lock holders, and env defaults that lie.

    Only narrow frames: a deprecation sentence naming a replacement, a
    lock-requirement naming the lock, a same-file comment stating a
    default for an env var read with a different default in code.
    Bare prose never reports; only contradictions do.
    """
    findings: list[Finding] = []
    code = _code_text(facts)
    language = facts.language if facts.language in ("python", "javascript", "go", "c") else "python"
    for c in facts.comments:
        text = c.text
        if not text.strip() or _TICKET.search(text):
            continue
        if _CONTRACT_DEPRECATION.search(text):
            strong = bool(re.search(
                r"deprecat\w*|\breplac\w*\s+by\b|\bsupersed\w*\s+by\b|\bmigrat\w+\s+to\b",
                text, re.IGNORECASE))
            for m in _CONTRACT_NAME.finditer(text):
                raw = m.group(1).rstrip(".")
                is_call = raw.endswith(")")
                name = raw[:raw.index("(")] if is_call else raw
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", name or ""):
                    continue
                base = name.split(".")[-1]
                root = name.split(".")[0]
                if len(base) < 3 or _is_dunder(base) or _is_reserved(base, language):
                    continue
                if not strong and base.isupper():
                    continue  # bare "use X instead" naming SQL/platform
                    # builtins (JSON_TYPE, COALESCE): uppercase convention
                if "." not in name and not is_call:
                    continue  # bare word in prose, not a reference
                if _contract_known(root, base, facts, index, code, language):
                    continue
                hint = _suggest(base, index)
                findings.append(Finding(
                    path=facts.path, line=c.line, end_line=c.end_line,
                    checker="stale-contract-ref", severity="lie",
                    title=f"Deprecation notice points at `{name}` which does not exist",
                    claim=f"`{name}`",
                    evidence=f"`{root}` is not defined, imported, or used in this file, "
                             f"and no definition of `{base}` was found in {len(index.files)} indexed source files.",
                    fix=f"Point the notice at the real replacement, or remove it.{hint}",
                    confidence=0.8,
                ))
        for m in _CONTRACT_LOCK.finditer(text):
            name = m.group(1).rstrip(".")
            base = name.split(".")[-1]
            root = name.split(".")[0]
            if len(base) < 3 or _is_dunder(base) or _is_reserved(base, language):
                continue
            if not _CONTRACT_LOCK_LIKE.search(base):
                continue  # "must hold a reference": prose, not a lock
            if _contract_known(root, base, facts, index, code, language):
                continue
            findings.append(Finding(
                path=facts.path, line=c.line, end_line=c.end_line,
                checker="stale-contract-ref", severity="lie",
                title=f"Threading claim requires `{name}` which does not exist",
                claim=f"`{name}`",
                evidence=f"No `{base}` is defined, imported, or used in this file, "
                         f"and none was found in {len(index.files)} indexed source files: "
                         f"the lock was likely renamed.",
                fix="Update the claim to the current lock name.",
                confidence=0.8,
            ))
    if facts.language in ("python", "javascript"):
        skip: set[int] = set()
        for c in facts.comments:
            for ln in range(c.line, c.end_line + 1):
                skip.add(ln)
        for idx, line in enumerate(facts.lines, start=1):
            if idx in skip or not line.strip():
                continue
            pairs: list[tuple[str, str]] = []
            if facts.language == "python":
                for m in _CONTRACT_ENV_PY.finditer(line):
                    var = m.group(1) or m.group(3)
                    default = m.group(2) if m.group(1) else m.group(4)
                    if var and default is not None:
                        pairs.append((var, _contract_norm_literal(default)))
            else:
                for m in _CONTRACT_ENV_JS.finditer(line):
                    pairs.append((m.group(1), _contract_norm_literal(m.group(2))))
                for dm in _CONTRACT_ENV_JS_DESTRUCT.finditer(line):
                    for part in dm.group(1).split(","):
                        if "=" in part:
                            k, _, v = part.partition("=")
                            k = k.strip()
                            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
                                pairs.append((k, _contract_norm_literal(v)))
            for var, default in pairs:
                for c in facts.comments:
                    if not re.search(r"\b" + re.escape(var) + r"\b", c.text):
                        continue
                    if not _CONTRACT_DEFAULT_FRAME.search(c.text):
                        continue
                    found = False
                    for lm in _CONTRACT_LITERAL.finditer(c.text):
                        claimed = _contract_norm_literal(lm.group(1))
                        if claimed != default:
                            findings.append(Finding(
                                path=facts.path, line=c.line, end_line=c.end_line,
                                checker="stale-contract-ref", severity="drift",
                                title=f"Comment claims default `{claimed}` for `{var}`, code uses `{default}`",
                                claim=f"{var} default {claimed}",
                                evidence=f"`{var}` is read with default `{default}` in this file.",
                                fix=f"Update the comment to `{default}`, or change the code default.",
                                confidence=0.7,
                            ))
                            found = True
                            break
                    if found:
                        break
    return _dedupe(findings)


# ---------------------------------------------------------------- ghost-export
# EXPERIMENTAL, opt-in only. A public symbol nobody can reach: no
# importers anywhere, no use in its own file, no deliberate API marking.
# Libraries consume their API externally, so anything that looks like
# deliberate surface (__init__ modules, __all__, exports, Go-exported
# names, C without static info) is excluded, not flagged.

_GHOST_ALL = re.compile(r"__all__\s*=\s*\[[^\]]*\]")
_GHOST_TEST_FILE = re.compile(r"^(test_.*|.*_test)\.(py|go)$|\.(test|spec)\.[A-Za-z0-9]+$")

# Expected-output and generated paths: reachability cannot be judged for
# code a generator emits, so neither can "nobody can reach it". Covers
# svelte's `tests/snapshot/samples/*/_expected/`, jest/vitest
# `__snapshots__/`, and the usual codegen directory names.
_GHOST_GENERATED_PATH = re.compile(
    r"(^|/)(_expected|__snapshots__|snapshots|generated|codegen)(/|$)"
    r"|\.(gen|generated)\.[A-Za-z0-9]+$")


def _ghost_importers(symbol: str, own: str, index: RepoIndex) -> bool:
    for rel, names in index.file_imports.items():
        if rel != own and symbol in names:
            return True
    return False


def _ghost_used_in_sibling(name: str, rel: str, index: RepoIndex) -> bool:
    """Same-package cross-file use: Go/C call across files without imports,
    so same-file counting plus importers miss real uses (seen:
    debugPrintRoute called from gin.go, defined in debug.go). Only files
    in the same directory are consulted (Go package boundary; C
    translation-unit proximity), and only call-shaped occurrences count.
    Suppression-only: a comment mentioning the name cannot resurrect real
    dead code, it can only hide a finding.
    """
    texts = getattr(index, "_texts", None)
    root = getattr(index, "root", None)
    if not texts or root is None:
        return False
    want_dir = posixpath.dirname(rel)
    pat = re.compile(r"\b" + re.escape(name) + r"\s*\(")
    for f in getattr(index, "files", []):
        try:
            frel = f.relative_to(root).as_posix()
        except ValueError:
            continue
        if frel == rel or posixpath.dirname(frel) != want_dir:
            continue
        if pat.search(texts.get(str(f), "")):
            return True
    return False


def _ghost_build_tagged_variants(name: str, index: RepoIndex) -> bool:
    """Mutually exclusive //go:build variants (binding.go vs
    binding_nomsgpack.go): flagging either as dead deletes a live build
    configuration. All definers constrained ⇒ unknowable which builds."""
    definers = index.symbol_files.get(name, set())
    if len(definers) < 2:
        return False
    texts = getattr(index, "_texts", None)
    root = getattr(index, "root", None)
    if not texts or root is None:
        return False
    for drel in definers:
        text = texts.get(str(root / drel))
        if text is None or not re.search(r"^\s*//go:build\b", text, re.MULTILINE):
            return False
    return True


def check_ghost_export(facts: FileFacts, index: RepoIndex) -> list[Finding]:
    """Public symbol with no importers, no in-file use, no API marking.

    Runs per defining file: each top-level public definition is checked
    against repo-wide importers plus same-file code use. Methods,
    dunders, package surface, exports, and (for Go) exported names are
    never candidates.
    """
    if facts.language not in ("python", "javascript", "go"):
        return []
    if _GHOST_GENERATED_PATH.search(facts.path):
        return []  # generated/expected output: reachability is unknowable
    findings: list[Finding] = []
    code = _code_text(facts)
    full_text = "\n".join(facts.lines)
    all_match = _GHOST_ALL.search(full_text)
    all_block = all_match.group(0) if all_match else ""
    for f in facts.functions:
        name = f.name
        if not name or name.startswith("_") or _is_dunder(name) or len(name) < 3:
            continue
        if name.startswith("test_") and _GHOST_TEST_FILE.search(posixpath.basename(facts.path)):
            continue  # framework-discovered entry points (pytest, go test)
        if getattr(f, "is_method", False):
            continue
        defline = facts.lines[f.lineno - 1] if 1 <= f.lineno <= len(facts.lines) else ""
        if facts.language == "javascript":
            if not re.match(r"^\s*(?:export\s+)?(?:async\s+)?(?:function\s+|class\s+|(?:const|let|var)\s+"
                            + re.escape(name) + r"\b)", defline):
                continue  # methods and object properties are not trackable here
            if re.search(r"^\s*export\b[^\n]*\b" + re.escape(name) + r"\b", full_text, re.MULTILINE):
                continue  # deliberate export surface
            if re.search(r"module\.exports\b[^\n]*\b" + re.escape(name) + r"\b", full_text):
                continue
        elif facts.language == "go":
            if not re.match(r"^\s*func\s+[A-Za-z_]", defline):
                continue  # methods carry a receiver between func and name
            if name[0].isupper():
                continue  # exported: consumed outside the repo by design
            if name in ("main", "init"):
                continue
        else:
            if posixpath.basename(facts.path) == "__init__.py":
                return []  # package surface file: everything here is API
            if re.search(r"['\"]" + re.escape(name) + r"['\"]", all_block):
                continue  # deliberate API via __all__
        if _ghost_importers(name, facts.path, index):
            continue
        if index.attr_used_by(name, facts.path):
            continue  # used as mod.name elsewhere (from pkg import mod)
        uses = len(re.findall(r"\b" + re.escape(name) + r"\b", code))
        if uses > 1:
            continue  # used in its own file (def line itself counts once)
        if facts.language in ("go", "c") and _ghost_used_in_sibling(name, facts.path, index):
            continue  # same-package cross-file call needs no import
        if _ghost_build_tagged_variants(name, index):
            continue  # mutually exclusive build variants, all constrained
        findings.append(Finding(
            path=facts.path, line=f.lineno, end_line=f.lineno,
            checker="ghost-export", severity="smell",
            title=f"`{name}` is public but never imported or used anywhere",
            claim=f"`{name}`",
            evidence=f"No file imports `{name}`, and it is used nowhere else in "
                     f"`{facts.path}` across {len(index.files)} indexed source files.",
            fix="Delete it, or mark the API surface explicitly (`__all__`/export).",
            confidence=0.7,
        ))
    return _dedupe(findings)


# ---------------------------------------------------------------- stale-entrypoint
# EXPERIMENTAL, opt-in only. Install-time strings rot silently:
# pyproject [project.scripts] targets and package.json bin/main paths.
# Only in-repo claims are judged; build-output dirs (dist/, build/)
# stay silent (absent pre-publish is normal, not a lie).

_ENTRY_BUILD_DIRS = {"dist", "build", "out", "target", "esm", "cjs", "umd"}


def _entry_toml(text: str):
    try:
        import tomllib  # py3.11+
        return tomllib.loads(text)
    except ImportError:
        pass
    except ValueError:
        return None
    try:
        from .toml_compat import loads as _compat_loads
        return _compat_loads(text)
    except Exception:
        return None


def _entry_line(lines: list[str], needle: str) -> int:
    for i, line in enumerate(lines, start=1):
        if needle and needle in line:
            return i
    return 1


def check_stale_entrypoint(facts: FileFacts, index: RepoIndex) -> list[Finding]:
    """Manifest entry points that point nowhere.

    pyproject.toml `[project.scripts]`/`[project.gui-scripts]`
    `name = "mod:func"`: the module must exist and define the function.
    package.json `bin`/`main`: the relative file must exist (outside
    build-output dirs). Malformed manifests stay silent, never guess.
    """
    if facts.language != "config":
        return []
    findings: list[Finding] = []
    base = posixpath.basename(facts.path)
    parent = posixpath.dirname(facts.path)
    if base == "pyproject.toml":
        data = _entry_toml("\n".join(facts.lines))
        if not isinstance(data, dict):
            return []
        scripts: dict = {}
        proj = data.get("project")
        if isinstance(proj, dict):
            for section in ("scripts", "gui-scripts"):
                part = proj.get(section)
                if isinstance(part, dict):
                    scripts.update(part)
        for name, target in scripts.items():
            if not isinstance(target, str):
                continue
            ref = target.split("[")[0].strip()
            mod, _, func = ref.partition(":")
            mod, func = mod.strip(), func.strip()
            if not mod or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", mod):
                continue
            targets = _resolve_py_target(index, facts.path, mod, 0)
            if targets is None:
                continue  # external package
            existing = [t for t in targets if t in index.rel_paths]
            lineno = _entry_line(facts.lines, target)
            if not existing:
                findings.append(Finding(
                    path=facts.path, line=lineno, end_line=lineno,
                    checker="stale-entrypoint", severity="lie",
                    title=f"Entry point `{name}` targets missing module `{mod}`",
                    claim=target,
                    evidence=f"No `{mod}` module file exists in this repo.",
                    fix="Fix the module path or remove the entry point.",
                    confidence=0.85,
                ))
                continue
            if func:
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", func):
                    continue
                if any(not index.knows_symbols(t) for t in existing):
                    continue  # unparsed target may provide it: unknowable
                provided = any(func in _effective_symbols(index, t) for t in existing)
                dynamic = any("__getattr__" in index.file_symbols.get(t, set())
                              or t in index.file_dynamic_ns for t in existing)
                if provided or dynamic:
                    continue
                findings.append(Finding(
                    path=facts.path, line=lineno, end_line=lineno,
                    checker="stale-entrypoint", severity="lie",
                    title=f"Entry point `{name}` targets `{mod}:{func}`, which is not defined there",
                    claim=target,
                    evidence=f"`{existing[0]}` exists but defines no `{func}`.",
                    fix=f"Fix the function name or remove the entry point.",
                    confidence=0.8,
                ))
    elif base == "package.json":
        try:
            data = json.loads("\n".join(facts.lines))
        except ValueError:
            return []
        if not isinstance(data, dict):
            return []
        jobs: list[tuple[str, str]] = []
        b = data.get("bin")
        if isinstance(b, str):
            jobs.append(("bin", b))
        elif isinstance(b, dict):
            for k, v in b.items():
                if isinstance(v, str):
                    jobs.append((f"bin:{k}", v))
        m = data.get("main")
        if isinstance(m, str):
            jobs.append(("main", m))
        for label, target in jobs:
            t = target.strip()
            if not t or t.startswith(("http://", "https://")):
                continue
            if not (t.startswith("./") or t.startswith("../") or t.startswith("/")):
                continue  # bare package ref: external
            norm = posixpath.normpath(posixpath.join(parent, t.lstrip("/")) if parent else t)
            norm = norm[2:] if norm.startswith("./") else norm
            if norm in index.rel_paths:
                continue
            local = posixpath.normpath(t)
            local = local[2:] if local.startswith("./") else local
            if local.split("/")[0] in _ENTRY_BUILD_DIRS:
                continue  # build output absent pre-publish is normal
            lineno = _entry_line(facts.lines, target)
            findings.append(Finding(
                path=facts.path, line=lineno, end_line=lineno,
                checker="stale-entrypoint", severity="lie",
                title=f"package.json `{label}` points at missing file `{t}`",
                claim=target,
                evidence=f"No such file exists in this repo.",
                fix="Fix the path or remove the entry.",
                confidence=0.8,
            ))
    return _dedupe(findings)


# ---------------------------------------------------------------- stale-mock-ref
# EXPERIMENTAL, opt-in only. Test doubles rot silently: @patch("a.b.C")
# names a symbol that no longer exists, and nothing fails until that
# test runs. Only in-repo module paths are judged; external strings,
# create=True, and unresolvable targets stay silent.

_MOCK_PATCH_STR = re.compile(
    r"(?:^|[\s(@.])(?:[A-Za-z_][A-Za-z0-9_.]*\.)?patch\s*\(\s*[\"']([^\"']+)[\"']")
_MOCK_PATCH_OBJECT = re.compile(
    r"(?:^|[\s(@.])(?:[A-Za-z_][A-Za-z0-9_.]*\.)?patch\.object\s*\(\s*"
    r"(?:[\"']([^\"']+)[\"']|([A-Za-z_][A-Za-z0-9_.]*))\s*,\s*[\"']([^\"']+)[\"']")


def _mock_split(path: str) -> tuple[str, str] | None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", path or ""):
        return None
    parts = path.split(".")
    if len(parts) < 2:
        return None
    return (".".join(parts[:-1]), parts[-1])


def _mock_provided(index: RepoIndex, target: str, symbol: str) -> bool:
    provided = symbol in _effective_symbols(index, target)
    dynamic = ("__getattr__" in index.file_symbols.get(target, set())
               or target in index.file_dynamic_ns)
    return provided or dynamic


_IMPORT_AS = re.compile(
    r"^\s*import\s+(.+)$")


def _mock_import_map(facts: FileFacts, skip: set[int]) -> dict[str, tuple[str, int, str | None]]:
    """Bare head -> (module, level, orig): full dotted module, the name as
    defined there (alias resolved), level for relatives. Covers
    `from m import (X as) Y`, `import a.b as m`, and plain `import a`
    (top segment, usable as an absolute root).
    """
    out: dict[str, tuple[str, int, str | None]] = {}
    for module, level, names, _guarded, _lineno in facts.from_imports:
        for orig, alias in names:
            out[alias or orig] = (module or "", level, orig)
    for idx, line in enumerate(facts.lines, start=1):
        if idx in skip:
            continue
        m = _IMPORT_AS.match(line)
        if not m:
            continue
        for part in m.group(1).split(","):
            pm = re.fullmatch(r"\s*([A-Za-z_][A-Za-z0-9_.]*)\s+as\s+([A-Za-z_][A-Za-z0-9_]*)\s*", part)
            if pm:
                out[pm.group(2)] = (pm.group(1), 0, None)
    for alias, root in facts.imports.items():
        if root and alias not in out:
            out[alias] = (root, 0, None)
    return out


def _mock_resolve_path(index: RepoIndex, claimer: str, parts: list[str]
                       ) -> tuple[str, str, str] | None:
    """Progressive resolution of an absolute dotted mock path.

    Returns None when silent (external top, or a resolvable prefix
    provides the head: attribute chains, methods, builtins injected
    into module namespace), else (modfile, head, full) for the verdict.
    The longest file-prefix wins; attribute chains below a provided
    head are method gaps the snapshot cannot falsify.
    """
    if not parts or len(parts) < 2:
        return None
    top_targets = _resolve_py_target(index, claimer, parts[0], 0)
    if top_targets is None and parts[0] not in index.py_prefixes:
        return None  # external top-level: outside snapshot analysis
    for k in range(len(parts) - 1, 0, -1):
        mod = ".".join(parts[:k])
        targets = _resolve_py_target(index, claimer, mod, 0)
        if targets is None:
            continue
        existing = [t for t in targets if t in index.rel_paths]
        if not existing:
            # Namespace package portion (no __init__): unenumerable.
            prefix = "/".join(parts[:k])
            if prefix in index.dirs and any(
                    r == prefix or r.startswith(prefix + "/") for r in index.rel_paths):
                return None
            continue
        if not all(index.knows_symbols(t) for t in existing):
            return None  # unparsed target may provide it: unknowable
        head = parts[k]
        if (head in PYTHON_BUILTINS
                or any(_mock_provided(index, t, head) for t in existing)):
            return None
        modpath = "/".join(parts[:k])
        if (f"{modpath}/{head}.py" in index.rel_paths
                or f"{modpath}/{head}/__init__.py" in index.rel_paths
                or f"{modpath}/{head}" in index.dirs):
            return None  # head is itself a module: patching it is valid
        return (existing[0], head, ".".join(parts))
    return None


def check_stale_mock_ref(facts: FileFacts, index: RepoIndex) -> list[Finding]:
    """@patch / patch.object strings naming absent in-repo symbols.

    A mocked path that resolves to a real module file but names nothing
    there is a test that errors at runtime. Module paths that resolve
    nowhere stay silent (external); create=True opts out explicitly.
    """
    if facts.language != "python":
        return []
    findings: list[Finding] = []
    skip: set[int] = set()
    for c in facts.comments:
        for ln in range(c.line, c.end_line + 1):
            skip.add(ln)
    import_map = _mock_import_map(facts, skip)
    for idx, line in enumerate(facts.lines, start=1):
        if idx in skip or not line.strip():
            continue
        jobs: list[list[str]] = []  # absolute dotted paths, attr included
        for m in _MOCK_PATCH_STR.finditer(line):
            split = _mock_split(m.group(1))
            if split:
                jobs.append((split[0] + "." + split[1]).split("."))
        for m in _MOCK_PATCH_OBJECT.finditer(line):
            str_target, bare_target, attr = m.group(1), m.group(2), m.group(3)
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", attr or ""):
                continue
            if str_target:
                # patch.object("app.Foo", "meth"): the class is verified,
                # the method is a documented gap.
                split = _mock_split(str_target)
                if split:
                    jobs.append((split[0] + "." + split[1]).split("."))
            elif bare_target:
                parts = bare_target.split(".")
                entry = import_map.get(parts[0])
                if not entry:
                    continue
                mod, level, orig = entry
                # segs continues the object path below the imported name;
                # orig is that name as defined (alias resolved). A bare
                # top import (`import a` used as `a.b.X`) is already
                # absolute: don't re-prepend. The attr itself stays
                # unjudged (method/meta gap by design).
                if orig is not None:
                    tail = [orig] + parts[1:]
                elif mod and mod != parts[0]:
                    tail = mod.split(".") + parts[1:]  # import-as alias
                else:
                    tail = parts
                if level:
                    base = _resolve_py_base(facts.path, level)
                    if not base and level - 1 > len(facts.path.split("/")[:-1]):
                        continue
                    full = base + ((mod.split(".") if mod else []) + tail
                                   if orig is not None or (mod and mod != parts[0])
                                   else tail)
                else:
                    full = ((mod.split(".") if mod else []) + tail
                            if orig is not None or (mod and mod != parts[0])
                            else tail)
                jobs.append(full)
        if not jobs:
            continue
        if re.search(r"\bcreate\s*=\s*True\b", line):
            continue
        for full in jobs:
            if len(full[-1]) < 3 or _is_dunder(full[-1]):
                continue
            verdict = _mock_resolve_path(index, facts.path, full)
            if verdict is None:
                continue
            modfile, head, _full = verdict
            findings.append(Finding(
                path=facts.path, line=idx, end_line=idx,
                checker="stale-mock-ref", severity="lie",
                title=f"Mock patches `{_full}`: `{head}` not found in `{modfile}`",
                claim=f'"{_full}"',
                evidence=f"`{modfile}` exists but provides no `{head}`.",
                fix="Update the mock to the current name.",
                confidence=0.8,
            ))
    return _dedupe(findings)


# ---------------------------------------------------------------- phantom-package
# EXPERIMENTAL, opt-in only. Imports that run locally (installed in the
# author's environment) but are declared nowhere: dead on clean CI and
# fertile ground for dependency confusion. Only absolute imports of
# names missing from every manifest flavor are flagged; stdlib,
# in-repo modules, and test-scoped groups (unioned) stay silent.
# Monorepos: root manifests only. This is hygiene drift, never a lie.

_NODE_BUILTINS = frozenset({
    "assert", "async_hooks", "buffer", "child_process", "cluster",
    "console", "constants", "crypto", "dgram", "diagnostics_channel",
    "dns", "domain", "events", "fs", "http", "http2", "https",
    "inspector", "module", "net", "os", "path", "perf_hooks", "process",
    "punycode", "querystring", "readline", "repl", "stream",
    "string_decoder", "sys", "timers", "tls", "trace_events", "tty",
    "url", "util", "v8", "vm", "wasi", "worker_threads", "zlib",
})


# Import name -> distribution name for the notorious mismatches
# (import yaml lives in distribution pyyaml). Curated, unambiguous
# only; ambiguous cases (Crypto, magic) stay silent via... nothing:
# they report, and the docs list this map. Keep it short on purpose.
_IMPORT_TO_DIST = {
    "yaml": "pyyaml",
    "PIL": "pillow",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "gi": "pygobject",
    "wx": "wxpython",
    "serial": "pyserial",
    "usb": "pyusb",
    "attr": "attrs",
    "jwt": "pyjwt",
    "jose": "python-jose",
    "dns": "dnspython",
    "nmap": "python-nmap",
    "ldap": "python-ldap",
    "consul": "python-consul",
    "socks": "pysocks",
    "rest_framework": "djangorestframework",
    "corsheaders": "django-cors-headers",
    "git": "gitpython",
    "jenkins": "python-jenkins",
    "magic": "python-magic",
}


def _phantom_py(facts: FileFacts, index: RepoIndex, declared: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()
    _norm = _norm_dist
    jobs: list[tuple[str, int]] = []  # (top module, lineno)
    for module, level, _names, guarded, lineno in facts.from_imports:
        if guarded:
            continue  # compat import that may legitimately fail
        if module and not level:
            jobs.append((module.split(".")[0], lineno))
    for _alias, root in facts.imports.items():
        if root:
            top = root.split(".")[0]
            lines = _import_lines(facts, top)
            if lines and all(ln in facts.guarded_lines for ln in lines):
                continue  # every occurrence guarded: may legitimately fail
            jobs.append((top, lines[0] if lines else 1))
    for top, lineno in jobs:
        if not top or top in _STDLIB_MODULES or top in seen:
            continue
        seen.add(top)
        targets = _resolve_py_target(index, facts.path, top, 0)
        if targets is not None and any(t in index.rel_paths for t in targets):
            continue  # first-party (src-layout aware)
        if top in index.parent_tops:
            continue  # first-party above the scan root: not a distribution
        if _norm(top) in declared or _norm(_IMPORT_TO_DIST.get(top, top)) in declared:
            continue
        line = lineno if lineno > 1 else _import_line(facts, top)
        findings.append(Finding(
            path=facts.path, line=line, end_line=line,
            checker="phantom-package", severity="drift",
            title=f"`{top}` is imported but declared in no manifest",
            claim=f"import {top}",
            evidence=f"`{top}` is not stdlib, not in-repo, and matches no "
                     f"dependency in pyproject.toml, requirements files, or package.json.",
            fix=f"Declare it (or remove the import if the environment lied to you).",
            confidence=0.65,
        ))
    return findings


def _import_line(facts: FileFacts, top: str) -> int:
    lines = _import_lines(facts, top)
    return lines[0] if lines else 1


def _import_lines(facts: FileFacts, top: str) -> list[int]:
    out = []
    for i, line in enumerate(facts.lines, start=1):
        s = line.strip()
        if re.match(r"(?:from|import)\s+", s) and top in s:
            out.append(i)
    return out


def _phantom_js(facts: FileFacts, index: RepoIndex, declared: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    _norm = _norm_dist
    for spec, _kind, _default, _named, lineno in facts.js_imports:
        if spec.startswith(("./", "../", "/", "node:")):
            continue
        if spec in (".", ".."):
            continue  # parent/self-dir self-reference (require('..'))
        if spec.startswith("#"):
            continue  # package imports-map: unresolvable statically
        pkg = "/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0]
        base = pkg[5:] if pkg.startswith("node:") else pkg
        if base in _NODE_BUILTINS:
            continue
        if _norm(pkg) in declared or _norm(base) in declared:
            continue
        # @types/X declares the host-provided module X (vscode, chrome):
        # unactionable as a runtimedep, so it stays silent. Trade-off, made
        # explicit: @types/lodash without lodash is missed the same way.
        type_pkg = "@types/" + (pkg[1:].replace("/", "__") if pkg.startswith("@") else pkg)
        if _norm(type_pkg) in declared:
            continue
        findings.append(Finding(
            path=facts.path, line=lineno, end_line=lineno,
            checker="phantom-package", severity="drift",
            title=f"`{pkg}` is imported but declared in no manifest",
            claim=f"import {pkg}",
            evidence=f"`{pkg}` matches no dependency in package.json.",
            fix=f"Declare it (or remove the import if the environment lied to you).",
            confidence=0.65,
        ))
    return findings


def check_phantom_package(facts: FileFacts, index: RepoIndex) -> list[Finding]:
    """Imports declared in no manifest (pyproject, requirements, package.json)."""
    if facts.language not in ("python", "javascript"):
        return []
    declared = index.declared_dependencies(facts.path)
    if declared is None:
        return []  # no manifest anywhere: nothing to judge against
    if facts.language == "python":
        return _dedupe(_phantom_py(facts, index, declared))
    return _dedupe(_phantom_js(facts, index, declared))


# ---------------------------------------------------------------- stale-cli-ref
# EXPERIMENTAL, opt-in only. Documented `grounded` invocations that would
# fail: unknown subcommands, unknown flags. The spec is introspected from
# argparse itself, so the checker cannot drift from the CLI. Agent
# instructions live or die by these lines.

_CLI_SPEC: dict | None = None
_CLI_SHELL_OPS = set("|&;><()#")


def _cli_spec() -> dict:
    global _CLI_SPEC
    if _CLI_SPEC is not None:
        return _CLI_SPEC
    import argparse
    from .cli import build_parser
    parser = build_parser()
    spec: dict = {"flags": {}, "cmds": {}}
    for action in parser._actions:
        for opt in action.option_strings:
            spec["flags"][opt] = action
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                flags: dict = {}
                for sact in sub._actions:
                    for opt in sact.option_strings:
                        flags[opt] = sact
                spec["cmds"][name] = flags
    _CLI_SPEC = spec
    return spec


def _cli_argv_segments(line: str) -> list[list[str]]:
    """Split a line into `grounded ...` argv lists (shell-aware)."""
    import shlex
    out: list[list[str]] = []
    try:
        tokens = shlex.split(line, posix=True)
    except ValueError:
        return out
    i = 0
    while i < len(tokens):
        if tokens[i] == "grounded":
            argv = ["grounded"]
            i += 1
            while i < len(tokens):
                tok = tokens[i]
                if (tok in _CLI_SHELL_OPS or tok.startswith("$")
                        or tok.startswith("`") or "\\n" in tok):
                    break
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tok):
                    i += 1
                    continue
                argv.append(tok)
                i += 1
            out.append(argv)
        elif tokens[i:i + 3] == ["python", "-m", "grounded.cli"]:
            argv = ["grounded", *tokens[i + 3:]]
            cut = len(argv)
            for j in range(1, len(argv)):
                if argv[j] in _CLI_SHELL_OPS:
                    cut = j
                    break
            out.append(argv[:cut])
            i += 3
        else:
            i += 1
    return out


def _cli_takes_value(action) -> bool:
    import argparse as _ap
    return not isinstance(action, (_ap._StoreTrueAction, _ap._StoreFalseAction,
                                   _ap._CountAction, _ap._HelpAction, _ap._VersionAction))


def _cli_check_argv(argv: list[str], spec: dict) -> str | None:
    """None if valid, else the offending token."""
    rest = argv[1:]
    flags = spec["flags"]
    if rest and not rest[0].startswith("-"):
        if rest[0] not in spec["cmds"]:
            return rest[0]
        flags = spec["cmds"][rest[0]]
        rest = rest[1:]
    elif not rest:
        return None
    skip_next = False
    for tok in rest:
        if skip_next:
            skip_next = False
            continue
        if tok == "--":
            break
        if not tok.startswith("-") or tok == "-":
            continue  # positionals/values: not verifiable, never flagged
        if tok in flags:
            if _cli_takes_value(flags[tok]):
                skip_next = True
            continue
        if tok.startswith("--"):
            matches = [o for o in flags if o.startswith(tok)]
            if len(matches) == 1:
                continue  # unambiguous argparse prefix
            return tok
        return tok
    return None


def check_stale_cli_ref(facts: FileFacts, index: RepoIndex) -> list[Finding]:
    """Documented `grounded` invocations with unknown subcommands/flags.

    Markdown only. Strong contexts (fenced console blocks, `$` lines,
    backticked spans starting with `grounded`) get full checking
    including unknown subcommands. Weak contexts (prose mentions) are
    checked only when the word after `grounded` is already a known
    subcommand or flag: "the grounded skill teaches" is prose, not an
    invocation, and never reports. Synopsis meta-syntax (`[--flag]`,
    `UPPER` placeholders) is positional and never flagged.
    """
    if facts.language != "markdown":
        return []
    findings: list[Finding] = []
    spec = _cli_spec()
    in_fence = False
    fence_tag = ""
    for lineno, text in enumerate(facts.lines, start=1):
        fm = re.match(r"^(`{3,}|~{3,})\s*([A-Za-z0-9_+-]*)\s*$", text.strip())
        if fm:
            if in_fence:
                in_fence = False
            else:
                in_fence, fence_tag = True, fm.group(2).lower()
            continue
        segments: list[tuple[list[str], bool]] = []
        for m in re.finditer(r"`([^`\n]+)`", text):
            span = m.group(1)
            if "grounded" in span:
                for argv in _cli_argv_segments(span):
                    segments.append((argv, span.strip().startswith("grounded")))
        stripped = text.strip()
        in_console = in_fence and fence_tag in ("", "console", "bash", "sh", "shell",
                                                "text", "plaintext", "terminal", "zsh")
        if stripped.startswith("$") or (in_console and "grounded" in text):
            body = stripped[1:].strip() if stripped.startswith("$") else stripped
            for argv in _cli_argv_segments(body):
                if argv and argv[0] == "grounded":
                    segments.append((argv, body.startswith("grounded")))
        for argv, strong in segments:
            if len(argv) < 2:
                continue
            if argv[1].endswith(":"):
                continue  # program output (`grounded fix: ...`), not an invocation
            if not strong and not (argv[1] in spec["cmds"] or argv[1].startswith("-")):
                continue  # prose mention, not an invocation
            bad = _cli_check_argv(argv, spec)
            if bad is None:
                continue
            findings.append(Finding(
                path=facts.path, line=lineno, end_line=lineno,
                checker="stale-cli-ref", severity="lie",
                title=f"Documented invocation uses unknown `{bad}`",
                claim=" ".join(argv[:4]),
                evidence=f"`{bad}` matches no subcommand or flag in this version of grounded.",
                fix="Fix the invocation or remove the example.",
                confidence=0.85,
            ))
    return _dedupe(findings)


CHECKERS = {
    "stale-symbol-ref": check_stale_symbol,
    "stale-file-ref": check_stale_file,
    "stale-import": check_stale_import,
    "number-drift": check_number_drift,
    "fragile-anchor": check_fragile_anchor,
    "stale-doc-ref": check_stale_doc_ref,
    "stale-contract-ref": check_stale_contract_ref,
    "ghost-export": check_ghost_export,
    "stale-entrypoint": check_stale_entrypoint,
    "stale-mock-ref": check_stale_mock_ref,
    "phantom-package": check_phantom_package,
    "stale-cli-ref": check_stale_cli_ref,
}

CHECKER_DESCRIPTIONS = {
    "stale-symbol-ref": "Comment names a call (foo() or `foo()`) that is not defined, imported, or used in-file (v2: import- and scope-aware).",
    "stale-file-ref": "Comment claims a path inside this repo's tree that does not exist (namespace- and placeholder-aware).",
    "stale-import": "Resolvable `from M import N` where the module is missing or N is not defined, re-exported, or a submodule there.",
    "number-drift": "Comment states a magic number (timeout/port/limit) that disagrees with adjacent code.",
    "fragile-anchor": "Line-number anchors, see-above/below, or untracked HACK/WORKAROUND markers.",
    "stale-doc-ref": "EXPERIMENTAL, opt-in only: fenced Markdown code example calls a symbol defined nowhere in the repo.",
    "stale-contract-ref": "EXPERIMENTAL, opt-in only: deprecation target, lock-holder claim, or env default in a comment that contradicts the repo.",
    "ghost-export": "EXPERIMENTAL, opt-in only: public symbol with no importers, no in-file use, and no deliberate API marking.",
    "stale-entrypoint": "pyproject scripts and package.json bin/main pointing at nothing in the repo (graduated 2026-09-22: silent on 5 real repos).",
    "stale-mock-ref": "@patch/patch.object strings naming symbols absent from the in-repo module (graduated 2026-09-22: zero false positives on django/CPython stress).",
    "phantom-package": "EXPERIMENTAL, opt-in only: imports declared in no manifest (pyproject, requirements, package.json).",
    "stale-cli-ref": "EXPERIMENTAL, opt-in only: documented `grounded` invocations with unknown subcommands or flags.",
}

# Opt-in checkers are registered (so --enable/explain work) but excluded
# from every default set. A checker graduates by measured precision, not
# by age: see docs/rules.md.
OPT_IN_CHECKERS = frozenset({"stale-doc-ref", "stale-contract-ref", "ghost-export",
                             "phantom-package", "stale-cli-ref"})
DEFAULT_ENABLED = frozenset(CHECKERS) - OPT_IN_CHECKERS

# Intentionally unimplemented: docstring contracts and commented-out code
# are covered more precisely by darglint/pydoclint, eslint-plugin-jsdoc,
# and Ruff ERA001. `explain <id>` points users at them.
REMOVED_CHECKERS = {
    "param-mismatch": "removed in v2 (use darglint/pydoclint for Python, eslint-plugin-jsdoc check-param-names/require-param for JS/TS).",
    "raises-mismatch": "removed in v2 (use darglint DAR402/pydoclint DOC502-503 for Python, eslint-plugin-jsdoc require-throws for JS/TS).",
    "return-mismatch": "removed in v2 (use darglint DAR201-202/pydoclint DOC201-203 for Python, eslint-plugin-jsdoc require-returns-check for JS/TS).",
    "commented-code": "removed in v2 (use Ruff ERA001 for Python, eslint-plugin-comment-cleaner for JS/TS).",
}


def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple] = set()
    out: list[Finding] = []
    for f in findings:
        key = (f.path, f.line, f.checker, f.title)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out
