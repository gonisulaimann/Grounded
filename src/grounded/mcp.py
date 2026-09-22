"""MCP server over stdio (stdlib only): expose grounded to coding agents.

Speaks JSON-RPC 2.0 per the Model Context Protocol (2025-03-26 baseline):
initialize with version negotiation, notifications/initialized, tools/list,
tools/call, ping. Logs go to stderr; stdout carries only MCP messages,
newline-delimited. All filesystem access is confined to --root.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import __version__
from .checkers import CHECKER_DESCRIPTIONS, CHECKERS, REMOVED_CHECKERS
from .models import CheckerError

SUPPORTED_VERSIONS = ("2025-03-26", "2025-06-18", "2024-11-05")
SERVER_NAME = "grounded"


def _tool_defs() -> list[dict]:
    return [
        {
            "name": "check_path",
            "description": ("Scan a directory or file under the server root "
                            "for dangling references in code comments. "
                            "Returns findings with claim, evidence, and fix."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "Path relative to the server root (default: .)"},
                    "fail_on": {"type": "string",
                                "description": "Minimum severity that counts as failing",
                                "enum": ["lie", "drift", "smell", "never"]},
                },
            },
        },
        {
            "name": "explain_checker",
            "description": "Describe what a checker proves (including removed checkers and their replacements).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "checker": {"type": "string",
                                "description": "Checker id, e.g. stale-symbol-ref"},
                },
                "required": ["checker"],
            },
        },
        {
            "name": "blast_radius",
            "description": ("Show everything touching a symbol before renaming it: "
                            "defining files, importing files, and files whose "
                            "comments mention it."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string",
                               "description": "Symbol name, e.g. gettext_lazy"},
                    "path": {"type": "string",
                             "description": "Directory to scan, relative to the server root"},
                },
                "required": ["symbol"],
            },
        },
    ]


def _error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _ok(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


class McpServer:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.initialized = False

    # -- filesystem guard: agents must not read outside the root --------

    def _resolve(self, rel: str) -> Path:
        target = (self.root / (rel or ".")).resolve()
        try:
            target.relative_to(self.root)
        except ValueError:
            raise ValueError(f"path escapes server root: {rel!r}")
        return target

    # -- protocol ---------------------------------------------------------

    def handle(self, msg: dict):
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return _error(msg.get("id") if isinstance(msg, dict) else None,
                          -32600, "invalid JSON-RPC request")
        method = msg.get("method")
        req_id = msg.get("id")
        params = msg.get("params") or {}
        if not isinstance(params, dict):
            return _error(req_id, -32602, "params must be an object")

        if method == "initialize":
            return self._initialize(req_id, params)
        if method == "notifications/initialized":
            self.initialized = True
            return None
        if method == "ping":
            return _ok(req_id, {})
        if method in ("notifications/cancelled",):
            return None
        if not self.initialized and req_id is not None:
            return _error(req_id, -32002, "server not initialized")
        if method == "tools/list":
            return _ok(req_id, {"tools": _tool_defs()})
        if method == "tools/call":
            return self._call(req_id, params)
        if req_id is None:
            return None  # unknown notification: ignore
        return _error(req_id, -32601, f"method not found: {method}")

    def _initialize(self, req_id, params: dict) -> dict:
        want = params.get("protocolVersion", "")
        version = want if want in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        self.initialized = True
        return _ok(req_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
            "instructions": ("Check code comments for dangling references "
                             "before trusting them. Use check_path on edited "
                             "files; fix reported lies before building on them."),
        })

    def _call(self, req_id, params: dict):
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return _error(req_id, -32602, "arguments must be an object")
        if name == "check_path":
            return self._check_path(req_id, args)
        if name == "blast_radius":
            return self._blast_radius(req_id, args)
        if name == "explain_checker":
            return self._explain(req_id, args)
        return _error(req_id, -32602, f"unknown tool: {name}")

    def _check_path(self, req_id, args: dict):
        from .config import Config
        from .scanner import apply_suppressions, scan_root
        try:
            target = self._resolve(str(args.get("path", ".")))
        except ValueError as exc:
            return _error(req_id, -32602, str(exc))
        if not target.exists():
            return _error(req_id, -32602, f"path does not exist: {args.get('path')}")
        root = target if target.is_dir() else target.parent
        fail_on = str(args.get("fail_on", "lie"))
        if fail_on not in ("lie", "drift", "smell", "never"):
            return _error(req_id, -32602, f"bad fail_on: {fail_on}")
        checker_errors: list[CheckerError] = []
        findings, facts, _index = scan_root(root, Config.load(root),
                                           checker_errors=checker_errors)
        facts_by_path = {f.path: f for f in facts}
        findings, n_suppressed = apply_suppressions(findings, facts_by_path)
        from .models import SEVERITY_RANK
        threshold = SEVERITY_RANK.get(fail_on, 3)
        failed = [f for f in findings if SEVERITY_RANK.get(f.severity, 0) >= threshold]
        # An agent acting on `failed: false` must not be reading the result of
        # a checker that died: report the failures explicitly and let them
        # force a failure, so "no findings" is never mistaken for "verified".
        incomplete = bool(checker_errors) and fail_on != "never"
        return _ok(req_id, {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "failed": bool(failed) or incomplete,
                    "incomplete": bool(checker_errors),
                    "checker_errors": [e.to_dict() for e in checker_errors],
                    "summary": {
                        "files": len(facts),
                        "findings": len(findings),
                        "lie": sum(1 for f in findings if f.severity == "lie"),
                        "drift": sum(1 for f in findings if f.severity == "drift"),
                        "smell": sum(1 for f in findings if f.severity == "smell"),
                        "suppressed": n_suppressed,
                        "checker_errors": len(checker_errors),
                    },
                    "findings": [dict(f.to_dict(), fix_hint=f.fix) for f in findings],
                }),
            }],
            "isError": False,
        })

    def _blast_radius(self, req_id, args: dict):
        from .config import Config
        from .graph import ClaimGraph
        from .scanner import scan_root
        try:
            target = self._resolve(str(args.get("path", ".")))
        except ValueError as exc:
            return _error(req_id, -32602, str(exc))
        if not target.exists():
            return _error(req_id, -32602, f"path does not exist: {args.get('path')}")
        symbol = str(args.get("symbol", "")).strip()
        if not symbol:
            return _error(req_id, -32602, "symbol is required")
        root = target if target.is_dir() else target.parent
        _, facts, index = scan_root(root, Config.load(root), include_claim_surfaces=True)
        result = ClaimGraph(index, {f.path: f for f in facts}).blast_radius(symbol)
        return _ok(req_id, {
            "content": [{"type": "text", "text": json.dumps(result)}],
            "isError": False,
        })

    def _explain(self, req_id, args: dict):
        cid = str(args.get("checker", ""))
        if cid in REMOVED_CHECKERS:
            text = f"{cid}: {REMOVED_CHECKERS[cid]}"
        elif cid in CHECKER_DESCRIPTIONS:
            text = f"{cid}: {CHECKER_DESCRIPTIONS[cid]}"
        else:
            return _error(req_id, -32602,
                          f"unknown checker {cid!r}. Known: {', '.join(sorted(CHECKERS))}")
        return _ok(req_id, {"content": [{"type": "text", "text": text}], "isError": False})


def serve(root: Path) -> int:
    server = McpServer(root)
    stdin = sys.stdin
    stdout = sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError as exc:
            stdout.write(json.dumps(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": -32700, "message": f"parse error: {exc}"}}) + "\n")
            stdout.flush()
            continue
        try:
            resp = server.handle(msg)
        except Exception as exc:  # never break the stream on a tool crash
            req_id = msg.get("id") if isinstance(msg, dict) else None
            resp = {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32603, "message": f"internal error: {exc}"}}
        if resp is not None:
            stdout.write(json.dumps(resp) + "\n")
            stdout.flush()
    return 0
