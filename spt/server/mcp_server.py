"""Minimal MCP stdio server (JSON-RPC 2.0, one message per line), read-only."""
from __future__ import annotations
import json
import sys
from typing import Any

from . import agent

PROTOCOL = "2025-06-18"
TOOLS = [
    {"name": "spt_guide",
     "description": "先读这个：SPT 资产库的目录规则——作品、提示词、素材、记录、skills 各放哪里、怎么命名、说明怎么写。",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "spt_sections",
     "description": "各类资产数量和分组（作品专业、素材表、提示词分组、skills 来源）。数量和 spt_search 默认列出的一致，不含作品的旧版本提示词；superseded 是旧版本有几条。",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "spt_search",
     "description": "搜索资产。kind: work/prompt/material/record/skill/note（note 是便签），留空搜全部；section 是分组名，如 衣服、镜头、运营；便签的 section 是绳子名；client 是客户简称（如 AK、自家），只给这个客户的作品和作品里的提示词、记录。作品里的提示词每件作品只给定稿那一版（没定稿就给最新一版），带 version；all_versions: true 时旧版本也给，标 superseded: true。返回摘要和 id。",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"},
         "kind": {"type": "string", "enum": ["", *agent.KINDS]},
         "section": {"type": "string"},
         "client": {"type": "string"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 200},
         "all_versions": {"type": "boolean"}}}},
    {"name": "spt_get",
     "description": "按 id 取完整内容：条目全文，或作品的各版本提示词、记录、发布记录。",
     "inputSchema": {"type": "object", "required": ["id"],
                     "properties": {"id": {"type": "string"}}}},
    {"name": "spt_export",
     "description": "把资产导出成一张完整表格（xlsx/csv/md），返回本机文件路径。作品的旧版本提示词要 all_versions: true 才导出。kind=metrics 只导出数据记录（一行一次记录）；xlsx 全表另有「数据」页。",
     "inputSchema": {"type": "object", "properties": {
         "format": {"type": "string", "enum": ["xlsx", "csv", "md"]},
         "kind": {"type": "string", "enum": ["", *agent.KINDS, "metrics"]},
         "all_versions": {"type": "boolean"}}}},
    {"name": "spt_reindex",
     "description": "新增或改动文件后重建索引，让 SPT 看到最新内容。",
     "inputSchema": {"type": "object", "properties": {}}},
    # ---- 数据记录 (spt/docs/数据记录格式.md) ----
    {"name": "spt_metrics",
     "description": "查数据记录：作品的 数据/表现.csv、留存.csv、分析/，以及 工作区/数据/账号。不带参数列出所有有记录的作品，一篇一条：最新数字、D1/D3/D7（带 late_hours 晚到小时）、留存、分析和标签。client（简称或名字）/platform/account/since/until/tag/q 是筛选；work 给作品 id、文件夹名或唯一关键字时返回这一篇的完整时间线；tags: true 只返回标签统计（哪些毛病最常见）。",
     "inputSchema": {"type": "object", "properties": {
         "client": {"type": "string"}, "platform": {"type": "string"},
         "account": {"type": "string"}, "since": {"type": "string"},
         "until": {"type": "string"}, "tag": {"type": "string"}, "q": {"type": "string"},
         "work": {"type": "string"}, "tags": {"type": "boolean"}}}},
    {"name": "spt_metrics_add",
     "description": "记一次数据，只追加文件、不改旧行。kind=observation：作品一行表现（work、platform 必填，account 一个号时可省，数字不知道就不传、不要传 0；点击率等百分数传 12.5 表示 12.5%）；kind=retention：作品留存曲线（work、platform、points [[秒, 留存率], …]）；kind=account：账号级（platform、account、followers、views……写进 工作区/数据/账号）。at 是记录时间，带时区，默认现在。source 写数字从哪来。写完自动刷新索引。",
     "inputSchema": {"type": "object", "required": ["kind"], "properties": {
         "kind": {"type": "string", "enum": ["observation", "retention", "account"]},
         "work": {"type": "string"}, "platform": {"type": "string"},
         "account": {"type": "string"}, "at": {"type": "string"},
         "views": {"type": "number"}, "reach": {"type": "number"},
         "likes": {"type": "number"}, "comments": {"type": "number"},
         "saves": {"type": "number"}, "shares": {"type": "number"},
         "profile_visits": {"type": "number"}, "follows": {"type": "number"},
         "ctr": {"type": "number"}, "three_sec_rate": {"type": "number"},
         "completion_rate": {"type": "number"}, "avg_watch_sec": {"type": "number"},
         "followers": {"type": "number"}, "interactions": {"type": "number"},
         "points": {"type": "array", "items": {"type": "array",
                                               "items": {"type": "number"}}},
         "source": {"type": "string"}, "note": {"type": "string"}}}},
    {"name": "spt_metrics_analyse",
     "description": "写一份分析到作品的 数据/分析/<日期>-<节点>.md，不覆盖已有文件。work、conclusion（一句话结论）必填；platform、account、node（D1/D3/D7/周/复盘……）、tags（毛病的名字，同一个毛病每次写同一个词，如 开头弱、封面、标题、节奏慢、选题偏、结尾无引导、发布时间、话题标签）、body（正文：现象、原因、下次怎么改）、date（默认今天）可选。",
     "inputSchema": {"type": "object", "required": ["work", "conclusion"], "properties": {
         "work": {"type": "string"}, "platform": {"type": "string"},
         "account": {"type": "string"}, "node": {"type": "string"},
         "conclusion": {"type": "string"},
         "tags": {"type": "array", "items": {"type": "string"}},
         "body": {"type": "string"}, "date": {"type": "string"}}}},
]
METRIC_FILTERS = ("client", "platform", "account", "since", "until", "tag", "q")


