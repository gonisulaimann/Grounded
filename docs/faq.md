# Frequently Asked Questions (FAQ)

This document addresses architectural, operational, and security inquiries regarding Grounded.

---

### 1. Architectural & Engineering Questions

#### How does Grounded differ fundamentally from traditional linters like ESLint, Ruff, or Pylint?
Traditional linters and compilers operate strictly over executable tokens within a single file's Abstract Syntax Tree. They deliberately treat comments, docstrings, Markdown examples, test mock strings, and build manifests as opaque, unparsed character sequences. 

Grounded operates over the **entire repository's global symbol graph**, parsing non-executable surfaces and mathematically cross-referencing their claims against the concrete symbol table. While ESLint verifies syntax correctness within a file, Grounded verifies that non-executable assertions made across the repository do not contradict reality.

#### Why does Grounded not use an LLM or neural network for contradiction detection?
Grounded is deliberately designed as a **deterministic, mechanical compiler**:
1. **Sub-Millisecond Speed:** Grounded rechecks modified files in **0.6 milliseconds** in-process and scans entire multi-thousand-file repositories in ~2 seconds. LLM calls require 5 to 45 seconds of network latency.
2. **Zero Hallucination:** A verification tool that hallucinates creates negative value. Grounded operates solely on concrete AST facts.
3. **Deterministic Reproducibility:** The same repository tree and configuration will produce the exact same byte-for-byte findings on any machine, at any time.
4. **Zero Cost and Total Privacy:** Grounded costs $0 in API tokens and executes completely offline.

#### How does Grounded achieve 0.6ms recheck latency in editors and watch mode?
Grounded maintains a binary-serialized index in `.git/grounded/` and an in-memory `RepoIndex` during persistent processes (LSP, MCP, and `grounded watch`). When a file modification occurs, Grounded evicts only the modified file's symbol bindings, re-parses the buffer in memory, and re-evaluates rules against the existing warm symbol table.

#### Why did Grounded remain silent on a comment that is clearly outdated?
Grounded enforces a strict **Mechanical Precision Contract**. It stays silent on references when:
1. **Bare Conversational Prose:** An identifier is mentioned in plain English prose without backticks or a reference verb (e.g. "We will handle authentication later"). Checking bare prose introduces unacceptable false positive rates.
2. **Dynamic Runtime Metaprogramming:** When a module uses dynamic reflection (`globals().update()`, `importlib.import_module()`, or `setattr()`), Grounded marks the export surface as unknowable and stays silent rather than guessing.
3. **External Dependencies:** References to third-party libraries, standard library modules, or operating system system calls are excluded from local repo-contradiction checkers.

---

### 2. Operational & Workflow Questions

#### Will running Grounded slow down my pre-commit hooks or CI/CD pipelines?
No. Using the `--changed` flag, Grounded calculates differential slices based on Git diffs. On a repository with over 3,500 files, evaluating a branch diff against `origin/main` takes between **1.2 and 1.9 seconds** on standard commodity hardware.

#### How do Baseline Fingerprints avoid line-number churn on legacy repositories?
When you generate a baseline via `grounded baseline`, Grounded computes a SHA-256 fingerprint over:
$$\text{Fingerprint} = \text{hash}(\text{Checker ID} \parallel \text{Canonical Path} \parallel \text{Exact Claim Text})$$

Line numbers are deliberately excluded from the hash. If an unrelated commit adds 50 lines of code at the top of a file, existing baselined findings in that file do not churn or invalidate the baseline.

#### How does `grounded fix` prevent accidental code corruption?
`grounded fix` enforces strict safety invariants:
* It only applies rewrites when exactly **one unambiguous candidate** with identical semantics exists in the repository.
* It will never rewrite docstrings or code comments if multiple similar symbol names are discovered.
* You can always preview planned modifications with `grounded fix --dry-run`.

---

### 3. Security, Privacy, and Environment Questions

#### Does Grounded transmit source code, telemetry, or repository data over the network?
**No.** Default scans are 100% offline. Grounded contains zero analytics, zero usage telemetry, and zero network calls during standard operations. All MCP and LSP communication is handled strictly via local operating system standard input/output (`stdio`).

The only checker that interacts with the network is the opt-in `slop-package` checker, which queries the public PyPI/npm registries over HTTPS to detect unregistered hallucinated packages. It is disabled by default.

#### Does Grounded support Windows natively?
Yes. Grounded provides official 64-bit Windows executables (`grounded-windows-amd64.exe`) and an automated 1-line PowerShell installer (`install.ps1`). All internal path handling utilizes `pathlib.Path` to guarantee platform-agnostic file resolution across Windows, macOS, and Linux.

#### Can Grounded be deployed in air-gapped or high-security networks?
Yes. Because Grounded requires zero external runtime dependencies and can be distributed as a single standalone executable, binary artifacts can be transferred into air-gapped environments via standard secure transfer protocols.

---

### 4. Integration Questions

#### Does Grounded replace docstring linters like Darglint or pydoclint?
No. Grounded operates in tandem with specialized docstring contract linters:
* **Darglint / pydoclint:** Validates that documented `@param`, `@return`, and `@raises` clauses match the concrete function signature.
* **Grounded:** Validates that symbol names, file paths, and cross-module calls mentioned *inside* the description prose actually exist in the repository.

#### How does Grounded integrate into Claude Code, Cursor, and Aider?
Running `grounded init-agent` automatically configures:
1. **Claude Code:** Installs a `PostToolUse` command hook in `.claude/settings.json` that invokes `grounded hook claude-code`. If an edit introduces a contradiction, Grounded exits non-zero and prints the exact claim and evidence on `stderr`, triggering Claude's self-correction loop.
2. **Cursor:** Generates `.cursor/rules/grounded.mdc` to guide Cursor's background agent.
3. **Aider:** Configures `--lint-cmd` inside `.aider.conf.yml` to run Grounded after each multi-file edit.
