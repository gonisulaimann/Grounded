# Command Line Interface (CLI) Specification

This document provides the formal operational specification for the Grounded command line interface. All arguments, subcommands, exit codes, environment controls, and serialization formats are defined herein.

---

## 1. Global Invariants and Exit Status Protocols

Grounded strictly adheres to POSIX standard conventions. All human-readable diagnostic messages and progress indicators are written to `stderr`. Machine-readable output formats (`json`, `sarif`, `markdown`, `html`) are directed to `stdout` (or the file target specified by `--output`).

### Process Exit Statuses

Every invocation terminates with an explicit integer status code:

| Status Code | Label | Formal Semantics |
| :---: | :--- | :--- |
| `0` | `SUCCESS` | Operational success. Zero findings met or exceeded the threshold defined by `--fail-on`. |
| `1` | `CONTRADICTION` | Failure threshold breached. One or more verified mechanical contradictions were detected. |
| `2` | `USAGE_ERROR` | Command-line invocation error. Invalid arguments, unknown checker IDs, missing files, or bad configs. |
| `3` | `INTERNAL_FAULT` | Processing halted prematurely due to an unexpected unhandled exception or parsing abort. |

---

## 2. Command Catalog

```
grounded [--version] [--help] <command> [options]
```

### `scan`

Executes AST analysis and reference verification across a directory tree or single file.

```console
$ grounded scan [PATH] [options]
```

#### Arguments & Options

| Option | Type | Default | Description |
| :--- | :---: | :---: | :--- |
| `PATH` | Positional | `.` | Root directory or specific file path to analyze. |
| `--format` | Enum | `terminal` | Output serialization: `terminal`, `json`, `sarif`, `markdown`, `html`. |
| `--output`, `-o` | String | `None` | Write output payload directly to designated file path rather than `stdout`. |
| `--fail-on` | Enum | `lie` | Minimum finding severity triggering exit code `1`: `lie`, `drift`, `smell`, `never`. |
| `--enable` | String | `None` | Comma-separated list of checker IDs to activate (enables opt-in checkers). |
| `--disable` | String | `None` | Comma-separated list of checker IDs to deactivate. |
| `--baseline` | Path | `None` | Path to baseline JSON manifest. Findings present in the baseline are suppressed. |
| `--show-baselined` | Flag | `False` | Render suppressed baseline findings to `stderr` for audit logging. |
| `--changed [BASE]` | String | `HEAD` | Delta-scan mode. Evaluates lines modified relative to `BASE` (e.g. `origin/main`). |
| `--cross-index` | Path | `None` | Path to auxiliary repository tree to cross-verify OpenAPI/Swagger endpoints. |
| `--no-index-cache` | Flag | `False` | Disable `.git/grounded/` disk cache and force a complete re-indexing pass. |
| `--jobs`, `-j` | Integer | Auto | Number of parallel worker threads. Defaults to serial under 512 files. |
| `--config` | Path | `None` | Explicit path to `grounded.toml` configuration file. |
| `--no-color` | Flag | `False` | Strip ANSI escape sequences from terminal output. |
| `--quiet`, `-q` | Flag | `False` | Suppress finding descriptions; emit only summary counts and exit status. |

---

### `baseline`

Generates an authoritative JSON snapshot of all current findings in the target tree to facilitate delta gating on legacy codebases.

```console
$ grounded baseline [PATH] [--output FILE] [--config FILE]
```

* Defaults to `.grounded-baseline.json` if `--output` is omitted.
* Fingerprints are computed over `(checker, normalized_path, claim_text)` rather than fragile line numbers, preserving baseline validity across unrelated code additions.

---

### `fix`

Executes deterministic, mechanical AST rewrites for unambiguous symbol renames and moved file paths.

```console
$ grounded fix [PATH] [--dry-run] [--config FILE]
```

* `--dry-run`: Emits planned modifications without writing to disk.
* Safety contract: Only executes rewrites when exactly one candidate symbol with identical semantics exists in the scope. Ambiguous references are never altered.

---

### `impact`

