# Changelog

All notable changes to `grounded` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- **`scan --cross-index DIR`**: two-root API verification for
  `stale-api-ref` (the flag itself is the pairing evidence).
- Doc-example bindings: comprehension targets, trailing-comment
  prose, and the `cls` convention stay silent.
- `check_text` query leniency: function parameters answer as known
  (qualified), unique case-insensitive hits note the casing, tool
  names (`pip`, `git`, `docker`, …) stay silent. Checkers unchanged
  and strict.

### Added
- **`scan --cross-index DIR`**: two-root API verification. The other
  tree's OpenAPI/Swagger routes join the route set `stale-api-ref`
  checks against; the flag itself is the pairing evidence, reporting
  stays on the primary tree. A client calling a route the other tree
  removed now fires with cross-tree evidence.

## [0.17.0] - 2026-09-27

### Added
- **`stale-api-ref`** (opt-in): HTTP-call string literals verified
  against the repo's own JSON OpenAPI/Swagger documents, templates
  matched segment-wise. The cross-repo contract problem in miniature;
  design for the two-root mode in `docs/cross-repo.md`.

### Changed
- **`--changed` reports what the change introduced, not every finding that
  shares a word with it.** The old rule kept any finding, anywhere, whose
  claim named an identifier from a changed line, so an edit to a line
  containing `self` or `None` surfaced old findings from across the repo.
  Measured on 12 consecutive cpython commits: 357 findings reported, every
  one of them present before the commit (0 introduced). Off the changed
  lines, a finding is now reported when a full scan of the worktree has it
  and a full scan of the base does not. It costs far less than two scans:
  the base index reuses every unchanged file's entry, only files that can
  reach a changed name are checked (they import its module or spell
  `module.name`; a name whose repo-wide presence changed is searched
  everywhere), and only files with a finding naming a changed name are
  re-checked at the base. Verified against two full scans per commit:
  exact on 30 consecutive django commits, 29 cpython commits, and 10
  constructed renames, deletions, mock-target and in-file cases (69 samples,
  32 introduced findings, 0 missed, 0 extra; tests pin seven cases).
  Changes to files checkers read from disk (`pyproject.toml`,
  `package.json`, `setup.*`, `.gitignore`, `tsconfig`, `requirements`)
  fall back to the old rule, announced on stderr in every format.
- **`--changed` latency** on real history (each commit replayed as
  uncommitted work, fresh process, interpreter start included,
  `bench/changed.py`): cpython p50 10.3 s -> 1.9 s, p95 13.0 s -> 3.4 s;
  django p50 8.2 s -> 1.2 s, p95 14.9 s -> 3.3 s. Over the same 30 django
  commits the old rule reported 47 findings, none introduced by the commit;
  the new one reports 0.

### Added
- **`grounded doctor`**: installation and agent-wiring health in one
  command. Compares the engine against PyPI latest (fail-open offline),
  verifies the hook adapter exists, audits `~/.claude/settings.json`
  for the legacy exit-1 hook (findings reach you, never the model),
  checks the agent skill, and handshakes the MCP server. Exits 1 with
  actionable fixes when anything is stale — born from a real 0.11.0
  install silently running five versions behind.
- **Persistent index cache** in the git directory (`.git/grounded/`): each
  file's index contribution is stored by (mtime, size) and replayed, so a
  scan re-indexes only what changed (cpython index build 2.25 s -> 0.14 s
  load + merge). Entries within 2 s of the cache write are never trusted
  (the "racily clean" rule git applies to its own index), and any load
  problem is an empty cache. The rebuilt index equals a fresh build in every
  attribute (tested, with mutation checks). Opt out with
  `--no-index-cache` or `GROUNDED_NO_INDEX_CACHE=1`.
- `bench/changed.py`: `--changed` latency on real history (p50/p95/max,
  mode per sample).

### Fixed
- **`--cache` reported `clean` over a real lie.** A file's cached result was
  replayed whenever that file's own mtime and size were unchanged, but its
  findings depend on the rest of the tree: after `b.py` renamed the function
  `a.py` imports, `scan --cache` still printed `clean`. Results now replay
  only while the whole tree (indexed files, the files checkers read from
  disk, config) is unchanged.
- **`--changed` below the git top level** matched findings against
  top-level paths (`pkg/app/a.py` vs `app/a.py`); only the rename-fallout
  rule hid it. Diffs are now scan-root-relative (`--relative`).
