"""数据记录: a work's 数据/ files and 工作区/数据/账号, read into the index and queried.

Files are the facts (spt/docs/数据记录格式.md); nothing here writes. 表现.csv rows
become observations with their age since publication, 留存.csv rows a retention
curve, 分析/*.md one analysis each. D1/D3/D7 are chosen at query time from the
stored ages: the observation closest to 24/72/168 h inside its window.
"""
from __future__ import annotations
import csv
import datetime as dt
import hashlib
import io
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable

from .files import FileError, read_text, safe_files, timestamp
from .models import AccountObservation, Analysis, Observation, Retention, Work

FOLDER = "数据"
ACCOUNTS = "账号"
PERFORMANCE = "表现.csv"
RETENTION_FILE = "留存.csv"
ANALYSES = "分析"
PLATFORMS = ("rednote", "douyin", "wechat_channels", "bilibili", "instagram",
             "facebook", "tiktok", "youtube", "google_business", "yelp")
PLATFORM_LABELS = {"rednote": "小红书", "douyin": "抖音", "wechat_channels": "视频号",
                   "bilibili": "B站", "instagram": "Instagram", "facebook": "Facebook",
                   "tiktok": "TikTok", "youtube": "YouTube",
                   "google_business": "Google 商家资料", "yelp": "Yelp"}
ALIASES = {"小红书": "rednote", "xiaohongshu": "rednote", "xhs": "rednote",
           "抖音": "douyin", "视频号": "wechat_channels", "微信视频号": "wechat_channels",
           "wechat": "wechat_channels", "channels": "wechat_channels",
           "b站": "bilibili", "哔哩哔哩": "bilibili", "油管": "youtube",
           "ins": "instagram", "ig": "instagram", "instagramreels": "instagram",
           "脸书": "facebook", "facebookreels": "facebook", "抖音国际": "tiktok",
           "google_business_profile": "google_business", "google商家资料": "google_business",
           "google商家": "google_business", "googlebusinessprofile": "google_business",
           "谷歌商家": "google_business"}
# node: (target hours, window start inclusive, window end exclusive)
NODES = {"D1": (24.0, 18.0, 48.0), "D3": (72.0, 48.0, 120.0), "D7": (168.0, 120.0, 240.0)}
METRICS = ("views", "reach", "likes", "comments", "saves", "shares", "profile_visits",
           "follows", "ctr", "three_sec_rate", "completion_rate", "avg_watch_sec")
ACCOUNT_METRICS = ("followers", "views", "reach", "interactions", "likes", "comments",
                   "saves", "shares", "profile_visits", "follows")
PERCENTS = {"ctr", "three_sec_rate", "completion_rate", "rate"}
LABELS = {"at": "记录时间", "platform": "平台", "account": "账号", "views": "浏览",
          "reach": "触达", "likes": "点赞", "comments": "评论", "saves": "收藏",
          "shares": "分享", "profile_visits": "主页访问", "follows": "涨粉",
          "ctr": "点击率", "three_sec_rate": "三秒率", "completion_rate": "完播率",
          "avg_watch_sec": "平均观看秒", "source": "来源", "note": "备注",
          "followers": "粉丝", "interactions": "互动", "second": "秒", "rate": "留存率"}
COLUMNS = {field: (label, field) for field, label in LABELS.items()}
COLUMNS.update({"at": ("记录时间", "时间", "at", "observed_at"), "views": ("浏览", "播放", "views"),
                "shares": ("分享", "转发", "shares"), "follows": ("涨粉", "follows", "follows_gained"),
                "avg_watch_sec": ("平均观看秒", "平均观看", "avg_watch_sec", "avg_watch_time_sec")})
HEADER_KEYS = {"platform": "平台", "account": "账号", "node": "节点", "conclusion": "结论",
               "tags": "标签", "date": "日期"}
ZONES = {"Z": 0, "UTC": 0, "GMT": 0, "PDT": -7, "PST": -8, "MDT": -6, "MST": -7, "CDT": -5,
         "EDT": -4, "EST": -5, "BST": 1, "CET": 1, "CEST": 2, "HKT": 8, "SGT": 8, "JST": 9}
TIME = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?))?"
                  r"\s*(Z|[A-Z]{3,4}|[+-]\d{2}:?\d{2})?")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
