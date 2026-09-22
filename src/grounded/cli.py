"""CLI for grounded. Stdlib only (argparse)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .checkers import CHECKER_DESCRIPTIONS, CHECKERS, DEFAULT_ENABLED, REMOVED_CHECKERS
from .config import Config
from .delta import (
    DEFAULT_BASELINE_NAME,
    GitError,
    changed_lines,
    changed_symbols,
    filter_changed,
    load_baseline,
    split_baselined,
    write_baseline,
)
from .models import SEVERITY_RANK, CheckerError
from .reporters import format_terminal, to_html, to_json, to_sarif
from .scanner import apply_suppressions, collect_files, scan_root, warn_unknown_suppressions


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="grounded",
        description="grounded: find dangling references in code comments. Deterministic, offline, zero dependencies.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="scan a directory for dangling references")
    s.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    s.add_argument("--format", choices=["terminal", "json", "sarif", "html"], default="terminal")
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
    s.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    s.add_argument("--quiet", "-q", action="store_true", help="only print findings count + failures")
    s.add_argument("--jobs", type=int, default=None, metavar="N",
                   help="parallel workers (default: auto by file count)")
    s.add_argument("--cache", nargs="?", const=".grounded-cache.json", default=None, metavar="FILE",
                   help="reuse per-file results keyed by mtime+size (default file: .grounded-cache.json)")

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
    return p


def _resolve_enable_disable(config: Config, enable: str | None, disable: str | None) -> Config:
    if enable:
        want = {x.strip() for x in enable.split(",") if x.strip()}
        config.enabled = {w for w in want if w in CHECKERS} or set(config.enabled)
    if disable:
        drop = {x.strip() for x in disable.split(",") if x.strip()}
        config.enabled -= drop
    if not config.enabled:
        config.enabled = set(DEFAULT_ENABLED)
    return config


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


def cmd_scan(args: argparse.Namespace) -> int:
    given = Path(args.path)
    root = given.resolve()
    if not root.exists():
        print(f"grounded: path does not exist: {args.path}", file=sys.stderr)
        return 2
    # A file argument scopes REPORTING to that file; the index is still
    # built from the whole tree so cross-file references keep resolving.
    only: str | None = None
    if root.is_file():
        try:
            only = root.relative_to(root.parent.resolve()).as_posix()
        except ValueError:
            only = root.name
        root = root.parent
    config = Config.load(root, explicit=args.config)
    if args.fail_on:
        config.fail_on = args.fail_on
    _resolve_enable_disable(config, args.enable, args.disable)

    cache_path = Path(args.cache) if args.cache else None
    if cache_path is not None and not cache_path.is_absolute():
        cache_path = root / cache_path
    checker_errors: list[CheckerError] = []
    findings, facts, index = scan_root(root, config, jobs=args.jobs, cache_path=cache_path,
                                       checker_errors=checker_errors)
    n_files = len(facts)
    n_unparsed = len(index.parse_failed)
    _report_checker_errors(checker_errors)
    for wpath, wline, wids in warn_unknown_suppressions(facts):
        print(f"grounded: warning: unknown checker id(s) in suppression at "
              f"{wpath}:{wline}: {', '.join(wids)} (known: {', '.join(sorted(CHECKERS))})",
              file=sys.stderr)
    if only is not None:
        findings = [f for f in findings if f.path == only]

    suppressed_note = ""
    facts_by_path = {f.path: f for f in facts}
    findings, n_suppressed = apply_suppressions(findings, facts_by_path)
    if n_suppressed:
        suppressed_note = f" ({n_suppressed} suppressed by grounded-disable)"
    if args.changed is not None:
        try:
            hunks, untracked = changed_lines(root, args.changed)
            symbols = changed_symbols(root, args.changed)
        except GitError as exc:
            print(f"grounded: --changed unavailable: {exc}", file=sys.stderr)
            return 2
        before = len(findings)
        findings = filter_changed(findings, hunks, untracked, symbols)
        suppressed_note = f" ({before - len(findings)} outside changed lines hidden)"
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
    if root.is_file():
        root = root.parent
    config = Config.load(root, explicit=args.config)
    _resolve_enable_disable(config, args.enable, args.disable)
    checker_errors: list[CheckerError] = []
    findings, facts, index = scan_root(root, config, checker_errors=checker_errors)
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


def cmd_fix(args: argparse.Namespace) -> int:
    from .fix import apply_fixes, apply_symbol_fixes, file_fix_candidates, symbol_fix_candidates
    given = Path(args.path)
    root = given.resolve()
    if not root.exists():
        print(f"grounded: path does not exist: {args.path}", file=sys.stderr)
        return 2
    only: str | None = None
    if root.is_file():
        try:
            only = root.relative_to(root.parent.resolve()).as_posix()
        except ValueError:
            only = root.name
        root = root.parent
    config = Config.load(root, explicit=args.config)
    findings, facts, index = scan_root(root, config)
    facts_by_path = {f.path: f for f in facts}
    findings, _ = apply_suppressions(findings, facts_by_path)
    if only is not None:
        # Never rewrite files the user did not name.
        findings = [f for f in findings if f.path == only]
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


_CLAUDE_HOOK = {
    "matcher": "Edit|Write",
    "hooks": [{"type": "command", "command": "grounded scan . --changed --quiet"}],
}

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
    )


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
    for entry in post:
        try:
            for h in entry.get("hooks", []):
                if h.get("command") == _CLAUDE_HOOK["hooks"][0]["command"]:
                    return f"hook already present in {target}"
        except AttributeError:
            continue
    post.append(dict(_CLAUDE_HOOK))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return f"wrote {target}"


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
    if root.is_file():
        root = root.parent
    config = Config.load(root, explicit=args.config)
    _, facts, index = scan_root(root, config, include_claim_surfaces=True)
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
    config = Config.load(root, explicit=args.config)
    for f in collect_files(root, config)[0]:
        try:
            print(f.relative_to(root).as_posix())
        except ValueError:
            print(str(f))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "scan":
        return cmd_scan(args)
    if args.cmd == "baseline":
        return cmd_baseline(args)
    if args.cmd == "fix":
        return cmd_fix(args)
    if args.cmd == "mcp":
        from .mcp import serve as serve_mcp
        return serve_mcp(Path(args.root).resolve())
    if args.cmd == "init-agent":
        return cmd_init_agent(args)
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
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
