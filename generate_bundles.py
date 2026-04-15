#!/usr/bin/env python3
"""generate_bundles.py — Regenerates cockpit_bundle.txt and pnl_engine_bundle.txt

Usage:
    python generate_bundles.py          # both bundles
    python generate_bundles.py cockpit  # cockpit only
    python generate_bundles.py pnl      # pnl_engine only
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

COCKPIT_EXTRACTOR = r'''#!/usr/bin/env python3
"""extract_bundle.py — Recreates the project structure from a bundle .txt file

Usage:
    python extract_bundle.py [--bundle cockpit_bundle.txt] [--output-dir output]

Reads this bundle file, finds all ===FILE START=== / ===FILE END=== blocks,
and writes each file to disk under the output directory.
"""
import argparse
import os
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract bundle")
    parser.add_argument("--bundle", default="cockpit_bundle.txt",
                        help="Path to the bundle .txt file")
    parser.add_argument("--output-dir", default="output",
                        help="Output directory (default: output)")
    args = parser.parse_args()
    extract(args.bundle, args.output_dir)
'''

PNL_EXTRACTOR = r'''#!/usr/bin/env python3
"""extract_bundle.py — Recreates the project structure from pnl_engine_bundle.txt

Usage:
    python extract_bundle.py [--bundle pnl_engine_bundle.txt] [--output-dir output]

Reads this bundle file, finds all ===FILE START=== / ===FILE END=== blocks,
and writes each file to disk under the output directory.
"""
import argparse
import os
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
    print(f"\nNext steps:")
    print(f"  cd {out}")
    print(f"  pip install numpy pandas openpyxl  # or: uv sync")
    print(f"  python -m tests.fixtures.generate_mock_inputs  # regenerate .xlsx fixtures")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract pnl_engine bundle")
    parser.add_argument("--bundle", default="pnl_engine_bundle.txt",
                        help="Path to the bundle .txt file (default: pnl_engine_bundle.txt)")
    parser.add_argument("--output-dir", default="output",
                        help="Output directory (default: output)")
    args = parser.parse_args()
    extract(args.bundle, args.output_dir)
'''


def make_bundle(
    title: str,
    step_text: list[str],
    extractor_script: str,
    source_dir: Path,
    extensions: list[str],
    output_path: str,
) -> None:
    files = []
    for ext in extensions:
        files.extend(source_dir.rglob(f"*{ext}"))
    files = sorted(set(files), key=lambda p: str(p).replace(os.sep, "/"))

    lines: list[str] = []
    lines.append("=" * 60)
    lines.append(f"{title} BUNDLE — swiss-treasury-cockpit")
    lines.append(f"Generated: {date.today().isoformat()}")
    lines.append("=" * 60)
    lines.append("")
    lines.extend(step_text)
    lines.append("")
    lines.append("=" * 60)
    lines.append("===EXTRACTOR START===")
    lines.append(extractor_script.strip())
    lines.append("===EXTRACTOR END===")
    lines.append("")
    lines.append(
        "To use: copy everything between ===EXTRACTOR START=== and ===EXTRACTOR END==="
    )
    lines.append(
        'into a file named "extract_bundle.py", then run: python extract_bundle.py'
    )
    lines.append("")

    for f in files:
        rel = str(f).replace(os.sep, "/")
        content = f.read_text(encoding="utf-8", errors="replace")
        lines.append(f"===FILE START=== {rel}")
        lines.append(content)
        if not content.endswith("\n"):
            lines.append("")
        lines.append(f"===FILE END=== {rel}")
        lines.append("")

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {output_path}: {len(files)} files")


def generate_cockpit() -> None:
    make_bundle(
        "COCKPIT",
        [
            'STEP 1: Save this entire file as "cockpit_bundle.txt"',
            "STEP 2: Run the extractor below:",
            "        python extract_bundle.py --bundle cockpit_bundle.txt",
        ],
        COCKPIT_EXTRACTOR,
        Path("src/cockpit"),
        [".py", ".html"],
        "cockpit_bundle.txt",
    )


def generate_pnl() -> None:
    make_bundle(
        "PNL_ENGINE",
        [
            'STEP 1: Save this entire file as "pnl_engine_bundle.txt"',
            "STEP 2: Run the extractor below:",
            "        python extract_bundle.py",
            "STEP 3: Regenerate Excel fixtures:",
            "        cd output/ && uv run python -m tests.fixtures.generate_mock_inputs",
        ],
        PNL_EXTRACTOR,
        Path("src/pnl_engine"),
        [".py"],
        "pnl_engine_bundle.txt",
    )


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"

    if target in ("all", "cockpit"):
        generate_cockpit()
    if target in ("all", "pnl"):
        generate_pnl()
    if target not in ("all", "cockpit", "pnl"):
        print(f"Unknown target: {target}")
        print("Usage: python generate_bundles.py [all|cockpit|pnl]")
        sys.exit(1)
