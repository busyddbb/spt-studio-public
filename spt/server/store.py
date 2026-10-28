"""SQLite persistence for normalized filesystem facts."""
from __future__ import annotations
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from .cache import safe_database
from .covers import IMAGES, ITEM_THUMBS, VIDEOS
from .metrics import (ACCOUNT_METRICS, METRICS, account_metrics, metrics_posts, recorded_posts,
                      metrics_tags, work_metrics)
from .models import AccountObservation, Analysis, Item, Work
from .schema import SCHEMA, SCHEMA_VERSION, TABLES

ITEM_KINDS = ("prompt", "material", "record", "skill", "note")
ITEM_COLUMNS = ("SELECT items.*, item_thumbs.name AS thumb_name, "
                "item_thumbs.as_is AS thumb_as_is, "
                "item_versions.version AS version, "
                "item_versions.superseded AS superseded, "
                "item_versions.adopted AS adopted FROM items "
                "LEFT JOIN item_thumbs ON item_thumbs.item_id=items.id "
                "LEFT JOIN item_versions ON item_versions.item_id=items.id")
# Lists, search and counts show one version per work unless all_versions is asked
# for; superseded prompts stay in the index and in the work detail.
LISTED = "COALESCE(item_versions.superseded, 0)=0"


def terms(query: str) -> list[str]:
    """Search words: split on any whitespace (a full-width space too), case ignored."""
    return query.casefold().split()


def found(words: list[str], parts: Iterable[str]) -> bool:
    """Every word appears somewhere in the parts."""
    haystack = "\n".join(parts).casefold()
    return all(word in haystack for word in words)


