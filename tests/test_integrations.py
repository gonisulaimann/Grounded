"""MCP, LSP, agent configs, the bundled skill, release plumbing, harnesses.

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


class TestReleaseBinaries(unittest.TestCase):
    """The standalone-binary release is a three-way contract: `install.sh`
    derives `grounded-${OS}-${ARCH}` from `uname`, `release-binaries.yml`
    publishes exactly those names, and `verify-release.yml` audits them. On
    2026-09-22 three releases shipped three of four assets because the
    darwin-amd64 leg asked for the retired `macos-13` image and stayed queued
    forever instead of failing; with a missing Intel asset, the advertised
    one-liner 404'd on Intel Macs and blamed the network. These pin the
    invariants that let that gap stay invisible."""

    def _root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    def _workflow(self, name: str) -> str:
        return (self._root() / ".github" / "workflows" / name).read_text(encoding="utf-8")

    def _assets(self, text: str) -> set[str]:
        import re
        return set(
            re.findall(r"grounded-(?:darwin|linux|windows)-(?:arm64|amd64)(?:\.exe)?", text)
        )

    def test_producer_and_auditor_agree_on_the_asset_set(self) -> None:
        produced = self._assets(self._workflow("release-binaries.yml"))
        audited = self._assets(self._workflow("verify-release.yml"))
        self.assertEqual(produced, audited)
        self.assertEqual(
            produced,
            {
                "grounded-linux-amd64",
                "grounded-windows-amd64.exe",
                "grounded-darwin-arm64",
                "grounded-darwin-amd64",
            },
        )

    def test_no_dated_macos_runner_in_the_binary_matrix(self) -> None:
        # A job pointed at a retired image does not fail — it stays queued
        # forever, so the workflow never goes red. Every dated macOS image is
        # retired eventually, so the matrix must use the rolling label.
        import re
        text = self._workflow("release-binaries.yml")
        dated = re.findall(r"(?:runs-on:\s*|os:\s*)(macos-\d+)\b", text)
        self.assertEqual(dated, [], f"dated macOS runner images queue forever: {dated}")
        self.assertIn("macos-latest", text)

    def test_macos_binary_is_universal2_gated(self) -> None:
        # One fat binary serves both darwin names; the gate is what stops an
        # arm64-only build from ever being published under the amd64 name.
        text = self._workflow("release-binaries.yml")
        self.assertIn("--target-arch universal2", text)
        self.assertIn("ARCH_FLAG", text)
        self.assertIn("lipo -archs", text)

    def test_a_stuck_leg_is_audited_outside_the_producing_workflow(self) -> None:
        # A queued job cannot report on itself, so the audit runs in a separate
        # workflow, on a schedule as well as on the release event, and reaches
        # an issue rather than a red run nobody reads.
        text = self._workflow("verify-release.yml")
        self.assertIn("release:", text)
        self.assertIn("schedule:", text)
        self.assertIn("failure()", text)

    def test_installer_never_advertises_an_unpublished_platform(self) -> None:
        import re
        sh = (self._root() / "install.sh").read_text(encoding="utf-8")
        arches = set(re.findall(r'ARCH="([a-z0-9_]+)"', sh))
        self.assertEqual(arches, {"amd64", "arm64"}, arches)
        produced = self._assets(self._workflow("release-binaries.yml"))
        for arch in arches:  # both macOS architectures must resolve
            self.assertIn(f"grounded-darwin-{arch}", produced)
        for osname, arch in re.findall(r"\b(linux|darwin)/(amd64|arm64)\b", sh):
            self.assertIn(f"grounded-{osname}-{arch}", produced)


class TestMcp(unittest.TestCase):
    def _server(self, root: Path):
        from grounded.mcp import McpServer
        return McpServer(root)

    def _handshake(self, server):
        init = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": "2025-03-26",
                                         "capabilities": {},
                                         "clientInfo": {"name": "t", "version": "0"}}})
        self.assertEqual(init["result"]["protocolVersion"], "2025-03-26")
        self.assertIn("tools", init["result"]["capabilities"])
        self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_full_session(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text("# Calls `ghost_fn()`.\nX = 1\n", encoding="utf-8")
            server = self._server(root)
            self._handshake(server)
            tools = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            names = {t["name"] for t in tools["result"]["tools"]}
            self.assertEqual(names, {"check_path", "explain_checker", "blast_radius", "check_text"})
            resp = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                  "params": {"name": "check_path", "arguments": {"path": "."}}})
            payload = json.loads(resp["result"]["content"][0]["text"])
            self.assertTrue(payload["failed"])
            self.assertEqual(payload["summary"]["lie"], 1)
            self.assertIn("ghost_fn", payload["findings"][0]["title"])
            exp = server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                 "params": {"name": "explain_checker",
                                            "arguments": {"checker": "stale-symbol-ref"}}})
            self.assertIn("stale-symbol-ref", exp["result"]["content"][0]["text"])

    def test_version_negotiation_and_errors(self):
        with tempfile.TemporaryDirectory() as td:
            server = self._server(Path(td))
            old = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                 "params": {"protocolVersion": "1999-01-01", "capabilities": {},
                                            "clientInfo": {"name": "t", "version": "0"}}})
            self.assertEqual(old["result"]["protocolVersion"], "2025-03-26")
            self.assertEqual(
                server.handle({"jsonrpc": "2.0", "id": 2, "method": "nope"}),
                {"jsonrpc": "2.0", "id": 2,
                 "error": {"code": -32601, "message": "method not found: nope"}})
            self.assertEqual(
                server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                               "params": {"name": "nope", "arguments": {}}})["error"]["code"],
                -32602)

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            server = self._server(Path(td))
            self._handshake(server)
            resp = server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                  "params": {"name": "check_path", "arguments": {"path": ".."}}})
            self.assertEqual(resp["error"]["code"], -32602)

    def test_check_text_resolves_claims(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pkg").mkdir()
            (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
            (root / "pkg" / "core.py").write_text(
                "def get_account(uid):\n    return uid\n", encoding="utf-8")
            server = self._server(root)
            self._handshake(server)
            resp = server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                  "params": {"name": "check_text",
                                             "arguments": {
                                                 "path": ".",
                                                 "text": ("rename to `get_account()` per "
                                                          "pkg/core.py; drop `ghost_fn()`; "
                                                          "see pkg/gone.py") }}})
            payload = json.loads(resp["result"]["content"][0]["text"])
            by_claim = {c["claim"]: c["verdict"] for c in payload["claims"]}
            self.assertEqual(by_claim["`get_account()`"], "known")
            self.assertEqual(by_claim["`ghost_fn()`"], "unknown")
            self.assertEqual(by_claim["pkg/core.py"], "known")
            self.assertEqual(by_claim["pkg/gone.py"], "unknown")
            self.assertEqual(payload["unknown"], 2)
            bad = server.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                                 "params": {"name": "check_text",
                                            "arguments": {"path": ".", "text": "  "}}})
            self.assertEqual(bad["error"]["code"], -32602)

    def test_stdio_transport_roundtrip(self):
        import os
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text("X = 1\n", encoding="utf-8")
            repo = Path(__file__).resolve().parent.parent
            env = dict(os.environ)
            env["PYTHONPATH"] = str(repo / "src") + os.pathsep + env.get("PYTHONPATH", "")
            proc = subprocess.run(
                [sys.executable, "-m", "grounded.cli", "mcp", "--root", str(root)],
                input=('{"jsonrpc":"2.0","id":1,"method":"initialize",'
                       '"params":{"protocolVersion":"2025-03-26","capabilities":{},'
                       '"clientInfo":{"name":"t","version":"0"}}}\n'
                       '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
                       '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'),
                capture_output=True, text=True, timeout=120, env=env,
                cwd=str(Path(__file__).resolve().parent.parent))
            self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
            lines = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip()]
            self.assertEqual(lines[0]["result"]["serverInfo"]["name"], "grounded")
            self.assertEqual({t["name"] for t in lines[1]["result"]["tools"]},
                             {"check_path", "explain_checker", "blast_radius",
                              "check_text"})
            self.assertNotIn("Traceback", proc.stderr)


class TestLsp(unittest.TestCase):
    def _framed_session(self, root: Path, messages: list[dict]) -> list[dict]:
        """Drive the server with Content-Length framing, return responses."""
        import os
        import subprocess
        import sys
        repo = Path(__file__).resolve().parent.parent
        env = dict(os.environ)
        env["PYTHONPATH"] = str(repo / "src") + os.pathsep + env.get("PYTHONPATH", "")
        payload = b""
        for m in messages:
            body = json.dumps(m).encode()
            payload += b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        proc = subprocess.run(
            [sys.executable, "-m", "grounded.cli", "lsp"],
            input=payload, capture_output=True, timeout=120, env=env, cwd=str(repo))
        self.assertEqual(proc.returncode, 0, proc.stderr.decode()[-500:])
        out, responses = proc.stdout, []
        while True:
            head, sep, rest = out.partition(b"\r\n\r\n")
            if not sep:
                break
            length = 0
            for ln in head.decode().split("\r\n"):
                if ln.lower().startswith("content-length:"):
                    length = int(ln.split(":")[1])
            responses.append(json.loads(rest[:length].decode()))
            out = rest[length:]
        self.assertNotIn("Traceback", proc.stderr.decode())
        return responses

    def test_full_session(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            uri = root.as_uri() + "/a.py"
            text = "# Calls `ghost_fn()`.\nX = 1\n"
            rs = self._framed_session(root, [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"rootUri": root.as_uri(), "capabilities": {}}},
                {"jsonrpc": "2.0", "method": "initialized", "params": {}},
                {"jsonrpc": "2.0", "method": "textDocument/didOpen",
                 "params": {"textDocument": {"uri": uri, "languageId": "python",
                                             "version": 1, "text": text}}},
            ])
            init = next(r for r in rs if r.get("id") == 1)
            self.assertIn("codeActionProvider", init["result"]["capabilities"])
            pubs = [r for r in rs if r.get("method") == "textDocument/publishDiagnostics"]
            self.assertEqual(len(pubs), 1)
            diags = pubs[0]["params"]["diagnostics"]
            self.assertEqual(len(diags), 1)
            self.assertEqual(diags[0]["severity"], 1)
            self.assertEqual(diags[0]["code"], "stale-symbol-ref")
            self.assertEqual(diags[0]["source"], "grounded")

    def test_code_action_and_heal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "real.py").write_text("def ghost_fix_target():\n    pass\n", encoding="utf-8")
            uri = root.as_uri() + "/a.py"
            text = "# Calls `ghost_fixtarget()`.\nX = 1\n"
            rs = self._framed_session(root, [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"rootUri": root.as_uri(), "capabilities": {}}},
                {"jsonrpc": "2.0", "method": "textDocument/didOpen",
                 "params": {"textDocument": {"uri": uri, "languageId": "python",
                                             "version": 1, "text": text}}},
            ])
            diag = next(r for r in rs if r.get("method") == "textDocument/publishDiagnostics")
            d = diag["params"]["diagnostics"][0]
            rs2 = self._framed_session(root, [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"rootUri": root.as_uri(), "capabilities": {}}},
                {"jsonrpc": "2.0", "method": "textDocument/didOpen",
                 "params": {"textDocument": {"uri": uri, "languageId": "python",
                                             "version": 1, "text": text}}},
                {"jsonrpc": "2.0", "id": 2, "method": "textDocument/codeAction",
                 "params": {"textDocument": {"uri": uri},
                            "range": d["range"],
                            "context": {"diagnostics": [d]}}},
                {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
                {"jsonrpc": "2.0", "method": "exit"},
            ])
            acts = next(r for r in rs2 if r.get("id") == 2)["result"]
            self.assertEqual(len(acts), 1)
            self.assertEqual(acts[0]["kind"], "quickfix")
            edit = acts[0]["edit"]["changes"][uri][0]
            self.assertIn("ghost_fix_target", edit["newText"])
            healed = text.replace("ghost_fixtarget", "ghost_fix_target")
            rs3 = self._framed_session(root, [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"rootUri": root.as_uri(), "capabilities": {}}},
                {"jsonrpc": "2.0", "method": "textDocument/didChange",
                 "params": {"textDocument": {"uri": uri, "version": 2},
                            "contentChanges": [{"text": healed}]}},
            ])
            pubs = [r for r in rs3 if r.get("method") == "textDocument/publishDiagnostics"]
            self.assertEqual(pubs[0]["params"]["diagnostics"], [])

    def test_unknown_method_and_shutdown(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rs = self._framed_session(root, [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"rootUri": root.as_uri(), "capabilities": {}}},
                {"jsonrpc": "2.0", "id": 2, "method": "nope/method"},
                {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
                {"jsonrpc": "2.0", "method": "exit"},
            ])
            err = next(r for r in rs if r.get("id") == 2)
            self.assertEqual(err["error"]["code"], -32601)
            bye = next(r for r in rs if r.get("id") == 3)
            self.assertEqual(bye["result"], None)

    def test_buffer_rename_invalidates_peer(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "models.py").write_text("class UserProfile:\n    pass\n", encoding="utf-8")
            (root / "views.py").write_text("# Uses `UserProfile()`.\nX = 1\n", encoding="utf-8")
            v_uri = root.as_uri() + "/views.py"
            m_uri = root.as_uri() + "/models.py"
            rs = self._framed_session(root, [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"rootUri": root.as_uri(), "capabilities": {}}},
                {"jsonrpc": "2.0", "method": "textDocument/didOpen",
                 "params": {"textDocument": {"uri": v_uri, "languageId": "python",
                                             "version": 1,
                                             "text": "# Uses `UserProfile()`.\nX = 1\n"}}},
                {"jsonrpc": "2.0", "method": "textDocument/didChange",
                 "params": {"textDocument": {"uri": m_uri, "version": 2},
                            "contentChanges": [{"text": "class AccountProfile:\n    pass\n"}]}},
                {"jsonrpc": "2.0", "method": "textDocument/didChange",
                 "params": {"textDocument": {"uri": v_uri, "version": 2},
                            "contentChanges": [{"text": "# Uses `UserProfile()`.\nX = 1\n"}]}},
            ])
            pubs = [r for r in rs if r.get("method") == "textDocument/publishDiagnostics"]
            first = [p for p in pubs if p["params"]["uri"].endswith("views.py")][0]
            self.assertEqual(first["params"]["diagnostics"], [])
            last = [p for p in pubs if p["params"]["uri"].endswith("views.py")][-1]
            self.assertEqual(len(last["params"]["diagnostics"]), 1)
            self.assertEqual(last["params"]["diagnostics"][0]["code"], "stale-symbol-ref")

    def test_close_reverts_to_disk(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "models.py").write_text("class UserProfile:\n    pass\n", encoding="utf-8")
            (root / "views.py").write_text("# Uses `UserProfile()`.\nX = 1\n", encoding="utf-8")
            v_uri = root.as_uri() + "/views.py"
            m_uri = root.as_uri() + "/models.py"
            rs = self._framed_session(root, [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"rootUri": root.as_uri(), "capabilities": {}}},
                {"jsonrpc": "2.0", "method": "textDocument/didOpen",
                 "params": {"textDocument": {"uri": v_uri, "languageId": "python",
                                             "version": 1,
                                             "text": "# Uses `UserProfile()`.\nX = 1\n"}}},
                {"jsonrpc": "2.0", "method": "textDocument/didChange",
                 "params": {"textDocument": {"uri": m_uri, "version": 2},
                            "contentChanges": [{"text": "class AccountProfile:\n    pass\n"}]}},
                {"jsonrpc": "2.0", "method": "textDocument/didClose",
                 "params": {"textDocument": {"uri": m_uri}}},
                {"jsonrpc": "2.0", "method": "textDocument/didChange",
                 "params": {"textDocument": {"uri": v_uri, "version": 3},
                            "contentChanges": [{"text": "# Uses `UserProfile()`.\nX = 1\n"}]}},
            ])
            pubs = [r for r in rs if r.get("method") == "textDocument/publishDiagnostics"]
            last = [p for p in pubs if p["params"]["uri"].endswith("views.py")][-1]
            self.assertEqual(last["params"]["diagnostics"], [])

    def test_broken_buffer_keeps_diagnostics(self):
        # Mid-typing syntax error: diagnostics degrade, never vanish.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text("X = 1\n", encoding="utf-8")
            uri = root.as_uri() + "/a.py"
            rs = self._framed_session(root, [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"rootUri": root.as_uri(), "capabilities": {}}},
                {"jsonrpc": "2.0", "method": "textDocument/didOpen",
                 "params": {"textDocument": {"uri": uri, "languageId": "python",
                                             "version": 1,
                                             "text": "# Calls `ghost_fn()`.\nX = 1\n"}}},
                {"jsonrpc": "2.0", "method": "textDocument/didChange",
                 "params": {"textDocument": {"uri": uri, "version": 2},
                            "contentChanges": [{"text": "# Calls `ghost_fn()`.\ndef broken(:\n"}]}},
            ])
            pubs = [r for r in rs if r.get("method") == "textDocument/publishDiagnostics"]
            self.assertTrue(all(len(p["params"]["diagnostics"]) == 1 for p in pubs))


class TestInitAgent(unittest.TestCase):
    def test_all_three_fresh(self):
        import json
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            cwd, target = Path.cwd(), Path(td)
            import os
            os.chdir(target)
            try:
                self.assertEqual(main(["init-agent"]), 0)
                settings = json.loads((target / ".claude" / "settings.json").read_text())
                cmds = [h.get("command")
                        for e in settings["hooks"]["PostToolUse"] for h in e.get("hooks", [])]
                self.assertIn("grounded hook claude-code", cmds)
                mdc = (target / ".cursor" / "rules" / "grounded.mdc").read_text()
                self.assertIn("alwaysApply: false", mdc)
                self.assertIn("description:", mdc)
                self.assertIn("lint-cmd", (target / ".aider.conf.yml").read_text())
            finally:
                os.chdir(cwd)

    def test_idempotent_and_merging(self):
        import json
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            (target / ".claude").mkdir()
            (target / ".claude" / "settings.json").write_text(
                json.dumps({"hooks": {"PostToolUse": [
                    {"matcher": "Bash",
                     "hooks": [{"type": "command", "command": "other"}]}]}}),
                encoding="utf-8")
            import os
            cwd = Path.cwd()
            os.chdir(target)
            try:
                self.assertEqual(main(["init-agent", "--claude"]), 0)
                self.assertEqual(main(["init-agent", "--claude"]), 0)
                settings = json.loads((target / ".claude" / "settings.json").read_text())
                cmds = [h.get("command")
                        for e in settings["hooks"]["PostToolUse"] for h in e.get("hooks", [])]
                self.assertIn("other", cmds)
                self.assertEqual(cmds.count("grounded hook claude-code"), 1)
            finally:
                os.chdir(cwd)

    def test_invalid_json_refused(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            (target / ".claude").mkdir()
            (target / ".claude" / "settings.json").write_text("{nope", encoding="utf-8")
            import os
            cwd = Path.cwd()
            os.chdir(target)
            try:
                self.assertEqual(main(["init-agent", "--claude"]), 0)
                self.assertEqual((target / ".claude" / "settings.json").read_text(), "{nope")
            finally:
                os.chdir(cwd)

    def test_existing_files_kept_without_force(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            (target / ".cursor" / "rules").mkdir(parents=True)
            (target / ".cursor" / "rules" / "grounded.mdc").write_text("mine\n", encoding="utf-8")
            (target / ".aider.conf.yml").write_text("lint: true\n", encoding="utf-8")
            import os
            cwd = Path.cwd()
            os.chdir(target)
            try:
                self.assertEqual(main(["init-agent", "--cursor", "--aider"]), 0)
                self.assertEqual(
                    (target / ".cursor" / "rules" / "grounded.mdc").read_text(), "mine\n")
                self.assertEqual((target / ".aider.conf.yml").read_text(), "lint: true\n")
                self.assertEqual(
                    main(["init-agent", "--cursor", "--aider", "--force"]), 0)
                self.assertNotEqual(
                    (target / ".cursor" / "rules" / "grounded.mdc").read_text(), "mine\n")
            finally:
                os.chdir(cwd)

    def test_skill_project_installs_and_keeps(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            import os
            cwd = Path.cwd()
            os.chdir(target)
            try:
                self.assertEqual(main(["init-agent", "--skill-project"]), 0)
                dest = target / ".claude" / "skills" / "grounded"
                self.assertTrue((dest / "SKILL.md").exists())
                self.assertTrue((dest / "references" / "rules.md").exists())
                self.assertTrue((dest / "references" / "commands.md").exists())
                self.assertTrue((dest / "examples" / "sessions.md").exists())
                (dest / "SKILL.md").write_text("mine\n", encoding="utf-8")
                self.assertEqual(main(["init-agent", "--skill-project"]), 0)
                self.assertEqual((dest / "SKILL.md").read_text(), "mine\n")
                self.assertEqual(main(["init-agent", "--skill-project", "--force"]), 0)
                self.assertNotEqual((dest / "SKILL.md").read_text(), "mine\n")
            finally:
                os.chdir(cwd)

    def test_skill_user_dir_uses_home(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            target, home = Path(td) / "proj", Path(td) / "home"
            target.mkdir()
            import os
            cwd, old_home = Path.cwd(), os.environ.get("HOME")
            os.environ["HOME"] = str(home)
            os.chdir(target)
            try:
                self.assertEqual(main(["init-agent", "--skill"]), 0)
                dest = home / ".claude" / "skills" / "grounded"
                self.assertTrue((dest / "SKILL.md").exists())
                self.assertFalse((target / ".claude" / "skills").exists())
            finally:
                os.chdir(cwd)
                if old_home is None:
                    del os.environ["HOME"]
                else:
                    os.environ["HOME"] = old_home

    def test_skill_dry_run_writes_nothing(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            target, home = Path(td) / "proj", Path(td) / "home"
            target.mkdir()
            import os
            cwd, old_home = Path.cwd(), os.environ.get("HOME")
            os.environ["HOME"] = str(home)
            os.chdir(target)
            try:
                self.assertEqual(
                    main(["init-agent", "--skill", "--skill-project", "--dry-run"]), 0)
                self.assertFalse((target / ".claude").exists())
                self.assertFalse((home / ".claude").exists())
            finally:
                os.chdir(cwd)
                if old_home is None:
                    del os.environ["HOME"]
                else:
                    os.environ["HOME"] = old_home

    def test_bare_init_agent_touches_no_skill(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            target, home = Path(td) / "proj", Path(td) / "home"
            target.mkdir()
            import os
            cwd, old_home = Path.cwd(), os.environ.get("HOME")
            os.environ["HOME"] = str(home)
            os.chdir(target)
            try:
                self.assertEqual(main(["init-agent"]), 0)
                self.assertFalse((target / ".claude" / "skills").exists())
                self.assertFalse((home / ".claude").exists())
            finally:
                os.chdir(cwd)
                if old_home is None:
                    del os.environ["HOME"]
                else:
                    os.environ["HOME"] = old_home

    def test_precommit_install_keeps_force_dryrun(self):
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            import os
            cwd = Path.cwd()
            os.chdir(target)
            try:
                self.assertEqual(main(["init-agent", "--pre-commit"]), 0)
                text = (target / ".pre-commit-config.yaml").read_text()
                self.assertIn("gonisulaimann/Grounded", text)
                self.assertIn("- id: grounded", text)
                # Both first-party hooks are offered by default.
                self.assertIn("- id: grounded-fences", text)
                (target / ".pre-commit-config.yaml").write_text("mine\n", encoding="utf-8")
                self.assertEqual(main(["init-agent", "--pre-commit"]), 0)
                self.assertEqual(
                    (target / ".pre-commit-config.yaml").read_text(), "mine\n")
                self.assertEqual(
                    main(["init-agent", "--pre-commit", "--force", "--dry-run"]), 0)
            finally:
                os.chdir(cwd)


class TestSkillSync(unittest.TestCase):
    """`agent-skill/` is generated from `src/grounded/skill/`, not maintained.

    `src/grounded/skill/` is the source of truth (it is what
    `init-agent --skill` installs and what `package-data` ships in the wheel);
    the top-level directory exists so the skill stays browsable and
    `cp -r`-able from the repository. A test that only compared the two trees
    told a maintainer *that* they had drifted, never how to fix it, and left
    every doc correction to be typed twice.
    """

    def _repo(self) -> Path:
        return Path(__file__).resolve().parent.parent

    def _run(self, *args: str) -> "subprocess.CompletedProcess":
        import subprocess
        script = self._repo() / "scripts" / "sync-skill.py"
        return subprocess.run([sys.executable, str(script), *args],
                              capture_output=True, text=True)

    def test_mirror_is_in_sync_with_its_source(self) -> None:
        proc = self._run("--check")
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def test_drift_is_detected_then_repaired(self) -> None:
        repo = self._repo()
        source = repo / "src" / "grounded" / "skill"
        with tempfile.TemporaryDirectory() as td:
            mirror = Path(td) / "agent-skill"
            # control: a missing mirror is drift, and says what is missing
            empty = self._run("--check", "--source", str(source), "--mirror", str(mirror))
            self.assertEqual(empty.returncode, 1)
            self.assertIn("SKILL.md", empty.stderr)
            # generating repairs it, and a re-check is clean
            self.assertEqual(
                self._run("--source", str(source), "--mirror", str(mirror)).returncode, 0)
            self.assertEqual(
                self._run("--check", "--source", str(source), "--mirror", str(mirror)).returncode, 0)
            # a file the source no longer has is drift too, and is pruned
            stale = mirror / "references" / "gone.md"
            stale.write_text("removed upstream\n", encoding="utf-8")
            self.assertEqual(
                self._run("--check", "--source", str(source), "--mirror", str(mirror)).returncode, 1)
            self._run("--source", str(source), "--mirror", str(mirror))
            self.assertFalse(stale.exists())

    def test_skill_front_matter_and_examples_shipped(self) -> None:
        repo = self._repo()
        for rel in ("agent-skill", "src/grounded/skill"):
            skill = repo / rel / "SKILL.md"
            self.assertTrue(skill.exists(), rel)
            self.assertIn("name: grounded", skill.read_text().splitlines()[1])
        self.assertTrue((repo / "src/grounded/skill" / "examples").is_dir())


class TestRecallHarness(unittest.TestCase):
    """`bench/recall.py` measures recall inside real repos, so the planting
    itself must never decide the outcome.

    Two artifacts were measured on 2026-09-22 while building it, both of which
    first reported as recall losses the checkers never caused:

    * a case planted one directory deeper stopped firing, because three cases
      depend on repo-root-relative semantics (`src/` layout, `@patch` module
      roots, a top-level `pyproject.toml`);
    * a fixture merged into a host whose Markdown ends inside an unclosed fence
      landed *inside* that dangling block, so `stale-cli-ref` could not parse
      the invocation as one. This repo's own `README.md` had exactly that
      defect, so the phantom miss was not hypothetical.

    A published recall number is only meaningful if the harness can show the
    rot was planted in a well-formed context; the second case is pinned here.
    """

    def _recall(self):
        import importlib.util
        path = Path(__file__).resolve().parent.parent / "bench" / "recall.py"
        spec = importlib.util.spec_from_file_location("bench_recall", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _host(self, readme: str):
        td = tempfile.TemporaryDirectory()
        host = Path(td.name) / "host"
        host.mkdir()
        (host / "README.md").write_text(readme, encoding="utf-8")
        return td, host

    def test_plant_survives_an_unclosed_host_fence(self) -> None:
        recall = self._recall()
        original = "# Host\n\n```console\ngrounded scan .\n"  # opened, never closed
        td, host = self._host(original)
        with td:
            self.assertTrue(recall.ends_inside_fence(original))
            report = recall.run_repo(host, recall.firing_cases(["cli-stale"]))
            self.assertEqual([r["outcome"] for r in report["results"]], ["caught"],
                             report["results"])
            # the host's own defect is surfaced, never silently absorbed
            self.assertEqual(report["unbalanced_hosts"], ["README.md"])
            self.assertEqual(report["checker_errors"], [])
            # and a measured repo is left exactly as it was found
            self.assertEqual((host / "README.md").read_text(encoding="utf-8"),
                             original)

    def test_balanced_host_merges_without_closing_anything(self) -> None:
        recall = self._recall()
        td, host = self._host("# Host\n\n```console\ngrounded scan .\n```\n")
        with td:
            report = recall.run_repo(host, recall.firing_cases(["cli-stale"]))
            self.assertEqual([r["outcome"] for r in report["results"]], ["caught"])
            self.assertEqual(report["unbalanced_hosts"], [])

    def test_merged_expectation_line_numbers_translate(self) -> None:
        # Expectations that embed fixture line numbers (a title like
        # "swallowed by the block opened at line <N>") must shift by the
        # plant offset, or a merge into a non-empty host reports a phantom
        # title miss. The host here contributes 3 content lines + 2
        # separator lines, so the fixture's seventh line lands at twelve —
        # judged caught there, not a miss with "title changed".
        recall = self._recall()
        td, host = self._host("# Host\n\nSome intro prose.\n")
        with td:
            report = recall.run_repo(
                host, recall.firing_cases(["fence-bare-outer-boundary"]))
            r = report["results"][0]
            self.assertEqual(r["outcome"], "caught", report["results"])
            self.assertEqual(r["expected_line"], 12, report["results"])
            self.assertEqual(r["observed_line"], 12, report["results"])
            self.assertEqual(r["detail"],
                             "merged into the host's own file", report["results"])


class TestClaudeCodeHook(unittest.TestCase):
    """The hook must exit 2 (stderr reaches the model) on lies in the
    agent's edit, 0 when clean, and 1 (human-only) on its own failures."""

    def _git(self, root: Path, *args: str) -> None:
        import subprocess
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                       env={**__import__("os").environ, "GIT_AUTHOR_NAME": "t",
                            "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                            "GIT_COMMITTER_EMAIL": "t@t"})

    def _event(self, root: Path, rel: str) -> str:
        return json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Edit",
                           "cwd": str(root), "tool_input": {"file_path": rel}})

    def test_rename_fallout_in_other_file_blocks(self):
        from grounded.hooks import claude_code
        if shutil.which("git") is None:
            self.skipTest("git not installed")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pyproject.toml").write_text('[project]\nname = "p"\n', encoding="utf-8")
            (root / "app").mkdir()
            (root / "app" / "__init__.py").write_text("", encoding="utf-8")
            (root / "app" / "core.py").write_text("def fetch_user():\n    return 1\n", encoding="utf-8")
            (root / "app" / "views.py").write_text("from app.core import fetch_user\n", encoding="utf-8")
            self._git(root, "init", "-q")
            self._git(root, "add", "-A")
            self._git(root, "commit", "-qm", "init")
            (root / "app" / "core.py").write_text("def load_user():\n    return 1\n", encoding="utf-8")
            code, err = claude_code(self._event(root, "app/core.py"))
            self.assertEqual(code, 2, err)
            self.assertIn("views.py", err)
            self.assertIn("fetch_user", err)

    def test_untouched_rot_does_not_nag(self):
        from grounded.hooks import claude_code
        if shutil.which("git") is None:
            self.skipTest("git not installed")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text("# Calls `ghost_fn()` for retries.\nX = 1\n", encoding="utf-8")
            self._git(root, "init", "-q")
            self._git(root, "add", "-A")
            self._git(root, "commit", "-qm", "init")
            (root / "a.py").write_text("# Calls `ghost_fn()` for retries.\nX = 2\n", encoding="utf-8")
            self.assertEqual(claude_code(self._event(root, "a.py")), (0, ""))

    def test_no_git_checks_the_edited_file(self):
        from grounded.hooks import claude_code
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text("# Calls `ghost_fn()` for retries.\nX = 1\n", encoding="utf-8")
            (root / "b.py").write_text("# Calls `other_ghost()` for retries.\nY = 1\n", encoding="utf-8")
            code, err = claude_code(self._event(root, str(root / "a.py")))
            self.assertEqual(code, 2)
            self.assertIn("ghost_fn", err)
            self.assertNotIn("other_ghost", err)

    def test_clean_edit_and_bad_payloads(self):
        from grounded.hooks import claude_code
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "ok.py").write_text("X = 1\n", encoding="utf-8")
            self.assertEqual(claude_code(self._event(root, "ok.py")), (0, ""))
            self.assertEqual(claude_code(self._event(root, "gone.py")), (0, ""))
        self.assertEqual(claude_code("not json")[0], 1)
        self.assertEqual(claude_code("[]")[0], 1)
        self.assertEqual(claude_code(json.dumps({"tool_input": {}})), (0, ""))

    def test_init_agent_upgrades_legacy_hook(self):
        import os
        from grounded.cli import main
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            (target / ".claude").mkdir()
            (target / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"PostToolUse": [
                {"matcher": "Edit|Write", "hooks": [
                    {"type": "command", "command": "grounded scan . --changed --quiet"}]}]}}),
                encoding="utf-8")
            cwd = Path.cwd()
            os.chdir(target)
            try:
                self.assertEqual(main(["init-agent", "--claude"]), 0)
            finally:
                os.chdir(cwd)
            post = json.loads((target / ".claude" / "settings.json").read_text())["hooks"]["PostToolUse"]
            self.assertEqual(len(post), 1)
            self.assertEqual(post[0]["hooks"][0]["command"], "grounded hook claude-code")
            self.assertEqual(post[0]["matcher"], "Edit|Write|MultiEdit")