- Untracked paths with non-ASCII names were read with git's quoting on
  (`ls-files -z` now).

### Performance
- Full scans, same output byte for byte: grpc-go 5.4 -> 4.0 s, django
  13.3 -> 11.1 s, cpython 42.0 -> 37.9 s, prettier 5.4 -> 3.3 s; with a
  warm index cache 3.0, 8.4, 32.1 and 2.5 s.
- `--changed` asks git 4 times instead of 13 (one worktree-vs-base diff
  gives hunks and identifiers, numbered by worktree lines).
- `collect_tsconfigs` walks with `os.scandir` (django 0.40 -> 0.13 s).
- Tree walk with `os.scandir` (entry types come with the directory read):
  cpython 0.12 -> 0.05 s, prettier 0.53 -> 0.17 s, identical file lists.
- Checker pools are sized by bytes to check, not file count: each worker
  first receives a pickled index (about 2.6 s for 8 workers on cpython),
  so 40 files ran 7x slower in parallel than serially.
- The unknown-suppression warning scanned every line of every file with a
  regex (2.2M calls on cpython); one substring test per file now gates it.

### Fixed (wide round: 55 repositories)
- **Lazy modules read as thousands of missing names.** A module that
  replaces itself (`sys.modules[__name__] = _LazyModule(...)`, the
  transformers/diffusers idiom) now has an unknowable export surface:
  transformers 5,157 lies -> 181 before the rest of this round.
