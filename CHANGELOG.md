# Changelog

All notable changes to `grounded` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Fixed
- **A checker that raised was silently skipped, and the scan still reported
  `clean`.** `_scan_one` caught `Exception` and continued, so a crash was
  indistinguishable from a checker that found nothing: the summary printed
  `grounded: clean, N file(s) scanned, 0 findings` and exited `0`. Every gate
  built on that output could therefore only get *greener* from a bug — which
  is exactly how `stale-doc-ref` stayed dark on any tree without a manifest
  (its `declared_dependencies()` returned `None`) while the dogfood
  `self-verify` gate read `clean`. Failures are now recorded per checker and
  file, reported on stderr grouped by cause (one broken checker over a
  10k-file tree is one line, not 10k), and a scan that has any of them can no
  longer print the word `clean`.
- **The README's fences did not balance, so 186 of its last 248 lines
  rendered as one code block on GitHub** — the `stale-symbol-ref` table,
  Configuration, Limitations and Contributing sections included. A
  ` ```console ` block opened at line 216 was never closed, and in Markdown
  an unterminated fence runs to EOF, so every fence after it inverted: 49
  fences, odd. The rendering damage was the visible half; the silent half is
  that `stale-cli-ref` stopped checking the whole tail of the file, since an
  invocation inside a code block is not parsed as one. Now 50 fences,
  balanced, with a test pinning the parity so the class cannot return
  unnoticed.
- Releases were shipping **three of four macOS/desktop binaries without
  saying so**. The `darwin-amd64` leg asked for `runs-on: macos-13`, an image
  GitHub retired, and a job pointed at a retired runner does not fail — it
  stays **queued forever**. The matrix therefore never went red, nothing
  reported the gap, and because `install.sh` derives
  `grounded-${OS}-${ARCH}` from `uname`, Intel Macs got a 404 from the
  advertised one-liner and blamed the network. Measured 2026-09-22: three
  runs stuck queued, the oldest over 20 hours. The two macOS legs are now a
  single `macos-latest` leg that builds a **universal2** binary and
  publishes it under both historical asset names, so no installer, README
  link or user script changes. `timeout-minutes` does **not** cover queue
  time, so the fix is removing the runner dependency rather than bounding
  it.

### Added
- Exit code `3` for an incomplete scan, distinct from `1` on purpose: a
  finding is a verdict about the repo, a checker error means there is no
  verdict at all, so a pipeline can tell "this repo has problems" from "this
  scan is not trustworthy". The MCP `check_path` result carries `incomplete`
  plus `checker_errors`, and `baseline` refuses to write a file from an
  incomplete scan — a blind spot must never be persisted into every later
  gate. `--disable <id>` and `fail_on = "never"` remain as the two explicit
  ways to proceed, and neither hides the error. The cache format is v2: it
  now stores per-file checker errors, because replaying a v1 entry would
  re-import "no findings" for a file whose checker had crashed.
- `verify-release.yml`, an independent audit of the published asset set
  (every release, plus daily). A leg that never starts cannot report on
  itself, so the audit runs outside the producing workflow: it waits up to
  30 minutes for all four assets, checks the macOS assets are genuinely fat
  Mach-O carrying both `arm64` and `x86_64`, names the outstanding leg and
  its runner label when it fails, and opens a deduplicated issue for any
  trigger — including the release event, where a red run would otherwise be
  seen by no one.
- `bench/recall.py`, a repo-scale **recall** harness. `corpus/run.py`
  measures precision in isolation and is structurally unable to measure this:
  it plants rot in the smallest tree that shows the behavior, so it says
  nothing about whether the checker still fires with a real repository around
  it — a definition two directories away, a manifest that declares the
  package, a build directory that looks generated. The harness plants each
  firing corpus case into a *copy* of a real repo, one case at a time and
  root-relative, and requires the expected finding to reappear as a delta
  against a baseline scan. Outcomes are three-way — caught, missed, and *not
  planted* when a fixture may not overwrite a host file (excluded from the
  number, never counted as a failure) — and a checker that raised refuses to
  produce a recall number at all. Measured 2026-09-22 over Grounded, flask,
  requests and svelte (3,922 files): 77 expectations, **0 misses, 0 checker
  errors**.
- Three corpus cases for the checkers that had no firing fixture at all
  (`stale-symbol-ref`, `number-drift`, `fragile-anchor`), so all 12 checkers
  are now held to a designed true positive instead of only to silence. The
  corpus goes 37 → **40 cases**.
- `scripts/sync-skill.py` — the agent skill is now generated, not
  maintained: `src/grounded/skill/` is the source of truth (it is what
  `init --agent` installs and what the wheel ships) and the top-level
  `agent-skill/` is its mirror. A doc correction used to be typed twice and
  verified by a test that only reported *that* the trees had drifted; now
  `--check` reports the exact file and the test runs the real generator.
- `--target-arch universal2` builds assert their precondition first: the
  macOS build refuses to start unless the interpreter is genuinely
  universal2 (setup-python's macOS packages are, verified from the published
  packages' own Mach-O headers — `bin/python3.11` and
  `libpython3.11.dylib` both report `x86_64 arm64`), then gates the output
  with `lipo -archs`. A thin binary can therefore never be published, least
  of all under the amd64 name.

### Changed
- `docs/rules.md` no longer treats isolation precision as repo recall, and no
  longer cites a stale count: it claimed 14 corpus cases where there are 40,
  and now records both measurements separately — 1.00 precision across 40
  corpus cases, and 77 planted expectations with 0 misses at repo scale. The
  README's development block listed `243 tests` and now states the measured
  261, plus the recall command.
- The graduation note for `stale-entrypoint` and `stale-mock-ref` no longer
  claims precision from silence alone. "Silent on 5 real repos" is not
  reproducible evidence and cannot distinguish a precise checker from a dead
  one, so it is restated as measured with the checker-error count at `0` —
  0 false positives over **15,196 files** in svelte (3,489), OmniRoute
  (11,581), flask (88) and requests (38), where the count proves both
  checkers actually ran. `docs/rules.md` now requires that count before
  "silent on N repos" may be cited as evidence at all.

## [0.16.0] - 2026-09-22

### Fixed
- Negated backticked claims ("there is no call to X") no longer fire.
- `e.g.`/`i.e.` illustrative paths no longer fire (trailing-`\b` never
  matched them in real prose).
- Go stdlib roots (`fmt`, `time`, `os`, …) silent in doc examples.
- Same-package cross-file Go/C calls suppress ghost findings;
  mutually exclusive `//go:build` variants never flagged.
