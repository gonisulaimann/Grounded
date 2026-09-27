<h1 align="center">
    <a href="https://grounded.readthedocs.io">
        <picture>
          <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/gonisulaimann/Grounded/main/docs/assets/logo_white.png">
          <img alt="Grounded Logo" src="https://raw.githubusercontent.com/gonisulaimann/Grounded/main/docs/assets/logo_black.png" width="280">
        </picture>
    </a>
    <br>
</h1>

**Grounded** catches the references your code no longer backs up: the
import of a function someone renamed, the mock that patches a name that
moved, the comment pointing at a file that was deleted, the doc example
calling an API that is gone. Every finding is a mechanical
contradiction (a name that resolves nowhere, a path that does not
exist), checked against the repository itself, so a clean scan means
something and a finding means something.

It is built for the moment code changes, especially when an agent
changed it: `grounded scan --changed` reports what an edit broke
anywhere in the repo, in about two seconds (median) on a tree the size
of CPython.
Python, JavaScript/TypeScript, Go and C. Zero dependencies, offline,
deterministic, no LLM anywhere.

<p align="center">
    <a href="docs/README_AR.md"><img alt="README بالعربية" title="README بالعربية" src="https://img.shields.io/badge/Arabic-DFE0E5"></a>
    <a href="docs/README_ES.md"><img alt="README en Español" src="https://img.shields.io/badge/Español-DFE0E5"></a>
    <a href="docs/README_PT-BR.md"><img alt="README em Português (Brasil)" src="https://img.shields.io/badge/Português%20(Brasil)-DFE0E5"></a>
    <a href="docs/README_FR.md"><img alt="README en Français" src="https://img.shields.io/badge/Français-DFE0E5"></a>
    <a href="docs/README_DE.md"><img alt="README auf Deutsch" src="https://img.shields.io/badge/Deutsch-DFE0E5"></a>
    <a href="docs/README_CN.md"><img alt="简体中文版自述文件" src="https://img.shields.io/badge/简体中文-DFE0E5"></a>
    <a href="docs/README_JP.md"><img alt="日本語のREADME" src="https://img.shields.io/badge/日本語-DFE0E5"></a>
    <a href="docs/README_RU.md"><img alt="Русская версия README" src="https://img.shields.io/badge/Русский-DFE0E5"></a>
    <a href="docs/README_KR.md"><img alt="한국어 README" src="https://img.shields.io/badge/한국어-DFE0E5"></a>
    <br/>
    <a href="https://github.com/gonisulaimann/Grounded/actions/workflows/ci.yml"><img src="https://github.com/gonisulaimann/Grounded/actions/workflows/ci.yml/badge.svg" alt="Tests"></a>
    <a href="https://pypi.org/project/grounded-lint/"><img src="https://img.shields.io/pypi/v/grounded-lint.svg?color=brightgreen&label=pypi%20package" alt="PyPI package"></a>
    <a href="https://open-vsx.org/extension/gonisulaimann/grounded"><img src="https://img.shields.io/open-vsx/v/gonisulaimann/grounded?color=purple&logo=visualstudiocode" alt="Open VSX Extension"></a>
    <a href="https://github.com/gonisulaimann/homebrew-tap"><img src="https://img.shields.io/badge/Homebrew-gonisulaimann%2Ftap-blue.svg?logo=homebrew" alt="Homebrew"></a>
    <a href="https://grounded.readthedocs.io/en/latest/"><img src="https://readthedocs.org/projects/grounded/badge/?version=latest" alt="Documentation Status"></a>
    <a href="docs/agent-skill.md"><img src="https://img.shields.io/badge/Skill-black?style=flat&label=Agent" alt="AI Agent Skill"></a>
    <a href="https://clawhub.ai/gonisulaimann/grounded"><img src="https://img.shields.io/badge/Clawhub-darkred?style=flat&label=OpenClaw" alt="OpenClaw Skill"></a>
    <br/>
    <a href="https://www.ko-fi.com/gonisulaiman"><img src="https://srv-cdn.himpfen.io/badges/kofi/kofi-flat.svg" alt="Ko-Fi"></a>
    <img src="https://img.shields.io/badge/Per--file%20recheck-0.6ms-blueviolet" alt="0.6 ms per-file recheck (in-process, editor/LSP)">
    <img src="https://img.shields.io/badge/Dependencies-0%20(stdlib)-brightgreen" alt="Zero Dependencies">
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
    <br/>
    <a href="https://pypi.org/project/grounded-lint/"><img src="https://img.shields.io/pypi/pyversions/grounded-lint.svg" alt="Supported Python versions"></a>
