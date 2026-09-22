<h1 align="center">
    <a href="https://grounded.readthedocs.io">
        <picture>
          <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/gonisulaimann/Grounded/main/docs/assets/logo_white.png">
          <img alt="Grounded Logo" src="https://raw.githubusercontent.com/gonisulaimann/Grounded/main/docs/assets/logo_black.png" width="280">
        </picture>
    </a>
    <br>
</h1>

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
    <img src="https://img.shields.io/badge/Scan%20Latency-0.6ms-blueviolet" alt="0.6ms Latency">
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

**Grounded** is a reference integrity firewall: it finds comments, doc
examples, imports, and config strings that contradict the repository
they live in. A rule fires only on mechanical contradiction — a name
that resolves nowhere, a path that does not exist, a default the code
disagrees with — so a clean scan means something and a finding means
something. It runs on Python, JavaScript/TypeScript, Go, and C with
zero dependencies, offline, deterministically.

```console
$ grounded scan ./src
LIE src/app.py:9 [stale-symbol-ref] Comment references `ghost_service` which is not defined here
    claim: `ghost_service()`
    evidence: `ghost_service` is not defined, imported, or used in this file,
              and no definition was found in 84 indexed source files.
    fix: Update the comment to the current name, or remove the reference.
```

Zero dependencies. No network access. Works on Python, JavaScript/TypeScript, Go, and C.

## Proven on real code