ISSUE_LIMIT = 8   # bad rows reported per file; the rest is skipped quietly


# ---------------------------------------------------------------- values

def platform_code(value: object) -> str | None:
    """The 表现.csv platform vocabulary, from an id, an alias or a Chinese name."""
    text = re.sub(r"[\s#·：:_-]", "", str(value or "")).casefold()
    if not text:
        return None
    for name in PLATFORMS:
        if text == name.replace("_", ""):
            return name
    return ALIASES.get(text) or ALIASES.get(str(value or "").strip().casefold())


def parse_time(value: object) -> dt.datetime | None:
    """A moment from the forms records carry: ISO with offset or Z, `2026-09-08 17:22 PDT`,
    a naive time (this computer's zone) or a bare date (its noon)."""
    text = " ".join(str(value or "").split())
    match = TIME.fullmatch(text)
    if not match:
        return None
    day, clock, zone = match.groups()
    try:
        moment = dt.datetime.fromisoformat(day + "T" + (clock or "12:00"))
    except ValueError:
        return None
    if zone is None:
        return moment.astimezone()
    if zone in ZONES:
        return moment.replace(tzinfo=dt.timezone(dt.timedelta(hours=ZONES[zone])))
    if re.fullmatch(r"[+-]\d{2}:?\d{2}", zone):
        hours, minutes = int(zone[1:3]), int(zone[-2:])
        offset = dt.timedelta(hours=hours, minutes=minutes)
        return moment.replace(tzinfo=dt.timezone(-offset if zone[0] == "-" else offset))
    return None


def iso_utc(moment: dt.datetime) -> str:
    return moment.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def number(value: object) -> float | None:
    """A cell's number; empty is None (unknown, not 0); `12.5%` is 12.5. Raises ValueError."""
    text = str(value if value is not None else "").strip().replace(",", "").replace("，", "")
    if text.endswith("%") or text.endswith("％"):
        text = text[:-1].strip()
    if not text:
        return None
    if len(text) > 32 or not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        raise ValueError(text)
    return float(text)


def plain(value: float | None) -> int | float | None:
    """Numbers as the API shows them: whole numbers as int."""
    if value is None:
        return None
    return int(value) if float(value).is_integer() else value


def split_tags(value: object) -> list[str]:
    """标签 split on , ， 、 ; order kept, duplicates dropped."""
    parts = [part.strip() for part in re.split(r"[,，、]", str(value or ""))]
    return list(dict.fromkeys(part for part in parts if part))


def identifier(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:20]


# ---------------------------------------------------------------- CSV

def csv_table(text: str) -> tuple[dict[str, int], list[tuple[int, list[str]]]]:
    """(field -> column index by header name, [(line number, cells)…])."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    header = next(reader, None)
    if header is None:
        return {}, []
    names = [cell.strip().casefold() for cell in header]
    columns: dict[str, int] = {}
    for field, aliases in COLUMNS.items():
        for alias in aliases:
            if alias.casefold() in names:
                columns[field] = names.index(alias.casefold())
                break
    rows = []
    for cells in reader:
        if any(cell.strip() for cell in cells):
            rows.append((reader.line_num, cells))
    return columns, rows


def cell(cells: list[str], columns: dict[str, int], field: str) -> str:
    index = columns.get(field)
    return cells[index].strip() if index is not None and index < len(cells) else ""


class Reporter:
    """Collects at most ISSUE_LIMIT issues for one file, each naming file and line."""

    def __init__(self, label: str, issues: list[str]) -> None:
        self.label, self.issues, self.count = label, issues, 0

    def bad(self, line: int, text: str) -> None:
        self.count += 1
        if self.count <= ISSUE_LIMIT:
            self.issues.append(f"{self.label} 第 {line} 行：{text}，已跳过")


def read_numbers(cells: list[str], columns: dict[str, int], fields: tuple[str, ...],
                 report: Reporter, line: int) -> dict[str, float | None] | None:
    values: dict[str, float | None] = {}
    for field in fields:
        try:
            values[field] = number(cell(cells, columns, field))
        except ValueError:
            report.bad(line, f"{LABELS[field]}「{cell(cells, columns, field)}」不是数字")
            return None
    return values


def read_performance(path: Path, label: str, issues: list[str]) -> list[Observation]:
    """Rows of a work's 表现.csv; a row without a readable time or platform is reported."""
    columns, rows = csv_table(read_text(path))
    report = Reporter(label, issues)
    if "at" not in columns:
        issues.append(f"{label}：表头里没有「记录时间」")
        return []
    result = []
    for line, cells in rows:
        moment = parse_time(cell(cells, columns, "at"))
        platform = platform_code(cell(cells, columns, "platform"))
        if moment is None:
            report.bad(line, f"记录时间「{cell(cells, columns, 'at')}」看不懂")
            continue
        if not platform:
            report.bad(line, f"平台「{cell(cells, columns, 'platform')}」不认识")
            continue
        values = read_numbers(cells, columns, METRICS, report, line)
        if values is None:
            continue
        result.append(Observation(iso_utc(moment), platform, cell(cells, columns, "account"),
                                  label, None, source=cell(cells, columns, "source"),
                                  note=cell(cells, columns, "note"), **values))
    result.sort(key=lambda item: item.at)
    return result


