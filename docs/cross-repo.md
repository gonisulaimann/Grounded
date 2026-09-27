# Cross-repo contract integrity (moonshot design)

The problem `stale-api-ref` answers inside one repo generalizes:
service A's client calls the endpoint service B removed last Tuesday,
and neither repo's tests can see it — each side is consistent alone.
This document records the design; the shipped checker is the
same-repo kernel.

## Shipped (v0.17.0): same-repo kernel

`stale-api-ref` (opt-in): HTTP-call string literals verified against
the repo's own JSON OpenAPI/Swagger documents. Proves the machinery
(route templates, call anchoring, silence rules) on one tree.

## Design: two-root verification

```
grounded scan ./frontend --cross-index ./backend
```

1. Build both indexes (reuse: `scan_root` twice, no new parsing).
2. Pair by manifest: `frontend/package.json` names the API it consumes
   (private registry URL, `openapi:` pointer, or explicit
   `--consumes ./backend/openapi.json`); no pairing evidence means no
   verdicts — the phantom-package rule applied to roots.
3. Run the client side of one index against the spec side of the other,
   both directions where both sides exist.
4. Findings carry both paths (`frontend/app.js:12` calls what
   `backend/openapi.json` no longer defines), so either maintainer can
   act.

## Non-goals (explicit)

- No live traffic, no staging diffing: snapshots only, like everything
  else. A contract observed at runtime is a different product.
- No version resolution across registries (which published version of
  B does A consume?): out of scope until manifest pairing proves the
  core. Monorepos (both sides in one tree) already work today — the
  checker cannot tell the difference, which is the point.
- YAML specs: stdlib only, no YAML parser. JSON first; YAML if a
  dependency-free reader earns its place the way `toml_compat` did.

## Falsifier

One documented real-world catch across two roots (a client calling a
removed route, confirmed by the owning team) graduates the two-root
mode from design to feature. Until then it stays here, not in `--help`.
