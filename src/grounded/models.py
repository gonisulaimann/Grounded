"""Core data models for grounded."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


SEVERITIES = ("lie", "drift", "smell")

SEVERITY_RANK = {"lie": 3, "drift": 2, "smell": 1}


@dataclass
class Finding:
    path: str
    line: int
    end_line: int
    checker: str
    severity: str  # lie | drift | smell
    title: str
    claim: str = ""
    evidence: str = ""
    fix: str = ""
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def rank(self) -> int:
        return SEVERITY_RANK.get(self.severity, 0)


@dataclass
class CheckerError:
    """A checker that raised instead of returning findings for one file.

    A crash yields no findings, which is indistinguishable from a clean tree
    in every summary line. Recording it is what lets a scan refuse to report
    `clean` without every enabled checker having actually run.
    """

    checker: str
    path: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FileFacts:
    path: str  # relative posix path
    language: str  # "python" | "javascript"
    lines: list[str] = field(default_factory=list)
    functions: list[Any] = field(default_factory=list)  # FuncInfo
    comments: list[Any] = field(default_factory=list)  # Comment
    # v2: import-awareness. Local names bound by imports, and the top-level
    # module each alias comes from ("" for relative/unresolvable).
    # e.g. {"CookieJar": "http.cookiejar", "os": "os", "axios": ""}
    imports: dict[str, str] = field(default_factory=dict)
    # Structured from-imports for import resolution:
    # [(module or None, level, [(name, asname)], guarded, lineno)] where
    # guarded means inside try/except, TYPE_CHECKING, or a version/platform
    # conditional (compat imports that may legitimately fail are never
    # flagged).
    from_imports: list[Any] = field(default_factory=list)
    # Linenos of Import/ImportFrom under try/except, TYPE_CHECKING, or
    # version/platform conditionals (see parsers._is_guarded).
    guarded_lines: set = field(default_factory=set)
    # Structured JS/TS imports: [(specifier, kind, default or None,
    # [named], lineno)]. Kinds: named, namespace (`* as ns`), sideeffect,
    # require. Side-effect-only and non-relative specifiers resolve to
    # module existence at most.
    js_imports: list[Any] = field(default_factory=list)


@dataclass
class FuncInfo:
    name: str
    lineno: int
    end_lineno: int
    args: list[str]
    docstring: str = ""
    docstring_lineno: int = 0
    has_value_return: bool = False
    has_bare_return_only: bool = False
    raises: list[str] = field(default_factory=list)
    is_method: bool = False


@dataclass
class Comment:
    text: str  # stripped of marker, preserved inner text
    raw: str  # full raw line(s) joined
    line: int  # start line (1-indexed)
    end_line: int
    is_block: bool = False  # /* */ or docstring-adjacent block
