# Architecture & Systems Internals

This document provides an exhaustive technical specification of Grounded's internal compiler architecture, memory representations, AST extraction algorithms, and deterministic verification pipeline.

---

## 1. High-Level Compiler Pipeline

Grounded executes as an multi-phase static analysis pipeline designed to maximize cache locality, eliminate redundant disk I/O, and maintain sub-millisecond incremental evaluation:

```
[Filesystem Walk]
       │
       ▼ (Phase 1: Discovery & Filtering)
[Raw File Buffers]
       │
       ▼ (Phase 2: Ingestion & Single-Pass Read)
[Inverted Index Construction (RepoIndex)] ◄─── [.git/grounded/ Cache]
       │
       ▼ (Phase 3: AST & Lexical Extraction)
[Per-File FileFacts Structs]
       │
       ▼ (Phase 4: Pure Functional Checker Evaluation)
[Raw Diagnostic Findings]
       │
       ▼ (Phase 5: Baseline Pruning & Delta Filtering)
[Verified Contradictions]
       │
       ▼ (Phase 6: Deterministic Sort & Formatters)
[Terminal / JSON / SARIF / HTML Output]
```

---

## 2. Phase-by-Phase Technical Specification

### Phase 1: Discovery & Lexical Boundary Filtering

The scanner (`scanner.py`) executes a parallelized recursive walk starting from the target root.

* **Exclusion Invariants:** Directories matching `node_modules`, `.venv`, `.git`, `dist`, and user-defined `ignore_dirs` are pruned at the directory entry level before stat calls occur.
* **Asset Boundary Checks:** Minified assets (`*.min.js`), source maps (`*.map`), and binary blobs are rejected via byte-header inspection and filename heuristics.

### Phase 2: In-Memory Inverted Index (`RepoIndex`)

The `RepoIndex` (`repo_index.py`) is the centralized in-memory symbol graph against which all non-executable assertions are tested. It maintains normalized symbol sets partitioned across multiple dimensions:

```python
class RepoIndex:
    root: Path
    rel_paths: set[str]                          # All indexed canonical file paths
    symbols_by_name: dict[str, set[str]]         # Symbol token -> Set of defining file paths
    file_exports: dict[str, set[str]]            # File path -> Set of exported identifiers
    file_imports: dict[str, set[str]]            # File path -> Set of imported module specifiers
    file_export_stars: dict[str, list[str]]      # Files containing re-export star syntax
    file_export_unknown: set[str]                # Files whose export surface is dynamically unknowable
    file_esm: set[str]                           # Files verified as ECMAScript Modules
    parent_tops: set[str]                        # Top-level packages in the repository
    tsconfig_zones: list[TsConfigZone]           # Mapped tsconfig.json alias domains
```

#### Cache Coherency Architecture

To achieve instantaneous startup times, Grounded maintains a binary-serialized index cache under `.git/grounded/`:
* Each file entry is keyed by its relative path, file size in bytes, and microsecond-precision modification time (`mtime`).
* If `(size, mtime)` matches the disk state, the parsed symbol facts are restored directly from cache.
* On incremental edits, only the modified file is evicted and re-indexed via `_index_one()` and `forget_file()`.

### Phase 3: Polyglot Parsing & Fact Extraction

Parsing is decoupled from rule evaluation. Each source file is parsed into a frozen `FileFacts` record (`models.py`) containing immutable extractions:

* **Python:** Parsed via the standard library `ast` module combined with `tokenize`. If a Python file contains syntax errors (such as during mid-typing editor states), Grounded gracefully degrades to lexical comment extraction rather than aborting the scan.
* **JavaScript / TypeScript:** Evaluated through a hybrid approach:
  * When `tree-sitter` is available in the runtime environment (`tree_sitter_js.py`), Grounded executes native AST queries to extract nested type declarations, ambient modules, and scoped bindings.
  * In fallback pure-stdlib mode, an optimized lexical scanner parses imports, exports, JSDoc docstrings, and inline comments without spawning Node.js subprocesses.
* **Go & C:** Evaluated via targeted lexical scanners identifying package declarations, type definitions, function headers, exported uppercase identifiers (Go), and `#include` preprocessor directives (C).

### Phase 4: Reference Extraction (The Heuristic Lexer)

Extracting claims from natural language comments requires separating deliberate code references from conversational English prose. The reference extractor enforces strict grammatical and lexical boundaries:

1. **Backtick Boundaries:** Any identifier enclosed in backticks (e.g. `` `calculate_tax()` `` or `` `src/utils.py` ``) is extracted as an explicit claim.
2. **Call-Verb Signatures:** Identifiers immediately preceding parentheses (e.g. `initialize_session()`) are extracted if preceded by reference verbs such as `call`, `invoke`, `run`, `use`, or `see`.
3. **Common Verb Immunity:** Common English verbs that happen to match programming words (e.g. `will`, `can`, `for`, `do`, `while`) are filtered against an authoritative reserved vocabulary unless formatted with explicit backticks or parentheses.

### Phase 5: Pure Functional Checker Evaluation

Checkers in Grounded are pure mathematical functions:
$$\text{checker}: (\text{FileFacts}, \text{RepoIndex}) \to \text{list}[\text{Finding}]$$

* **Purity Invariant:** Checkers perform zero filesystem I/O, make zero network requests, read no environment variables, and invoke no subprocesses.
* **Isolation Invariant:** A failure or exception inside a single checker is captured and isolated, preventing corruption of the remaining diagnostic pipeline.

---

## 3. The Delta Engine (`--changed`)

The `--changed` verification engine implements differential graph slicing to evaluate Git working tree modifications in under 2 seconds on repositories with tens of thousands of files:

```
[Git Diff (HEAD vs Base)]
          │
          ▼
[Extract Modified Files & Changed Line Spans]
          │
          ▼
[Identify Mutated Symbol Names]
          │
          ▼
[Slice Symbol Graph: Find All Importers and Comment Claimants]
          │
          ▼
[Execute Targeted Verification on Sliced Subgraph Only]
```

### Fallback to Broad Semantic Rules

If a Git diff modifies configuration manifests that affect global repository resolution—such as `pyproject.toml`, `package.json`, `.gitignore`, or `tsconfig.json`—the delta engine automatically falls back to a broader evaluation rule, informing the operator via `stderr` to maintain absolute precision.

---

## 4. Concurrency & Determinism Contract

Grounded utilizes a hybrid concurrency model:

* **Serial Execution:** Trees with fewer than 512 files execute serially in a single process to avoid thread synchronization overhead.
* **Parallel Worker Pool:** Repositories exceeding 512 files are partitioned across a `concurrent.futures` worker pool scaled to `os.cpu_count()`.
* **Deterministic Serialization:** Regardless of whether execution occurs serially, across 4 cores, or across 64 cores, the output is sorted by `(canonical_path, line_number, checker_id, claim)`. Output streams are byte-for-byte identical across runs.