Measured 2026-09-21 (harness: `bench/run.py`; full tables in
[docs](https://grounded.readthedocs.io/en/latest/benchmarks/)):

| Tree | Files | Scan | Result (all classified) |
|---|---|---|---|
| django | 2,977 | 16.7 s | 1 true lie (stale test cross-reference) + fixture noise |
| cpython | 3,049 | 47.2 s | true moved-file references + fixture noise |
| grpc-go | 1,068 | 4.4 s | true missing implementation (`NewContextWithHandshakeInfo`) |
| express | 141 | 0.6 s | clean (was 101 false alarms before the CJS-interop fix) |

Benchmarking on real repos is part of development here: every round so
far has surfaced and fixed a precision bug before release.

## Install

### 1-Line Quick Install (Zero Dependencies)

No Python or package manager required. Automatically installs the standalone binary (or uses your existing `uv`/`pip`/`brew`):

**macOS & Linux**:
```console
curl -fsSL https://raw.githubusercontent.com/gonisulaimann/Grounded/main/install.sh | sh
```

**Windows (PowerShell)**:
```powershell
irm https://raw.githubusercontent.com/gonisulaimann/Grounded/main/install.ps1 | iex
```

### macOS & Linux (Homebrew)

```console
brew install gonisulaimann/tap/grounded
```

### Python Package (pip / uv)

```console
pip install grounded-lint
# or with uv
uv tool install grounded-lint
```

No Python management needed (measured 0.05s cached startup):

```console
uvx --from grounded-lint grounded scan .
```

From source:

```console
git clone https://github.com/gonisulaimann/Grounded.git
cd Grounded
pip install -e .
```

## Usage

```console
grounded scan [PATH] [--format terminal|json|sarif|html] [--output FILE]
               [--fail-on lie|drift|smell|never]
               [--enable CHECKER,...] [--disable CHECKER,...]
               [--baseline FILE] [--show-baselined]
               [--changed [BASE]] [--cache [FILE]] [--jobs N]
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
grounded mcp [--root .]    # MCP server over stdio for coding agents
grounded lsp               # LSP 3.17 server over stdio for editors
```

`grounded scan` exits with status `1` when any finding meets `--fail-on`
(default: `lie`), `0` otherwise. Point it at CI and gate on the default.

Example output formats for tooling: `--format json` for scripts,
`--format sarif` for GitHub code scanning, `--format html` for a
self-contained report page (no external assets, works opened from disk).

Large trees scan in parallel automatically (512+ files); `--jobs N`
overrides, `--jobs 1` forces serial. Output is identical either way.

In VS Code, wire the bundled problem matcher through a task
(`.vscode/tasks.json`, paths relative to the workspace):

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "grounded",
      "type": "shell",
      "command": "grounded scan . --no-color",
      "problemMatcher": {
        "owner": "grounded",
        "pattern": [
          {
            "regexp": "^(LIE|DRIFT|SMELL)\\s+(.+?):(\\d+)\\s+\\[(.+?)\\]\\s+(.*)$",
            "file": 2,
            "line": 3,
            "code": 4,
            "message": 5
          }
        ]
      }
    }
  ]
}
```

## Adopting on an existing codebase

Two mechanisms, composable. Both keep the full-tree scan and filter
reporting only.

Record a baseline once, commit it, gate on the delta:

```console
grounded baseline . --output .grounded-baseline.json   # record today
git add .grounded-baseline.json
grounded scan . --baseline .grounded-baseline.json     # new findings only
```

Fingerprints cover checker, path, and claim text, not line numbers, so
unrelated edits do not churn the file. Editing the offending line itself
re-triggers the gate. `--show-baselined` lists suppressed findings.

Gate pull requests on changed lines only:

```console
grounded scan . --changed                # uncommitted work vs HEAD
grounded scan . --changed origin/main    # branch vs base (CI)
```

Untracked files are fully reported. Findings off the diff still report
when their claim names a diff-touched symbol (rename fallout on
untouched lines). Outside a git repo, or with an
unresolvable base, `--changed` exits `2` with the git error instead of
silently scanning everything.

Repeat scans go faster with `--cache` (per-file results keyed by
mtime and size, opt-in, never required):

```console
grounded scan . --cache                # writes .grounded-cache.json
```

A repeat full-tree scan reuses unchanged files; the index still rebuilds
from disk, so expect roughly a 2x speedup on large trees, not magic.
Corrupt or mismatched caches fall back to a full scan silently.

## Rules

| ID | Default severity | What it reports |
|---|---|---|
| `stale-symbol-ref` | lie (error) | A comment names a call that resolves nowhere: not defined in the repo, not imported in the file, not used in the file, not a builtin or keyword. Prints rename suggestions when a close match exists. |
| `stale-import` | lie (error) | A resolvable import whose module is missing, or whose name is not defined, re-exported, or a submodule there. Python `from`/`import`, JS/TS relative imports (tsconfig aliases resolved). Guarded, stdlib, and external imports never report. |
| `stale-file-ref` | lie (error) | A comment claims a path inside the repo tree that does not exist. References to other projects, frameworks, template namespaces, and placeholder paths are ignored. |
| `number-drift` | drift (warning) | A comment states a magic number (timeout, port, limit, threshold) that disagrees with adjacent code. |
| `fragile-anchor` | smell (note) | `line 42` anchors, `see above` / `see below` without a symbol, and workaround markers (`HACK`, `XXX`, `workaround`) with no ticket or expiry condition. |
| `stale-entrypoint` | lie (error) | A `pyproject.toml` `[project.scripts]` target or `package.json` `bin`/`main` path pointing at nothing in the repo. Graduated 2026-09-22: silent on 5 real repos. |
| `stale-mock-ref` | lie (error) | A `@patch`/`patch.object` string naming a symbol absent from the in-repo module (a test that errors at runtime). Graduated 2026-09-22: 134 Django findings classified, all fixed or documented. |

Four more checkers ship **opt-in** (`--enable <id>`); they graduate to
default-on by measured precision ([tracked here](https://github.com/gonisulaimann/Grounded/tree/main/corpus)):

| ID | Severity | What it reports |
|---|---|---|
| `stale-doc-ref` | lie | fenced doc example calling a symbol defined nowhere |
| `stale-contract-ref` | lie / drift | deprecation target, lock claim, or env default contradicting the repo |
| `ghost-export` | smell | public symbol with no importers, no use, no API marking |
| `phantom-package` | drift | import declared in no manifest |

A rule stays silent unless the contradiction is mechanical. Imported names,
standard library names, parameters, locals, attributes, docstring field
lists (`:param:`, `@param`), and illustrative examples ("For example …")
never produce findings.

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

Path aliases (`@/`, `~/`, and any tsconfig `paths` entries) resolve
against the nearest `tsconfig.json` (which may use comments and
`extends`). Unresolvable alias targets report as drift, never as lies:
they are often build-generated. Mappings into `node_modules` are
always skipped. Bare specifiers whose only visible resolution is
external — a package's own name (self-import through its exports map)
or any alias whose replacements are types-only `.d.ts` surfaces — are
also silent: the scan cannot see the real resolution, so it never
claims a lie about it. Only aliases that map onto the scanned tree
stay fully checked.

Suppress a single accepted finding where it sits (reviewable, local):

```python
# Calls `legacy_parse()` for old dumps.  # grounded-disable: stale-symbol-ref
```

```js
// Calls `legacyParse()` for old dumps.  // grounded-disable: stale-symbol-ref
```

## CI, pre-commit, and GitHub Action

Gate pull requests with the first-party Action (inline PR annotations
included via problem matchers):

```yaml
- uses: gonisulaimann/Grounded@v0.16.0
  with:
    changed-base: origin/main   # new findings on edited lines only
    fail-on: lie
```

Or with a baseline file for whole-tree delta gating:

```yaml
- uses: gonisulaimann/Grounded@v0.16.0
  with:
    baseline: .grounded-baseline.json
```

As a pre-commit hook (runs on uncommitted changes):

```yaml
repos:
  - repo: https://github.com/gonisulaimann/Grounded
    rev: v0.16.0
    hooks:
      - id: grounded
