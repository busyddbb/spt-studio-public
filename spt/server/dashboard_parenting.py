"""Read the explicitly dated parenting handoff without inventing samples."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any

from .dashboard_accounts import empty_metrics, use_snapshot
from .dashboard_io import identifier, number


def parenting_snapshot(text: str, source: Path) -> dict[str, Any] | None:
    pattern = (r"最近已报账号：(\d+)粉、(\d+)关注、赞藏圆整显示"
               r"([\d.]+[KMB])，原观察"
               r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) PDT")
    match = re.search(pattern, text)
    if not match:
        return None
    metrics = empty_metrics()
    metrics["followers"] = int(match[1])
    return {
        "date": match[4], "observed_at": match[4] + "T" + match[5] + "-07:00",
        "window_start": None, "window_end": None, "metrics": metrics,
        "display_metrics": {"likes_and_saves": match[3]},
        "following": int(match[2]), "status": "source_handoff_only",
        "source": str(source), "source_label": "本地接收的旧时点摘要",
        "notes": "原快照与平台证据尚未交；不代表当前实时数据",
    }


def attach_parenting(accounts: list[dict[str, Any]], text: str,
                     source: Path) -> None:
    snapshot = parenting_snapshot(text, source)
    if snapshot is None:
        return
    for item in accounts:
        if item["id"] == "parenting:rednote":
            use_snapshot(item, snapshot)
            item["history"] = [snapshot]


def parenting_posts(text: str, source: Path) -> list[dict[str, Any]]:
    result = []
    year_match = re.search(r"原观察(\d{4})-", text)
    year = year_match.group(1) if year_match else None
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 8 or not re.fullmatch(r"\d+ D[137]", cells[0]):
            continue
        if any(number(cell) is None for cell in cells[1:6]):
            continue
        result.append(parenting_post(cells, source, year))
    return result


def parenting_post(cells: list[str], source: Path,
                   year: str | None) -> dict[str, Any]:
    node, window = cells[0].split()
    metrics = {"views": number(cells[1]), "likes": number(cells[2]),
               "comments": number(cells[3]), "saves": number(cells[4]),
               "shares": number(cells[5]), "reach": None,
               "interactions": None, "avg_watch_time_sec": None,
               "completion_rate": None}
    stamp = node_time(cells[6], year)
    point = {"window": window, "metrics": metrics, "observed_at": stamp,
             "observed_label": cells[6], "age_note": cells[7],
             "source": str(source), "notes": "原节点JSON尚未交"}
    return {
        "id": identifier("parenting", "rednote", node),
        "account_id": "parenting:rednote", "content_id": node,
        "title": "第" + node + "篇", "caption": None,
        "caption_complete": False, "url": None, "published_at": None,
        "format": "image", "duration_sec": None, "status": "source_recorded",
        "current": True, "source_kind": "metric_node",
        "observed_at": stamp, "metrics": metrics,
        "metric_window": window, "metrics_by_window": {window: metrics},
        "metric_observed_at_by_window": {window: stamp},
        "history": [point], "source": str(source), "work_id": None,
        "cover": None, "preview_url": None,
        "issues": ["仅接到节点摘要，标题与线上身份未全部补齐"],
    }


def node_time(label: str, year: str | None) -> str | None:
    match = re.match(r"(\d{2})/(\d{2}) (\d{2}:\d{2}:\d{2})", label)
    if not year or not match:
        return None
    return f"{year}-{match[1]}-{match[2]}T{match[3]}-07:00"