def read_retention(path: Path, label: str, issues: list[str]) -> list[Retention]:
    columns, rows = csv_table(read_text(path))
    report = Reporter(label, issues)
    if "at" not in columns or "second" not in columns or "rate" not in columns:
        issues.append(f"{label}：表头要有「记录时间」「秒」「留存率」")
        return []
    result = []
    for line, cells in rows:
        moment = parse_time(cell(cells, columns, "at"))
        platform = platform_code(cell(cells, columns, "platform"))
        if moment is None:
            report.bad(line, f"记录时间「{cell(cells, columns, 'at')}」看不懂")
            continue
        if not platform:
            report.bad(line, f"平台「{cell(cells, columns, 'platform')}」不认识")
            continue
        values = read_numbers(cells, columns, ("second", "rate"), report, line)
        if values is None:
            continue
        if values["second"] is None or values["rate"] is None:
            report.bad(line, "秒和留存率都要填")
            continue
        result.append(Retention(iso_utc(moment), platform, cell(cells, columns, "account"),
                                values["second"], values["rate"], label))
    result.sort(key=lambda item: (item.at, item.second))
    return result


def read_account_performance(path: Path, platform: str, account: str, label: str,
                             issues: list[str]) -> list[AccountObservation]:
    columns, rows = csv_table(read_text(path))
    report = Reporter(label, issues)
    if "at" not in columns:
        issues.append(f"{label}：表头里没有「记录时间」")
        return []
    result = []
    for line, cells in rows:
        moment = parse_time(cell(cells, columns, "at"))
        if moment is None:
            report.bad(line, f"记录时间「{cell(cells, columns, 'at')}」看不懂")
            continue
        values = read_numbers(cells, columns, ACCOUNT_METRICS, report, line)
        if values is None:
            continue
        result.append(AccountObservation(platform, account, iso_utc(moment), label,
                                         source=cell(cells, columns, "source"),
                                         note=cell(cells, columns, "note"), **values))
    result.sort(key=lambda item: item.at)
    return result


# ---------------------------------------------------------------- 分析

def split_header(text: str) -> tuple[dict[str, str], str]:
    """Leading `键: 值` lines (optionally fenced by ---) until a blank line, then the body.

    Lines are taken as a header only when one of the known keys is among them;
    otherwise the whole file is body.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    fenced = bool(lines) and lines[0].strip() == "---"
    index = 1 if fenced else 0
    header: dict[str, str] = {}
    while index < len(lines):
        line = lines[index]
        if fenced and line.strip() == "---":
            index += 1
            break
        if not line.strip():
            break
        match = re.match(r"^([^:：#\s][^:：]{0,19})[:：]\s*(.*)$", line)
        if not match:
            if fenced:
                index += 1
                continue
            break
        header[match.group(1).strip()] = match.group(2).strip()
        index += 1
    if not any(key in header for key in HEADER_KEYS.values()):
        return {}, text.strip()
    return header, "\n".join(lines[index:]).strip()


def read_analysis(path: Path, label: str, platform: str = "", account: str = "") -> Analysis:
    """One analysis file. platform/account are the folder's for account-level files."""
    header, body = split_header(read_text(path))
    value = {field: header.get(key, "") for field, key in HEADER_KEYS.items()}
    named = DATE.search(path.stem)
    date = value["date"] if DATE.fullmatch(value["date"]) else (
        named.group(0) if named else
        dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone().date().isoformat())
    return Analysis(label, date, platform_code(value["platform"]) or platform,
                    value["account"] or account, value["node"], value["conclusion"], body,
                    timestamp(path), split_tags(value["tags"]))


