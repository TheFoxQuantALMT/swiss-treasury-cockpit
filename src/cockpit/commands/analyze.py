"""CLI command: generate LLM daily brief."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from cockpit.config import DATA_DIR
from cockpit.commands._helpers import load_json, save_json


def cmd_analyze(
    *,
    date: str,
    data_dir: Path = DATA_DIR,
    dry_run: bool = False,
) -> None:
    """Generate LLM daily brief using Ollama agents."""
    macro_path = data_dir / f"{date}_macro_snapshot.json"
    macro_data = load_json(macro_path)
    if macro_data is None:
        print(f"[analyze] Error: {macro_path} not found. Run 'cockpit fetch' first.")
        sys.exit(1)

    scores_path = data_dir / f"{date}_scores.json"
    scores_data = load_json(scores_path) or {}

    from cockpit.engine.comparison import compute_deltas, format_deltas_for_brief
    from cockpit.engine.alerts.alerts import check_alerts
    from cockpit.agents.analyst import _build_template, create_analyst_agent
    from cockpit.agents.reviewer import programmatic_check, create_reviewer_agent
    from cockpit.agents.reporter import generate_html_brief
    from cockpit.config import MAX_REVIEW_RETRIES

    deltas = scores_data.get("_deltas", compute_deltas(macro_data))
    alerts = scores_data.get("_alerts", check_alerts(macro_data, deltas))
    delta_table = format_deltas_for_brief(deltas)

    print(f"[analyze] Building analyst template for {date}...")
    template = _build_template(macro_data, deltas, delta_table, alerts)

    print("[analyze] Running analyst agent...")
    analyst = create_analyst_agent()
    brief_text = asyncio.run(analyst.run(template))

    print("[analyze] Running reviewer agent...")
    reviewer = create_reviewer_agent()
    reviewed = False
    for attempt in range(MAX_REVIEW_RETRIES):
        errors = programmatic_check(brief_text, macro_data)
        if not errors:
            reviewed = True
            break
        print(f"[analyze] Review attempt {attempt + 1}: {len(errors)} issues found, retrying...")
        brief_text = asyncio.run(analyst.run(template))

    brief_html = generate_html_brief(brief_text, macro_data, deltas)

    result = {
        "date": date,
        "reviewed": reviewed,
        "html": brief_html,
        "text": brief_text,
    }

    if not dry_run:
        output_path = data_dir / f"{date}_brief.json"
        save_json(result, output_path)
        print(f"[analyze] Saved brief to {output_path}")
    else:
        print("[analyze] Dry run — brief not saved.")
