"""grounded watch: the Prove-It Loop's eyes.

A polling file watcher (stdlib only — no watchdog dependency to audit)
that re-scans on every change and reports only findings that were not
present in the previous scan. The persistent index cache makes re-scans
cheap (unchanged files replay), so the loop is: change, rescan, verdict.

Semantics, stated plainly:
- Findings are fingerprinted (see delta.fingerprint: checker + path +
  claim + title, never line numbers), so an edit that merely shifts
  lines does not re-report.
- The first iteration establishes the baseline silently: watch reports
  what the change *introduced*, never the pre-existing state.
- Status goes to stderr; findings go to stdout (pipeable).
- Exit code is always 0 (Ctrl-C stops it): a monitor reports, it does
  not gate. For gates use `scan` (exit 1) with `--changed` or baselines.
- A scan with checker errors is reported as incomplete on stderr, and
  its findings are still compared: an error must never read as clean,
  but it must not wedge the loop either.
"""
from __future__ import annotations

import time
from pathlib import Path

from .config import Config
from .delta import fingerprint
from .models import CheckerError, Finding
from .scanner import apply_suppressions, collect_files, scan_root


def snapshot_files(root: Path, config: Config) -> dict[str, tuple[float, int]]:
    """rel path -> (mtime, size) for every scannable file. Pure read."""
    out: dict[str, tuple[float, int]] = {}
    resolved = root.resolve()
    files, _ = collect_files(root, config)
    for f in files:
        try:
            rel = f.relative_to(resolved).as_posix()
        except ValueError:
            rel = f.name
        try:
            st = f.stat()
        except OSError:
            continue
        out[rel] = (st.st_mtime, st.st_size)
    return out


def detect_new(before: set[str], findings: list[Finding]) -> list[Finding]:
    """Findings whose fingerprint was absent before."""
    return [f for f in findings if fingerprint(f) not in before]


def run_watch(root: Path, config: Config, interval: float = 2.0,
              max_iterations: int | None = None,
              on_event=None, use_color: bool | None = None) -> int:
    """Poll until interrupted (or max_iterations scans). on_event(kind,
    findings, iteration) receives 'start' once, then 'new' or 'clean'
    per scan; the default prints findings to stdout, status to stderr.
    Returns 0 always (see module docstring for why)."""
    import sys
    iteration = 0
    known: set[str] | None = None
    while True:
        errors: list[CheckerError] = []
        findings, facts, _ = scan_root(root, config, checker_errors=errors)
        findings, _ = apply_suppressions(findings, {f.path: f for f in facts})
        current = {fingerprint(f) for f in findings}
        if known is None:
            known = current
            _emit(on_event, "start", [], iteration, len(facts),
                  use_color=use_color,
                  extra=f"watching {len(facts)} file(s), "
                        f"{len(findings)} finding(s) at start")
        else:
            new = detect_new(known, findings)
            known = current
            if new:
                _emit(on_event, "new", new, iteration, len(facts),
                      use_color=use_color)
            else:
                _emit(on_event, "clean", [], iteration, len(facts))
        if errors:
            _emit(on_event, "errors", errors, iteration)
        iteration += 1
        if max_iterations is not None and iteration >= max_iterations:
            return 0
        time.sleep(interval)


def _emit(on_event, kind, payload, iteration, n_files=0, use_color=None, extra=""):
    import sys
    if on_event is not None:
        on_event(kind, payload, iteration)
        return
    if kind == "start":
        print(f"grounded watch: {extra} (Ctrl-C to stop).", file=sys.stderr)
    elif kind == "new":
        from .reporters import format_terminal
        color = sys.stdout.isatty() if use_color is None else use_color
        print(format_terminal(payload, n_files, root="", use_color=color))
        sys.stdout.flush()
    elif kind == "errors":
        print(f"grounded watch: {len(payload)} checker error(s); "
              f"this scan is incomplete, not clean.", file=sys.stderr)
    # 'clean' stays silent: a monitor that narrates health is noise.
