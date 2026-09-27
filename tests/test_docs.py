"""Markdown checkers: the CommonMark fence walk, stale-doc-ref, stale-cli-ref, unclosed-fence.

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


class TestFenceToggleCommonMark(unittest.TestCase):
    """Fence tracking must follow CommonMark, not count fence-looking lines.

    Measured 2026-09-22: re-deriving the retired scan and A/B-ing it against
    the shared walk over 10,857 Markdown files (Grounded, OmniRoute, svelte,
    flask, requests) shows two error directions. Prose wrongly skipped
    (the disarm): 1 file, 41 lines — an i18n doc with header text glued to
    its fence lines shifting the toggle's state. The far larger error ran
    the other way: 10,962 lines of code in 1,032 files were read as prose,
    because the retired regex did not recognize indented fences, rich info
    strings (` ```bash title="x" `), or unclosed fences running to EOF.
    An earlier draft of this docstring cited "238 files / 20,681 lines";
    that figure came from a comparison that mixed line populations and is
    retracted here.

    CommonMark rules pinned here:

    * a closing fence is a run of the **same character**, **at least as
      long**, carrying **no info string** — a longer bare fence closes;
    * an info-carrying fence inside an open block is **content**, not an
      opener (the README-216 defect, renderer-verified);
    * a fence may carry a rich info string (` ```bash title="x" `) and up
      to three leading spaces; a backtick fence whose info string contains
      a backtick is not a fence at all.
    """

    def _doc_blocks(self, text):
        from grounded.checkers import _doc_fence_blocks
        return _doc_fence_blocks(text.splitlines())

    def test_closing_fence_requires_no_info_string(self):
        # ```console inside an open block is content, not an opener; the
        # block stays open to EOF.
        text = ("# Guide\n\n```console\ngrounded scan . --changed\n\n"
                "Untracked files are fully reported.\n\n"
                "```console\ngrounded scan . --cache\n```")
        self.assertEqual(self._doc_blocks(text), [])

    def test_rich_info_string_is_still_a_fence(self):
        # `bash title="x"` opens a block; the old regex did not match it, so
        # every line inside was analyzed as prose. CommonMark property: the
        # info string is everything after the fence run.
        from grounded.checkers import _fence_scan
        blocks, open_at = _fence_scan(
            ['```bash title="install"', "ghost_tool --run", "```"])
        self.assertEqual([(b["open"], b["close"], b["info"]) for b in blocks],
                         [(1, 3, 'bash title="install"')])
        self.assertEqual(open_at, 0)
        # and the language table's deliberate narrowness is unchanged:
        # bash blocks are console, not parsed doc examples.
        self.assertEqual(self._doc_blocks(
            '```bash title="install"\nghost_tool --run\n```\n'), [])

    def test_indented_fence_opens_a_block(self):
        # Up to three leading spaces are allowed; the old regex required the
        # fence at column 0.
        text = "intro\n\n   ```python\nx = ghost_call()\n   ```\n"
        self.assertEqual(self._doc_blocks(text), [("python", 4, 5)])

    def test_longer_bare_fence_closes(self):
        text = "````python\nx = ghost_call()\n`````\n"
        self.assertEqual(self._doc_blocks(text), [("python", 2, 3)])

    def test_backtick_in_info_string_is_not_a_fence(self):
        # CommonMark: a backtick fence's info string may not contain a
        # backtick, so ``` `code` ``` is content — and must not swallow the
        # rest of the file.
        text = "``` `code` example\nnot a fence\n\n```python\nx = ghost()\n```\n"
        self.assertEqual(self._doc_blocks(text), [("python", 5, 6)])

    def test_nested_shorter_fence_is_content(self):
        # Declared scaffold: ````markdown around ```python. The inner block
        # is part of the illustrated content, not a separate block: exactly
        # one CommonMark block, and the inner fence is never re-emitted as
        # a python doc block (no double-reporting, no unparsed-language
        # leak into stale-doc-ref).
        from grounded.checkers import _fence_scan
        lines = "````markdown\n```python\nx = 1\n```\n````\n".splitlines()
        blocks, open_at = _fence_scan(lines)
        self.assertEqual([(b["open"], b["close"]) for b in blocks], [(1, 5)])
        self.assertEqual(open_at, 0)
        self.assertEqual(self._doc_blocks("\n".join(lines) + "\n"), [])

    def test_cli_ref_sees_invocations_in_rich_fences(self):
        import io
        from contextlib import redirect_stdout
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "README.md").write_text(
                '# Guide\n\n```bash title="check"\ngrounded scan . --bogus-flag\n````\n',
                encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                main(["scan", td, "--no-color", "--enable", "stale-cli-ref"])
            self.assertIn("bogus-flag", buf.getvalue())

    def test_cli_ref_not_disarmed_by_rich_fence(self):
        # The measured disarm: a rich fence the old toggle did not match
        # flipped its state for the rest of the file.
        import io
        from contextlib import redirect_stdout
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "README.md").write_text(
                '# Guide\n\n```bash title="x"\nls\n```\n\n'
                "```console\ngrounded frobnicate --yes\n```\n",
                encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                main(["scan", td, "--no-color", "--enable", "stale-cli-ref"])
            self.assertIn("frobnicate", buf.getvalue())

    def test_unclosed_fence_uses_the_same_walk(self):
        # The checker and the toggle must agree by construction: a rich
        # info string no longer hides a defect.
        import io
        from contextlib import redirect_stdout
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "README.md").write_text(
                '# Guide\n\n```bash title="x"\ngrounded scan .\n',
                encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                main(["scan", td, "--no-color", "--enable", "unclosed-fence"])
            self.assertIn("never closed", buf.getvalue())


class TestStaleDocRef(unittest.TestCase):
    DOC = (
        "# Demo\n\n```python\nfrom pkg.core import get_account\n\n"
        "client = get_account(1)\nghost = fetch_user(2)\n```\n"
    )

    def _tree(self, root, readme=None):
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "core.py").write_text(
            "def get_account(uid):\n    return uid\n", encoding="utf-8")
        (root / "README.md").write_text(
            readme if readme is not None else self.DOC, encoding="utf-8")

    def test_off_by_default(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            import os
            self._tree(Path(td))
            self.assertEqual(main(["scan", td, "--no-color"]), 0)

    def test_opt_in_finds_stale_call(self):
        from grounded.cli import main
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as td:
            self._tree(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["scan", td, "--no-color", "--enable", "stale-doc-ref"])
            self.assertEqual(rc, 1)
            self.assertIn("[stale-doc-ref]", buf.getvalue())
            self.assertIn("fetch_user", buf.getvalue())
            self.assertNotIn("get_account(1)", buf.getvalue())

    def test_go_stdlib_calls_silent(self):
        # Toolchain calls (fmt.Printf, time.Now) are not repo claims
        # (seen: gin docs). PONDER stays flagged as the control.
        from grounded.cli import main
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "README.md").write_text(
                "# Demo\n\n```go\nfmt.Println(time.Now())\nPONDER()\n```\n",
                encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["scan", td, "--no-color", "--enable", "stale-doc-ref"])
            self.assertEqual(rc, 1)
            self.assertIn("PONDER", buf.getvalue())
            self.assertNotIn("fmt.Println", buf.getvalue())
            self.assertNotIn("time.Now", buf.getvalue())

    def test_skips_uncheckable_blocks(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            self._tree(Path(td), readme=(
                "# Demo\n\n```console\nghost_tool --run\n```\n\n"
                "```\nfoo(bar)\n```\n\n"
                "```python\nresult = compute_total(...)\n```\n\n"
                "```python\nx = my_widget.render()\n```\n\n"
                "```python\nimport os\nprint(os.getcwd())\n```\n"))
            self.assertEqual(
                main(["scan", td, "--no-color", "--enable", "stale-doc-ref"]), 0)

    def test_enable_via_config_file(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            import os
            root = Path(td)
            self._tree(root)
            (root / "grounded.toml").write_text(
                'enable = ["stale-doc-ref"]\n', encoding="utf-8")
            cwd = Path.cwd()
            os.chdir(root)
            try:
                self.assertEqual(main(["scan", ".", "--no-color"]), 1)
            finally:
                os.chdir(cwd)

    def test_default_set_excludes_opt_in(self):
        from grounded.checkers import CHECKERS, DEFAULT_ENABLED, OPT_IN_CHECKERS
        self.assertIn("stale-doc-ref", CHECKERS)
        self.assertIn("stale-doc-ref", OPT_IN_CHECKERS)
        self.assertNotIn("stale-doc-ref", DEFAULT_ENABLED)
        from grounded.config import Config
        self.assertNotIn("stale-doc-ref", Config().enabled)

    def test_js_ambient_roots_silent(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text(
                "# Demo\n\n```js\n"
                "return Promise.reject(error);\n"
                "const el = document.getElementById('x');\n"
                "this.setup();\n"
                "try {\n  foo();\n"
                "} catch (e) {\n  bar(e);\n"
                "}\n```\n",
                encoding="utf-8")
            self.assertEqual(
                main(["scan", td, "--no-color", "--enable", "stale-doc-ref"]), 0)

    def test_js_bindings_params_methods_templates(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text('{"name": "demo"}\n', encoding="utf-8")
            (root / "README.md").write_text(
                "# Demo\n\n```js\n"
                "import qs from 'qs';\n"
                "import { a, b as c } from './lib';\n"
                "import * as ns from './ns';\n"
                "function handle(x) { return x; }\n"
                "const show = (t) => t;\n"
                "const out = qs.stringify(ns.val(c));\n"
                "[1].forEach((item) => handle(item));\n"
                "function render(title) { return show(title); }\n"
                "class Widget {\n  normalize(e) { return e; }\n"
                "}\n"
                "const msg = `hi ${name()}`;\n"
                "demo.run();\n"
                "```\n",
                encoding="utf-8")
            self.assertEqual(
                main(["scan", td, "--no-color", "--enable", "stale-doc-ref"]), 0)

    def test_js_chain_lines_silent(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text(
                "# Demo\n\n```js\n"
                "fetch(url)\n"
                "  .then(r => r.json())\n"
                "  .catch(handle);\n"
                "```\n",
                encoding="utf-8")
            # fetch is ambient; .then/.catch are continuation chains
            self.assertEqual(
                main(["scan", td, "--no-color", "--enable", "stale-doc-ref"]), 0)

    def test_js_event_constructors_silent(self):
        # DOM event constructors are ambient (seen: axios migration guide).
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text(
                "# Demo\n\n```js\n"
                "const el = document.createElement('x');\n"
                "el.dispatchEvent(new CustomEvent('x'));\n"
                "const m = new Map();\n"
                "console.log(el, m);\n"
                "```\n",
                encoding="utf-8")
            self.assertEqual(
                main(["scan", td, "--no-color", "--enable", "stale-doc-ref"]), 0)


class TestStaleCliRef(unittest.TestCase):
    def _scan(self, td):
        from grounded.cli import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["scan", td, "--no-color", "--enable", "stale-cli-ref"])
        return rc, buf.getvalue()

    def test_bad_subcommand_and_flag_fire(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "README.md").write_text(
                "# Demo\n\n```console\ngrounded scan . --changed --quiet\n"
                "grounded frobnicate --yes\n```\n",
                encoding="utf-8")
            rc, out = self._scan(td)
            self.assertEqual(rc, 1)
            self.assertIn("frobnicate", out)

    def test_valid_prose_synopsis_output_silent(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "README.md").write_text(
                "# Demo\n\nRun `grounded init-agent --cursor` after edits.\n\n"
                "```console\n$ grounded mcp [--root .]\n"
                "grounded fix: 1 file(s) would change.\n```\n\n"
                "The grounded skill teaches agents to verify first.\n",
                encoding="utf-8")
            rc, out = self._scan(td)
            self.assertEqual(rc, 0)
            self.assertNotIn("stale-cli-ref", out)

    def test_python_m_form(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "README.md").write_text(
                "```console\npython -m grounded.cli scan . --bogus-flag\n```\n",
                encoding="utf-8")
            rc, out = self._scan(td)
            self.assertIn("--bogus-flag", out)

    def test_off_by_default(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "README.md").write_text(
                "```console\ngrounded frobnicate\n```\n", encoding="utf-8")
            self.assertEqual(main(["scan", td, "--no-color"]), 0)


class TestUnclosedFence(unittest.TestCase):
    """`unclosed-fence`: fences the renderer does not honour.

    Precision measured 2026-09-22 over 11,564 Markdown files in eight real
    repos (svelte, vuejs/docs, rust-lang/book, markdown-it, flask, requests,
    OmniRoute, and this repo): 0 false positives. The only findings were these
    fixtures and one real document — OmniRoute's
    `docs/frameworks/OPEN_SSE_ARCHITECTURE.md`, where a stray bare
    ```` ```` ```` fence made GitHub render a 76-line code block containing
    `## Services (117 modules)`, `### Common Patterns` and the surrounding
    prose, verified with `POST /markdown` (`mode=gfm`).

    The two silence cases below are the shapes that would otherwise fire: a
    *declared* nesting scaffold (` ````markdown ` around ` ```python `, which
    is how svelte's docs show Svelte inside HTML on purpose, and renders
    correctly) and a bare fence inside a block (the illustrated closer of a
    nested example).
    """

    def _findings(self, td):
        return scan_root(Path(td), Config(enabled={"unclosed-fence"}))[0]

    def test_never_closed_fires_at_the_opener(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "README.md").write_text(
                "\n".join(["# Guide", "", "Prose.", "", "```console",
                           "grounded scan ."]), encoding="utf-8")
            findings = self._findings(td)
            self.assertEqual(len(findings), 1, findings)
            self.assertEqual(findings[0].line, 5)
            self.assertIn("never closed", findings[0].title)
            # Graduated 2026-09-22: a fence the renderer does not honour is
            # document corruption, not a style note — it gates like a lie.
            self.assertEqual(findings[0].severity, "lie")

    def test_swallowed_boundary_names_the_open_block(self):
        # The real shape: a missing close, then a second header of the same
        # length, which CommonMark reads as content rather than an opener.
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "README.md").write_text(
                "\n".join(["# Guide", "", "Gate on changed lines:", "",
                           "```console", "grounded scan . --changed", "",
                           "Untracked files are fully reported.", "",
                           "```console", "grounded scan . --cache", "```"]),
                encoding="utf-8")
            findings = self._findings(td)
            self.assertEqual(len(findings), 1, findings)
            self.assertEqual(findings[0].line, 10)
            self.assertIn("swallowed by the block opened at line 5",
                          findings[0].title)

    def test_bare_longer_fence_fires(self):
        # A bare 4-backtick line reads as a closer but opens a block; the ts
        # header inside it is then content. This is the OmniRoute shape.
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "README.md").write_text(
                "\n".join(["# Guide", "", "Providers are configured in one place.",
                           "", "````", "", "```ts", "const x = 1;", "```",
                           "", "````"]), encoding="utf-8")
            findings = self._findings(td)
            self.assertEqual(len(findings), 1, findings)
            self.assertEqual(findings[0].line, 7)
            self.assertIn("block opened at line 5", findings[0].title)

    def test_declared_nesting_scaffold_is_silent(self):
        # ````markdown around ```python: the outer fence declares itself, so
        # the inner header is an illustration, not a swallowed boundary.
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "README.md").write_text(
                "\n".join(["# Guide", "", "````markdown", "```python",
                           "x = 1", "```", "````"]), encoding="utf-8")
            self.assertEqual(self._findings(td), [])

    def test_bare_inner_fence_is_silent(self):
        # A bare fence inside a block is the illustrated closer of a nested
        # example, not a header.
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "README.md").write_text(
                "\n".join(["# Guide", "", "````svelte", "<p>hi</p>", "```",
                           "````"]), encoding="utf-8")
            self.assertEqual(self._findings(td), [])

    def test_non_markdown_is_silent(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.py").write_text("x = '```console'\n", encoding="utf-8")
            self.assertEqual(self._findings(td), [])

    def test_cli_collects_markdown_for_this_checker(self):
        # The scanner only collects Markdown when one of its checkers runs;
        # without that gate this checker would silently see no files.
        import io
        from contextlib import redirect_stdout
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "README.md").write_text(
                "# Guide\n\n```console\ngrounded scan .\n", encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["scan", td, "--no-color"])
            # Graduated 2026-09-22: collected and gating by default. The
            # scanner only collects Markdown when one of its checkers runs,
            # and this checker is always in DEFAULT_ENABLED now.
            self.assertEqual(rc, 1)
            self.assertIn("unclosed-fence", buf.getvalue())

    def test_explicit_opt_out_still_works(self):
        import io
        from contextlib import redirect_stdout
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "README.md").write_text(
                "# Guide\n\n```console\ngrounded scan .\n", encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["scan", td, "--no-color", "--disable", "unclosed-fence"])
            self.assertEqual(rc, 0)

    def test_on_by_default(self):
        from grounded.checkers import DEFAULT_ENABLED, OPT_IN_CHECKERS
        self.assertIn("unclosed-fence", DEFAULT_ENABLED)
        self.assertNotIn("unclosed-fence", OPT_IN_CHECKERS)


