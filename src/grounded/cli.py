"""CLI for grounded. Stdlib only (argparse)."""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from . import __version__
from .checkers import CHECKER_DESCRIPTIONS, CHECKERS, DEFAULT_ENABLED, REMOVED_CHECKERS
from .config import Config, ConfigError
from .delta import (
    DEFAULT_BASELINE_NAME,
    GitError,
    load_baseline,
    split_baselined,
    write_baseline,
)
from .models import SEVERITY_RANK, CheckerError
from .reporters import format_terminal, to_html, to_json, to_markdown, to_sarif
from .scanner import (
    apply_suppressions,
    collect_files,
    in_scope,
    project_root_for,
    resolve_scan_scope,
    scan_root,
    warn_unknown_suppressions,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="grounded",
        description="grounded: find dangling references in code comments. Deterministic, offline, zero dependencies.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="scan a directory for dangling references")
    s.add_argument("paths", nargs="*", default=None,
                   help="directories or files to scan (default: .); several file "
                        "arguments scope reporting to those files (used by "
                        "pass_filenames hooks)")
    s.add_argument("--format", choices=["terminal", "json", "sarif", "markdown", "html"], default="terminal")
    s.add_argument("--output", "-o", default=None, help="write report to file instead of stdout")
    s.add_argument("--fail-on", choices=["lie", "drift", "smell", "never"], default=None,
                   help="minimum severity that fails the run (default: from config, else 'lie')")
    s.add_argument("--config", default=None, help="explicit config file (grounded.toml)")
    s.add_argument("--enable", default=None, help="comma-separated checker ids to run exclusively")
    s.add_argument("--disable", default=None, help="comma-separated checker ids to skip")
    s.add_argument("--baseline", default=None, metavar="FILE",
                   help="report only findings not recorded in FILE (see 'grounded baseline')")
    s.add_argument("--show-baselined", action="store_true",
                   help="with --baseline, also list suppressed findings on stderr")
    s.add_argument("--changed", nargs="?", const="HEAD", default=None, metavar="BASE",
                   help="report only findings on lines changed vs BASE (default: HEAD, uncommitted work). "
                        "The tree is still fully scanned; reporting is filtered. Errors outside git.")
    s.add_argument("--cross-index", default=None, metavar="DIR",
                   help="verify API clients against another tree's specs too: "
                        "stale-api-ref checks this tree's clients against the union of "
                        "both trees' OpenAPI/Swagger routes (the flag itself is the "
                        "pairing evidence). Primary-tree reporting only.")
    s.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    s.add_argument("--quiet", "-q", action="store_true", help="only print findings count + failures")
    s.add_argument("--jobs", type=int, default=None, metavar="N",
                   help="parallel workers (default: auto by file count)")
    s.add_argument("--cache", nargs="?", const=".grounded-cache.json", default=None, metavar="FILE",
                   help="replay per-file results while the whole tree is unchanged "
                        "(default file: .grounded-cache.json)")
    s.add_argument("--no-index-cache", action="store_true",
                   help="rebuild the repo index from scratch instead of reusing unchanged files' "
                        "entries from the git dir (also: GROUNDED_NO_INDEX_CACHE=1)")

    sub.add_parser("init", help="write a starter grounded.toml in the current directory").add_argument(
        "--force", action="store_true", help="overwrite existing grounded.toml")

    b = sub.add_parser("baseline", help="record current findings so later scans gate on new ones only")
    b.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    b.add_argument("--output", "-o", default=None,
                   help=f"baseline file to write (default: <path>/{DEFAULT_BASELINE_NAME})")
    b.add_argument("--config", default=None, help="explicit config file (grounded.toml)")
    b.add_argument("--enable", default=None, help="comma-separated checker ids to run exclusively")
    b.add_argument("--disable", default=None, help="comma-separated checker ids to skip")

    fx = sub.add_parser("fix", help="rewrite unambiguous stale references (preview with --dry-run)")
    fx.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    fx.add_argument("--dry-run", action="store_true", help="print fixes without writing")
    fx.add_argument("--config", default=None, help="explicit config file (grounded.toml)")

    pr = sub.add_parser("pr", help="apply unambiguous fixes on a branch and open a pull request")
    pr.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    pr.add_argument("--title", default=None, help="PR title (default: generated from fix count)")
    pr.add_argument("--dry-run", action="store_true", help="print the plan and PR body without writing")
    pr.add_argument("--config", default=None, help="explicit config file (grounded.toml)")

    gr = sub.add_parser("generate-agent-rules",
                        help="write an AGENTS.md containing only verified paths and commands")
    gr.add_argument("--output", "-o", default="AGENTS.md", help="file to write (default: ./AGENTS.md)")
    gr.add_argument("--force", action="store_true", help="overwrite existing file")
    gr.add_argument("--dry-run", action="store_true", help="print without writing")

    bd = sub.add_parser("badge", help="print a Reference Integrity badge; --check gates it on a clean README")
    bd.add_argument("--check", action="store_true",
                    help="verify README code fences first (exit 1 on lies)")

    mc = sub.add_parser("mcp", help="serve grounded over stdio as an MCP server for coding agents")
    mc.add_argument("--root", default=".", help="server root; all paths stay inside it (default: .)")

    ag = sub.add_parser("init-agent", help="write agent configs (Claude/Cursor/Aider) that run grounded")
    ag.add_argument("--claude", action="store_true", help="only .claude/settings.json hook")
    ag.add_argument("--cursor", action="store_true", help="only .cursor/rules/grounded.mdc rule")
    ag.add_argument("--aider", action="store_true", help="only .aider.conf.yml lint loop")
    ag.add_argument("--force", action="store_true", help="overwrite existing generated files")
    ag.add_argument("--dry-run", action="store_true", help="print actions without writing")
    ag.add_argument("--skill", action="store_true",
                    help="install the grounded agent skill to ~/.claude/skills/grounded (all projects)")
    ag.add_argument("--skill-project", action="store_true",
                    help="install the grounded agent skill to .claude/skills/grounded (this project only)")
    ag.add_argument("--pre-commit", action="store_true",
                    help="write .pre-commit-config.yaml with the grounded hook")

    hk = sub.add_parser("hook", help="agent hook adapters (read the agent's event on stdin)")
    hk.add_argument("agent", choices=["claude-code"],
                    help="claude-code: PostToolUse hook; exits 2 with findings on stderr "
                         "so the agent sees and fixes them")
    hk.add_argument("--fail-on", choices=["lie", "drift", "smell"], default="lie",
                    help="minimum severity fed back to the agent (default: lie)")

    ls = sub.add_parser("lsp", help="serve grounded over stdio as an LSP server for editors")

    im = sub.add_parser("impact", help="show everything touching a symbol (definers, importers, claims across comments, docs, mocks, entry points)")
    im.add_argument("symbol", help="symbol name, e.g. gettext_lazy")
    im.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    im.add_argument("--format", choices=["terminal", "json"], default="terminal")
    im.add_argument("--config", default=None, help="explicit config file (grounded.toml)")

    e = sub.add_parser("explain", help="explain what a checker proves")
    e.add_argument("checker", nargs="?", default=None, help="checker id (omit to list all)")

    l = sub.add_parser("list", help="list files that would be scanned")
    l.add_argument("path", nargs="?", default=".")
    l.add_argument("--config", default=None)

    d = sub.add_parser("doctor", help="check the installation and agent wiring for staleness")
    d.add_argument("--json", action="store_true", help="machine-readable report")

    w = sub.add_parser("watch", help="rescan on every change; report only new findings (Prove-It Loop)")
    w.add_argument("path", nargs="?", default=".", help="directory to watch (default: .)")
    w.add_argument("--interval", type=float, default=2.0, metavar="SECONDS",
                   help="poll interval (default: 2.0)")
    w.add_argument("--config", default=None, help="explicit config file (grounded.toml)")
    w.add_argument("--enable", default=None, help="comma-separated checker ids to run exclusively")
    w.add_argument("--disable", default=None, help="comma-separated checker ids to skip")
    w.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    return p


def _home() -> Path:
    """Home directory, factored for tests (never writes here)."""
    return Path.home()


def _pypi_latest(timeout: float = 15.0) -> str | None:
    """Latest grounded-lint on PyPI, or None when offline. Fail-open:
    a version check must never fail a gate."""
    import json as _json
    import urllib.request
    try:
        with urllib.request.urlopen(
                "https://pypi.org/pypi/grounded-lint/json",
                timeout=timeout) as r:
            return str(_json.load(r)["info"]["version"])
    except Exception:
        return None


def _hook_wiring(home: Path) -> list[tuple[str, str]]:
    """(status, detail) for the Claude Code hook: current, legacy
    (exit-1, invisible to the model), or missing. Read-only."""
    import json as _json
    cfg = home / ".claude" / "settings.json"
    if not cfg.exists():
        return [("missing", f"no {cfg} (run: grounded init-agent --claude)")]
    try:
        data = _json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [("warn", f"{cfg} unreadable")]
    out: list[tuple[str, str]] = []
    post = (data.get("hooks") or {}).get("PostToolUse", [])
    cmds = [h.get("command", "") for e in post if isinstance(e, dict)
            for h in (e.get("hooks") or []) if isinstance(h, dict)]
    if not any("grounded" in c for c in cmds):
        out.append(("missing", "no grounded hook in PostToolUse"))
    if any(c.strip() == "grounded hook claude-code" for c in cmds):
        out.append(("ok", "grounded hook claude-code (exit-2 feedback)"))
    if any(c.strip() in _CLAUDE_LEGACY_CMDS for c in cmds):
        out.append(("stale",
                    "legacy 'grounded scan . --changed --quiet' exits 1: "
                    "findings reach you, never the model "
                    "(run: grounded init-agent --claude to upgrade)"))
    return out or [("warn", "PostToolUse has no grounded entry")]


def _resolve_enable_disable(config: Config, enable: str | None, disable: str | None) -> Config:
    if enable:
        want = {x.strip() for x in enable.split(",") if x.strip()}
        unknown = sorted(w for w in want if w not in CHECKERS)
        if unknown:
            # A typo'd id must fail, not silently run a different set:
            # `--enable stale-symobl` running the full default suite is
            # the same green-masking class as silent config defaults.
            raise ConfigError(
                f"unknown checker id(s): {', '.join(unknown)}. "
                f"Known: {', '.join(sorted(CHECKERS))}")
        config.enabled = set(want)
    if disable:
        drop = {x.strip() for x in disable.split(",") if x.strip()}
        unknown = sorted(d for d in drop if d not in CHECKERS)
        if unknown:
            raise ConfigError(
                f"unknown checker id(s): {', '.join(unknown)}. "
                f"Known: {', '.join(sorted(CHECKERS))}")
        config.enabled -= drop
    if not config.enabled:
        config.enabled = set(DEFAULT_ENABLED)
    return config


def _load_config(root: Path, explicit: str | None) -> Config:
    try:
        return Config.load(root, explicit=explicit)
    except ConfigError as exc:
        print(f"grounded: {exc}", file=sys.stderr)
        raise SystemExit(2)


def _report_checker_errors(errors: list[CheckerError]) -> None:
    """Report checkers that raised, grouped by cause.

    stderr keeps the stdout payload (JSON/SARIF/HTML) byte-identical, the way
    unknown-suppression warnings already behave. Grouping matters: one broken
    checker on 10k files is one mistake, not 10k lines of noise.
    """
    if not errors:
        return
    grouped: dict[tuple[str, str], list[str]] = {}
    for e in errors:
        grouped.setdefault((e.checker, e.message), []).append(e.path)
    for (checker_id, message), paths in sorted(grouped.items()):
        where = paths[0] if len(paths) == 1 else f"{paths[0]} (+{len(paths) - 1} more)"
        print(f"grounded: checker error: {checker_id} raised {message} at {where}",
              file=sys.stderr)
    print(f"grounded: {len(errors)} checker error(s): this scan is incomplete, not clean. "
          f"Fix the checker, or disable it explicitly with --disable <id>.", file=sys.stderr)


def _report_key(resolved: Path, root: Path) -> str:
    """Findings report repo-relative POSIX paths (scanner.py builds them the
    same way); files outside the scan root fall back to their bare name."""
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.name


def cmd_scan(args: argparse.Namespace) -> int:
    paths = [Path(p) for p in (getattr(args, "paths", None) or ["."])]
    given = paths[0]
    root = given.resolve()
    if not root.exists():
        print(f"grounded: path does not exist: {given}", file=sys.stderr)
        return 2
    # A file argument scopes REPORTING to those files; the index is built
    # from the files' project (nearest marker ancestor), not the parent
    # directory: a parent-only snapshot manufactures absence claims about
    # files it never looked at (see scanner.project_root_for). Several
    # file arguments (pre-commit batches the filenames a `pass_filenames`
    # hook receives) each scope reporting; the FIRST one anchors the
    # project root and the rest must live under it.
    only_set: set[str] | None = None
    prefix: str | None = None
    if root.is_dir():
        # A directory argument scopes reporting the same way: the index is
        # the whole project, so `scan src` and `scan .` agree on every file.
        root, prefix = resolve_scan_scope(root)
    else:
        root = project_root_for(root.parent)
        only_set = {_report_key(p.resolve(), root) for p in paths}
        for p in paths[1:]:
            rp = p.resolve()
            if not rp.exists():
                print(f"grounded: path does not exist: {p}", file=sys.stderr)
                return 2
            if rp != root and root not in rp.parents:
                print(f"grounded: all paths must share a directory tree "
                      f"({paths[0]} and {p} do not)", file=sys.stderr)
                return 2
    config = _load_config(root, explicit=args.config)
    if args.fail_on:
        config.fail_on = args.fail_on
    try:
        _resolve_enable_disable(config, args.enable, args.disable)
    except ConfigError as exc:
        print(f"grounded: {exc}", file=sys.stderr)
        return 2

    cache_path = Path(args.cache) if args.cache else None
    if cache_path is not None and not cache_path.is_absolute():
        cache_path = root / cache_path
    checker_errors: list[CheckerError] = []
    plan = None
    if args.changed is not None:
        from .changed import ChangedPlan
        try:
            plan = ChangedPlan.from_git(root, args.changed)
        except GitError as exc:
            print(f"grounded: --changed unavailable: {exc}", file=sys.stderr)
            return 2
    findings, facts, index = scan_root(root, config, jobs=args.jobs, cache_path=cache_path,
                                       checker_errors=checker_errors, changed=plan,
                                       index_cache=_index_cache_on(args))
    if args.cross_index is not None:
        from .checkers.api import check_stale_api_ref, routes_of_index
        other = Path(args.cross_index)
        other_root = other if other.is_absolute() else Path.cwd() / other
        other_root = other_root.resolve()
        if not other_root.is_dir():
            print(f"grounded: --cross-index needs a directory: {args.cross_index}",
                  file=sys.stderr)
            return 2
        if "stale-api-ref" not in config.enabled:
            print("grounded: note: --cross-index only affects stale-api-ref "
                  "(not enabled); ignoring it.", file=sys.stderr)
        else:
            # Index-only scan of the other tree (no checkers run): its
            # specs join the route set; reporting stays on this tree, so
            # either maintainer runs their own mirror.
            _, _, other_index = scan_root(
                other_root, Config(enabled=set()), checker_errors=checker_errors)
            found, other_routes = routes_of_index(other_index)
            if found:
                scope = (f"this repo's or `{args.cross_index}`'s API specs")
                cross: list = []
                for f in facts:
                    if f.language not in ("python", "javascript"):
                        continue
                    cross.extend(check_stale_api_ref(
                        f, index, extra_routes=other_routes, scope_note=scope))
                findings = ([f for f in findings if f.checker != "stale-api-ref"]
                            + cross)
    n_files = len(facts)
    n_unparsed = len(index.parse_failed)
    _report_checker_errors(checker_errors)
    for wpath, wline, wids in warn_unknown_suppressions(
            [f for f in facts if in_scope(f.path, prefix)]):
        print(f"grounded: warning: unknown checker id(s) in suppression at "
              f"{wpath}:{wline}: {', '.join(wids)} (known: {', '.join(sorted(CHECKERS))})",
              file=sys.stderr)
    if only_set is not None:
        findings = [f for f in findings if f.path in only_set]
    if prefix is not None:
        findings = [f for f in findings if in_scope(f.path, prefix)]
        n_files = sum(1 for f in facts if in_scope(f.path, prefix))

    suppressed_note = ""
    facts_by_path = {f.path: f for f in facts}
    findings, n_suppressed = apply_suppressions(findings, facts_by_path)
    if n_suppressed:
        suppressed_note = f" ({n_suppressed} suppressed by grounded-disable)"
    if plan is not None and plan.mode == "precise":
        suppressed_note += (f" (--changed: {plan.checked} file(s) checked against the base; "
                            f"findings older than the change are not shown)")
    elif plan is not None:
        suppressed_note += (f" (--changed: broad mode because {plan.reason}; "
                            f"shows findings naming any identifier the diff touches)")
    if args.baseline:
        try:
            fps = load_baseline(Path(args.baseline))
        except ValueError as exc:
            print(f"grounded: {exc}", file=sys.stderr)
            return 2
        findings, suppressed = split_baselined(findings, fps)
        suppressed_note += f" ({len(suppressed)} baselined hidden)"
        if args.show_baselined:
            for f in suppressed:
                print(f"baselined: {f.path}:{f.line} [{f.checker}] {f.title}", file=sys.stderr)

    fmt = args.format
    if fmt == "json":
        out = to_json(findings)
    elif fmt == "sarif":
        out = to_sarif(findings, root=str(root))
    elif fmt == "markdown":
        out = to_markdown(findings, n_files, n_checker_errors=len(checker_errors))
    elif fmt == "html":
        out = to_html(findings, n_files, root=str(root))
    else:
        use_color = (not args.no_color) and sys.stdout.isatty()
        if args.quiet:
            counts = {"lie": 0, "drift": 0, "smell": 0}
            for f in findings:
                counts[f.severity] += 1
            note = f", {n_unparsed} file(s) unparsed" if n_unparsed else ""
            errs = f", {len(checker_errors)} checker error(s)" if checker_errors else ""
            out = (f"grounded: {len(findings)} finding(s), {counts['lie']} lie(s), "
                   f"{counts['drift']} drift(s), {counts['smell']} smell(s) in {n_files} file(s)"
                   f"{note}{errs}.")
        else:
            out = format_terminal(findings, n_files, root=str(root), use_color=use_color,
                                  n_unparsed=n_unparsed,
                                  n_checker_errors=len(checker_errors))
    if suppressed_note and fmt in ("terminal",):
        out += f"\ngrounded:{suppressed_note}."
    elif plan is not None and plan.mode != "precise":
        # Machine formats keep stdout parseable, but a consumer (an agent
        # hook) must still learn that this report is the broad superset.
        print(f"grounded: --changed broad mode because {plan.reason}.", file=sys.stderr)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
    else:
        print(out)
    # exit code
    if config.fail_on == "never":
        return 0
    if checker_errors:
        # Distinct from 1 on purpose: a finding is a verdict about the repo;
        # a checker error means there is no verdict at all, so a pipeline can
        # tell "this repo has problems" from "this scan is not trustworthy".
        return 3
    threshold = SEVERITY_RANK.get(config.fail_on, 3)
    for f in findings:
        if SEVERITY_RANK.get(f.severity, 0) >= threshold:
            return 1
    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    if not root.exists():
        print(f"grounded: path does not exist: {args.path}", file=sys.stderr)
        return 2
    root, prefix = resolve_scan_scope(root)
    config = _load_config(root, explicit=args.config)
    try:
        _resolve_enable_disable(config, args.enable, args.disable)
    except ConfigError as exc:
        print(f"grounded: {exc}", file=sys.stderr)
        return 2
    checker_errors: list[CheckerError] = []
    findings, facts, index = scan_root(root, config, checker_errors=checker_errors,
                                       index_cache=_index_cache_on(args))
    findings = [f for f in findings if in_scope(f.path, prefix)]
    if checker_errors:
        # A baseline is a persisted scan result: writing one from an
        # incomplete scan bakes permanent blind spots into every later gate.
        _report_checker_errors(checker_errors)
        print("grounded: refusing to write a baseline from an incomplete scan.",
              file=sys.stderr)
        return 3
    findings, _ = apply_suppressions(findings, {f.path: f for f in facts})
    target = Path(args.output) if args.output else (root / DEFAULT_BASELINE_NAME)
    stats = write_baseline(target, findings)
    if target.exists() and (stats["added"] or stats["removed"]):
        print(f"grounded: wrote {target}: {stats['total']} recorded "
              f"(+{stats['added']} new, -{stats['removed']} stale removed)")
    else:
        print(f"grounded: wrote {target}: {stats['total']} recorded")
    print("grounded: commit this file; scans with --baseline gate on new findings only.")
    return 0


def _index_cache_on(args: argparse.Namespace) -> bool:
    if getattr(args, "no_index_cache", False):
        return False
    return os.environ.get("GROUNDED_NO_INDEX_CACHE", "") in ("", "0")


def cmd_fix(args: argparse.Namespace) -> int:
    from .fix import apply_fixes, apply_symbol_fixes, file_fix_candidates, symbol_fix_candidates
    given = Path(args.path)
    root = given.resolve()
    if not root.exists():
        print(f"grounded: path does not exist: {args.path}", file=sys.stderr)
        return 2
    root, only = resolve_scan_scope(root)
    config = _load_config(root, explicit=args.config)
    findings, facts, index = scan_root(root, config, index_cache=_index_cache_on(args))
    facts_by_path = {f.path: f for f in facts}
    findings, _ = apply_suppressions(findings, facts_by_path)
    # Never rewrite files outside the path the user named.
    findings = [f for f in findings if in_scope(f.path, only)]
    fixes = file_fix_candidates(findings, root, config=config)
    sym_fixes = symbol_fix_candidates(findings, root, index)
    if not fixes and not sym_fixes:
        print("grounded fix: nothing unambiguous to rewrite.")
        return 0
    for f, replacement, ln in fixes:
        print(f"{'would rewrite' if args.dry_run else 'rewrote'} "
              f"{f.path}:{ln}: {f.claim} -> {replacement}")
    for f, old_seg, new_seg, ln in sym_fixes:
        print(f"{'would rewrite' if args.dry_run else 'rewrote'} "
              f"{f.path}:{ln}: {old_seg}() -> {new_seg}()")
    n = apply_fixes(root, fixes, dry_run=args.dry_run)
    n += apply_symbol_fixes(root, sym_fixes, dry_run=args.dry_run)
    print(f"grounded fix: {n} file(s) {'would change' if args.dry_run else 'changed'}.")
    return 0


def _pr_body(fixes: list, sym_fixes: list) -> str:
    """PR body listing every mechanical rewrite with its evidence."""
    lines = ["# fix(integrity): update stale references",
             "",
             "Mechanical rewrites only — every item below was unambiguous "
             "(exactly one rename candidate, same-directory preferred) and "
             "no runtime logic was touched.",
             ""]
    for f, replacement, ln in fixes:
        lines.append(f"- `{f.path}:{ln}`: `{f.claim}` -> `{replacement}` "
                     f"[{f.checker}]")
    for f, old_seg, new_seg, ln in sym_fixes:
        lines.append(f"- `{f.path}:{ln}`: `{old_seg}()` -> `{new_seg}()` "
                     f"[{f.checker}]")
    lines += ["",
              "---",
              "Generated mechanically by Grounded (reference integrity "
              "firewall). Each line above cites the finding it resolves; "
              "revert any single line without affecting the rest."]
    return "\n".join(lines)


def cmd_pr(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone
    from .delta import GitError, _git
    from .fix import apply_fixes, apply_symbol_fixes, file_fix_candidates, symbol_fix_candidates
    given = Path(args.path)
    root = given.resolve()
    if not root.exists():
        print(f"grounded: path does not exist: {args.path}", file=sys.stderr)
        return 2
    root, only = resolve_scan_scope(root)
    config = _load_config(root, explicit=args.config)
    findings, facts, index = scan_root(root, config, index_cache=_index_cache_on(args))
    facts_by_path = {f.path: f for f in facts}
    findings, _ = apply_suppressions(findings, facts_by_path)
    findings = [f for f in findings if in_scope(f.path, only)]
    fixes = file_fix_candidates(findings, root, config=config)
    sym_fixes = symbol_fix_candidates(findings, root, index)
    if not fixes and not sym_fixes:
        print("grounded pr: nothing unambiguous to rewrite.")
        return 0
    total = len(fixes) + len(sym_fixes)
    title = args.title or f"fix(integrity): update {total} stale reference(s)"
    body = _pr_body(fixes, sym_fixes)
    if args.dry_run:
        print(body)
        return 0
    import shutil
    import subprocess
    if shutil.which("git") is None or shutil.which("gh") is None:
        print("grounded pr: needs `git` and `gh` on PATH "
              "(https://cli.github.com).", file=sys.stderr)
        return 2
    try:
        status = _git(root, "status", "--porcelain=v1", "--untracked-files=no")
    except GitError as exc:
        print(f"grounded pr: not a git repo or git failed: {exc}", file=sys.stderr)
        return 2
    if status.strip():
        print("grounded pr: working tree is dirty; commit or stash first "
              "(refusing to mix your edits with mechanical fixes).", file=sys.stderr)
        return 2
    try:
        base = _git(root, "branch", "--show-current").strip() or "main"
    except GitError:
        base = "main"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    branch = f"grounded-fixes-{stamp}"
    try:
        apply_fixes(root, fixes, dry_run=False)
        apply_symbol_fixes(root, sym_fixes, dry_run=False)
        changed = _git(root, "status", "--porcelain=v1", "--untracked-files=no")
        if not changed.strip():
            print("grounded pr: fixes applied cleanly but tree unchanged; "
                  "nothing to propose.", file=sys.stderr)
            return 0
        _git(root, "checkout", "-b", branch)
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", title)
        _git(root, "push", "-u", "origin", branch)
    except GitError as exc:
        print(f"grounded pr: git failed: {exc}", file=sys.stderr)
        return 2
    try:
        proc = subprocess.run(
            ["gh", "pr", "create", "--title", title, "--body", body,
             "--base", base, "--head", branch],
            cwd=root, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"grounded pr: branch {branch} pushed, but `gh pr create` "
              f"failed: {exc}", file=sys.stderr)
        return 2
    if proc.returncode != 0:
        print(f"grounded pr: branch {branch} pushed, but `gh pr create` "
              f"failed: {(proc.stderr or proc.stdout).strip()[:300]}", file=sys.stderr)
        return 2
    print(proc.stdout.strip())
    return 0


_CLAUDE_HOOK_CMD = "grounded hook claude-code"
_CLAUDE_HOOK = {
    "matcher": "Edit|Write|MultiEdit",
    "hooks": [{"type": "command", "command": _CLAUDE_HOOK_CMD}],
}
# Commands earlier versions installed. They exited 1 on findings, which
# Claude Code shows to the human but never to the model; init-agent
# upgrades them in place.
_CLAUDE_LEGACY_CMDS = frozenset({"grounded scan . --changed --quiet"})

_CURSOR_RULE = """---
description: Verify code references with grounded before building on edited code
alwaysApply: false
---

After editing source files, run `grounded scan . --changed` and fix
reported lies (dangling function names, missing files) before running
tests or committing. For agents over MCP, call the `check_path` tool
on edited files instead of shelling out.
"""

_AIDER_CONF = """# Aider: lint edited files with grounded (verified contract: filenames
# in, non-zero exit on findings).
lint-cmd: "sh -c 'for f; do grounded scan \"$f\" --quiet || exit 1; done' sh"
"""


def _precommit_conf() -> str:
    return (
        "# Grounded: fail commits carrying new dangling references.\n"
        "# Keep the rev current with: pre-commit autoupdate\n"
        "repos:\n"
        "  - repo: https://github.com/gonisulaimann/Grounded\n"
        f"    rev: v{__version__}\n"
        "    hooks:\n"
        "      - id: grounded\n"
        "      - id: grounded-fences\n"
    )


def _agent_rules_text(root: Path) -> str:
    """AGENTS.md content where every path exists and every command was
    read from a real file. Nothing is inferred, guessed, or templated:
    a claim the tree cannot prove is omitted, so the file cannot rot at
    birth. Re-run after restructuring (or let the pre-commit hook remind
    you: stale paths in here are exactly what stale-file-ref catches)."""
    import json as _json
    lines = ["# Agent rules (generated by `grounded generate-agent-rules`)",
             "",
             "Every path below was verified to exist and every command was",
             "read from a real config file when this was generated. Re-run",
             "`grounded generate-agent-rules --force` after restructuring.",
             ""]
    lines.append("## Layout")
    try:
        kids = sorted(p for p in root.iterdir()
                      if p.is_dir() and not p.name.startswith(".")
                      and p.name not in {"node_modules", "__pycache__", "dist",
                                         "build", "vendor", "target"})
    except OSError:
        kids = []
    if kids:
        for d in kids[:12]:
            lines.append(f"- `{d.name}/`")
    else:
        lines.append("- (no top-level directories found)")
    lines.append("")
    cmds: list[tuple[str, str]] = []  # (command, source)
    pj = root / "package.json"
    if pj.is_file():
        try:
            scripts = (_json.loads(pj.read_text(encoding="utf-8")) or {}).get("scripts") or {}
        except ValueError:
            scripts = {}
        if isinstance(scripts, dict):
            for name in ("test", "lint", "build", "start"):
                if isinstance(scripts.get(name), str):
                    cmds.append((f"npm run {name}", "package.json scripts"))
    for makefile in ("Makefile", "makefile", "GNUmakefile", "justfile", "Justfile"):
        mf = root / makefile
        if not mf.is_file():
            continue
        try:
            text = mf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            m = re.match(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*)\s*:(?:[^=]|$)", line)
            if m and m.group(1) not in (".PHONY",):
                runner = "just" if "just" in makefile.lower() else "make"
                cmds.append((f"{runner} {m.group(1)}", makefile))
                if len(cmds) >= 8:
                    break
        if len(cmds) >= 8:
            break
    if (root / ".github" / "workflows").is_dir():
        try:
            wfs = sorted(p.name for p in (root / ".github" / "workflows").iterdir()
                         if p.suffix in (".yml", ".yaml"))[:4]
        except OSError:
            wfs = []
        if wfs:
            cmds.append((f"CI runs on push ({', '.join(wfs)})", ".github/workflows"))
    lines.append("## Commands")
    if cmds:
        seen: set[str] = set()
        for cmd, src in cmds:
            if cmd not in seen:
                seen.add(cmd)
                lines.append(f"- `{cmd}` ({src})")
    else:
        lines.append("- (no test/lint/build commands discovered in manifests)")
    lines += ["",
              "## Reference integrity (always true)",
              "",
              "- After editing, run `grounded scan . --changed` and fix lies",
              "  before tests or commits.",
              "- `grounded impact SYMBOL` lists everything touching a name",
              "  before you rename it.",
              "- A finding names claim, evidence, and fix: act on evidence,",
              "  never on the model's memory of the code.",
              ""]
    return "\n".join(lines)


_BADGE_MD = ("[![Reference Integrity]"
              "(https://img.shields.io/badge/Reference%20Integrity-Grounded-brightgreen)]"
              "(https://github.com/gonisulaimann/Grounded)")


def cmd_badge(args: argparse.Namespace) -> int:
    if args.check:
        from .scanner import scan_root
        root = Path.cwd()
        config = _load_config(root, explicit=None)
        config.enabled = (set(config.enabled)
                          | {"stale-doc-ref", "unclosed-fence"})
        findings, _, index = scan_root(root, config)
        readme = [f for f in findings if f.path == "README.md"
                  and f.severity == "lie"]
        if readme:
            print(f"grounded badge: README has {len(readme)} unverified "
                  f"code claim(s); fix them before displaying the badge.",
                  file=sys.stderr)
            for f in readme:
                print(f"  README.md:{f.line} [{f.checker}] {f.title}",
                      file=sys.stderr)
            return 1
    print(_BADGE_MD)
    return 0


def cmd_generate_agent_rules(args: argparse.Namespace) -> int:
    root = Path.cwd()
    target = root / (args.output or "AGENTS.md")
    if target.exists() and not args.force:
        print(f"grounded: {target} already exists (use --force to overwrite)",
              file=sys.stderr)
        return 2
    text = _agent_rules_text(root)
    if args.dry_run:
        print(text)
        return 0
    target.write_text(text, encoding="utf-8")
    print(f"grounded: wrote {target} (every path verified, every command read from config)")
    return 0


def _init_precommit(root: Path, force: bool, dry_run: bool) -> str:
    # Same no-merge rule as Aider: without a YAML library, merging into
    # an existing config risks corrupting it, so existing files win.
    target = root / ".pre-commit-config.yaml"
    if target.exists() and not force:
        return f"exists, kept (use --force): {target}"
    if dry_run:
        return f"would write {target}"
    target.write_text(_precommit_conf(), encoding="utf-8")
    return f"wrote {target}"


def _init_claude(root: Path, force: bool, dry_run: bool) -> str:
    import json
    target = root / ".claude" / "settings.json"
    if dry_run:
        return f"would merge hook into {target}"
    data: dict = {}
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except ValueError:
            return f"refusing to touch invalid JSON: {target}"
        if not isinstance(data, dict):
            return f"refusing to touch non-object JSON: {target}"
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return f"refusing to touch non-object hooks in: {target}"
    post = hooks.setdefault("PostToolUse", [])
    if not isinstance(post, list):
        return f"refusing to touch non-list PostToolUse in: {target}"
    upgraded = False
    for entry in post:
        try:
            for h in entry.get("hooks", []):
                if h.get("command") == _CLAUDE_HOOK_CMD:
                    return f"hook already present in {target}"
                if h.get("command") in _CLAUDE_LEGACY_CMDS:
                    h["command"] = _CLAUDE_HOOK_CMD
                    entry["matcher"] = _CLAUDE_HOOK["matcher"]
                    upgraded = True
        except AttributeError:
            continue
    if not upgraded:
        post.append(json.loads(json.dumps(_CLAUDE_HOOK)))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return f"{'upgraded hook in' if upgraded else 'wrote'} {target}"


def _init_cursor(root: Path, force: bool, dry_run: bool) -> str:
    target = root / ".cursor" / "rules" / "grounded.mdc"
    if target.exists() and not force:
        return f"exists, kept (use --force): {target}"
    if dry_run:
        return f"would write {target}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_CURSOR_RULE, encoding="utf-8")
    return f"wrote {target}"


def _init_aider(root: Path, force: bool, dry_run: bool) -> str:
    # YAML is appended to, never parsed: without a YAML library, merging
    # into an existing config risks corrupting it, so existing files win.
    target = root / ".aider.conf.yml"
    if target.exists() and not force:
        return (f"exists, kept: {target} (add lint-cmd manually: "
                f"{_AIDER_CONF.strip().splitlines()[-1].strip()})")
    if dry_run:
        return f"would write {target}"
    target.write_text(_AIDER_CONF, encoding="utf-8")
    return f"wrote {target}"


_SKILL_DIR_NAME = "grounded"


def _skill_source() -> Path | None:
    src = Path(__file__).resolve().parent / "skill"
    if (src / "SKILL.md").exists():
        return src
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        bundle = Path(sys._MEIPASS) / "grounded" / "skill"
        if (bundle / "SKILL.md").exists():
            return bundle
    return None


def _install_skill(dest: Path, force: bool, dry_run: bool) -> tuple[str, bool]:
    src = _skill_source()
    if src is None:
        return ("skill source missing from install (reinstall grounded-lint)", False)
    files = sorted(p for p in src.rglob("*") if p.is_file())
    if dry_run:
        return (f"would install skill ({len(files)} files) to {dest}", True)
    kept, wrote = 0, 0
    for path in files:
        target = dest / path.relative_to(src)
        if target.exists() and not force:
            kept += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        wrote += 1
    if wrote == 0:
        return (f"skill already installed, kept (use --force): {dest}", True)
    extra = f", {kept} kept" if kept else ""
    return (f"installed skill to {dest} ({wrote} files{extra})", True)


def cmd_init_agent(args: argparse.Namespace) -> int:
    root = Path.cwd()
    want_all = not (args.claude or args.cursor or args.aider or args.skill or args.skill_project
                    or args.pre_commit)
    results = []
    ok = True
    if args.claude or want_all:
        results.append(_init_claude(root, args.force, args.dry_run))
    if args.cursor or want_all:
        results.append(_init_cursor(root, args.force, args.dry_run))
    if args.aider or want_all:
        results.append(_init_aider(root, args.force, args.dry_run))
    if args.skill:
        msg, good = _install_skill(
            Path.home() / ".claude" / "skills" / _SKILL_DIR_NAME, args.force, args.dry_run)
        results.append(msg)
        ok = ok and good
    if args.skill_project:
        msg, good = _install_skill(
            root / ".claude" / "skills" / _SKILL_DIR_NAME, args.force, args.dry_run)
        results.append(msg)
        ok = ok and good
    if args.pre_commit:
        results.append(_init_precommit(root, args.force, args.dry_run))
    for line in results:
        print(f"grounded init-agent: {line}")
    return 0 if ok else 2


def cmd_impact(args: argparse.Namespace) -> int:
    from .graph import ClaimGraph
    root = Path(args.path).resolve()
    if not root.exists():
        print(f"grounded: path does not exist: {args.path}", file=sys.stderr)
        return 2
    root, _prefix = resolve_scan_scope(root)
    config = _load_config(root, explicit=args.config)
    _, facts, index = scan_root(root, config, include_claim_surfaces=True,
                                index_cache=_index_cache_on(args))
    result = ClaimGraph(index, {f.path: f for f in facts}).blast_radius(args.symbol)
    if args.format == "json":
        import json as _json
        print(_json.dumps(result, indent=2))
    else:
        print(f"impact of `{args.symbol}`:")
        for key in ("defined_in", "imported_by", "claimed_by"):
            items = result[key]
            print(f"  {key} ({len(items)}):")
            for item in items[:20]:
                print(f"    {item}")
            if len(items) > 20:
                print(f"    ... and {len(items) - 20} more")
        if not any(result[k] for k in ("defined_in", "imported_by", "claimed_by")):
            print("  nothing references this symbol anywhere.")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    target = Path.cwd() / "grounded.toml"
    if target.exists() and not args.force:
        print(f"grounded: {target} already exists (use --force to overwrite)", file=sys.stderr)
        return 2
    target.write_text(
        '# grounded configuration\n'
        '# Uncomment to disable noisy checkers, or set fail_on to drift/smell/never.\n\n'
        '# disable = ["fragile-anchor"]\n'
        '# fail_on = "lie"\n'
        '# ignore_dirs = ["docs"]\n',
        encoding="utf-8",
    )
    print(f"grounded: wrote {target}")
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    if not args.checker:
        for cid in sorted(CHECKERS):
            print(f"{cid:18} {CHECKER_DESCRIPTIONS[cid]}")
        print("\nseverities: lie (error, provably false) > drift (warning, stale by evidence) > smell (note, fragile, will rot)")
        return 0
    cid = args.checker
    if cid in REMOVED_CHECKERS:
        print(f"{cid}\n  {REMOVED_CHECKERS[cid]}")
        return 0
    if cid not in CHECKERS:
        print(f"grounded: unknown checker {cid!r}. Known: {', '.join(sorted(CHECKERS))}", file=sys.stderr)
        return 2
    print(f"{cid}\n  {CHECKER_DESCRIPTIONS[cid]}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    config = _load_config(root, explicit=args.config)
    for f in collect_files(root, config)[0]:
        try:
            print(f.relative_to(root).as_posix())
        except ValueError:
            print(str(f))
    return 0


def _mcp_probe() -> tuple[str, str]:
    """MCP handshake over a subprocess (initialize + tools/list).
    Fail-open: any problem is a warning, never an exception."""
    import subprocess as _sp
    try:
        init = ('{"jsonrpc":"2.0","id":1,"method":"initialize",'
                '"params":{"protocolVersion":"2025-06-18","capabilities":{},'
                '"clientInfo":{"name":"grounded-doctor","version":"0"}}}\n')
        lst = ('{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n')
        proc = _sp.run([sys.executable, "-m", "grounded", "mcp"],
                       input=init + lst,
                       capture_output=True, text=True, timeout=25)
        lines = (proc.stdout or "").splitlines()
        if any('"tools"' in ln for ln in lines):
            return ("ok", "MCP server answers (initialize + tools/list)")
        return ("warn", "MCP server did not answer tools/list")
    except Exception as exc:
        return ("warn", f"MCP server probe failed: {exc}")


def cmd_watch(args: argparse.Namespace) -> int:
    from .watch import run_watch
    root = Path(args.path).resolve()
    if not root.exists():
        print(f"grounded: path does not exist: {args.path}", file=sys.stderr)
        return 2
    if root.is_file():
        root = root.parent
    config = _load_config(root, explicit=args.config)
    try:
        _resolve_enable_disable(config, args.enable, args.disable)
    except ConfigError as exc:
        print(f"grounded: {exc}", file=sys.stderr)
        return 2
    try:
        return run_watch(root, config, interval=args.interval,
                         use_color=(False if args.no_color else None))
    except KeyboardInterrupt:
        print("grounded watch: stopped.", file=sys.stderr)
        return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Installation + agent-wiring health. Read-only, fail-open on
    network: a diagnostic must never fail a gate. Exits 0 when healthy,
    1 when anything needs attention."""
    import json as _json
    import subprocess as _sp
    rows: list[tuple[str, str]] = [("info", f"engine {__version__}")]
    latest = _pypi_latest()
    if latest is None:
        rows.append(("warn", "PyPI unreachable (offline?): latest version unknown"))
    elif latest == __version__:
        rows.append(("ok", f"PyPI latest is {latest}: this install is current"))
    else:
        rows.append(("warn", f"PyPI latest is {latest}: reinstall to upgrade "
                             "(pipx upgrade grounded-lint / uv tool upgrade grounded-lint)"))
    try:
        sub = [a for a in build_parser()._actions
               if type(a).__name__ == "_SubParsersAction"]
        has_hook = "hook" in (sub[0].choices if sub else {})
    except Exception:
        has_hook = False
    rows.append(("ok", "hook adapter present (grounded hook claude-code)")
                if has_hook else
                ("stale", "no hook adapter: this binary predates agent feedback "
                          "(reinstall from a current release)"))
    rows.extend(_hook_wiring(_home()))
    skill = _home() / ".claude" / "skills" / "grounded" / "SKILL.md"
    rows.append(("ok", f"agent skill installed ({skill})") if skill.exists() else
                ("info", "agent skill not installed "
                         "(optional: grounded init-agent --skill)"))
    rows.append(_mcp_probe())
    bad = any(s in ("warn", "stale", "missing") for s, _ in rows)
    if args.json:
        print(_json.dumps([{"status": s, "detail": d} for s, d in rows], indent=2))
    else:
        for s, d in rows:
            print(f"grounded doctor [{s}]: {d}")
    if bad:
        print("grounded doctor: issues found above (exit 1 is diagnostic, not a verdict).",
              file=sys.stderr if args.json else sys.stdout)
    else:
        print("grounded doctor: healthy.",
              file=sys.stderr if args.json else sys.stdout)
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "scan":
        return cmd_scan(args)
    if args.cmd == "baseline":
        return cmd_baseline(args)
    if args.cmd == "fix":
        return cmd_fix(args)
    if args.cmd == "pr":
        return cmd_pr(args)
    if args.cmd == "generate-agent-rules":
        return cmd_generate_agent_rules(args)
    if args.cmd == "badge":
        return cmd_badge(args)
    if args.cmd == "mcp":
        from .mcp import serve as serve_mcp
        return serve_mcp(Path(args.root).resolve())
    if args.cmd == "init-agent":
        return cmd_init_agent(args)
    if args.cmd == "hook":
        from .hooks import claude_code
        code, message = claude_code(sys.stdin.read(), fail_on=args.fail_on)
        if message:
            print(message, file=sys.stderr)
        return code
    if args.cmd == "lsp":
        from .lsp import serve as serve_lsp
        return serve_lsp()
    if args.cmd == "impact":
        return cmd_impact(args)
    if args.cmd == "init":
        return cmd_init(args)
    if args.cmd == "explain":
        return cmd_explain(args)
    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "doctor":
        return cmd_doctor(args)
    if args.cmd == "watch":
        return cmd_watch(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