- `stale-import` no longer claims a module is missing when the specifier
  resolves **above the scan root**. Sub-tree and single-file scans (the
  advertised agent loop) manufactured 51 lies on OmniRoute's `src/lib`
  for `../../shared/...` and `../../../open-sse/...` targets that exist
  one level up; the same tree scanned from the repo root reported 3, and
  now both agree. Applied to the relative and alias resolution arms.
- `ghost-export` no longer hides a live use that sits on a line opening
  with an inline block comment (`/** @param {T} x */ (x) => use(x)`):
  `_code_text` keeps the code after a `*/` that closes mid-line instead
  of blanking the whole line (measured: svelte's `reg_exp_entity`).
- `ghost-export` stays silent under generated/expected-output paths
  (`_expected/`, `__snapshots__/`, `snapshots/`, `generated/`,
  `codegen/`, `*.gen.*`): reachability of generated code is unknowable,
  so neither is the claim that nobody can reach it (measured: 10 of 11
  svelte findings were `tests/snapshot/samples/*/_expected/` output).
- `stale-doc-ref` precision round on a real docs corpus: documentation
  highlight markers (`+++`/`---`) are stripped before identifiers are
  extracted, destructured fixture parameters (`async ({ page }) =>`) and
  other in-example bindings count as known, ambient web-platform roots
  (`customElements`, `getComputedStyle`, observers, workers) stay
  silent, and doc-tooling directives (`// @noErrors`, `@errors`,
  `/// file:`, `---cut---`) mark a block illustrative. svelte went from
  12 lies to 0.
- `stale-file-ref` no longer reports a path under a directory the scan
  deliberately ignores (build outputs, vendor trees, coverage): those
  files are never indexed, so their existence cannot be judged. Removed
  20 findings on a real monorepo, all generated or written at runtime
  (`dist/docs/openapi.yaml` in CLI help text, `dist/index.cjs` in a
  setup command).
- `stale-file-ref` no longer reports elided paths (`src/.../File.tsx`).
  The placeholder list already intended to silence these, but the
  segment split turned `...` into empty strings and never matched.
- `grounded baseline` de-duplicates its fingerprints before writing. Two
  findings can share a fingerprint (it hashes rule, path, title and
  claim, never line numbers), so the file held repeats and disagreed
  with the `total` the command printed (measured: 284 entries for 277
  unique fingerprints).
- `stale-doc-ref` is no longer silently disabled on a tree with no
  manifest anywhere: `declared_dependencies` returns `None` there and the
  checker iterated it, raising inside a swallowed checker guard. Absence
  of a manifest is now an empty declared set, not a dark checker.

### Added
- Adversarial corpus (`adv-*`, 19 cases): planted agent-style rot that
  must fire (rename fallout, moved paths, stale CLI flags, real ghosts)
  alongside legitimate lookalikes that must stay silent (PEP 562 lazy
  attributes, namespace packages, star re-exports, guarded imports,
  pytest doubles, docs prose, CJS interop, `+++`-annotated examples,
  generated `_expected` output, inline-comment-guarded calls). 37/37
  cases green.

### Fixed
- `stale-doc-ref` JavaScript precision across two rounds: ambient roots
  (platform, Node, `this`), JS call-keywords (`catch (e)`),
  continuation chains, template-literal contents, ESM/arrow/function/
  method bindings, package self-name, manifest-declared externals
  (unioned up the tree, kebab/camel agnostic), self-dir
  `require('..')`, DOM event constructors, and cross-block tutorial
  narrative no longer report. Axios docs: 580 → 40 (≈8 unique
  narrative-residue families, documented as the boundary).

## [0.15.0] - 2026-09-22

### Fixed
- `phantom-package` no longer reports guarded imports (`try/except`,
  `TYPE_CHECKING`, version/platform conditionals are compat shims by
  the project's own doctrine): 43 findings removed on django with zero
  true positives among them.
- `stale-contract-ref` no longer treats ALL-CAPS names in a bare "use
  X instead" frame as deprecation targets (SQL/platform builtins like
  `JSON_TYPE`); explicit `DEPRECATED:` notices are still checked.
- Parse-failure opacity: modules that fail `ast.parse` (version-skewed
  grammar, truncated buffers) are marked opaque instead of indexing
  zero symbols, which cascaded into phantom absence lies (24,881
  `stale-import` findings on home-assistant/core under Python 3.13).
  Top-level bindings are recovered heuristically, and the scan summary
  reports the unparsed count.

### Added
- Graduated `stale-mock-ref` and `stale-entrypoint` to default-on.
  Mock strings resolve progressively (cross-module chains, aliases,
  proxies, builtins injected into module namespace); entrypoint and
  mock evidence came from silent runs on django/CPython plus fixtures.
- `grounded init-agent --pre-commit` writes `.pre-commit-config.yaml`
  with the grounded hook (refuses to merge, like the Aider config).

### Fixed
- `collect_files`: symlinked directories are no longer followed — inside
  the root they duplicated whole trees under a second rel path (seen:
  OmniRoute's `@omniroute/` -> `open-sse/` workspace-alias symlink,
  doubling findings and poisoning alias resolution), and outside the
  root they pulled foreign trees into the snapshot.
- `collect_files`: `.claude/worktrees/` (agent-session worktrees holding
  full second copies of the repo) is skipped. Seen on OmniRoute: 4,027
  of 4,458 findings were worktree duplicates of real files.
- `stale-import` (JS/TS): bare specifiers whose resolution is invisible
  to snapshot analysis no longer report. Two classes suppressed: the
  repo's own package name (self-imports resolve through the package
  exports map / bundler self-reference, not the tsconfig paths shim) and
  bare aliases whose every replacement is outside the scanned tree or a
  types-only `.d.ts` surface. Fixture: sveltejs/svelte went from 1,253
  `stale-import` findings (1,235 false drift on `svelte`/`svelte/*`
  self-imports) to 18, all genuine. Aliases mapped onto the scanned tree
  are unchanged and stay fully checked (regression-tested both ways).
