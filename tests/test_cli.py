"""CLI surfaces: reporters, exit codes, baselines, --changed, suppressions, fix, impact.

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


class TestReporters(unittest.TestCase):
    def test_json_roundtrip(self):
        from grounded.models import Finding
        f = [Finding(path="a.py", line=1, end_line=1, checker="stale-symbol-ref",
                      severity="lie", title="t", claim="c", evidence="e", fix="x", confidence=0.9)]
        data = json.loads(to_json(f))
        self.assertEqual(data[0]["checker"], "stale-symbol-ref")

    def test_terminal_unparsed_note(self):
        from grounded.reporters import format_terminal
        plain = format_terminal([], 2, root=".")
        self.assertNotIn("unparsed", plain)
        noted = format_terminal([], 2, root=".", n_unparsed=1)
        self.assertIn("1 file(s) unparsed", noted)

    def test_markdown_table_is_row_safe(self):
        from grounded.models import Finding
        from grounded.reporters import to_markdown
        f = [Finding(path="a.py", line=4, end_line=4, checker="stale-symbol-ref",
                     severity="lie", title="a | b\nc")]
        out = to_markdown(f, 3)
        row = [l for l in out.splitlines() if l.startswith("| lie")][0]
        self.assertIn("a \\| b c", row)
        self.assertIn("1 finding(s) in 3 file(s): 1 lie.", out)
        self.assertIn("No findings in 2 file(s).", to_markdown([], 2))
        self.assertIn("Incomplete scan", to_markdown(f, 3, n_checker_errors=1))

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

    def test_rename_fallout_on_untouched_lines_reported(self):
        import contextlib
        import io
        import json
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root, {
                "pkg/__init__.py": "",
                "pkg/core.py": "def get_user(uid):\n    return uid\n",
                "pkg/views.py": ('"""Views."""\nfrom .core import get_user\n\n\n'
                                 "def show(uid):\n    return get_user(uid)\n"),
                "other.py": "# Calls `other_ghost()`.\nY = 1\n",
            })
            (root / "pkg" / "core.py").write_text(
                "def get_account(uid):\n    return uid\n", encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["scan", str(root), "--no-color", "--changed", "--format", "json"])
            self.assertEqual(rc, 1)
            out = json.loads(buf.getvalue())
            self.assertEqual(len(out), 1)
            self.assertIn("get_user", out[0]["title"])
            self.assertEqual(out[0]["checker"], "stale-import")


class TestMultiPathScan(unittest.TestCase):
    """`grounded scan FILE [FILE ...]` — pre-commit batches the changed
    filenames it passes to a `pass_filenames` hook, so the fence hook
    (`grounded-fences` in .pre-commit-hooks.yaml) needs multi-path scan.

    Semantics follow the single-file rule: each file scopes REPORTING to
    itself while the index is still built from the whole tree, so
    cross-file references keep resolving.
    """

    def test_two_files_one_finding(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "bad.md").write_text("# Guide\n\n```console\ngrounded scan .\n",
                                         encoding="utf-8")
            (root / "ok.md").write_text("# Ok\n\n```python\nx = 1\n```\n",
                                        encoding="utf-8")
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["scan", str(root / "bad.md"), str(root / "ok.md"),
                           "--no-color", "--fail-on", "lie",
                           "--enable", "unclosed-fence"])
            self.assertEqual(rc, 1)
            self.assertIn("bad.md", buf.getvalue())
            self.assertNotIn("ok.md:", buf.getvalue())

    def test_two_files_both_clean(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.md").write_text("```python\nx = 1\n```\n", encoding="utf-8")
            (root / "b.md").write_text("```python\ny = 2\n```\n", encoding="utf-8")
            self.assertEqual(
                main(["scan", str(root / "a.md"), str(root / "b.md"),
                      "--no-color", "--fail-on", "lie",
                      "--enable", "unclosed-fence"]), 0)

    def test_zero_files_falls_back_to_dot(self):
        # pre-commit passes no filenames when nothing matched `files:`; the
        # hook must stay silent rather than die on `scan` with no path.
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.py").write_text("X = 1\n", encoding="utf-8")
            self.assertEqual(main(["scan", str(td), "--no-color"]), 0)


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

    def test_unknown_id_warns_without_failing(self):
        import contextlib
        import io
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text(
                "# Calls `ghost_fn()`.  # grounded-disable: stale-symobl\nX = 1\n",
                encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = main(["scan", str(root), "--no-color", "--fail-on", "never"])
            self.assertEqual(rc, 0)
            self.assertIn("unknown checker id", err.getvalue())
            self.assertIn("stale-symobl", err.getvalue())

    def test_known_id_no_warning(self):
        import contextlib
        import io
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text(
                "# Calls `ghost_fn()`.  # grounded-disable: stale-symbol-ref\nX = 1\n",
                encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                main(["scan", str(root), "--no-color"])
            self.assertNotIn("unknown checker id", err.getvalue())


class TestFix(unittest.TestCase):
    def _write(self, root: Path, files: dict[str, str]) -> None:
        for rel, text in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")

    def test_unique_match_rewritten(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, {
                "src/real/deep.py": "X = 1\n",
                "a.py": "# See src/old/deep.py for details.\nY = 2\n",
            })
            self.assertEqual(main(["fix", str(root)]), 0)
            self.assertIn("src/real/deep.py", (root / "a.py").read_text())
            # rescan is clean
            self.assertEqual(main(["scan", str(root), "--no-color"]), 0)

    def test_dry_run_writes_nothing(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, {
                "src/real/deep.py": "X = 1\n",
                "a.py": "# See src/old/deep.py for details.\nY = 2\n",
            })
            before = (root / "a.py").read_text()
            self.assertEqual(main(["fix", str(root), "--dry-run"]), 0)
            self.assertEqual((root / "a.py").read_text(), before)

    def test_ambiguous_basename_untouched(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, {
                "src/one/deep.py": "X = 1\n",
                "src/two/deep.py": "X = 2\n",
                "a.py": "# See src/old/deep.py for details.\nY = 2\n",
            })
            self.assertEqual(main(["fix", str(root)]), 0)
            self.assertIn("src/old/deep.py", (root / "a.py").read_text())

    def test_docstring_claim_untouched(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, {
                "src/real/deep.py": "X = 1\n",
                "a.py": 'def f():\n    """Do.\n\n    See src/old/deep.py.\n    """\n    return 1\n',
            })
            self.assertEqual(main(["fix", str(root)]), 0)
            self.assertIn("src/old/deep.py", (root / "a.py").read_text())

    def test_non_file_findings_untouched(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, {"a.py": "# Calls `ghost_fn()`.\nX = 1\n"})
            before = (root / "a.py").read_text()
            self.assertEqual(main(["fix", str(root)]), 0)
            self.assertEqual((root / "a.py").read_text(), before)

    def test_ignored_directories_not_used_as_fix_candidates(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, {
                ".git/hooks/pre-commit.py": "print('hook')\n",
                ".venv/lib/helper.py": "print('venv')\n",
                "a.py": "# See src/hooks/pre-commit.py and src/old/helper.py\nX = 1\n",
            })
            before = (root / "a.py").read_text()
            self.assertEqual(main(["fix", str(root)]), 0)
            self.assertEqual((root / "a.py").read_text(), before)

    def test_symbol_rename_same_dir_unique(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, {
                "pkg/real.py": "def test_max_cookie_length():\n    pass\n",
                "pkg/note.py": "# see comment in CookieTests.test_cookie_max_length()\nX = 1\n",
                "other/test_choices_in_max_length.py": "def test_choices_in_max_length():\n    pass\n",
            })
            self.assertEqual(main(["fix", str(root)]), 0)
            text = (root / "pkg" / "note.py").read_text()
            self.assertIn("test_max_cookie_length", text)
            self.assertNotIn("test_cookie_max_length", text)

    def test_symbol_rename_ambiguous_same_dir_untouched(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, {
                "pkg/a.py": "def test_max_cookie_length():\n    pass\n",
                "pkg/b.py": "def test_cookie_max_thing():\n    pass\n",
                "pkg/note.py": "# see comment in CookieTests.test_cookie_max_length()\nX = 1\n",
            })
            before = (root / "pkg" / "note.py").read_text()
            self.assertEqual(main(["fix", str(root)]), 0)
            self.assertEqual((root / "pkg" / "note.py").read_text(), before)

    def test_symbol_bare_claim_fixed_when_unique(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, {
                "pkg/real.py": "def fetch_user_data():\n    pass\n",
                "pkg/note.py": "# Calls fetch_user_data_old() and formats.\nX = 1\n",
            })
            self.assertEqual(main(["fix", str(root)]), 0)
            text = (root / "pkg" / "note.py").read_text()
            self.assertIn("fetch_user_data()", text)
            self.assertNotIn("fetch_user_data_old", text)


class TestMatcherDrift(unittest.TestCase):
    def test_terminal_lines_match_problem_matcher(self):
        """The GitHub Action annotations break silently if terminal output
        drifts from the matcher regexes. This pins them together."""
        import io
        import contextlib
        import re
        from grounded.cli import main
        root = Path(__file__).resolve().parent.parent
        matcher = json.loads((root / ".github" / "grounded-problem-matcher.json").read_text())
        patterns = {}
        for entry in matcher["problemMatcher"]:
            sev = {"error": "LIE", "warning": "DRIFT", "notice": "SMELL"}[
                entry["severity"]]
            patterns[sev] = re.compile(entry["pattern"][0]["regexp"])
        with tempfile.TemporaryDirectory() as td:
            troot = Path(td)
            (troot / "a.py").write_text(
                "# Calls `ghost_fn()`.\n# See line 99 for details.\nX = 1\n",
                encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                main(["scan", str(troot), "--no-color"])
            matched = {"LIE": False, "SMELL": False}
            for line in buf.getvalue().splitlines():
                for sev, pat in patterns.items():
                    m = pat.match(line)
                    if m and sev in matched:
                        matched[sev] = True
            self.assertTrue(matched["LIE"], "LIE line must match its matcher")
            self.assertTrue(matched["SMELL"], "SMELL line must match its matcher")


class TestImpact(unittest.TestCase):
    def _tree(self, root: Path) -> None:
        (root / "pkg").mkdir(parents=True)
        (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (root / "pkg" / "core.py").write_text(
            "def get_account(uid):\n    return uid\n", encoding="utf-8")
        (root / "pkg" / "views.py").write_text(
            "from .core import get_account\n\n\n"
            "def show(uid):\n    # Uses `get_account()`.\n    return get_account(uid)\n",
            encoding="utf-8")

    def test_blast_radius(self):
        from grounded.config import Config
        from grounded.graph import ClaimGraph
        from grounded.scanner import scan_root
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._tree(root)
            _, facts, index = scan_root(root, Config())
            result = ClaimGraph(index, {f.path: f for f in facts}).blast_radius("get_account")
            self.assertEqual(result["defined_in"], ["pkg/core.py"])
            self.assertEqual(result["imported_by"], ["pkg/views.py"])
            self.assertEqual(result["claimed_by"], ["pkg/views.py"])

    def test_blast_radius_claims_all_surfaces(self):
        from grounded.config import Config
        from grounded.graph import ClaimGraph
        from grounded.scanner import scan_root
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pkg = root / "pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "core.py").write_text(
                "def get_account(uid):\n    return uid\n", encoding="utf-8")
            (pkg / "views.py").write_text(
                "# DEPRECATED: use get_account(uid) instead.\nX = 1\n", encoding="utf-8")
            (root / "README.md").write_text(
                "# Demo\n\n```python\nresult = get_account(1)\n```\n", encoding="utf-8")
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_core.py").write_text(
                'from unittest.mock import patch\n\n@patch("pkg.core.get_account")\n'
                "def test_x(m):\n    pass\n",
                encoding="utf-8")
            (root / "pyproject.toml").write_text(
                '[project]\nname = "d"\n[project.scripts]\ndemo = "pkg.core:get_account"\n',
                encoding="utf-8")
            _, facts, index = scan_root(root, Config(), include_claim_surfaces=True)
            result = ClaimGraph(index, {f.path: f for f in facts}).blast_radius("get_account")
            self.assertEqual(
                sorted(result["claimed_by"]),
                ["README.md", "pkg/views.py", "pyproject.toml", "tests/test_core.py"])

    def test_dangling_signature(self):
        from grounded.config import Config
        from grounded.graph import ClaimGraph
        from grounded.scanner import scan_root
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._tree(root)
            _, facts, index = scan_root(root, Config())
            result = ClaimGraph(index, {f.path: f for f in facts}).blast_radius("gone_fn")
            self.assertEqual(result, {"symbol": "gone_fn", "defined_in": [],
                                      "imported_by": [], "claimed_by": []})

    def test_cli_terminal_and_json(self):
        import contextlib
        import io
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._tree(root)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(main(["impact", "get_account", str(root)]), 0)
            self.assertIn("pkg/core.py", buf.getvalue())
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(main(["impact", "get_account", str(root), "--format", "json"]), 0)
            self.assertEqual(json.loads(buf.getvalue())["defined_in"], ["pkg/core.py"])

    def test_mcp_blast_radius(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._tree(root)
            from grounded.mcp import McpServer
            server = McpServer(root)
            server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                      "clientInfo": {"name": "t", "version": "0"}}})
            tools = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            self.assertIn("blast_radius", {t["name"] for t in tools["result"]["tools"]})
            resp = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                  "params": {"name": "blast_radius",
                                             "arguments": {"symbol": "get_account"}}})
            payload = json.loads(resp["result"]["content"][0]["text"])
            self.assertEqual(payload["defined_in"], ["pkg/core.py"])
            bad = server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                 "params": {"name": "blast_radius", "arguments": {}}})
            self.assertEqual(bad["error"]["code"], -32602)

    def test_blast_radius_sees_module_attribute_use(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pkg = root / "pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "helper.py").write_text(
                "def serve():\n    return 1\n", encoding="utf-8")
            (root / "main.py").write_text(
                "from pkg import helper\nhelper.serve()\n", encoding="utf-8")
            from grounded.mcp import McpServer
            server = McpServer(root)
            server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                      "clientInfo": {"name": "t", "version": "0"}}})
            resp = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                  "params": {"name": "blast_radius",
                                             "arguments": {"symbol": "serve"}}})
            payload = json.loads(resp["result"]["content"][0]["text"])
            self.assertIn("main.py", payload["imported_by"])

    def test_mcp_honors_project_config(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text("# Calls `ghost_fn()`.\nX = 1\n", encoding="utf-8")
            (root / "grounded.toml").write_text(
                'disable = ["stale-symbol-ref"]\n', encoding="utf-8")
            from grounded.mcp import McpServer
            server = McpServer(root)
            server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                      "clientInfo": {"name": "t", "version": "0"}}})
            resp = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                  "params": {"name": "check_path", "arguments": {"path": "."}}})
            payload = json.loads(resp["result"]["content"][0]["text"])
            self.assertFalse(payload["failed"])
            self.assertEqual(payload["summary"]["findings"], 0)


class TestBaselineIntegrity(unittest.TestCase):
    def test_baseline_is_deduplicated_and_total_matches_file(self):
        """Two findings on different lines can share a fingerprint (it
        hashes rule, path, title and claim — never line numbers). Writing
        the raw list made the file longer than the reported total
        (measured: 284 entries for 277 unique fingerprints on a 10k-file
        tree)."""
        from grounded.delta import write_baseline
        from grounded.models import Finding
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".grounded-baseline.json"
            same = dict(path="a.py", line=1, end_line=1, checker="stale-symbol-ref",
                        severity="lie", title="t", claim="`ghost()`")
            findings = [Finding(**same), Finding(**{**same, "line": 9})]
            stats = write_baseline(path, findings)
            written = json.loads(path.read_text(encoding="utf-8"))["fingerprints"]
            self.assertEqual(len(written), len(set(written)))
            self.assertEqual(len(written), stats["total"])
            self.assertEqual(stats["total"], 1)

    def test_baseline_round_trips_as_a_set(self):
        from grounded.delta import load_baseline, write_baseline
        from grounded.models import Finding
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "b.json"
            f = Finding(path="a.py", line=3, end_line=3, checker="stale-file-ref",
                        severity="lie", title="t", claim="src/gone.py")
            write_baseline(path, [f])
            self.assertEqual(len(load_baseline(path)), 1)


class TestDoctor(unittest.TestCase):
    def _home_with(self, settings=None, skill=False):
        from unittest import mock
        td = tempfile.TemporaryDirectory()
        home = Path(td.name)
        if settings is not None:
            d = home / ".claude"
            d.mkdir(parents=True)
            (d / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        if skill:
            d = home / ".claude" / "skills" / "grounded"
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text("# skill", encoding="utf-8")
        self.addCleanup(td.cleanup)
        return mock.patch("grounded.cli._home", return_value=home)

    def _run(self, argv):
        import contextlib
        import io
        from grounded.cli import main
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(argv)
        return rc, buf.getvalue()

    def test_healthy_home(self):
        from unittest import mock
        from grounded import __version__
        settings = {"hooks": {"PostToolUse": [
            {"matcher": "Edit|Write|MultiEdit",
             "hooks": [{"type": "command",
                        "command": "grounded hook claude-code"}]}]}}
        with self._home_with(settings, skill=True), \
                mock.patch("grounded.cli._pypi_latest",
                           return_value=__import__("grounded").__version__), \
                mock.patch("grounded.cli._mcp_probe",
                           return_value=("ok", "MCP server answers")):
            rc, out = self._run(["doctor"])
            self.assertEqual(rc, 0)
            self.assertIn("healthy", out)
            rc, out = self._run(["doctor", "--json"])
            self.assertEqual(rc, 0)
            rows = json.loads(out)
            self.assertTrue(all({"status", "detail"} <= set(r) for r in rows))

    def test_legacy_hook_is_stale(self):
        from unittest import mock
        settings = {"hooks": {"PostToolUse": [
            {"matcher": "Edit|Write",
             "hooks": [{"type": "command",
                        "command": "grounded scan . --changed --quiet"}]}]}}
        with self._home_with(settings), \
                mock.patch("grounded.cli._pypi_latest", return_value=None), \
                mock.patch("grounded.cli._mcp_probe",
                           return_value=("ok", "MCP server answers")):
            rc, out = self._run(["doctor"])
            self.assertEqual(rc, 1)
            self.assertIn("[stale]", out)
            self.assertIn("init-agent --claude", out)

    def test_missing_hook(self):
        from unittest import mock
        with self._home_with(None), \
                mock.patch("grounded.cli._pypi_latest", return_value=None), \
                mock.patch("grounded.cli._mcp_probe",
                           return_value=("ok", "MCP server answers")):
            rc, out = self._run(["doctor"])
            self.assertEqual(rc, 1)
            self.assertIn("[missing]", out)


class TestWatch(unittest.TestCase):
    def test_start_then_new_finding(self):
        from grounded.config import Config
        from grounded.watch import run_watch, snapshot_files
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text("X = 1\n", encoding="utf-8")
            snap = snapshot_files(root, Config())
            self.assertEqual(list(snap), ["a.py"])
            events = []

            def on_event(kind, payload, iteration):
                events.append((kind, len(payload), iteration))
                if kind == "start":
                    (root / "a.py").write_text(
                        "# Calls `ghost_fn_xyz()`.\nX = 1\n", encoding="utf-8")

            rc = run_watch(root, Config(), interval=0, max_iterations=2,
                           on_event=on_event)
            self.assertEqual(rc, 0)
            self.assertEqual([e[0] for e in events], ["start", "new"])
            self.assertEqual(events[1][1], 1)

    def test_line_shift_is_not_new(self):
        from grounded.config import Config
        from grounded.watch import run_watch
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text("# Calls `ghost_fn_xyz()`.\nX = 1\n",
                                       encoding="utf-8")
            events = []

            def on_event(kind, payload, iteration):
                events.append((kind, len(payload), iteration))
                if kind == "start":
                    (root / "a.py").write_text(
                        "\n\n# Calls `ghost_fn_xyz()`.\nX = 1\n", encoding="utf-8")

            run_watch(root, Config(), interval=0, max_iterations=2,
                      on_event=on_event)
            self.assertEqual([e[0] for e in events], ["start", "clean"])

    def test_cli_watch_bad_path(self):
        from grounded.cli import main
        self.assertEqual(main(["watch", "/nonexistent-grounded-dir"]), 2)


class TestPr(unittest.TestCase):
    def _write(self, root: Path, files: dict[str, str]) -> None:
        for rel, text in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")

    def _git(self, root: Path, *args: str) -> None:
        import os
        import subprocess
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        subprocess.run(["git", *args], cwd=root, check=True,
                       capture_output=True, env=env, timeout=60)

    def _fixable(self, root: Path) -> None:
        self._write(root, {
            "src/real/deep.py": "X = 1\n",
            "a.py": "# See src/old/deep.py for details.\nY = 2\n",
        })

    def test_dry_run_prints_plan_and_body(self):
        import contextlib
        import io
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._fixable(root)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(main(["pr", str(root), "--dry-run"]), 0)
            out = buf.getvalue()
            self.assertIn("src/real/deep.py", out)
            self.assertIn("Generated mechanically by Grounded", out)
            self.assertIn("src/old/deep.py", (root / "a.py").read_text())

    def test_dirty_tree_refused(self):
        import shutil
        from grounded.cli import main
        if shutil.which("git") is None:
            self.skipTest("git not installed")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._fixable(root)
            self._git(root, "init", "-q")
            self._git(root, "add", "-A")
            self._git(root, "commit", "-qm", "init")
            (root / "a.py").write_text("# See src/old/deep.py for details.\n# dirty work in progress\n",
                                       encoding="utf-8")
            self.assertEqual(main(["pr", str(root), "--dry-run"]), 0)
            import contextlib
            import io
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(main(["pr", str(root)]), 2)
            self.assertIn("dirty", err.getvalue())

    def test_full_flow_with_stub_gh(self):
        import contextlib
        import io
        import os
        import shutil
        import stat
        import subprocess
        from unittest import mock
        from grounded.cli import main
        if shutil.which("git") is None:
            self.skipTest("git not installed")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bindir = Path(td) / "bin"
            bindir.mkdir()
            log = bindir / "gh-args.log"
            stub = bindir / "gh"
            stub.write_text("#!/bin/sh\necho \"$@\" >> \"$GH_LOG\"\n"
                            "echo https://github.com/o/r/pull/1\n",
                            encoding="utf-8")
            stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
            self._fixable(root)
            self._git(root, "init", "-q")
            self._git(root, "add", "-A")
            self._git(root, "commit", "-qm", "init")
            self._git(root, "remote", "add", "origin", "https://x.invalid/o/r.git")
            env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ["PATH"],
                       GH_LOG=str(log))
            buf = io.StringIO()
            err = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=False), \
                    contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
                rc = main(["pr", str(root), "--title", "fix test"])
            # push to the invalid remote fails: the fix lands on a local
            # branch + commit, and the command reports honestly (rc 2)
            # instead of faking a PR URL.
            self.assertEqual(rc, 2)
            self.assertIn("src/real/deep.py", (root / "a.py").read_text())
            branches = subprocess.run(["git", "branch", "--list", "grounded-fixes-*"],
                                      cwd=root, capture_output=True, text=True,
                                      timeout=60).stdout
            self.assertIn("grounded-fixes-", branches)
            log_text = subprocess.run(["git", "log", "--format=%s", "-1"],
                                      cwd=root, capture_output=True, text=True,
                                      timeout=60).stdout.strip()
            self.assertEqual(log_text, "fix test")
            # gh itself was never reached (push failed first)
            self.assertFalse(log.exists())

    def test_pr_created_against_local_remote(self):
        import contextlib
        import io
        import os
        import shutil
        import stat
        import subprocess
        from unittest import mock
        from grounded.cli import main
        if shutil.which("git") is None:
            self.skipTest("git not installed")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bindir = Path(td) / "bin"
            bindir.mkdir()
            log = bindir / "gh-args.log"
            stub = bindir / "gh"
            stub.write_text("#!/bin/sh\necho \"$@\" >> \"$GH_LOG\"\n"
                            "echo https://github.com/o/r/pull/7\n",
                            encoding="utf-8")
            stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
            self._fixable(root)
            self._git(root, "init", "-q")
            self._git(root, "add", "-A")
            self._git(root, "commit", "-qm", "init")
            bare = Path(td) / "remote.git"
            subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True,
                           capture_output=True, timeout=60)
            self._git(root, "remote", "add", "origin", str(bare))
            env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ["PATH"],
                       GH_LOG=str(log))
            buf = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=False), \
                    contextlib.redirect_stdout(buf):
                rc = main(["pr", str(root), "--title", "fix test"])
            self.assertEqual(rc, 0)
            self.assertIn("https://github.com/o/r/pull/7", buf.getvalue())
            recorded = log.read_text(encoding="utf-8")
            self.assertIn("pr create", recorded)
            self.assertIn("fix test", recorded)
            self.assertIn("Generated mechanically by Grounded", recorded)

    def test_nothing_to_fix(self):
        import contextlib
        import io
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, {"a.py": "X = 1\n"})
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(main(["pr", str(root), "--dry-run"]), 0)
            self.assertIn("nothing unambiguous", buf.getvalue())


class TestGenerateAgentRules(unittest.TestCase):
    def _tree(self, root: Path) -> None:
        (root / "src").mkdir()
        (root / "tests").mkdir()
        (root / "package.json").write_text(
            '{"scripts": {"test": "node --test", "build": "tsc"}}', encoding="utf-8")
        (root / "Makefile").write_text("lint:\n\truff check .\n", encoding="utf-8")

    def test_verified_content_only(self):
        import contextlib
        import io
        import os
        import re
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._tree(root)
            cwd = Path.cwd()
            os.chdir(root)
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    self.assertEqual(main(["generate-agent-rules"]), 0)
            finally:
                os.chdir(cwd)
            text = (root / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("npm run test", text)
            self.assertIn("make lint", text)
            # every claimed directory exists; every claimed command names
            # a real source (no invented paths, no invented commands)
            for m in re.finditer(r"`([A-Za-z0-9_][A-Za-z0-9_.\-/]*/)`", text):
                self.assertTrue((root / m.group(1)).exists(), m.group(1))

    def test_existing_kept_without_force(self):
        import contextlib
        import io
        import os
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._tree(root)
            (root / "AGENTS.md").write_text("mine\n", encoding="utf-8")
            cwd = Path.cwd()
            os.chdir(root)
            try:
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    self.assertEqual(main(["generate-agent-rules"]), 2)
            finally:
                os.chdir(cwd)
            self.assertEqual((root / "AGENTS.md").read_text(encoding="utf-8"), "mine\n")


class TestBadge(unittest.TestCase):
    def test_prints_shields_snippet(self):
        import contextlib
        import io
        from grounded.cli import main
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(main(["badge"]), 0)
        out = buf.getvalue()
        self.assertIn("img.shields.io", out)
        self.assertIn("github.com/gonisulaimann/Grounded", out)

    def test_check_gates_dirty_readme(self):
        import contextlib
        import io
        import os
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text(
                "# Demo\n\n```python\nphantom_call_xyz()\n```\n",
                encoding="utf-8")
            cwd = Path.cwd()
            os.chdir(root)
            try:
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    self.assertEqual(main(["badge", "--check"]), 1)
            finally:
                os.chdir(cwd)

    def test_check_passes_clean_readme(self):
        import contextlib
        import io
        import os
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text("# Demo\n\nNo code here.\n",
                                            encoding="utf-8")
            cwd = Path.cwd()
            os.chdir(root)
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    self.assertEqual(main(["badge", "--check"]), 0)
            finally:
                os.chdir(cwd)
            self.assertIn("img.shields.io", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
