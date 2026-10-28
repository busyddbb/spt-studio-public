"""数据记录 writes: append a row or add a file under a work's 数据/ or 工作区/数据/账号/.

Append only, as spt/docs/数据记录格式.md asks: rows go to the end of 表现.csv /
留存.csv (created with a header when missing), an analysis is a new file that never
replaces one. Every path is checked to stay inside the workspace and links are
refused; after writing, only the touched part of the index is refreshed.
"""
from __future__ import annotations
import csv
import datetime as dt
import io
import os
import re
from pathlib import Path
from typing import Any

from .files import BINARY, NOFOLLOW, is_link
from .metrics import (ACCOUNT_METRICS, ACCOUNTS, ANALYSES, FOLDER, HEADER_KEYS, LABELS,
                      METRICS, PERFORMANCE, RETENTION_FILE, number, parse_time,
                      platform_code, split_tags)

PERFORMANCE_FIELDS = ("at", "platform", "account", *METRICS, "source", "note")
RETENTION_FIELDS = ("at", "platform", "account", "second", "rate")
ACCOUNT_FIELDS = ("at", *ACCOUNT_METRICS, "source", "note")
NAME = re.compile(r"[^\s/\\:*?\"<>|.][^/\\:*?\"<>|]{0,59}")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
TEXT_LIMIT = 500
BODY_LIMIT = 64 * 1024


class MetricsError(ValueError):
    """A write that cannot be carried out as asked (HTTP 400)."""


class WorkLookup(LookupError):
    """No single work matches what was given (HTTP 404); the message lists candidates."""


# ---------------------------------------------------------------- values

def text(value: object, label: str, limit: int = TEXT_LIMIT, required: bool = False) -> str:
    """One line of text; newlines become spaces."""
    result = " ".join(str(value if value is not None else "").split())
    if required and not result:
        raise MetricsError(f"{label}不能为空")
    if len(result) > limit:
        raise MetricsError(f"{label}太长（最多 {limit} 字）")
    return result


def safe_name(value: object, label: str) -> str:
    result = text(value, label, 60)
    if result and (not NAME.fullmatch(result) or result.endswith(" ")):
        raise MetricsError(f"{label}：1–60 个字，不能以 . 开头，不能有 / \\ : * ? \" < > |")
    return result


def platform(value: object, required: bool = True) -> str:
    code = platform_code(value)
    if code is None:
        if not required and not str(value or "").strip():
            return ""
        raise MetricsError(f"平台「{value or ''}」不认识，可写 rednote、douyin、instagram…或 小红书、抖音")
    return code


def moment(value: object) -> str:
    """记录时间 as written to the file: the given time with its own offset (a naive one
    is this computer's zone), else now."""
    if value in (None, ""):
        return dt.datetime.now().astimezone().isoformat(timespec="seconds")
    parsed = parse_time(value)
    if parsed is None:
        raise MetricsError(f"记录时间「{value}」看不懂，请写 2026-10-22T09:30:00+08:00 这样的时间")
    return parsed.isoformat(timespec="seconds")


def numbers(value: dict[str, Any], fields: tuple[str, ...]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for field in fields:
        raw = value.get(field)
        if isinstance(raw, bool):
            raise MetricsError(f"{LABELS[field]}要是数字")
        try:
            parsed = number(raw if isinstance(raw, str) else ("" if raw is None else repr(raw)))
        except ValueError:
            raise MetricsError(f"{LABELS[field]}「{raw}」不是数字") from None
        if parsed is not None and parsed < 0:
            raise MetricsError(f"{LABELS[field]}不能是负数")
        result[field] = parsed
    return result


def shown(value: float | None) -> str:
    if value is None:
        return ""
    return str(int(value)) if value.is_integer() else repr(value)


def points(value: object) -> list[tuple[float, float]]:
    """Retention points from [[sec, rate], …] or "0:100,3:71.5,10:40"."""
    pairs: list[Any]
    if isinstance(value, str):
        pairs = [part.split(":") for part in re.split(r"[,，;；\s]+", value.strip()) if part]
    elif isinstance(value, list):
        pairs = value
    else:
        raise MetricsError("points 要是 [[秒, 留存率], …] 或 \"0:100,3:71.5\"")
    result = []
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise MetricsError("每个点要是 [秒, 留存率]")
        try:
            second, rate = number(str(pair[0])), number(str(pair[1]))
        except ValueError:
            raise MetricsError(f"留存点「{pair}」不是数字") from None
        if second is None or rate is None or second < 0 or rate < 0:
            raise MetricsError(f"留存点「{pair}」要有秒和留存率")
        result.append((second, rate))
    if not result:
        raise MetricsError("至少要一个留存点")
    return sorted(result)


# ---------------------------------------------------------------- places

def resolve_work(store: Any, value: object) -> dict[str, Any]:
    """The one work meant by an id, a folder name or a unique keyword."""
    key = text(value, "work", 200)
    if not key:
        raise MetricsError("要写 work：作品 id、文件夹名或唯一的关键字")
    found = store.lookup_work(key)
    if len(found) == 1:
        return found[0]
    if not found:
        raise WorkLookup(f"找不到作品「{key}」，先 spt search 一下")
    names = "、".join(Path(row["relative_path"]).name for row in found[:8])
    raise WorkLookup(f"「{key}」匹配到 {len(found)} 件作品：{names}，请写文件夹名")


def ensure_folder(root: Path, *parts: str) -> Path:
    """root/parts…, created when missing; a link anywhere on the way is refused."""
    current = root
    for part in parts:
        current = current / part
        if is_link(current):
            raise MetricsError(f"{current.relative_to(root)} 是替身，不写入")
        if not current.exists():
            current.mkdir()
        elif not current.is_dir():
            raise MetricsError(f"{current.relative_to(root)} 不是文件夹")
    return current


def open_append(path: Path) -> int:
    if is_link(path):
        raise MetricsError(f"{path.name} 是替身，不写入")
    return os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | NOFOLLOW | BINARY, 0o644)


