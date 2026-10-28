"""Check dashboard_sources.json, the hand-kept source file behind the 情报 page.

Usage:
    python3 spt/server/tools/validate_sources.py <dashboard_sources.json 或草稿>

Exit status 0 when the file is valid. Otherwise one Chinese line on stderr
names the first problem and the exit status is 1 (2 for wrong usage).
Importing this module does nothing; `first_problem(data)` is the pure check.

The schema mirrors what dashboard_intelligence.py reads: the loader silently
ignores unknown keys, so a misspelt field would vanish from the page without
an error. This check is where that is caught.
"""
from __future__ import annotations
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator

TOP_LEVEL = ("checked_at", "source_document", "news", "research")
LISTS = ("news", "research")
LIMITS = {"news": 12, "research": 8}
ITEM_FIELDS = ("id", "title", "url", "source", "published_at", "checked_at",
               "summary", "state")
DATE_FIELDS = ("published_at", "checked_at")
MAX_BYTES = 2 * 1024 * 1024  # dashboard_io.MAX_SOURCE_BYTES: larger files are not read
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
URL = re.compile(r"https?://\S+")
USAGE = "用法：python3 spt/server/tools/validate_sources.py <dashboard_sources.json 或草稿>"


def text(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def date_problem(value: Any, what: str) -> str | None:
    if not isinstance(value, str) or not DATE.fullmatch(value):
        return f"{what} 不是日期（要 YYYY-MM-DD）：{value!r}"
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return f"{what} 不是真实日期：{value}"
    return None


def item_problem(name: str, index: int, item: Any) -> str | None:
    label = f"{name} 第 {index + 1} 条"
    if not isinstance(item, dict):
        return f"{label} 不是对象 {{...}}"
    for key in item:
        if key not in ITEM_FIELDS:
            return f"{label} 有不认识的字段：{key}（只允许 {'、'.join(ITEM_FIELDS)}）"
    if text(item.get("id")):
        label += f"（{item['id'].strip()}）"
    for field in ITEM_FIELDS:
        if field not in item:
            return f"{label} 缺少 {field}"
        if not text(item[field]):
            return f"{label} 的 {field} 为空或不是文字"
    if not URL.fullmatch(item["url"].strip()):
        return (f"{label} 的 url 必须以 http:// 或 https:// 开头，中间不能有空格："
                f"{item['url']}")
    for field in DATE_FIELDS:
        problem = date_problem(item[field], f"{label} 的 {field}")
        if problem:
            return problem
    if item["checked_at"] < item["published_at"]:
        return (f"{label} 的 checked_at（{item['checked_at']}）早于 "
                f"published_at（{item['published_at']}）")
    return None


def list_problem(name: str, items: Any) -> str | None:
    if not isinstance(items, list):
        return f"{name} 必须是列表 [...]"
    if len(items) > LIMITS[name]:
        return (f"{name} 超过 {LIMITS[name]} 条（现在 {len(items)} 条），"
                "按 published_at 去掉最旧的")
    for index, item in enumerate(items):
        problem = item_problem(name, index, item)
        if problem:
            return problem
    return None


def entries(data: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for name in LISTS:
        for index, item in enumerate(data.get(name, [])):
            yield f"{name} 第 {index + 1} 条（{item['id'].strip()}）", item


def duplicate_problem(data: dict[str, Any]) -> str | None:
    ids: dict[str, str] = {}
    keys: dict[tuple[str, str], str] = {}
    for label, item in entries(data):
        ident = item["id"].strip()
        if ident in ids:
            return f"{label} 的 id 和 {ids[ident]} 重复：{ident}"
        ids[ident] = label
        key = (item["url"].strip(), item["title"].strip())
        if key in keys:
            return f"{label} 和 {keys[key]} 重复（url 和标题都相同）：{key[0]}"
        keys[key] = label
    return None


def latest_problem(data: dict[str, Any]) -> str | None:
    top = data["checked_at"]
    for label, item in entries(data):
        for field in DATE_FIELDS:
            if item[field] > top:
                return (f"顶层 checked_at（{top}）早于 {label} 的 {field}"
                        f"（{item[field]}）：顶层日期要是文件里最新的一天")
    return None


def first_problem(data: Any) -> str | None:
    """Return the first problem in parsed JSON, or None when it is valid."""
    if not isinstance(data, dict):
        return "顶层必须是对象 {...}，不是列表或别的"
    for key in data:
        if key not in TOP_LEVEL:
            return f"顶层有不认识的字段：{key}（只允许 {'、'.join(TOP_LEVEL)}）"
    if "checked_at" not in data:
        return "缺少顶层 checked_at（这次核对的日期，页面显示为 as_of）"
    problem = date_problem(data["checked_at"], "顶层 checked_at")
    if problem:
        return problem
    if "source_document" in data and not text(data["source_document"]):
        return "source_document 为空或不是文字（相对软件根目录的路径）"
    for name in LISTS:
        problem = list_problem(name, data.get(name, []))
        if problem:
            return problem
    return duplicate_problem(data) or latest_problem(data)


def load(path: Path) -> tuple[Any, str | None]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, f"文件不存在：{path}"
    except OSError as error:
        return None, f"读不了文件：{path}（{error.strerror or error}）"
    if len(raw) > MAX_BYTES:
        return None, f"文件超过 2 MiB（{len(raw)} 字节），仪表盘不会读取"
    try:
        return json.loads(raw.decode("utf-8-sig")), None
    except UnicodeDecodeError:
        return None, "文件不是 UTF-8 文本"
    except ValueError as error:
        return None, f"不是合法 JSON：{error}"


def validate_file(path: Path) -> str | None:
    data, problem = load(path)
    return problem or first_problem(data)


def summary(data: dict[str, Any]) -> str:
    return (f"通过：news {len(data.get('news', []))} 条、"
            f"research {len(data.get('research', []))} 条、"
            f"checked_at {data['checked_at']}")


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        print(USAGE, file=sys.stderr)
        return 2
    data, problem = load(Path(argv[0]))
    problem = problem or first_problem(data)
    if problem:
        print(f"不通过：{problem}", file=sys.stderr)
        return 1
    print(summary(data))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
