"""SPT 读数据: the Mac app reads the 小红书 creator center with this Mac's own login;
this module matches what it read to works and appends it to their 数据/表现.csv.

Flow: a request (the 数据 page button, `spt metrics capture`, or the schedule below)
waits here; the Mac app claims it, opens 笔记管理 for each logged-in 小红书 account
and posts back what the page showed: each note's title, publish time and five
numbers, the account name in the page header, the follower count on the profile.
Nothing here talks to the platform. Windows has no reader, so a request nobody
claims within a minute and a half ends with a message saying so.

Writes follow spt/docs/数据记录格式.md: append only, empty is not 0, one 记录时间
per read. A note is matched to a work by its note ID in 发布记录.md, else by its
title together with its publish time.
"""
from __future__ import annotations
import datetime as dt
import json
import re
import threading
import unicodedata
import uuid
from pathlib import Path
from typing import Any

from . import metrics_write
from .metrics import parse_time, platform_code

AUTO_HOURS = 8             # the app reads by itself when the last good read is this old
NODE_HOURS = (24, 72, 168) # …and when a post's D1 / D3 / D7 moment has passed since that read
RETRY_HOURS = 2            # …but waits this long after a failed one
CLAIM_SECONDS = 90         # a request nobody claims ends then (no Mac app running)
READ_MINUTES = 10          # a read that has not finished by then is given up
SAME_READ_MINUTES = 45     # a work read again this soon is left alone
UNCHANGED_HOURS = 20       # identical numbers are written again only after this long
HISTORY = 20               # finished runs kept in the status file
LIST_ZONE = dt.timezone(dt.timedelta(hours=8))   # 笔记管理 shows publish times in China time
TITLE_HOURS = 12           # a title match whose publish times differ more is refused
CAPTION_CHARS = 40         # a caption prefix this long names a post as well as a title does
NEAR_MINUTES = 45          # a lone work published this close to a row's time is that row
SOURCE_NOTES = "SPT 读数据 · 笔记管理"
SOURCE_PROFILE = "SPT 读数据 · 主页"
LIST_ORDER = ("views", "comments", "likes", "saves", "shares")   # the list's icon order
NOT_LIVE = re.compile(r"审核中|未通过|仅自己可见|已删除|违规")
NOTE_ID = re.compile(r"(?<![0-9a-f])([0-9a-f]{24})(?![0-9a-f])")
NUMBER = re.compile(r"\d[\d,]*")
# 账号档案 platform → 表现.csv platform; only these have a reader in the Mac app.
READ_PLATFORMS = {"xiaohongshu": "rednote", "instagram": "instagram", "facebook": "facebook",
                  "tiktok": "tiktok"}
# The platform's own post id inside a 发布记录 link.
POST_ID = {
    "rednote": NOTE_ID,
    "tiktok": re.compile(r"/video/(\d{15,})"),
    "instagram": re.compile(r"/(?:p|reel|reels)/([A-Za-z0-9_-]{6,})"),
    "facebook": re.compile(r"(?:/reel/|/videos/|/posts/|fbid=|story_fbid=|/v/)(\d{10,})"),
}
SOURCES = {"rednote": SOURCE_NOTES, "tiktok": "SPT 读数据 · TikTok Studio",
           "instagram": "SPT 读数据 · Meta Business Suite",
           "facebook": "SPT 读数据 · Meta Business Suite"}
