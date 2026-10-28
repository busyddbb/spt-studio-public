"""Read-only bridge: CSV imports and 发布记录 numbers from the legacy DB.

Only the ``observations`` table is read (never ``ops_metrics``: voiding a
receipt deletes its observations, so those numbers must not come back).
Posts come out shaped like ``spt.server.dashboard_posts`` posts so the
数据 and 运营 pages render them without special cases.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spt.server.dashboard_accounts import empty_metrics
from spt.server.dashboard_io import (
    PLATFORM_LABELS, identifier, number, platform_id,
)
from spt.server.dashboard_posts import WINDOWS, empty_post_metrics
from spt.server.timezones import pacific

if __package__:
    from . import core
else:
    import core

LOCAL = pacific()   # ZoneInfo, or the built-in US rules on Windows without tzdata
WINDOW_AGES = {1: "D1", 3: "D3", 7: "D7"}
SOCIAL_METRICS = ("views", "reach", "likes", "comments", "shares", "saves",
                  "clicks")
RECEIPT = "manual_receipt"
# Dashboard platform ids → the ids the legacy DB stores (and back).
LEGACY_PLATFORMS = {"rednote": "xiaohongshu",
                    "google_business_profile": "google_business"}


def legacy_platform(value: str) -> str:
    return LEGACY_PLATFORMS.get(value, value)


# ---------------------------------------------------------------- reading

def read_rows(database: Path, query: str) -> list[tuple[Any, ...]]:
    """Run one SELECT over a read-only connection; [] when unreadable.

    The system SQLite (Python 3.9) refuses ``mode=ro`` on a WAL database
    whose -shm/-wal files are absent. Nothing has the database open then,
    so an immutable view of the main file is complete and safe.
    """
    if not database.is_file():
        return []
    uri = database.as_uri() + "?mode=ro"
    for suffix in ("", "&immutable=1"):
        try:
            with closing(sqlite3.connect(uri + suffix, uri=True)) as connection:
                return connection.execute(query).fetchall()
        except sqlite3.OperationalError as error:
            if suffix or "unable to open" not in str(error):
                return []
        except sqlite3.Error:
            return []
    return []


def read_observations(database: Path
                      ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Social and ads payloads in capture order; empty when unreadable."""
    rows = read_rows(database, "SELECT kind,payload FROM observations "
                     "WHERE dataset='real' ORDER BY observed_at,rowid")
    social: list[dict[str, Any]] = []
    ads: list[dict[str, Any]] = []
    for kind, payload in rows:
        try:
            item = json.loads(payload)
        except (TypeError, ValueError):
            continue
        if isinstance(item, dict) and kind in ("social", "ads"):
            (social if kind == "social" else ads).append(item)
    return social, ads


def local_time(value: Any) -> dt.datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(LOCAL)


def local_iso(moment: dt.datetime | None) -> str | None:
    return moment.isoformat(timespec="seconds") if moment else None


