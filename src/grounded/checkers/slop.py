"""slop-package (experimental): the AI package-hallucination firewall.

Agents invent dependency names that do not exist; attackers watch for
exactly those names and register malware under them (slopsquatting /
package baiting). This checker closes that loop at the import line:

- a third-party import naming a distribution that exists on NO public
  registry (PyPI for Python, npm for JavaScript) is a lie: the install
  breaks, and the name is claimable by an attacker;
- a distribution registered less than 48 hours ago is drift: possibly
  legitimate, possibly planted for this exact import — verify before
  trusting.

Only checker that touches the network, and it says so: registry lookups
time out fast (10 s) and any failure (offline, DNS, rate limit) is
silence, never a finding and never an error. A gate that fails closed
on airplane wifi would train users to disable it; a gate that fails
open still catches every hallucination the moment it can see. Opt-in
for exactly this reason: default scans stay offline and deterministic.

Scope mirrors phantom-package (absolute third-party imports; stdlib,
guarded, and first-party stay silent), but declared status does NOT
silence: a manifest entry for a nonexistent package is a broken install
at best and a planted dependency at worst. Declared-vs-undeclared only
changes the evidence text.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from ..models import FileFacts, Finding
from ..repo_index import RepoIndex, _norm_dist
from ._shared import (
    _STDLIB_MODULES,
    _dedupe,
)
from .phantom import _NODE_BUILTINS
from .imports import (
    _resolve_py_target,
)
from .phantom import _IMPORT_TO_DIST, _import_lines

NEWBORN_HOURS = 48
_TIMEOUT = 10.0


def _age_hours(iso: str) -> float | None:
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0


def registry_lookup(kind: str, dist: str) -> dict | None:
    """{"exists": bool, "age_hours": float|None} or None when the
    registry cannot be reached. Monkeypatch point for tests (network
    never runs in the suite)."""
    import json as _json
    import urllib.error
    import urllib.request

    def fetch(url: str):
        req = urllib.request.Request(url, headers={"User-Agent": "grounded-lint",
                                                    "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                return _json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"__missing__": True}
            return None
        except Exception:
            return None

    if kind == "pypi":
        data = fetch(f"https://pypi.org/pypi/{dist}/json")
        if data is None:
            return None
        if data.get("__missing__"):
            return {"exists": False, "age_hours": None}
        urls = data.get("urls") or []
        times = [u.get("upload_time_iso_8601") for u in urls if u.get("upload_time_iso_8601")]
        age = min((_age_hours(t) for t in times if _age_hours(t) is not None),
                  default=None)
        return {"exists": True, "age_hours": age}
    if kind == "npm":
        data = fetch("https://registry.npmjs.org/" + dist.replace("/", "%2F"))
        if data is None:
            return None
        if data.get("__missing__"):
            return {"exists": False, "age_hours": None}
        created = (data.get("time") or {}).get("created")
        return {"exists": True,
                "age_hours": _age_hours(created) if created else None}
    return None


def _py_jobs(facts: FileFacts, index: RepoIndex) -> list[tuple[str, str, int]]:
    """(kind, top, lineno) third-party candidates."""
    jobs: list[tuple[str, str, int]] = []
    for module, level, _names, guarded, lineno in facts.from_imports:
        if guarded:
            continue
        if module and not level:
            jobs.append(("pypi", module.split(".")[0], lineno))
    for _alias, root in facts.imports.items():
        if root:
            top = root.split(".")[0]
            lines = _import_lines(facts, top)
            if lines and all(ln in facts.guarded_lines for ln in lines):
                continue
            jobs.append(("pypi", top, lines[0] if lines else 1))
    out = []
    for kind, top, lineno in jobs:
        if not top or top in _STDLIB_MODULES:
            continue
        targets = _resolve_py_target(index, facts.path, top, 0)
        if targets is not None and any(t in index.rel_paths for t in targets):
            continue  # first-party
        if top in index.parent_tops:
            continue
        out.append((kind, top, lineno))
    return out


def _js_jobs(facts: FileFacts, index: RepoIndex) -> list[tuple[str, str, int]]:
    out = []
    for spec, _kind, _default, _named, lineno in facts.js_imports:
        if spec.startswith(("./", "../", "/", "node:")):
            continue
        if spec in (".", ".."):
            continue
        if spec.startswith("#"):
            continue
        pkg = "/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0]
        base = pkg[5:] if pkg.startswith("node:") else pkg
        if base in _NODE_BUILTINS:
            continue
        out.append(("npm", pkg, lineno))
    return out


def check_slop_package(facts: FileFacts, index: RepoIndex) -> list[Finding]:
    """Third-party imports naming distributions missing from (or newborn
    on) the public registry."""
    if facts.language not in ("python", "javascript"):
        return []
    jobs = (_py_jobs(facts, index) if facts.language == "python"
            else _js_jobs(facts, index))
    try:
        declared = index.declared_dependencies(facts.path) or set()
    except Exception:
        declared = set()
    findings: list[Finding] = []
    seen: set[str] = set()
    for kind, top, lineno in jobs:
        dist = _norm_dist(_IMPORT_TO_DIST.get(top, top)) if kind == "pypi" else top
        if dist in seen:
            continue
        seen.add(dist)
        info = registry_lookup(kind, dist)
        if info is None:
            continue  # offline or unreachable: silence, never a finding
        is_declared = dist in declared
        if not info.get("exists", True):
            findings.append(Finding(
                path=facts.path, line=lineno, end_line=lineno,
                checker="slop-package", severity="lie",
                title=f"`{top}` is imported but `{dist}` exists on no public registry",
                claim=f"import {top}",
                evidence=(f"`{dist}` is not stdlib, not in-repo, "
                          f"{'declared but' if is_declared else 'not declared and'} "
                          f"absent from {'PyPI' if kind == 'pypi' else 'npm'}. "
                          f"Potential AI hallucination or supply-chain attack "
                          f"(slopsquatting): the name is claimable by anyone."),
                fix="Verify the intended package name; if real, check the spelling "
                    "and declare it. Never install to 'see if it works'.",
                confidence=0.85,
            ))
            continue
        age = info.get("age_hours")
        if age is not None and age < NEWBORN_HOURS:
            findings.append(Finding(
                path=facts.path, line=lineno, end_line=lineno,
                checker="slop-package", severity="drift",
                title=f"`{dist}` was registered {age:.0f} hours ago: verify before trusting",
                claim=f"import {top}",
                evidence=(f"`{dist}` exists on {'PyPI' if kind == 'pypi' else 'npm'} "
                          f"but was first published {age:.0f} hours ago. "
                          f"Brand-new distributions are the classic vehicle for "
                          f"package-baiting attacks aimed at hallucinated imports."),
                fix="Pin a review: inspect the package contents and publisher "
                    "before this import runs anywhere sensitive.",
                confidence=0.7,
            ))
    return _dedupe(findings)
