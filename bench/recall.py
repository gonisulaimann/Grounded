"""Repo-scale recall: replay the precision corpus inside real repositories.

The corpus (`corpus/run.py`) proves each checker fires on the smallest tree
that shows the behavior. That is isolation truth: it says the checker *can*
fire, and says nothing about whether it still fires with real context around
it — a definition elsewhere in the tree, a manifest that declares the package,
a build directory that looks generated. Real-repo context can only ever
*silence* a finding, so the corpus is structurally unable to measure it.

This harness measures exactly that, by planting each firing corpus case into a
copy of a real repository and checking that the expected finding still appears:

    python3 bench/recall.py /path/to/repo [...] [--json out.json]
                            [--report-only] [--case ID ...]

Each plant *is* a corpus case, so the rot is known-rot by construction (CI
already gates that it fires in isolation) and no expectation is reinvented
here. Three properties keep the number honest:

* **Root-relative planting.** Cases are copied to the same relative paths they
  have inside the case directory, because several of them depend on
  repo-root-relative semantics: `src-layout` needs the `src/` layout
  detection, `mock-stale` needs `@patch("app.services...")` to resolve from
  the module root, `entrypoint-stale` needs a top-level `pyproject.toml`.
  Verified 2026-09-22: nested one directory deeper, those three stop firing
  while the case still fires in isolation — an artifact of the planting, not
  recall loss, and measuring it as a miss would have been a lie.
* **One case at a time.** Cases are planted, measured and removed
  individually, so two fixtures sharing a directory (`pkg/`) cannot interfere.
  The cost is one scan per case.
* **A known fence state.** The doc checkers are fence-state machines, so a
  host file that ends inside an unclosed fence inverts the state for every
  appended line. Measured 2026-09-22: this repo's own `README.md` had 49
  fences with one never closed, and the two `stale-cli-ref` cases reported as
  misses — the rot had fired in isolation and the *host's* dangling block had
  swallowed the planted invocation. A merge therefore closes a dangling fence
  before appending, and every such host is listed in the report, because an
  unbalanced host is a real defect and hiding it would make the measurement
  quietly easier.

Outcomes are three-way, never two: **caught**, **missed**, and **not planted**
when the host already has a file at that path (a fixture may not overwrite the
host's own `pyproject.toml` — that would change what the host *is*). `not
planted` is excluded from recall rather than silently counted as a failure.
Prose collisions are the exception: a doc fixture whose file already exists is
**merged** into the host's own file, because every real repository has a
`README.md` and the rot (a fenced example calling an absent symbol) is just as
real sitting at the end of the host's prose. Structured formats are never
merged — appending to TOML or JSON only corrupts them.

Findings are compared as a delta against a baseline scan of the pristine tree,
so a pre-existing finding is never mistaken for a catch. Incidental findings
caused by the plant are ignored: precision is what the corpus and a plain
baseline scan measure, recall is what this measures.

Exit codes: `0` when every planted expectation was caught, `1` on any miss or
any checker that raised (recall computed with a crashed checker is not a
measurement), `2` on usage/environment error. `--report-only` always exits `0`.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from grounded.checkers import CHECKERS  # noqa: E402
from grounded.config import Config  # noqa: E402
from grounded.models import CheckerError  # noqa: E402
from grounded.scanner import collect_files, scan_root  # noqa: E402

CASES = REPO / "corpus" / "cases"
# Mirrors the scanner's own ignore set, so the copy is scanned exactly like the
# original; a divergence here would surface as phantom recall misses.
COPY_IGNORE = shutil.ignore_patterns(
    ".git", ".hg", ".svn", ".venv", "node_modules", "__pycache__", ".mypy_cache")
# Prose can be merged into a host file that already exists; structured formats
# cannot. Matches the suffixes the scanner collects for the doc checkers.
MERGEABLE = {".md", ".markdown", ".mdc"}
# The same fence toggle the doc checkers use. Kept byte-identical to theirs on
# purpose: the point is to reproduce the state machine the checkers actually
# run, not an idealized Markdown parser.
FENCE = re.compile(r"^(`{3,}|~{3,})\s*([A-Za-z0-9_+-]*)\s*$")


def firing_cases(only: list[str] | None = None) -> list[tuple[str, list[dict]]]:
    """(case id, expected findings) for cases that plant known rot."""
    out: list[tuple[str, list[dict]]] = []
    for case in sorted(p for p in CASES.iterdir() if p.is_dir()):
        if only and case.name not in only:
            continue
        manifest = case / "expected.json"
        if not manifest.exists():
            continue
        expect = json.loads(manifest.read_text(encoding="utf-8")).get("expect", [])
        if expect:
            out.append((case.name, expect))
    return out


def scan(root: Path) -> tuple[list, list[CheckerError]]:
    """Scan every checker; return (findings, checker failures)."""
    errors: list[CheckerError] = []
    findings, _, _ = scan_root(root, Config(enabled=set(CHECKERS)),
                               checker_errors=errors)
    return findings, errors


def ends_inside_fence(text: str) -> bool:
    """True when a Markdown file's last fence is never closed.

    Faithful to GFM — an unterminated fence runs to EOF — which is exactly why
    it matters here: prose appended to such a file lands *inside* the host's
    dangling block, so a planted invocation is no longer parsed as one.
    """
    inside = False
    for line in text.splitlines():
        if FENCE.match(line.strip()):
            inside = not inside
    return inside


def plant(case_id: str, into: Path,
          ) -> tuple[list[str], list[str], dict[str, bytes], list[str]]:
    """Plant a case root-relative.

    Returns `(created, skipped, merged originals, hosts whose dangling fence
    had to be closed first)`.
    """
    case = CASES / case_id
    created: list[str] = []
    skipped: list[str] = []
    merged: dict[str, bytes] = {}
    closed: list[str] = []
    for src in sorted(p for p in case.rglob("*") if p.is_file()):
        rel = src.relative_to(case).as_posix()
        if rel == "expected.json":
            continue
        dest = into / rel
        if dest.exists():
            if dest.suffix.lower() not in MERGEABLE:
                skipped.append(rel)
                continue
            host = dest.read_bytes()
            merged[rel] = host
            separator = b"\n\n"
            if ends_inside_fence(host.decode("utf-8", "replace")):
                # Close the host's dangling fence so the plant starts in a
                # known state; otherwise the host's own defect decides the
                # outcome and reports as a recall miss.
                separator = b"\n\n```\n\n"
                closed.append(rel)
            dest.write_bytes(host + separator + src.read_bytes())
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        created.append(rel)
    return created, skipped, merged, closed


def unplant(into: Path, created: list[str], merged: dict[str, bytes]) -> None:
    """Undo a plant: delete what was created, restore what was merged."""
    for rel in created:
        try:
            (into / rel).unlink()
        except OSError:
            pass
    for rel, original in merged.items():
        try:
            (into / rel).write_bytes(original)
        except OSError:
            pass
    for rel in sorted({str(Path(p).parent) for p in created}):
        directory = into / rel
        while directory != into and directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
            directory = directory.parent


def run_repo(root: Path, cases: list[tuple[str, list[dict]]]) -> dict:
    baseline, errors = scan(root)
    baseline_keys = {(f.checker, f.path, f.line) for f in baseline}
    results: list[dict] = []
    unbalanced: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="grounded-recall-") as td:
        copy = Path(td) / root.name
        shutil.copytree(root, copy, ignore=COPY_IGNORE, symlinks=True)
        for case_id, expect in cases:
            created, skipped, merged, closed = plant(case_id, copy)
            unbalanced.update(closed)
            findings, raised = scan(copy)
            errors.extend(raised)
            delta = [f for f in findings
                     if (f.checker, f.path, f.line) not in baseline_keys]
            measurable = set(created) | set(merged)
            for e in expect:
                match = [f for f in delta if f.checker == e["checker"]
                         and f.path == e["path"]]
                hit = [f for f in match if e.get("contains", "") in f.title]
                outcome, detail = "missed", ""
                if e["path"] in skipped:
                    outcome, detail = "not-planted", "host already has this path"
                elif e["path"] not in measurable:
                    outcome, detail = "not-planted", "fixture file absent"
                elif hit:
                    outcome = "caught"
                    if e["path"] in merged:
                        detail = "merged into the host's own file"
                        if e["path"] in closed:
                            detail += "; host's unclosed fence closed first"
                elif not match:
                    detail = "no finding on that path"
                else:
                    detail = f"{len(match)} finding(s) on the path, title changed"
                results.append({
                    "case": case_id, "checker": e["checker"], "path": e["path"],
                    "expected_line": e.get("line"),
                    "observed_line": hit[0].line if hit else None,
                    "outcome": outcome, "detail": detail,
                })
            unplant(copy, created, merged)
    return {
        "repo": root.name,
        "files": len(collect_files(root, Config(enabled=set(CHECKERS)))[0]),
        "results": results,
        "unbalanced_hosts": sorted(unbalanced),
        "checker_errors": [e.to_dict() for e in errors],
    }


def report(reports: list[dict]) -> tuple[dict[str, list[int]], int, int]:
    """Print tables; return (per-checker [caught, missed, not-planted], misses, skipped)."""
    per_checker: dict[str, list[int]] = {}
    misses = skipped = 0
    print(f"{'repo':<22} {'files':>7} {'caught':>7} {'missed':>7} {'n/p':>5} {'recall':>7}")
    for rep in reports:
        rows = rep["results"]
        caught = sum(1 for r in rows if r["outcome"] == "caught")
        missed = [r for r in rows if r["outcome"] == "missed"]
        not_planted = sum(1 for r in rows if r["outcome"] == "not-planted")
        measurable = caught + len(missed)
        pct = 100.0 * caught / measurable if measurable else 100.0
        print(f"{rep['repo']:<22} {rep['files']:>7} {caught:>7} {len(missed):>7} "
              f"{not_planted:>5} {pct:>6.0f}%")
        for r in rows:
            tally = per_checker.setdefault(r["checker"], [0, 0, 0])
            index = {"caught": 0, "missed": 1, "not-planted": 2}[r["outcome"]]
            tally[index] += 1
            if r["outcome"] == "missed":
                misses += 1
                print(f"    MISS {r['checker']:<20} {r['case']:<22} {r['path']}  ({r['detail']})")
            elif r["outcome"] == "not-planted":
                skipped += 1
    print("\nper checker (caught / missed / not-planted, all repos):")
    for checker in sorted(per_checker):
        caught, missed, not_planted = per_checker[checker]
        flag = "   <-- RECALL GAP" if missed else ""
        print(f"  {checker:<22} {caught:>3} / {missed:<3} / {not_planted:<3}{flag}")
    hosts = sorted({(rep["repo"], h) for rep in reports for h in rep["unbalanced_hosts"]})
    if hosts:
        print("\nhosts with an unclosed fence (a defect in the repo, not a recall miss;")
        print("closed before merging so the plant's context is well-formed):")
        for repo, host in hosts:
            print(f"  {repo}/{host}")
    return per_checker, misses, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repos", nargs="+", type=Path,
                        help="repository paths to measure recall against")
    parser.add_argument("--json", type=Path, default=None,
                        help="also write the full result document here")
    parser.add_argument("--report-only", action="store_true",
                        help="always exit 0, even with misses")
    parser.add_argument("--case", action="append", default=None,
                        help="only this corpus case (repeatable)")
    args = parser.parse_args(argv)

    missing = [r for r in args.repos if not r.is_dir()]
    if missing:
        for r in missing:
            print(f"recall: not a directory: {r}", file=sys.stderr)
        return 2
    cases = firing_cases(args.case)
    if not cases:
        print("recall: no firing corpus cases selected", file=sys.stderr)
        return 2

    reports = [run_repo(r.resolve(), cases) for r in args.repos]
    _, misses, skipped = report(reports)
    failed = [e for rep in reports for e in rep["checker_errors"]]
    if failed:
        print(f"\nrecall: {len(failed)} checker error(s) — recall is not measurable "
              f"with a checker that raised:", file=sys.stderr)
        for e in failed[:5]:
            print(f"  {e['checker']} raised {e['message']} at {e['path']}", file=sys.stderr)
    if args.json:
        args.json.write_text(json.dumps({
            "cases": [c for c, _ in cases], "repos": reports,
            "misses": misses, "not_planted": skipped,
            "checker_errors": failed,
        }, indent=2), encoding="utf-8")
    if args.report_only:
        return 0
    return 1 if (misses or failed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