- `stale-import` (JS/TS): TypeScript-style `.js`-extension relative
  imports now resolve the same-named `.ts`/`.tsx`/`.mts`/`.cts` sibling
  (default `tsc` behavior); the resolved module is checked normally.
- `stale-import` (JS/TS): extensionless specifiers resolving to an
  ambient `.d.ts` module are silent — declaration files are
  existence-tracked (`RepoIndex.decl_paths`), never parsed, so the
  checker no longer claims an ambient type module does not exist.
- `stale-import` (JS/TS): relative imports into directories the scan
  deliberately ignores (`vendor`, `build`, `dist`, ...) no longer report
  "does not exist" — the target may be a real file the snapshot skipped
  (seen: OmniRoute's tracked `open-sse/vendor/` and `scripts/build/`).
- `stale-import` (JS/TS): `require()` default-shape imports from `.js`
  importers stay silent — a `.js` file may run as CJS, where the call
  binds any `module.exports` shape. Forced-ESM (`.mjs`) importers are
  still checked.
- `stale-import` (JS/TS): tsconfig/manual alias targets that land in a
  scan-ignored directory (vendor, build, dist, ...) are never findings —
  the alias arm now shares the relative arm's verdict (seen: OmniRoute
  `@omniroute/open-sse/*` reaching tracked `open-sse/vendor/` code).