# Where the Mac is: Meta Business Suite and TikTok Studio show times in the Mac's own zone.
LOCAL_ZONE = dt.datetime.now().astimezone().tzinfo
MONTHS = {name: index for index, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def stamp(moment: dt.datetime | None) -> str | None:
    return moment.astimezone(dt.timezone.utc).isoformat(timespec="seconds") if moment else None


def since(text: str | None) -> float | None:
    """Hours from an ISO time to now; None when there is none."""
    moment = parse_time(text) if text else None
    return (now() - moment).total_seconds() / 3600 if moment else None


# ---------------------------------------------------------------- reading the page text

def exact_number(text: object) -> int | None:
    """'1,234' → 1234. Rounded forms (1.2万, 1.7K) and anything else → None: empty is not 0."""
    value = str(text or "").strip()
    return int(value.replace(",", "")) if NUMBER.fullmatch(value) else None


def title_key(text: object) -> str:
    folded = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return re.sub(r"[\s\"'“”‘’「」『』《》…·.,，。!！?？:：;；、~～—\-]", "", folded)


def list_time(text: object, platform: str = "rednote",
              observed: dt.datetime | None = None) -> dt.datetime | None:
    """The publish time a list shows: 「2026-10-23 19:49」 (China time) on 笔记管理;
    「Fri Oct 23, 11:53pm」 (Meta) or 「Oct 23, 11:59 PM」 (TikTok) in the Mac's zone,
    the year being the one that puts the date on or before the read."""
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::\d{2})?", value)
    if match:
        try:
            moment = dt.datetime.fromisoformat(f"{match.group(1)}T{match.group(2)}")
        except ValueError:
            return None
        return moment.replace(tzinfo=LIST_ZONE if platform == "rednote" else LOCAL_ZONE)
    iso = parse_time(value)
    if iso is not None:
        return iso
    match = re.fullmatch(r"(?:[A-Za-z]{3},?\s+)?([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:,\s*(\d{4}))?"
                         r"(?:,?\s+(\d{1,2}):(\d{2})\s*([AaPp][Mm])?)?", value)
    if not match:
        return None
    month = MONTHS.get(match.group(1).lower())
    if month is None:
        return None
    seen = (observed or now()).astimezone(LOCAL_ZONE)
    hour, minute = int(match.group(4) or 0), int(match.group(5) or 0)
    meridiem = (match.group(6) or "").lower()
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    year = int(match.group(3)) if match.group(3) else seen.year
    try:
        moment = dt.datetime(year, month, int(match.group(2)), hour, minute, tzinfo=LOCAL_ZONE)
    except ValueError:
        return None
    if not match.group(3) and moment > seen + dt.timedelta(days=1):
        moment = moment.replace(year=year - 1)
    return moment


def read_platform(account: dict[str, Any]) -> str | None:
    return READ_PLATFORMS.get(str(account.get("platform") or "").strip().lower())


def account_label(account: dict[str, Any]) -> str:
    """The 表现.csv 账号 for an 账号档案 entry: on 小红书 its name without a「 · 小红书」
    tail; elsewhere its handle (the rows Codex wrote by hand use the handle too)."""
    code = read_platform(account) or "rednote"
    handle = str(account.get("handle") or "").strip().lstrip("@")
    if code != "rednote" and handle and not re.match(r"https?://", handle):
        return handle
    name = str(account.get("name") or account.get("brand") or "").strip()
    return re.sub(r"\s*[·・|｜-]\s*(小红书|rednote|xiaohongshu|instagram|facebook|tiktok)$",
                  "", name, flags=re.I).strip()


def same_account(label: str, account: dict[str, Any], header: list[str],
                 notes: list[dict[str, Any]] | None = None) -> bool:
    """The page names this account: its 档案 name, brand or handle in the header, or in
    the rows themselves (TikTok links carry /@handle/, Meta rows name the Page)."""
    names = {title_key(label), title_key(account.get("name")), title_key(account.get("brand")),
             title_key(str(account.get("handle") or "").lstrip("@"))}
    names.discard("")
    texts = list(header)
    for note in notes or []:
        if isinstance(note, dict):
            texts.extend(str(note.get(field) or "") for field in ("owner", "url"))
    return any(title_key(text) in names or any(name and name in title_key(text) for name in names)
               for text in texts if text)


# ---------------------------------------------------------------- matching to works

def rednote_works(store: Any) -> list[dict[str, Any]]:
    return platform_works(store, "rednote")


def platform_works(store: Any, code: str) -> list[dict[str, Any]]:
    """Works with a current publish record on that platform: id, title, the platform's
    post ids from the links, the publish time, and the 发布包 caption's start."""
    with store.connect() as connection:
        rows = [dict(row) for row in connection.execute(
            "SELECT w.id, w.title, r.platform, r.url, r.published_at FROM publish_records r "
            "JOIN works w ON w.id = r.work_id WHERE r.state = 'current'")]
        captions = {(row["work_id"], platform_code(row["platform"]) or row["platform"]): row["caption"]
                    for row in connection.execute("SELECT work_id, platform, caption FROM package_sections")}
    pattern = POST_ID.get(code, NOTE_ID)
    works: dict[str, dict[str, Any]] = {}
    for row in rows:
        if platform_code(row["platform"]) != code:
            continue
        work = works.setdefault(row["id"], {"id": row["id"], "title": row["title"],
                                            "note_ids": set(), "published": None,
                                            "caption": caption_key(captions.get((row["id"], code)))})
        for found in pattern.findall(str(row["url"] or "")):
            work["note_ids"].add(found.lower() if code == "rednote" else found)
            if code == "instagram":
                work["note_ids"].add(shortcode_id(found))
        moment = parse_time(row["published_at"])
        if moment and (work["published"] is None or moment < work["published"]):
            work["published"] = moment
    return list(works.values())