```

SARIF upload for code scanning: run with `--format sarif --output
results.sarif`, then upload with `github/codeql-action/upload-sarif`.

## Coding agents

`grounded scan <file>` checks one file (exit 1 on findings, 0 when clean,
3 when a checker raised so the scan is incomplete), which is the contract
agent lint loops expect. Verified recipes:

Aider (`--lint-cmd` accepts filenames, expects non-zero on failure):

```console
aider --lint-cmd "sh -c 'for f; do grounded scan \"$f\" --quiet || exit 1; done' sh"
```

Claude Code (`.claude/settings.json`, runs after every file edit):

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{ "type": "command", "command": "grounded scan . --changed --quiet" }]
      }
    ]
  }
}
```

Cursor rules are generated, not hand-written (`.md` files in
`.cursor/rules/` are ignored by Cursor; only `.mdc` with frontmatter
loads):

```console
grounded init-agent                 # Claude hook + Cursor rule + Aider config
grounded init-agent --cursor        # just .cursor/rules/grounded.mdc
grounded init-agent --skill         # teach every project: ~/.claude/skills/grounded
```

Or write the rule by hand (agent-requested mode: description, no globs):

```markdown
---
description: Verify code references with grounded before building on edited code
alwaysApply: false
---

After editing source files, run `grounded scan . --changed` and fix
reported lies (dangling function names, missing files) before running
tests or committing.
```

For agents that speak MCP, use `grounded mcp` (see below) instead of
shelling out.

Measured cost (best of 7, wall clock, `examples/bench/bench.py`):
in-process single-file check 0.6 ms, cold CLI single-file check 58 ms
(Python startup dominates). No pytest comparison is claimed here: tests
catch everything, grounded is the millisecond pre-filter before you pay
for them.

`grounded` serves itself over stdio as a Model Context Protocol server,
so agents can verify references instead of trusting them:

```json
{
  "mcpServers": {
    "grounded": { "command": "grounded", "args": ["mcp", "--root", "."] }
  }
}
```

Three tools: `check_path` (scan a path under the server root; paths cannot
escape it), `explain_checker`, and `blast_radius` (definers, importers,
and comment claims for a symbol: ask before renaming). Protocol versions `2024-11-05` through
`2025-06-18` are negotiated per the spec; logs go to stderr, stdout
carries only MCP messages. Scan tools honor the `grounded.toml` in the
scanned root.

## Editors (LSP)

`grounded lsp` speaks Language Server Protocol 3.17 over stdio: instant
diagnostics (lie as error, drift as warning, smell as information) plus
quickfix actions for unambiguous renames and path moves. Neovim:

```lua
vim.api.nvim_create_autocmd("FileType", {
  pattern = { "python", "javascript", "typescript", "go", "c" },
  callback = function()
    vim.lsp.start({ name = "grounded", cmd = { "grounded", "lsp" } })
  end,
})
```

Any editor with a generic LSP client (VS Code, Cursor, Zed, Emacs
eglot) can point at the same command. On **Cursor**, **Windsurf**, and
**VSCodium**, you can also install the 1-click [Open VSX Extension](https://open-vsx.org/extension/gonisulaimann/grounded)
directly from the Extensions tab.

## Non-goals

Docstring contracts (parameter lists, return sections, raised exceptions)
are covered precisely by [darglint](https://github.com/terrencepreilly/darglint)
and [pydoclint](https://github.com/jsh9/pydoclint) for Python and
[eslint-plugin-jsdoc](https://github.com/gajus/eslint-plugin-jsdoc) for
JavaScript/TypeScript. Commented-out code is covered by
[Ruff ERA001](https://docs.astral.sh/ruff/rules/commented-out-code/) and
equivalent ESLint rules. `grounded` intentionally does not duplicate them;
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
  same-directory candidate.
- `grounded fix` rewrites stale file paths only on unambiguous
  same-basename matches in comments (never docstrings, never ties).
- Generated or build-time content (`tsc` declaration dirs, `dist/`
  outputs) and dynamic namespaces (`globals().update()`) stay silent
  rather than guessed about.

## Development

```console
python -m unittest discover -s tests   # 261 tests, stdlib only, no extras
grounded scan src                      # self-scan gate, must report clean
grounded scan examples/v2demo          # fixture tree, expect 10 findings
python3 corpus/run.py                  # precision corpus, exact-match
python3 bench/recall.py ~/some/repo    # recall: corpus rot replayed in a real tree
./demo/firewall.sh                     # 30-second firewall demo, self-checking
```

## Contributing

Issues and pull requests are welcome. Please include:

- a minimal fixture (a few lines showing the comment and the code),
- current output vs expected output,
- the checker id in the issue title.

New checkers are accepted only with a fixture, tests, a corpus case
(`corpus/cases/`), and no new runtime
dependencies (stdlib only is a project rule). New trigger classes ship
opt-in and graduate by measured precision, never by volume.

## License

MIT. See [LICENSE](https://github.com/gonisulaimann/Grounded/blob/main/LICENSE).