- `stale-import` (JS/TS): TS `type` modifiers inside re-export braces
  (`export { type X }` / `export { type X as Y }`) are stripped before
  recording, so re-exported types stay on the module's export surface
  (seen: OmniRoute barrel re-exporting `ProviderMessageTranslator` —
  13 bogus stale-imports on its importers).
- `stale-import` (JS/TS): files under a tsconfig `exclude` prefix are
  outside the repo's own typecheck contract and never report missing
  modules — codegen templates whose relative imports resolve only after
  transplantation (seen: svelte's excluded
  `scripts/process-messages/templates/`). After these five suppressions
  the svelte fixture reports zero `stale-import` findings, with the
  genuine relative-miss cases now resolved correctly instead.

### Added
- Rename mapping across all claim surfaces: `impact` / MCP
  `blast_radius` now report claims from doc examples, mock strings,
  entry points, and contract frames — not just comments. Docs and
  manifests ride along in query paths only; gated scans are
  byte-identical.

### Added
- `stale-entrypoint` (experimental, opt-in): `pyproject.toml`
  `[project.scripts]` targets and `package.json` `bin`/`main` paths
  pointing at nothing in the repo. Manifest files are collected only
  when it runs.
- `stale-mock-ref` (experimental, opt-in): `@patch`/`patch.object`
  strings naming symbols absent from the in-repo module.
- `phantom-package` (experimental, opt-in): absolute imports declared
  in no manifest, with unioned manifest closure (all dep groups,
  requirements includes, monorepo-aware) and an import→distribution
  map for the notorious mismatches.
- `stale-cli-ref` (experimental, opt-in): documented `grounded`
  invocations with unknown subcommands or flags, verified against the
  live parser (undriftable by construction).

### Fixed
- `src/` and `lib/` layout packages resolve in absolute imports (was:
  entire layouts silently skipped as third-party).

## [0.14.0] - 2026-09-21

### Added
- `--changed` rename-fallout expansion: findings off the diff still
  report when their claim names a diff-touched symbol. Only verified
  findings surface; the demo is `demo/firewall.sh` (30 seconds,
  self-checking).
- Repo-scale benchmark harness (`bench/run.py`: cold-CLI latency,
  throughput, RSS, findings as JSON) and the firewall demo (`demo/`).

### Fixed
- PEP 695 `type X = ...` aliases indexed (was: false lies on every
  import from such a module).
- `./`-prefixed index paths normalized before JS export lookup (was:
  false "no default export" on directory imports).
- `require('./x').prop` treated as a named import, not a default
  import.
- Default imports from CJS-shaped targets stay silent (Node interop
  always binds); the missing-default check applies to ESM targets.
- `from . import X` follows star re-exports and yields to
  `globals().update()` namespaces (static-analysis boundary, seen on
  CPython).
- `Xxx`/`XXX` placeholder names never report in `stale-symbol-ref`.

## [0.13.0] - 2026-09-21

### Added
- `grounded init-agent --skill` installs the agent skill to
  `~/.claude/skills/grounded/` (all projects); `--skill-project`
  installs to `.claude/skills/grounded/` (this repo only). Skill files
  ship inside the package, so pip/uvx/brew installs work with no repo
  checkout. Bare `init-agent` behavior is unchanged.
- ClawHub publish path documented (`docs/agent-skill.md`); skill
  frontmatter name is now `grounded` to match its directory.
- `stale-doc-ref` (experimental, opt-in): fenced Markdown code examples
  calling symbols defined nowhere in the repo. Excluded from every
  default set; run with `--enable stale-doc-ref`. Markdown files are
  collected only when it runs, so default scans are unchanged.
- VS Code / Cursor extension (`editors/vscode/`): thin LSP client with
  explicit server resolution (PATH, `serverPath`, or consent-gated
  uvx). Published on Open VSX; VS Code Marketplace pending.
- `stale-contract-ref` (experimental, opt-in): deprecation targets,
  lock-holder claims, and env-var defaults in comments that contradict
  the repo. Narrow frames only; bare prose never reports.
