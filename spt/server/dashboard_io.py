"""Bounded, read-only source loading for the operations dashboard."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import math
import re
from pathlib import Path
from typing import Any

MAX_SOURCE_BYTES = 2 * 1024 * 1024
ACCOUNT_METRICS = (
    "followers", "views", "reach", "non_follower_reach", "interactions",
    "likes", "comments", "saves", "shares", "profile_visits", "page_visits",
    "follows_gained", "link_clicks", "minutes_viewed", "three_second_views",
)
PLATFORM_LABELS = {
    "rednote": "rednote", "instagram": "Instagram", "facebook": "Facebook",
    "tiktok": "TikTok", "google_business_profile": "Google 商家资料",
    "yelp": "Yelp",
}


def platform_id(value: str) -> str:
    aliases = {"xiaohongshu": "rednote", "google_business":
               "google_business_profile"}
    return aliases.get(value, value)


def read_source(path: Path) -> str:
    with path.open("rb") as source:
        content = source.read(MAX_SOURCE_BYTES + 1)
    if len(content) > MAX_SOURCE_BYTES:
        raise ValueError("来源超过2MiB，未读取")
    return content.decode("utf-8-sig")


def read_json(path: Path) -> Any:
    return json.loads(read_source(path))


def read_csv(path: Path) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(read_source(path)))
    return [{key: value or "" for key, value in row.items()
             if key is not None} for row in reader]


def number(value: str | None) -> int | float | None:
    text = (value or "").strip().replace(",", "")
    if len(text) > 64 or not re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return None
    result = float(text)
    if not math.isfinite(result):
        return None
    return int(result) if result.is_integer() else result


def known_text(value: str | None) -> str | None:
    text = (value or "").strip()
    unknown = {"", "unknown", "unavailable", "null", "none", "--", "‑‑"}
    return None if text.lower() in unknown else text


def identifier(*values: str) -> str:
    return hashlib.sha256("\0".join(values).encode()).hexdigest()[:20]


def observed_at(notes: str) -> str | None:
    pattern = (r"(?:observed_at|captured_at)\s*=\s*"
               r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
               r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)")
    match = re.search(pattern, notes)
    return match.group(1) if match else None


def load_optional(path: Path, kind: str,
                  issues: list[dict[str, str]]) -> Any:
    try:
        if kind == "csv":
            return read_csv(path)
        if kind == "json":
            return read_json(path)
        return read_source(path)
    except (OSError, ValueError, UnicodeError, csv.Error):
        issues.append({"source": str(path), "error": "来源暂不可读"})
        return [] if kind in {"csv", "json"} else ""
