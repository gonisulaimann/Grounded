# Registry Grid pilot

The moonshot's first step: README-vs-code truth for published packages.
`bench/registry.py` downloads sdists, extracts, and runs the doc-example
check of each README against the shipped code.

## Pilot round (2026-09-27, 8 packages)

| Package | README blocks | Call lines | Unknown |
| --- | ---: | ---: | ---: |
| requests | 1 | ~2 | 0 |
| click | 1 | ~7 | 0 |
| rich | 15 | ~43 | 0 |
| attrs | 2 | ~16 | 0 |
| httpx | 1 | ~1 | 0 |
| pyyaml | 0 | 0 | 0 (no python fences) |
| packaging | 0 | 0 | 0 (README.rst, no fences) |
| idna | 2 | ~5 | 0 |

~74 call lines examined, 0 unknown. Reproduce:
`python3 bench/registry.py requests click rich attrs httpx pyyaml packaging idna`.

## Reading (honest, not flattering)

Mature-package READMEs are clean: they show own-API calls, which
resolve (self-package roots, stdlib, placeholders all silent by
design). Zero unknowns here is evidence the checker does not cry wolf
on the world's most-read docs — precision signal, not a trophy.

It is NOT evidence the grid finds rot: these READMEs are tiny surfaces
(1–2 fences each; rich's 15 blocks all resolved). The real examples
live in `docs/` directories, which the pilot deliberately does not
crawl, and in freshly released versions mid-drift. Method limits are
documented in the harness docstring: sdist/wheel only, README only,
Python fences only, and every unknown is a *candidate* requiring human
classification — the harness records, it never accuses.

## Next steps toward the grid

1. Crawl `docs/` trees (bounded depth, same checker).
2. Version-pair runs: N vs N-1 of the same package, diffing unknowns
   (drift appears at release boundaries, not in steady state).
3. Maintainer-sized output: one finding = file:line + evidence + fix,
   ready to paste as an upstream issue.
4. Nightly schedule + truth badges (only after 1–3 prove signal).