- `ghost-export` (experimental, opt-in): public symbols with no
  importers, no in-file use, and no API marking.
- Precision corpus (`corpus/`): planted-staleness fixtures with exact
  expected findings, enforced in CI. 10 cases, all checkers at 1.00
  precision and recall on the corpus.
- Attribute-call tracking: `from pkg import mod` + `mod.name()` counts
  as an importer (ghost-export suppression, `blast_radius` recall).

### Fixed
- Index records original names alongside import aliases (`import x as
  y` counts as a dependency on `x`).
- MCP `check_path` and `blast_radius` honor the `grounded.toml` in the
  scanned root (previously bare defaults: agents saw different results
  than the CLI).

### Removed
- Dead helper `path_to_uri` (found by `ghost-export` dogfooding).

## [0.12.1] - 2026-09-21

### Changed
- Documentation overhaul: language ribbon with 9 translated quickstarts
  (AR, ES, PT-BR, FR, DE, CN, JP, RU, KR), expanded rules reference,
  corrected installation pins.
- Action Marketplace description covers PR annotations, baselines, SARIF.

## [0.12.0] - 2026-09-21

### Added
- Claim graph: symbols, imports, and comment claims as queryable edges.
- `grounded impact SYMBOL`: definers, importers, and comment claims for
  a symbol (answers "what breaks if I rename this?").
- MCP `blast_radius` tool with the same query surface for agents.

## [0.11.1] - 2026-09-21

### Added
- Unknown suppression ids warn on stderr (`grounded-disable: stale-symobl`
  no longer fails silently); the gate exit code is unchanged.

### Changed
- `fix` help text covers symbol renames, not just file paths.

## [0.11.0] - 2026-09-21

### Added
- Alias refinements: node_modules mappings skipped, unresolvable aliases
  report as drift (generated files stay out of the default gate),
  `export type` recognized, bare `export *` marks export sets unknowable.
- Mid-typing tolerance: broken Python buffers still yield comment
  diagnostics; editor flicker test pins it.

### Changed
- Memory optimization declined after measurement: index heap 31 MB on
  2,977 files (~10 KB/file); interning moved nothing. Documented as the
  scaling ceiling instead (~500 MB at 50k files).

## [0.10.1] - 2026-09-21

### Fixed
- Config files work on Python 3.10 via a strict built-in TOML subset
  reader (parity-tested against tomllib; verified on real 3.10).

## [0.10.0] - 2026-09-21

### Added
- JS/TS path-alias resolution: tsconfig `paths` auto-detected per
  directory (JSONC tolerant, `extends` chains, longest-prefix wins) plus
  manual `path_aliases` config. Unresolvable aliases report as drift.
- Config files work on Python 3.10 via a strict built-in TOML subset
  reader (parity-tested against tomllib; anything outside reads as
  unreadable, never half-applied).

## [0.9.0] - 2026-09-21

### Added
- `stale-import` now covers JS/TS relative imports (module existence,
  named/default exports, star re-exports; bare and asset specifiers skip).
- LSP incremental index: buffer edits re-index the file, peer documents
  re-diagnose, close reverts to disk. Single-file patch measured 9-22 ms.
- `grounded init-agent`: generates Claude hook, Cursor rule, Aider config
  (idempotent, refuses invalid JSON, never merges YAML blindly).
- Parallel threshold retuned to 512 files / 8 workers on measurements
  (parallel loses below ~500 files; 12-way oversubscription regressed).
- Disk cache (`scan --cache`): mtime+size keyed per-file findings.

## [0.8.0] - 2026-09-21

### Added
- `stale-import` checker: resolvable Python imports verified (module
  exists; name defined, re-exported, or a submodule). Star re-exports,
  tuple targets, nested compat blocks, `__getattr__` modules, and dunder
  imports handled; guarded and external imports never flagged.
- `grounded lsp`: stdlib LSP 3.17 server (diagnostics + quickfix actions),
  protocol-tested including a full heal loop.
- File-scoped `scan`/`fix`: a file argument scopes reporting (and
  rewriting) to that file; the index still spans the tree.
- Agent recipes: verified Aider lint loop, Claude Code hooks JSON, Cursor
  rules snippet.
- `examples/bench/bench.py`: reproducible pre-test-filter timings.

### Changed
- General Markdown verification declined after measurement; symbol rename
  autofix requires scope plus similarity (ties never touch).

## [0.7.1] - 2026-09-21

