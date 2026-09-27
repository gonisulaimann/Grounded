# CLI reference

Generated from `grounded --help`; if this page and `--help` disagree,
`--help` wins.

## Commands

| Command | Purpose |
|---|---|
| `scan [PATH]` | Scan a directory (or one file). Never writes. |
| `baseline [PATH]` | Record findings to `.grounded-baseline.json`. |
| `fix [PATH]` | Rewrite unambiguous findings. Prints without writing under `--dry-run`. |
| `impact SYMBOL [PATH]` | Definers, importers, and claims (comments, doc examples, mocks, entry points) for a symbol. Never writes. |
| `list [PATH]` | List files that would be scanned. Never writes. |
| `explain [CHECKER]` | Describe a checker (or where a removed one went). Never writes. |
| `init` | Write a starter `grounded.toml`. Refuses to overwrite without `--force`. |
| `init-agent` | Write Claude/Cursor/Aider configs, or install the agent skill (`--skill` for all projects, `--skill-project` for this repo). Refuses invalid JSON, never merges YAML blindly, never writes outside the repo without `--skill`. |
| `hook claude-code` | Claude Code PostToolUse adapter: reads the edit event on stdin, checks changed lines plus rename fallout, exits `2` with findings on stderr (fed back to the model). Never writes. |
| `doctor` | Installation and agent-wiring health (engine vs PyPI, hook currency, skill, MCP handshake). Read-only; exit `1` is diagnostic. |
| `watch [PATH]` | Rescan on every change; report only introduced findings. Status on stderr, findings on stdout. Exit `0` always (monitors report, they don't gate). |
| `mcp` | Serve MCP over stdio (`check_path`, `explain_checker`, `blast_radius`, `check_text`). Never writes. |
| `lsp` | Serve LSP 3.17 over stdio. Never writes. |

Only `fix` (without `--dry-run`) writes, and only the lines of
unambiguous findings. Everything else is read-only by construction.

## `scan` flags

| Flag | Effect |
|---|---|
| `--format terminal\|json\|sarif\|markdown\|html` | Output shape (default `terminal`). `markdown` is a GitHub-flavored table for PR comments and job summaries. |
| `--output FILE`, `-o` | Write the report to a file instead of stdout. |
| `--fail-on lie\|drift\|smell\|never` | Minimum severity that exits `1` (default from config, else `lie`). |
| `--enable ID,...` / `--disable ID,...` | Run a subset of checkers. Unknown ids fail with exit `2` (a typo must never silently run a different set); an emptied set falls back to all. Opt-in checkers (`stale-doc-ref`, `stale-contract-ref`, `ghost-export`, `phantom-package`, `stale-cli-ref`, `stale-cli-flag`, `stale-api-ref`) run only when named. |
| `--baseline FILE` | Report only findings not recorded in FILE. `--show-baselined` also lists suppressed findings on stderr. |
| `--changed [BASE]` | Report findings on lines changed vs BASE (default `HEAD`) and in new files, plus findings anywhere that the change introduced (in a full scan of the worktree, not in one of the base). Only files that can reach a changed name are checked. Edits to files checkers read from disk (manifests, `.gitignore`, `tsconfig`) fall back to the broad rule (findings naming any identifier on a changed line), announced on stderr. Errors outside git (exit `2`). |
| `--no-index-cache` | Rebuild the repo index from scratch instead of reusing unchanged files' entries from `.git/grounded/` (also `GROUNDED_NO_INDEX_CACHE=1`). |
| `--cache [FILE]` | Replay per-file results when the whole tree (every indexed file, manifests, config) is unchanged since they were written (default `.grounded-cache.json`). Corrupt or mismatched caches fall back silently. |
| `--jobs N` | Parallel workers. Auto by file count (serial below 512 files); output identical either way. |
| `--config FILE` | Explicit config file instead of discovery. |
| `--no-color` | Disable ANSI colors. |
| `--quiet`, `-q` | Findings count only. |

## Exit codes

`0` clean (or below the fail gate), `1` a finding meets the gate,
`2` usage or environment error (bad path, unreadable baseline/config,
unresolvable git base). A typo can never mask drift with a green build.

## Environment

No environment variables are read. No network calls are made. The
working directory matters only as the default scan root and, for
`init`/`init-agent`, the write target (current directory, never the
scan path).