def numeric(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    return number(str(value))


def text(value: Any) -> str | None:
    result = str(value or "").strip()
    return result or None


def content_key(value: Any) -> str | None:
    result = str(value or "").strip().rstrip("/")
    return result or None


def handle_key(value: Any) -> str | None:
    result = str(value or "").strip().lower().rstrip("/")
    for prefix in ("https://", "http://", "www.", "@"):
        if result.startswith(prefix):
            result = result[len(prefix):]
    return result or None


def has_values(metrics: dict[str, Any] | None) -> bool:
    return any(value is not None for value in (metrics or {}).values())


def post_metrics(item: dict[str, Any]) -> dict[str, Any]:
    metrics = legacy_empty_metrics()
    for name in SOCIAL_METRICS:
        metrics[name] = numeric(item.get(name))
    return metrics


def legacy_empty_metrics() -> dict[str, Any]:
    metrics: dict[str, Any] = empty_post_metrics()
    metrics["clicks"] = None
    return metrics


# ---------------------------------------------------------------- records

def social_record(index: int, item: dict[str, Any]
                  ) -> dict[str, Any] | None:
    observed = local_time(item.get("observed_at"))
    platform = text(item.get("platform"))
    post_id = content_key(item.get("post_id"))
    if observed is None or not platform or not post_id:
        return None
    published = local_time(item.get("published_at"))
    age = (observed.date() - published.date()).days if published else None
    url = text(item.get("url"))
    if url and not url.startswith(("https://", "http://")):
        url = None
    keys = [(platform, post_id)]
    if url and (platform, content_key(url)) not in keys:
        keys.append((platform, content_key(url)))
    return {
        "index": index, "platform": platform, "keys": keys,
        "account": text(item.get("account")) or "", "post_id": post_id,
        "url": url, "title": text(item.get("title")),
        "published": published, "published_at": local_iso(published),
        "observed": observed, "observed_at": local_iso(observed),
        "window": WINDOW_AGES.get(age) if age is not None else None,
        "metrics": post_metrics(item),
        "receipt": item.get("source_type") == RECEIPT,
        "source": text(item.get("source")),
    }


def group_records(records: list[dict[str, Any]]
                  ) -> list[list[dict[str, Any]]]:
    """Observations sharing a platform + post id or URL are one post."""
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(key: tuple[str, str]) -> tuple[str, str]:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for record in records:
        for key in record["keys"]:
            parent.setdefault(key, key)
        first = find(record["keys"][0])
        for key in record["keys"][1:]:
            parent[find(key)] = first
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault(find(record["keys"][0]), []).append(record)
    return [sorted(group, key=lambda item: (item["observed"], item["index"]))
            for group in groups.values()]


def window_picks(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per window the whole latest observation; a receipt beats a CSV row."""
    picks: dict[str, dict[str, Any]] = {}
    for record in records:
        label = record["window"]
        if not label:
            continue
        current = picks.get(label)
        if current is None or ((record["receipt"], record["observed"])
                               >= (current["receipt"], current["observed"])):
            picks[label] = record
    return picks


def facts(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Identity fields: receipts first, then the most recent row."""
    ordered = sorted(records, key=lambda item: (item["receipt"],
                                                item["observed"],
                                                item["index"]), reverse=True)
    result: dict[str, Any] = {}
    for name in ("title", "url", "published_at", "account", "post_id"):
        result[name] = next((item[name] for item in ordered if item[name]),
                            None)
    return result


def snapshot(record: dict[str, Any]) -> dict[str, Any]:
    label = record["window"]
    return {
        "observed_at": record["observed_at"], "window": label,
        "metrics": record["metrics"],
        "metrics_by_window": {label: record["metrics"]} if label else {},
        "source": record["source"],
        "source_type": RECEIPT if record["receipt"] else "csv",
        "status": "published", "notes": "",
    }


def history_key(pair: tuple[int, dict[str, Any]]) -> tuple[float, int]:
    index, entry = pair
    moment = local_time(entry.get("observed_at"))
    return (moment.timestamp() if moment else float("-inf")), index


def merged_history(existing: list[dict[str, Any]],
                   records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = list(existing) + [snapshot(record) for record in records]
    return [entry for _, entry in sorted(enumerate(entries), key=history_key)]


# ---------------------------------------------------------------- posts

def apply_latest(post: dict[str, Any], records: list[dict[str, Any]]) -> None:
    """Latest = the most recent snapshot; a window's numbers stay whole."""
    latest = max(records, key=lambda item: (item["observed"], item["index"]))
    if post.get("metric_window") and has_values(post.get("metrics")):
        own = local_time(post.get("observed_at"))
        if own is None or own >= latest["observed"]:
            return
    label = latest["window"]
    if label:
        post["metric_window"] = label
        post["metrics"] = post["metrics_by_window"][label]
        post["observed_at"] = post["metric_observed_at_by_window"][label]
    else:
        post["metric_window"] = None
        post["metrics"] = latest["metrics"]
        post["observed_at"] = latest["observed_at"]


def fill_windows(post: dict[str, Any], records: list[dict[str, Any]]) -> None:
    windows = post.setdefault("metrics_by_window", {})
    times = post.setdefault("metric_observed_at_by_window", {})
    for label in WINDOWS:
        windows.setdefault(label, legacy_empty_metrics())
        times.setdefault(label, None)
    for label, record in window_picks(records).items():
        if has_values(windows.get(label)):
            continue  # the post's own source already has this window
        windows[label] = record["metrics"]
        times[label] = record["observed_at"]


def merge_into(post: dict[str, Any], records: list[dict[str, Any]]) -> None:
    fill_windows(post, records)
    post["history"] = merged_history(post.get("history") or [], records)
    apply_latest(post, records)


def legacy_post(records: list[dict[str, Any]], account_id: str,
                channel: str) -> dict[str, Any]:
    head = facts(records)
    latest = max(records, key=lambda item: (item["observed"], item["index"]))
    post: dict[str, Any] = {
        "id": identifier("import", channel, head["url"] or head["post_id"]),
        "account_id": account_id, "content_id": head["post_id"],
        "title": head["title"] or head["post_id"], "caption": None,
        "caption_complete": False, "url": head["url"],
        "published_at": head["published_at"], "format": None,
        "duration_sec": None, "status": "published", "current": True,
        "source_kind": "post_record", "observed_at": None,
        "metrics": legacy_empty_metrics(), "metric_window": None,
        "metrics_by_window": {}, "history": [], "source": latest["source"],
        "work_id": None, "cover": None, "preview_url": None, "issues": [],
        "metric_observed_at_by_window": {},
    }
    merge_into(post, records)
    return post


# ---------------------------------------------------------------- accounts

def platform_label(channel: str) -> str:
    names = {item["id"]: item["name"] for item in core.PLATFORMS}
    return PLATFORM_LABELS.get(channel) or names.get(legacy_platform(channel),
                                                     channel)


def dashboard_account(platform: str, handle: str, account_id: str,
                      brand_id: str, brand: str, name: str,
                      legacy_account_id: str | None, origin: str
                      ) -> dict[str, Any]:
    """An account entry shaped like the AK-sourced ones, without samples."""
    channel = platform_id(platform)
    return {
        "id": account_id, "brand_id": brand_id, "brand": brand, "name": name,
        "platform": channel, "platform_label": platform_label(channel),
        "handle": handle,
        "profile_url": handle if handle.startswith(("https://", "http://"))
        else None,
        "readonly": False, "login_state": "not_checked",
        "data_state": "unavailable", "as_of": None, "source": None,
        "metrics": empty_metrics(), "display_metrics": {},
        "window_start": None, "window_end": None, "history": [],
        "latest_snapshot": None, "posts_count": 0,
        "posts_count_kind": "indexed_records",
        "legacy_account_id": legacy_account_id, "origin": origin,
    }


def registry_account(row: dict[str, Any]) -> dict[str, Any]:
    """A 账号档案 row that matches no dashboard account."""
    handle = text(row.get("handle")) or ""
    brand = text(row.get("brand")) or "未分组"
    return dashboard_account(
        str(row.get("platform") or ""), handle, "legacy:" + str(row["id"]),
        "legacy:" + brand, brand, text(row.get("name")) or handle,
        str(row["id"]), "legacy_accounts")


def import_account(platform: str, handle: str,
                   identities: list[dict[str, str]],
                   brands: dict[str, tuple[str, str]] | None = None
                   ) -> dict[str, Any]:
    """A CSV account string that matches neither source.

    Spelled like a dashboard brand, it joins that brand's group.
    """
    key = "import:" + identifier(handle_key(handle) or "")
    brand_id, brand = (brands or {}).get(handle_key(handle) or "",
                                         (key, handle))
    matches = [item for item in identities
               if item.get("platform") == platform
               and handle_key(item.get("handle")) == handle_key(handle)]
    return dashboard_account(
        platform, handle, key + ":" + platform_id(platform), brand_id,
        brand, handle, matches[0]["id"] if len(matches) == 1 else None,
        "csv_import")


def account_table(accounts: list[dict[str, Any]]
                  ) -> dict[tuple[str, str], dict[str, Any]]:
    table: dict[tuple[str, str], dict[str, Any]] = {}
    for account in accounts:
        platform = legacy_platform(str(account.get("platform") or ""))
        for value in (account.get("handle"), account.get("profile_url")):
            key = handle_key(value)
            if key:
                table.setdefault((platform, key), account)
    return table


def post_table(snapshot_: dict[str, Any]
               ) -> dict[tuple[str, str], dict[str, Any]]:
    platforms = {account.get("id"): str(account.get("platform") or "")
                 for account in snapshot_.get("accounts", [])}
    table: dict[tuple[str, str], dict[str, Any]] = {}
    for post in (list(snapshot_.get("posts", []))
                 + list(snapshot_.get("history_posts", []))):
        account_id = str(post.get("account_id") or "")
        channel = platforms.get(account_id) or account_id.rsplit(":", 1)[-1]
        platform = legacy_platform(channel)
        for value in (post.get("url"), post.get("content_id")):
            key = content_key(value)
            if key:
                table.setdefault((platform, key), post)
    return table


def existing_post(group: list[dict[str, Any]],
                  posts: dict[tuple[str, str], dict[str, Any]]
                  ) -> dict[str, Any] | None:
    for record in group:
        key = (record["platform"], content_key(record["url"]))
        if record["url"] and key in posts:
            return posts[key]
    for record in group:
        if (record["platform"], record["post_id"]) in posts:
            return posts[(record["platform"], record["post_id"])]
    return None


# ---------------------------------------------------------------- merge

def merge_social(snapshot_: dict[str, Any], items: list[dict[str, Any]],
                 identities: list[dict[str, str]]) -> list[dict[str, Any]]:
    records = [record for record in
               (social_record(index, item) for index, item in enumerate(items))
               if record]
    if not records:
        return []
    accounts = snapshot_.setdefault("accounts", [])
    posts = snapshot_.setdefault("posts", [])
    snapshot_.setdefault("history_posts", [])
    known_posts = post_table(snapshot_)
    known_accounts = account_table(accounts)
    brands: dict[str, tuple[str, str]] = {}
    for account in accounts:
        key = handle_key(account.get("brand"))
        if key and account.get("brand_id"):
            brands.setdefault(key, (str(account["brand_id"]),
                                    str(account["brand"])))
    added: list[dict[str, Any]] = []
    for group in group_records(records):
        match = existing_post(group, known_posts)
        if match is not None:
            merge_into(match, group)
            continue
        head = facts(group)
        platform = group[-1]["platform"]
        handle = head["account"] or ""
        account = known_accounts.get((platform, handle_key(handle) or ""))
        if account is None:
            account = import_account(platform, handle, identities, brands)
            accounts.append(account)
            known_accounts[(platform, handle_key(handle) or "")] = account
        post = legacy_post(group, account["id"], account["platform"])
        posts.append(post)
        added.append(post)
    if added:
        for account in accounts:
            account["posts_count"] = sum(post.get("account_id") ==
                                         account.get("id") for post in posts)
        posts.sort(key=lambda post: post.get("published_at") or "",
                   reverse=True)
    return added


def ads_structure(items: list[dict[str, Any]]) -> dict[str, Any]:
    campaigns: dict[tuple[str, ...], dict[str, Any]] = {}
    for item in items:
        key = tuple(str(item.get(name) or "")
                    for name in ("platform", "account", "campaign", "currency"))
        day = text(item.get("date"))
        if not day:
            continue
        entry = campaigns.setdefault(key, {
            "platform": key[0], "account": key[1], "campaign": key[2],
            "currency": key[3], "days": {}})
        entry["days"][day] = {
            "date": day,
            "impressions": numeric(item.get("impressions")),
            "clicks": numeric(item.get("clicks")),
            "spend": numeric(item.get("spend")),
            "conversions": numeric(item.get("conversions")),
        }
    return {"campaigns": [
        {**campaigns[key], "days": [campaigns[key]["days"][day]
                                    for day in sorted(campaigns[key]["days"])]}
        for key in sorted(campaigns)]}


def merge(snapshot_: dict[str, Any],
          identities: list[dict[str, str]] | None = None
          ) -> list[dict[str, Any]]:
    """Add legacy numbers to a dashboard snapshot; returns the new posts."""
    social, ads = read_observations(core.DB.resolve())
    added = merge_social(snapshot_, social, identities or []) if social else []
    if ads:
        structure = ads_structure(ads)
        if structure["campaigns"]:
            snapshot_["ads"] = structure
    return added