def metrics_query(indexer: Any, arguments: dict[str, Any]) -> Any:
    """spt_metrics: one work's full record, the tag counts, or the posts list."""
    from .metrics import client_code
    from .metrics_write import resolve_work
    store = indexer.store
    if arguments.get("work"):
        work = resolve_work(store, arguments["work"])
        return {"work": work, **store.work_metrics(work["id"])}
    filters = {key: str(arguments.get(key) or "") for key in METRIC_FILTERS}
    filters["client"] = client_code(filters["client"], indexer.clients.read(indexer.workspace)[0])
    if arguments.get("tags") in (True, "true", "1"):
        return store.metrics_tags(**filters)
    return store.metrics_posts(**filters)


def metrics_add(indexer: Any, arguments: dict[str, Any]) -> Any:
    from . import metrics_write
    writers = {"observation": metrics_write.record_observation,
               "retention": metrics_write.record_retention,
               "account": metrics_write.record_account}
    kind = str(arguments.get("kind") or "observation")
    if kind not in writers:
        raise ValueError("kind 只能是 observation、retention、account")
    return writers[kind](indexer, arguments)


def call(name: str, arguments: dict[str, Any]) -> Any:
    if name == "spt_guide":
        return agent.guide()
    indexer = agent.open_indexer(name == "spt_reindex")
    if name == "spt_reindex":
        return indexer.health()["counts"]
    if name == "spt_sections":
        return agent.sections(indexer)
    all_versions = arguments.get("all_versions") in (True, "true", "1")
    if name == "spt_search":
        return agent.search(indexer, str(arguments.get("query", "")),
                            str(arguments.get("kind", "")),
                            str(arguments.get("section", "")),
                            int(arguments.get("limit", 30)), all_versions,
                            str(arguments.get("client") or ""))
    if name == "spt_get":
        value = agent.get(indexer, str(arguments.get("id", "")))
        if value is None:
            raise ValueError("没有这个 id，先 spt_search")
        return value
    if name == "spt_export":
        return str(agent.export_file(indexer,
                                     str(arguments.get("format") or "xlsx"),
                                     str(arguments.get("kind") or ""),
                                     all_versions=all_versions))
    if name == "spt_metrics":
        return metrics_query(indexer, arguments)
    if name == "spt_metrics_add":
        return metrics_add(indexer, arguments)
    if name == "spt_metrics_analyse":
        from .metrics_write import record_analysis
        return record_analysis(indexer, arguments)
    raise ValueError("未知工具：" + name)


def respond(message: dict[str, Any]) -> dict[str, Any] | None:
    method, identifier = message.get("method"), message.get("id")
    if identifier is None:
        return None
    if method == "initialize":
        result: Any = {"protocolVersion": PROTOCOL,
                       "capabilities": {"tools": {}},
                       "serverInfo": {"name": "spt", "version": "0.2.0"},
                       "instructions": "SPT 是 用户的本地资产库。先调 spt_guide 了解放置规则，"
                                       "用 spt_search / spt_get 找提示词和素材。本服务只读；"
                                       "新建内容按规则直接写文件，然后 spt_reindex。"
                                       "数据记录用 spt_metrics 查、spt_metrics_add / "
                                       "spt_metrics_analyse 记（只追加文件）。"}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") or {}
        try:
            value = call(params.get("name", ""), params.get("arguments") or {})
            text = value if isinstance(value, str) else json.dumps(
                value, ensure_ascii=False, indent=1)
            result = {"content": [{"type": "text", "text": text}]}
        except Exception as error:
            result = {"content": [{"type": "text", "text": str(error)}],
                      "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": identifier,
                "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": identifier, "result": result}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            reply: dict[str, Any] | None = {
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = respond(message)
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
