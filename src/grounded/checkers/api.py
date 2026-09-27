"""stale-api-ref: client calls an endpoint the repo's own spec never defines.

EXPERIMENTAL, opt-in only. The cross-repo contract problem in miniature:
code calls `GET /api/v3/users`, but the OpenAPI/Swagger document in this
repo defines no such route. The call will fail at runtime, and no test
that mocks HTTP will catch it.

Narrow on purpose:
- Specs are JSON OpenAPI/Swagger documents (`openapi.json`,
  `swagger.json`, or any `*.json` whose top level has `paths` or
  `openapi`/`swagger` keys). YAML specs are out of scope: stdlib only,
  no YAML parser, and guessing at YAML is how false lies are made.
- Clients are string literals that are the first argument to an
  HTTP-shaped call (`requests.get("...")`, `fetch("...")`,
  `axios.post("...")`, ...). Bare strings are never judged: a `"/health"`
  in a comment, a constant, or a log line is not a request.
- Only absolute URLs (scheme + host stripped) and root-relative paths
  (`/...`). Relative paths (`v1/users`) are ambiguous against base URLs
  and stay silent.
- Route templates match segment-wise (`/users/{id}` and `/users/:id`
  both match `/users/42`).
- Filesystem-looking literals (`/etc/hosts`, `/usr/...`, `/tmp/...`,
  `/var/...`, `/dev/...`, `/proc/...`, anything with a static-asset
  extension) stay silent.
- No spec file anywhere in the tree: silence, not "everything is
  unknown". Like phantom-package, there must be something to judge
  against.
"""
from __future__ import annotations

import json
import posixpath
import re

from ..models import FileFacts, Finding
from ..repo_index import RepoIndex
from ._shared import _dedupe

_HTTP_CALL = re.compile(
    r"(?<![A-Za-z0-9_$.])"
    r"(?:[A-Za-z_][A-Za-z0-9_$]*\.)?"
    r"(get|post|put|delete|patch|head|options|request|fetch|ajax)"
    r"\(\s*[\"']([^\"']+)[\"']")
_NON_API_ROOTS = ("/etc/", "/usr/", "/var/", "/tmp/", "/dev/", "/proc/")
_STATIC_EXTS = frozenset({
    ".js", ".mjs", ".cjs", ".css", ".png", ".jpg", ".jpeg", ".gif",
    ".svg", ".ico", ".woff", ".woff2", ".ttf", ".map", ".html", ".htm",
})


def _spec_routes(text: str) -> set[str] | None:
    """Route templates from a JSON OpenAPI/Swagger doc, or None when
    the text is not one."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    paths = data.get("paths")
    if not isinstance(paths, dict):
        return None
    if "openapi" not in data and "swagger" not in data:
        return None  # a random JSON object with a "paths" key is not a spec
    return {str(p) for p in paths}


def _route_match(route: str, path: str) -> bool:
    rsegs = route.strip("/").split("/")
    psegs = path.strip("/").split("/")
    if len(rsegs) != len(psegs):
        return False
    for r, p in zip(rsegs, psegs):
        if re.fullmatch(r"\{[^/{}]+\}|:[^/:]+", r):
            if not p:
                return False
            continue
        if r != p:
            return False
    return True


def _url_path(raw: str) -> str | None:
    """Absolute-URL or root-relative literal -> path, else None."""
    s = raw.strip()
    m = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://[^/]*(/[^?#]*)?", s)
    if m:
        s = m.group(1) or "/"
    elif not s.startswith("/"):
        return None
    s = s.split("?", 1)[0].split("#", 1)[0]
    if not s or " " in s or "\\" in s:
        return None
    low = s.lower()
    if low.startswith(_NON_API_ROOTS):
        return None
    if posixpath.splitext(low)[1] in _STATIC_EXTS:
        return None
    return s or None


def _collect_routes(index: RepoIndex) -> set[str] | None:
    """Union of route templates from every JSON spec in the tree.
    None when the repo has no spec to judge against."""
    texts = getattr(index, "_texts", None)
    root = getattr(index, "root", None)
    found = False
    routes: set[str] = set()
    if texts and root is not None:
        for rel in index.rel_paths:
            if rel.startswith("./"):
                continue
            if not rel.lower().endswith(".json"):
                continue
            text = texts.get(str(root / rel))
            if text is None:
                continue
            got = _spec_routes(text)
            if got is None:
                continue
            found = True
            routes |= got
    if found:
        return routes
    # Fallback: read candidate spec files from disk (index may not hold
    # texts, e.g. single-file LSP indexes).
    from pathlib import Path
    try:
        base_root = Path(str(root)) if root is not None else None
    except Exception:
        return None
    if base_root is None:
        return None
    for name in ("openapi.json", "swagger.json"):
        for cand in [base_root / name, base_root / "docs" / name,
                     base_root / "spec" / name, base_root / "api" / name]:
            try:
                got = _spec_routes(cand.read_text(encoding="utf-8",
                                                  errors="ignore"))
            except OSError:
                continue
            if got is not None:
                found = True
                routes |= got
    return routes if found else None


def check_stale_api_ref(facts: FileFacts, index: RepoIndex) -> list[Finding]:
    """HTTP-call string literals with no matching route in the repo's
    own OpenAPI/Swagger documents."""
    if facts.language not in ("python", "javascript"):
        return []
    routes = _collect_routes(index)
    if not routes:
        return []
    findings: list[Finding] = []
    skip: set[int] = set()
    for c in facts.comments:
        for ln in range(c.line, c.end_line + 1):
            skip.add(ln)
    for lineno, line in enumerate(facts.lines, start=1):
        if lineno in skip or not line.strip():
            continue
        for m in _HTTP_CALL.finditer(line):
            method, raw = m.group(1).lower(), m.group(2)
            path = _url_path(raw)
            if path is None:
                continue
            if any(_route_match(r, path) for r in routes):
                continue
            findings.append(Finding(
                path=facts.path, line=lineno, end_line=lineno,
                checker="stale-api-ref", severity="lie",
                title=f"Client calls `{method.upper()} {path}` with no matching route in this repo's API spec",
                claim=f"{method.upper()} {path}",
                evidence=f"no route in the repo's OpenAPI/Swagger documents matches `{path}` "
                         f"(templates compared segment-wise).",
                fix="Update the client path or the spec; one of them moved without the other.",
                confidence=0.75,
            ))
    return _dedupe(findings)
