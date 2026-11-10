"""Check MIC3 model I/O contracts against local clones of the model repositories.

For every contract in contracts/*.yaml, the script finds entries that point at files inside a repository
and reports whether they exist at the checked-out commit. For CSV files and xlsx sheets it also checks
that the columns the contract lists are present in the header.

Entries checked:
  - any mapping with `path` (or `check_path`) and `in_repo: true`; the repository is the entry's `repo`
    key if present, otherwise the contract's `source.repo`
  - any mapping with `repo` and `path`/`then`/`config` keys whose repo is cloned locally (existing code)

Usage:
    python tools/check_contracts.py --repos <folder with clones> [--contracts contracts] [--pins]

`--pins` also reports whether each clone's HEAD matches the commit recorded in the contract.
Exit code 1 if any check fails.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

import yaml

FILE_KEYS = ("path", "then", "config", "mapping", "mapping_file")


def clone_dir(repos: Path, repo: str) -> Path:
    return repos / repo.split("/")[-1]


def csv_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [c.strip() for c in next(csv.reader(f))]


def xlsx_header(path: Path, sheet: str) -> list[str]:
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True)
    if sheet not in wb.sheetnames:
        raise KeyError(f"sheet '{sheet}' missing (has {wb.sheetnames})")
    row = next(wb[sheet].iter_rows(max_row=1, values_only=True))
    return [str(c).strip() for c in row if c is not None]


def walk(node, trail=()):
    if isinstance(node, dict):
        yield node, trail
        for k, v in node.items():
            yield from walk(v, trail + (str(k),))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, trail + (str(i),))


def check_contract(path: Path, repos: Path, pins: bool) -> list[tuple[str, str, str]]:
    contract = yaml.safe_load(path.read_text(encoding="utf-8"))
    results = []
    source_repo = contract["source"]["repo"]

    if pins:
        pinned = {source_repo: contract["source"]["commit"]}
        for rel in contract.get("related_repos", []):
            pinned[rel["repo"]] = rel["commit"]
        for repo, commit in pinned.items():
            d = clone_dir(repos, repo)
            if not d.exists():
                results.append(("MISSING", repo, "no local clone"))
                continue
            head = subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
            results.append(("OK" if head == commit else "CHANGED", repo, f"pinned {commit[:7]}, clone at {head[:7]}"))

    seen = set()
    for node, trail in walk(contract):
        repo = node.get("repo", source_repo)
        if not isinstance(repo, str) or "/" not in repo:
            continue
        candidates = []
        if node.get("in_repo") is True:
            candidates.append(node.get("check_path", node.get("path")))
        elif "repo" in node:
            candidates += [node[k] for k in FILE_KEYS if isinstance(node.get(k), str)]
            candidates += [p for p in node.get("chain", []) + node.get("paths", []) if isinstance(p, str)]
        for rel in candidates:
            if not rel or "<" in rel or "*" in rel:
                continue
            key = (repo, rel, node.get("sheet"))
            if key in seen:
                continue
            seen.add(key)
            d = clone_dir(repos, repo)
            label = f"{repo}:{rel}" + (f" [{node['sheet']}]" if node.get("sheet") else "")
            if not d.exists():
                results.append(("SKIP", label, "no local clone"))
                continue
            f = d / rel
            if not f.exists():
                results.append(("FAIL", label, "file not found"))
                continue
            cols = [str(c) for c in node.get("columns", [])] if node.get("in_repo") is True else []
            if cols:
                try:
                    header = xlsx_header(f, node["sheet"]) if node.get("sheet") else csv_header(f)
                except Exception as exc:  # noqa: BLE001 - report, don't stop
                    results.append(("FAIL", label, str(exc)))
                    continue
                missing = [c for c in cols if c not in header]
                if missing:
                    results.append(("FAIL", label, f"missing columns {missing}; header {header[:12]}"))
                    continue
                results.append(("OK", label, f"exists; columns {cols} present"))
            else:
                results.append(("OK", label, "exists"))
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repos", type=Path, required=True)
    parser.add_argument("--contracts", type=Path, default=Path(__file__).resolve().parent.parent / "contracts")
    parser.add_argument("--pins", action="store_true")
    args = parser.parse_args(argv)

    failed = False
    for path in sorted(args.contracts.glob("*.yaml")):
        print(f"\n== {path.name}")
        for status, label, detail in check_contract(path, args.repos, args.pins):
            failed |= status in ("FAIL", "MISSING")
            print(f"  {status:8} {label}  ({detail})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
