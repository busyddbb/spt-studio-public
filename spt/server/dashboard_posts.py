"""Normalize post identity, cohorts, unknown values and withdrawal history."""
from __future__ import annotations
from collections import defaultdict
import datetime as dt
from pathlib import Path
from typing import Any

from .dashboard_io import (
    identifier, known_text, number, observed_at, platform_id,
)

WINDOWS = {"D1": "24h", "D3": "72h", "D7": "7d"}
POST_METRICS = (
    "views", "reach", "interactions", "saves", "shares", "comments",
    "profile_visits", "follows", "link_clicks", "minutes_viewed",
    "three_second_views", "avg_watch_time_sec",
    "likes", "completion_rate",
)


def metric_windows(row: dict[str, str]) -> dict[str, dict[str, Any]]:
    return {
        label: {name: number(row.get(name + "_" + suffix))
                for name in POST_METRICS}
        for label, suffix in WINDOWS.items()
    }


def choose_window(windows: dict[str, dict[str, Any]]) -> str | None:
    for label in ("D7", "D3", "D1"):
        if any(value is not None for value in windows[label].values()):
            return label
    return None


def post_snapshot(row: dict[str, str], source: Path) -> dict[str, Any]:
    return {"observed_at": observed_at(row.get("notes", "")),
            "metrics_by_window": metric_windows(row),
            "source": str(source), "status": row.get("status"),
            "notes": row.get("notes", "")}


def group_posts(rows: list[dict[str, str]]
                ) -> list[list[dict[str, str]]]:
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = platform_id(row.get("platform", "")), row.get("content_id", "")
        groups[key].append(row)
    result = []
    for group in groups.values():
        urls = {row.get("url") for row in group if known_text(row.get("url"))}
        if len(urls) <= 1:
            result.append(group)
        else:
            by_url: dict[str, list[dict[str, str]]] = defaultdict(list)
            for row in group:
                by_url[row.get("url", "")].append(row)
            result.extend(by_url.values())
    return result


def combine_windows(rows: list[dict[str, str]]
                    ) -> dict[str, dict[str, Any]]:
    combined = metric_windows({})
    for row in rows:
        for label, values in metric_windows(row).items():
            if any(value is not None for value in values.values()):
                combined[label] = values
    return combined


def window_times(rows: list[dict[str, str]]) -> dict[str, str | None]:
    selected: dict[str, str | None] = dict.fromkeys(WINDOWS)
    for row in rows:
        for label, values in metric_windows(row).items():
            if any(value is not None for value in values.values()):
                selected[label] = observed_at(row.get("notes", ""))
    return selected


def normalize_post(rows: list[dict[str, str]], source: Path
                   ) -> dict[str, Any]:
    ordered = sorted(enumerate(rows), key=observation_key)
    history_rows = [row for _, row in ordered]
    latest = rows[-1]
    channel = platform_id(latest.get("platform", ""))
    content_id = latest.get("content_id", "")
    url = known_text(latest.get("url"))
    windows = combine_windows(history_rows)
    window = choose_window(windows)
    post = post_fact(latest, content_id, channel, url, windows, window,
                     [post_snapshot(row, source) for row in history_rows],
                     source)
    post["metric_observed_at_by_window"] = window_times(history_rows)
    post["observed_at"] = window_times(history_rows).get(window)
    return post


def observation_key(pair: tuple[int, dict[str, str]]) -> tuple[float, int]:
    index, row = pair
    stamp = observed_at(row.get("notes", ""))
    if not stamp:
        return float("-inf"), index
    try:
        value = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        value = value.replace(tzinfo=value.tzinfo or dt.timezone.utc)
        return value.timestamp(), index
    except ValueError:
        return float("-inf"), index


def post_fact(row: dict[str, str], content_id: str, channel: str,
              url: str | None, windows: dict[str, dict[str, Any]],
              window: str | None, history: list[dict[str, Any]],
              source: Path) -> dict[str, Any]:
    title = known_text(row.get("dish")) or content_id
    return {
        "id": identifier("demo-brand", channel, url or content_id),
        "account_id": "demo-brand:" + channel,
        "content_id": content_id, "title": title,
        "caption": known_text(row.get("caption_opener")),
        "caption_complete": False, "url": url,
        "published_at": known_text(row.get("published_at")),
        "format": row.get("format") or None,
        "duration_sec": number(row.get("duration_sec")),
        "status": row.get("status") or "unknown",
        "current": row.get("status") == "published",
        "source_kind": "post_record",
        "observed_at": history[-1]["observed_at"],
        "metrics": windows[window] if window else empty_post_metrics(),
        "metric_window": window, "metrics_by_window": windows,
        "history": history, "source": str(source), "work_id": None,
        "cover": None, "preview_url": None, "issues": [],
    }


def empty_post_metrics() -> dict[str, None]:
    return dict.fromkeys((*POST_METRICS, "likes", "completion_rate"))


def normalize_posts(rows: list[dict[str, str]],
                    source: Path) -> list[dict[str, Any]]:
    return [normalize_post(group, source) for group in group_posts(rows)]
