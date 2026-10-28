"""Shared read-only queries for the CLI and the MCP server."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from .config import default_config
from .exporter import export
from .indexer import Indexer

GUIDE = Path(__file__).resolve().parents[1] / "AGENTS.md"
KINDS = ("work", "prompt", "material", "record", "skill", "note")


def open_indexer(fresh: bool = False) -> Indexer:
    indexer = Indexer(default_config())
    if fresh or not indexer.store.metadata().get("indexed_at"):
        indexer.reindex()
    return indexer


def brief_work(work: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "category", "date", "client", "title", "status", "note",
            "tags", "tool", "relative_path", "latest_version",
            "current_version", "platforms")
    return {"kind": "work", **{key: work.get(key) for key in keys}}


def brief_item(item: dict[str, Any], text_limit: int = 400) -> dict[str, Any]:
    keys = ("id", "kind", "section", "code", "title", "note", "tags", "tool",
            "status", "source", "path", "file", "work_id", "client", "version",
            "adopted", "superseded", "modified_at")
    text = item.get("text") or ""
    result = {key: item.get(key) for key in keys if item.get(key)}
    result["text"] = text if len(text) <= text_limit else \
        text[:text_limit] + f"…（共{len(text)}字，用 get 取全文）"
    return result


def search(indexer: Indexer, query: str = "", kind: str = "",
           section: str = "", limit: int = 30,
           all_versions: bool = False, client: str = "") -> list[dict[str, Any]]:
    """Works' prompts come once per work (the 定稿, else the newest version);
    all_versions adds the superseded ones, marked "superseded": true.
    client: only works for that client code and the items that came from them."""
    if kind and kind not in KINDS:
        raise ValueError("kind 只能是 " + "/".join(KINDS))
    results: list[dict[str, Any]] = []
    if kind in ("", "work"):
        results += [brief_work(work) for work in indexer.store.list_works(
            category=section, query=query, client=client)]
    if kind != "work":
        results += [brief_item(item) for item in indexer.store.list_items(
            kind, section, query, all_versions=all_versions, client=client)]
    return results[:max(1, min(limit, 200))]


def get(indexer: Indexer, identifier: str) -> dict[str, Any] | None:
    item = indexer.store.get_item(identifier)
    if item:
        return item
    detail = indexer.store.detail(identifier)
    if not detail:
        return None
    work = brief_work(detail["work"])
    work["versions"] = [{"name": version["name"], "prompt": version["prompt"],
                         "prompt_path": version["prompt_path"],
                         "media": [media["path"] for media in version["media"]]}
                        for version in detail["versions"]]
    work["documents"] = {doc["name"]: doc["text"]
                         for doc in detail["source_documents"]}
    work["finals"] = [media["path"] for media in detail["finals"]]
    work["records"] = [{key: record[key] for key in
                        ("platform", "url", "published_at", "state")}
                       for record in detail["records"]]
    work["path"] = detail["work"]["path"]
    return work


def sections(indexer: Indexer) -> dict[str, Any]:
    summary = indexer.store.library()
    categories: dict[str, int] = {}
    for work in indexer.store.list_works():
        categories[work["category"]] = categories.get(work["category"], 0) + 1
    summary["work_categories"] = categories
    summary["workspace"] = str(indexer.workspace)
    return summary


def export_file(indexer: Indexer, format_name: str = "xlsx", kind: str = "",
                target: Path | None = None, all_versions: bool = False) -> Path:
    data, _, name = export(indexer.store, format_name, kind,
                           all_versions=all_versions)
    folder = indexer.config.cache / "exports"
    folder.mkdir(parents=True, exist_ok=True)
    path = target or folder / name
    path.write_bytes(data)
    return path


def guide() -> str:
    return GUIDE.read_text(encoding="utf-8") if GUIDE.is_file() else ""