def _reference_scan(text: str) -> list[tuple[int, int | None, str]]:
    """Independent fenced-code extraction for the differential fuzz.

    Written from the CommonMark 0.31.2 fenced-code-block clauses but
    structurally unlike `_fence_scan`: char-by-char scanning, no regexes,
    no block list. Returns `(open_line, close_line, info)` per block, with
    `close_line` None when a block runs to EOF. Deliberately shares the
    scanner's documented contract: top-level (non-list) structure only.
    """
    open_char, open_len, open_line, open_info = "", 0, 0, ""
    blocks: list[tuple[int, int | None, str]] = []
    for lineno, line in enumerate(text.split("\n"), start=1):
        stripped = line.rstrip("\r")
        indent = 0
        i = 0
        while i < len(stripped) and stripped[i] == " " and indent < 4:
            indent += 1
            i += 1
        rest = stripped[i:]
        if not open_char:
            if indent <= 3 and rest[:3] in ("```", "~~~"):
                ch = rest[0]
                n = 0
                while n < len(rest) and rest[n] == ch:
                    n += 1
                if n >= 3:
                    info = rest[n:]
                    if ch == "`" and "`" in info:
                        continue  # info may not contain backticks: not a fence
                    open_char, open_len = ch, n
                    open_line, open_info = lineno, info
            continue
        if indent <= 3 and rest[:1] == open_char:
            n = 0
            while n < len(rest) and rest[n] == open_char:
                n += 1
            if n >= open_len and not rest[n:].strip():
                blocks.append((open_line, lineno, open_info))
                open_char, open_len, open_line, open_info = "", 0, 0, ""
    if open_char:
        blocks.append((open_line, None, open_info))
    return blocks