</p>

<p align="center">
    <a href="https://grounded.readthedocs.io/en/latest/"><strong>Documentation</strong></a>
    &middot;
    <a href="https://grounded.readthedocs.io/en/latest/installation/"><strong>Installation</strong></a>
    &middot;
    <a href="https://grounded.readthedocs.io/en/latest/rules/"><strong>Rules &amp; Checkers</strong></a>
    &middot;
    <a href="https://grounded.readthedocs.io/en/latest/agents/"><strong>Agent Setup (LSP / MCP)</strong></a>
    &middot;
    <a href="https://grounded.readthedocs.io/en/latest/agent-skill/"><strong>Agent Skill</strong></a>
    &middot;
    <a href="https://grounded.readthedocs.io/en/latest/benchmarks/"><strong>Benchmarks</strong></a>
</p>

---

<p align="center">
  <img src="https://raw.githubusercontent.com/gonisulaimann/Grounded/main/demo/firewall.gif" alt="30-second demo: an agent renames a function in one file; grounded scan --changed catches the stale import in another file pre-commit" width="900">
</p>
<p align="center"><em>30 seconds, offline, self-checking — reproduce it: <a href="demo/firewall.sh">demo/firewall.sh</a></em></p>

After renaming `fetch_user` to `load_user` in `app/core.py`:

```console
$ grounded scan . --changed
LIE app/views.py:1 [stale-import] `fetch_user` imported from `app/core.py` but never defined there
    claim: from app.core import fetch_user
    evidence: `app/core.py` exists but defines no `fetch_user`.
    fix: Check for a rename in `app/core.py` (or a moved submodule).

grounded: 1 finding(s) in 4 file(s), 1 lie(s), 0 drift(s), 0 smell(s).
grounded: (--changed: 2 file(s) checked against the base; findings older than the change are not shown).
```

## What it catches

| Rule | Example of what it reports |
|---|---|
| `stale-import` | `from app.core import fetch_user` after `fetch_user` was renamed or removed (Python, and JS/TS with tsconfig aliases) |
| `stale-mock-ref` | `patch("app.core.helper")` when `app/core.py` no longer has `helper`: the test errors at runtime |
| `stale-symbol-ref` | a comment saying ``calls `legacy_parse()` `` when no such function exists anywhere |
| `stale-file-ref` | a comment pointing at `tests/ech_test.sh` when the file is `tests/ech_tests.sh` |
| `stale-entrypoint` | a `[project.scripts]` or `package.json` `bin` target that points at nothing |
| `unclosed-fence` | a Markdown fence that never closes, so everything after it renders as code |