SHORTCODE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def shortcode_id(shortcode: str) -> str:
    """The media id an Instagram link's shortcode encodes (what Business Suite calls content_id)."""
    value = 0
    for char in shortcode:
        value = value * 64 + SHORTCODE.index(char)
    return str(value)


def caption_key(text: object) -> str:
    """The first CAPTION_CHARS of a caption, folded like a title; '' when too short to name a post."""
    key = title_key(re.split(r"\n\s*\n", str(text or "").strip(), 1)[0])
    return key[:CAPTION_CHARS] if len(key) >= 12 else ""


def match(note: dict[str, Any], works: list[dict[str, Any]],
          code: str = "rednote", observed: dt.datetime | None = None) -> dict[str, Any] | None:
    """The work this list row is: by the platform's post id in the 发布记录 link, else
    by exact title, else by the caption's start, each checked against the publish time."""
    ids = [str(item) for item in (note.get("note_id"), note.get("detail_id")) if item]
    if code == "rednote":
        ids = [item.lower() for item in ids]
    for note_id in ids:
        found = [work for work in works if note_id in work["note_ids"]]
        if len(found) == 1:
            return found[0]
    key = title_key(note.get("title"))
    if not key:
        return None
    named = [work for work in works if title_key(work["title"]) == key]
    if not named:
        named = [work for work in works if work["caption"] and key.startswith(work["caption"])]
    shown = list_time(note.get("time"), code, observed)
    if not named and shown is not None:
        # Meta lists captions, not our titles, and its row ids are not the link ids:
        # the one work this client published on that platform at that moment is it.
        near = [work for work in works if work["published"] is not None
                and abs((work["published"] - shown).total_seconds()) <= NEAR_MINUTES * 60]
        if len(near) == 1:
            return near[0]
        return None

    def apart(work: dict[str, Any]) -> float | None:
        if shown is None or work["published"] is None:
            return None
        return abs((work["published"] - shown).total_seconds()) / 3600

    if len(named) > 1 and shown is not None:
        named = [work for work in named if (apart(work) or 99) <= 0.5]
    if len(named) != 1:
        return None
    gap = apart(named[0])
    return named[0] if gap is None or gap <= TITLE_HOURS else None


def latest_reading(store: Any, work_id: str, account: str,
                   code: str = "rednote") -> dict[str, Any] | None:
    with store.connect() as connection:
        row = connection.execute(
            "SELECT at, views, reach, comments, likes, saves, shares FROM metric_observations "
            "WHERE work_id = ? AND platform = ? AND account = ? "
            "ORDER BY at DESC, position DESC LIMIT 1", (work_id, code, account)).fetchone()
    return dict(row) if row else None


def latest_followers(store: Any, account: str, code: str = "rednote") -> dict[str, Any] | None:
    with store.connect() as connection:
        row = connection.execute(
            "SELECT at, followers FROM account_observations WHERE platform = ? "
            "AND account = ? AND followers IS NOT NULL ORDER BY at DESC, position DESC LIMIT 1",
            (code, account)).fetchone()
    return dict(row) if row else None


def note_values(note: dict[str, Any]) -> dict[str, int | None]:
    """The numbers a list row showed, by field. 笔记管理 gives five texts in icon order;
    the other readers name them (views, reach, likes, comments, shares, saves)."""
    metrics = note.get("metrics")
    if isinstance(metrics, dict):
        return {field: exact_number(metrics.get(field))
                for field in ("views", "reach", "likes", "comments", "saves", "shares")
                if field in metrics}
    raw = list(note.get("numbers") or [])[:len(LIST_ORDER)]
    return {field: exact_number(raw[index]) if index < len(raw) else None
            for index, field in enumerate(LIST_ORDER)}


def worth_writing(previous: dict[str, Any] | None, values: dict[str, int | None]) -> str | None:
    """Why a reading is skipped ('刚记过' / '没变'), None when it should be written."""
    if previous is None:
        return None
    hours = since(previous["at"])
    if hours is not None and hours * 60 < SAME_READ_MINUTES:
        return "刚记过"
    same = all(values[field] is None or previous.get(field) == values[field]
               for field in values)
    return "没变" if same and hours is not None and hours < UNCHANGED_HOURS else None


# ---------------------------------------------------------------- recording one account