class TestCheckText(unittest.TestCase):
    def _index(self, root: Path):
        (root / "pkg").mkdir()
        (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (root / "pkg" / "core.py").write_text(
            "def get_account(uid):\n    return uid\n", encoding="utf-8")
        _, _, index = scan_root(root, Config())
        return index

    def test_known_and_unknown(self):
        from grounded.checkers.query import check_text_claims
        with tempfile.TemporaryDirectory() as td:
            index = self._index(Path(td))
            out = {c["claim"]: c["verdict"] for c in check_text_claims(
                "Call `get_account()` per pkg/core.py; avoid `ghost_fn()`.", index)}
            self.assertEqual(out["`get_account()`"], "known")
            self.assertEqual(out["pkg/core.py"], "known")
            self.assertEqual(out["`ghost_fn()`"], "unknown")

    def test_prose_is_not_claims(self):
        from grounded.checkers.query import check_text_claims
        with tempfile.TemporaryDirectory() as td:
            index = self._index(Path(td))
            out = check_text_claims(
                "For example, call foo() or bar() with something.", index)
            self.assertEqual(out, [])

    def test_unknown_suggests(self):
        from grounded.checkers.query import check_text_claims
        with tempfile.TemporaryDirectory() as td:
            index = self._index(Path(td))
            out = check_text_claims("Call `get_acount()`.", index)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["verdict"], "unknown")
            self.assertIn("get_account", out[0]["detail"])


if __name__ == "__main__":
    unittest.main()