Plus two softer rules (`number-drift`, `fragile-anchor`) and six opt-in
checkers; see [Rules](#rules). A rule stays silent unless the
contradiction is mechanical: imports, stdlib names, parameters, locals,
docstring field lists and illustrative examples never produce findings.

## Proven on real code

**Precision is measured, not asserted.** Every lie and drift on 25
pinned repositories (Python, JS/TS, Go, C) is classified by hand in
[`bench/precision/ledger.json`](bench/precision/ledger.json), and CI
fails on any finding nobody has classified. Current: 30 true, 9 false
(precision 0.77). The true ones are real rot in redis, curl, grpc-go,
django, celery, pydantic, prettier, pytest, vite, typer, sqlmodel,
cobra, flask, fastapi and scrapy: renamed functions still named in
comments, examples importing a decorator removed in Celery 5, a test
fixture importing `flask.Module` (removed in Flask 1.0), lint config
listing a file that moved.

**`--changed` matches ground truth.** It reports what the change
introduced; on every sample its output equaled the difference of two
full scans (worktree minus base), plus findings on changed lines: 29
consecutive cpython commits, 30 django commits and 10 constructed
refactors (renames, deleted modules, mock targets): 32 introduced
findings, 0 missed, 0 extra.

| `--changed` on real commits (`bench/changed.py`) | p50 | p95 |
|---|---|---|
| cpython (3,605 files) | 1.9 s | 3.4 s |
| django (2,986 files) | 1.2 s | 3.3 s |

Full scans (measured 2026-09-24, MacBook Air M-series, fresh process,
[`bench/`](bench/README.md)):

| Tree | Files | Cold | Warm index |
|---|---|---|---|
| cpython | 3,605 | 37.9 s | 32.1 s |
| django | 2,986 | 11.1 s | 8.4 s |
| prettier | 6,255 | 3.3 s | 2.5 s |
| grpc-go | 1,141 | 4.0 s | 3.0 s |

Details and every classification: [Benchmarks](https://grounded.readthedocs.io/en/latest/benchmarks/).

## Install

One line, no Python needed (installs the standalone binary, or uses your
existing `uv`/`pip`/`brew`):

```console
curl -fsSL https://raw.githubusercontent.com/gonisulaimann/Grounded/main/install.sh | sh
```

```powershell
irm https://raw.githubusercontent.com/gonisulaimann/Grounded/main/install.ps1 | iex
```

Or with a package manager:

```console
brew install gonisulaimann/tap/grounded
pip install grounded-lint                        # or: uv tool install grounded-lint
uvx --from grounded-lint grounded scan .         # run without installing
```

From source: `git clone https://github.com/gonisulaimann/Grounded.git && pip install -e Grounded`.

## Quick start

```console
grounded scan .                          # whole tree; exit 1 on any lie
grounded scan . --changed                # what your uncommitted work broke
grounded scan . --changed origin/main    # what this branch broke (CI)
grounded fix . --dry-run                 # unambiguous renames and path moves
```

`grounded scan` exits `1` when a finding meets `--fail-on` (default
`lie`), `0` when clean, `2` on usage errors and `3` when a checker raised
so the scan is incomplete. `--format json|sarif|markdown|html` for
tooling; SARIF uploads to GitHub code scanning.

## For coding agents

One command wires Grounded into Claude Code, Cursor and Aider:

```console
grounded init-agent                 # Claude hook + Cursor rule + Aider config
grounded init-agent --skill         # teach every project: ~/.claude/skills/grounded
```

**Claude Code.** `init-agent --claude` installs a PostToolUse hook:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [{ "type": "command", "command": "grounded hook claude-code" }]
      }
    ]
  }
}
```

After every edit, `grounded hook claude-code` checks the changed lines
plus what the edit broke in other files, and exits `2` with the findings
on stderr, which Claude Code feeds back to the model. Its own failures
exit `1` and never wedge the agent loop. Hooks installed by older
versions (`grounded scan . --changed --quiet`) only reached the human;
re-run `grounded init-agent --claude` to upgrade in place.

**Cursor.** `grounded init-agent --cursor` writes
`.cursor/rules/grounded.mdc` (Cursor loads only `.mdc` with
frontmatter, not `.md`). By hand, in agent-requested mode:

```markdown
---
description: Verify code references with grounded before building on edited code
alwaysApply: false
---

