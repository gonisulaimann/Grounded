# Operational Quickstart Guide

This guide details the complete operational workflow of Grounded, from initial deployment and delta verification to automated remediation and continuous integration enforcement.

---

## 1. System Verification

Verify that the Grounded executable is installed and available in the current execution environment:

```console
$ grounded --version
grounded 0.17.0
```

To run a rapid self-diagnostic confirming system compatibility, AST engine integrity, and agent hook bindings, execute:

```console
$ grounded doctor
grounded doctor: 0.17.0 (Python 3.11.8, darwin-arm64)
  [OK] Index cache: .git/grounded (active, 0 bytes)
  [OK] Tree-sitter: available (TypeScript/JavaScript parser loaded)
  [OK] Agent wiring: Claude Code hook (.claude/settings.json) configured
  [OK] Agent wiring: Cursor rule (.cursor/rules/grounded.mdc) present
  [OK] Integrity status: healthy
```

---

## 2. Executing a Baseline Scan

Execute an initial structural reference scan against a repository directory:

```console
$ grounded scan ./src
```

### Understanding the Diagnostic Output

When Grounded identifies a structural contradiction, it renders a standardized finding block:

```text
LIE src/api/router.py:42 [stale-symbol-ref] Comment references `handle_auth_callback` which is not defined here
    claim: `handle_auth_callback()`
    evidence: `handle_auth_callback` is not defined, imported, or used in this file,
              and no definition was found in 412 indexed source files.
    fix: Update the comment to the current name, or remove the reference. Did you mean: `handle_oauth_callback()`?

grounded: 1 finding(s) in 412 file(s), 1 lie(s), 0 drift(s), 0 smell(s).
```

### Exit Status Codes

Grounded adheres to strict, deterministic exit protocols suitable for automation pipelines:

| Exit Code | Classification | Meaning |
| :---: | :--- | :--- |
| `0` | Clean | Scan completed with no findings exceeding the `--fail-on` threshold. |
| `1` | Contradiction | One or more findings met or exceeded the failure threshold (default: `lie`). |
| `2` | Configuration Error | Invalid command line arguments, unresolvable paths, or syntax errors in `grounded.toml`. |
| `3` | Internal Fault | An unhandled exception or AST parser abort prevented full repository analysis. |

---

## 3. High-Velocity Delta Scanning (`--changed`)

In continuous integration and pre-commit scenarios, scanning an entire multi-thousand-file repository on every keystroke is inefficient. Grounded provides the `--changed` flag to calculate delta findings relative to a Git reference:

```console
# Verify uncommitted local working directory changes:
$ grounded scan . --changed

# Verify local branch commits against target mainline:
$ grounded scan . --changed origin/main
```

### Delta Calculation Invariant

The `--changed` algorithm operates on a differential graph principle:
1. It computes the exact symbol mutations introduced by the diff (definitions added, modified, or removed).
2. It evaluates findings on modified lines in modified files.
3. It recursively tests external repository files that import or reference any symbol touched by the diff.
4. Pre-existing technical debt outside the blast radius of the current change is suppressed automatically.

---

## 4. Symbol Graph Impact Queries (`grounded impact`)

Before refactoring, renaming, or removing an exported symbol, query Grounded to establish its complete repository blast radius:

```console
$ grounded impact handleChatCore
```

```text
Symbol: handleChatCore
Definers:
  - open-sse/handlers/chatCore.ts:18
Importers:
  - src/app/api/v1/chat/completions/route.ts:5
  - src/sse/handlers/chatHelpers.ts:12
Claimed by Comments & Docstrings:
  - docs/architecture/ARCHITECTURE.md:44
  - src/shared/utils/circuitBreaker.ts:177
Mock Targets:
  - tests/unit/chat-core.test.ts:31
```

By querying the graph beforehand, developers and agents identify all dependent call sites, doc claims, and test mocks that require concurrent updates.

---

## 5. Automated Mechanical Remediation (`grounded fix` and `grounded pr`)

Grounded includes an integrated rewriting engine designed to repair unambiguous symbol renames and moved file paths without altering program logic.

### Previewing Mechanical Fixes

Always execute remediation with `--dry-run` to preview candidate transformations:

```console
$ grounded fix . --dry-run
would rewrite src/shared/utils/circuitBreaker.ts:186: recordProviderFailure() -> recordFailure()
would rewrite src/shared/utils/httpClientAbortGuard.mjs:101: scripts/dev/run-next.mjs -> scripts/dev/run.mjs
grounded fix: 2 file(s) would change.
```

### Applying Fixes Locally

Drop the `--dry-run` flag to write modifications directly to disk:

```console
$ grounded fix .
rewrote src/shared/utils/circuitBreaker.ts:186: recordProviderFailure() -> recordFailure()
rewrote src/shared/utils/httpClientAbortGuard.mjs:101: scripts/dev/run-next.mjs -> scripts/dev/run.mjs
grounded fix: 2 file(s) changed.
```

### Automated Pull Request Synthesis (`grounded pr`)

In CI environments or automated maintenance workflows, Grounded can branch, commit, and open a Pull Request automatically via the GitHub CLI:

```console
$ grounded pr --title "chore(integrity): repair 38 stale symbol references"
grounded pr: created branch grounded-fix-1727479800
grounded pr: committed 4 modified file(s)
grounded pr: opened pull request https://github.com/org/repo/pull/142
```

---

## 6. Continuous Feedback with Watch Mode (`grounded watch`)

During active development sessions, run Grounded in continuous watch mode to maintain a warm index in memory:

```console
$ grounded watch
grounded watch: warm index active (842 files, 12,410 symbols)
watching for file modifications...
```

Watch mode monitors filesystem events. When a buffer is saved, Grounded executes an in-process delta recheck in approximately **0.6 milliseconds**, outputting new contradictions to the console immediately.

---

## 7. Institutional Baseline Gating

When introducing Grounded to an established repository with substantial pre-existing documentation drift, attempting to resolve all legacy contradictions in a single PR can halt development. Grounded solves this with **Baseline Gating**.

### Step 1: Snapshot Existing Findings

Generate a canonical baseline manifest:

```console
$ grounded baseline . --output .grounded-baseline.json
grounded baseline: recorded 156 finding(s) to .grounded-baseline.json
```

Commit the baseline manifest to version control:

```console
$ git add .grounded-baseline.json
$ git commit -m "chore: record initial grounded baseline manifest"
```

### Step 2: Enforce Delta Gates in CI

Configure your CI pipeline or local scan to evaluate against the baseline:

```console
$ grounded scan . --baseline .grounded-baseline.json
grounded: clean, 842 file(s) scanned, 0 new findings (156 suppressed by baseline).
```

* **Legacy Findings:** Suppressed automatically based on content and structural fingerprinting (independent of shifting line numbers).
* **New Findings:** If a newly introduced commit introduces a lie or drift, Grounded exits with status `1`, blocking the regression while allowing ongoing feature development.
