"""Repository-wide index: symbols and files for cross-reference checks."""
from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .index_cache import IndexCache

_JS_FUNC_PATTERNS = [
    re.compile(r"^\s*function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\("),
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\("),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][A-Za-z0-9_$]*)\s*=>"),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?function\b"),
    re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)\b"),
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?([A-Za-z_$][A-Za-z0-9_$]*)\s*\([^)]*\)\s*\{"),
    re.compile(r"^\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*:\s*(?:async\s*)?function\b"),
    re.compile(r"^\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*:\s*(?:async\s*)?\([^)]*\)\s*=>"),
    re.compile(r"^\s*export\s+default\s+(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\("),
    re.compile(r"^\s*module\.exports\.([A-Za-z_$][A-Za-z0-9_$]*)\s*="),
    re.compile(r"^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_$][A-Za-z0-9_$]*)\b"),
]

_JS_METHOD_HINT = re.compile(r"^\s*(?:async\s+|static\s+|get\s+|set\s+)?([A-Za-z_$][A-Za-z0-9_$]*)\s*\(")


def _walkup_tops(root: Path) -> set[str]:
    """First-party top segments above the scan root.

    Finds the nearest ancestor (inclusive) containing pyproject.toml,
    package.json, or .git and collects importable top names there only:
    `<pkg>/` dirs containing `.py` files, `<pkg>.py` files, and the same
    under `src/` and `lib/` prefixes. No marker anywhere up to the
    filesystem root means no evidence: empty set, never guessed.
    Presence-only, read once at build: names here suppress "undeclared",
    never resolve symbols.
    """
    cur = root.resolve()
    project: Path | None = None
    while True:
        if ((cur / "pyproject.toml").exists() or (cur / "package.json").exists()
                or (cur / ".git").exists()):
            project = cur
            break
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    if project is None:
        return set()
    tops: set[str] = set()

    def harvest(d: Path) -> None:
        try:
            children = list(d.iterdir())
        except OSError:
            return
        for child in children:
            if child.name in (".git", "__pycache__", "node_modules", ".venv"):
                continue
            if child.is_dir():
                try:
                    inner = list(child.iterdir())
                except OSError:
                    continue
                if any(f.suffix == ".py" for f in inner if f.is_file()):
                    tops.add(child.name)
            elif child.suffix == ".py":
                tops.add(child.stem)

    harvest(project)
    for prefix in ("src", "lib"):
        sub = project / prefix
        if sub.is_dir():
            harvest(sub)
    return tops


def _root_package_names(root: Path) -> set[str]:
    """The `name` field of the root package.json, if present."""
    try:
        data = json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if isinstance(data, dict) and isinstance(data.get("name"), str):
        return {data["name"]}
    return set()


_FALLBACK_DEF = re.compile(r"^(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)")
_FALLBACK_CLASS = re.compile(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)")
_FALLBACK_ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=")
_FALLBACK_TRIPLE = re.compile(r'("""|\'\'\')[\s\S]*?\1')


def _fallback_top_level(text: str) -> set[str]:
    """Top-level def/class/assign names from unparseable Python.

    Heuristic of last resort: triple-quoted regions are blanked first
    (a col-0 `def` inside a docstring must not become a binding), then
    only column-0 definitions count. Over-approximation only ever
    suppresses findings, never invents them; the file stays opaque
    regardless (see parse_failed).
    """
    names: set[str] = set()
    scrubbed = _FALLBACK_TRIPLE.sub("", text)
    for line in scrubbed.splitlines():
        m = _FALLBACK_DEF.match(line) or _FALLBACK_CLASS.match(line)
        if m:
            names.add(m.group(1))
            continue
        m = _FALLBACK_ASSIGN.match(line)
        if m and m.group(1) not in ("if", "for", "while", "with", "try",
                                    "return", "import", "from", "class", "def"):
            names.add(m.group(1))
    return names


_IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_PY_FROM_LINE = re.compile(r"^[ \t]*from[ \t]+([.\w]+)[ \t]+import\b([^\n#]*)", re.MULTILINE)
_PY_IMPORT_LINE = re.compile(r"^[ \t]*import[ \t]+([^\n#]+)", re.MULTILINE)
_JS_SPEC = re.compile(r"""(?:\bfrom|\bimport|\brequire)[ \t]*\(?[ \t]*['"]([^'"\n]+)['"]""")


def import_tokens(text: str) -> set[str]:
    """Module-path tokens a file imports, read from text: JS/TS specifiers
    (`from './mod'`, `require('../lib/mod')`, `import('./m.js')`), and for
    Python files that do not parse, `from a.mod import` / `import a.mod`
    lines (`from . import mod` contributes `mod`). A superset is fine:
    these only widen `--changed` candidates."""
    out: set[str] = set()
    for m in _PY_FROM_LINE.finditer(text):
        mod = m.group(1)
        out.update(_IDENT.findall(mod))
        if not mod.strip("."):
            out.update(_IDENT.findall(m.group(2)))
    for m in _PY_IMPORT_LINE.finditer(text):
        out.update(_IDENT.findall(m.group(1)))
    for m in _JS_SPEC.finditer(text):
        out.update(_IDENT.findall(m.group(1)))
    return out


