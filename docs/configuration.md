# Configuration Specification

Grounded provides a declarative, layered configuration model supporting dedicated TOML configuration files, `pyproject.toml` integration, inline source code suppressions, and runtime command-line overrides.

---

## 1. Configuration Resolution Hierarchy

When Grounded initializes a scan, it resolves configuration parameters according to a strict precedence order (higher tiers override lower tiers):

```
+-------------------------------------------------------------------+
| 1. Command-Line Arguments (--fail-on, --enable, --disable)        | (Highest Precedence)
+-------------------------------------------------------------------+
| 2. Explicit Configuration Target (--config /path/to/custom.toml)  |
+-------------------------------------------------------------------+
| 3. Auto-Discovered Project Configuration File                     |
|    a. ./grounded.toml                                             |
|    b. ./.grounded.toml                                            |
|    c. ./pyproject.toml (under [tool.grounded])                    |
+-------------------------------------------------------------------+
| 4. System Default Invariants                                      | (Lowest Precedence)
+-------------------------------------------------------------------+
```

---

## 2. Configuration Schema (`grounded.toml`)

Below is the complete reference schema for `grounded.toml`:

```toml
# ==============================================================================
# Grounded Institutional Configuration Specification
# ==============================================================================

# Minimum severity threshold that triggers a non-zero exit status (exit 1).
# Options: "lie", "drift", "smell", "never" (default: "lie").
fail_on = "lie"

# Checkers to activate explicitly (promotes opt-in checkers to active).
enable = [
    "stale-symbol-ref",
    "stale-import",
    "stale-file-ref",
    "stale-mock-ref",
    "stale-entrypoint",
    "unclosed-fence",
    "slop-package",      # Opt-in: Public registry package hallucination firewall
    "stale-api-ref",      # Opt-in: OpenAPI/Swagger client validation
]

# Checkers to deactivate from the active evaluation pool.
disable = [
    "fragile-anchor",    # Disables line-number anchor warnings
]

# Additional directories to exclude from lexical and AST indexing.
# These entries append to the built-in system exclusion list.
ignore_dirs = [
    "docs/generated",
    "vendor/third_party",
    "benchmark/fixtures",
    "tmp",
]

# Specific file patterns or explicit relative file paths to ignore.
ignore_files = [
    "src/generated_client.ts",
    "proto/service_pb2.py",
]

# Explicit fallback path aliases for JavaScript and TypeScript repositories.
# Note: Grounded automatically reads and parses nearest tsconfig.json files;
# this table serves as an explicit override for complex monorepo workspaces.
[path_aliases]
"@/*" = "src/*"
"@omniroute/*" = "packages/*"
"~/*" = "app/*"
```

---

## 3. `pyproject.toml` Integration

Python-first repositories can maintain configuration directly within `pyproject.toml` under the `[tool.grounded]` namespace:

```toml
[tool.grounded]
fail_on = "lie"
enable = ["slop-package", "stale-doc-ref"]
disable = ["fragile-anchor"]
ignore_dirs = ["legacy_tests", "fixtures"]
ignore_files = ["src/generated_pb.py"]
```

---

## 4. Built-in Ignore Invariants

Grounded embeds an authoritative set of default ignore targets designed to eliminate noise and prevent indexing of non-repository source trees:

* **Dependency Trees:** `node_modules`, `.venv`, `venv`, `env`, `vendor`, `.pnpm-store`
* **Compilation Artifacts:** `__pycache__`, `dist`, `build`, `.next`, `.nuxt`, `target`, `out`, `*.egg-info`
* **Version Control Metadata:** `.git`, `.hg`, `.svn`
* **Lockfiles & Binary Blobs:** `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `Cargo.lock`, `poetry.lock`
* **Minified Assets:** `*.min.js`, `*.min.css`, `*.bundle.js`, `*.map`
* **Declaration Files:** `*.d.ts` (handled via ambient typing rules, excluded from source reference checks)

Custom entries specified in `ignore_dirs` and `ignore_files` append to this foundation; they never replace it.

---

## 5. Inline Code Suppressions

When a legacy reference, illustrative pseudo-call, or intentional historical comment must remain in the codebase, developers can apply inline suppression annotations.

### Single-Line Suppression (`# grounded-disable`)

Append `# grounded-disable: <checker>` to the offending line:

```python
# Calls legacy_parse() for backward compatibility with 2021 database dumps. # grounded-disable: stale-symbol-ref
def process_blob(data):
    ...
```

For JavaScript, TypeScript, Go, and C files, standard comment tokens are supported:

```typescript
// See line 1477 for upstream synchronization notes. // grounded-disable: fragile-anchor
```

### Multi-Checker Suppressions

To suppress multiple checkers simultaneously on a single line, supply a comma-separated list:

```python
# See line 42 for calls to obsolete_helper()  # grounded-disable: fragile-anchor, stale-symbol-ref
```

### File-Level Suppressions

To exempt an entire file from a specific checker (e.g. legacy test suites or historical migration scripts), place the directive at the top of the file:

```python
# grounded-disable-file: stale-symbol-ref, fragile-anchor
"""Historical migration script executed for database cutover in 2024."""
```

---

## 6. Path Alias Resolution Protocol

For TypeScript and JavaScript monorepos, Grounded resolves imports through a deterministic multi-stage resolution pipeline:

1. **Nearest `tsconfig.json` Discovery:** The resolver walks up the directory hierarchy starting from the importing file until it identifies the nearest configuration file.
2. **`extends` Chaining:** Grounded recursively resolves and flattens extended tsconfig bases.
3. **`baseUrl` and `paths` Mapping:** In-repo target paths are translated to canonical repository coordinates.
4. **Safety Valve:** If an alias targets a file that exists on disk but resides outside the scanned AST snapshot (e.g. ambient `.d.ts` definitions or generated outputs), Grounded treats the import as external, staying strictly silent rather than emitting a false contradiction.