- **Codegen templates:** relative imports that climb to a non-package repo
  root (transformers' `examples/modular-transformers`), ALL-CAPS module
  placeholders (`components.NEW_DOMAIN`), and outputs of Panda CSS, GraphQL
  Mesh, EdgeDB and fumadocs generators.
- **Local folders shadowing installed packages:** a top-level directory
  without `__init__.py` (home-assistant's `pylint/`) no longer captures
  imports of the real package (161 findings).
- **JS/TS/Flow parsing:** `export const enum`, `export declare`,
  `export namespace`, Flow `export opaque type`; export-less build shims
  (React's `ReactFiberConfig.js`); directory imports of folders named like
  build output (`../build` -> `build/index.ts`, next.js).
- **More fixture conventions:** jscodeshift `__testfixtures__`, Jest
  `__mocks__`, `input`/`snapshot` folders and `input.*`/`output.*` files
  under test roots (turbopack).
- **Platform APIs in comments:** syscall/libc names in Go and Python,
  Win32 APIs in Python files with Windows evidence, ECMAScript abstract
  operations and globals (`Symbol`, `Math.random`) in JS, and lowercase
  dotted names of namespaces the repo does not own (`jax.numpy.select()`).
- **Go doc comments were reported twice** (once per `//` line, once as the
  joined doc at another line).
- **stale-mock-ref doubled `import a.b.c as m` paths**
  (`a.b.c.a.b.c`), reporting every `patch.object(m, ...)` as missing.
- **A killed worker lost the whole scan.** The checker pool now falls back
  to the serial path like the index pool does.

### Added
- **`stale-cli-flag`** (experimental, opt-in): documented invocations of
  the repository's own programs using a long flag no parser in the repo
  declares. Programs from `[project.scripts]`, `console_scripts`,
  package.json `bin` and Go `cmd/`; flags from argparse, click, pytest
  `addoption`, Go `flag`/cobra/pflag and commander/cac; Markdown, reST and
  Sphinx `.txt` docs. Silent whenever the inventory cannot be complete.
- **`grounded hook claude-code`**: a Claude Code PostToolUse adapter. It
  reads the edit event on stdin, checks lines changed since `HEAD` plus
  rename fallout in other files, and exits `2` with the findings on
  stderr: the exit code Claude Code feeds back to the model. Its own
  failures exit `1` (human-only) and never wedge the agent loop.
- **`--format markdown`**: a GitHub-flavored findings table. The Action
  writes it to the job summary (`summary: 'true'`, default).

### Fixed
- **Source packages named like build output were never scanned.**
  `coverage/`, `build/`, `dist/` and `out/` were skipped by name, so
  coverage.py's and pypa/build's own packages were invisible. A directory
  holding `__init__.py` is now scanned unless `ignore_dirs` names it.
- **stale-mock-ref ignored submodules** (`patch.object(_ctx, ...)` after
  `from build import _ctx`).
- **stale-file-ref read `pyproject.toml/.coveragerc.toml` as a path.** A
  path whose directory part is an existing file is an alternatives list.
- **The Claude Code hook never reached the agent.** `init-agent --claude`
  installed `grounded scan . --changed --quiet`, which exits `1` on
  findings; Claude Code shows exit-1 stderr to the human only, and
  `--quiet` printed just counts. It now installs `grounded hook
  claude-code` (matcher `Edit|Write|MultiEdit`) and upgrades the legacy
  command in place.

### Changed
- **Directory scans index the whole project.** `grounded scan src` (and
  `baseline`, `fix`, `impact` on a subdirectory) now build the index from
  the directory's project root (nearest marker ancestor, never climbing to
  `~`) and scope only the *report* to the directory, as file arguments
  already did. Finding paths are project-relative (`src/app/x.py`, not
  `app/x.py`); regenerate baselines written from a subdirectory scan.

### Added
- **Real-repo precision gate** (`bench/precision.py`, CI
  `precision.yml`): 25 repos pinned by SHA; every lie/drift must be
  labeled TP/FP in `bench/precision/ledger.json`. Precision on that set
  went from 0.17 (30 of 175) to 0.77 (30 of 39) in this round with no
  true positive lost.

### Fixed
- **Precision round (25 real repos, 136 false positives removed).** Test
  fixture data (`tests/format/`, `tests/data/`, `fixtures/`, `testdata/`,
  `broken_*`) no longer reports; bundler resource queries, Node CJS
  extension appending, package.json `main`/`browser` resolution and
  symlinked sources resolve like Node does; destructured
  `export const {...}` and comments inside `export {...}` lists are
  parsed; gitignored build artifacts (nested `.gitignore` included),
  `.pyi`-only compiled modules and lazy string-keyed exports are
  evidence of existence; non-typo dunders, `Type#method()`, pluralized C
  calls, Win32 and included-library C APIs and `_suffix()` fragments are
  not repo claims; docstring path listings are samples; paths relative
  to the claiming file's directory and `<project>'s path` references
  resolve; number-drift compares the keyword's own value (including
  `==` comparisons); `require()` quoted inside strings is not an import;
  fences of a different character inside a declared fence are nesting.
- **Python 3.10 refused real projects.** Without `tomllib`, the subset
  reader parsed the whole `pyproject.toml` and exited 2 on other tools'
  syntax (`[[tool.mypy.overrides]]`) or any multi-line array, which is
  nearly every Python repo. It now reads only the `[tool.grounded*]`
  tables and supports multi-line arrays.
- **C includes were invisible.** The include pattern lacked
  `re.MULTILINE`, so only an include on a file's first line was seen.
- **Subdirectory scans manufactured lies.** A comment in `src/` naming a
  helper defined in `scripts/` was a `stale-symbol-ref` lie under
  `scan src` and clean under `scan .`; the same partial snapshot hid
  project-wide file refs from `scan src` CI gates. One file now gets one
  verdict whatever directory was named.
- **Metasyntactic paths read as file claims.** `src/mypkg/x.py`-style
  layout explanations (`my`-prefixed package nouns, `x`/`y`/`z` stems) are
  placeholders unless the file really exists (corpus:
  `adv-metasyntactic-path`, with a real stale path as positive control).
- **Runtime module aliases read as missing modules.** An ancestor module
  that writes `sys.modules` (requests' `packages.py` aliasing
  `requests.packages.urllib3.*`) now makes dotted imports below it
  unknowable instead of a `stale-import` lie. requests: 1 lie -> 0
  (corpus: `adv-sys-modules-alias`, with a missing sibling module as
  positive control).
- **History notes and ticket-anchored blocks reported as lies** (this
  round: httpx, preact — see below).
- **Recall harness phantom misses on case-insensitive filesystems.**
  README fixtures merged into the host's `Readme.md` matched no
  expectation by path (7 phantom misses on express). The harness now
  tracks on-disk names; express and flask recall 100% (23/23, 22/22)
  across all 13 checkers.
- **File scans indexed only the parent directory, manufacturing lies.**
  `grounded scan sub/file.py` (and the MCP/LSP file paths) built the
  index from the file's parent, so any name defined elsewhere in the
  repo reported as missing. File targets now index the file's project
  (nearest marker ancestor, bounded); reporting stays scoped to the
  named files, and MCP paths are server-root-relative.
- **Config failures were silent defaults.** A missing `--config` file,
  a corrupt `grounded.toml`, and unknown checker ids in `--enable`,
  `--disable`, `enable`, or `disable` now fail with exit 2 instead of
  running a different configuration with a green build.
- **`--changed` hid staged lines.** Only branch + unstaged diffs were
  gated; `git add` moved lines out of the gate. Staged (`--cached`)
  hunks and symbols are now included, and non-ASCII paths are unquoted
  before matching.
- **A corrupt baseline crashed `grounded baseline`.** Overwriting a
  corrupt file now treats it as empty instead of tracebacking.
- **Cyclic tsconfig `extends` crashed the scan** with `RecursionError`.
  Cycles now resolve to empty.
- **MCP `fail_on: "never"` still failed** on lies, and notifications
  received responses with `id: null`. Report-only is now total, and
  notifications are silent per JSON-RPC.
- **An LSP outside-workspace file overwrote its same-named in-root
  file's index entry**, deleting real symbols. Outside files are now
  keyed collision-free.
- **`fix` followed symlinked directories** (duplicate ties, and a
  cyclic link walked forever). Same guard as the scanner.
- **HTML report placeholders collided with repo names**: a root
  literally named `__LIE__` printed 0 and injected the rows table.
  Single-pass substitution.
- **TOML fallback misread** `[[tables]]`, dotted keys, trailing
  commas, and `\u` escapes on Python 3.10. Now rejects or decodes
  per spec.
- **Metasyntactic calls (`foo()`, `blah()`) reported as lies**;
  Python builtins (`locals()`, …) were incomplete; tutorial
  narrative above a doc fence ("Here's an example:") is now
  illustrative. Measured: svelte default 8→6, rich doc-ref 36→17
  (residue: 17 translated READMEs, English-only markers).
- **History notes and ticket-anchored blocks reported as lies.**
  "We used to use `cgi.parse_header()`" (httpx), SES `lockdown()`
  with See #5109 and React-compat `UNSAFE_componentDidMount()` with
  an issue link (preact) are discussion, not live claims. Past-tense
  frames and block-level tickets now silence backticked claims —
  except in `TODO`/`FIXME` blocks, which keep full checking.
- **Alias prefixes hijacked sibling packages.** tsconfig
  `paths: {"preact": [...]}` matched `preact-router` by raw
  string prefix and drifted on a declared dependency. Prefixes now
  follow TypeScript segment semantics (exact or subtree only).
- **Directory imports ignored `package.json` entry points.**
  `import {h} from '../../'` in preact's tests names the package
  root via `main`; a `dist/` main (absent pre-build) is now silent
  instead of a lie, while an in-tree main verifies bindings.
- **Recall harness phantom misses on case-insensitive filesystems.**
  A `README.md` fixture merged into the host's `Readme.md` matched
  no expectation by path. The harness now   tracks on-disk names:
  express and flask recall 100% across all 13 checkers.

### Measured (fresh trees, 2026-09-23)
- httpx default 1→0, preact default 11→4 (smells only), svelte
  default stable at 6 smells, gin 2 smells, rich clean.
- `unclosed-fence` fired once on first contact with cli/cli;
  renderer-verified mechanically true, classified deliberate (bare
  balanced scaffolds displaying template source) — documented, no
  upstream noise. doc-ref and ghost-export stay opt-in: no new real
  rot found, translations bound the narrative rule.

### Added
- `docs/roadmap.md`: the evidence-ordered product plan with
  falsifiers, non-goals, and how to propose work.
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
- **The README's fence count was odd, because one ` ```console ` opened at
  line 216 was never closed.** A closing fence must be at least as long as its
  opener and carry no info string, so the block ran on to the next bare fence
  and the paragraphs at lines 220-228 rendered as code. Verified against
  GitHub's own renderer (`POST /markdown`, `mode=gfm`): 24 code blocks in the
  broken file, 25 after the fix, every heading correctly rendered in both.
  **An earlier draft of this entry claimed 186 of the last 248 lines rendered
  as one code block, and that figure does not reproduce** — it came from this
  tool's own fence toggle rather than from a renderer, which is exactly the
  mistake this project's rules warn about. The toggle's view is still real,
  and it is the quiet half: it inverts for the rest of the file, so
  `stale-cli-ref` stopped checking the whole tail (186 of the last 248 lines
  read as code from the toggle's side) and two corpus plants reported as
  phantom recall misses. Now 50 fences, balanced, with a test pinning the
  parity so the class cannot return unnoticed.
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
  (`stale-symbol-ref`, `number-drift`, `fragile-anchor`), so all 13 checkers
  are now held to a designed true positive instead of only to silence. The
  corpus goes 37 → **45 cases**.
- `unclosed-fence` (opt-in), a checker for the defect that started this: a
  Markdown fence that never closes, or an info-carrying fence the renderer
  swallows because an earlier block is still open. Fences are judged by
  CommonMark instead of counted, because counting is what gets it wrong: a
  closer must be a run of the same character, at least as long as its opener,
  with no info string. Two legitimate shapes stay silent — a *declared*
  nesting scaffold (a longer enclosing fence that carries its own info string,
  which is how svelte's docs show Svelte inside HTML on purpose) and a bare
  fence inside a block (the illustrated closer of a nested example). Measured
  2026-09-22 over **11,564 Markdown files** in eight real repos (svelte,
  vuejs/docs, rust-lang/book, markdown-it, flask, requests, OmniRoute, this
  repo): **0 false positives**, and the only findings were its own corpus
  fixtures plus one real document — OmniRoute's
  `docs/frameworks/OPEN_SSE_ARCHITECTURE.md`, where a stray bare four-backtick
  fence makes GitHub render a 76-line code block holding `## Services (117
  modules)`, `### Common Patterns` and the surrounding prose. Known residue: a
  *bare* fence inside a block is never reported, so an over-long fence used by
  mistake stays silent where the identical shape is a legitimate scaffold —
  `docs/guides/USAGE_QUOTA_GUIDE.md` is the measured example, 33 lines
  swallowed.
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
- **One CommonMark fence walk shared by every fence consumer.**
  `stale-doc-ref` and `stale-cli-ref` tracked fences with a line-by-line
  toggle that flipped on any bare fence-looking line and ignored lines whose
  info string was not a bare tag, so a swallowed boundary inverted their
  view of every line after it and fenced code with a rich info string
  (` ```bash title="x" `) or an indented fence was analyzed as prose.
  `_fence_scan` is now the single walk (`_doc_fence_blocks`,
  `check_stale_cli_ref`, `check_unclosed_fence`, and the graph query all
  run on it), so the checkers and the `unclosed-fence` checker agree by
  construction. `bench/recall.py` imports the walk instead of re-deriving
  the retired toggle, and translates merged-plant expectations (line
  numbers and opener references shift when a fixture lands under host
  content) — a fixture's `opened at line 5` finding lands at line 12 under
  a 5-line host and is judged caught there, not as a phantom title miss.
  Measured A/B of the retired scan vs the walk over 10,857 Markdown files
  (Grounded, OmniRoute, svelte, flask, requests): 1 file with prose wrongly
  skipped (41 lines, an i18n doc with header text glued to its fence
  lines), and 1,032 files / 10,962 lines of fenced code the old scan
  wrongly analyzed as prose. An earlier note citing "238 files / 20,681
  lines" came from a comparison that mixed line populations and is
  retracted.
- **Documentation audit against v0.16.0 reality.** Fresh measured numbers
  everywhere: 279 unit tests (was 238 on the landing page, 269 in the
  README), 45 corpus cases (was 37), 13 checkers — 7 default-on, 6 opt-in —
  with `stale-cli-ref` and `unclosed-fence` now in the README's opt-in
  table (was 4), and the recall harness at 89/89 expectations over 3,927
  files. `pyproject.toml` keywords now describe what the tool actually is
  (documentation rot, AI agents, MCP, LSP), classifiers updated to Beta
  with Python 3.14 and OS-independent, Documentation and Bug Tracker URLs
  added; the VS Code extension manifest version follows the wheel (0.16.0);
  `docs/agent-skill.md` documents that `agent-skill/` is generated from
  `src/grounded/skill/` by `scripts/sync-skill.py`; `docs/benchmarks.md`
  documents the recall harness and its measured run alongside the corpus.

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
