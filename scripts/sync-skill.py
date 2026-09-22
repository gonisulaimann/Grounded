#!/usr/bin/env python3
"""Generate the top-level `agent-skill/` mirror from `src/grounded/skill/`.

`src/grounded/skill/` is the single source of truth: it is what
`grounded init-agent --skill` installs (`_skill_source()`) and what
`[tool.setuptools.package-data]` ships in the wheel. The top-level
`agent-skill/` directory exists so the skill stays browsable and
`cp -r agent-skill ~/.claude/skills/grounded`-able straight from the
repository, so it is *generated*: editing it directly is a change the next
run reverts, and a correction made in only one of the two copies fails the
build.

    python3 scripts/sync-skill.py            # rewrite the mirror
    python3 scripts/sync-skill.py --check    # exit 1 when out of date

`--source` / `--mirror` point the tool at other trees, which is how the test
proves drift is detected without touching the repository.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "src" / "grounded" / "skill"
MIRROR = REPO / "agent-skill"


def _files(root: Path) -> dict[Path, bytes]:
    """rel path -> bytes for every file under root (empty when absent)."""
    if not root.is_dir():
        return {}
    return {p.relative_to(root): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def drift(source: Path, mirror: Path) -> tuple[list[Path], list[Path], list[Path]]:
    """(missing, differing, extra) rel paths — mirror compared against source."""
    want, have = _files(source), _files(mirror)
    missing = sorted(set(want) - set(have))
    differing = sorted(r for r in set(want) & set(have) if want[r] != have[r])
    extra = sorted(set(have) - set(want))
    return missing, differing, extra


def check(source: Path, mirror: Path) -> list[str]:
    """Human-readable problems; empty means the mirror is in sync."""
    missing, differing, extra = drift(source, mirror)
    problems = [f"missing from the mirror: {rel.as_posix()}" for rel in missing]
    problems += [f"stale copy, regenerate: {rel.as_posix()}" for rel in differing]
    problems += [f"gone from the source, remove: {rel.as_posix()}" for rel in extra]
    return problems


def sync(source: Path, mirror: Path) -> tuple[int, int]:
    """Rewrite the mirror. Returns (files written, files removed)."""
    missing, differing, extra = drift(source, mirror)
    for rel in missing + differing:
        dest = mirror / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((source / rel).read_bytes())
    for rel in extra:
        (mirror / rel).unlink()
    # Drop directories the mirror no longer needs, and prune upward so a
    # deleted subdirectory does not survive as an empty shell.
    for path in sorted((p for p in mirror.rglob("*") if p.is_dir()),
                       key=lambda p: len(p.parts), reverse=True):
        if not any(path.iterdir()):
            path.rmdir()
    return len(missing) + len(differing), len(extra)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="report drift and exit non-zero; write nothing")
    parser.add_argument("--source", type=Path, default=SOURCE,
                        help="source tree (default: src/grounded/skill)")
    parser.add_argument("--mirror", type=Path, default=MIRROR,
                        help="generated mirror (default: agent-skill)")
    args = parser.parse_args(argv)
    if not (args.source / "SKILL.md").exists():
        print(f"sync-skill: no SKILL.md under {args.source}", file=sys.stderr)
        return 2
    if args.check:
        problems = check(args.source, args.mirror)
        for problem in problems:
            print(f"sync-skill: {problem}", file=sys.stderr)
        if problems:
            print("sync-skill: run `python3 scripts/sync-skill.py` to regenerate",
                  file=sys.stderr)
            return 1
        print(f"sync-skill: {args.mirror.name}/ matches {args.source}/")
        return 0
    written, removed = sync(args.source, args.mirror)
    print(f"sync-skill: {args.mirror}: {written} written, {removed} removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
