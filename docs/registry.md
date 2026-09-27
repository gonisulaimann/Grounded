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

## Docs-crawl round (2026-09-27, click + attrs, 36 pages)

Extending the pilot to bounded `docs/` trees (20 files max, depth 5):

| Package | Pages | Unknown | Classification |
| --- | ---: | ---: | --- |
| click | 21 | 4 | narrative residue: tutorial-invented DB helpers (`open_database()`, `db.save()`) in a "For example" block beyond the 1-line framing window |
| attrs | 15 | 3 | narrative residue: user-supplied `WebClient` example class |

Fixed by this round (were firing, now silent with positive controls):
comprehension loop variables (`x.rstrip()`), trailing-comment prose
(`split into (...)` in `#` comments), the `cls()` classmethod
convention. Remaining 7 are one class: invented tutorial helpers
with no example-frame marker in reach. The 1-line framing window is
deliberate (wider windows launder real staleness); translations and
unmarked narrative stay residue by design.

## Next steps toward the grid

1. ~~Version-pair runs~~ — piloted 2026-09-27: click 8.4.2 → 8.5.0
   shows identical unknown sets (the 4 narrative-residue calls, stable
   across the release). Negative result, honestly recorded: stable
   scaffolding, not drift. Real rot would move between versions; the
   method is ready for a pair where it does.
2. Maintainer-sized output: one finding = file:line + evidence + fix,
   ready to paste as an upstream issue.
3. Nightly schedule + truth badges (only after 1–2 prove signal).
