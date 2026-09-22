#!/bin/sh
# Grounded 1-Line Installer for macOS and Linux
# Usage: curl -fsSL https://raw.githubusercontent.com/gonisulaimann/Grounded/main/install.sh | sh
set -e

REPO="gonisulaimann/Grounded"
BIN_NAME="grounded"

info() {
    printf "\033[1;34m==>\033[0m \033[1m%s\033[0m\n" "$1"
}

success() {
    printf "\033[1;32m==>\033[0m \033[1m%s\033[0m\n" "$1"
}

warn() {
    printf "\033[1;33mWarning:\033[0m %s\n" "$1"
}

error() {
    printf "\033[1;31mError:\033[0m %s\n" "$1" >&2
    exit 1
}

# 1. Check if Homebrew is available (macOS / Linuxbrew preferred path)
if [ "$(uname -s)" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
    info "Installing Grounded via Homebrew tap..."
    brew install gonisulaimann/tap/grounded && {
        success "Grounded installed successfully via Homebrew!"
        exit 0
    }
fi

# 2. Check if modern Python tooling is available (uv / pipx / pip)
if command -v uv >/dev/null 2>&1; then
    info "Installing Grounded via uv..."
    uv tool install grounded-lint && {
        success "Grounded installed successfully via uv!"
        exit 0
    }
fi

if command -v pipx >/dev/null 2>&1; then
    info "Installing Grounded via pipx..."
    pipx install grounded-lint && {
        success "Grounded installed successfully via pipx!"
        exit 0
    }
fi

if command -v python3 >/dev/null 2>&1 && python3 -m pip --version >/dev/null 2>&1; then
    info "Installing Grounded via pip..."
    python3 -m pip install --user grounded-lint && {
        success "Grounded installed successfully via pip!"
        exit 0
    }
fi

# 3. Zero-Python Fallback: Download standalone precompiled binary from GitHub Releases
info "Python not found or package install skipped. Fetching standalone binary from GitHub..."

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"

case "$ARCH" in
    x86_64|amd64) ARCH="amd64" ;;
    arm64|aarch64) ARCH="arm64" ;;
    *) error "Unsupported CPU architecture: $ARCH" ;;
esac

case "$OS" in
    darwin) OS_NAME="darwin" ;;
    linux) OS_NAME="linux" ;;
    *) error "Unsupported Operating System: $OS" ;;
esac

TARGET_NAME="grounded-${OS_NAME}-${ARCH}"
URL="https://github.com/${REPO}/releases/latest/download/${TARGET_NAME}"

INSTALL_DIR="${HOME}/.local/bin"
mkdir -p "$INSTALL_DIR"
DEST="${INSTALL_DIR}/${BIN_NAME}"

# A 404 here is usually a missing asset, not a network fault: this path runs
# only after Homebrew and pip/uvx were both skipped, and the release publishes
# a fixed platform set. Naming the platform stops "check your network
# connection" from being the only clue — Intel Macs got exactly that for three
# releases while their asset was simply absent (2026-09-22).
download_failed() {
    # Guidance first: error() exits, so anything after it is dead code.
    printf '  Grounded publishes standalone binaries for linux/amd64, darwin/arm64 and darwin/amd64.\n' >&2
    printf '  This machine is %s/%s.\n' "$OS_NAME" "$ARCH" >&2
    printf '  Install Python 3.10 or later and re-run this script to use the pip/uvx path.\n' >&2
    error "no standalone binary at ${URL}"
}

info "Downloading ${TARGET_NAME} to ${DEST}..."
if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$URL" -o "$DEST" || download_failed
elif command -v wget >/dev/null 2>&1; then
    wget -qO "$DEST" "$URL" || download_failed
else
    error "Neither curl nor wget is installed."
fi

chmod +x "$DEST"

success "Grounded standalone binary installed to ${DEST}!"

# Check PATH
case ":$PATH:" in
    *":$INSTALL_DIR:"*) ;;
    *)
        warn "$INSTALL_DIR is not in your PATH."
        warn "Add this to your shell profile (~/.zshrc or ~/.bashrc):"
        printf "\n    export PATH=\"%s:\$PATH\"\n\n" "$INSTALL_DIR"
        ;;
esac

info "Verification: running grounded --version..."
"$DEST" --version || true

printf "\n\033[1;32mGrounded is ready to use!\033[0m\n"
printf "Run \033[1mgrounded scan .\033[0m in any repository to catch stale references.\n"