def file_header(path: Path) -> list[str] | None:
    """The header cells of an existing CSV, None when the file is missing or empty."""
    if not path.exists():
        return None
    with path.open("rb") as source:
        first = source.read(64 * 1024).decode("utf-8-sig", errors="replace").splitlines()
    if not first or not first[0].strip():
        return None
    return next(csv.reader([first[0]]))


def column_order(header: list[str], fields: tuple[str, ...],
                 rows: list[dict[str, str]]) -> list[str | None]:
    """Which field each existing column takes; a value with no column is an error."""
    names = [cell.strip().casefold() for cell in header]
    order: list[str | None] = []
    for name in names:
        order.append(next((field for field in fields
                           if name in (LABELS[field].casefold(), field.casefold())), None))
    for field in fields:
        if field not in order and any(row.get(field) for row in rows):
            raise MetricsError(f"文件的表头里没有「{LABELS[field]}」这一列，请先补表头")
    return order


def append_rows(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    """Rows to the end of a CSV in its own column order; a new file gets the header."""
    header = file_header(path)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    if header is None:
        header = [LABELS[field] for field in fields]
        order: list[str | None] = list(fields)
        writer.writerow(header)
    else:
        order = column_order(header, fields, rows)
    for row in rows:
        writer.writerow([row.get(field, "") if field else "" for field in order])
    data = buffer.getvalue().encode("utf-8")
    descriptor = open_append(path)
    try:
        if os.fstat(descriptor).st_size:
            with path.open("rb") as source:
                source.seek(-1, os.SEEK_END)
                if source.read(1) not in (b"\n", b"\r"):
                    os.write(descriptor, b"\n")
        os.write(descriptor, data)
    finally:
        os.close(descriptor)


def free_name(folder: Path, stem: str, suffix: str) -> Path:
    candidate = folder / f"{stem}{suffix}"
    for count in range(2, 1000):
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
        candidate = folder / f"{stem}-{count}{suffix}"
    raise MetricsError(f"{stem} 重名太多")


def write_new(path: Path, content: str) -> None:
    if is_link(path):
        raise MetricsError(f"{path.name} 是替身，不写入")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW | BINARY, 0o644)
    try:
        os.write(descriptor, content.encode("utf-8"))
    finally:
        os.close(descriptor)


def refresh(indexer: Any, work_id: str | None) -> dict[str, Any] | None:
    """Put the written file into the index; None when a rebuild is already running
    (the watcher picks the change up within seconds anyway)."""
    try:
        return indexer.refresh_work(work_id) if work_id else indexer.refresh_accounts()
    except RuntimeError:
        return None


# ---------------------------------------------------------------- writes

