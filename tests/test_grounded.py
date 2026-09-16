"""Deterministic test suite for grounded (stdlib unittest, no dependencies).

Scope: import-aware, scope-aware reference checks. Docstring contracts
(params/returns/raises) and commented-out code are out of scope:
darglint/pydoclint, eslint-plugin-jsdoc, and Ruff ERA001 cover them.
Tests pin suppression rules, not just detections.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from grounded.config import Config
from grounded.parsers import parse_file
from grounded.repo_index import RepoIndex
from grounded.reporters import to_html, to_json, to_sarif
from grounded.scanner import scan_root


class TestImportsParsing(unittest.TestCase):
    def test_py_imports(self):
        import ast
        from grounded.parsers import _py_imports
        tree = ast.parse("import os\nimport a.b as c\nfrom x import y\nfrom . import z\n")
        self.assertEqual(_py_imports(tree), {"os": "os", "c": "a", "y": "x", "z": ""})

    def test_js_imports(self):
        from grounded.parsers import _js_imports
        got = _js_imports('import axios from "axios";\nimport { helper } from "./real.js";\nconst fs = require("fs");\n')
        self.assertEqual(got.get("axios"), "axios")
        self.assertEqual(got.get("helper"), "")
        self.assertEqual(got.get("fs"), "fs")


class TestSymbolV2(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def scan(self, files: dict[str, str], **cfg_kwargs):
        for rel, text in files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        config = Config(**cfg_kwargs) if cfg_kwargs else Config()
        findings, facts, index = scan_root(self.root, config)
        return findings

    def syms(self, files):
        return [f for f in self.scan(files) if f.checker == "stale-symbol-ref"]

    def test_backticked_call_missing_is_lie(self):
        out = self.syms({"a.py": "def real():\n    return 1\n",
                         "b.py": "# Calls `ghost_fn()` for help.\nX = 1\n"})
        self.assertTrue(any("ghost_fn" in f.title for f in out))

    def test_imported_root_is_silent(self):
        out = self.syms({"a.py": "from http.cookiejar import CookieJar\n# Wraps CookieJar.clear().\nX = 1\n"})
        self.assertEqual(out, [])

    def test_stdlib_root_is_silent(self):
        out = self.syms({"a.py": "# See Tarfile.extractfile docs.\nX = 1\n",
                         "t.py": "import tarfile\nY = tarfile.open\n"})
        # Tarfile imported in t.py but NOT in a.py; stdlib rule still silences
        self.assertFalse([f for f in out if "Tarfile" in f.title or "extractfile" in f.title])

    def test_same_file_param_local_attr_silent(self):
        out = self.syms({"a.py": "def f(dict_class):\n    # merged using `dict_class`\n    rewindable = True\n    # `rewindable` guards retry\n    self._x = 1\n    # `_x` set above\n    return dict_class\n"})
        self.assertEqual(out, [])

    def test_sphinx_field_lines_scrubbed(self):
        out = self.syms({"a.py": 'def f(headers):\n    """Do.\n\n    :param headers: a mapping.\n    """\n    return headers\n'})
        self.assertEqual(out, [])

    def test_backticked_field_name_silent(self):
        out = self.syms({"a.py": "# `status_code` below 400 is success.\nstatus_code = 200\n"})
        self.assertEqual(out, [])

    def test_dunder_typo_is_lie_with_suggestion(self):
        out = self.syms({"a.py": "def __getitem__(self, k):\n    return k\n",
                         "b.py": "# Both ``__get_item__`` and get use this.\nX = 1\n"})
        self.assertTrue(any("__get_item__" in f.title for f in out))
        hit = [f for f in out if "__get_item__" in f.title][0]
        self.assertIn("__getitem__", hit.fix)

    def test_common_dunder_silent(self):
        out = self.syms({'a.py': '# Run with `__main__` guard.\nif __name__ == "__main__":\n    pass\n'})
        self.assertEqual(out, [])

    def test_bare_call_with_verb_is_lie(self):
        out = self.syms({"a.py": "def real():\n    return 1\n",
                         "b.py": "# Calls fetch_user_data() and formats.\nX = 1\n"})
        self.assertTrue(any("fetch_user_data" in f.title for f in out))

    def test_bare_call_without_verb_silent(self):
        out = self.syms({"a.py": "# _fix_ie_filename() edge cases noted.\nX = 1\n"})
        self.assertEqual(out, [])

    def test_builtin_and_keyword_silent(self):
        out = self.syms({"a.py": "# Uses print() for output.\nX = 1\n",
                         "b.js": "// method without `function` keyword\nconst x = 1;\n"})
        self.assertEqual(out, [])

    def test_defined_symbol_silent(self):
        out = self.syms({"a.py": "def real_thing():\n    return 1\n",
                         "b.py": "# Calls `real_thing()` for help.\nX = 1\n"})
        self.assertEqual(out, [])

    def test_js_relative_import_silent(self):
        out = self.syms({"a.js": 'import { helper } from "./real.js";\n// Uses `helper()`.\nconst x = 1;\n',
                         "real.js": "export function helper(x) { return x; }\n"})
        self.assertEqual(out, [])

    def test_js_same_file_ident_silent(self):
        out = self.syms({"a.js": "// `socketPath` option noted.\nconst opts = { socketPath: '/x' };\n"})
        self.assertEqual(out, [])

    def test_module_level_assignment_known(self):
        out = self.syms({"a.py": "from lazy import lazy\n",
                         "b.py": "gettext_lazy = 1\n",
                         "c.py": "# The input is the result of a gettext_lazy() call.\nX = 1\n"})
        # gettext_lazy assigned at module level in b.py -> repo-known
        self.assertEqual(out, [])

    def test_stdlib_class_form_silent(self):
        out = self.syms({"a.py": "# See `Tarfile.extractfile()` docs.\nX = 1\n"})
        self.assertEqual(out, [])

    def test_screaming_bare_call_silent(self):
        out = self.syms({"a.py": "# Don't use the built-in RANDOM() function here.\nX = 1\n",
                         "b.py": "# The use of VALUES() is not supported.\nY = 2\n"})
        self.assertEqual(out, [])

    def test_negated_bare_call_silent(self):
        out = self.syms({"a.py": "# arrays are cast and byref() calls are not needed.\nX = 1\n"})
        self.assertEqual(out, [])

    def test_rename_candidate_still_fires(self):
        out = self.syms({"a.py": "def test_max_cookie_length():\n    pass\n",
                         "b.py": "# see comment in CookieTests.test_cookie_max_length()\nX = 1\n"})
        self.assertTrue(any("test_cookie_max_length" in f.title for f in out))


class TestFileV2(unittest.TestCase):
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

    def files(self, files):
        return [f for f in self.scan(files) if f.checker == "stale-file-ref"]

    def test_in_scope_missing_is_lie(self):
        out = self.files({"src/keep.py": "X = 1\n",
                          "a.py": "# See src/gone.py for details.\nY = 2\n"})
        self.assertTrue(any("src/gone.py" in f.title for f in out))

    def test_in_scope_existing_silent(self):
        out = self.files({"src/keep.py": "X = 1\n",
                          "a.py": "# See src/keep.py for details.\nY = 2\n"})
        self.assertEqual(out, [])

    def test_out_of_scope_silent(self):
        # dependency modules, template namespaces, external sources:
        # the snapshot cannot decide them, so they must stay quiet.
        out = self.files({"src/a.py": "X = 1\n",
                          "a.py": ("# See MySQLdb/cursors.py.\n"
                                   "# See flatpages/default.html.\n"
                                   "# See Modules/_sqlite/connection.c.\n"
                                   "Y = 2\n")})
        self.assertEqual(out, [])

    def test_placeholder_silent(self):
        out = self.files({"src/a.py": "X = 1\n",
                          "a.py": "# e.g. myapp/css/base.css\nY = 2\n"})
        self.assertEqual(out, [])

    def test_protocol_version_silent(self):
        out = self.files({"src/a.py": "X = 1\n",
                          "a.py": "# HTTP/1.1 requires persistence.\nY = 2\n"})
        self.assertEqual(out, [])

    def test_illustrative_example_silent(self):
        out = self.files({"src/a.py": "X = 1\n",
                          "a.py": "# For example, see src/news/photos.py for layout.\nY = 2\n"})
        self.assertEqual(out, [])


class TestNumberAndAnchor(unittest.TestCase):
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

    def test_number_drift(self):
        out = self.scan({"a.py": "# timeout is 30s\ntimeout = 60\n"})
        self.assertTrue(any(f.checker == "number-drift" for f in out))

    def test_number_agree_silent(self):
        out = self.scan({"a.py": "# timeout is 60s\ntimeout = 60\n"})
        self.assertFalse([f for f in out if f.checker == "number-drift"])

    def test_line_anchor_smell(self):
        out = self.scan({"a.py": "# See line 42 for logic.\nX = 1\n"})
        self.assertTrue(any(f.checker == "fragile-anchor" for f in out))

    def test_ticketed_workaround_silent(self):
        out = self.scan({"a.py": "# HACK(#123): skip until v2\nX = 1\n"})
        self.assertFalse([f for f in out if f.checker == "fragile-anchor"])

    def test_prose_not_commented_code_cascade(self):
        # 3 prose lines must not suppress their own symbol findings
        out = self.scan({"a.py": "def real():\n    return 1\n",
                         "b.py": ("# Calls `ghost_xyz()` when ready.\n"
                                  "# timeout is 30s for dialing.\n"
                                  "# See line 9 for policy.\ntimeout = 60\n")})
        kinds = {(f.checker) for f in out}
        self.assertIn("stale-symbol-ref", kinds)
        self.assertIn("number-drift", kinds)


class TestRemovedCheckers(unittest.TestCase):
    def test_no_removed_ids_emitted(self):
        removed = {"param-mismatch", "raises-mismatch", "return-mismatch", "commented-code"}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text(
                'def f(timeout):\n    """Do.\n\n    Args:\n        host: missing.\n    """\n'
                '    # result = compute(1)\n    # total = result + 2\n    # print(total)\n    return 1\n',
                encoding="utf-8")
            findings, _, _ = scan_root(root, Config())
            self.assertFalse([f for f in findings if f.checker in removed])

    def test_explain_points_to_incumbents(self):
        from grounded.cli import main
        for cid in ["param-mismatch", "raises-mismatch", "return-mismatch", "commented-code"]:
            self.assertEqual(main(["explain", cid]), 0)


class TestScannerV2(unittest.TestCase):
    def test_dts_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.d.ts").write_text(
                "/**\n * @param {string} ghost missing\n */\ndeclare function f(x: string): void;\n// Calls `ghost_fn()`.\n",
                encoding="utf-8")
            findings, facts, _ = scan_root(root, Config())
            self.assertEqual(facts, [])
            self.assertEqual(findings, [])

    def test_syntax_error_file_does_not_crash(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "bad.py").write_text("def broken(:\n  # Calls `ghost_fn()`.\n", encoding="utf-8")
            findings, _, _ = scan_root(root, Config())
            self.assertIsInstance(findings, list)

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(scan_root(Path(td), Config())[0], [])


class TestReporters(unittest.TestCase):
    def test_json_roundtrip(self):
        from grounded.models import Finding
        f = [Finding(path="a.py", line=1, end_line=1, checker="stale-symbol-ref",
                      severity="lie", title="t", claim="c", evidence="e", fix="x", confidence=0.9)]
        data = json.loads(to_json(f))
        self.assertEqual(data[0]["checker"], "stale-symbol-ref")

    def test_sarif_valid_shape(self):
        from grounded.models import Finding
        f = [Finding(path="a.py", line=3, end_line=3, checker="stale-file-ref",
                      severity="lie", title="t")]
        sarif = json.loads(to_sarif(f))
        self.assertEqual(sarif["version"], "2.1.0")
        self.assertEqual(sarif["runs"][0]["results"][0]["ruleId"], "stale-file-ref")

    def test_html_escapes(self):
        from grounded.models import Finding
        f = [Finding(path="a.py", line=1, end_line=1, checker="stale-symbol-ref",
                      severity="lie", title="<b>bold</b>", claim="c", evidence="e", fix="x")]
        out = to_html(f, 1, root=".")
        self.assertIn("&lt;b&gt;bold&lt;/b&gt;", out)


class TestExitCodes(unittest.TestCase):
    def test_fail_on_never(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text("# Calls `ghost_fn_xyz()`.\nX = 1\n", encoding="utf-8")
            from grounded.cli import main
            self.assertEqual(main(["scan", str(root), "--no-color", "--fail-on", "never"]), 0)

    def test_fail_on_lie(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text("# Calls `ghost_fn_xyz()`.\nX = 1\n", encoding="utf-8")
            from grounded.cli import main
            self.assertEqual(main(["scan", str(root), "--no-color", "--fail-on", "lie"]), 1)


class TestBaseline(unittest.TestCase):
    def _write(self, root: Path, files: dict[str, str]) -> None:
        for rel, text in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")

    def test_write_then_suppress(self):
        from grounded.cli import main
        from grounded.delta import load_baseline
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, {"a.py": "# Calls `ghost_fn()`.\nX = 1\n"})
            base = root / ".grounded-baseline.json"
            self.assertEqual(main(["baseline", str(root), "--output", str(base)]), 0)
            self.assertTrue(load_baseline(base))
            # same tree: everything baselined, exit 0
            self.assertEqual(
                main(["scan", str(root), "--no-color", "--baseline", str(base)]), 0)

    def test_new_finding_fails_new_only(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, {"a.py": "# Calls `ghost_fn()`.\nX = 1\n"})
            base = root / "base.json"
            self.assertEqual(main(["baseline", str(root), "--output", str(base)]), 0)
            self._write(root, {"b.py": "# Calls `other_ghost()`.\nY = 2\n"})
            # without baseline: 2 findings; with: only the new one gates
            self.assertEqual(
                main(["scan", str(root), "--no-color", "--baseline", str(base),
                      "--format", "json"]),
                1)

    def test_line_shift_does_not_churn(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, {"a.py": "# Calls `ghost_fn()`.\nX = 1\n"})
            base = root / "base.json"
            self.assertEqual(main(["baseline", str(root), "--output", str(base)]), 0)
            # insert 20 blank lines above: line numbers move, claim identical
            self._write(root, {"a.py": "\n" * 20 + "# Calls `ghost_fn()`.\nX = 1\n"})
            self.assertEqual(
                main(["scan", str(root), "--no-color", "--baseline", str(base)]), 0)

    def test_edited_claim_retriggers(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, {"a.py": "# Calls `ghost_fn()`.\nX = 1\n"})
            base = root / "base.json"
            self.assertEqual(main(["baseline", str(root), "--output", str(base)]), 0)
            self._write(root, {"a.py": "# Calls `ghost_fn_v2()`.\nX = 1\n"})
            self.assertEqual(
                main(["scan", str(root), "--no-color", "--baseline", str(base)]), 1)

    def test_missing_baseline_is_error(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, {"a.py": "X = 1\n"})
            self.assertEqual(
                main(["scan", str(root), "--no-color", "--baseline", str(root / "nope.json")]), 2)

    def test_rewrite_reports_delta_counts(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, {"a.py": "# Calls `ghost_fn()`.\nX = 1\n"})
            base = root / "base.json"
            self.assertEqual(main(["baseline", str(root), "--output", str(base)]), 0)
            (root / "a.py").write_text("X = 1\n", encoding="utf-8")
            self.assertEqual(main(["baseline", str(root), "--output", str(base)]), 0)
            from grounded.delta import load_baseline
            self.assertEqual(load_baseline(base), set())


@unittest.skipUnless(shutil.which("git"), "git not available")
class TestChangedLines(unittest.TestCase):
    def _git(self, root: Path, *args: str) -> None:
        import subprocess
        subprocess.run(["git", *args], cwd=root, check=True,
                       capture_output=True, timeout=60)

    def _repo(self, root: Path, files: dict[str, str]) -> None:
        for rel, text in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        self._git(root, "init", "-q")
        self._git(root, "-c", "user.email=t@t", "-c", "user.name=t",
                  "commit", "-q", "--allow-empty", "-m", "init")
        self._git(root, "add", "-A")
        self._git(root, "-c", "user.email=t@t", "-c", "user.name=t",
                  "commit", "-q", "-m", "base")

    def test_only_new_lines_reported(self):
        import contextlib
        import io
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root, {"a.py": "# Calls `old_ghost()`.\nX = 1\n"})
            # committed finding exists; uncommitted edit adds another + touches X
            (root / "a.py").write_text(
                "# Calls `old_ghost()`.\nX = 2\n# Calls `new_ghost()`.\n", encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["scan", str(root), "--no-color", "--changed", "--format", "json"])
            self.assertEqual(rc, 1)
            changed_only = json.loads(buf.getvalue())
            self.assertEqual(len(changed_only), 1)
            self.assertIn("new_ghost", changed_only[0]["title"])
            buf_all = io.StringIO()
            with contextlib.redirect_stdout(buf_all):
                rc_all = main(["scan", str(root), "--no-color", "--format", "json"])
            self.assertEqual(rc_all, 1)
            self.assertEqual(len(json.loads(buf_all.getvalue())), 2)

    def test_untracked_file_fully_reported(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root, {"a.py": "X = 1\n"})
            (root / "new.py").write_text("# Calls `fresh_ghost()`.\nY = 1\n", encoding="utf-8")
            self.assertEqual(
                main(["scan", str(root), "--no-color", "--changed", "--fail-on", "lie"]), 1)

    def test_outside_git_is_error(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text("# Calls `ghost_fn()`.\nX = 1\n", encoding="utf-8")
            self.assertEqual(main(["scan", str(root), "--no-color", "--changed"]), 2)


class TestSuppressions(unittest.TestCase):
    def scan(self, root: Path, files: dict[str, str]):
        for rel, text in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return scan_root(root, Config())

    def test_trailing_disable_suppresses(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text(
                "# Calls `ghost_fn()`.  # grounded-disable: stale-symbol-ref\nX = 1\n",
                encoding="utf-8")
            self.assertEqual(main(["scan", str(root), "--no-color"]), 0)

    def test_other_checker_not_suppressed(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text(
                "# Calls `ghost_fn()`.  # grounded-disable: fragile-anchor\nX = 1\n",
                encoding="utf-8")
            self.assertEqual(main(["scan", str(root), "--no-color"]), 1)

    def test_all_suppresses(self):
        from grounded.scanner import apply_suppressions
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text(
                "# Calls `ghost_fn()`.  # grounded-disable: all\nX = 1\n", encoding="utf-8")
            findings, facts, _ = scan_root(root, Config())
            kept, n = apply_suppressions(findings, {f.path: f for f in facts})
            self.assertEqual(kept, [])
            self.assertEqual(n, 1)

    def test_js_marker_suppresses(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.js").write_text(
                "// Calls `ghost_fn()`. // grounded-disable: stale-symbol-ref\nconst x = 1;\n",
                encoding="utf-8")
            self.assertEqual(main(["scan", str(root), "--no-color"]), 0)


class TestRepoFiles(unittest.TestCase):
    def test_action_files_parse(self):
        import json
        root = Path(__file__).resolve().parent.parent
        matcher = json.loads((root / ".github" / "grounded-problem-matcher.json").read_text())
        self.assertEqual(len(matcher["problemMatcher"]), 3)
        for entry in matcher["problemMatcher"]:
            self.assertIn("owner", entry)
        action = (root / "action.yml").read_text()
        self.assertIn("grounded-problem-matcher.json", action)
        self.assertIn("composite", action)

    def test_action_no_dot_notation_hyphen_inputs(self):
        # Regression: `${{ inputs.fail-on }}` parses as arithmetic and
        # expands empty. Hyphenated inputs require bracket notation.
        import re
        root = Path(__file__).resolve().parent.parent
        action = (root / "action.yml").read_text()
        bad = re.findall(r"\$\{\{\s*inputs\.[A-Za-z0-9_]+-[A-Za-z0-9_-]*", action)
        self.assertEqual(bad, [])
        hooks = (root / ".pre-commit-hooks.yaml").read_text()
        self.assertIn("grounded scan", hooks)


if __name__ == "__main__":
    unittest.main()
