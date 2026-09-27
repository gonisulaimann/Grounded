<h1 align="center">
    <a href="https://grounded.readthedocs.io">
        <picture>
          <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/gonisulaimann/Grounded/main/docs/assets/logo_white.png">
          <img alt="Grounded Logo" src="https://raw.githubusercontent.com/gonisulaimann/Grounded/main/docs/assets/logo_black.png" width="320">
        </picture>
    </a>
    <br>
    The 0.6ms Reference Integrity Firewall for Codebases &amp; AI Agents
</h1>

<p align="center">
    <strong>Stop AI agents and human refactors from leaving ghost methods, broken comments, stale docs, and hallucinated packages in your repo.</strong>
</p>

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
    <a href="https://pypi.org/project/grounded-lint/"><img src="https://img.shields.io/pypi/v/grounded-lint.svg?color=brightgreen&label=pypi" alt="PyPI package"></a>
    <a href="https://www.npmjs.com/package/grounded-lint"><img src="https://img.shields.io/npm/v/grounded-lint?color=red&label=npm" alt="npm package"></a>
    <a href="https://open-vsx.org/extension/gonisulaimann/grounded"><img src="https://img.shields.io/open-vsx/v/gonisulaimann/grounded?color=purple&logo=visualstudiocode" alt="Open VSX Extension"></a>
    <a href="https://github.com/gonisulaimann/homebrew-tap"><img src="https://img.shields.io/badge/Homebrew-gonisulaimann%2Ftap-blue.svg?logo=homebrew" alt="Homebrew"></a>
    <a href="https://grounded.readthedocs.io/en/latest/"><img src="https://readthedocs.org/projects/grounded/badge/?version=latest" alt="Documentation Status"></a>
    <a href="docs/agent-skill.md"><img src="https://img.shields.io/badge/Skill-black?style=flat&label=Agent" alt="AI Agent Skill"></a>
    <a href="https://clawhub.ai/gonisulaimann/grounded"><img src="https://img.shields.io/badge/Clawhub-darkred?style=flat&label=OpenClaw" alt="OpenClaw Skill"></a>
    <br/>
    <a href="https://www.ko-fi.com/gonisulaiman"><img src="https://srv-cdn.himpfen.io/badges/kofi/kofi-flat.svg" alt="Ko-Fi"></a>
    <img src="https://img.shields.io/badge/Per--file%20recheck-0.6ms-blueviolet" alt="0.6 ms per-file recheck">
    <img src="https://img.shields.io/badge/Dependencies-0%20(stdlib)-brightgreen" alt="Zero Dependencies">
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
    <a href="https://pypi.org/project/grounded-lint/"><img src="https://img.shields.io/pypi/pyversions/grounded-lint.svg" alt="Supported Python versions"></a>
</p>

<p align="center">
    <a href="#quickstart"><strong>Quickstart</strong></a>
    &middot;
    <a href="#why-grounded"><strong>Why Grounded</strong></a>
    &middot;
    <a href="#ai-agent-firewall"><strong>AI Agent Firewall</strong></a>
    &middot;
    <a href="#rule-matrix"><strong>Rule Matrix</strong></a>
    &middot;
    <a href="#benchmarks"><strong>Benchmarks</strong></a>
    &middot;
    <a href="https://grounded.readthedocs.io/en/latest/"><strong>Documentation</strong></a>
</p>

---

<p align="center">
  <img src="https://raw.githubusercontent.com/gonisulaimann/Grounded/main/demo/firewall.gif" alt="30-second demo: an agent renames a function in one file; grounded scan --changed catches the stale import in another file pre-commit" width="880">
</p>
<p align="center"><em>30-second live demo: watch Grounded catch cross-file drift offline in milliseconds. Reproduce: <code>demo/firewall.sh</code></em></p>

---

## The Reality of Modern Repositories

When software evolves—especially with AI coding agents (Claude Code, Cursor, Aider, Copilot) authoring code at machine speed—**repositories rot silently from the inside**:

1. A function `fetch_account()` is renamed to `get_account()` in `services/auth.ts`.
2. The code compiles, but **40 comments, 5 mock patches, 2 doc tutorials, and 3 README examples still refer to the old name**.
3. Next week, another engineer or an AI agent reads those comments, trusts them, calls `fetch_account()`, and creates a hallucinated broken feature.

**Traditional linters (ESLint, Ruff, Pylint) cannot save you.** They only parse live syntax trees and completely ignore comments, documentation claims, and string references.

**AI Review Bots (CodeRabbit, Qodo) are too slow and expensive.** They take 45 seconds per PR, burn cloud tokens, and hallucinate themselves.

### Grounded is the Missing Mechanical Layer

**Grounded** is an offline, sub-millisecond reference-integrity firewall. It cross-references every comment, docstring, mock target, manifest entrypoint, and import against the **concrete symbol graph of the entire repository**.

Every finding is a **strict mechanical contradiction**—a name that resolves nowhere, a file that does not exist, a magic number that disagrees with the AST, or a package missing from public registries.