Queries the repository symbol graph to compute the total blast radius of a symbol across definitions, imports, doc comments, test mocks, and configuration entrypoints.

```console
$ grounded impact <SYMBOL> [PATH] [--format terminal|json]
```

* `SYMBOL`: Token identifier (e.g., `handleChatCore` or `RecordProviderFailure`).
* Emits graph node mappings including callers, dependent docstrings, and test patches.

---

### `watch`

Activates continuous polling and in-process cache monitoring over the repository tree.

```console
$ grounded watch [PATH]
```

* Maintains a warm in-process symbol table.
* Rechecks modified buffers upon file modification in **~0.6 milliseconds**.
* Only announces introduced findings, suppressing pre-existing repository debt.

---

### `doctor`

Runs an institutional health and environment audit checking binary integrity, cache health, agent hook bindings, and Tree-Sitter parser availability.

```console
$ grounded doctor
```

---

### `init-agent`

Configures agent integration hooks, Cursor rules, Aider configurations, and spec-compliant agent skills.

```console
$ grounded init-agent [--claude] [--cursor] [--aider] [--skill] [--skill-project] [--force] [--dry-run]
```

* `--claude`: Writes or upgrades `PostToolUse` hook in `.claude/settings.json`.
* `--cursor`: Generates `.cursor/rules/grounded.mdc` with frontmatter rule metadata.
* `--aider`: Configures `--lint-cmd` loop in `.aider.conf.yml`.
* `--skill`: Installs the universal AgentSkills-spec package to `~/.claude/skills/grounded`.
* `--skill-project`: Installs skill locally to `.claude/skills/grounded` in current repository.

---

### `hook`

Agent hook adapter processing incoming IDE and agent events via standard input.

```console
$ grounded hook claude-code
```

* Reads JSON payload emitted by Claude Code on `stdin`.
* Executes differential reference scan over changed buffers.
* Emits formatted contradiction diagnostics on `stderr` and exits `2` to trigger agent self-correction.

---

### `pr`

Applies verified mechanical rewrites on an isolated Git branch and opens a GitHub Pull Request via `gh`.

```console
$ grounded pr [--title TITLE] [--body BODY]
```

---

### `badge`

Generates an authoritative Markdown/Shields.io Reference Integrity badge.

```console
$ grounded badge [--check]
```

* `--check`: Gating mode. Exits `1` if the current repository README or documentation contains any broken reference, ensuring badges cannot be displayed fraudulently.

---

### `mcp`

Launches the Model Context Protocol (MCP) server over standard input/output.

```console
$ grounded mcp [--root PATH]
```

* Implements JSON-RPC 2.0 protocol specifications.
* Exposes 4 native agent tools: `check_path`, `explain_checker`, `blast_radius`, and `check_text`.

---

### `lsp`

Launches the Language Server Protocol (LSP 3.17) server over standard input/output.

```console
$ grounded lsp
```

* Real-time diagnostic publishing (`textDocument/publishDiagnostics`).
* Code actions and quickfixes for unambiguous renames (`textDocument/codeAction`).

---

## 3. Machine-Readable Schema Specifications

### JSON Output Schema (`--format json`)

```json
{
  "summary": {
    "scanned_files": 412,
    "total_findings": 1,
    "lies": 1,
    "drifts": 0,
    "smells": 0
  },
  "findings": [
    {
      "path": "src/api/router.py",
      "line": 42,
      "end_line": 42,
      "checker": "stale-symbol-ref",
      "severity": "lie",
      "title": "Comment references `handle_auth_callback` which is not defined here",
      "claim": "`handle_auth_callback()`",
      "evidence": "`handle_auth_callback` is not defined, imported, or used in this file, and no definition was found in 412 indexed source files.",
      "fix": "Update the comment to the current name, or remove the reference. Did you mean: `handle_oauth_callback()`?",
      "confidence": 0.85
    }
  ]
}
```

### SARIF 2.1.0 Output Schema (`--format sarif`)

Grounded produces fully compliant OASIS SARIF v2.1.0 logs suitable for native ingestion into GitHub Code Scanning, GitLab Security Dashboards, and Azure DevOps Pipelines.