def read_analyses(folder: Path, root: Path, issues: list[str],
                  platform: str = "", account: str = "") -> list[Analysis]:
    if not folder.is_dir() or folder.is_symlink():
        return []
    result = []
    for path in safe_files(folder):
        if path.suffix.lower() != ".md":
            continue
        label = path.relative_to(root).as_posix()
        try:
            result.append(read_analysis(path, label, platform, account))
        except (FileError, OSError, UnicodeError) as error:
            issues.append(f"{label}：{error}")
    result.sort(key=lambda item: (item.date, item.path), reverse=True)
    return result


# ---------------------------------------------------------------- works

def publish_moments(records: list[Any]) -> dict[str, dt.datetime]:
    """Publish time per platform code from the current publish records; "" is the
    earliest of them, used for a platform the records do not name."""
    moments: dict[str, dt.datetime] = {}
    for record in records:
        state = record.state if hasattr(record, "state") else record["state"]
        platform = record.platform if hasattr(record, "platform") else record["platform"]
        published = record.published_at if hasattr(record, "published_at") else record["published_at"]
        moment = parse_time(published) if state == "current" else None
        if moment is None:
            continue
        code = platform_code(platform) or platform
        if code not in moments or moment < moments[code]:
            moments[code] = moment
        if "" not in moments or moment < moments[""]:
            moments[""] = moment
    return moments


def age_hours(at: str, platform: str, moments: dict[str, dt.datetime]) -> float | None:
    published = moments.get(platform) or moments.get("")
    if published is None:
        return None
    seen = dt.datetime.fromisoformat(at)
    return round((seen - published).total_seconds() / 3600, 2)


def read_metrics(work: Work, root: Path, issues: list[str]) -> None:
    """Fill a work's observations, retention and analyses from its 数据/ folder.

    Problems are reported with file and line in the index issues and on the work.
    """
    folder = Path(work.path) / FOLDER
    if not folder.is_dir() or folder.is_symlink():
        return
    found: list[str] = []
    files = {path.name: path for path in safe_files(folder)}
    readers: tuple[tuple[str, Callable[..., list[Any]], str], ...] = (
        (PERFORMANCE, read_performance, "observations"),
        (RETENTION_FILE, read_retention, "retention"))
    for name, reader, attribute in readers:
        if name in files:
            label = files[name].relative_to(root).as_posix()
            try:
                setattr(work, attribute, reader(files[name], label, found))
            except (FileError, OSError, UnicodeError, csv.Error) as error:
                found.append(f"{label}：{error}")
    work.analyses = read_analyses(folder / ANALYSES, root, found)
    moments = publish_moments(work.records)
    for observation in work.observations:
        observation.age_hours = age_hours(observation.at, observation.platform, moments)
    work.issues.extend(found)
    issues.extend(found)


def account_folder(name: str) -> tuple[str, str] | None:
    """`<平台>-<账号>` → (platform code, account); None when the platform is unknown."""
    platform, separator, account = name.partition("-")
    code = platform_code(platform)
    return (code, account.strip()) if code and separator and account.strip() else None


def scan_accounts(root: Path, issues: list[str]
                  ) -> tuple[list[AccountObservation], list[Analysis]]:
    """Everything under 工作区/数据/账号/."""
    base = root / FOLDER / ACCOUNTS
    observations: list[AccountObservation] = []
    analyses: list[Analysis] = []
    if not base.is_dir() or base.is_symlink():
        return observations, analyses
    for folder in sorted(base.iterdir()):
        if not folder.is_dir() or folder.is_symlink() or folder.name.startswith("."):
            continue
        parsed = account_folder(folder.name)
        if parsed is None:
            issues.append(f"{FOLDER}/{ACCOUNTS}/{folder.name}：文件夹名要是「平台-账号」，已跳过")
            continue
        platform, account = parsed
        table = folder / PERFORMANCE
        if table in safe_files(folder):
            label = table.relative_to(root).as_posix()
            try:
                observations.extend(read_account_performance(table, platform, account, label, issues))
            except (FileError, OSError, UnicodeError, csv.Error) as error:
                issues.append(f"{label}：{error}")
        analyses.extend(read_analyses(folder / ANALYSES, root, issues, platform, account))
    return observations, analyses