After editing source files, run `grounded scan . --changed` and fix
reported lies (dangling function names, missing files) before running
tests or committing.
```

**Aider** (`--lint-cmd` gets filenames and expects non-zero on failure):

```console
aider --lint-cmd "sh -c 'for f; do grounded scan \"$f\" --quiet || exit 1; done' sh"
```

**MCP.** `grounded mcp` serves four tools over stdio: `check_path`
(scan a path under the server root, which paths cannot escape),
`explain_checker`, `blast_radius` (definers, importers and comment
claims for a symbol: ask before renaming), and `check_text` (resolve
the names/paths in free text to known/unknown: ask before acting). Protocol versions
`2024-11-05` through `2025-06-18`; stdout carries only MCP messages.

```json
{
  "mcpServers": {
    "grounded": { "command": "grounded", "args": ["mcp", "--root", "."] }
  }
}
```

Cost: 0.6 ms for an in-process single-file check, 58 ms from a cold CLI
(Python startup dominates; best of 7, `examples/bench/bench.py`). Tests
catch everything; grounded is the millisecond pre-filter before you pay
for them.

## Editors (LSP)

`grounded lsp` speaks Language Server Protocol 3.17 over stdio: live
diagnostics (lie as error, drift as warning, smell as information) and
quickfixes for unambiguous renames and path moves. On **Cursor**,
**Windsurf** and **VSCodium**, install the
[Open VSX extension](https://open-vsx.org/extension/gonisulaimann/grounded).
Neovim:

```lua
vim.api.nvim_create_autocmd("FileType", {
  pattern = { "python", "javascript", "typescript", "go", "c" },
  callback = function()
    vim.lsp.start({ name = "grounded", cmd = { "grounded", "lsp" } })
  end,
})
```

Any generic LSP client (VS Code, Zed, Emacs eglot) can run the same
command. For a VS Code task instead, see the
[editor docs](https://grounded.readthedocs.io/en/latest/editors/).

## CI, pre-commit, and GitHub Action

```yaml
- uses: gonisulaimann/Grounded@v0.17.0
  with:
    changed-base: origin/main   # what this pull request broke
    fail-on: lie
```

The Action annotates the pull request inline and writes a findings table
to the job summary. For whole-tree gating, record a baseline instead
(`baseline: .grounded-baseline.json`, see below).

```yaml
repos:
  - repo: https://github.com/gonisulaimann/Grounded
    rev: v0.17.0
    hooks:
      - id: grounded          # dangling references in your changes
      - id: grounded-fences   # Markdown fences the renderer will not honour
