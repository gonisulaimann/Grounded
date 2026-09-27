# Enterprise Installation & Deployment Specification

Grounded is engineered for frictionless deployment across heterogeneous computing environments, supporting zero-dependency standalone binaries, standardized system package managers, and containerized CI/CD runners.

---

## 1. Distribution Matrix

| Platform / Ecosystem | Distribution Channel | Execution Mechanism | Target Architecture |
| :--- | :--- | :--- | :--- |
| **Linux** | Standalone Binary | Native Executable | `x86_64` (AMD64) |
| **macOS** | Universal2 Binary / Homebrew | Native Executable | `arm64` (Apple Silicon) + `x86_64` (Intel) |
| **Windows** | Standalone Binary | Native Executable (`.exe`) | `x86_64` (AMD64) |
| **Node.js / Web** | npm Registry | Native Binary Wrapper | Cross-platform (`npx grounded-lint`) |
| **Python** | PyPI Registry | Wheel / Source Distribution | Python $\ge$ 3.10 |
| **Container** | Docker / OCI Image | Scratch / Distroless Container | Multi-arch OCI |

---

## 2. Universal 1-Line Standalone Installation

For environments without administrative privileges, Python runtimes, or external package managers, Grounded provides universal bootstrap scripts that download the appropriate precompiled, self-contained binary directly from GitHub Releases.

### macOS and Linux (POSIX Shell)

```bash
curl -fsSL https://raw.githubusercontent.com/gonisulaimann/Grounded/main/install.sh | sh
```

The script determines platform and architecture via `uname -s` and `uname -m`, downloads the binary to `${HOME}/.local/bin/grounded`, applies executable permissions (`chmod +x`), and verifies PATH availability.

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/gonisulaimann/Grounded/main/install.ps1 | iex
```

The installer verifies architecture, downloads `grounded-windows-amd64.exe` to `$env:LOCALAPPDATA\grounded\grounded.exe`, and registers the directory in the User `PATH` environment variable.

### Binary Naming Contract and Universal2 Architecture

Official binary artifacts adhere to a strict naming contract:

* `grounded-linux-amd64` (ELF 64-bit LSB executable, statically linked libc compatibility)
* `grounded-windows-amd64.exe` (PE32+ executable for Windows x64)
* `grounded-darwin-arm64` (Mach-O Universal2 binary containing both ARM64 and x86_64 slices)
* `grounded-darwin-amd64` (Identical Mach-O Universal2 binary, mirrored for legacy tooling)

Every release undergoes independent verification (`verify-release.yml`) asserting that macOS artifacts contain dual architecture slices before publishing.

---

## 3. Package Manager Integration

### Node.js and TypeScript (`npm` / `npx`)

Web and TypeScript projects can invoke Grounded directly through the Node ecosystem without managing a Python runtime:

```bash
# Execute ephemerally via npx:
npx grounded-lint scan .

# Install as a project development dependency:
npm install --save-dev grounded-lint
```

Add a convenience script to `package.json`:

```json
{
  "scripts": {
    "lint:references": "grounded scan src --changed origin/main"
  }
}
```

### Homebrew (macOS and Linuxbrew)

Grounded maintains an official tap for automated installation and upgrades:

```bash
# Tap the repository and install:
brew install gonisulaimann/tap/grounded

# Verify installation:
grounded --version
```

### Python Ecosystem (`pip` and `uv`)

For Python-centric environments (Python 3.10 through 3.14):

```bash
# Standard pip installation:
pip install --upgrade grounded-lint

# Ephemeral execution with uv (sub-second cached startup):
uvx --from grounded-lint grounded scan .

# Persistent tool installation via uv:
uv tool install grounded-lint
```

---

## 4. Containerized & Air-Gapped Environments

### Minimal Docker Pattern

To incorporate Grounded into Dockerized build chains without bloating final image layers, utilize multi-stage builds:

```dockerfile
# Stage 1: Acquisition
FROM alpine:latest AS grounded-builder
RUN apk add --no-cache curl
RUN curl -fsSL https://raw.githubusercontent.com/gonisulaimann/Grounded/main/install.sh | sh

# Stage 2: Target Production Environment
FROM debian:bookworm-slim
COPY --from=grounded-builder /root/.local/bin/grounded /usr/local/bin/grounded

WORKDIR /workspace
ENTRYPOINT ["grounded"]
CMD ["scan", "."]
```

### Air-Gapped Installation (Offline Security Enclaves)

In high-security or defense-grade air-gapped environments where outbound network access is prohibited:

1. Download the standalone executable and corresponding SHA-256 checksum from the GitHub Releases page on an internet-connected staging machine.
2. Verify the checksum:
   ```bash
   sha256sum -c grounded-linux-amd64.sha256
   ```
3. Transfer the single binary into the air-gapped network via approved media.
4. Relocate the binary to `/usr/local/bin/grounded`. Grounded contains zero dynamic network dependencies and functions with 100% operational fidelity offline.

---

## 5. Pre-Commit Integration

To prevent broken references from entering Git history, wire Grounded into `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/gonisulaimann/Grounded
    rev: v0.17.0
    hooks:
      - id: grounded
        name: Grounded Reference Integrity
        stages: [commit]
      - id: grounded-fences
        name: Grounded Markdown Fence Integrity
        stages: [commit]
```

Install the pre-commit hook into your local `.git` directory:

```bash
pre-commit install
```