# ---------------------------------------------------------------- nodes

def assign_nodes(points: list[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    """Per node the observation whose age is closest to the target inside the window;
    readings with a view count win over ones without (a public page often shows
    likes but not views); ties go to the earlier one. Each gets late_hours = age - target."""
    nodes: dict[str, dict[str, Any] | None] = {}
    for label, (target, low, high) in NODES.items():
        inside = [point for point in points
                  if point["age_hours"] is not None and low <= point["age_hours"] < high]
        best = min(inside, key=lambda point: (point["metrics"].get("views") is None,
                                              abs(point["age_hours"] - target), point["at"]),
                   default=None)
        nodes[label] = None if best is None else {
            "at": best["at"], "age_hours": best["age_hours"],
            "late_hours": round(best["age_hours"] - target, 2), "metrics": best["metrics"],
            "platform": best["platform"], "account": best["account"]}
    return nodes


def empty_metrics(fields: tuple[str, ...] = METRICS) -> dict[str, None]:
    return dict.fromkeys(fields)


# ---------------------------------------------------------------- queries

def public_observation(row: dict[str, Any]) -> dict[str, Any]:
    return {"at": row["at"], "age_hours": row["age_hours"], "platform": row["platform"],
            "account": row["account"] or "",
            "metrics": {field: plain(row[field]) for field in METRICS},
            "source": row["source"] or "", "note": row["note"] or "", "path": row["path"]}


def public_analysis(row: dict[str, Any], tags: list[str], body: bool = True) -> dict[str, Any]:
    result = {"path": row["path"], "date": row["date"], "platform": row["platform"] or "",
              "account": row["account"] or "", "node": row["node"] or "",
              "conclusion": row["conclusion"] or "", "tags": tags,
              "modified_at": row["modified_at"]}
    if body:
        result["body"] = row["body"] or ""
    return result


def analyses_for(connection: sqlite3.Connection, work_id: str,
                 body: bool = True) -> list[dict[str, Any]]:
    tags: dict[str, list[str]] = {}
    for row in connection.execute("SELECT path,tag FROM metric_analysis_tags WHERE work_id=? "
                                  "ORDER BY rowid", (work_id,)):
        tags.setdefault(row["path"], []).append(row["tag"])
    return [public_analysis(dict(row), tags.get(row["path"], []), body)
            for row in connection.execute("SELECT * FROM metric_analyses WHERE work_id=? "
                                          "ORDER BY date DESC, path DESC", (work_id,))]


def curves(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retention rows → curves, newest first; one curve per (at, platform, account)."""
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["at"], row["platform"], row["account"] or "")
        curve = grouped.setdefault(key, {"at": row["at"], "platform": row["platform"],
                                         "account": row["account"] or "", "points": []})
        curve["points"].append([plain(row["second"]), plain(row["rate"])])
    for curve in grouped.values():
        curve["points"].sort(key=lambda point: point[0])
    return sorted(grouped.values(), key=lambda curve: curve["at"], reverse=True)


def retention_for(connection: sqlite3.Connection, work_id: str) -> list[dict[str, Any]]:
    return curves([dict(row) for row in connection.execute(
        "SELECT * FROM metric_retention WHERE work_id=? ORDER BY position", (work_id,))])


def matches_post(item: dict[str, Any], platform: str, account: str) -> bool:
    """An analysis or curve belongs to a post when its platform/account agree or are blank."""
    return (not item["platform"] or item["platform"] == platform) and \
        (not item["account"] or not account or item["account"] == account)


def points_of(observations: list[dict[str, Any]],
              nodes: dict[str, dict[str, Any] | None]) -> list[dict[str, Any]]:
    chosen = {node["at"]: label for label, node in nodes.items() if node}
    return [{"window": chosen.get(item["at"]), "metrics": item["metrics"],
             "observed_at": item["at"], "age_hours": item["age_hours"],
             "source": item["source"], "note": item["note"]} for item in observations]


def post_shape(work: dict[str, Any], platform: str, account: str,
               observations: list[dict[str, Any]], analyses: list[dict[str, Any]],
               retention: list[dict[str, Any]], published_at: str | None,
               url: str | None) -> dict[str, Any]:
    """One post per (work, platform, account), in the dashboard's post shape."""
    nodes = assign_nodes(observations)
    latest = observations[-1]
    window = next((label for label, node in nodes.items()
                   if node and node["at"] == latest["at"]), None)
    own = [item for item in analyses if matches_post(item, platform, account)]
    curve = next((item for item in retention if matches_post(item, platform, account)), None)
    return {
        "id": identifier("workspace", work["id"], platform, account),
        "account_id": None, "content_id": work["id"], "work_id": work["id"],
        "title": work["title"], "client": work["client"],
        "relative_path": work["relative_path"], "platform": platform, "account": account,
        "url": url, "published_at": published_at, "caption": None, "caption_complete": False,
        "format": None, "duration_sec": None, "status": "published", "current": True,
        "source_kind": "workspace_metrics", "observed_at": latest["at"],
        "metrics": latest["metrics"], "metric_window": window,
        "latest": {"at": latest["at"], "age_hours": latest["age_hours"],
                   "metrics": latest["metrics"]},
        "nodes": nodes,
        "metrics_by_window": {label: (node["metrics"] if node else empty_metrics())
                              for label, node in nodes.items()},
        "metric_observed_at_by_window": {label: (node["at"] if node else None)
                                         for label, node in nodes.items()},
        "history": points_of(observations, nodes),
        "analyses": own, "tags": sorted({tag for item in own for tag in item["tags"]}),
        "retention": curve, "source": latest["path"],
        "cover": work.get("cover"), "preview_url": None, "issues": [],
    }


def work_row(connection: sqlite3.Connection, work_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT id,title,client,relative_path,cover_source,cover_cache "
                             "FROM works WHERE id=?", (work_id,)).fetchone()
    if row is None:
        return None
    from .store import cover_url
    work = dict(row)
    has_cover = work["cover_source"] or work["cover_cache"]
    work["cover"] = cover_url(work_id, work["cover_cache"]) if has_cover else None
    return work


def publication(connection: sqlite3.Connection, work_id: str
                ) -> tuple[dict[str, dt.datetime], dict[str, str]]:
    """(publish moments per platform, current url per platform) from publish_records."""
    rows = [dict(row) for row in connection.execute(
        "SELECT platform,url,published_at,state FROM publish_records WHERE work_id=? "
        "ORDER BY position", (work_id,))]
    urls: dict[str, str] = {}
    for row in rows:
        code = platform_code(row["platform"]) or row["platform"]
        if row["state"] == "current" and row["url"] and code not in urls:
            urls[code] = row["url"]
    return publish_moments(rows), urls


def published_iso(moments: dict[str, dt.datetime], platform: str) -> str | None:
    """The publish moment in the zone it was recorded in, so its date is the day it went out."""
    moment = moments.get(platform) or moments.get("")
    return moment.isoformat(timespec="seconds") if moment else None


def posts_of(connection: sqlite3.Connection, work: dict[str, Any],
             observations: list[dict[str, Any]], body: bool = False) -> list[dict[str, Any]]:
    """The work's posts: one per (platform, account) that has observations."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in observations:
        groups.setdefault((item["platform"], item["account"]), []).append(item)
    analyses = analyses_for(connection, work["id"], body)
    retention = retention_for(connection, work["id"])
    moments, urls = publication(connection, work["id"])
    return [post_shape(work, platform, account, group, analyses, retention,
                       published_iso(moments, platform), urls.get(platform))
            for (platform, account), group in groups.items()]


def observations_for(connection: sqlite3.Connection, work_id: str) -> list[dict[str, Any]]:
    return [public_observation(dict(row)) for row in connection.execute(
        "SELECT * FROM metric_observations WHERE work_id=? ORDER BY at, position", (work_id,))]


def work_metrics(connection: sqlite3.Connection, work_id: str) -> dict[str, Any]:
    """Everything recorded for one work. nodes/latest follow the (platform, account)
    with the newest observation; `posts` has every combination."""
    work = work_row(connection, work_id)
    observations = observations_for(connection, work_id) if work else []
    posts = posts_of(connection, work, observations, body=True) if work else []
    newest = max(posts, key=lambda post: post["observed_at"], default=None)
    return {"observations": observations,
            "nodes": newest["nodes"] if newest else dict.fromkeys(NODES),
            "latest": newest["latest"] if newest else None,
            "retention": retention_for(connection, work_id) if work else [],
            "analyses": analyses_for(connection, work_id) if work else [],
            "posts": posts}


def in_range(moment: str | None, since: str, until: str) -> bool:
    """since/until are dates or ISO times; a bare until date includes that whole day."""
    if not since and not until:
        return True
    if moment is None:
        return False
    seen = dt.datetime.fromisoformat(moment)
    start = parse_time(since) if since else None
    end = parse_time(until) if until else None
    if since and start is None or until and end is None:
        raise ValueError("since/until 要写成 2026-10-01 这样的日期")
    if end is not None and DATE.fullmatch(until.strip()):
        end = end.replace(hour=23, minute=59, second=59)
    if start is not None and DATE.fullmatch(since.strip()):
        start = start.replace(hour=0, minute=0, second=0)
    return (start is None or seen >= start) and (end is None or seen <= end)


def mentions(post: dict[str, Any], query: str) -> bool:
    words = query.casefold().split()
    if not words:
        return True
    parts = [post["title"], post["client"], post["platform"], post["account"],
             post["relative_path"]]
    parts += [item["conclusion"] + " " + " ".join(item["tags"]) for item in post["analyses"]]
    haystack = "\n".join(parts).casefold()
    return all(word in haystack for word in words)


def metrics_posts(connection: sqlite3.Connection, client: str = "", platform: str = "",
                  account: str = "", since: str = "", until: str = "", tag: str = "",
                  q: str = "") -> list[dict[str, Any]]:
    """Posts in the dashboard shape, newest publication first. since/until apply to
    the publish time, or to the latest observation when there is none."""
    code = platform_code(platform) if platform else None
    if platform and code is None:
        raise ValueError(f"平台「{platform}」不认识")
    sql, values = "SELECT DISTINCT work_id FROM metric_observations WHERE 1=1", []
    for column, value in (("platform", code), ("account", account)):
        if value:
            sql += f" AND {column}=?"
            values.append(value)
    posts: list[dict[str, Any]] = []
    for row in connection.execute(sql, values):
        work = work_row(connection, row["work_id"])
        if work is None or (client and work["client"] != client):
            continue
        observations = [item for item in observations_for(connection, work["id"])
                        if (not code or item["platform"] == code)
                        and (not account or item["account"] == account)]
        posts.extend(posts_of(connection, work, observations))
    posts = [post for post in posts
             if (not tag or tag in post["tags"]) and mentions(post, q)
             and in_range(post["published_at"] or post["observed_at"], since, until)]
    posts.sort(key=lambda post: (post["published_at"] or post["observed_at"] or "",
                                 post["title"]), reverse=True)
    return posts


def recorded_posts(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """Posts that 发布记录.md says went out but that have no 表现.csv row yet, so a
    publication shows the day it happens, not the day its first numbers are
    recorded (用户 2026-10-24: "昨天发布的都没有显示"). One per (work, platform)."""
    posts: list[dict[str, Any]] = []
    rows = connection.execute(
        "SELECT work_id, platform, account, url, published_at FROM publish_records "
        "WHERE state='current' ORDER BY work_id, position").fetchall()
    by_work: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_work.setdefault(row["work_id"], []).append(dict(row))
    for work_id, records in by_work.items():
        work = work_row(connection, work_id)
        if work is None:
            continue
        seen = {(item["platform"], item["account"]) for item in observations_for(connection, work_id)}
        observed_platforms = {platform for platform, _ in seen}
        moments, urls = publication(connection, work_id)
        done: set[str] = set()
        for record in records:
            code = platform_code(record["platform"]) or record["platform"]
            if not code or code in done or code in observed_platforms:
                continue
            done.add(code)
            account = str(record["account"] or "")
            posts.append({
                "id": identifier("workspace", work_id, code, account),
                "account_id": None, "content_id": work_id, "work_id": work_id,
                "title": work["title"], "client": work["client"],
                "relative_path": work["relative_path"], "platform": code, "account": account,
                "url": urls.get(code), "published_at": published_iso(moments, code),
                "caption": None, "caption_complete": False, "format": None,
                "duration_sec": None, "status": "published", "current": True,
                "source_kind": "publish_record", "observed_at": None,
                "metrics": empty_metrics(), "metric_window": None, "latest": None,
                "nodes": dict.fromkeys(NODES),
                "metrics_by_window": {label: empty_metrics() for label in NODES},
                "metric_observed_at_by_window": dict.fromkeys(NODES),
                "history": [], "analyses": [], "tags": [], "retention": None,
                "source": None, "cover": work.get("cover"), "preview_url": None,
                "issues": [],
            })
    return posts


def account_tags(connection: sqlite3.Connection, platform: str = "",
                 account: str = "") -> list[str]:
    sql = ("SELECT t.tag FROM account_analysis_tags t JOIN account_analyses a ON a.path=t.path "
           "WHERE 1=1")
    values = []
    code = platform_code(platform) if platform else None
    for column, value in (("platform", code), ("account", account)):
        if value:
            sql += f" AND a.{column}=?"
            values.append(value)
    return [row[0] for row in connection.execute(sql, values)]


def metrics_tags(connection: sqlite3.Connection, client: str = "", platform: str = "",
                 account: str = "", since: str = "", until: str = "", tag: str = "",
                 q: str = "") -> list[dict[str, Any]]:
    """[{tag, count, post_ids}] most frequent first. count is analyses carrying the tag
    (account-level ones too, unless a client is given); post_ids the posts among them."""
    counts: dict[str, int] = {}
    post_ids: dict[str, list[str]] = {}
    for post in metrics_posts(connection, client, platform, account, since, until, tag, q):
        for item in post["analyses"]:
            for name in item["tags"]:
                if tag and name != tag:
                    continue
                counts[name] = counts.get(name, 0) + 1
                post_ids.setdefault(name, [])
                if post["id"] not in post_ids[name]:
                    post_ids[name].append(post["id"])
    if not client:
        for name in account_tags(connection, platform, account):
            if not tag or name == tag:
                counts[name] = counts.get(name, 0) + 1
                post_ids.setdefault(name, [])
    return [{"tag": name, "count": counts[name], "post_ids": post_ids[name]}
            for name in sorted(counts, key=lambda name: (-counts[name], name))]


def account_metrics(connection: sqlite3.Connection, platform: str = "",
                    account: str = "") -> list[dict[str, Any]]:
    """Per (platform, account) under 工作区/数据/账号: latest numbers, history, analyses."""
    code = platform_code(platform) if platform else None
    sql, values = "SELECT * FROM account_observations WHERE 1=1", []
    for column, value in (("platform", code), ("account", account)):
        if value:
            sql += f" AND {column}=?"
            values.append(value)
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for row in connection.execute(sql + " ORDER BY platform, account, at, position", values):
        row = dict(row)
        entry = groups.setdefault((row["platform"], row["account"]), {
            "platform": row["platform"], "account": row["account"],
            "platform_label": PLATFORM_LABELS.get(row["platform"], row["platform"]),
            "latest": None, "history": [], "analyses": []})
        point = {"at": row["at"], "metrics": {field: plain(row[field]) for field in ACCOUNT_METRICS},
                 "source": row["source"] or "", "note": row["note"] or "", "path": row["path"]}
        entry["history"].append(point)
        entry["latest"] = {"at": point["at"], **point["metrics"], "source": point["source"],
                           "note": point["note"]}
    tags: dict[str, list[str]] = {}
    for row in connection.execute("SELECT path,tag FROM account_analysis_tags ORDER BY rowid"):
        tags.setdefault(row["path"], []).append(row["tag"])
    for row in connection.execute("SELECT * FROM account_analyses ORDER BY date DESC, path DESC"):
        row = dict(row)
        if (code and row["platform"] != code) or (account and row["account"] != account):
            continue
        entry = groups.setdefault((row["platform"], row["account"]), {
            "platform": row["platform"], "account": row["account"],
            "platform_label": PLATFORM_LABELS.get(row["platform"], row["platform"]),
            "latest": None, "history": [], "analyses": []})
        entry["analyses"].append(public_analysis(row, tags.get(row["path"], [])))
    return list(groups.values())


def client_code(value: str, clients: list[dict[str, Any]]) -> str:
    """A client given by name (客户.md 名字) becomes its code; codes pass through."""
    text = value.strip()
    if not text or any(row["code"] == text for row in clients):
        return text
    named = [row["code"] for row in clients if str(row.get("name") or "").casefold() == text.casefold()]
    return named[0] if len(named) == 1 else text