```

`grounded-fences` gates changed *files*, not lines: one unclosed fence
corrupts everything after it, the defect a line-scoped review misses.

## Adopting on an existing codebase

**Gate only what changes.** `--changed` needs nothing set up. On a
changed line or in a new file every finding reports. Anywhere else, a
finding reports when the change introduced it: a full scan of your tree
has it and a full scan of the base does not. Rename a function, and
every file still importing the old name shows up; older findings that
merely share a word with the diff stay hidden. It gets there without
two full scans: the base index reuses every unchanged file, and only
files that can reach a changed name are checked. When the change edits a
file checkers read from disk (`pyproject.toml`, `package.json`,
`.gitignore`, `tsconfig.json`), it falls back to a broader, noisier rule
and says so on stderr. Outside a git repo, or with an unresolvable base,
it exits `2` instead of silently scanning everything.

**Or record a baseline** once, commit it, and gate on anything new:

```console
grounded baseline . --output .grounded-baseline.json   # record today
git add .grounded-baseline.json
grounded scan . --baseline .grounded-baseline.json     # new findings only
```

Fingerprints cover checker, path and claim text, not line numbers, so
unrelated edits do not churn the file; editing the offending line
re-triggers the gate. `--show-baselined` lists what is suppressed.

**Accept a single finding** where it sits:

```python
# Calls `legacy_parse()` for old dumps.  # grounded-disable: stale-symbol-ref
```

**Speed.** The repo index is cached in the git directory
(`.git/grounded/`) per file, by size and mtime, so a repeat scan
re-indexes only what you edited; opt out with `--no-index-cache` or
`GROUNDED_NO_INDEX_CACHE=1`. `--cache` also replays whole per-file
results while nothing else in the tree changed (CI retries). Large scans
run in parallel automatically; `--jobs N` overrides and the output is
identical either way.

## Rules

| ID | Default severity | What it reports |
|---|---|---|
| `stale-symbol-ref` | lie (error) | A comment names a call that resolves nowhere: not defined in the repo, not imported in the file, not used in the file, not a builtin or keyword. Prints rename suggestions when a close match exists. |
| `stale-import` | lie (error) | A resolvable import whose module is missing, or whose name is not defined, re-exported, or a submodule there. Python `from`/`import`, JS/TS relative imports (tsconfig aliases resolved). Guarded, stdlib, and external imports never report. |
| `stale-file-ref` | lie (error) | A comment claims a path inside the repo tree that does not exist. References to other projects, frameworks, template namespaces, and placeholder paths are ignored. |
| `stale-mock-ref` | lie (error) | A `@patch`/`patch.object` string naming a symbol absent from the in-repo module (a test that errors at runtime). Graduated 2026-09-22: 134 Django findings classified, all fixed or documented. |
| `stale-entrypoint` | lie (error) | A `pyproject.toml` `[project.scripts]` target or `package.json` `bin`/`main` path pointing at nothing in the repo. Graduated 2026-09-22: 0 false positives over 15,196 files. |
| `unclosed-fence` | lie (error) | A Markdown fence that never closes, or one the renderer swallows because an earlier block is still open. Judged by CommonMark, not by counting fences. Graduated 2026-09-22: 0 false positives over 11,564 Markdown files, walk pinned by a differential fuzz. |
| `number-drift` | drift (warning) | A comment states a magic number (timeout, port, limit, threshold) that disagrees with adjacent code. |
| `fragile-anchor` | smell (note) | `line 42` anchors, `see above` / `see below` without a symbol, and workaround markers (`HACK`, `XXX`, `workaround`) with no ticket or expiry condition. |

Six more checkers ship **opt-in** (`--enable <id>`) and graduate to
default-on only by measured precision
([tracked here](https://github.com/gonisulaimann/Grounded/tree/main/corpus)):

| ID | Severity | What it reports |
|---|---|---|
| `stale-doc-ref` | lie | fenced doc example calling a symbol defined nowhere |
| `stale-contract-ref` | lie / drift | deprecation target, lock claim, or env default contradicting the repo |
| `ghost-export` | smell | public symbol with no importers, no use, no API marking |
| `phantom-package` | drift | import declared in no manifest |
| `stale-cli-ref` | lie | a documented `grounded` invocation the live CLI parser rejects |
| `stale-cli-flag` | lie | a documented invocation of the repo's own CLI with a long flag no argparse, click, cobra, commander or Go `flag` definition declares |

## Configuration

`grounded init` writes a starter file. Settings also load from
`pyproject.toml` under `[tool.grounded]`.

```toml
# grounded.toml
disable = ["fragile-anchor"]
fail_on = "lie"
ignore_dirs = ["docs", "sandbox"]
ignore_files = ["generated.py"]

# JS/TS path aliases, repo-root-relative (tsconfig `paths` are picked
# up automatically per directory; these are the fallback).
# path_aliases = { "@/" = "src/", "~/" = "app/" }
```

Path aliases resolve against the nearest `tsconfig.json` (comments and
`extends` supported). Unresolvable alias targets report as drift, never
as lies: they are often build-generated. Mappings into `node_modules`
are skipped, and bare specifiers whose only visible resolution is
external (a package's own name, types-only `.d.ts` surfaces) stay
silent: the scan cannot see the real resolution, so it never claims a
lie about it.

## Command reference

```console
grounded scan [PATH] [--format terminal|json|sarif|markdown|html] [--output FILE]
               [--fail-on lie|drift|smell|never]
               [--enable CHECKER,...] [--disable CHECKER,...]
               [--baseline FILE] [--show-baselined]
               [--changed [BASE]] [--cache [FILE]] [--no-index-cache] [--jobs N]
               [--config FILE] [--no-color] [--quiet]