class TestFenceScanSpec(unittest.TestCase):
    """`_fence_scan` pinned three ways: spec goldens, differential fuzz,
    real-document mutation.

    The fence walk is the single source of truth for every doc checker, so
    a regression there silently corrupts several checkers at once — the
    failure mode that started this (a naive toggle missing rich-info
    fences read 10,962 lines of fenced code as prose across 1,032 files).
    The reference walker above is written from the CommonMark clauses but
    shares no code or regexes with `_fence_scan`; the fuzz layer mutates
    real repository Markdown so the corpus of inputs is the repo itself,
    not just synthetic lines.
    """

    GOLDENS: list[tuple[str, list[tuple[int, int | None, str]]]] = [
        # CommonMark 0.31.2 example 141: info line with a backtick inside an
        # open block is content, and the block still closes on the bare fence.
        ("```\n``` aaa\n```\n", [(1, 3, "")]),
        # Example 142: tilde block swallows a backtick fence as content.
        ("~~~\n```\n", [(1, None, "")]),
        # Example 143: a longer outer fence; inner fences are content.
        ("````\n```\naaa\n```\n````\n", [(1, 5, "")]),
        # Closing fence may be longer than the opener, never shorter.
        ("```\naaa\n`````\n", [(1, 3, "")]),
        ("````\naaa\n```\n", [(1, None, "")]),
        # Characters cannot mix: ~~~ never closes a backtick block.
        ("```\naaa\n~~~\n", [(1, None, "")]),
        # Backtick info strings containing a backtick are not fences.
        ("``` a`b\nfoo\n", []),
        # ...but the same line inside a tilde block is just content there.
        ("~~~\n``` a`b\n~~~\n", [(1, 3, "")]),
        # Tilde info strings may contain backticks freely — the whole rest
        # of the line is the info string, backticks and all.
        ("~~~ ```\naaa\n~~~\n", [(1, 3, " ```")]),
        # An info-carrying fence inside an open block is content — the
        # exact shape that broke this repo's README (a ```console opened
        # and a later ```console was swallowed).
        ("```console\n$ ls\n```py\nx = 1\n```\n", [(1, 5, "console")]),
        # Indented 4+ is not a fence at all.
        ("     ```\nfoo\n", []),
        # Up to 3 spaces of indent open, and close, a fence.
        ("  ```py\nx = 1\n   ```\n", [(1, 3, "py")]),
        # Closing fence may carry trailing whitespace, never an info string.
        ("```\naaa\n```   \n", [(1, 3, "")]),
        ("```\naaa\n``` py\n", [(1, None, "")]),
        # Unclosed at EOF: close is None.
        ("a\n```py\nx = 1\n", [(2, None, "py")]),
    ]

    _FUZZ_LINES = [
        "```", "~~~", "````", "~~~~", "```py", "~~~py", "``` a`b", "```a``",
        "~~~ x~~~", "  ```", "   ~~~", "    ```", "``` ", "```\t", "text",
        "```md", "~~~~~~", "``````", "```~", "~```", "``` `` ", "console",
        "$ grounded scan .", "", "   ", "````md", "```{python}", "~```~",
        "``` ```", "  ~~~py", "```py``", "~~~~~", "     ```", "\t```",
    ]

    def _walk(self, text: str) -> list[tuple[int, int | None, str]]:
        from grounded.checkers import _fence_scan
        blocks, _open_at = _fence_scan(text.split("\n"))
        return [(b["open"], b["close"], b["info"]) for b in blocks]

    def test_spec_goldens(self) -> None:
        for text, expected in self.GOLDENS:
            with self.subTest(text=text):
                got = self._walk(text)
                self.assertEqual(got, expected,
                                 f"reference={_reference_scan(text)!r}")

    def _repo_markdown(self) -> list[Path]:
        root = Path(__file__).resolve().parent.parent
        skip = {".git", "node_modules", "__pycache__", "corpus"}
        return sorted(p for p in root.rglob("*.md")
                      if not any(part in skip for part in p.parts))

    def test_differential_random_lines(self) -> None:
        rng = random.Random(0xF11)
        for seed in range(240):
            lines = [rng.choice(self._FUZZ_LINES)
                     for _ in range(rng.randint(2, 12))]
            text = "\n".join(lines)
            with self.subTest(seed=seed, text=text):
                self.assertEqual(self._walk(text), _reference_scan(text),
                                 f"seed {seed} diverged")

    def test_differential_splice_into_real_docs(self) -> None:
        rng = random.Random(0xFE2)
        docs = self._repo_markdown()
        self.assertGreater(len(docs), 20, "expected repo docs to mutate")
        for path in docs:
            text = path.read_text(encoding="utf-8")
            for _ in range(2):
                lines = text.split("\n")
                lines.insert(rng.randrange(len(lines) + 1),
                             rng.choice(self._FUZZ_LINES))
                mutated = "\n".join(lines)
                with self.subTest(doc=str(path)):
                    self.assertEqual(self._walk(mutated),
                                     _reference_scan(mutated),
                                     f"splice into {path.name} diverged")

    def test_differential_mutate_fence_lines_of_real_docs(self) -> None:
        from grounded.checkers import _FENCE_LINE
        rng = random.Random(0xFE3)
        for path in self._repo_markdown():
            lines = path.read_text(encoding="utf-8").split("\n")
            fence_idx = [i for i, ln in enumerate(lines) if _FENCE_LINE.match(ln)]
            for i in rng.sample(fence_idx, min(2, len(fence_idx))):
                for kind in ("length", "char", "info"):
                    mutated = list(lines)
                    if kind == "length":
                        mutated[i] = mutated[i].replace(
                            "```", "```" + "`", 1) if "```" in mutated[i] \
                            else mutated[i] + "~"
                    elif kind == "char":
                        mutated[i] = mutated[i].replace("```", "~~~", 1) \
                            if "```" in mutated[i] else mutated[i].replace(
                            "~~~", "```", 1)
                    else:
                        mutated[i] = mutated[i] + " py"
                    text = "\n".join(mutated)
                    with self.subTest(doc=str(path), line=i + 1, kind=kind):
                        self.assertEqual(self._walk(text),
                                         _reference_scan(text),
                                         f"{path.name}:{i + 1} {kind} diverged")

    def test_differential_over_real_corpora_when_present(self) -> None:
        hosts = [p for p in (Path("/tmp/eval2/svelte"),
                             Path("/tmp/reverify/flask"),
                             Path("/tmp/reverify/requests")) if p.is_dir()]
        if not hosts:
            self.skipTest("no real-world corpora checked out")
        for host in hosts:
            docs = sorted(host.rglob("*.md"))[:250]
            if not docs:
                self.skipTest(f"{host.name} has no markdown (partial checkout)")
            for path in docs:
                text = path.read_text(encoding="utf-8", errors="replace")
                with self.subTest(host=host.name, doc=str(path)):
                    self.assertEqual(self._walk(text), _reference_scan(text),
                                     f"{path} diverged")


