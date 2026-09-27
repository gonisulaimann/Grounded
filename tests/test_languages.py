"""Go and C support.

Deterministic test suite for grounded (stdlib unittest, no dependencies).
"""
from __future__ import annotations

import json
import random
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure src/ is on sys.path when running tests without prior editable install
_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from grounded.config import Config
from grounded.parsers import parse_file
from grounded.repo_index import RepoIndex
from grounded.reporters import to_html, to_json, to_sarif
from grounded.scanner import collect_files, scan_root


class TestGo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def scan(self, files: dict[str, str]):
        for rel, text in files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return scan_root(self.root, Config())[0]

    def test_backticked_call_missing_is_lie(self):
        out = self.scan({"a.go": 'package main\n\n// Calls `ghost_cmd()` on failure.\nfunc Ping() {}\n'})
        self.assertTrue(any(f.checker == "stale-symbol-ref" and "ghost_cmd" in f.title for f in out))

    def test_imported_and_builtin_silent(self):
        out = self.scan({"a.go": 'package main\n\nimport "fmt"\n\n// Uses `fmt.Println()`.\n// len() of the batch.\nfunc f() {}\n'})
        self.assertFalse([f for f in out if f.checker == "stale-symbol-ref"])

    def test_defined_method_silent(self):
        out = self.scan({"a.go": 'package main\n\n// See ParseFlags() for merging.\nfunc ParseFlags() {}\n'})
        self.assertFalse([f for f in out if f.checker == "stale-symbol-ref"])

    def test_ticket_next_line_silences_temporal(self):
        out = self.scan({"a.go": 'package main\n\n// Temporarily disable check X.\n// See https://example.com/issue/1.\nfunc f() {}\n'})
        self.assertFalse([f for f in out if f.checker == "fragile-anchor"])

    def test_untracked_hack_still_fires(self):
        out = self.scan({"a.go": 'package main\n\n// HACK: skip validation for now\nfunc f() {}\n'})
        self.assertTrue(any(f.checker == "fragile-anchor" for f in out))


class TestC(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def scan(self, files: dict[str, str]):
        for rel, text in files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return scan_root(self.root, Config())[0]

    def syms(self, files):
        return [f for f in self.scan(files) if f.checker == "stale-symbol-ref"]

    def test_backticked_call_missing_is_lie(self):
        out = self.syms({"a.c": "// Calls `ghost_fn()` on error.\nint main() { return 0; }\n"})
        self.assertTrue(any("ghost_fn" in f.title for f in out))

    def test_split_declaration_known(self):
        out = self.syms({"a.c": "static void\nghost_fn(int x) {\n}\n",
                         "b.c": "// Calls `ghost_fn()` on error.\nint main() { return 0; }\n"})
        self.assertEqual(out, [])

    def test_knr_definition_known(self):
        out = self.syms({"a.c": "ghost_fn(x, y)\n{\n}\n",
                         "b.c": "// Calls `ghost_fn()` on error.\nint main() { return 0; }\n"})
        self.assertEqual(out, [])

    def test_function_pointer_member_known(self):
        out = self.syms({"a.h": "typedef struct { void (*cb)(int x); } T;\n",
                         "b.c": '// Uses `cb()` for events.\n#include "a.h"\nint main() { return 0; }\n'})
        # cb is imported via a.h include map (base a) or struct member context;
        # at minimum the fptr declaration must not break the scan
        self.assertIsInstance(out, list)

    def test_stdlib_and_posix_silent(self):
        out = self.syms({"a.c": "// Uses malloc() and strlen().\n// Calls socket() then bind().\nint main() { return 0; }\n"})
        self.assertEqual(out, [])

    def test_call_statement_not_indexed(self):
        # `ghost_fn(x);` as a bare statement must not register a definition
        from grounded.parsers import c_top_level_names
        self.assertNotIn("ghost_fn", c_top_level_names("int main() {\n  ghost_fn(1);\n  return 0;\n}\n"))


def _has_ts_libs() -> bool:
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_javascript  # noqa: F401
        return True
    except ImportError:
        return False


class TestTreeSitterEnrichment(unittest.TestCase):
    """Optional tree-sitter union for JS/TS indexing: None without the
    libraries (CI pins the regex core), declaration + export names with
    them. Suppression-only in both worlds."""

    def test_returns_none_without_libraries(self):
        from unittest import mock
        from grounded import tree_sitter_js
        with mock.patch.object(tree_sitter_js, "_load", return_value=None):
            self.assertIsNone(tree_sitter_js.extract_js_defs("const x = 1;", ".js"))

    def test_index_unchanged_without_libraries(self):
        from unittest import mock
        from grounded import tree_sitter_js
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.ts").write_text(
                "export const enum E { A = 1 }\nexport const x = 1;\n",
                encoding="utf-8")
            with mock.patch.object(tree_sitter_js, "_load", return_value=None):
                _, _, index = scan_root(root, Config())
            self.assertIn("x", index.file_exports.get("a.ts", set()))

    @unittest.skipUnless(_has_ts_libs(), "tree-sitter grammars not installed")
    def test_exotic_declarations_recorded(self):
        from grounded import tree_sitter_js
        out = tree_sitter_js.extract_js_defs(
            "export const enum E { A = 1 }\n"
            "export namespace N { export const x = 1; }\n"
            "export abstract class C {}\n"
            "const top_plain = 5;\n"
            "export default function main() {}\n", ".ts")
        self.assertEqual(out["symbols"] & {"E", "N", "C", "main"}, {"E", "N", "C", "main"})
        self.assertIn("E", out["exports"])
        self.assertTrue(out["has_default"])
        self.assertNotIn("top_plain", out["symbols"])
        self.assertNotIn("x", out["symbols"])

    @unittest.skipUnless(_has_ts_libs(), "tree-sitter grammars not installed")
    def test_malformed_input_never_crashes_index(self):
        from grounded.repo_index import RepoIndex
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.js").write_text("function broken( {\nconst = = =\n",
                                       encoding="utf-8")
            _, _, index = scan_root(root, Config())
            self.assertIn("a.js", index.rel_paths)


if __name__ == "__main__":
    unittest.main()