grounded baseline [PATH] [--output FILE]  # record findings for delta gating
grounded fix [PATH] [--dry-run]  # rewrite unambiguous stale refs
grounded impact SYMBOL [PATH] [--format terminal|json]
                     # show everything touching a symbol: definers,
                     # importers, comment claims
grounded list [PATH]       # show files that would be scanned
grounded explain CHECKER   # describe a checker (including removed ones)
grounded init [--force]    # write a starter grounded.toml
grounded init-agent [--claude|--cursor|--aider] [--skill] [--skill-project] [--force] [--dry-run]
grounded hook claude-code  # Claude Code PostToolUse adapter (stdin event)
grounded mcp [--root .]    # MCP server over stdio for coding agents
grounded lsp               # LSP 3.17 server over stdio for editors
```

Full flag documentation: [CLI reference](https://grounded.readthedocs.io/en/latest/cli-reference/).

## Non-goals

No LLM in detection, ever: findings are deterministic and reproducible
offline. No style or "smell" rules that add noise. Docstring contracts
(parameters, returns, raises) are covered precisely by
[darglint](https://github.com/terrencepreilly/darglint) and
[pydoclint](https://github.com/jsh9/pydoclint) for Python and
[eslint-plugin-jsdoc](https://github.com/gajus/eslint-plugin-jsdoc) for
JavaScript/TypeScript; commented-out code by
[Ruff ERA001](https://docs.astral.sh/ruff/rules/commented-out-code/).
`grounded explain <id>` points at the right tool for each removed check.

## Limitations

- Unformatted, unverbed name mentions are skipped. A rename noted without
  backticks or a reference verb ("calls", "see", "uses") will be missed.
  This trades recall for precision.
- Names imported from anywhere are treated as known elsewhere, including
  cross-module renames.
- Framework namespaces (template paths, URL names) are out of scope; such
  references stay silent instead of guessed.
- JavaScript/TypeScript, Go, and C analysis is syntactic (imports plus
  identifiers), not a full type graph.
- External references stay silent only when recognized: stdlib and POSIX
  names, imports, and same-file identifiers. References to vendored code,
  kernel idioms, platform APIs, paper algorithms, and prose verbs in
  parentheses (`forks()`) can still report; judge those on sight.
- Rename suggestions use string similarity only; the first guess can miss.
  `grounded fix` applies a symbol rename only with exactly one similar,
  same-directory candidate, and rewrites stale file paths only on
  unambiguous same-basename matches in comments (never docstrings, never
  ties).
- Generated or build-time content (`tsc` declaration dirs, `dist/`
  outputs) and dynamic namespaces (`globals().update()`) stay silent
  rather than guessed about.

## Development

```console
python -m unittest discover -s tests   # stdlib only, no extras
python3 corpus/run.py                  # precision corpus, exact-match
grounded scan src                      # self-scan gate, must report clean
grounded scan examples/v2demo          # fixture tree, expect 10 findings
python3 bench/precision.py             # precision gate on pinned repos
python3 bench/changed.py ~/some/clone  # --changed latency on real history
python3 bench/recall.py ~/some/repo    # recall: corpus rot replayed in a real tree
./demo/firewall.sh                     # 30-second firewall demo, self-checking
```

## Contributing

Issues and pull requests are welcome. Please include a minimal fixture
(a few lines showing the reference and the code), current vs expected
output, and the checker id in the title.

New checkers need a fixture, tests, a corpus case (`corpus/cases/`), a
real-repo measurement, and no runtime dependencies (stdlib only is a
project rule); they ship opt-in and graduate by measured precision,
never by volume. See
[Adding or changing a rule](CONTRIBUTING.md#adding-or-changing-a-rule).

## License

MIT. See [LICENSE](https://github.com/gonisulaimann/Grounded/blob/main/LICENSE).