class TestRepoDocFences(unittest.TestCase):
    """The README's fences must balance.

    Measured 2026-09-22: one ` ```console ` opener at line 216 was never
    closed, so the paragraphs at lines 220-228 rendered as code on GitHub
    (verified with GitHub's own renderer: 24 code blocks broken, 25 fixed).
    It also inverted the doc checkers' fence state for the rest of the file,
    disarming `stale-cli-ref` for the whole tail. Neither symptom is visible
    in a diff review. Balance is judged by the shared `_fence_scan` walk —
    the CommonMark close rule, not a toggle count — so a file with a stray
    fence-lookalike inside a block still counts as balanced.
    """

    def test_readme_fences_are_balanced(self) -> None:
        from grounded.checkers import _fence_scan
        readme = Path(__file__).resolve().parent.parent / "README.md"
        _, open_at = _fence_scan(
            readme.read_text(encoding="utf-8").splitlines())
        self.assertEqual(open_at, 0, "README.md has an unclosed fence")


class TestDocRefPrecision(unittest.TestCase):
    def _doc(self, root, text):
        (root / "guide.md").write_text(text, encoding="utf-8")
        return scan_root(root, Config(enabled={"stale-doc-ref"}))[0]

    def test_diff_annotated_bindings_are_known(self):
        # svelte annotates doc examples with `+++`/`---`. The markers broke
        # identifier extraction (`function add(+++getA, getB+++)` binds
        # nothing), turning bound params into phantom calls.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = self._doc(root,
                "```js\n"
                "function add(+++getA, getB+++) {\n"
                "\treturn +++() => getA() + getB()+++;\n"
                "}\n"
                "```\n")
            self.assertEqual([f for f in out if f.checker == "stale-doc-ref"], [])

    def test_destructured_fixture_param_is_known(self):
        # Playwright fixtures arrive destructured: `({ page }) =>`.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = self._doc(root,
                "```js\n"
                "test('home', async ({ page }) => {\n"
                "\tawait page.goto('/');\n"
                "});\n"
                "```\n")
            self.assertEqual([f for f in out if f.checker == "stale-doc-ref"], [])

    def test_platform_roots_are_ambient(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = self._doc(root,
                "```js\n"
                "customElements.define('x-el', class extends HTMLElement {});\n"
                "```\n")
            self.assertEqual([f for f in out if f.checker == "stale-doc-ref"], [])

    def test_directive_blocks_are_illustrative(self):
        # `// @noErrors` and `/// file:` are doc-tooling directives: the
        # docs themselves declare the code is not project surface.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = self._doc(root,
                "```js\n"
                "// @noErrors\n"
                "preprocess: [\n"
                "\tvitePreprocess(),\n"
                "]\n"
                "```\n")
            self.assertEqual([f for f in out if f.checker == "stale-doc-ref"], [])

    def test_missing_repo_symbol_still_reports(self):
        # Control: an example calling a symbol this repo really lacks.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = self._doc(root,
                "```js\n"
                "const result = vanishedHelper(41);\n"
                "```\n")
            self.assertTrue([f for f in out if f.checker == "stale-doc-ref"])


if __name__ == "__main__":
    unittest.main()
