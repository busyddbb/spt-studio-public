"""Read-only operations bridge; facts stay in their original projects."""
from __future__ import annotations
import datetime as dt
from pathlib import Path
from typing import Any

from .dashboard_accounts import (
    attach_snapshots, definitions, load_registry,
)
from .dashboard_intelligence import intelligence
from .dashboard_io import load_optional
from .dashboard_links import enrich_posts
from .dashboard_parenting import attach_parenting, parenting_posts
from .dashboard_posts import normalize_posts


def dashboard_snapshot(project_root: Path | None = None) -> dict[str, Any]:
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    issues: list[dict[str, str]] = []
    project_file = root / "app/projects.json"
    loaded = load_optional(project_file, "json", issues)
    projects = loaded if isinstance(loaded, list) else []
    roots = project_roots(projects)
    ak_root = roots.get("demo-brand")
    registry = load_registry(ak_root, issues) if ak_root else {}
    accounts = definitions(projects, registry)
    account_rows, post_rows, trend_rows = ak_sources(ak_root, issues)
    data = ak_root / "系统（不用看）/数据" if ak_root else root
    attach_snapshots(accounts, account_rows, data / "account_daily.csv")
    posts = normalize_posts(post_rows, data / "content_performance.csv")
    posts.extend(parenting_sources(accounts, roots.get("parenting"), issues))
    enrich_posts(posts, root)
    current = [post for post in posts if post["current"]]
    for item in accounts:
        item["posts_count"] = sum(post["account_id"] == item["id"]
                                  for post in current)
    current.sort(key=lambda post: post.get("published_at") or "", reverse=True)
    return result(accounts, current, posts, projects, project_file, issues,
                  intelligence(root, trend_rows, issues))


def project_roots(projects: list[dict[str, Any]]) -> dict[str, Path]:
    return {project["id"]: Path(project["root_path"])
            for project in projects
            if project.get("id") and project.get("root_path")}


def ak_sources(root: Path | None, issues: list[dict[str, str]]
               ) -> tuple[list[dict[str, str]], ...]:
    if root is None:
        return [], [], []
    data = root / "系统（不用看）/数据"
    names = ("account_daily.csv", "content_performance.csv", "trend_inbox.csv")
    rows = [load_optional(data / name, "csv", issues) for name in names]
    return tuple(rows)


def parenting_sources(accounts: list[dict[str, Any]], root: Path | None,
                      issues: list[dict[str, str]]) -> list[dict[str, Any]]:
    if root is None:
        return []
    source = root / "10-数据复盘/当前账号数据.md"
    text = load_optional(source, "text", issues)
    attach_parenting(accounts, text, source)
    return parenting_posts(text, source)


def result(accounts: list[dict[str, Any]], current: list[dict[str, Any]],
           all_posts: list[dict[str, Any]], projects: list[dict[str, Any]],
           source: Path, issues: list[dict[str, str]],
           intel: dict[str, Any]) -> dict[str, Any]:
    allowed = ("id", "name", "kind", "root_path", "entry_path",
               "delivery_path", "summary", "checked_at")
    return {
        "accounts": accounts, "posts": current,
        "history_posts": [post for post in all_posts if not post["current"]],
        "intelligence": intel,
        "projects": [{key: project.get(key) for key in allowed}
                     for project in projects],
        "sources": {"projects": str(source), "mode": "local_readonly"},
        "as_of": dt.datetime.now(dt.timezone.utc).isoformat(),
        "as_of_kind": "assembled_at_not_sampled_at", "issues": issues,
        "capabilities": {"readonly_metrics": True, "live_metrics": False,
                         "publish": False, "account_login": False,
                         "intelligence_live": False},
    }
