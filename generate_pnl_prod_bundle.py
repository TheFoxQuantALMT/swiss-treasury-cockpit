#!/usr/bin/env python3
"""generate_pnl_prod_bundle.py — Production-only PnL bundle.

Builds a single text file that deploys the minimum set of modules needed to
run ``uv run cockpit render-pnl`` on the prod PC (the one with WASP reachable,
no Claude Code, no internet fetchers).

Compared to the generic ``generate_bundles.py`` this bundle:
  * Excludes every path touched by the mock WIRP-curve fallback — prod must
    fail loud when WASP is unreachable, never silently use a mock.
  * Excludes agents / web fetchers / HTML cockpit renderer / Notion — the
    daily PnL pipeline only reads Excel inputs and writes xlsx/html/pdf.
  * Ships ``scripts/wasp_preflight.py`` so the pipeline can verify WASP
    before burning time on a full run.
  * Refuses to include any file whose path contains ``mock`` or lives under
    ``tests/`` — belt-and-braces guard against accidentally shipping dev code.

Usage:
    python generate_pnl_prod_bundle.py           # writes pnl_prod_bundle.txt
    python generate_pnl_prod_bundle.py --output custom.txt
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path


# ---------------------------------------------------------------------------
# Inclusion / exclusion rules
# ---------------------------------------------------------------------------

# Roots to scan (project-relative). Missing paths are silently skipped so the
# generator keeps working during refactors — the extractor summary surfaces it.
INCLUDE_ROOTS: list[tuple[str, tuple[str, ...]]] = [
    ("src/pnl_engine", (".py",)),
    ("src/cockpit", (".py", ".html", ".jinja", ".css", ".js")),
    ("config", (".yaml",)),
    ("scripts", (".py",)),
    ("pyproject.toml", ()),  # single file
]

# Paths (substring match on POSIX-form relative path) that must never enter
# the prod bundle. Keep the list explicit — new devs should see it and ask.
EXCLUDE_SUBSTRINGS: tuple[str, ...] = (
    "/tests/",
    "/__pycache__/",
    "/src/cockpit/agents/",
    "/src/cockpit/data/fetchers/",
    "/src/cockpit/data/manager.py",
    "/src/cockpit/render/",
    "/src/cockpit/integrations/notion_export.py",
    # Mock-curve guard: any dev helper must stay in tests/ — this is the
    # last line of defense if someone forgets.
    "mock_curves",
    "_mock_",
)


EXTRACTOR_SCRIPT = r'''#!/usr/bin/env python3
"""extract_pnl_prod_bundle.py — Recreates the PnL prod layout from the bundle.

Usage:
    python extract_pnl_prod_bundle.py [--bundle pnl_prod_bundle.txt] [--output-dir .]
