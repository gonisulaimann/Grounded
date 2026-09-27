"""Registry Grid pilot: README-vs-code truth for published packages.

The moonshot's first step, honestly scoped: given PyPI package names,
download their sdists, extract, and run the doc-example check
(stale-doc-ref) of each README against the shipped code. Output is a
JSON report per package: which documented calls resolve, which do not.

Method limits (stated, not hidden):
- sdist preferred, wheel fallback; packages without either are skipped.
- README only (md/rst/markdown, any case); docs/ directories are NOT
  crawled in the pilot (that's the grid's next step).
- Python fences only; narrative/tutorial residue applies exactly as in
  the checker (placeholders, stdlib, bindings all silent).
- An "unknown" call is a *candidate* for doc rot, not proof: examples
  often show user-side or third-party code. Every unknown needs human
  classification before it becomes a claim. The pilot records, it does
  not accuse.

Usage:
    python3 bench/registry.py requests click rich [--json out.json]
    python3 bench/registry.py --local /path/to/package [--json out.json]
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

UA = {"User-Agent": "grounded-registry-pilot/0.17 (+https://github.com/gonisulaimann/Grounded)"}


def _get_json(url: str, timeout: float = 30.0):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_sdist(name: str, version: str | None, dest: Path) -> Path | None:
    """Download name's sdist (wheel fallback) into dest. None on any problem."""
    try:
        meta = _get_json(f"https://pypi.org/pypi/{name}/json")
    except Exception:
        return None
    if version is None:
        version = meta.get("info", {}).get("version")
    urls = [u for u in meta.get("urls", [])
            if u.get("python_version") == "source" or u.get("packagetype") == "sdist"]
    if not urls:
        urls = [u for u in meta.get("urls", []) if u.get("filename", "").endswith(".whl")]
    if not urls:
        return None
    url = urls[0]["url"]
    target = dest / urls[0]["filename"]
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=120) as r, open(target, "wb") as f:
            shutil.copyfileobj(r, f, length=1024 * 64)
    except Exception:
        return None
    return target


def extract(archive: Path, dest: Path) -> Path | None:
    """Unpack into dest; return the single top-level dir (or dest)."""
    try:
        if archive.suffix == ".zip" or archive.name.endswith(".whl"):
            with zipfile.ZipFile(archive) as z:
                z.extractall(dest)
        else:
            with tarfile.open(archive, "r:*") as t:
                t.extractall(dest, filter="data")
    except Exception:
        return None
    kids = [p for p in dest.iterdir() if p.is_dir()]
    return kids[0] if len(kids) == 1 else dest


def find_readme(tree: Path) -> Path | None:
    cands = sorted(tree.glob("README*")) + sorted(tree.glob("readme*"))
    for c in cands:
        if c.is_file() and c.suffix.lower() in (".md", ".rst", ".markdown", ".txt", ""):
            return c
    for c in sorted(tree.rglob("README.md")):
        if len(c.relative_to(tree).parts) <= 2:
            return c
    return None


def check_package(tree: Path) -> dict:
    """Run the doc-example check of tree's README against its code."""
    from grounded.config import Config
    from grounded.parsers import parse_file
    from grounded.scanner import scan_root
    from grounded.checkers.docs import check_stale_doc_ref
    readme = find_readme(tree)
    if readme is None:
        return {"readme": None, "calls": [], "unknown": []}
    try:
        text = readme.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {"readme": readme.name, "calls": [], "unknown": [],
                "error": "unreadable"}
    _, _, index = scan_root(tree, Config())
    facts = parse_file(readme, readme.relative_to(tree).as_posix(), text)
    findings = check_stale_doc_ref(facts, index)
    calls = sorted({f.claim.strip("`") for f in findings})
    return {"readme": readme.relative_to(tree).as_posix(),
            "calls": calls,
            "unknown": [{"call": f.claim.strip("`"), "line": f.line,
                         "title": f.title} for f in findings]}


def run_package(name: str, version: str | None = None,
                local: Path | None = None) -> dict:
    report: dict = {"package": name, "version": version}
    if local is not None:
        report["version"] = "local"
        out = check_package(local)
        report.update(out)
        return report
    with tempfile.TemporaryDirectory(prefix="grounded-registry-") as td:
        base = Path(td)
        archive = fetch_sdist(name, version, base)
        if archive is None:
            report["error"] = "no sdist or wheel on PyPI"
            return report
        outdir = base / "unpacked"
        outdir.mkdir()
        tree = extract(archive, outdir)
        if tree is None:
            report["error"] = "extraction failed"
            return report
        try:
            actual_version = tree.name.rsplit("-", 1)[-1]
        except Exception:
            actual_version = version
        report["version"] = actual_version or version
        report.update(check_package(tree))
        return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("packages", nargs="*", help="PyPI names (pin with ==)")
    ap.add_argument("--local", default=None, help="scan a local dir as a package")
    ap.add_argument("--json", default=None, help="write full report JSON")
    args = ap.parse_args(argv)
    reports = []
    if args.local:
        reports.append(run_package(Path(args.local).name, local=Path(args.local)))
    for spec in args.packages:
        if "==" in spec:
            name, version = spec.split("==", 1)
        else:
            name, version = spec, None
        print(f"registry: {spec} ...", flush=True)
        reports.append(run_package(name, version))
    total_unknown = sum(len(r.get("unknown", [])) for r in reports)
    print(f"registry: {len(reports)} package(s), "
          f"{total_unknown} unknown documented call(s) "
          f"(candidates, not verdicts — classify before claiming).")
    if args.json:
        Path(args.json).write_text(json.dumps(reports, indent=2), encoding="utf-8")
    else:
        print(json.dumps(reports, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