def record_account_read(indexer: Any, value: dict[str, Any]) -> dict[str, Any]:
    """What the app read for one account → rows in the works' 表现.csv and the account's.

    `value`: {account: {name, brand, …}, status: done|login|attention, reason,
    observed_at, header: [texts in the page header], notes: [{note_id, title, time,
    numbers: [5 texts], state}], profile: {followers}}.
    """
    account = value.get("account") if isinstance(value.get("account"), dict) else {}
    code = read_platform(account) or "rednote"
    label = account_label(account)
    summary: dict[str, Any] = {"account": label or "小红书", "platform": code, "recorded": 0,
                               "unchanged": 0, "unmatched": [], "followers": None, "ok": False}
    status = value.get("status")
    if status == "login":
        summary["message"] = f"{summary['account']} 需要重新登录：在 发布 → 平台入口 打开这个平台登录一次"
        return summary
    if status != "done":
        summary["message"] = f"{summary['account']}：{str(value.get('reason') or '页面没有读出来')[:1000]}"
        return summary
    if not label:
        summary["message"] = "账号档案没有名字，不知道记到哪个账号"
        return summary
    header = [str(text)[:80] for text in value.get("header") or [] if str(text).strip()][:80]
    notes = [note for note in value.get("notes") or [] if isinstance(note, dict)]
    summary["header"] = header[:12]
    summary["page"] = str(value.get("page") or "")[:160]
    summary["sample"] = [{"title": str(note.get("title") or "")[:60], "time": note.get("time"),
                          "ids": [note.get("note_id"), note.get("detail_id")],
                          "metrics": note.get("metrics") or note.get("numbers"),
                          **({"debug": note["debug"]} if note.get("debug") else {})} for note in notes[:3]]
    if not same_account(label, account, header, notes):
        summary["message"] = f"登录的好像不是 {label}，这次没有记"
        return summary
    observed = parse_time(value.get("observed_at")) or now()
    at = stamp(observed)
    works = platform_works(indexer.store, code)
    for note in value.get("notes") or []:
        if not isinstance(note, dict) or NOT_LIVE.search(str(note.get("state") or "")):
            continue
        values = note_values(note)
        if all(item is None for item in values.values()):
            continue
        work = match(note, works, code, observed)
        if work is None:
            shown = str(note.get("title") or note.get("note_id") or "")[:40]
            summary["unmatched"].append(f"{shown}（{note['time']}）" if note.get("time") else shown)
            continue
        if worth_writing(latest_reading(indexer.store, work["id"], label, code), values):
            summary["unchanged"] += 1
            continue
        metrics_write.record_observation(indexer, {
            "work": work["id"], "platform": code, "account": label, "at": at,
            **{field: item for field, item in values.items() if item is not None},
            "source": SOURCES.get(code, SOURCE_NOTES)})
        summary["recorded"] += 1
    profile = value.get("profile") if isinstance(value.get("profile"), dict) else {}
    followers = exact_number(profile.get("followers"))
    if followers is not None:
        summary["followers"] = followers
        previous = latest_followers(indexer.store, label, code)
        if not worth_writing(previous and {"at": previous["at"], "followers": previous["followers"]},
                             {"followers": followers}):
            metrics_write.record_account(indexer, {"platform": code, "account": label,
                                                   "at": at, "followers": followers,
                                                   "source": SOURCE_PROFILE})
    summary["ok"] = True
    parts = [f"{label}：新记 {summary['recorded']} 篇"]
    if summary["unchanged"]:
        parts.append(f"{summary['unchanged']} 篇没变")
    if followers is not None:
        parts.append(f"粉丝 {followers}")
    if summary["unmatched"]:
        parts.append(f"{len(summary['unmatched'])} 篇没对上作品")
    summary["message"] = "，".join(parts)
    return summary


# ---------------------------------------------------------------- requests and the schedule

def node_passed(store: Any, after: str | None, moment: dt.datetime | None = None) -> str | None:
    """Which current post reached a D1 / D3 / D7 node between `after` and now, e.g. '北京鸭 D1';
    None when none did. Only posts on platforms the app can read count."""
    start = parse_time(after) if after else None
    moment = moment or now()
    readable = set(READ_PLATFORMS) | set(READ_PLATFORMS.values())
    with store.connect() as connection:
        rows = connection.execute(
            "SELECT w.title, r.platform, r.published_at FROM publish_records r "
            "JOIN works w ON w.id = r.work_id WHERE r.state = 'current' "
            "AND r.published_at IS NOT NULL AND r.published_at != ''").fetchall()
    for row in rows:
        row = dict(row)
        if (platform_code(row["platform"]) or row["platform"]) not in readable:
            continue
        published = parse_time(row["published_at"])
        if published is None:
            continue
        for hours in NODE_HOURS:
            node = published + dt.timedelta(hours=hours)
            if node <= moment and (start is None or node > start):
                return f"{str(row['title'])[:20]} D{hours // 24}"
    return None


