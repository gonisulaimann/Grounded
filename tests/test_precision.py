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


if __name__ == "__main__":
    unittest.main()
