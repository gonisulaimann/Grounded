# Rules

| ID | Default severity | What it reports |
|---|---|---|
| `stale-symbol-ref` | lie (error) | A comment names a call that resolves nowhere: not defined in the repo, not imported in the file, not used in the file, not a builtin or keyword. Prints rename suggestions when a close match exists. |
| `stale-import` | lie (error) | A resolvable import whose module is missing, or whose name is not defined, re-exported, or a submodule there. Python `from`/`import`, JS/TS relative imports with tsconfig aliases resolved. Guarded, stdlib, and external imports never report. |
| `stale-file-ref` | lie (error) | A comment claims a path inside the repo tree that does not exist. References to other projects, frameworks, template namespaces, and placeholder paths are ignored. |
| `number-drift` | drift (warning) | A comment states a magic number (timeout, port, limit, threshold) that disagrees with adjacent code. |
| `fragile-anchor` | smell (note) | `line 42` anchors, `see above` / `see below` without a symbol, or untracked markers (`HACK`, `XXX`, `FIXME`, `workaround`) with no ticket or expiry condition. |
| `stale-doc-ref` | lie (error), **experimental, opt-in only** | A fenced code example (explicit `python`/`js`/`ts`/`go`/`c` tag) calls a symbol bound nowhere in the example and defined nowhere in the repo. |
| `stale-contract-ref` | lie/drift, **experimental, opt-in only** | A deprecation notice naming a nonexistent replacement, a lock-holder claim (`must hold X`) naming nothing, or a comment stating an env default the code contradicts. |
| `ghost-export` | smell (note), **experimental, opt-in only** | A public symbol with no importers anywhere, no use in its own file, and no deliberate API marking (`__all__`, exports, `__init__`). |
| `stale-entrypoint` | lie (error) | A `pyproject.toml` `[project.scripts]` target or `package.json` `bin`/`main` path pointing at nothing in the repo. Graduated 2026-09-22. |
| `stale-mock-ref` | lie (error) | A `@patch`/`patch.object` string naming a symbol absent from the in-repo module. Graduated 2026-09-22. |
| `phantom-package` | drift (warning), **experimental, opt-in only** | An absolute import declared in no manifest (`pyproject.toml`, `requirements*.txt`, `package.json`). |
| `stale-cli-ref` | lie (error), **experimental, opt-in only** | A documented `grounded` invocation with an unknown subcommand or flag (verified against the live parser). |
## Experimental checkers

Opt-in checkers are registered but excluded from every default set: run
them with `--enable <id>` (or `enable = [...]`). A checker graduates
to default-on by measured precision, not by age. Silence is the point:
a clean scan means the repo earned it (smoke detectors don't invent
fires), so a new trigger class stays opt-in until its false-positive
rate is measured near zero.