class CaptureQueue:
    """One read at a time. Finished runs are kept in a small JSON next to the index."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.current: dict[str, Any] | None = None
        self.runs: list[dict[str, Any]] = self.load()

    def load(self) -> list[dict[str, Any]]:
        try:
            runs = json.loads(self.path.read_text(encoding="utf-8")).get("runs", [])
        except (OSError, ValueError, AttributeError):
            return []
        return [run for run in runs if isinstance(run, dict)][-HISTORY:]

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            scratch = self.path.with_suffix(".tmp")
            scratch.write_text(json.dumps({"runs": self.runs[-HISTORY:]}, ensure_ascii=False,
                                          indent=1), encoding="utf-8")
            scratch.replace(self.path)
        except OSError:
            pass   # the status file is a convenience; the 表现.csv rows are the record

    def close(self, state: str, message: str) -> None:
        run = self.current
        if run is None:
            return
        run.update(state=state, message=message, finished_at=stamp(now()))
        self.runs.append(run)
        self.current = None
        self.save()

    def expire(self) -> None:
        run = self.current
        if run is None:
            return
        if run["state"] == "pending" and (since(run["requested_at"]) or 0) * 3600 > CLAIM_SECONDS:
            self.close("failed", "没有读到：只有 Mac 上打开的 SPT 应用能读平台数据")
        elif run["state"] == "reading" and (since(run["claimed_at"]) or 0) * 60 > READ_MINUTES:
            self.close("failed", "读取超时，下次会再试")

    def new(self, reason: str) -> dict[str, Any]:
        self.current = {"id": uuid.uuid4().hex[:12], "reason": reason, "state": "pending",
                        "requested_at": stamp(now()), "claimed_at": None, "finished_at": None,
                        "accounts": [], "message": "等 SPT 应用来读"}
        return self.current

    def why_due(self, store: Any = None) -> str | None:
        """Why the app should read now without being asked: '定时' when the last good read is
        AUTO_HOURS old, '到节点 <作品> D1' when a post passed a node since it; None otherwise."""
        good = next((run for run in reversed(self.runs) if run.get("state") == "done"), None)
        last = self.runs[-1] if self.runs else None
        good_age = since(good and good.get("finished_at"))
        last_age = since(last and last.get("finished_at"))
        if last_age is not None and last_age < RETRY_HOURS:
            return None
        if good_age is None or good_age >= AUTO_HOURS:
            return "定时"
        node = node_passed(store, good.get("finished_at")) if store is not None else None
        return f"到节点 {node}" if node else None

    def due(self, store: Any = None) -> bool:
        return self.why_due(store) is not None

    def request(self, reason: str = "手动") -> dict[str, Any]:
        with self.lock:
            self.expire()
            return dict(self.current or self.new(reason))

    def claim(self, auto: bool = False, store: Any = None) -> dict[str, Any] | None:
        with self.lock:
            self.expire()
            if self.current is None and auto and (reason := self.why_due(store)):
                self.new(reason)
            run = self.current
            if run is None or run["state"] != "pending":
                return None
            run.update(state="reading", claimed_at=stamp(now()), message="正在读")
            return {"id": run["id"], "reason": run["reason"]}

    def report(self, indexer: Any, value: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            run = self.current
            if run is None or run["id"] != value.get("id") or run["state"] != "reading":
                raise ValueError("这次读取已经结束了")
        summary = record_account_read(indexer, value)   # writes outside the lock
        with self.lock:
            if self.current is run:
                run["accounts"].append(summary)
        return summary

    def finish(self, value: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            run = self.current
            if run is None or run["id"] != value.get("id"):
                raise ValueError("这次读取已经结束了")
            accounts = run["accounts"]
            if not accounts:
                self.close("failed", str(value.get("reason") or "还没有在 SPT 里登录过账号")[:160])
            else:
                ok = any(item.get("ok") for item in accounts)
                self.close("done" if ok else "failed",
                           "；".join(item.get("message", "") for item in accounts))
            return dict(self.runs[-1])

    def status(self) -> dict[str, Any]:
        with self.lock:
            self.expire()
            good = next((run for run in reversed(self.runs) if run.get("state") == "done"), None)
            return {"current": dict(self.current) if self.current else None,
                    "last": dict(self.runs[-1]) if self.runs else None,
                    "last_good_at": good and good.get("finished_at"),
                    "auto_hours": AUTO_HOURS}


_QUEUES: dict[str, CaptureQueue] = {}
_QUEUES_LOCK = threading.Lock()


def queue_for(indexer: Any) -> CaptureQueue:
    path = Path(indexer.config.cache) / "metrics-capture.json"
    with _QUEUES_LOCK:
        return _QUEUES.setdefault(str(path), CaptureQueue(path))
