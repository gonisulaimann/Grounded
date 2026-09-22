# Installation

Requires Python 3.10 or later. Zero runtime dependencies in every method.

## Standalone binary

No Python or package manager needed:

```console
curl -fsSL https://raw.githubusercontent.com/gonisulaimann/Grounded/main/install.sh | sh
```

`install.sh` picks the asset from `uname -s` / `uname -m`, so these names are a
contract:

| Platform | `uname -m` | Asset |
| --- | --- | --- |
| Linux x86-64 | `x86_64` | `grounded-linux-amd64` |
| Windows x86-64 | — | `grounded-windows-amd64.exe` |
| macOS Apple silicon | `arm64` | `grounded-darwin-arm64` |
| macOS Intel | `x86_64` | `grounded-darwin-amd64` |

Both macOS assets are the **same universal2 (fat) binary**, published under
two names so one download serves either architecture. There is no
arm64-only macOS artifact: a single `macos-latest` runner builds it, so the
release no longer depends on Intel runner images, which GitHub retires
periodically.

Every release is audited independently (`verify-release.yml`): the audit
fails if any of the four assets is missing and verifies the macOS assets
really do carry both `arm64` and `x86_64` slices, so an architecture-specific
binary can never be published under a universal name.

## Homebrew (macOS and Linux)

```console
brew install gonisulaimann/tap/grounded
grounded --version
```

## pip

```console
pip install grounded-lint
grounded --version
```

## uvx (no Python management)

Runs without installing anything persistently:

```console
uvx --from grounded-lint grounded scan .
```

## From source

```console
git clone https://github.com/gonisulaimann/Grounded.git
cd Grounded
pip install -e .
python -m unittest discover -s tests
```

## Verify

```console
grounded scan --help
grounded explain stale-symbol-ref
```

## Pre-commit hook

```yaml
repos:
  - repo: https://github.com/gonisulaimann/Grounded
    rev: v0.16.0
    hooks:
      - id: grounded
```
