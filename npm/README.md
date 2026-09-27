# grounded on npm

`npx -y @gonisulaimann/grounded scan` — same binary, same exit codes, no Python needed.

(The bare name `grounded` is squatted on npm (a 0.0.1-alpha
placeholder), so this ships scoped. The installed command is still
plain `grounded`.)

## How it works

This package ships a Node shim (`bin/grounded`) plus a postinstall step
that downloads the standalone binary for your platform from the GitHub
release of the **same version**. Supported: darwin/arm64,
darwin/amd64, linux/amd64, windows/amd64. Anything else prints
directions to `pip install grounded-lint` instead of failing obscurely.

## Version coupling (maintainers)

`npm/package.json` `version` MUST equal the GitHub release tag it
downloads from (`vX.Y.Z` ↔ `X.Y.Z`). Bump the two together on every
release, or installs 404. Checklist:

1. Bump `pyproject.toml`, `src/grounded/__init__.py`,
   `editors/vscode/package.json`, **and** `npm/package.json` together.
2. Tag + GitHub Release (binaries attach automatically).
3. `cd npm && npm publish` (requires `npm login` once per machine).

## Publishing (maintainer, needs npm auth)

```console
cd npm
npm pack --dry-run   # verify file list without network
npm publish          # first run needs: npm login
npx -y grounded@latest --version   # smoke test from a clean machine
```
