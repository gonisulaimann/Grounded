"""Helpers behind the real-repo precision rounds (bench/precision/).

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


class TestPrecisionRound(unittest.TestCase):
    """Helpers behind the 2026-09-24 real-repo precision round
    (bench/precision/): each pins one false-positive family and the
    boundary that keeps real rot firing."""

    def test_fixture_paths(self):
        from grounded.scanner import is_fixture_path
        for rel in ("tests/format/js/a.js", "tests/data/cases/x.py", "pkg/fixtures/a.py",
                    "src/__tests__/fixtures/x.js", "testdata/README.md",
                    "tests/admin/broken_app/models.py", "tests/template_tests/broken_tag.py",
                    "tests/mypy/outputs/x.py"):
            self.assertTrue(is_fixture_path(rel), rel)
        for rel in ("tests/test_app.py", "src/data/loader.py", "tests/test_apps/mod/__init__.py",
                    "src/broken.py", "format/x.js"):
            self.assertFalse(is_fixture_path(rel), rel)

    def test_nested_gitignore(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".gitignore").write_text("/build\n*.log\ngen/\n", encoding="utf-8")
            (root / "website").mkdir()
            (root / "website" / ".gitignore").write_text("static/lib\n!keep.log\n", encoding="utf-8")
            idx = RepoIndex(root, [])
            self.assertTrue(idx.is_gitignored("build/x.js"))
            self.assertTrue(idx.is_gitignored("a/b/debug.log"))
            self.assertTrue(idx.is_gitignored("pkg/gen/client.py"))
            self.assertTrue(idx.is_gitignored("website/static/lib/next/m.mjs"))
            self.assertFalse(idx.is_gitignored("website/keep.log"))
            self.assertFalse(idx.is_gitignored("src/build.py"))
            self.assertFalse(idx.is_gitignored("static/lib/x.js"))

    def test_require_inside_string_is_not_an_import(self):
        from grounded.parsers import _js_import_entries
        got = _js_import_entries(
            "const a = require('./a')\n"
            "const t = { src: 'const r = require(\"./lib/r\")' }\n")
        self.assertEqual([e[0] for e in got], ["./a"])

    def test_docstring_listing_dropped_prose_kept(self):
        from grounded.checkers import _drop_literal_blocks
        doc = ("Names in a distribution.\n\n    Listed as:\n\n        src/a/b.py\n"
               "        src/a/c.py\n\n    Moved to src/pkg/x.py.\n"
               "    Args:\n        path: see src/real.py\n")
        out = _drop_literal_blocks(doc)
        self.assertNotIn("src/a/b.py", out)
        self.assertIn("src/pkg/x.py", out)
        self.assertIn("see src/real.py", out)

    def test_c_include_regex_is_multiline(self):
        from grounded.parsers import _c_imports
        got = _c_imports("/* hdr */\n#include <stdio.h>\n#  include <ares.h>\n#include \"local.h\"\n")
        self.assertEqual(got, {"stdio": "stdio.h", "ares": "ares.h", "local": ""})

    def test_derived_lookups_follow_rebuilds(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            f = root / "a.py"
            f.write_text("def cf_socket_active():\n    pass\n", encoding="utf-8")
            idx = RepoIndex(root, [f])
            self.assertIn("_active", idx.underscore_suffixes())
            idx._index_one("a.py", ".py", "def renamed():\n    pass\n")
            self.assertNotIn("_active", idx.underscore_suffixes())

    def test_dunder_typo_only(self):
        from grounded.checkers import _dunder_typo_of

        class _Idx:
            all_symbols: set = set()
        self.assertTrue(_dunder_typo_of("__get_item__", _Idx()))
        for name in ("__annotations__", "__wrapped__", "__pydantic_fields__", "__tests__"):
            self.assertFalse(_dunder_typo_of(name, _Idx()), name)


class TestStaleApiRef(unittest.TestCase):
    """stale-api-ref: client literals vs the repo's own JSON OpenAPI spec.

    Narrow by construction: no spec means silence, bare strings are
    never requests, templates match segment-wise, and filesystem or
    asset paths stay out."""

    SPEC = ('{"openapi": "3.0.0", "info": {"title": "t", "version": "1"}, '
            '"paths": {"/users/{id}": {"get": {}}, "/health": {"get": {}}}}')

    def _tree(self, root: Path, client: str, spec: str | None = SPEC) -> None:
        if spec is not None:
            (root / "openapi.json").write_text(spec, encoding="utf-8")
        (root / "app.py").write_text(client, encoding="utf-8")

    def _api(self, files: dict[str, str]):
        from grounded.checkers.api import check_stale_api_ref
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spec = files.pop("openapi.json", None)
            self._tree(root, files["app.py"], spec)
            _, facts, index = scan_root(root, Config())
            facts_by_path = {f.path: f for f in facts}
            return check_stale_api_ref(facts_by_path["app.py"], index)

    def test_missing_route_fires(self):
        out = self._api({"openapi.json": self.SPEC,
                         "app.py": 'import requests\nrequests.get("/v2/gone")\n'})
        self.assertEqual(len(out), 1)
        self.assertIn("GET /v2/gone", out[0].title)
        self.assertEqual(out[0].severity, "lie")

    def test_template_and_absolute_url_silent(self):
        out = self._api({"openapi.json": self.SPEC,
                         "app.py": ('import requests\nrequests.get("/users/42")\n'
                                    'requests.get("https://api.x.com/health?x=1")\n')})
        self.assertEqual(out, [])

    def test_no_spec_silent(self):
        out = self._api({"app.py": 'import requests\nrequests.get("/v2/gone")\n'})
        self.assertEqual(out, [])

    def test_non_spec_json_ignored(self):
        out = self._api({"openapi.json": '{"name": "pkg", "paths": {}}',
                         "app.py": 'import requests\nrequests.get("/v2/gone")\n'})
        self.assertEqual(out, [])

    def test_filesystem_and_comment_strings_silent(self):
        out = self._api({"openapi.json": self.SPEC,
                         "app.py": ('import requests\np = "/etc/hosts"\n'
                                    '# see "/old/docs"\nrequests.get("/health")\n')})
        self.assertEqual(out, [])


class TestCrossIndex(unittest.TestCase):
    """Two-root verification: --cross-index unions another tree's specs.

    Shipped (not a sketch): the flag itself is the pairing evidence."""

    SPEC = ('{"openapi": "3.0.0", "info": {"title": "t", "version": "1"}, '
            '"paths": {"/users/{id}": {"get": {}}}}')

    def _roots(self, base: Path) -> tuple[Path, Path]:
        fe = base / "frontend"
        be = base / "backend"
        fe.mkdir()
        (fe / "app.js").write_text(
            'import { x } from "./x";\nfetch("/users/42");\nfetch("/v2/gone");\n',
            encoding="utf-8")
        (fe / "x.js").write_text("export const x = 1;\n", encoding="utf-8")
        be.mkdir()
        (be / "openapi.json").write_text(self.SPEC, encoding="utf-8")
        return fe, be

    def _scan(self, args):
        import contextlib
        import io
        from grounded.cli import main
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(args)
        return rc, buf.getvalue()

    def test_cross_index_fires(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            fe, be = self._roots(Path(td))
            rc, out = self._scan(["scan", str(fe), "--no-color", "--format", "json",
                                  "--enable", "stale-api-ref",
                                  "--cross-index", str(be)])
            self.assertEqual(rc, 1)
            titles = [f["title"] for f in json.loads(out)]
            self.assertTrue(any("/v2/gone" in t for t in titles))
            self.assertFalse(any("/users/42" in t for t in titles))

    def test_without_flag_silent(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            fe, be = self._roots(Path(td))
            rc, out = self._scan(["scan", str(fe), "--no-color", "--format", "json",
                                  "--enable", "stale-api-ref"])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(out), [])

    def test_missing_dir_is_usage_error(self):
        import contextlib
        import io
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            fe, _ = self._roots(Path(td))
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = main(["scan", str(fe), "--cross-index", str(Path(td) / "nope")])
            self.assertEqual(rc, 2)

    def test_flag_without_checker_is_note(self):
        import contextlib
        import io
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            fe, be = self._roots(Path(td))
            err = io.StringIO()
            out = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                rc = main(["scan", str(fe), "--no-color",
                           "--cross-index", str(be)])
            self.assertEqual(rc, 0)
            self.assertIn("only affects stale-api-ref", err.getvalue())


class TestDocExampleBindings(unittest.TestCase):
    """Doc-example names bound by the example itself: comprehension
    targets, trailing-comment prose, and the classmethod convention."""

    def _doc(self, readme, enable="stale-doc-ref"):
        import contextlib
        import io
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text(readme, encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["scan", str(root), "--no-color", "--enable", enable])
            return rc, buf.getvalue()

    def test_comprehension_variable_silent(self):
        rc, _ = self._doc(
            "Title\n\n```python\niterator = (x.rstrip() for x in items)\n"
            "print(iterator)\n```\n")
        self.assertEqual(rc, 0)

    def test_trailing_comment_prose_silent(self):
        rc, _ = self._doc(
            'Title\n\n```python\ndefault_map = {\n'
            '    "point": "3 4",  # split into ("3", "4") for nargs=2\n'
            '}\nprint(default_map)\n```\n')
        self.assertEqual(rc, 0)

    def test_cls_convention_silent(self):
        rc, _ = self._doc(
            "Title\n\n```python\nfrom pkg import Point\n\n"
            "@classmethod\ndef from_row(cls, row):\n"
            "    return cls(row.x, row.y)\n```\n")
        self.assertEqual(rc, 0)

    def test_unbound_call_still_fires(self):
        rc, out = self._doc(
            "Title\n\n```python\nfrom pkg import process\n\n"
            "iterator = (x.rstrip() for x in items)\n"
            "frobnicate(iterator)\n```\n")
        self.assertEqual(rc, 1)
        self.assertIn("frobnicate", out)


if __name__ == "__main__":
    unittest.main()
