"""Previously checked source notes and dated local candidates, not a feed."""
from __future__ import annotations
import datetime as dt
from pathlib import Path
from typing import Any

from .dashboard_io import load_optional
from .timezones import pacific


def intelligence(project_root: Path, rows: list[dict[str, str]],
                 issues: list[dict[str, str]]) -> dict[str, Any]:
    path = Path(__file__).with_name("dashboard_sources.json")
    saved = load_optional(path, "json", issues) if path.exists() else {}
    if not isinstance(saved, dict):
        saved = {}
    candidates = [candidate(row) for row in rows]
    today = dt.datetime.now(pacific()).date().isoformat()
    active = [item for item in candidates if item["status"] == "candidate"
              and item["expires_at"] and item["expires_at"] >= today]
    return {
        "news": saved.get("news", []), "research": saved.get("research", []),
        "as_of": saved.get("checked_at"), "live": False,
        "source": str(path), "candidate_count": len(candidates),
        "candidate_active_count": len(active),
        "candidate_label": "历史线索", "candidates": candidates,
        "source_document": (str(project_root / saved["source_document"])
                            if saved.get("source_document") else None),
    }


def candidate(row: dict[str, str]) -> dict[str, Any]:
    return {
        "id": row.get("trend_id"), "title": row.get("topic"),
        "captured_at": row.get("captured_at"), "platform": row.get("platform"),
        "url": row.get("source_url") or None, "status": row.get("status"),
        "expires_at": row.get("expires_at") or None,
        "notes": row.get("notes", ""),
    }