class RepoIndex:
    def __init__(self, root: Path, files: list[Path], texts: dict[str, str] | None = None,
                 alias_zones: list[tuple[str, list[tuple[str, list[str]]]]] | None = None,
                 decl_paths: set[str] | None = None,
                 tsconfig_excluded: set[str] | None = None,
                 jobs: int = 1,
                 stats: dict[str, tuple[int, int]] | None = None,
                 index_cache: "IndexCache | None" = None,
                 entries: dict[str, dict] | None = None):
        self._jobs = max(1, jobs)
        # Persistent per-file contributions (see index_cache.py), reused for
        # files whose (mtime_ns, size) in `stats` (abs path -> stat) match.
        self._index_cache = index_cache
        self._stats = stats or {}
        # Prebuilt contributions (rel -> entry) used as-is: `--changed`
        # assembles the base index from the current one this way.
        self._given_entries = entries or {}
        # rel -> entry of this build, kept for base_variant().
        self._entries: dict[str, dict] = {}
        self.root = root
        self.files = files  # absolute paths
        self.py_symbols: set[str] = set()
        self.js_symbols: set[str] = set()
        self.go_symbols: set[str] = set()
        self.c_symbols: set[str] = set()
        self.all_symbols: set[str] = set()
        self.lower_map: dict[str, set[str]] = {}
        # Defining file per symbol (rel posix paths), for scope-proximate
        # rename suggestions in autofix. A name may have several definers.
        self.symbol_files: dict[str, set[str]] = {}
        # Defined names per file (rel posix path), for import resolution.
        self.file_symbols: dict[str, set[str]] = {}
        # From-imported names per file (re-export chains resolve through these).
        self.file_imports: dict[str, set[str]] = {}
        # Attribute uses per file: (module, attr) pairs from `mod.attr`
        # text. Suppression-only evidence (ghost-export, blast_radius):
        # over-approximation can only hide a finding, never invent one.
        self.file_attr_uses: dict[str, set[tuple[str, str]]] = {}
        # Star imports per file: [(module, level)] for one-hop expansion.
        self.file_stars: dict[str, list[tuple[str | None, int]]] = {}
        # JS/TS export surface per file: exported names ('default' marks a
        # default export) and star re-export specifiers.
        self.file_exports: dict[str, set[str]] = {}
        # Files with at least one ESM `export` statement. A default import
        # from a non-ESM (CJS/script) file is valid via interop, so the
        # missing-default check only applies to ESM targets.
        self.file_esm: set[str] = set()
        # Files with dynamic namespace injection (see _DYNAMIC_NS).
        self.file_dynamic_ns: set[str] = set()
        # Files that register modules at runtime (see _REGISTERS_MODULES).
        self.file_registers_modules: set[str] = set()
        # Modules that replace themselves in sys.modules
        # (`sys.modules[__name__] = _LazyModule(...)`): their attribute
        # surface is whatever the replacement object serves.
        self.file_replaces_self: set[str] = set()
        self.file_export_stars: dict[str, list[str]] = {}
        # Tokens of the module paths each file imports (`http`, `server` for
        # `from http.server import x`; `lib`, `mod` for `'../lib/mod.js'`).
        # `--changed` uses them to find who can reach a changed module.
        self.file_import_modules: dict[str, set[str]] = {}
        # Files with a bare `export *` (external re-export): export set unknown.
        self.file_export_unknown: set[str] = set()
        # Optional pre-read contents (abs path string -> text) so callers
        # that already read the tree skip a second disk pass.
        self._texts = texts or {}
        # tsconfig/manual path-alias zones: [(zone dir rel, [(prefix, [replacements])])].
        self.alias_zones: list[tuple[str, list[tuple[str, list[str]]]]] = list(alias_zones or [])
        # relative posix paths + basenames for file-ref resolution
        self.rel_paths: set[str] = set()
        # Ambient declaration files (.d.ts/.d.mts/.d.cts): deliberately not
        # parsed as source, but their existence is real and an ambient
        # module they define is importable (bare sibling specifiers, seen:
        # svelte's `import type { Effect } from './types'` -> types.d.ts).
        # Presence-only: lets import checks stay silent without treating
        # declarations as indexed implementation surface.
        self.decl_paths: set[str] = set(decl_paths or [])
        # Repo-relative prefixes excluded by some tsconfig: the repo itself
        # declares these files outside its typecheck contract. Import checks
        # stay silent about files under them (never "missing").
        self.tsconfig_excluded: set[str] = set(tsconfig_excluded or [])
        self.basenames: set[str] = set()
        self.dirs: set[str] = set()
        # Absolute-import source roots: top segment -> path prefix, for
        # src/ and lib/ layouts (`src/mypkg/...` imported as `mypkg`).
        # Root-level packages win on collision. Presence-based: content
        # edits never affect it, file add/remove recomputes it.
        self.py_prefixes: dict[str, str] = {}
        # Files whose Python parse failed (opaque): checkers may use
        # positively-indexed names from these files, but must never
        # claim a symbol is absent from them.
        self.parse_failed: set[str] = set()
        self._deps_cache: dict | None = None
        # First-party top segments living ABOVE the scan root (subdirectory
        # scans: `scan tests/` must still recognize the project's own
        # `src/<pkg>/` package as first-party, not phantom). Bounded walk
        # to the project dir; presence-only, read once at build.
        self.parent_tops: set[str] = _walkup_tops(root)
        # This repo's own package name(s): doc examples calling the
        # documented package (`axios.get(...)` in axios's README) are
        # self-referential by construction, never stale.
        self.root_package_names: set[str] = _root_package_names(root)
        # v2: top-level names (repo root entries) for the "claims about this
        # repo" rule: file refs whose first segment is not a repo top-level
        # name (and not ./ ../ /) are external/framework namespaces, not lies.
        self.top_names: set[str] = set()
        try:
            for child in root.iterdir():
                if child.name in (".git", "__pycache__", "node_modules"):
                    continue
                self.top_names.add(child.name)
        except OSError:
            pass
        self._build()

    def text_of(self, rel: str) -> str | None:
        """File text for rel: the pre-read buffer when present (CLI serial
        scans, LSP's unsaved edits), else read from disk once and cached.
        Worker processes receive the index without the buffers (for
        cpython they were 79 MB of the 91 MB pickled into every worker);
        the few suppression paths that need raw text read it here."""
        texts = getattr(self, "_texts", None) or {}
        hit = texts.get(str(self.root / rel))
        if hit is not None:
            return hit
        cache = self.__dict__.setdefault("_disk_texts", {})
        if rel not in cache:
            try:
                cache[rel] = (self.root / rel).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                cache[rel] = None
        return cache[rel]

    def underscore_suffixes(self) -> set[str]:
        """Every `_tail` of every symbol (`cf_socket_active` -> `_socket_active`,
        `_active`), built once per process: family-fragment lookups were a
        linear scan of all symbols per candidate (232M calls on cpython)."""
        cached = self.__dict__.get("_underscore_suffixes")
        if cached is None:
            cached = set()
            for sym in self.all_symbols:
                i = sym.find("_", 1)
                while i != -1:
                    cached.add(sym[i:])
                    i = sym.find("_", i + 1)
            self.__dict__["_underscore_suffixes"] = cached
        return cached

    def dunder_symbols(self) -> frozenset[str]:
        cached = self.__dict__.get("_dunder_symbols")
        if cached is None:
            cached = frozenset(n for n in self.all_symbols
                               if len(n) > 4 and n.startswith("__") and n.endswith("__"))
            self.__dict__["_dunder_symbols"] = cached
        return cached

    def worker_copy(self) -> "RepoIndex":
        """Shallow copy for worker processes, without the text buffers."""
        import copy
        clone = copy.copy(self)
        clone._texts = {}
        clone._index_cache = None
        clone._stats = {}
        clone._entries = {}
        for lazy in ("_disk_texts",) + self._LAZY_DERIVED:
            clone.__dict__.pop(lazy, None)
        return clone

    def base_variant(self, status: dict[str, str], texts: dict[str, str]) -> "RepoIndex":
        """This index as it was at the diff base. `status` maps changed rel
        paths to "A"/"M"/"D"; `texts` holds their base text. Files the
        change added are absent, modified and deleted files carry their
        base text, and every other file keeps this build's contribution.
        Callers must not ask for a variant when a changed path is outside
        the index (manifests, .gitignore, data files): checkers read those
        from disk, where the base is not.

        Built by patching a copy of this index (copy-on-write for every
        shared container it touches), not by merging all entries again:
        on cpython the full rebuild cost 0.35 s per `--changed` scan. The
        result equals a fresh build of the base (TestBaseVariant)."""
        import copy
        base = copy.copy(self)
        for name in self._PER_FILE_DICTS:
            setattr(base, name, dict(getattr(self, name)))
        for name in self._PER_FILE_SETS + self._NAME_SETS:
            setattr(base, name, set(getattr(self, name)))
        base.symbol_files = dict(self.symbol_files)
        base.all_symbols = set(self.all_symbols)
        base.lower_map = dict(self.lower_map)
        base.rel_paths = set(self.rel_paths)
        base.decl_paths = set(self.decl_paths)
        base._entries = dict(self._entries)
        base._index_cache = None
        base._stats = {}
        base._given_entries = {}
        for lazy in ("_disk_texts", "_cli_inventory") + self._LAZY_DERIVED:
            base.__dict__.pop(lazy, None)
        base._texts = {}
        by_rel = {self._rel(f): f for f in self.files}
        touched: set[str] = set()
        for rel, code in sorted(status.items()):
            old = self._entries.get(rel)
            if old is not None:
                touched |= old.get("file_symbols", set())
                base._unapply_entry(rel, old)
                base._entries.pop(rel, None)
                base.rel_paths.discard(rel)
                base.rel_paths.discard("./" + rel)
                by_rel.pop(rel, None)
            if code != "A" and rel in texts:
                f = self.root / rel
                entry = RepoIndex.index_entry(rel, f.suffix.lower(), texts[rel])
                touched |= entry.get("file_symbols", set())
                base._apply_entry(rel, entry, copy_on_write=True)
                base._entries[rel] = entry
                base.rel_paths.add(rel)
                base.rel_paths.add("./" + rel)
                base._texts[str(f)] = texts[rel]
                by_rel[rel] = f
        order = sorted(by_rel)
        base.files = [by_rel[r] for r in order]
        rank = {r: i for i, r in enumerate(order)}
        # Per-file dicts in file order, as a fresh build fills them.
        for name in self._PER_FILE_DICTS:
            d = getattr(base, name)
            setattr(base, name, {r: d[r] for r in sorted(d, key=lambda r: rank.get(r, -1))})
        base._entries = {r: base._entries[r] for r in order if r in base._entries}
        base.basenames = {r.rsplit("/", 1)[-1] for r in order}
        base.dirs = {r[:i] for r in order for i in range(len(r)) if r[i] == "/"}
        base._refresh_names(touched)
        base._compute_py_prefixes()
        return base

    def _unapply_entry(self, rel: str, entry: dict) -> None:
        """Remove rel's contribution (the inverse of _apply_entry), copying
        any symbol_files set before changing it. Language-set membership
        is left to _refresh_names: a name may still have other definers."""
        for name in self._PER_FILE_DICTS:
            getattr(self, name).pop(rel, None)
        for name in self._PER_FILE_SETS:
            getattr(self, name).discard(rel)
        for sym in entry.get("file_symbols", ()):
            holders = self.symbol_files.get(sym)
            if holders is not None and rel in holders:
                holders = set(holders)
                holders.discard(rel)
                if holders:
                    self.symbol_files[sym] = holders
                else:
                    del self.symbol_files[sym]

    _LANG_SUFFIXES = (("py_symbols", {".py"}),
                      ("js_symbols", {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}),
                      ("go_symbols", {".go"}),
                      ("c_symbols", {".c", ".h"}))

    def _refresh_names(self, names: set[str]) -> None:
        """Recompute language sets, all_symbols and lower_map for `names`
        from their definers: a name is in a language's set exactly when a
        file of that language defines it (what _record does per file)."""
        for n in names:
            holders = self.symbol_files.get(n, ())
            suffixes = {"." + h.rsplit(".", 1)[-1].lower() for h in holders if "." in h}
            present = False
            for attr, sfx in self._LANG_SUFFIXES:
                if suffixes & sfx:
                    getattr(self, attr).add(n)
                    present = True
                else:
                    getattr(self, attr).discard(n)
            key = n.lower()
            group = set(self.lower_map.get(key, ()))
            if present:
                self.all_symbols.add(n)
                group.add(n)
            else:
                self.all_symbols.discard(n)
                group.discard(n)
            if group:
                self.lower_map[key] = group
            else:
                self.lower_map.pop(key, None)

    def _rel(self, f: Path) -> str:
        try:
            return f.relative_to(self.root).as_posix()
        except ValueError:
            return f.name

    def knows_symbols(self, rel: str) -> bool:
        """False when rel failed to parse: absence there is unknowable."""
        return rel not in self.parse_failed

    # Everything `_index_one` writes. A per-file indexer reads only its own
    # text, so chunks of files can be indexed in worker processes and the
    # partial states merged here (keys are disjoint rel paths; name sets
    # union). A new per-file attribute MUST be listed here or parallel
    # builds silently drop it (pinned by TestParallelIndexBuild).
    _PER_FILE_DICTS = ("file_symbols", "file_imports", "file_attr_uses",
                       "file_exports", "file_stars", "file_export_stars",
                       "file_import_modules")
    _PER_FILE_SETS = ("file_esm", "file_dynamic_ns", "file_registers_modules", "file_replaces_self",
                      "file_export_unknown", "parse_failed")
    _NAME_SETS = ("py_symbols", "js_symbols", "go_symbols", "c_symbols")

    @classmethod
    def _blank(cls) -> "RepoIndex":
        part = cls.__new__(cls)
        for name in cls._PER_FILE_DICTS:
            setattr(part, name, {})
        for name in cls._PER_FILE_SETS + cls._NAME_SETS:
            setattr(part, name, set())
        part.symbol_files = {}
        return part

    @classmethod
    def index_entry(cls, rel: str, suffix: str, text: str) -> dict:
        """One file's whole contribution to the index, as plain data
        (marshal-safe: persisted by IndexCache). Keys present only when
        the fresh build would hold them: attribute -> this file's value
        for per-file dicts, True for per-file sets, names for name sets.
        symbol_files is not stored: _record writes it as the exact
        inverse of file_symbols, so _apply_entry derives it."""
        part = cls._blank()
        part._index_one(rel, suffix, text, rebuild=False)
        entry: dict = {}
        for name in cls._PER_FILE_DICTS:
            per_file = getattr(part, name)
            if rel in per_file:
                entry[name] = per_file[rel]
        for name in cls._PER_FILE_SETS:
            if rel in getattr(part, name):
                entry[name] = True
        for name in cls._NAME_SETS:
            names = getattr(part, name)
            if names:
                entry[name] = names
        return entry

    @classmethod
    def index_chunk(cls, items: list[tuple[str, str, str]]) -> list[tuple[str, dict]]:
        """[(rel, entry)] for [(rel, suffix, text)] (worker entry point)."""
        return [(rel, cls.index_entry(rel, suffix, text)) for rel, suffix, text in items]

    def _apply_entry(self, rel: str, entry: dict, copy_on_write: bool = False) -> None:
        for name, value in entry.items():
            if name in self._PER_FILE_DICTS:
                getattr(self, name)[rel] = value
            elif name in self._PER_FILE_SETS:
                getattr(self, name).add(rel)
            elif not copy_on_write:
                # Language sets. A patched variant recomputes them per name
                # instead (_refresh_names).
                getattr(self, name).update(value)
        for sym in entry.get("file_symbols", ()):
            if copy_on_write:
                self.symbol_files[sym] = set(self.symbol_files.get(sym, ())) | {rel}
            else:
                self.symbol_files.setdefault(sym, set()).add(rel)

    # Below this many files, process spawn costs more than it saves.
    _PARALLEL_MIN_FILES = 512

    def _build(self) -> None:
        cache = self._index_cache
        stats = self._stats
        entries: dict[str, dict] = {}
        order: list[str] = []
        abs_of: dict[str, str] = {}
        pending: list[tuple[str, str, str]] = []
        # String operations, not pathlib: relative_to/parent/parts/suffix
        # cost ~0.3 s per 3k files, and a cached `--changed` scan does
        # little else here.
        prefix = str(self.root).rstrip(os.sep) + os.sep
        for f in self.files:
            fs = str(f)
            rel = fs[len(prefix):].replace(os.sep, "/") if fs.startswith(prefix) else f.name
            name = rel.rsplit("/", 1)[-1]
            self.rel_paths.add(rel)
            self.rel_paths.add("./" + rel)
            if name.endswith((".d.ts", ".d.mts", ".d.cts")):
                self.decl_paths.add(rel)
            self.basenames.add(name)
            for i, ch in enumerate(rel):
                if ch == "/":
                    self.dirs.add(rel[:i])
            dot = name.rfind(".")
            suffix = name[dot:].lower() if 0 < dot < len(name) - 1 else ""
            given = self._given_entries.get(rel)
            if given is not None:
                entries[rel] = given
                order.append(rel)
                continue
            if cache is not None:
                hit = cache.lookup(rel, stats.get(fs))
                if hit is not None:
                    entries[rel] = hit
                    order.append(rel)
                    continue
            if fs in self._texts:
                text = self._texts[fs]
            else:
                try:
                    text = f.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
            order.append(rel)
            abs_of[rel] = fs
            pending.append((rel, suffix, text))
        fresh: list[tuple[str, dict]] | None = None
        if self._jobs > 1 and len(pending) >= self._PARALLEL_MIN_FILES:
            from concurrent.futures import ProcessPoolExecutor
            from concurrent.futures.process import BrokenProcessPool
            n = self._jobs * 4
            chunks = [pending[i::n] for i in range(n)]
            try:
                with ProcessPoolExecutor(max_workers=self._jobs) as pool:
                    fresh = [pair for part in pool.map(RepoIndex.index_chunk, chunks)
                             for pair in part]
            except (OSError, BrokenProcessPool):
                # No usable worker processes (sandboxed runners, spawn
                # failures): the serial build gives the identical index.
                fresh = None
        if fresh is None:
            fresh = RepoIndex.index_chunk(pending)
        for rel, entry in fresh:
            entries[rel] = entry
            if cache is not None:
                cache.store(rel, stats.get(abs_of[rel]), entry)
        # Applied in file order whatever their source, so the cached, the
        # serial and the parallel build fill every attribute identically.
        for rel in order:
            self._apply_entry(rel, entries[rel])
        self._entries = {rel: entries[rel] for rel in order}
        self._given_entries = {}
        if cache is not None:
            cache.save()
        self._rebuild_unions()
        self._compute_py_prefixes()

    def _compute_py_prefixes(self) -> None:
        prefixes: dict[str, str] = {}
        clean = {r for r in self.rel_paths if not r.startswith("./")}
        for src_root in ("src", "lib"):
            if src_root not in self.top_names:
                continue
            for rel in sorted(clean):
                if not rel.startswith(src_root + "/"):
                    continue
                rest = rel[len(src_root) + 1:]
                pkg = rest.split("/")[0] if "/" in rest else rest.rsplit(".", 1)[0]
                if not pkg or pkg in prefixes:
                    continue
                if (f"{src_root}/{pkg}/__init__.py" in clean
                        or f"{src_root}/{pkg}.py" in clean
                        or f"{src_root}/{pkg}" in self.dirs):
                    prefixes[pkg] = src_root
        # Root-level packages win: drop shadowed entries.
        for pkg in [p for p in prefixes
                    if p + ".py" in clean or f"{p}/__init__.py" in clean]:
            del prefixes[pkg]
        self.py_prefixes = prefixes


    def _record(self, target: set[str], name: str, rel: str) -> None:
        target.add(name)
        self.symbol_files.setdefault(name, set()).add(rel)
        self.file_symbols.setdefault(rel, set()).add(name)

    def attr_used_by(self, symbol: str, own: str) -> set[str]:
        """Files (other than own) importing own's module and touching
        `mod.symbol` textually: `from pkg import mod` + `mod.symbol()`.

        The file must import the module root, so a same-named local
        (`lsp = get_conf(); lsp.serve()`) is not evidence. Used for
        suppression (ghost-export) and recall (blast_radius) only.
        """
        dot = own.rfind(".")
        stem = own[:dot]
        stem = stem[stem.rfind("/") + 1:] if "/" in stem else stem
        dotted = own[:dot].replace("/", ".") if dot > 0 else own
        out: set[str] = set()
        for rel, pairs in self.file_attr_uses.items():
            if rel == own:
                continue
            mods = self.file_imports.get(rel, set())
            for (mod, attr) in pairs:
                if attr != symbol:
                    continue
                base = mod.split(".")[0]
                if base in mods and (mod == stem or mod == dotted
                                     or mod.endswith("." + stem)):
                    out.add(rel)
        return out

    _ATTR_USE = re.compile(
        r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"
        r"\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)\b")
    # Dynamic namespace injection: static analysis cannot enumerate the
    # names (`globals().update(...)` in __init__). Files flagged here make
    # `from . import X` unknowable for their package: suppress, don't guess.
    _DYNAMIC_NS = re.compile(r"globals\(\)\s*\.\s*update\s*\(")
    # Runtime module registration: `sys.modules[name] = mod` (or update /
    # setdefault) creates importable dotted paths with no file behind them.
    # Seen: requests/packages.py aliases `requests.packages.urllib3.*` onto
    # urllib3, and `from requests.packages.urllib3.poolmanager import ...`
    # read as a missing module.
    _REPLACES_SELF = re.compile(r"sys\.modules\s*\[\s*__name__\s*\]\s*=(?!=)")
    _REGISTERS_MODULES = re.compile(
        r"sys\.modules\s*(?:\[[^\]\n]+\]\s*=(?!=)|\.\s*(?:update|setdefault)\s*\()")

    @staticmethod
    def _attr_pairs(text: str) -> set[tuple[str, str]]:
        """(module, attr) pairs from `mod.attr` text. Full-line comments
        and string literals are blanked first; residue only ever
        suppresses, never invents."""
        out: set[tuple[str, str]] = set()
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("//") or s.startswith("*"):
                continue
            code = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", '""', line)
            for m in RepoIndex._ATTR_USE.finditer(code):
                out.add((m.group(1), m.group(2)))
        return out

    def _index_one(self, rel: str, suffix: str, text: str, rebuild: bool = True) -> None:
        """(Re-)index a single file's contributions. Safe to call repeatedly:
        previous contributions for rel are forgotten first."""
        self._forget_no_rebuild(rel)
        if suffix == ".py":
            self._index_python(text, rel)
        elif suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}:
            self._index_js(text, rel)
        elif suffix == ".go":
            self._index_go(text, rel)
        elif suffix in {".c", ".h"}:
            self._index_c(text, rel)
        if suffix in {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
                      ".mts", ".cts", ".go", ".c", ".h"}:
            self.file_attr_uses[rel] = self._attr_pairs(text)
        if self._DYNAMIC_NS.search(text):
            self.file_dynamic_ns.add(rel)
        if suffix == ".py" and self._REGISTERS_MODULES.search(text):
            self.file_registers_modules.add(rel)
            if self._REPLACES_SELF.search(text):
                self.file_replaces_self.add(rel)
        if rebuild:
            self._rebuild_unions()

    _LAZY_DERIVED = ("_underscore_suffixes", "_dunder_symbols", "_dunder_typo_memo",
                     "_module_stems")

    def _rebuild_unions(self) -> None:
        # Derived lookups follow all_symbols: drop them so LSP edits that
        # rebuild the unions never read a stale cache.
        for lazy in self._LAZY_DERIVED:
            self.__dict__.pop(lazy, None)
        self.all_symbols = set(self.py_symbols) | set(self.js_symbols) | set(self.go_symbols) | set(self.c_symbols)
        self.lower_map = {}
        for s in self.all_symbols:
            self.lower_map.setdefault(s.lower(), set()).add(s)

    def forget_file(self, rel: str) -> None:
        """Drop every index contribution from rel (rename/delete/close)."""
        self._forget_no_rebuild(rel)
        self.decl_paths.discard(rel)
        self._rebuild_unions()
        self._compute_py_prefixes()

    def declared_dependencies(self, rel: str | None = None) -> set[str] | None:
        """Distribution names from manifests (normalized), mtime-cached.

        Project dir = nearest ancestor (from rel's dir, else scan root)
        containing pyproject.toml or package.json; its manifests plus its
        requirements files form the closure, unioned with nearer nested
        manifests walking down AND further ancestors walking up (Node
        resolution walks up; monorepo roots hoist deps). Returns None
        when no manifest exists anywhere: without evidence the checker
        stays silent. Union-everything is deliberate: a name missing here
        is declared nowhere, which is exactly the claim.
        """
        start = (self.root / rel).parent if rel else self.root
        start = start if start.is_dir() else self.root
        project = start
        while not ((project / "pyproject.toml").exists()
                   or (project / "package.json").exists()):
            parent = project.parent
            if parent == project:
                return None
            project = parent
        dirs: list[Path] = []
        d = start
        while True:
            dirs.append(d)
            if d == project:
                break
            d = d.parent
        up = project.parent
        while True:
            dirs.append(up)
            if up.parent == up:
                break
            up = up.parent
        manifests: list[tuple[str, float]] = []
        for d in dirs:
            for name in ("pyproject.toml", "package.json"):
                try:
                    manifests.append((str(d / name), (d / name).stat().st_mtime))
                except OSError:
                    continue
        try:
            reqs = sorted(project.glob("requirements*.txt"))
            reqdir = project / "requirements"
            if reqdir.is_dir():
                reqs += sorted(reqdir.glob("*.txt"))
        except OSError:
            reqs = []
        for p in reqs:
            try:
                manifests.append((str(p), p.stat().st_mtime))
            except OSError:
                continue
        key = (tuple(str(d) for d in dirs), tuple(manifests))
        cached = (self._deps_cache or {}).get(key)
        if cached is not None:
            mtime_key, deps = cached
            if mtime_key == tuple(manifests):
                return set(deps)
        deps: set[str] = set()
        for d in dirs:
            try:
                pyproject = d / "pyproject.toml"
                if pyproject.exists():
                    data = _read_manifest_toml(pyproject)
                    if isinstance(data, dict):
                        _collect_py_deps(data, deps)
            except OSError:
                pass
            try:
                package_json = d / "package.json"
                if package_json.exists():
                    data = json.loads(package_json.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        for section in ("dependencies", "devDependencies",
                                        "peerDependencies", "optionalDependencies"):
                            part = data.get(section)
                            if isinstance(part, dict):
                                deps.update(_norm_dist(k) for k in part if isinstance(k, str))
            except (OSError, ValueError):
                pass
        for p in reqs:
            _collect_requirements(p, deps, seen=set())
        if self._deps_cache is None:
            self._deps_cache = {}
        self._deps_cache[key] = (tuple(manifests), set(deps))
        return deps

    def _forget_no_rebuild(self, rel: str) -> None:
        old = self.file_symbols.pop(rel, set())
        self.parse_failed.discard(rel)
        self.file_imports.pop(rel, None)
        self.file_esm.discard(rel)
        self.file_dynamic_ns.discard(rel)
        self.file_registers_modules.discard(rel)
        self.file_replaces_self.discard(rel)
        self.file_attr_uses.pop(rel, None)
        self.file_stars.pop(rel, None)
        self.file_exports.pop(rel, None)
        self.file_export_stars.pop(rel, None)
        self.file_import_modules.pop(rel, None)
        self.file_export_unknown.discard(rel)
        for name in old:
            holders = self.symbol_files.get(name)
            if holders is not None:
                holders.discard(rel)
                if not holders:
                    del self.symbol_files[name]
                    for lang in (self.py_symbols, self.js_symbols, self.go_symbols, self.c_symbols):
                        lang.discard(name)

    def _index_python(self, text: str, rel: str) -> None:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            # Unparseable (version-skewed grammar, mid-typing buffer):
            # record top-level bindings heuristically, but mark the file
            # opaque so no checker ever claims a symbol is ABSENT from it.
            # An empty symbol table reads as "exports nothing" downstream
            # and cascades into phantom lies (seen: 24,881 on
            # home-assistant/core scanned under the wrong interpreter).
            self.parse_failed.add(rel)
            for name in _fallback_top_level(text):
                self._record(self.py_symbols, name, rel)
            self.file_import_modules[rel] = import_tokens(text)
            return

        def _targets(t) -> list[str]:
            # Destructured assignment targets: `A, B = ...`, `(A, B) = ...`.
            if isinstance(t, ast.Name):
                return [t.id]
            if isinstance(t, (ast.Tuple, ast.List)):
                out: list[str] = []
                for e in t.elts:
                    out.extend(_targets(e))
                return out
            if isinstance(t, ast.Starred):
                return _targets(t.value)
            return []

        def _bind_assign(node) -> None:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    for name in _targets(t):
                        self._record(self.py_symbols, name, rel)
            elif isinstance(node, ast.AnnAssign):
                for name in _targets(node.target):
                    self._record(self.py_symbols, name, rel)

        def _bind_import(node) -> None:
            if isinstance(node, ast.Import):
                for a in node.names:
                    top = (a.name or "").split(".")[0]
                    self.file_imports.setdefault(rel, set()).add(a.asname or top)
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    if a.name == "*":
                        self.file_stars.setdefault(rel, []).append((node.module, node.level or 0))
                    else:
                        # Both: the alias is the local binding, the original
                        # is the cross-file dependency (ghost-export and
                        # re-export chains resolve through it).
                        self.file_imports.setdefault(rel, set()).add(a.asname or a.name)
                        if a.asname and a.asname != a.name:
                            self.file_imports[rel].add(a.name)

        _TypeAlias = getattr(ast, "TypeAlias", None)  # 3.12+; absent on 3.10/3.11
        modules = self.file_import_modules.setdefault(rel, set())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    modules.update(_IDENT.findall(a.name or ""))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.update(_IDENT.findall(node.module))
                else:  # `from . import mod`: the names are the modules
                    modules.update(a.name for a in node.names if a.name != "*")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self._record(self.py_symbols, node.name, rel)
            elif _TypeAlias is not None and isinstance(node, _TypeAlias):
                # PEP 695 `type X = ...`: a real runtime binding; without
                # it every `from types import X` misfires (seen: _pyrepl).
                name = getattr(node.name, "id", "")
                if name:
                    self._record(self.py_symbols, name, rel)
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    if a.name != "*":
                        self.file_imports.setdefault(rel, set()).add(a.asname or a.name)
                        if a.asname and a.asname != a.name:
                            self.file_imports[rel].add(a.name)
        # Module-level bindings: direct body plus recursive descent into
        # try/if bodies (compat shims nest try blocks and assign/import
        # there constantly). Never descends into functions or classes, so
        # locals stay local. Depth is bounded by the tree itself.
        _TRY = (ast.Try,) + ((ast.TryStar,) if hasattr(ast, "TryStar") else ())
        stack: list[list] = [getattr(tree, "body", [])]
        while stack:
            for node in stack.pop():
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.Import, ast.ImportFrom)):
                    _bind_assign(node)
                    _bind_import(node)
                elif isinstance(node, ast.If):
                    stack.append(list(node.orelse))
                    stack.append(list(node.body))
                elif isinstance(node, _TRY):
                    for h in node.handlers:
                        stack.append(list(h.body))
                    stack.append(list(node.orelse))
                    stack.append(list(node.finalbody))
                    stack.append(list(node.body))

    def _index_go(self, text: str, rel: str) -> None:
        for line in text.splitlines():
            m = re.match(r"^\s*func\s+(?:\([^)]*\)\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
            if m:
                self._record(self.go_symbols, m.group(1), rel)
                continue
            t = re.match(r"^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)\b", line)
            if t:
                self._record(self.go_symbols, t.group(1), rel)

    def _index_c(self, text: str, rel: str) -> None:
        from .parsers import c_top_level_names
        for name in c_top_level_names(text):
            self._record(self.c_symbols, name, rel)

    def _index_js(self, text: str, rel: str) -> None:
        self.file_import_modules[rel] = import_tokens(text)
        for line in text.splitlines():
            for pat in _JS_FUNC_PATTERNS:
                m = pat.match(line)
                if m:
                    self._record(self.js_symbols, m.group(1), rel)
                    break
            em = re.match(
                r"^\s*export\s+(?:declare\s+)?(?:async\s+)?(?:function\*?\s+|class\s+|"
                r"const\s+enum\s+|(?:const|let|var)\s+|(?:abstract\s+class\s+)|"
                r"(?:opaque\s+type|interface|type|enum|namespace|module)\s+)([A-Za-z_$][A-Za-z0-9_$]*)", line)
            if em:
                self.file_exports.setdefault(rel, set()).add(em.group(1))
                if not re.match(r"^\s*export\s+(?:opaque\s+)?(?:interface|type)\b", line):
                    # Value export (enum counts: it emits runtime code).
                    # Pure type exports are erased and prove nothing about
                    # the runtime module system.
                    self.file_esm.add(rel)
            if re.match(r"^\s*export\s+default\b", line):
                self.file_exports.setdefault(rel, set()).add("default")
                self.file_esm.add(rel)
        # export { a, b as c } / export type { T } / export * from './x'
        # export const { a, b: c, ...rest } = obj / export const [x, y] = arr.
        # Destructured value exports bind every target name (seen: prettier's
        # `export const { optionCategories, fastGlob, ... } = sharedWithCli`
        # reported as 9 stale imports).
        for m in re.finditer(r"export\s+(?:const|let|var)\s*([{\[])([^}\]]*)[}\]]\s*=", text):
            self.file_esm.add(rel)
            body = re.sub(r"//[^\n]*|/\*.*?\*/", "", m.group(2), flags=re.S)
            for part in body.split(","):
                part = part.strip()
                if part.startswith("..."):
                    part = part[3:]
                if m.group(1) == "{" and ":" in part:
                    part = part.split(":", 1)[1]
                name = part.split("=", 1)[0].strip()
                if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", name or ""):
                    self._record(self.js_symbols, name, rel)
                    self.file_exports.setdefault(rel, set()).add(name)
        for m in re.finditer(r"export\s+(?:(type)\s+)?\{\s*([^}]+)\}", text):
            if not m.group(1):
                self.file_esm.add(rel)
            # Comments inside the braces may contain commas
            # (seen: prettier's `// Shared with <file>, will remove later`):
            # strip them before splitting, or the next name is lost.
            names = re.sub(r"//[^\n]*|/\*.*?\*/", "", m.group(2), flags=re.S)
            for part in names.split(","):
                part = part.strip()
                if not part:
                    continue
                bits = [b.strip() for b in part.split(" as ")]
                # TS type modifier inside the braces (`export { type X }`,
                # `export { type X as Y }`): strip it, or the alias keeps a
                # "type " prefix, fails the identifier check, and the
                # re-exported type vanishes from the module's export
                # surface (seen: OmniRoute barrel re-exporting
                # ProviderMessageTranslator -> 13 bogus stale-imports).
                local = bits[0].split(":")[0].strip()
                if local.startswith("type "):
                    local = local[len("type "):].strip()
                alias = bits[-1].split(":")[0].strip()
                if alias.startswith("type "):
                    alias = alias[len("type "):].strip()
                if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", alias or ""):
                    if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", local or ""):
                        self._record(self.js_symbols, local, rel)
                    self.file_exports.setdefault(rel, set()).add(alias)
        for m in re.finditer(r"export\s*\*\s*from\s*['\"]([^'\"]+)['\"]", text):
            spec = m.group(1)
            self.file_esm.add(rel)
            self.file_export_stars.setdefault(rel, []).append(spec)
            if not spec.startswith("./") and not spec.startswith("../"):
                # Bare re-export (external package): this module's export
                # set is unknowable from the snapshot. Recorded so name
                # checks against it stay silent instead of guessing.
                self.file_export_unknown.add(rel)
        for m in re.finditer(r"module\.exports\s*=\s*\{([^}]+)\}", text):
            for part in m.group(1).split(","):
                name = part.strip().split(":")[0].strip()
                if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", name or ""):
                    self._record(self.js_symbols, name, rel)
                    self.file_exports.setdefault(rel, set()).add(name)
        for m in re.finditer(r"(?:exports|module\.exports)\.([A-Za-z_$][A-Za-z0-9_$]*)\s*=", text):
            self._record(self.js_symbols, m.group(1), rel)
            self.file_exports.setdefault(rel, set()).add(m.group(1))
        # `module.exports = <expr>` (anything but an object literal, whose
        # keys are handled above) is a default export, named or not.
        if re.search(r"module\.exports\s*=(?![=>])\s*(?![{\s])", text):
            self.file_exports.setdefault(rel, set()).add("default")
        base = rel.rsplit("/", 1)[-1]
        suffix = "." + base.rsplit(".", 1)[-1].lower() if "." in base else ""
        if suffix in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
                      ".mts", ".cts"):
            self._merge_tree_sitter_defs(text, rel, suffix)

    def _merge_tree_sitter_defs(self, text: str, rel: str, suffix: str) -> None:
        """Optional tree-sitter enrichment (see tree_sitter_js module).

        Unions declaration names and export names the regexes cannot see
        (multi-line headers, ambient `const enum`, namespaces, abstract
        classes, specifier aliases). Suppression-only: extra names can
        silence a finding, never invent one. No grammars installed means
        no change at all, which is exactly what CI pins.
        """
        try:
            from .tree_sitter_js import extract_js_defs
        except ImportError:
            return
        try:
            extra = extract_js_defs(text, suffix)
        except Exception:
            return
        if not extra:
            return
        for name in extra["symbols"]:
            self._record(self.js_symbols, name, rel)
        if extra["exports"]:
            self.file_exports.setdefault(rel, set()).update(extra["exports"])
            self.file_esm.add(rel)
        if extra["has_default"]:
            self.file_exports.setdefault(rel, set()).add("default")
            self.file_esm.add(rel)

    def has_symbol(self, name: str) -> bool:
        if not name:
            return False
        if name in self.all_symbols:
            return True
        # dotted: check last segment
        if "." in name:
            last = name.split(".")[-1]
            if last in self.all_symbols:
                return True
        return False

    def is_gitignored(self, rel: str) -> bool:
        """Whether rel matches the project's root `.gitignore`.

        A missing file the repo itself ignores is a build or test artifact
        (setuptools-scm's `_version.py`, generated clients), written after
        checkout: its absence in a snapshot is not evidence of rot. Root
        file only, `!` negations respected conservatively (any negation that
        matches means "not ignored"). Suppression-only.
        """
        import fnmatch
        rel = rel.lstrip("./")
        parts = rel.split("/")
        hit = False
        # Every .gitignore from the root down to the file's directory, each
        # matching paths relative to its own directory (git's semantics,
        # minus nothing that could *add* a finding: this only suppresses).
        for depth in range(0, len(parts)):
            base = "/".join(parts[:depth])
            pats = self._gitignore_patterns(base)
            if not pats:
                continue
            sub = parts[depth:]
            prefixes = ["/".join(sub[:i]) for i in range(1, len(sub) + 1)]
            for neg, anchored, dir_only, pat in pats:
                cands = prefixes[:-1] if dir_only else prefixes
                ok = False
                for c in cands:
                    tail = c.split("/")[-1]
                    if anchored or "/" in pat:
                        ok = fnmatch.fnmatchcase(c, pat)
                    else:
                        ok = fnmatch.fnmatchcase(tail, pat)
                    if ok:
                        break
                if ok:
                    if neg:
                        return False
                    hit = True
        return hit

    def _gitignore_patterns(self, base: str = "") -> list[tuple[bool, bool, bool, str]]:
        cache = getattr(self, "_gitignore_cache", None)
        if not isinstance(cache, dict):
            cache = self._gitignore_cache = {}
        if base in cache:
            return cache[base]
        out: list[tuple[bool, bool, bool, str]] = []
        try:
            raw = (self.root / base / ".gitignore").read_text(encoding="utf-8", errors="ignore")
        except OSError:
            raw = ""
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            neg = line.startswith("!")
            line = line[1:] if neg else line
            dir_only = line.endswith("/")
            line = line.rstrip("/")
            anchored = line.startswith("/")
            line = line.lstrip("/").replace("**/", "")
            if line:
                out.append((neg, anchored, dir_only, line))
        cache[base] = out
        return out

    def exists_near(self, ref: str, claimer: str) -> bool:
        """Whether ref names a real file relative to one of the claiming
        file's ancestor directories (below the root). Examples and nested
        packages write paths relative to themselves: grpc-go's
        `examples/route_guide/server/server.go` names
        `testdata/route_guide_db.json`, which lives in
        `examples/route_guide/testdata/`."""
        r = ref.strip().strip("'\"`").lstrip("./").split("?")[0].split("#")[0]
        if not r:
            return False
        parts = claimer.split("/")[:-1]
        for i in range(len(parts), 0, -1):
            try:
                if (self.root.joinpath(*parts[:i]) / r).exists():
                    return True
            except OSError:
                return False
        return False

    def has_exact_path(self, ref: str) -> bool:
        """Exact-path existence only (no basename fallback).

        Basename matching hid moved files (`src/old/x.py` silently
        resolving via an unrelated `x.py`), which is precisely the
        rename/move signal the checker and autofix need. Same-named
        files elsewhere are reported as candidates, not resolutions.
        """
        r = ref.strip().strip("'\"`").lstrip("./")
        r = r.split("?")[0].split("#")[0]
        if not r:
            return False
        if r in self.rel_paths:
            return True
        for known in self.rel_paths:
            if known.endswith("/" + r) or known == r:
                return True
        candidate = self.root / r
        try:
            if candidate.exists():
                return True
        except OSError:
            pass
        return False

    def same_named(self, ref: str) -> list[str]:
        """Repo-relative paths sharing the referenced basename, sorted."""
        base = ref.strip().split("/")[-1]
        return sorted(p for p in self.rel_paths if p.split("/")[-1] == base and not p.startswith("./"))


