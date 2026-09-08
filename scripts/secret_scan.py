"""Secret scanner for the keyrotor repo (rule #1: NO SECRETS in git).

Reuses keyrotor.redact.find_secrets() as the single source of truth for
secret patterns. Scans every text file in the repo and reports only the
KINDS of secrets found (never the values) plus a per-file count.

Exit codes:
    0  clean
    1  at least one secret-looking value found

Usage:
    python scripts/secret_scan.py
    python scripts/secret_scan.py /path/to/repo

The scan root defaults to the repo root (parent of scripts/) and can be
overridden with the KEYROTOR_SCAN_ROOT environment variable or the first
positional argument.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(
    os.environ.get(
        "KEYROTOR_SCAN_ROOT",
        Path(__file__).resolve().parent.parent,
    )
)

sys.path.insert(0, str(REPO_ROOT))

from keyrotor.redact import find_secrets  # noqa: E402

SKIP_DIRS = {
    ".git",
    "__pycache__",
    "unified",
    ".pytest_cache",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    ".eggs",
    "*.egg-info",
}

SKIP_FILES = {"repos.json"}

SKIP_SUFFIXES = {".pyc", ".pyo", ".exe", ".dll", ".so", ".png", ".jpg", ".ico"}

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".html",
    ".toml",
    ".yml",
    ".yaml",
    ".json",
    ".txt",
    ".ini",
    ".cfg",
}


def should_scan(path: Path) -> bool:
    if path.name in SKIP_FILES:
        return False
    if path.suffix in SKIP_SUFFIXES:
        return False
    parts = path.relative_to(REPO_ROOT).parts
    for part in parts[:-1]:
        if part in SKIP_DIRS:
            return False
    if path.name == ".env.example" or path.suffix in TEXT_SUFFIXES:
        return True
    return False


def scan(repo_root: Path) -> Dict[Path, Dict[str, int]]:
    findings: Dict[Path, Dict[str, int]] = {}
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file() or not should_scan(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        found = find_secrets(text)
        if not found:
            continue
        kinds: Dict[str, int] = {}
        for kind, _masked in found:
            kinds[kind] = kinds.get(kind, 0) + 1
        findings[path] = kinds
    return findings


def main(argv: List[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else REPO_ROOT
    if not root.is_dir():
        print(f"scan root not found: {root}", file=sys.stderr)
        return 2

    findings = scan(root)
    if not findings:
        print("SECRET SCAN: CLEAN")
        return 0

    print("SECRET SCAN: FOUND SECRET-LIKE VALUES")
    total = 0
    for path in sorted(findings):
        kinds = findings[path]
        count = sum(kinds.values())
        total += count
        rel = path.relative_to(root)
        detail = ", ".join(f"{kind}x{n}" for kind, n in sorted(kinds.items()))
        print(f"  {rel}: {count} matches ({detail})")
    print(f"TOTAL: {total} matches in {len(findings)} files")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