Silence alone is not evidence, though — a smoke detector with a dead
battery also never reports a fire, and a checker that *raises* returns
no findings either. "Silent on N repos" therefore only counts as
precision evidence when the scan can show the checker actually ran,
which is what a checker-error count of `0` means (see
[Exit codes](#severities-and-exit-codes)). Each graduation below is
recorded with that count.

`stale-doc-ref`: only fenced blocks with a supported language tag are
read. Bare fences, `console`/`bash` transcripts, data formats, comment
lines inside examples, decorator roots (framework surface), and any
block containing `...` or placeholder names (`foo`, `my_*`, `<key>`)
are skipped. In JavaScript blocks, platform and Node roots (`Promise`,
`document`, `fs`, `this`), DOM event constructors (`CustomEvent`,
`Event`), JS keywords used as calls (`catch (e)`), continuation chains
(`.then`/`.catch` lines), template-literal contents, ESM/arrow/function
bindings, method-shorthand definitions, the documented package's own
name, manifest-declared externals (unioned up the tree, kebab/camel
agnostic), and self-dir requires (`require('..')`) all stay silent;
bindings accumulate across blocks in file order (tutorial narrative).
Known residue: reader-supplied narrative helpers (`handleError`,
`getToken`) with no definition anywhere — statically indistinguishable
from real staleness. Measured on axios docs: 580 → 40 findings (×5
i18n duplication ≈ 8 unique families, all narrative residue, zero true
positives found).

`stale-contract-ref`: only narrow frames report — deprecation sentences
with a replacement name, `must hold`/`guarded by`-style lock claims on
lock-like names (`_lock`, `mutex`, …), and same-file comments stating a
default for an env var read with a different default in code. Known
limitation: an external successor (`use requests instead`) reads as a
missing symbol; ticket-link the comment to silence it. ALL-CAPS names
in a bare "use X instead" frame are treated as SQL/platform builtins,
not deprecation targets (explicit `DEPRECATED:` notices are still
checked). Bare prose never reports.

`ghost-export`: methods, dunders, `__init__` modules, `__all__` members,
JS exports / `module.exports`, Go-exported (capitalized) names, and
`main`/`init` are never candidates. Aliased imports (`import x as y`)
and module-attribute use (`from pkg import mod` + `mod.name()`) count
as importers — but only with the module import present, so same-named
locals don't qualify. Framework-discovered entry points are exempt:
`test_*` names in test files (pytest, go test). Known limitation:
barrel re-exports (`export * from`), aliased-module attribute use
(`import pkg as p` + `p.mod.name()`), template tags loaded by string
(Django `{% load %}`), and browser-global scripts (loaded by `<script>`
tags, never imported) are not traced. C is excluded (no static info).

`stale-entrypoint`: only `pyproject.toml` scripts and `package.json`
`bin`/`main` are read. Malformed files stay silent. Build-output dirs
(`dist/`, `build/`, …) stay silent — absent pre-publish is normal, not
a lie. External (`bare-package`) targets stay silent. Graduated
2026-09-22 after silent runs on 5 real repos plus fixtures.

`stale-mock-ref`: decorator, call, and `with` forms of
`patch`/`mocker.patch`/`mock.patch` plus `patch.object` (bare names
resolve through imports with alias resolution; string targets verify
progressively; method/meta/instance attributes stay silent by design).
`create=True` opts out; external module paths stay silent. Graduated
2026-09-22 after a django stress run (134 apparent lies classified:
cross-module chains, aliases, proxies, builtins — all fixed or
documented as gaps) plus CPython clean.

`phantom-package`: union of every manifest flavor (project deps, all
optional/PEP 735/Poetry groups, build-system requires,
`requirements*.txt` with includes, all `package.json` dep flavors),
nearest manifests walking up for monorepos, plus a curated
import→distribution map (`yaml`→`pyyaml`, `PIL`→`pillow`, …). Imports
under `try/except`, `TYPE_CHECKING`, or version/platform conditionals
are compat shims that may legitimately fail and never report.
Manifests are found by walking up to the nearest project dir, so
subscans work; with no manifest anywhere the checker stays silent. stdlib,
in-repo modules, `@types/`-covered host modules, and Node builtins
stay silent. Known limits: root manifests only for requirements files;
an `@types/X` declaration hides a missing runtime `X` (deliberate,
favors silence); this is hygiene drift, never supply-chain verdict.

`stale-cli-ref`: fenced console blocks, `$` lines, and backticked spans
starting with `grounded` get full checking (unknown subcommands
included); prose mentions are checked only when the next word is
already a known subcommand or flag ("the grounded skill teaches" never
reports). Synopsis meta-syntax, `cmd:`-style program output, and
positionals never report. The spec is introspected from argparse, so
checker and CLI cannot drift apart.

Measurement lives in [`corpus/`](https://github.com/gonisulaimann/Grounded/tree/main/corpus):
planted-staleness fixtures with exact expected findings, run in CI with
zero tolerance (a missing finding and an extra finding both fail). Current
numbers (2026-09-21):

* `stale-doc-ref`: 60 files, 9 checkable blocks, **0 findings, 0 false
  positives** — every silence individually justified. Recall beyond
  fixtures unmeasured.
* `stale-contract-ref`: violation fixtures fire; a valid-claims corpus
  (matching env default, existing replacement, present lock) is silent.
  This repo contains no trigger instances, so the measurement is thin —
  the bar for default-on is a real-world repo with deprecation traffic.
* `ghost-export`: 4 findings — 3 true positives on deliberately-stale
  demo fixtures plus **1 real dead helper** (`path_to_uri` in `lsp.py`,
  single reference repo-wide), **0 false positives** after the aliased-
  import fix. Default scans are byte-identical (Markdown is collected
  only when `stale-doc-ref` runs).
* New checkers ride the same track: 40 corpus cases hold every checker
  at 1.00 precision (`corpus/run.py`, CI-enforced — all 12 checkers
  have a firing fixture), and `stale-entrypoint`, `stale-mock-ref`, and
  `phantom-package` are silent on this repo's real code (the only
  finding is a planted corpus fixture).
* Isolation precision is not repo recall, and the two need separate
  evidence: the corpus plants rot in the smallest tree that shows the
  behavior, while `bench/recall.py` replays each firing case inside a
  copy of a real repository, where definitions, manifests and
  generated directories are the context that can silence it. Measured
  2026-09-22 over Grounded, flask, requests and svelte (3,922 files):
  **77 planted expectations, 0 misses, 0 checker errors**. 3 cases
  were not plantable — a fixture may not overwrite a host's own
  `pyproject.toml`, which would change what the host *is* — and are
  excluded from the number rather than counted as failures.

## How a rule decides

Imported names, standard library names, parameters, locals, attributes,
docstring field lists (`:param:`, `@param`), and illustrative examples
("For example …") never produce findings. Alias-prefixed JS/TS imports
(`@/`, `~/`) resolve through the nearest `tsconfig.json` (comments and
`extends` supported) or manual `path_aliases`; unresolvable alias targets
report as drift, mappings into `node_modules` stay silent.

## Severities and exit codes

* **`lie` (Error)**: provably false. Exits with code `1` when any finding
  meets `--fail-on` (default `lie`).
* **`drift` (Warning)**: mechanically stale by adjacent evidence.
* **`smell` (Note)**: fragile pattern likely to rot over time.

Exit code `2` means a usage or environment error (bad path, unreadable
baseline or config, unresolvable git base). A typo can never mask drift
with a green build.

Exit code `3` means the scan is **incomplete**: an enabled checker
raised on at least one file. A crashed checker returns no findings,
which is indistinguishable from a checker that found nothing, so the
summary refuses to say `clean` on its behalf. The failures are named on
stderr, grouped by cause (`checker error: <id> raised <Exception>: … at
<path>`, with a `(+N more)` count for repeats), so one broken checker
over a 10k-file tree is one line, not 10k. The stdout payload stays
byte-identical (`json` is still a bare list), and `baseline` refuses to
write a file from an incomplete scan — a blind spot is never persisted
into every later gate.

Two explicit ways to proceed when a checker is genuinely broken:
`--disable <id>` records which one you are accepting as broken, and
`fail_on = "never"` keeps the run report-only (exit `0`, errors still
printed). Neither one hides the error.

## Suppressions

Suppress a single accepted finding where it sits (reviewable, local):

```python
# Calls `legacy_parse()` for old dumps.  # grounded-disable: stale-symbol-ref
```

```js
// Calls `legacyParse()` for old dumps.  // grounded-disable: stale-symbol-ref
```

```go
// Calls `legacyParse()` for old dumps.  // grounded-disable: stale-symbol-ref
```

Unknown checker ids in a marker warn on stderr (`unknown checker id`)
without changing the exit code: a typo never silently disarms a gate.

## Non-goals

Docstring contracts (parameter lists, return sections, raised exceptions)
are covered by [darglint](https://github.com/terrencepreilly/darglint)
and [pydoclint](https://github.com/jsh9/pydoclint) for Python and
[eslint-plugin-jsdoc](https://github.com/gajus/eslint-plugin-jsdoc) for
JavaScript/TypeScript. Commented-out code is covered by
[Ruff ERA001](https://docs.astral.sh/ruff/rules/commented-out-code/).
`grounded explain <id>` points at the right tool for each removed check.

## Limitations

* Unformatted, unverbed name mentions are skipped. This trades recall for
  precision.
* Names imported from anywhere are treated as known elsewhere, including
  cross-module renames.
* Framework namespaces (template paths, URL names) are out of scope.
* JavaScript/TypeScript, Go, and C analysis is syntactic (imports plus
  identifiers), not a full type graph.
* External references stay silent only when recognized (stdlib and POSIX
  names, imports, same-file identifiers).
* Rename suggestions use string similarity only; `grounded fix` applies a
  symbol rename only with exactly one similar, same-directory candidate.
* Files that fail to parse (version-skewed grammar, truncated buffers)
  are marked opaque: no checker claims a symbol is absent from them, and
  top-level bindings are recovered heuristically. The scan summary
  reports the unparsed count; a nonzero count means some absence verdicts
  were withheld, never that findings were invented.
* Negated claims ("there is no call to X") and illustrative paths
  ("e.g. ...") assert absence or give examples: flagging them would
  contradict true statements, so they stay silent.
* Go/C same-package calls need no import: cross-file use within one
  directory suppresses ghost findings. Mutually exclusive `//go:build`
  variants are never flagged. Cross-directory C use and framework
  name-dispatch (template tags, browser globals, signal receivers)
  remain out of scope.
* In doc examples, toolchain calls (`fmt.Printf`, `Promise.reject`),
  JS control keywords used as calls (`catch (e)`), and `this`-rooted
  calls stay silent. Names bound inside the example (definitions,
  imports, destructured fixture parameters such as `async ({ page }) =>`)
  and blocks carrying doc-tooling directives (`// @noErrors`,
  `/// file:`, `---cut---`) are treated as illustrative. Documentation
  highlight markers (`+++`/`---`) are stripped before identifiers are
  extracted, so an annotated example parses like the code it shows.
* **A partial scan never claims absence for what it did not index.** A
  relative import that resolves *above* the scan root (a monorepo's
  sibling package when scanning `src/lib`, say) stays silent, exactly
  like a target under a scan-ignored directory. Sub-tree and single-file
  scans are first-class agent workflows and must not manufacture lies
  about files outside their snapshot. Practical consequence: scanning a
  subdirectory can only ever report fewer findings than scanning its
  enclosing root, never more.
* `grounded fix` rewrites stale file paths only on unambiguous
  same-basename matches in comments (never docstrings, never ties).