def _norm_dist(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _req_name(req: str) -> str:
    req = req.split(";")[0].strip()
    if " @ " in req:
        req = req.split(" @ ")[0].strip()
    m = re.match(r"[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?", req or "")
    return _norm_dist(m.group(0)) if m else ""


def _read_manifest_toml(path: Path):
    try:
        import tomllib  # py3.11+
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except ImportError:
        pass
    except (OSError, ValueError):
        return None
    try:
        from .toml_compat import loads as _compat_loads
        return _compat_loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def _collect_py_deps(data: dict, deps: set[str]) -> None:
    def add_list(items) -> None:
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str):
                    name = _req_name(item)
                    if name:
                        deps.add(name)

    proj = data.get("project")
    if isinstance(proj, dict):
        add_list(proj.get("dependencies"))
        opt = proj.get("optional-dependencies")
        if isinstance(opt, dict):
            for items in opt.values():
                add_list(items)
    groups = data.get("dependency-groups")
    if isinstance(groups, dict):
        for items in groups.values():
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, str):
                        name = _req_name(item)
                        if name:
                            deps.add(name)
    build = data.get("build-system")
    if isinstance(build, dict):
        add_list(build.get("requires"))
    tool = data.get("tool")
    if isinstance(tool, dict):
        poetry = tool.get("poetry")
        if isinstance(poetry, dict):
            for key, val in poetry.items():
                if key == "dependencies" and isinstance(val, dict):
                    for dep in val:
                        if isinstance(dep, str) and dep.lower() != "python":
                            deps.add(_norm_dist(dep))
                if key == "group":
                    groups = val if isinstance(val, dict) else {}
                    for grp in groups.values():
                        if isinstance(grp, dict):
                            sub = grp.get("dependencies")
                            if isinstance(sub, dict):
                                for dep in sub:
                                    if isinstance(dep, str) and dep.lower() != "python":
                                        deps.add(_norm_dist(dep))


def _collect_requirements(path: Path, deps: set[str], seen: set[str]) -> None:
    key = str(path.resolve()) if hasattr(path, "resolve") else str(path)
    if key in seen:
        return
    seen.add(key)
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-r ", "--requirement ", "-c ", "--constraint ")):
            target = line.split(None, 1)[1].strip().split()[0]
            _collect_requirements(path.parent / target, deps, seen)
            continue
        if line.startswith("-"):
            continue
        name = _req_name(line)
        if name:
            deps.add(name)