```console
$ grounded scan . --changed
LIE src/views/auth.py:12 [stale-symbol-ref] Comment references `verify_session_token` which is not defined here
    claim: `verify_session_token()`
    evidence: `verify_session_token` is not defined, imported, or used in this file,
              and no definition was found in 842 indexed source files.
    fix: Update the comment to the current name, or remove the reference. Did you mean: `verify_auth_token()`?

grounded: 1 finding(s) in 842 file(s), 1 lie(s), 0 drift(s), 0 smell(s).
```

---

## Features at a Glance

| Feature | Description |
| :--- | :--- |
| **Sub-Millisecond Recheck** | **0.6 ms** per-file in-process recheck. Scans a 3,000-file repository in under 2 seconds. |
| **Zero Dependencies** | **100% Python standard library**. No external runtime packages, no background daemon weight, no telemetry. |
| **Native AI Agent Firewall** | Intercepts Claude Code, Cursor, and Aider post-edit hooks pre-commit to catch hallucinations live. |
| **Polyglot Parsing** | Built-in AST and lexical indexers for **Python, TypeScript, JavaScript, Go, and C**. |
| **Slopsquatting Defense** | Flags imports of non-existent packages before attackers register malware on PyPI/npm. |
| **Tree-Sitter Enriched** | High-precision AST extraction for ambient type declarations, TS path aliases, and monorepos. |
| **LSP & MCP Servers** | Native **LSP 3.17** server for real-time IDE squigglies + **stdio MCP** server for agent tool-calling. |
| **Self-Healing PRs** | Run `grounded pr` to automatically rewrite unambiguous stale references and open a GitHub PR. |

---

## Quickstart

### 1-Line Universal Install (Zero Dependencies)

No Python, package manager, or build tools required. Installs standalone prebuilt single-file binary:

**macOS & Linux**:
```bash
curl -fsSL https://raw.githubusercontent.com/gonisulaimann/Grounded/main/install.sh | sh
```

**Windows (PowerShell)**:
```powershell
irm https://raw.githubusercontent.com/gonisulaimann/Grounded/main/install.ps1 | iex
```

### Via Package Managers

```bash
# Node.js / TypeScript (npm / npx)
npx grounded-lint scan .
npm install -D grounded-lint

# Homebrew (macOS / Linuxbrew)
brew install gonisulaimann/tap/grounded

# Python (pip / uv)
pip install grounded-lint
uv tool install grounded-lint
```

---

## Essential CLI Commands

```bash
# 1. Full repository scan (exits with status 1 on any lie)
grounded scan .

# 2. Gate uncommitted diffs (ideal for pre-commit & fast loops)
grounded scan . --changed

# 3. Gate CI pull request diffs against target branch
grounded scan . --changed origin/main

# 4. Preview and apply mechanical renames automatically
grounded fix . --dry-run
grounded fix .

# 5. Open an automated self-healing Pull Request
grounded pr --title "fix: repair 38 stale symbol references and dead links"

# 6. Live "Prove-It" watch loop (rescan only what changed on save)
grounded watch

# 7. Query symbol blast radius across code, docs, mocks, and entry points
grounded impact handleChatCore
```

---

## AI Agent Firewall Setup

Grounded wires directly into your agentic coding loop so agents fix their own hallucinations before you ever see them.

```bash
# One command sets up Claude Code, Cursor, and Aider:
grounded init-agent

# Install the AgentSkills-spec skill globally:
grounded init-agent --skill
```

### Claude Code Post-Tool Hook
`grounded init-agent --claude` configures `.claude/settings.json`:
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
*When Claude hallucinates a stale function or broken reference, Grounded exits non-zero and prints the exact contradiction. Claude immediately self-corrects the code in the same session.*

### Cursor IDE Rules
`grounded init-agent --cursor` installs `.cursor/rules/grounded.mdc` so Cursor's agent validates reference integrity before finishing edits.

### MCP Server (Model Context Protocol)
Add Grounded as an stdio MCP server in Claude Desktop or Cursor:
```json
{
  "mcpServers": {
    "grounded": {
      "command": "grounded",
      "args": ["mcp", "--root", "."]
    }
  }
}
```
*Gives agents 4 native tools: `check_path`, `blast_radius`, `explain_checker`, and `check_text`.*

---

## Rule Matrix

Grounded partitions findings into three deterministic severity levels:
- **`LIE` (Error):** Objective contradiction. The symbol, path, or package does not exist. Fails the build.
- **`DRIFT` (Warning):** Values or states that have decoupled from reality (e.g. comment says 120s, code says 10s).
- **`SMELL` (Info):** Fragile line-number anchors or unmaintained ticket markers.

### Default Active Checkers

