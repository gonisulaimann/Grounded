# Editor Integration & Language Server Protocol (LSP 3.17)

Grounded implements the standard Language Server Protocol (LSP 3.17) over standard input/output (`stdio`), providing instant in-editor diagnostic publishing, hover information, and mechanical quickfix transformations across Python, TypeScript, JavaScript, Go, and C.

---

## 1. LSP Server Capabilities

When invoked via `grounded lsp`, the language server advertises the following capabilities:

| LSP Capability | Protocol Method | Operational Behavior |
| :--- | :--- | :--- |
| **Incremental Text Sync** | `textDocument/didChange` | Full document synchronization over in-memory buffers during active typing. |
| **Diagnostics** | `textDocument/publishDiagnostics` | Real-time diagnostics mapped to editor severity bands: `LIE` (Error), `DRIFT` (Warning), `SMELL` (Info). |
| **Code Actions & Quickfix**| `textDocument/codeAction` | Unambiguous symbol renames and path moves presented as 1-click editor quickfixes. |
| **Re-index on Open/Close** | `textDocument/didOpen`, `didClose` | Modifies warm in-process symbol table; closing discards uncommitted buffer state. |

---

## 2. Visual Studio Code & Cursor Extension

An official client extension is maintained under `editors/vscode` and published on [Open VSX](https://open-vsx.org/extension/gonisulaimann/grounded).

### Installation

* **Cursor / Windsurf / VSCodium:** Open the Extensions sidebar (`Ctrl+Shift+X` / `Cmd+Shift+X`), search for `Grounded`, and select **Install**.
* **VS Code:** Install from Open VSX or build from source:
  ```bash
  cd editors/vscode
  npm ci && npm run compile && npx @vscode/vsce package
  code --install-extension grounded-*.vsix
  ```

### Binary Resolution Logic

The extension executes the language server using a strict, zero-magic discovery sequence:

1. `grounded.serverPath` setting (explicit executable path).
2. `grounded` available on system `PATH` (installed via Homebrew, npm, standalone binary, or pip).
3. If not found on PATH, offers ephemeral fallback execution via `uvx --from grounded-lint grounded lsp`.

### Extension Configuration Settings

Add the following to your VS Code / Cursor `settings.json`:

```json
{
  "grounded.serverPath": "/usr/local/bin/grounded",
  "grounded.failOn": "lie",
  "grounded.trace.server": "off"
}
```

---

## 3. Neovim (Native LSP)

Neovim 0.8+ natively supports Grounded via its built-in client. Add to your `init.lua`:

```lua
local lspconfig = require('lspconfig')
local configs = require('lspconfig.configs')

if not configs.grounded then
  configs.grounded = {
    default_config = {
      cmd = { 'grounded', 'lsp' },
      filetypes = { 'python', 'javascript', 'typescript', 'typescriptreact', 'go', 'c' },
      root_dir = lspconfig.util.root_pattern('grounded.toml', 'pyproject.toml', 'package.json', '.git'),
      settings = {},
    },
  }
end

lspconfig.grounded.setup({})
```

---

## 4. Helix Editor

Configure Grounded in your Helix user configuration (`~/.config/helix/languages.toml`):

```toml
[language-server.grounded]
command = "grounded"
args = ["lsp"]

[[language]]
name = "python"
language-servers = [ "pyright", "grounded" ]

[[language]]
name = "typescript"
language-servers = [ "typescript-language-server", "grounded" ]

[[language]]
name = "go"
language-servers = [ "gopls", "grounded" ]
```

---

## 5. Emacs (Eglot and LSP-Mode)

### Eglot (Built-in to Emacs 29+)

Add to your `init.el`:

```elisp
(with-eval-after-load 'eglot
  (add-to-list 'eglot-server-programs
               '((python-mode typescript-mode js-mode go-mode c-mode) . ("grounded" "lsp"))))
```

### LSP-Mode

```elisp
(with-eval-after-load 'lsp-mode
  (lsp-register-client
    (make-lsp-client :new-connection (lsp-stdio-connection '("grounded" "lsp"))
                     :major-modes '(python-mode typescript-mode js-mode go-mode c-mode)
                     :server-id 'grounded)))
```

---

## 6. Zed Editor

Add Grounded to your Zed language settings (`~/.config/zed/settings.json`):

```json
{
  "lsp": {
    "grounded": {
      "binary": {
        "path": "grounded",
        "arguments": ["lsp"]
      }
    }
  }
}
```