class Store:
    def __init__(self, database: Path, thumbs: Path | None = None) -> None:
        self.database = database
        # item thumbnails live next to the index: <cache>/item-thumbs/
        self.thumbs = thumbs or database.parent / ITEM_THUMBS
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        safe_database(self.database)
        connection = sqlite3.connect(self.database, timeout=10)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        safe_database(self.database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version < SCHEMA_VERSION:
                connection.execute("PRAGMA foreign_keys=OFF")
                for table in TABLES:
                    connection.execute(f"DROP TABLE IF EXISTS {table}")
            connection.executescript(SCHEMA)
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def replace(self, works: list[Work], indexed_at: str,
                items: list[Item] | None = None,
                issues: list[str] | None = None,
                thumbs: dict[str, tuple[str, bool]] | None = None,
                accounts: tuple[list[AccountObservation], list[Analysis]] | None = None
                ) -> None:
        self.initialize()
        everything = list(items or []) + [item for work in works
                                          for item in work.items]
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM item_versions")
            connection.execute("DELETE FROM item_thumbs")
            connection.execute("DELETE FROM items")
            connection.execute("DELETE FROM works")
            connection.execute("DELETE FROM account_observations")
            connection.execute("DELETE FROM account_analyses")
            for work in works:
                insert_work(connection, work)
            insert_items(connection, everything)
            insert_item_extras(connection, everything, thumbs or {})
            insert_accounts(connection, *(accounts or ([], [])))
            sql = "INSERT OR REPLACE INTO index_meta VALUES(?,?)"
            connection.execute(sql, ("indexed_at", indexed_at))
            connection.execute(sql, ("issues", json.dumps(
                list(issues or [])[:200], ensure_ascii=False)))

    def replace_work(self, work: Work,
                     thumbs: dict[str, tuple[str, bool]] | None = None) -> None:
        """Swap one work's rows (and the items that came from it) for a fresh scan."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM item_thumbs WHERE item_id IN "
                               "(SELECT id FROM items WHERE work_id=?)", (work.id,))
            connection.execute("DELETE FROM items WHERE work_id=?", (work.id,))
            connection.execute("DELETE FROM works WHERE id=?", (work.id,))
            insert_work(connection, work)
            insert_items(connection, work.items)
            insert_item_extras(connection, work.items, thumbs or {})

    def replace_accounts(self, observations: list[AccountObservation],
                         analyses: list[Analysis]) -> None:
        """Swap the account-level 数据记录 rows for a fresh scan of 工作区/数据/账号."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM account_observations")
            connection.execute("DELETE FROM account_analyses")
            insert_accounts(connection, observations, analyses)

    def metadata(self) -> dict[str, str]:
        with self.connect() as connection:
            return dict(connection.execute("SELECT key,value FROM index_meta"))

    def work_location(self, identifier: str) -> dict[str, str] | None:
        """Where an indexed work's folder is: {relative_path, category, path}."""
        with self.connect() as connection:
            row = connection.execute("SELECT relative_path,category,path FROM works "
                                     "WHERE id=?", (identifier,)).fetchone()
            return dict(row) if row else None

    def lookup_work(self, text: str) -> list[dict[str, Any]]:
        """Works a person may mean by `text`: the id, the folder name, else every work
        whose title or folder name contains it (case ignored)."""
        key = text.strip()
        if not key:
            return []
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute(
                "SELECT id,title,client,relative_path,path FROM works ORDER BY date DESC")]
        exact = [row for row in rows if row["id"] == key
                 or Path(row["relative_path"]).name == key or row["relative_path"] == key]
        if exact:
            return exact[:1]
        folded = key.casefold()
        return [row for row in rows if folded in row["title"].casefold()
                or folded in row["relative_path"].casefold()]

    # ---- 数据记录 (metrics.py holds the query code)

    def work_metrics(self, identifier: str) -> dict[str, Any]:
        with self.connect() as connection:
            return work_metrics(connection, identifier)

    def metrics_posts(self, **filters: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return metrics_posts(connection, **filters)

    def recorded_posts(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return recorded_posts(connection)

    def metrics_tags(self, **filters: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return metrics_tags(connection, **filters)

    def account_metrics(self, platform: str = "", account: str = "") -> list[dict[str, Any]]:
        with self.connect() as connection:
            return account_metrics(connection, platform, account)

    def delete_work(self, identifier: str) -> bool:
        """Drop one work and everything that hangs off it; False when it was not there.

        The work's child tables cascade; its items do not reference it, so they
        and their thumbnail names go explicitly (item_versions cascade from items).
        """
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM item_thumbs WHERE item_id IN "
                               "(SELECT id FROM items WHERE work_id=?)", (identifier,))
            connection.execute("DELETE FROM items WHERE work_id=?", (identifier,))
            removed = connection.execute("DELETE FROM works WHERE id=?",
                                         (identifier,)).rowcount
            return removed > 0

    def list_works(self, category: str = "", status: str = "",
                   query: str = "", client: str = "") -> list[dict[str, Any]]:
        with self.connect() as connection:
            sql = "SELECT * FROM works ORDER BY date DESC, relative_path"
            rows = connection.execute(sql)
            works = [public_work(connection, dict(row)) for row in rows]
            return [work for work in works if matches(connection, work,
                                                      category, status, query,
                                                      client)]

    def client_counts(self) -> dict[str, int]:
        """Works per client code (the 客户 part of the folder name)."""
        with self.connect() as connection:
            return {row[0]: row[1] for row in connection.execute(
                "SELECT client, COUNT(*) FROM works GROUP BY client")}

    def list_items(self, kind: str = "", section: str = "", query: str = "",
                   source: str = "", all_versions: bool = False,
                   client: str = "") -> list[dict[str, Any]]:
        sql, values = ITEM_COLUMNS + " WHERE 1=1", []
        for column, value in (("kind", kind), ("section", section),
                              ("source", source), ("client", client)):
            if value:
                sql += f" AND items.{column}=?"
                values.append(value)
        if not all_versions:
            sql += " AND " + LISTED
        sql += (" ORDER BY kind, CASE section WHEN '库内' THEN 0 "
                "WHEN '未分类' THEN 2 ELSE 1 END, section, code, "
                "modified_at DESC, title")
        ready = self.thumb_names().__contains__
        with self.connect() as connection:
            rows = [public_item(dict(row), ready=ready)
                    for row in connection.execute(sql, values)]
        words = terms(query)
        if not words:
            return rows
        # Not the path: folder names such as 提示词/, skills/ or a date would
        # make one word match a whole kind.
        return [row for row in rows if found(words, (
            str(row.get(key) or "") for key in
            ("title", "text", "note", "tags", "tool", "section", "code")))]

    def get_item(self, identifier: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(ITEM_COLUMNS + " WHERE items.id=?",
                                     (identifier,)).fetchone()
            return public_item(dict(row), full=True,
                               ready=lambda name: (self.thumbs / name).is_file()
                               ) if row else None

    def thumb_names(self) -> set[str]:
        """Item thumbnails already made (they are made on first request)."""
        try:
            return set(os.listdir(self.thumbs))
        except OSError:
            return set()

    def library(self, all_versions: bool = False) -> dict[str, Any]:
        """Counts per kind and section, the same items list_items shows.

        superseded: how many older versions of works' prompts there are; they
        are part of count only with all_versions.
        """
        kinds: dict[str, dict[str, Any]] = {}

        def entry(kind: str) -> dict[str, Any]:
            return kinds.setdefault(kind, {"count": 0, "sections": [],
                                           "superseded": 0})
        for kind in ITEM_KINDS:
            entry(kind)
        listed = "" if all_versions else f"WHERE {LISTED} "
        with self.connect() as connection:
            for row in connection.execute(
                    "SELECT kind, section, COUNT(*) AS n FROM items "
                    "LEFT JOIN item_versions ON item_versions.item_id=items.id "
                    f"{listed}GROUP BY kind, section ORDER BY kind, CASE section "
                    "WHEN '库内' THEN 0 WHEN '未分类' THEN 2 ELSE 1 END, "
                    "section"):
                group = entry(row["kind"])
                group["count"] += row["n"]
                group["sections"].append({"name": row["section"],
                                          "count": row["n"]})
            for row in connection.execute(
                    "SELECT kind, COUNT(*) AS n FROM items JOIN item_versions "
                    "ON item_versions.item_id=items.id "
                    "WHERE item_versions.superseded=1 GROUP BY kind"):
                entry(row["kind"])["superseded"] = row["n"]
            works = connection.execute("SELECT COUNT(*) FROM works").fetchone()
        return {"works": works[0], "kinds": kinds}

    def export_works(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = []
            for work in connection.execute(
                    "SELECT * FROM works ORDER BY date DESC, relative_path"):
                work = dict(work)
                version = work["current_version"] or work["latest_version"]
                prompt = connection.execute(
                    "SELECT prompt FROM versions WHERE work_id=? AND name=?",
                    (work["id"], version)).fetchone() if version else None
                records = [dict(row) for row in connection.execute(
                    "SELECT platform,url FROM publish_records "
                    "WHERE work_id=? AND state='current' ORDER BY position",
                    (work["id"],))]
                work["prompt"] = prompt[0] if prompt else ""
                work["version"] = version or ""
                work["platforms"] = "、".join(dict.fromkeys(
                    row["platform"] for row in records))
                work["urls"] = "\n".join(row["url"] for row in records
                                         if row["url"])
                rows.append(work)
            return rows

    def detail(self, identifier: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM works WHERE id=?",
                                     (identifier,)).fetchone()
            if row is None:
                return None
            work = public_work(connection, dict(row))
            versions = [version_detail(connection, identifier, dict(version))
                        for version in connection.execute(
                            "SELECT * FROM versions WHERE work_id=? "
                            "ORDER BY rowid",
                            (identifier,))]
            return build_detail(connection, identifier, work, versions)


def insert_work(connection: sqlite3.Connection, work: Work) -> None:
    values = asdict(work)
    columns = [row[1] for row in connection.execute(
        "PRAGMA table_info(works)")]
    sql = "INSERT INTO works VALUES(" + ",".join("?" for _ in columns) + ")"
    connection.execute(sql,
                       tuple(values[column] for column in columns))
    insert_versions(connection, work)
    insert_records(connection, work)
    connection.executemany("INSERT INTO package_sections VALUES(?,?,?)",
        [(work.id, platform, caption)
         for platform, caption in work.package.items()])
    connection.executemany("INSERT INTO documents VALUES(?,?,?,?)",
        [(work.id, document.name, document.text, document.modified_at)
         for document in work.documents])
    connection.executemany("INSERT INTO archives VALUES(?,?,?)",
        [(work.id, index, path)
         for index, path in enumerate(dict.fromkeys(work.archives))])
    connection.executemany("INSERT INTO evidence VALUES(?,?,?,?,?)",
        [(work.id, index, *fact) for index, fact in enumerate(work.basis)])
    connection.executemany("INSERT INTO issues VALUES(?,?,?)",
        [(work.id, index, issue) for index, issue in enumerate(work.issues)])
    insert_timeline(connection, work)
    insert_metrics(connection, work)


def insert_metrics(connection: sqlite3.Connection, work: Work) -> None:
    """The work's 数据/ rows: observations, retention points, analyses and their tags."""
    connection.executemany(
        "INSERT INTO metric_observations VALUES(" + ",".join("?" * 21) + ")",
        [(work.id, position, item.at, item.age_hours, item.platform, item.account,
          *(getattr(item, field) for field in METRICS), item.source, item.note, item.path)
         for position, item in enumerate(work.observations)])
    connection.executemany(
        "INSERT INTO metric_retention VALUES(?,?,?,?,?,?,?,?)",
        [(work.id, position, item.at, item.platform, item.account, item.second, item.rate,
          item.path) for position, item in enumerate(work.retention)])
    connection.executemany(
        "INSERT OR REPLACE INTO metric_analyses VALUES(?,?,?,?,?,?,?,?,?)",
        [(work.id, item.path, item.date, item.platform, item.account, item.node,
          item.conclusion, item.body, item.modified_at) for item in work.analyses])
    connection.executemany(
        "INSERT OR REPLACE INTO metric_analysis_tags VALUES(?,?,?)",
        [(work.id, item.path, tag) for item in work.analyses for tag in item.tags])


def insert_accounts(connection: sqlite3.Connection,
                    observations: list[AccountObservation],
                    analyses: list[Analysis]) -> None:
    positions: dict[tuple[str, str], int] = {}
    rows = []
    for item in observations:
        key = (item.platform, item.account)
        positions[key] = positions.get(key, -1) + 1
        rows.append((item.platform, item.account, positions[key], item.at,
                     *(getattr(item, field) for field in ACCOUNT_METRICS),
                     item.source, item.note, item.path))
    connection.executemany(
        "INSERT INTO account_observations VALUES(" + ",".join("?" * 17) + ")", rows)
    connection.executemany(
        "INSERT OR REPLACE INTO account_analyses VALUES(?,?,?,?,?,?,?,?)",
        [(item.platform, item.account, item.path, item.date, item.node, item.conclusion,
          item.body, item.modified_at) for item in analyses])
    connection.executemany(
        "INSERT OR REPLACE INTO account_analysis_tags VALUES(?,?)",
        [(item.path, tag) for item in analyses for tag in item.tags])


def insert_items(connection: sqlite3.Connection, items: list[Item]) -> None:
    columns = [row[1] for row in connection.execute("PRAGMA table_info(items)")]
    sql = ("INSERT OR REPLACE INTO items VALUES(" +
           ",".join("?" for _ in columns) + ")")
    connection.executemany(sql, [tuple(asdict(item)[column]
                                       for column in columns)
                                 for item in items])


def insert_item_extras(connection: sqlite3.Connection, items: list[Item],
                       thumbs: dict[str, tuple[str, bool]]) -> None:
    """Version flags and thumbnail names that go with items."""
    connection.executemany(
        "INSERT OR REPLACE INTO item_versions VALUES(?,?,?,?)",
        [(item.id, item.version, int(item.superseded), int(item.adopted))
         for item in items if item.version])
    wanted = {item.id for item in items}
    connection.executemany("INSERT OR REPLACE INTO item_thumbs VALUES(?,?,?)",
        [(identifier, name, int(as_is))
         for identifier, (name, as_is) in thumbs.items() if identifier in wanted])


def public_item(item: dict[str, Any], full: bool = False,
                ready: Callable[[str], bool] | None = None) -> dict[str, Any]:
    """The item as the API shows it; `ready` says whether a thumbnail was made yet."""
    name, as_is = item.pop("thumb_name", None), item.pop("thumb_as_is", None)
    item["version"] = item.get("version") or None
    item["superseded"] = bool(item.get("superseded"))
    item["adopted"] = bool(item.get("adopted"))
    item["file_url"] = (f"/api/items/{item['id']}/file"
                        if item.get("file") else None)
    item["thumb_url"] = None
    if item.get("file") and Path(item["file"]).suffix.lower() in IMAGES | VIDEOS:
        # versioned once the picture that will be sent is settled: a small picture
        # is sent as it is, a bigger one once its thumbnail exists
        settled = bool(name) and (bool(as_is) or (ready is not None and ready(name)))
        item["thumb_url"] = thumb_url(item["id"], name if settled else None)
    item["work_url"] = (f"/api/works/{item['work_id']}"
                        if item.get("work_id") else None)
    if not full:
        item.pop("body", None)
    return item


def insert_versions(connection: sqlite3.Connection, work: Work) -> None:
    media = list(work.finals)
    for version in work.versions:
        connection.execute("INSERT INTO versions VALUES(?,?,?,?,?,?,?)",
            (work.id, version.name, version.prompt, version.prompt_path,
             version.created_at,
             sum(item.role == "input" for item in version.media),
             sum(item.role == "return" for item in version.media)))
        media.extend(version.media)
    connection.executemany("INSERT INTO media VALUES(?,?,?,?,?,?,?,?,?,?)",
        [(work.id, item.version, item.name, item.path, item.role,
          item.mime_type, item.size, item.modified_at, item.order, item.sha256)
         for item in media])


def insert_records(connection: sqlite3.Connection, work: Work) -> None:
    seen = set()
    position = 0
    for record in work.records:
        key = (record.platform, record.url, record.state)
        if key in seen:
            continue
        seen.add(key)
        connection.execute(
            "INSERT INTO publish_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (work.id, position, record.platform, record.account, record.url,
             record.published_at, record.sha256,
             int(record.verified), record.state,
             record.source_path, record.source_heading, record.evidence))
        position += 1


def insert_timeline(connection: sqlite3.Connection, work: Work) -> None:
    events = [("created", work.created_at, "文件最早修改时间", work.relative_path)]
    events += [("version", version.created_at, version.name, version.name)
               for version in work.versions]
    events += [("publication", record.published_at,
                record.platform + " · " + record.state, record.source_path)
               for record in work.records if record.published_at]
    connection.executemany("INSERT INTO timeline VALUES(?,?,?,?,?,?)",
        [(work.id, position, *event) for position, event in enumerate(events)])


def cover_url(identifier: str, cache: str | None) -> str:
    """Thumbnails are named after the file they came from, so the URL changes when it does."""
    url = f"/api/works/{identifier}/cover"
    return f"{url}?v={Path(cache).stem[:12]}" if cache else url


def thumb_url(identifier: str, name: str | None) -> str:
    """Same idea for item thumbnails: versioned only when the name is settled."""
    url = f"/api/items/{identifier}/thumb"
    return f"{url}?v={Path(name).stem[:12]}" if name else url


def public_work(connection: sqlite3.Connection,
                work: dict[str, Any]) -> dict[str, Any]:
    identifier = work["id"]
    work["verified"] = bool(work["verified"])
    work["publication_verified"] = all(row[0] for row in connection.execute(
        "SELECT verified FROM publish_records "
        "WHERE work_id=? AND state='current'",
        (identifier,))) if work["status"] == "published" else False
    has_cover = work["cover_source"] or work["cover_cache"]
    work["cover"] = cover_url(identifier, work["cover_cache"]) if has_cover else None
    work["platforms"] = [row[0] for row in connection.execute(
        "SELECT DISTINCT platform FROM publish_records "
        "WHERE work_id=? AND state='current'",
        (identifier,))]
    work["issues"] = [row[0] for row in connection.execute(
        "SELECT description FROM issues WHERE work_id=? ORDER BY position",
        (identifier,))]
    for kind in ("status", "selection"):
        work[kind + "_basis"] = [dict(row) for row in connection.execute(
            "SELECT description AS text,source FROM evidence "
            "WHERE work_id=? AND kind=? ORDER BY position",
            (identifier, kind))]
    work.pop("cover_cache", None)
    return work


def matches(connection: sqlite3.Connection, work: dict[str, Any],
            category: str, status: str, query: str, client: str = "") -> bool:
    if category and category != work["category"]:
        return False
    if status and status != work["status"]:
        return False
    if client and client != work["client"]:
        return False
    words = terms(query)
    if not words:
        return True
    parts = [work["title"], work["client"], work["category"],
             work.get("note") or "", work.get("tags") or "",
             work.get("tool") or ""]
    parts += [row[0] or "" for row in connection.execute(
        "SELECT prompt FROM versions WHERE work_id=?", (work["id"],))]
    parts += [row[0] or "" for row in connection.execute(
        "SELECT content FROM documents WHERE work_id=?", (work["id"],))]
    return found(words, parts)


def media_list(connection: sqlite3.Connection, identifier: str,
               version: str | None = None) -> list[dict[str, Any]]:
    from urllib.parse import quote
    sql = "SELECT * FROM media WHERE work_id=?"
    values: tuple[str, ...] = (identifier,)
    if version is not None:
        sql += " AND version_name=?"
        values += (version,)
    items = [dict(row) for row in connection.execute(
        sql + " ORDER BY position,name", values)]
    for item in items:
        item["order"] = item.pop("position")
        base = f"/api/works/{identifier}/file?path="
        item["url"] = base + quote(item["path"], safe="")
        item.pop("work_id")
    return items


def version_detail(connection: sqlite3.Connection, identifier: str,
                   version: dict[str, Any]) -> dict[str, Any]:
    media = media_list(connection, identifier, version["name"])
    version["media"] = [item for item in media if item["role"] == "input"]
    version["returns"] = [item for item in media if item["role"] == "return"]
    version["references"] = [item for item in media
                             if item["role"] == "reference"]
    current = connection.execute(
        "SELECT current_version FROM works WHERE id=?",
        (identifier,)).fetchone()[0]
    version["is_current"] = version["name"] == current
    version.pop("work_id")
    return version


def build_detail(connection: sqlite3.Connection, identifier: str,
                 work: dict[str, Any],
                 versions: list[dict[str, Any]]) -> dict[str, Any]:
    records = [dict(row) for row in connection.execute(
        "SELECT * FROM publish_records WHERE work_id=? ORDER BY position",
        (identifier,))]
    for record in records:
        record["verified"] = bool(record["verified"])
        record["is_current"] = record["current"] = record["state"] == "current"
        record["verification_source"] = "file"
        record.pop("work_id")
    documents = [dict(row) for row in connection.execute(
        "SELECT name,content AS text,modified_at FROM documents "
        "WHERE work_id=?",
        (identifier,))]
    return {"work": work, "versions": versions, "records": records,
        "finals": [item for item in media_list(connection, identifier, "")],
        "package": dict(connection.execute(
            "SELECT platform,caption FROM package_sections WHERE work_id=?",
            (identifier,))),
        "archive_links": [row[0] for row in connection.execute(
            "SELECT path FROM archives WHERE work_id=? ORDER BY position",
            (identifier,))],
        "source_documents": documents, "notes": "\n".join(work["issues"]),
        "timeline": [dict(row) for row in connection.execute(
            "SELECT kind,at,description,source FROM timeline "
            "WHERE work_id=? ORDER BY position", (identifier,))],
        # 数据记录: the same as GET /api/works/<id>/metrics
        "metrics": work_metrics(connection, identifier)}
