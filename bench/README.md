# Repo-scale benchmark harness

`run.py` measures cold-CLI wall time (median of N fresh processes),
throughput, peak RSS, and findings per repo. Stdlib only.

```console
python3 bench/run.py /path/to/repo [...] [--reps 3] [--enable a,b]
```

Prints one JSON document. Methodology notes:

* Each timed rep is a fresh process: interpreter startup is included,
  because that is the real `scan` cost. One untimed warm run first.
* Peak RSS comes from `resource.ru_maxrss` over waited-for children and
  is a session maximum, so run **one repo per invocation** when RSS
  attribution matters.
* Findings come from a separate `--format json` run in the same process.
* Not a CI gate: shared runners are too noisy for timing. The numbers
  in `docs/benchmarks.md` were produced on quiet hardware with machine
  and date recorded; reproduce them by cloning the same repos
  (`--depth 1` at the recorded date is close enough) and re-running.

Repo choice is deliberate, not flattering: large Python (django,
CPython), large Go (grpc-go), mid TypeScript (axios), small JS/Python
anchors (express, flask). `vuejs/core` was attempted twice and failed
to clone on the author's network; pull requests adding repos (with
numbers) are welcome, provided findings are classified, not just
counted.

## Recall harness

`recall.py` answers the other half of the question. `corpus/run.py` measures
precision **in isolation**: it plants rot in the smallest tree that shows the
behavior, and exact-set-equality proves a checker fires and stays quiet where
it should. It cannot measure whether the checker still fires with a real
repository around it — a definition two directories away, a manifest that
declares the package, a build directory that looks generated. That context can
only ever *silence* a finding, so isolation truth and repo truth are different
claims and need different evidence.

```console
python3 bench/recall.py /path/to/repo [...] [--json out.json] [--case ID]
```

Each firing corpus case is planted into a **copy** of the repo at the same
relative paths it has in its case directory, one case at a time, and the
expected finding must still appear:

```
repo                     files  caught  missed   n/p  recall
requests                    51      19       0     1    100%

per checker (caught / missed / not-planted, all repos):
  stale-symbol-ref         4 / 0   / 0
  ...
```

Three outcomes, never two. **caught**, **missed**, and **not planted** when the
host already has a file at that path (a fixture may not overwrite the host's
own `pyproject.toml` — that would change what the host *is*); `not planted` is
excluded from recall instead of counting as a failure. Prose is the exception:
a doc fixture whose file already exists is merged into the host's own file,
because every repository has a `README.md` and the rot is just as real at the
end of the host's prose. Structured formats (TOML, JSON) are never merged —
appending to them only corrupts them.

A finding is only counted as a catch if it is a **delta** against a baseline
scan of the pristine tree, so a pre-existing finding is never credited to the
plant. Exit `0` only when every planted expectation was caught and no checker
raised (recall computed with a crashed checker is not a measurement — see
exit code 3); `--report-only` always exits `0`.

### The planting must not decide the outcome

Both of these were measured while building the harness, and both first
presented as recall gaps the checkers had not caused:

* **Root-relative planting.** Nested one directory deeper, three cases stopped
  firing: `src-layout` needs the `src/` layout detection, `mock-stale` needs
  `@patch("app.services...")` to resolve from the module root, and
  `entrypoint-stale` needs a top-level `pyproject.toml`. The case still fired
  in isolation; the *plant* had changed what was under test.
* **A known fence state.** The doc checkers are fence-state machines, so a host
  file that ends inside an unclosed fence inverts the state of every appended
  line. This repository's own `README.md` had 49 fences with one never closed,
  and the two `stale-cli-ref` cases reported as misses: the rot had fired in
  isolation, and the host's dangling block had swallowed the planted
  invocation. A merge therefore closes a dangling fence first, and every such
  host is listed in the report — an unbalanced host is a real defect, and
  hiding it would only make the measurement quietly easier.

When a number is reported, say which repo and which date it was measured on;
recall moves with the corpus, so an undated number is not evidence.
