"""Reporters: terminal, JSON, SARIF, self-contained HTML. Stdlib only."""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone

from .models import Finding


def _tool_version() -> str:
    try:
        from . import __version__
        return str(__version__)
    except ImportError:  # pragma: no cover - never happens in practice
        return "0.0.0"

SEV_COLOR = {"lie": "\033[31m", "drift": "\033[33m", "smell": "\033[36m"}
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def format_terminal(findings: list[Finding], n_files: int, root: str, use_color: bool = True,
                    n_unparsed: int = 0, n_checker_errors: int = 0) -> str:
    counts = {"lie": 0, "drift": 0, "smell": 0}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    unparsed_note = f", {n_unparsed} file(s) unparsed" if n_unparsed else ""
    err_note = f", {n_checker_errors} checker error(s)" if n_checker_errors else ""
    lines: list[str] = []
    if not findings:
        if n_checker_errors:
            # `clean` is a verdict about the repo. It is only true if every
            # enabled checker actually ran — a crashed checker also returns
            # zero findings, so saying `clean` here would assert something
            # this run cannot know.
            head = (f"grounded: 0 findings in {n_files} file(s){unparsed_note}, but "
                    f"{n_checker_errors} checker error(s): INCOMPLETE, not clean.")
            return head if not use_color else f"\033[31m{head}{RESET}"
        head = f"grounded: clean, {n_files} file(s) scanned, 0 findings{unparsed_note}."
        return head if not use_color else f"\033[32m{head}{RESET}"
    for f in findings:
        color = SEV_COLOR.get(f.severity, "") if use_color else ""
        reset = RESET if use_color else ""
        b = BOLD if use_color else ""
        d = DIM if use_color else ""
        lines.append(f"{color}{b}{f.severity.upper()}{reset} {d}{f.path}:{f.line}{reset} {b}[{f.checker}]{reset} {f.title}")
        if f.claim:
            lines.append(f"    {d}claim:{reset} {f.claim[:200]}")
        if f.evidence:
            lines.append(f"    {d}evidence:{reset} {f.evidence[:220]}")
        if f.fix:
            lines.append(f"    {d}fix:{reset} {f.fix[:220]}")
    summary = (
        f"\ngrounded: {len(findings)} finding(s) in {n_files} file(s), "
        f"{counts.get('lie',0)} lie(s), {counts.get('drift',0)} drift(s), {counts.get('smell',0)} smell(s)"
        f"{unparsed_note}{err_note}."
    )
    lines.append(summary if not use_color else f"{BOLD}{summary}{RESET}")
    return "\n".join(lines)


def to_json(findings: list[Finding]) -> str:
    return json.dumps([f.to_dict() for f in findings], indent=2)


def to_sarif(findings: list[Finding], root: str = "") -> str:
    rules_seen: dict[str, dict] = {}
    results = []
    level_map = {"lie": "error", "drift": "warning", "smell": "note"}
    for f in findings:
        rules_seen.setdefault(f.checker, {
            "id": f.checker,
            "name": f.checker,
            "shortDescription": {"text": f.checker},
        })
        results.append({
            "ruleId": f.checker,
            "level": level_map.get(f.severity, "warning"),
            "message": {"text": f"{f.title} Claim: {f.claim} Evidence: {f.evidence}".strip()},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": f.path},
                    "region": {"startLine": f.line, "endLine": max(f.line, f.end_line)},
                }
            }],
            "properties": {"severity": f.severity, "confidence": f.confidence, "fix": f.fix},
        })
    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "grounded",
                "version": _tool_version(),
                "informationUri": "https://github.com/gonisulaimann/Grounded",
                "rules": list(rules_seen.values()),
            }},
            "results": results,
        }],
    }
    return json.dumps(sarif, indent=2)


