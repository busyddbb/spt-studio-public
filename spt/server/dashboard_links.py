"""Optional association with the existing work index, opened read-only."""
from __future__ import annotations
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .store import cover_url


def indexed_links(project_root: Path) -> dict[str, dict[str, Any]]:
    database = project_root / "spt/server/.cache/index.sqlite3"
    if not database.is_file() or database.is_symlink():
        return {}
    query = (
        "SELECT r.url,r.work_id,r.platform,r.state,w.title,w.media_match,"
        "w.cover_source,w.cover_cache,p.caption FROM publish_records r "
        "JOIN works w ON w.id=r.work_id LEFT JOIN package_sections p "
        "ON p.work_id=r.work_id AND p.platform=r.platform "
        "WHERE r.state='current'"
    )
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro",
                                     uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            return {row["url"]: dict(row)
                    for row in connection.execute(query)}
    except sqlite3.Error:
        return {}


def enrich_posts(posts: list[dict[str, Any]], project_root: Path) -> None:
    links = indexed_links(project_root)
    for post in posts:
        link = links.get(post.get("url"))
        if not link:
            continue
        post["work_id"] = link["work_id"]
        post["title"] = link["title"]
        post["media_match"] = link["media_match"]
        if link["caption"]:
            post["caption"] = link["caption"]
            post["caption_complete"] = True
            post["caption_source"] = "工作区发布包，按当前发布URL关联"
        if link["media_match"] == "mismatch":
            post["issues"].append("本地成品与当前发布版本不一致")
        elif link["cover_source"] or link["cover_cache"]:
            post["cover"] = cover_url(link["work_id"], link["cover_cache"])
        post["preview_url"] = preview_url(project_root, link)


def preview_url(project_root: Path, link: dict[str, Any]) -> str | None:
    if link["media_match"] != "match":
        return None
    database = project_root / "spt/server/.cache/index.sqlite3"
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro",
                                     uri=True)) as connection:
            query = ("SELECT path FROM media WHERE work_id=? "
                     "AND role='final' ORDER BY position LIMIT 1")
            row = connection.execute(query, (link["work_id"],)).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    return ("/api/works/" + link["work_id"] + "/file?path=" +
            quote(row[0], safe=""))
