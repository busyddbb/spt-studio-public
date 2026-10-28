"""Account definitions and historical snapshots, never login assertions."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any

from .dashboard_io import (
    ACCOUNT_METRICS, PLATFORM_LABELS, load_optional, number, observed_at,
    platform_id,
)


def definitions(projects: list[dict[str, Any]], registry: dict[str, Any]
                ) -> list[dict[str, Any]]:
    accounts = []
    registered = {item.get("id"): item
                  for item in registry.get("platforms", [])}
    for project in projects:
        if project.get("kind") != "account":
            continue
        channels = list(project.get("channels", []))
        if project["id"] == "demo-brand":
            channels = registry.get("current_management_targets", channels)
        for channel in dict.fromkeys(map(platform_id, channels)):
            entry = registered.get(channel, {})
            accounts.append(account(project, channel, entry))
    return accounts


def account(project: dict[str, Any], channel: str,
            entry: dict[str, Any]) -> dict[str, Any]:
    name = project["name"].split(" · ")[0]
    return {
        "id": project["id"] + ":" + channel, "brand_id": project["id"],
        "brand": name, "name": name, "platform": channel,
        "platform_label": PLATFORM_LABELS.get(channel, channel),
        "handle": public_handle(project["id"], channel, entry),
        "profile_url": profile_url(project["id"], channel, entry),
        "readonly": False,
        "login_state": "not_checked", "data_state": "unavailable",
        "as_of": None, "source": None, "metrics": empty_metrics(),
        "display_metrics": {}, "window_start": None, "window_end": None,
        "history": [], "latest_snapshot": None, "posts_count": 0,
        "posts_count_kind": "indexed_records",
    }


def empty_metrics() -> dict[str, int | float | None]:
    return dict.fromkeys(ACCOUNT_METRICS)


def display_metrics(row: dict[str, str]) -> dict[str, str]:
    displayed = {}
    notes = row.get("notes", "")
    if platform_id(row.get("platform", "")) != "facebook":
        return displayed
    for name in ("views",):
        if number(row.get(name)) is not None:
            continue
        match = re.search(r"\b" + name + r"\s*=\s*([\d.]+[KMB])",
                          notes, re.IGNORECASE)
        if match:
            displayed[name] = match.group(1)
    return displayed


def public_handle(brand: str, channel: str,
                  entry: dict[str, Any]) -> str | None:
    if brand == "parenting" and channel == "rednote":
        return profile_url(brand, channel, entry)
    value = entry.get("account_identity")
    if channel == "google_business_profile" and "@" in (value or ""):
        return None
    return value


def profile_url(brand: str, channel: str,
                entry: dict[str, Any]) -> str | None:
    if entry.get("public_profile_url"):
        return entry["public_profile_url"]
    value = entry.get("account_identity") or ""
    if channel == "instagram" and re.fullmatch(r"[\w.]+", value):
        return "https://www.instagram.com/" + value + "/"
    if channel == "tiktok" and re.fullmatch(r"[\w.]+", value):
        return "https://www.tiktok.com/@" + value
    return None


def account_snapshot(row: dict[str, str], source: Path) -> dict[str, Any]:
    return {
        "date": row.get("date") or None,
        "observed_at": observed_at(row.get("notes", "")),
        "window_start": row.get("window_start") or None,
        "window_end": row.get("window_end") or None,
        "metrics": {name: number(row.get(name)) for name in ACCOUNT_METRICS},
        "display_metrics": display_metrics(row),
        "status": row.get("status") or None,
        "source": str(source), "source_label": row.get("source") or None,
        "notes": row.get("notes", ""),
    }


def attach_snapshots(accounts: list[dict[str, Any]],
                     rows: list[dict[str, str]], source: Path) -> None:
    for item in accounts:
        if item["brand_id"] != "demo-brand":
            continue
        history = [account_snapshot(row, source) for row in rows
                   if platform_id(row.get("platform", "")) == item["platform"]]
        history.sort(key=lambda snap: (snap["date"] or "",
                                      snap["observed_at"] or ""))
        item["history"] = history
        if history:
            use_snapshot(item, history[-1])


def use_snapshot(item: dict[str, Any], snapshot: dict[str, Any]) -> None:
    item.update({
        "as_of": snapshot["observed_at"] or snapshot["date"],
        "source": snapshot["source"], "metrics": snapshot["metrics"],
        "display_metrics": snapshot["display_metrics"],
        "window_start": snapshot["window_start"],
        "window_end": snapshot["window_end"], "latest_snapshot": snapshot,
        "data_state": "historical",
    })


def load_registry(root: Path, issues: list[dict[str, str]]) -> dict[str, Any]:
    path = root / "系统（不用看）/总控/平台登记.json"
    value = load_optional(path, "json", issues)
    return value if isinstance(value, dict) else {}