"""
import argparse
import sys
from pathlib import Path


def extract(bundle_path: str, output_dir: str) -> None:
    bundle = Path(bundle_path)
    out = Path(output_dir)

    if not bundle.exists():
        print(f"ERROR: bundle file not found: {bundle}")
        sys.exit(1)

    lines = bundle.read_text(encoding="utf-8").splitlines()

    current_file = None
    file_lines: list[str] = []
    files_written = 0

    for line in lines:
        if line.startswith("===FILE START=== "):
            current_file = line[len("===FILE START=== "):]
            file_lines = []
        elif line.startswith("===FILE END=== ") and current_file is not None:
            if file_lines and file_lines[-1] == "":
                file_lines.pop()
            dest = out / current_file
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("\n".join(file_lines) + "\n", encoding="utf-8")
            files_written += 1
            print(f"  {current_file}")
            current_file = None
            file_lines = []
        elif current_file is not None:
            file_lines.append(line)

    print(f"\nExtracted {files_written} files into '{out}/'")
    print("\nNext steps on prod:")
    print("  1. uv sync                                  # install deps")
    print("  2. python scripts/wasp_preflight.py --date YYYY-MM-DD")
    print("     (must exit 0 — if not, DO NOT run the pipeline)")
    print("  3. uv run cockpit render-pnl --date YYYY-MM-DD --input-dir <path>")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract PnL prod bundle")
    parser.add_argument("--bundle", default="pnl_prod_bundle.txt")
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()
    extract(args.bundle, args.output_dir)
'''


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def _to_posix(p: Path) -> str:
    return str(p).replace(os.sep, "/")


def _collect_files(project_root: Path) -> list[Path]:
    seen: set[Path] = set()
    for rel_root, extensions in INCLUDE_ROOTS:
        abs_root = project_root / rel_root
        if not abs_root.exists():
            print(f"  [skip missing] {rel_root}", file=sys.stderr)
            continue

        if abs_root.is_file():
            seen.add(abs_root.resolve())
            continue

        for ext in extensions or ("",):
            pattern = f"*{ext}" if ext else "*"
            for f in abs_root.rglob(pattern):
                if f.is_file():
                    seen.add(f.resolve())

    # Filter out excluded paths
    filtered: list[Path] = []
    dropped: list[Path] = []
    for f in seen:
        rel = "/" + _to_posix(f.relative_to(project_root))
        if any(sub in rel for sub in EXCLUDE_SUBSTRINGS):
            dropped.append(f)
        else:
            filtered.append(f)

    if dropped:
        print(f"  [excluded by policy] {len(dropped)} file(s):", file=sys.stderr)
        for d in sorted(dropped):
            print(f"    - {_to_posix(d.relative_to(project_root))}", file=sys.stderr)

    return sorted(filtered, key=lambda p: _to_posix(p))


# ---------------------------------------------------------------------------
# Safety tripwires
# ---------------------------------------------------------------------------

def _assert_no_mock_runtime(files: list[Path], project_root: Path) -> None:
    """Fail fast if production files still reference the mock-curve helper.

    A stray ``_mock_curves_from_wirp`` import in a prod-bundled file would
    ImportError the whole pipeline on the prod PC — better to catch it here.
    """
    offenders: list[tuple[str, int, str]] = []
    for f in files:
        if f.suffix != ".py":
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for ln, line in enumerate(text.splitlines(), start=1):
            if "_mock_curves_from_wirp" in line:
                offenders.append((_to_posix(f.relative_to(project_root)), ln, line.strip()))

    if offenders:
        print("\nERROR: production files still reference the mock-curve helper.", file=sys.stderr)
        print("Move the import into tests/ or delete the reference before bundling:\n", file=sys.stderr)
        for path, ln, line in offenders:
            print(f"  {path}:{ln}: {line}", file=sys.stderr)
        sys.exit(2)


# ---------------------------------------------------------------------------
# Bundling
# ---------------------------------------------------------------------------

def _write_bundle(output_path: Path, files: list[Path], project_root: Path) -> None:
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("PNL_PROD BUNDLE — swiss-treasury-cockpit")
    lines.append(f"Generated: {date.today().isoformat()}")
    lines.append(f"Files: {len(files)}")
    lines.append("=" * 60)
    lines.append("")
    lines.append('STEP 1: Save this entire file as "pnl_prod_bundle.txt"')
    lines.append("STEP 2: Copy the extractor script below into extract_pnl_prod_bundle.py")
    lines.append("STEP 3: python extract_pnl_prod_bundle.py --output-dir <target>")
    lines.append("STEP 4: python scripts/wasp_preflight.py --date YYYY-MM-DD  (must exit 0)")
    lines.append("STEP 5: uv run cockpit render-pnl --date YYYY-MM-DD --input-dir <path>")
    lines.append("")
    lines.append("=" * 60)
    lines.append("===EXTRACTOR START===")
    lines.append(EXTRACTOR_SCRIPT.strip())
    lines.append("===EXTRACTOR END===")
    lines.append("")

    for f in files:
        rel = _to_posix(f.relative_to(project_root))
        content = f.read_text(encoding="utf-8", errors="replace")
        lines.append(f"===FILE START=== {rel}")
        lines.append(content)
        if not content.endswith("\n"):
            lines.append("")
        lines.append(f"===FILE END=== {rel}")
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="pnl_prod_bundle.txt",
                        help="Output bundle path (default: pnl_prod_bundle.txt)")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent
    files = _collect_files(project_root)
    _assert_no_mock_runtime(files, project_root)

    output_path = Path(args.output)
    _write_bundle(output_path, files, project_root)

    print(f"\nWrote {output_path}: {len(files)} files")
    print("Sample contents:")
    for f in files[:10]:
        print(f"  {_to_posix(f.relative_to(project_root))}")
    if len(files) > 10:
        print(f"  ... and {len(files) - 10} more")


if __name__ == "__main__":
    main()
