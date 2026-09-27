# Commands reference

Condensed CLI surface for agents. Flags not listed here do not exist;
do not invent invocations.

```console
grounded scan [PATH] [--format terminal|json|sarif|markdown|html] [--output FILE]
              [--fail-on lie|drift|smell|never]
              [--enable ID,...] [--disable ID,...]
              [--baseline FILE] [--show-baselined]
              [--changed [BASE]] [--cache [FILE]] [--no-index-cache] [--jobs N]
              [--config FILE] [--no-color] [--quiet] [--cross-index DIR]
grounded baseline [PATH] [--output FILE]
grounded fix [PATH] [--dry-run]
grounded pr [PATH] [--title T] [--dry-run]
grounded generate-agent-rules [--output AGENTS.md] [--force] [--dry-run]
grounded badge [--check]
grounded impact SYMBOL [PATH] [--format terminal|json]
grounded list [PATH]
grounded explain [CHECKER]
grounded init [--force]
grounded init-agent [--claude|--cursor|--aider] [--skill] [--skill-project]
               [--pre-commit] [--force] [--dry-run]
grounded mcp [--root .]
grounded lsp
grounded doctor [--json]
grounded watch [PATH] [--interval SECONDS] [--enable ID,...] [--disable ID,...]
grounded hook claude-code [--fail-on lie|drift|smell]
```

Contracts:

* `scan <file>` checks one file, exit 1 on findings, 0 when clean, 3 when an enabled checker raised (incomplete scan).
* `scan` never writes. Only `fix` (without `--dry-run`) writes, and only
  the lines of unambiguous findings.
* `--changed` reports on-diff findings plus rename fallout: verified
  findings anywhere that name a diff-touched symbol.
* `impact` never writes. `mcp` and `lsp` never write.
* Machine output: `--format json` (scripts), `--format sarif` (code
  scanning). Terminal output is for humans; parse JSON instead.
* `stale-doc-ref` is opt-in: `--enable stale-doc-ref`. Never assume it
  ran; default scans exclude it.
* `init-agent --skill` installs this skill to `~/.claude/skills/grounded`
  (all projects); `--skill-project` installs to `.claude/skills/grounded`
  (this repo only). Bare `init-agent` never writes outside the repo.
* `watch` reports only findings introduced since the previous scan
  (exit 0 always: monitors report, they don't gate). `doctor` checks
  installation and agent-wiring health (exit 1 is diagnostic).
* MCP adds `check_text`: resolve names/paths in free text to
  known/unknown before acting. Query first; fix after.
