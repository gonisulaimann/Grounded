# Grounded: Reference Integrity Engine

Grounded is a deterministic, offline static analysis system designed to enforce structural reference integrity across software repositories and automated agent workflows. It verifies that documentation, comments, mock definitions, configuration manifests, and cross-module imports mechanically align with the underlying Abstract Syntax Tree (AST) and symbol table of the codebase.

The system requires zero external dependencies, performs no network communication during default verification, and operates with sub-millisecond per-file recheck latency.

---

## 1. Executive Summary and Theoretical Foundation

Software repositories deteriorate over time through a process known as reference rot. While traditional static analysis suites (such as compilers, typecheckers, and syntax linters) operate strictly over executable tokens, they systematically treat natural language docstrings, code comments, test mock strings, and build manifests as opaque, unparsed character sequences. 

Concurrently, modern automated code generation systems—such as Large Language Model (LLM) agents, autonomous refactoring bots, and probabilistic autocomplete assistants—synthesize code modifications at machine speed. These systems frequently perform semantic renames, signature migrations, or module extractions within an isolated file, leaving associated comments, architectural docstrings, unit test mock paths, and API references throughout the rest of the repository in an inconsistent, hallucinatory state.

```
+-------------------------------------------------------------------------------+
|                             Repository Landscape                              |
+---------------------------------------+---------------------------------------+
|            Executable AST             |        Non-Executable Surfaces        |
|  (Typecheckers, Compilers, Linters)   |      (Grounded Reference Firewall)    |
+---------------------------------------+---------------------------------------+
|  • Function definitions & signatures  |  • Natural language docstrings        |
|  • Concrete call expressions          |  • Explanatory inline comments        |
|  • Variable bindings & assignments    |  • String-based mock patches (@patch) |
|  • Import/Export syntax graphs        |  • Build manifests (scripts, bin)     |
|  • Type annotations & interfaces      |  • Markdown tutorials & READMEs       |
+---------------------------------------+---------------------------------------+
                                    |
                 Grounded Deterministic Verification Core
                                    |
    Cross-checks non-executable claims against the concrete symbol graph
```

Grounded formalizes a verification domain termed **Reference Integrity**: the mathematical guarantee that every explicit assertion made within non-executable program text regarding a symbol, file path, numeric constant, or external dependency is verifiable against the repository's concrete state.

---

## 2. The Verification Contract: Claims, Evidence, and Remedies

Grounded models every scan finding as a tuple containing four components:
$$\mathcal{F} = \langle \text{Location}, \text{Claim}, \text{Evidence}, \text{Fix} \rangle$$

1. **Location:** The canonical repository path, start line, and end line where the assertion originates.
2. **Claim:** The specific token, signature, numeric value, or filesystem path asserted in the document or comment.
3. **Evidence:** The structural or lexical proof extracted from the index establishing why the assertion is false or decoupled.
4. **Fix:** An unambiguous, deterministic transformation that reconciles the claim with current ground truth.

```console
$ grounded scan ./src
LIE src/services/auth.py:14 [stale-symbol-ref] Comment references `verify_session_token` which is not defined here
    claim: `verify_session_token()`
    evidence: `verify_session_token` is not defined, imported, or used in this file,
              and no definition was found in 842 indexed source files.
    fix: Update the comment to the current name, or remove the reference. Did you mean: `verify_auth_token()`?

grounded: 1 finding(s) in 842 file(s), 1 lie(s), 0 drift(s), 0 smell(s).
```

### Deterministic Three-State Evaluation

Grounded strictly avoids probabilistic heuristics, fuzzy guessing, or subjective style complaints. Every evaluated reference evaluates to exactly one of three states:

* **Contradiction (`LIE`, Exit Code 1):** The asserted claim directly contradicts verified repository state. The symbol does not exist in the symbol table, the target file path does not exist on disk, a mock targets an absent attribute, or a manifest script entrypoint fails to resolve.
* **Decoupling (`DRIFT`, Warning):** The assertion reflects an observable drift from adjacent AST reality, but may signify author intent rather than an unmitigated error (for example, a magic numeric timeout documented in a comment that diverges from the adjacent integer constant).
* **Silence (No Finding):** When Grounded encounters dynamic runtime metaprogramming, third-party symbols, or build-time generated outputs that cannot be proven mechanically, it remains strictly silent. In institutional engineering environments, false positives destroy developer trust; silence is a design invariant, not a defect.

---

## 3. Threat Model and Agentic Defense

Automated coding agents (such as Claude Code, Cursor, Aider, and Devin) interact with codebases iteratively. Their context windows are populated by reading comments, documentation, and interface specifications.

### The Feedback Degradation Loop

When a repository contains obsolete references, an AI agent incorporates those stale references into its prompt context. Consequently, the agent generates implementation proposals relying on non-existent APIs or deleted submodules:

```
[Repository Rot] ---> [Agent Ingests Stale Comments] ---> [Hallucinated Patch]
       ^                                                         |
       |                                                         v
[Diff Committed] <--- [Human Approves Surface Code] <--- [Fails at Runtime]
```

### The In-Process Verification Loop

Grounded breaks this failure chain at edit time by integrating into the agent loop via `PostToolUse` command hooks, stdio Language Server Protocol (LSP 3.17), and the Model Context Protocol (MCP):

```
[Agent Emits Edit] ---> [Grounded Hook (0.6ms)] ---> [Deterministic Exit 1]
                                                             |
                                                             v
[Clean Commit]    <--- [Agent Self-Corrects]   <--- [Diagnostic Returned]
```

By providing immediate, deterministic, and localized error payloads, Grounded forces the agent to resolve contradictions prior to test execution or pull request submission.

---

## 4. Key Architectural Pillars

* **Zero External Dependencies:** Built entirely with the standard libraries of its supported host runtimes. Grounded requires no virtual environments, no third-party package trees, and no ongoing supply chain maintenance.
* **Sub-Millisecond Incremental Latency:** Features a warm, in-process symbol table capable of re-verifying a modified buffer in approximately **0.6 milliseconds**. Whole-tree scans across repositories exceeding 3,000 files complete in under **2.0 seconds**.
* **Polyglot Symbol Synthesis:** Native parsing modules for Python (AST), JavaScript/TypeScript (AST and Tree-Sitter lexical extraction), Go (lexical structural index), and C (header and declaration mapping).
* **Deterministic Output:** Identical input source trees and configurations yield byte-for-byte identical JSON, SARIF, and terminal outputs across Linux, macOS, and Windows. Parallel worker pools preserve absolute ordering.

---

## 5. Documentation Navigation

This documentation suite provides authoritative reference specifications for developers, devops architects, and agent framework implementers:

* [Quickstart](quickstart.md): Immediate workflows for local developers, changed-line gating, and continuous watch loops.
* [Installation](installation.md): Single-file binaries, package managers (`npm`, `pip`, `brew`), and containerized distribution.
* [Rules & Checkers](rules.md): In-depth catalog of all default and opt-in mechanical checkers.
* [Configuration](configuration.md): Formal specification of `grounded.toml`, suppression directives, and path alias mapping.
* [CLI Reference](cli-reference.md): Complete argument definitions, exit code protocols, and machine-readable output schemas.
* [Agent & Editor Integration](agents.md): Configuration guidelines for Claude Code, Cursor, Aider, Neovim, and LSP clients.
* [Architecture & Internals](internals.md): Compiler pipeline, AST indexing passes, graph algorithms, and formal performance benchmarks.
* [Frequently Asked Questions](faq.md): Technical deep-dive on design constraints, precision thresholds, and comparison with traditional linters.
