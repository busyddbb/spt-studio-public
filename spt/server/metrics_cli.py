"""`spt metrics`: 数据记录 on the command line (spt/docs/数据记录格式.md 「查」「记」).

    spt metrics [--client …] [--platform …] [--tag …]   one line per post
    spt metrics tags / show <work> / add / retention / analyse / account
    spt metrics capture   让 Mac 上的 SPT 应用用本机登录读一次小红书（metrics_capture.py）
    --json everywhere; tables otherwise.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .metrics import NODES, client_code
from .metrics_write import (MetricsError, WorkLookup, record_account, record_analysis,
                            record_observation, record_retention)

FILTERS = ("client", "platform", "account", "since", "until", "tag", "q")
NUMBERS = ("views", "reach", "likes", "comments", "saves", "shares", "profile_visits",
           "follows", "ctr", "three_sec_rate", "completion_rate", "avg_watch_sec")
ACCOUNT_NUMBERS = ("followers", "views", "reach", "interactions", "likes", "comments",
                   "saves", "shares", "profile_visits", "follows")


def add_filters(parser: argparse.ArgumentParser, default: Any = "") -> None:
    """The 「查」 filters. Subcommands pass SUPPRESS so their defaults do not wipe
    what was given before the subcommand name (`spt metrics --client 示例客户 tags`)."""
    parser.add_argument("--client", default=default, help="客户简称或名字，例如 AK、示例创作者")
    parser.add_argument("--platform", default=default, help="rednote、douyin、instagram…或 小红书、抖音")
    parser.add_argument("--account", default=default, help="账号名")
    parser.add_argument("--since", default=default, help="发布时间从这天起（没有发布时间的作品按最近一次记录）")
    parser.add_argument("--until", default=default, help="发布时间到这天为止")
    parser.add_argument("--tag", default=default, help="只看分析里带这个标签的")
    parser.add_argument("--q", default=default, help="关键字：标题、客户、结论、标签")


def add_parser(commands: argparse._SubParsersAction) -> None:
    root = commands.add_parser("metrics", help="数据记录：查看或追加作品和账号的数据（只追加文件）")
    root.add_argument("--json", action="store_true", help="输出 JSON")
    add_filters(root)
    sub = root.add_subparsers(dest="metrics_command")

    def command(name: str, help_text: str) -> argparse.ArgumentParser:
        parser = sub.add_parser(name, help=help_text)
        parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                            help="输出 JSON")
        return parser

    tags = command("tags", "哪些毛病（分析标签）最常见")
    add_filters(tags, argparse.SUPPRESS)
    show = command("show", "一件作品的时间线、D1/D3/D7、留存、分析")
    show.add_argument("work", help="作品 id、文件夹名或唯一关键字")
    add = command("add", "记一行表现：追加到作品的 数据/表现.csv")
    add.add_argument("--work", required=True, help="作品 id、文件夹名或唯一关键字")
    add.add_argument("--platform", required=True)
    add.add_argument("--account", default="")
    add.add_argument("--at", default="", help="记录时间，默认现在；带时区，如 2026-10-22T09:30:00+08:00")
    for name in NUMBERS:
        add.add_argument("--" + name.replace("_", "-"), dest=name, default=None)
    add.add_argument("--source", default="", help="数字从哪来")
    add.add_argument("--note", default="", help="一句话备注")
    keep = command("retention", "记一条留存曲线：追加到 数据/留存.csv")
    keep.add_argument("--work", required=True)
    keep.add_argument("--platform", required=True)
    keep.add_argument("--account", default="")
    keep.add_argument("--at", default="")
    keep.add_argument("--points", required=True, help='"0:100,3:71.5,10:40"')
    analyse = command("analyse", "写一份分析：数据/分析/<日期>-<节点>.md，不覆盖")
    analyse.add_argument("--work", required=True)
    analyse.add_argument("--platform", default="")
    analyse.add_argument("--account", default="")
    analyse.add_argument("--node", default="", help="D1、D3、D7、周、复盘……")
    analyse.add_argument("--topic", default="", help="没有节点时用作文件名")
    analyse.add_argument("--conclusion", required=True, help="一句话结论")
    analyse.add_argument("--tags", default="", help="毛病的名字，逗号分隔")
    analyse.add_argument("--date", default="", help="默认今天")
    analyse.add_argument("--body", default="", help="正文")
    analyse.add_argument("--file", type=Path, help="正文文件（.md）")
    read = command("capture", "让 Mac 上的 SPT 应用用本机登录读一次小红书数据，写进作品的 表现.csv")
    read.add_argument("--status", action="store_true", help="只看上一次读的结果，不读")
    read.add_argument("--wait", type=int, default=300, help="最多等几秒，默认 300")
    read.add_argument("--port", type=int, default=8766, help="SPT 应用的本机端口")
    account = command("account", "记一行账号数据：工作区/数据/账号/<平台>-<账号>/表现.csv")
    account.add_argument("--platform", required=True)
    account.add_argument("--account", required=True)
    account.add_argument("--at", default="")
    for name in ACCOUNT_NUMBERS:
        account.add_argument("--" + name.replace("_", "-"), dest=name, default=None)
    account.add_argument("--source", default="")
    account.add_argument("--note", default="")


# ---------------------------------------------------------------- tables

def width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def pad(text: str, size: int) -> str:
    return text + " " * (size - width(text))


def table(headers: list[str], rows: list[list[Any]]) -> str:
    cells = [[("" if value is None else str(value)) for value in row] for row in rows]
    sizes = [max([width(header)] + [width(row[index]) for row in cells])
             for index, header in enumerate(headers)]
    lines = ["  ".join(pad(header, sizes[index]) for index, header in enumerate(headers))]
    lines.append("  ".join("-" * size for size in sizes))
    lines += ["  ".join(pad(value, sizes[index]) for index, value in enumerate(row))
              for row in cells]
    return "\n".join(line.rstrip() for line in lines)


def local(moment: str | None) -> str:
    import datetime as dt
    if not moment:
        return ""
    try:
        return dt.datetime.fromisoformat(moment).astimezone().strftime("%m-%d %H:%M")
    except ValueError:
        return moment


def node_cell(node: dict[str, Any] | None) -> str:
    if not node:
        return ""
    views = node["metrics"].get("views")
    late = node["late_hours"]
    text = "" if views is None else str(views)
    if late is not None and abs(late) >= 1:
        text += f" ({late:+.0f}h)"
    return text.strip()


def percent(value: Any) -> str:
    return "" if value is None else f"{value}%"


def post_rows(posts: list[dict[str, Any]]) -> str:
    headers = ["作品", "客户", "平台", "账号", "发布", "最新浏览", "D1", "D3", "D7", "完播率", "标签"]
    rows = [[post["title"], post["client"], post["platform"], post["account"],
             local(post["published_at"])[:5], post["metrics"].get("views"),
             node_cell(post["nodes"]["D1"]), node_cell(post["nodes"]["D3"]),
             node_cell(post["nodes"]["D7"]), percent(post["metrics"].get("completion_rate")),
             "、".join(post["tags"])] for post in posts]
    return table(headers, rows) if rows else "还没有数据记录"


def tag_rows(tags: list[dict[str, Any]]) -> str:
    rows = [[item["tag"], item["count"], len(item["post_ids"])] for item in tags]
    return table(["标签", "次数", "作品数"], rows) if rows else "还没有分析标签"


def show_text(work: dict[str, Any], metrics: dict[str, Any]) -> str:
    parts = [f"{work['title']}  {work['relative_path']}"]
    rows = [[local(item["at"]), item["age_hours"], item["platform"], item["account"],
             *(item["metrics"].get(field) for field in NUMBERS[:6]),
             percent(item["metrics"].get("completion_rate")), item["note"]]
            for item in metrics["observations"]]
    parts.append(table(["记录时间", "距发布h", "平台", "账号", "浏览", "触达", "点赞", "评论",
                        "收藏", "分享", "完播率", "备注"], rows) if rows else "还没有表现记录")
    nodes = [[label, local(node["at"]) if node else "", node["late_hours"] if node else "",
              node["metrics"].get("views") if node else ""]
             for label, node in metrics["nodes"].items()]
    parts.append(table(["节点", "记录时间", "晚到h", "浏览"], nodes))
    if metrics["retention"]:
        curve = metrics["retention"][0]
        parts.append("留存 " + local(curve["at"]) + "  " +
                     "  ".join(f"{second}s:{rate}%" for second, rate in curve["points"]))
    for item in metrics["analyses"]:
        parts.append(f"{item['date']} {item['node'] or ''} {item['conclusion']}"
                     + (f"  [{'、'.join(item['tags'])}]" if item["tags"] else "")
                     + f"  {item['path']}")
    return "\n".join(parts)


# ---------------------------------------------------------------- run

def output(value: object) -> None:
    json.dump(value, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def filters_of(options: argparse.Namespace, indexer: Any) -> dict[str, str]:
    values = {key: getattr(options, key, "") or "" for key in FILTERS}
    values["client"] = client_code(values["client"], indexer.clients.read(indexer.workspace)[0])
    return values


def write_value(options: argparse.Namespace, names: tuple[str, ...]) -> dict[str, Any]:
    value = {name: getattr(options, name) for name in names if getattr(options, name, None)}
    for name in ("work", "platform", "account", "at", "source", "note", "node", "topic",
                 "conclusion", "tags", "date", "points"):
        if getattr(options, name, None):
            value[name] = getattr(options, name)
    if getattr(options, "file", None):
        value["body"] = Path(options.file).read_text(encoding="utf-8")
    elif getattr(options, "body", None):
        value["body"] = options.body
    return value


def capture(options: argparse.Namespace) -> int:
    """`spt metrics capture`: ask the running SPT app for a read and wait for it.

    Exit 0 when it read, 1 when it could not (not logged in, app not open…),
    3 when it is still reading after --wait seconds."""
    base = f"http://127.0.0.1:{options.port}/api/spt/metrics/capture"
    as_json = getattr(options, "json", False)

    def call(path: str = "", body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"}
                                         if data else {}, method="POST" if data else "GET")
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        if options.status:
            status = call()
            output(status) if as_json else print((status.get("last") or {}).get("message") or "还没有读过")
            return 0
        run_id = call("/request", {"reason": "命令"})["run"]["id"]
        end = time.monotonic() + max(10, options.wait)
        status = call()
        while (status.get("current") or {}).get("id") == run_id and time.monotonic() < end:
            time.sleep(3)
            status = call()
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        print("连不上 SPT：先打开 Mac 上的 SPT 应用。", file=sys.stderr)
        return 1
    last = status.get("last") or {}
    if last.get("id") != run_id:
        print("还在读，稍后用 spt metrics capture --status 看结果。", file=sys.stderr)
        return 3
    output(last) if as_json else print(last.get("message") or "读完了")
    return 0 if last.get("state") == "done" else 1


def run(options: argparse.Namespace, indexer: Any) -> int:
    """Carry out `spt metrics …`; the exit code is the process's."""
    command = options.metrics_command
    as_json = getattr(options, "json", False)
    writers: dict[str, tuple[Callable[..., dict[str, Any]], tuple[str, ...]]] = {
        "add": (record_observation, NUMBERS), "retention": (record_retention, ()),
        "analyse": (record_analysis, ()), "account": (record_account, ACCOUNT_NUMBERS)}
    if command == "capture":
        return capture(options)
    try:
        if command in writers:
            writer, names = writers[command]
            result = writer(indexer, write_value(options, names))
            output(result) if as_json else print(f"已写入 {result['path']}")
            return 0
        if command == "show":
            found = indexer.store.lookup_work(options.work)
            if len(found) != 1:
                names = "、".join(Path(row["relative_path"]).name for row in found[:8])
                print(f"找不到唯一的作品：{names or options.work}", file=sys.stderr)
                return 1
            metrics = indexer.store.work_metrics(found[0]["id"])
            output({"work": found[0], **metrics}) if as_json else print(show_text(found[0], metrics))
            return 0
        filters = filters_of(options, indexer)
        if command == "tags":
            tags = indexer.store.metrics_tags(**filters)
            output(tags) if as_json else print(tag_rows(tags))
            return 0
        posts = indexer.store.metrics_posts(**filters)
        output(posts) if as_json else print(post_rows(posts))
        return 0
    except WorkLookup as error:
        print(str(error), file=sys.stderr)
        return 1
    except (MetricsError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
