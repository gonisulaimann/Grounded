# Grounded — landing page

Static, dependency-free landing page for Grounded.

**Constraints (deliberate, matching the product):** no JavaScript, no
external fonts, no CDN, no analytics. Verified: loading the page issues
**zero external network requests**, so it renders identically offline and
opened from disk. `style.css` and the PNGs in `assets/` are the only
resources.

## Local preview

```console
python3 -m http.server 8731 --directory site --bind 127.0.0.1
# open http://127.0.0.1:8731/
```

## Deploying to GitHub Pages

The docs under `docs/` are MkDocs (Read the Docs). This folder is separate
so the two do not fight over `index`.

**Option A — Actions (recommended).** Add a workflow that uploads `site/`
as the Pages artifact:

```yaml
name: site
on:
  push:
    branches: [main]
    paths: ["site/**"]
  workflow_dispatch:
permissions:
  contents: read
  pages: write
  id-token: write
concurrency:
  group: pages
  cancel-in-progress: true
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deploy.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with: { path: site }
      - id: deploy
        uses: actions/deploy-pages@v4
```

Repository → **Settings → Pages → Source: GitHub Actions** must be set once.

**Option B — a `gh-pages` branch**, no Actions needed:

```console
git subtree push --prefix site origin gh-pages
```

Then set Pages to deploy from the `gh-pages` branch root. `.nojekyll` is
included so nothing is filtered by Jekyll.

## Assets

Web-sized derivatives of the project logos live in `assets/`. The source
artwork is `Ground Icon.png`, `Grounded Logo Icon with Background.png`,
`Grounded Logo White.png` and `Grounded Fire Icon.png`.

> **Open question for the maintainer:** `Grounded Logo Black.png` and
> `Grounded Logo Green.png` are a separate **"Lint"** wordmark with the
> flame as the dot of the `i`, and `Grounded Logo White.png` sets the name
> as `GrounDED` with a node-hexagon mark. This page uses the **node-hexagon
> icon plus "Grounded" set in type**, with the flame as a small accent,
> because that is the name the README, the package (`grounded-lint`) and
> the docs site use. Say the word and the wordmark can replace the set
> type, or the page can be re-headed as Lint.