def to_html(findings: list[Finding], n_files: int, root: str = "") -> str:
    counts = {"lie": 0, "drift": 0, "smell": 0}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows = []
    for i, f in enumerate(findings):
        sev = html.escape(f.severity)
        rows.append(
            "<tr data-sev=\"{sev}\" data-checker=\"{checker}\">"
            "<td><span class=\"pill {sev}\">{sev}</span></td>"
            "<td><code>{path}:{line}</code></td>"
            "<td><code>{checker}</code></td>"
            "<td><strong>{title}</strong>"
            "{claim}{evidence}{fix}</td>"
            "<td class=\"conf\">{conf:.2f}</td></tr>".format(
                sev=sev,
                checker=html.escape(f.checker),
                path=html.escape(f.path),
                line=f.line,
                title=html.escape(f.title),
                claim=("<div class=\"meta\"><span>claim</span> " + html.escape(f.claim[:300]) + "</div>") if f.claim else "",
                evidence=("<div class=\"meta\"><span>evidence</span> " + html.escape(f.evidence[:400]) + "</div>") if f.evidence else "",
                fix=("<div class=\"meta fix\"><span>fix</span> " + html.escape(f.fix[:400]) + "</div>") if f.fix else "",
                conf=f.confidence,
            )
        )
    body_rows = "\n".join(rows) if rows else "<tr><td colspan=\"5\" class=\"clean\">All beliefs check out. No findings.</td></tr>"
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>grounded report</title>
<style>
:root{--bg:#0b0e14;--panel:#151a24;--ink:#e6e9ef;--mut:#8b93a7;--lie:#ff5c5c;--drift:#f5a524;--smell:#3ec6dd;--line:#232a3a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
.wrap{max-width:1060px;margin:0 auto;padding:32px 20px 60px}
header{display:flex;flex-wrap:wrap;gap:16px;align-items:end;justify-content:space-between;margin-bottom:18px}
h1{margin:0;font-size:28px;letter-spacing:-.02em}h1 small{color:var(--mut);font-weight:500}
.sub{color:var(--mut);font-size:13px}
.cards{display:flex;gap:10px;margin:18px 0;flex-wrap:wrap}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 16px;min-width:130px}
.card b{font-size:24px;display:block}.card span{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.08em}
.card.lie b{color:var(--lie)}.card.drift b{color:var(--drift)}.card.smell b{color:var(--smell)}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}
.toolbar button{background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:999px;padding:7px 14px;cursor:pointer;font-size:13px}
.toolbar button[aria-pressed="true"]{border-color:var(--ink)}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top;font-size:13.5px}
th{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.07em}
tr:last-child td{border-bottom:none}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;background:#0e1320;padding:2px 6px;border-radius:6px}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:11.5px;font-weight:700;text-transform:uppercase;letter-spacing:.06em}
.pill.lie{background:rgba(255,92,92,.15);color:var(--lie);border:1px solid rgba(255,92,92,.4)}
.pill.drift{background:rgba(245,165,36,.14);color:var(--drift);border:1px solid rgba(245,165,36,.4)}
.pill.smell{background:rgba(62,198,221,.13);color:var(--smell);border:1px solid rgba(62,198,221,.4)}
.meta{color:var(--mut);margin-top:6px}.meta span{display:inline-block;min-width:64px;color:#c6cddd;font-size:11px;text-transform:uppercase;letter-spacing:.07em}
.meta.fix{color:#b9f0d0}.conf{color:var(--mut);text-align:right}
.clean{text-align:center;color:var(--mut);padding:26px!important}
footer{color:var(--mut);font-size:12px;margin-top:14px}
</style></head><body><div class="wrap">
<header><div><h1>grounded <small>comment reference report</small></h1>
<div class="sub">__ROOT__ &middot; __NOW__ &middot; __NFILES__ file(s) scanned</div></div></div>
<div class="cards">
<div class="card lie"><b>__LIE__</b><span>lies (errors)</span></div>
<div class="card drift"><b>__DRIFT__</b><span>drifts (warnings)</span></div>
<div class="card smell"><b>__SMELL__</b><span>smells (notes)</span></div>
</div>
<div class="toolbar" role="toolbar" aria-label="filter">
<button data-f="all" aria-pressed="true">all (__TOTAL__)</button>
<button data-f="lie" aria-pressed="false">lies (__LIE__)</button>
<button data-f="drift" aria-pressed="false">drifts (__DRIFT__)</button>
<button data-f="smell" aria-pressed="false">smells (__SMELL__)</button>
<input id="q" placeholder="filter by text…" style="flex:1;min-width:180px;background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:7px 14px;color:var(--ink)">
</div>
<table><thead><tr><th>severity</th><th>location</th><th>checker</th><th>finding</th><th>conf</th></tr></thead>
<tbody id="rows">
__ROWS__
</tbody></table>
<footer>Deterministic, offline. Every finding lists claim, evidence, and fix.</footer>
</div>
<script>
const btns=[...document.querySelectorAll('.toolbar button')];const q=document.getElementById('q');
let f='all';
btns.forEach(b=>b.onclick=()=>{f=b.dataset.f;btns.forEach(x=>x.setAttribute('aria-pressed',x===b?'true':'false'));apply();});
q.oninput=apply;
function apply(){const s=q.value.toLowerCase();document.querySelectorAll('#rows tr').forEach(tr=>{
const okF=(f==='all'||tr.dataset.sev===f);const okQ=!s||tr.textContent.toLowerCase().includes(s);
tr.style.display=(okF&&okQ)?'':'none';});}
</script></body></html>""".replace(
        "__ROOT__", html.escape(root or ".")
    ).replace("__NOW__", now).replace("__NFILES__", str(n_files)).replace(
        "__LIE__", str(counts.get("lie", 0))
    ).replace("__DRIFT__", str(counts.get("drift", 0))).replace(
        "__SMELL__", str(counts.get("smell", 0))
    ).replace(
        "__TOTAL__", str(len(findings))
    ).replace(
        "__ROWS__", body_rows
    )