def record_observation(indexer: Any, value: dict[str, Any]) -> dict[str, Any]:
    """`spt metrics add` / POST /api/metrics/add: one 表现.csv row."""
    work = resolve_work(indexer.store, value.get("work"))
    row = {"at": moment(value.get("at")), "platform": platform(value.get("platform")),
           "account": safe_name(value.get("account"), "账号"),
           "source": text(value.get("source"), "来源"), "note": text(value.get("note"), "备注")}
    metrics = numbers(value, METRICS)
    if all(item is None for item in metrics.values()):
        raise MetricsError("至少要填一个数字（浏览、点赞……）")
    folder = ensure_folder(indexer.work_folder(work), FOLDER)
    path = folder / PERFORMANCE
    cells = {**row, **{field: shown(item) for field, item in metrics.items()}}
    append_rows(path, PERFORMANCE_FIELDS, [cells])
    return {"work_id": work["id"], "path": path.relative_to(indexer.workspace).as_posix(),
            "row": {**row, "metrics": {field: (None if item is None else
                                               int(item) if item.is_integer() else item)
                                       for field, item in metrics.items()}},
            "index": refresh(indexer, work["id"])}


def record_retention(indexer: Any, value: dict[str, Any]) -> dict[str, Any]:
    """`spt metrics retention`: one curve, one 留存.csv row per point, same 记录时间."""
    work = resolve_work(indexer.store, value.get("work"))
    at, code = moment(value.get("at")), platform(value.get("platform"))
    account = safe_name(value.get("account"), "账号")
    curve = points(value.get("points"))
    folder = ensure_folder(indexer.work_folder(work), FOLDER)
    path = folder / RETENTION_FILE
    append_rows(path, RETENTION_FIELDS, [
        {"at": at, "platform": code, "account": account, "second": shown(second),
         "rate": shown(rate)} for second, rate in curve])
    return {"work_id": work["id"], "path": path.relative_to(indexer.workspace).as_posix(),
            "at": at, "platform": code, "account": account,
            "points": [[int(s) if s.is_integer() else s, int(r) if r.is_integer() else r]
                       for s, r in curve],
            "index": refresh(indexer, work["id"])}


def analysis_text(header: dict[str, str], body: str) -> str:
    lines = [f"{HEADER_KEYS[field]}: {value}" for field, value in header.items() if value]
    return "\n".join(lines) + "\n" + ("\n" + body.strip() + "\n" if body.strip() else "")


def record_analysis(indexer: Any, value: dict[str, Any]) -> dict[str, Any]:
    """`spt metrics analyse`: 数据/分析/<日期>-<节点或主题>.md, never replacing a file."""
    work = resolve_work(indexer.store, value.get("work"))
    date = text(value.get("date"), "日期", 10) or dt.date.today().isoformat()
    if not DATE.fullmatch(date):
        raise MetricsError("日期要写成 2026-10-22")
    header = {"platform": platform(value.get("platform"), required=False),
              "account": safe_name(value.get("account"), "账号"),
              "node": safe_name(value.get("node"), "节点"),
              "conclusion": text(value.get("conclusion"), "结论", required=True),
              "tags": ", ".join(split_tags(value.get("tags")) if not isinstance(
                  value.get("tags"), list) else
                  [text(tag, "标签", 40) for tag in value["tags"] if str(tag).strip()])}
    body = str(value.get("body") or "")
    if len(body) > BODY_LIMIT:
        raise MetricsError("正文太长")
    stem = header["node"] or safe_name(value.get("topic"), "主题") or "分析"
    folder = ensure_folder(indexer.work_folder(work), FOLDER, ANALYSES)
    path = free_name(folder, f"{date}-{stem}", ".md")
    write_new(path, analysis_text(header, body))
    return {"work_id": work["id"], "path": path.relative_to(indexer.workspace).as_posix(),
            "date": date, **header, "tags": split_tags(header["tags"]),
            "index": refresh(indexer, work["id"])}


def record_account(indexer: Any, value: dict[str, Any]) -> dict[str, Any]:
    """`spt metrics account`: one row in 工作区/数据/账号/<平台>-<账号>/表现.csv."""
    code = platform(value.get("platform"))
    account = safe_name(value.get("account"), "账号")
    if not account:
        raise MetricsError("账号不能为空")
    row = {"at": moment(value.get("at")), "source": text(value.get("source"), "来源"),
           "note": text(value.get("note"), "备注")}
    metrics = numbers(value, ACCOUNT_METRICS)
    if all(item is None for item in metrics.values()):
        raise MetricsError("至少要填一个数字（粉丝、浏览……）")
    folder = ensure_folder(indexer.workspace, FOLDER, ACCOUNTS, f"{code}-{account}")
    path = folder / PERFORMANCE
    append_rows(path, ACCOUNT_FIELDS,
                [{**row, **{field: shown(item) for field, item in metrics.items()}}])
    return {"platform": code, "account": account,
            "path": path.relative_to(indexer.workspace).as_posix(),
            "row": {**row, "metrics": {field: (None if item is None else
                                               int(item) if item.is_integer() else item)
                                       for field, item in metrics.items()}},
            "index": refresh(indexer, None)}
