"""Optional tree-sitter enrichment for JavaScript/TypeScript indexing.

Stdlib-only is the product's contract, so this module is strictly
additive: every function returns None when the third-party packages
(`tree_sitter` plus a grammar) are not installed, and the regex core
never knows the difference. CI runs without these packages, which pins
the canonical results; with them installed, the index gains names the
regexes cannot see (ambient `const enum`, namespaces, abstract
classes, decorated declarations) and export lists get exact.

What it deliberately does NOT do: plain unexported `const x = 5`
bindings are left to the regex core. Adding every lexical name would
make results depend on which machine has grammars installed; only
declarations and exports — the shapes that decide absence verdicts —
are enriched. Suppression-only direction throughout: extra names can
silence a finding, never invent one.

Install: pip install tree-sitter tree-sitter-javascript
         tree-sitter-typescript   (for .ts/.mts/.cts/.tsx)
"""
from __future__ import annotations


def _load():
    """(Parser, Language, js_lang, ts_lang, tsx_lang) or None."""
    try:
        from tree_sitter import Language, Parser
    except ImportError:
        return None
    try:
        import tree_sitter_javascript as _js
        js_lang = Language(_js.language())
    except ImportError:
        js_lang = None
    try:
        import tree_sitter_typescript as _ts
        ts_lang = Language(_ts.language_typescript())
        tsx_lang = Language(_ts.language_tsx())
    except ImportError:
        ts_lang = tsx_lang = None
    if js_lang is None and ts_lang is None:
        return None
    return Parser, Language, js_lang, ts_lang, tsx_lang


def _grammar_for(suffix: str, loaded) -> object | None:
    _, _, js_lang, ts_lang, tsx_lang = loaded
    if suffix in (".ts", ".mts", ".cts"):
        return ts_lang
    if suffix == ".tsx":
        return tsx_lang if tsx_lang is not None else None
    return js_lang


def _node_name(node) -> str | None:
    named = node.child_by_field_name("name")
    if named is not None and named.type in ("identifier", "type_identifier"):
        try:
            return named.text.decode("utf-8", errors="ignore")
        except Exception:
            return None
    # TS namespaces surface as internal_module with a bare identifier
    # child carrying no field name.
    if node.type in ("internal_module", "module", "namespace"):
        for child in node.children:
            if child.type == "identifier":
                try:
                    return child.text.decode("utf-8", errors="ignore")
                except Exception:
                    return None
    return None


def extract_js_defs(text: str, suffix: str) -> dict | None:
    """{"symbols": set, "exports": set, "has_default": bool} or None.

    None means "unavailable or unusable": caller falls back to regex.
    Malformed code still yields partial results (tree-sitter recovers);
    only well-formed declaration nodes with identifier names are taken.
    """
    loaded = _load()
    if loaded is None:
        return None
    Parser, _Language, _, _, _ = loaded
    grammar = _grammar_for(suffix.lower(), loaded)
    if grammar is None:
        return None
    try:
        parser = Parser(grammar)
        tree = parser.parse(text.encode("utf-8", errors="ignore"))
    except Exception:
        return None
    symbols: set[str] = set()
    exports: set[str] = set()
    has_default = False

    def visit(node, exported: bool, toplevel: bool) -> None:
        nonlocal has_default
        ntype = node.type
        if ntype == "export_statement":
            for child in node.children:
                visit(child, True, toplevel)
            return
        if ntype == "export_clause":
            for child in node.children:
                if child.type == "export_specifier":
                    local = child.child_by_field_name("name")
                    alias = child.child_by_field_name("alias")
                    try:
                        lname = local.text.decode() if local is not None else None
                        aname = alias.text.decode() if alias is not None else None
                    except Exception:
                        continue
                    if aname and aname.isidentifier():
                        exports.add(aname)
                        if lname and lname.isidentifier():
                            symbols.add(lname)
                    elif lname and lname.isidentifier():
                        exports.add(lname)
            return
        if ntype in ("export", "default"):
            if ntype == "default":
                has_default = True
            for child in node.children:
                visit(child, exported, toplevel)
            return
        is_decl = (ntype.endswith("_declaration")
                   or ntype in ("namespace", "module", "internal_module"))
        if is_decl and toplevel:
            nm = _node_name(node)
            if nm and nm.isidentifier():
                symbols.add(nm)
                if exported:
                    exports.add(nm)
        if ntype == "variable_declarator" and exported and toplevel:
            for child in node.children:
                if child.type == "identifier":
                    try:
                        nm = child.text.decode("utf-8", errors="ignore")
                    except Exception:
                        continue
                    if nm.isidentifier():
                        symbols.add(nm)
                        exports.add(nm)
        for child in node.children:
            # Top level flows through the program root and through
            # declaration wrappers (export/lexical); anything else
            # (function bodies, namespaces, classes) is a new scope.
            # The `exported` flag separately tracks export context, so a
            # plain top-level `const x = 5` stays out: only declarations
            # and exported names enrich the index.
            child_top = toplevel and ntype in ("program", "export_statement",
                                               "lexical_declaration")
            visit(child, exported or ntype == "export_statement",
                  child_top)

    try:
        visit(tree.root_node, False, True)
    except Exception:
        return None
    return {"symbols": symbols, "exports": exports, "has_default": has_default}