| Checker ID | Severity | What It Proves |
| :--- | :---: | :--- |
| `stale-symbol-ref` | **LIE** | A comment or doc claims a call/symbol exists that is defined nowhere in the indexed repo. |
| `stale-import` | **LIE** | A resolvable import whose module is missing, or whose target export was renamed/deleted. |
| `stale-file-ref` | **LIE** | A comment or docstring references a repo path that does not exist on disk. |
| `stale-mock-ref` | **LIE** | A `@patch` or `mock.patch.object` string targeting a symbol absent from the module. |
| `stale-entrypoint` | **LIE** | A `pyproject.toml` script or `package.json` `bin`/`main` entry targeting a missing module. |
| `unclosed-fence` | **LIE** | A Markdown code fence that never closes, swallowing subsequent docs into raw code blocks. |
| `number-drift` | **DRIFT** | A comment states a numeric constant (timeout, port, limit) that contradicts adjacent code. |
| `fragile-anchor` | **SMELL** | Line-number anchors (e.g. `// see line 42`) and unbounded `HACK`/`TODO` markers. |

### Opt-In & Security Checkers (`--enable <id>`)

| Checker ID | Severity | What It Proves |
| :--- | :---: | :--- |
| `slop-package` | **LIE / DRIFT** | An import naming a third-party package absent from PyPI/npm (AI hallucination / slopsquatting risk). |
| `stale-api-ref` | **LIE** | An HTTP API route call literal that does not exist in the repo's OpenAPI/Swagger schema. |
| `stale-cli-flag` | **LIE** | A documented CLI flag that no internal `argparse`, `click`, `cobra`, or `flag` declares. |
| `stale-doc-ref` | **LIE** | A fenced documentation code example calling a symbol that does not exist in the codebase. |
| `stale-contract-ref`| **LIE / DRIFT** | Deprecation notices, lockfile claims, or env variable defaults contradicting code reality. |
| `phantom-package` | **DRIFT** | A third-party import used in source code that is undeclared in package manifests. |
| `ghost-export` | **SMELL** | An exported public symbol with zero internal importers, zero callers, and no API export tag. |

---

## Benchmarks & Ground Truth

Precision is mathematically measured across pinned open-source codebases, not marketing fluff. Every finding is classified in [`bench/precision/ledger.json`](bench/precision/ledger.json):

| Repository | Files | Language | Cold Scan | Warm Recheck | Real Rot Caught |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **cpython** | 3,605 | Python / C | 37.9 s | 1.9 s | Stale module cross-refs, moved C headers |
| **django** | 2,986 | Python | 11.1 s | 1.2 s | Stale test mocks, deleted template tags |
| **prettier** | 6,255 | JS / TS | 3.3 s | 0.8 s | Renamed parser options in doc comments |
| **grpc-go** | 1,141 | Go | 4.0 s | 0.6 s | Missing implementation claims in docstrings |
| **OmniRoute** | 3,199 | TS / Next.js | 4.2 s | 0.9 s | 156 contradictions (ghost methods, Zod drifts) |

*Tested on Apple Silicon M-series. In-process single-file LSP recheck: **0.6 milliseconds**.*

---

## Enterprise CI/CD Integration

### Official GitHub Action

Add Grounded to `.github/workflows/ci.yml` in 3 lines:

```yaml
name: Reference Integrity
on: [pull_request]

jobs:
  grounded:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: gonisulaimann/Grounded@v0.17.0
        with:
          changed-base: origin/main
          fail-on: lie
          pr-comment: 'true'
```

*Automatically leaves inline annotations on the pull request diff and maintains a single, non-spammy summary comment on the PR.*

### Pre-Commit Hook

Add to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/gonisulaimann/Grounded
    rev: v0.17.0
    hooks:
      - id: grounded
      - id: grounded-fences
```

### Legacy Codebase Baseline

To adopt Grounded on a large legacy project without fixing existing tech debt all at once:

```bash
# 1. Snapshot existing legacy findings into a baseline:
grounded baseline . --output .grounded-baseline.json
git add .grounded-baseline.json

# 2. Gate CI on NEW findings only:
grounded scan . --baseline .grounded-baseline.json
```

---

## Automated Repository Health Badge

Add the official Reference Integrity badge to your README:

```markdown
[![Reference Integrity: Grounded](https://img.shields.io/badge/Reference%20Integrity-100%25%20Grounded-brightgreen)](#)
```

Gate the badge in CI so it only passes when your documentation has zero lies:
```bash
grounded badge --check
```

---

## Non-Goals & Boundaries

Grounded is deliberately designed **never** to duplicate existing linters:
- **No LLM in Core Detection:** Findings are deterministic, reproducible offline, and never hallucinate.
- **No Code Formatting / Lint Rules:** Code formatting belongs to **Prettier** / **Ruff format**.
- **No Parameter Doc Contracts:** Parameter type and return mismatches belong to **darglint** (Python) and **eslint-plugin-jsdoc** (JS/TS).
- **No Commented-Out Code:** Commented-out code cleanup belongs to **Ruff ERA001** and **eslint-plugin-comment-cleaner**.

---

## Contributing

We welcome contributions! Check out our [Contributing Guide](CONTRIBUTING.md) to get started:

```bash
# Run unit tests (100% Python standard library)
python -m unittest discover -s tests

# Run precision corpus suite (80/80 test cases)
python3 corpus/run.py

# Self-scan repository gate
grounded scan src
```

---

## License

Released under the [MIT License](LICENSE). Grounded is free and open-source software built for developers and coding agents alike.
