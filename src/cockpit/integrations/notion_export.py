"""Export ALCO Decision Pack to Notion via API.

Pushes the structured decision pack (executive summary, decisions required,
risk overview) as a Notion page under a specified parent database/page.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


def build_notion_blocks(decision_pack: dict, date_run: str) -> list[dict]:
    """Convert ALCO Decision Pack to Notion block format.

    Args:
        decision_pack: Dict from _build_alco_decision_pack().
        date_run: Date string for the page title.

    Returns:
        List of Notion API block objects.
    """
    blocks: list[dict] = []

    # Title/heading
    blocks.append({
        "object": "block",
        "type": "heading_1",
        "heading_1": {"rich_text": [{"type": "text", "text": {"content": f"ALCO Decision Pack — {date_run}"}}]},
    })

    # Executive summary
    if decision_pack.get("executive_summary"):
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Executive Summary"}}]},
        })
        for item in decision_pack["executive_summary"]:
            emoji = "🔴" if item.get("severity") == "critical" else "🟡"
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": f"{emoji} {item['text']}"}}]},
            })

    # Decisions required
    if decision_pack.get("decisions"):
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Decisions Required"}}]},
        })
        for dec in decision_pack["decisions"]:
            priority_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(dec["priority"], "⚪")
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": f"{priority_emoji} [{dec['topic']}] {dec['description']}"}}],
                },
            })

    # Counts
    blocks.append({
        "object": "block",
        "type": "divider",
        "divider": {},
    })
    blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {
                "content": f"Critical: {decision_pack.get('n_critical', 0)} | High: {decision_pack.get('n_high', 0)} | Medium: {decision_pack.get('n_medium', 0)}"
            }}],
        },
    })

    return blocks


def build_notion_page_properties(date_run: str, decision_pack: dict) -> dict:
    """Build Notion page properties for the decision pack.

    Returns dict suitable for the Notion Create Page API.
    """
    return {
        "Name": {"title": [{"text": {"content": f"ALCO Pack {date_run}"}}]},
        "Date": {"date": {"start": date_run}},
        "Status": {"select": {"name": "Open" if decision_pack.get("n_critical", 0) > 0 else "Review"}},
        "Priority": {"select": {"name": "Critical" if decision_pack.get("n_critical", 0) > 0 else "High" if decision_pack.get("n_high", 0) > 0 else "Normal"}},
    }


async def export_to_notion(
    decision_pack: dict,
    date_run: str,
    parent_page_id: str,
    notion_token: Optional[str] = None,
) -> dict:
    """Export decision pack to Notion (async).

    Args:
        decision_pack: Dict from _build_alco_decision_pack().
        date_run: Date string.
        parent_page_id: Notion parent page/database ID.
        notion_token: Notion integration token (or from env NOTION_TOKEN).

    Returns:
        Dict with page_id and url of created page.
    """
    import os
    token = notion_token or os.environ.get("NOTION_TOKEN", "")
    if not token:
        return {"success": False, "error": "No Notion token provided"}

    blocks = build_notion_blocks(decision_pack, date_run)
    properties = build_notion_page_properties(date_run, decision_pack)

    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.notion.com/v1/pages",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Notion-Version": "2022-06-28",
                },
                json={
                    "parent": {"page_id": parent_page_id},
                    "properties": properties,
                    "children": blocks,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return {"success": True, "page_id": data["id"], "url": data["url"]}
    except Exception as e:
        return {"success": False, "error": str(e)}