### Changed
- Distribution renamed to `grounded-lint` on PyPI (bare `grounded` was
  claimed). Command (`grounded`), import package, and action behavior
  unchanged.

## [0.7.0] - 2026-09-21

### Added
- `grounded mcp`: stdlib MCP server over stdio (initialize negotiation,
  tools/list, tools/call, ping) with `check_path` and `explain_checker`
  tools; paths confined to the server root. Verified with an independent
  Node client against the spec.
- Symbol renames in `grounded fix`: exactly one similar (ratio 0.75+),
  same-directory candidate, or nothing is touched. Proven on the case
  that killed naive similarity autofix.
- Per-symbol defining files in the repo index (powers scope proximity).

### Changed
- General Markdown verification declined after measurement (199 import
  claims trivially valid, flag claims mostly external tools on axios
  docs); overlaps readme-ci, doccident, doc-drift, and docverity.

## [0.6.0] - 2026-09-17

### Added
- C support (`.c`/`.h`): functions incl. split declarations and K&R style,
  types, macros, function-pointer members, `#include` maps.
- Parallel scanning (`--jobs N`, auto by file count; identical output).
- VS Code task snippet using the bundled problem matcher.

### Changed
- JS index covers default exports, `module.exports` members, TS
  interfaces/types (no benchmark delta).

## [0.5.0] - 2026-09-17

### Added
- Go support: functions, types, and imports across all four checkers.
- `grounded fix [--dry-run]`: rewrites unambiguous stale file paths
  (unique same-basename match, comment lines only).
- Inline suppressions: `# grounded-disable: <id>` (`//` form for JS/TS/Go).
- First-party GitHub Action with problem matchers (verified live on a
  test PR); pre-commit hook definition.

### Changed
- File references use exact-path semantics and list same-named candidates;
  ticket-anchored history notes stay silent.
- Markdown files are not scanned: measured zero file-reference hits across
  160 documentation files, so no evidence of value (rejected).
- Symbol rename autofix rejected: string-similarity ranking picked the
  wrong target on a real case; suggestions stay advisory-only.

## [0.4.1] - 2026-09-17

### Fixed
- CI demo-fixture count to match current fixtures. No product changes.

## [0.4.0] - 2026-09-17

### Added
- Inline suppressions: `# grounded-disable: <id>` (`//` form for JS/TS).
- First-party GitHub Action (`action.yml`) with problem matchers for inline
  PR annotations; verified live on a test PR.
- Pre-commit hook definition (`.pre-commit-hooks.yaml`).

### Changed
- Commented-code suppression gate tightened (prose with a few keywords no
  longer qualifies).

## [0.3.0] - 2026-09-17

### Added
- `grounded baseline`: record current findings to `.grounded-baseline.json`.
  `scan --baseline FILE` then reports only new findings. Fingerprints hash
  checker, path, and claim text (never line numbers), so unrelated edits
  that shift lines do not churn the file. `--show-baselined` lists
  suppressed findings.
- `scan --changed [BASE]` (default: `HEAD`): report only findings on lines
  changed relative to BASE, for PR gates and pre-commit use. The tree is
  still fully scanned; reporting is filtered. Fails loudly outside git.
- `.gitignore`, contributor fixture guidelines in README.

## [0.2.0] - 2026-09-17

### Changed
- Deleted `param-mismatch`, `raises-mismatch`, `return-mismatch`,
  `commented-code`: verified redundant with darglint/pydoclint,
  eslint-plugin-jsdoc, and Ruff ERA001. `explain <id>` now routes to them.
- Rebuilt `stale-symbol-ref`: import-aware (stdlib/deps/relative), same-file
  scope proxy, Sphinx/JSDoc-tag scrubbing, dunder-typo class, verb-gated
  bare calls, acronym/negation/ticket gates, `difflib` rename suggestions.
- Hardened `stale-file-ref`: repo-scope rule, alphabetic extension list,
  placeholder + illustrative-example handling.
- Tightened commented-code suppression gate (suppression-only use).
- Excluded TypeScript declaration files (`.d.ts`/`.d.cts`/`.d.mts`).
- Measured on requests/axios/django: 844 → 42 findings; the 1 remaining
  lie is a confirmed true rename-rot.

### Added
- `examples/v2demo`: 4-file fixture tree (8 intended findings, designed
  silences for every suppression rule).
- MIT `LICENSE`, CI workflow (tests + self-scan gate), this file.

## [0.1.0] - 2026-09-16

Initial release: 8 checkers. Superseded by 0.2.0, which narrowed scope to
reference checks and removed contract checks covered by other linters.
