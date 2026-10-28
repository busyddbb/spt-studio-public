"""Who each work is for: 工作区/客户.md, one Markdown table people and agents edit by hand.

The file is optional. Its 简称 column is the client code that work folder names
carry (日期-客户-主题), so it joins to works.client. Its 类型 column is the group a
client is shown under (自己 and 客户 are the default two; any name goes). Reading
it never raises: a row that cannot be read becomes one index issue and the rest
is kept. It is read again only when its size or modification time changed, so
/api/health stays cheap. 「整理客户」 in the UI rewrites the table through
save_clients; whatever text stands before or after the table is kept.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any

from .files import FileError, read_text, write_atomic

CLIENT_FILE = "客户.md"
OWN = "自家"          # 用户's own work: always kind "own", first among codes not in the file
OWN_GROUP, CLIENT_GROUP = "自己", "客户"
COLUMNS = {"code": ("简称", "代号", "code"), "name": ("名字", "名称", "name"),
           "kind": ("类型", "kind", "type"), "color": ("颜色", "color")}
COLOR = re.compile(r"#[0-9a-fA-F]{6}")
RULE = re.compile(r":?-+:?")
ISSUE_LIMIT = 8       # rows reported per read; the rest of a broken file is skipped quietly
GROUP_LIMIT, ROW_LIMIT = 12, 200
HEADER = "| 简称 | 名字 | 类型 | 颜色 |\n|---|---|---|---|\n"
# written above the table when the file does not exist yet
PREAMBLE = ("# 客户\n\n"
            "作品文件夹名里的「客户」一栏用简称；这张表写清每个简称是谁、放在哪一组。"
            "「类型」一栏是分组名，自己、客户是默认的两组，也可以自己起名。"
            "没写在表里的简称归「客户」组（「自家」永远归「自己」）。颜色可不填。\n\n")


def cells(line: str) -> list[str]:
    return [part.strip() for part in line.strip().strip("|").split("|")]


def header_columns(cells_: list[str]) -> dict[str, int] | None:
    """Field -> column index, matched by header text; None without a 简称 column."""
    names = [name.strip().casefold() for name in cells_]
    found = {field: next((index for index, name in enumerate(names)
                          if name in [alias.casefold() for alias in aliases]), None)
             for field, aliases in COLUMNS.items()}
    return {field: index for field, index in found.items() if index is not None} \
        if found["code"] is not None else None


def find_table(lines: list[str]) -> tuple[int, dict[str, int]] | None:
    """(index of the first data line, columns) of the first table with a 简称 column."""
    for index in range(len(lines) - 1):
        header, rule = lines[index].strip(), lines[index + 1].strip()
        if "|" not in header or not rule.startswith("|") or \
                not re.fullmatch(r"\|[\s:|-]+\|?", rule):
            continue
        columns = header_columns(cells(header))
        if columns:
            return index + 2, columns
    return None


def table_end(lines: list[str], start: int) -> int:
    """Index of the first line after the table's rows (rows stop at a line without |)."""
    end = start
    while end < len(lines) and "|" in lines[end]:
        end += 1
    return end


def kind_of(code: str, group: str) -> str:
    return "own" if code == OWN or group == OWN_GROUP else "client"


def parse_clients(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Rows in file order ({code, name, kind, color, group}) and what could not be read."""
    lines = text.lstrip("﻿").splitlines()   # a BOM is not part of the first header cell
    issues: list[str] = []
    table = find_table(lines)
    if table is None:
        if text.strip():
            issues.append(f"{CLIENT_FILE} 里没有带「简称」列的表格")
        return [], issues
    start, columns = table
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def value(parts: list[str], field: str) -> str:
        index = columns.get(field)
        return parts[index] if index is not None and index < len(parts) else ""

    for number, line in enumerate(lines[start:], start + 1):
        if "|" not in line:
            break
        parts = cells(line)
        if all(not part or RULE.fullmatch(part) for part in parts):
            continue
        code = value(parts, "code")
        problem = ""
        if not code:
            problem = f"{CLIENT_FILE} 第 {number} 行看不懂"
        elif code in seen:
            problem = f"{CLIENT_FILE} 第 {number} 行：简称「{code}」重复，已忽略"
        if problem:
            if len(issues) < ISSUE_LIMIT:
                issues.append(problem)
            continue
        color = value(parts, "color")
        if color and not COLOR.fullmatch(color):
            if len(issues) < ISSUE_LIMIT:
                issues.append(f"{CLIENT_FILE} 第 {number} 行：颜色「{color}」不是 #rrggbb，已忽略")
            color = ""
        group = value(parts, "kind") or (OWN_GROUP if code == OWN else CLIENT_GROUP)
        seen.add(code)
        rows.append({"code": code, "name": value(parts, "name") or code,
                     "kind": kind_of(code, group), "color": color.lower() or None,
                     "group": group})
    return rows, issues


def client_groups(rows: list[dict[str, Any]]) -> list[str]:
    """Group names in order of first appearance; the two defaults when the file has none."""
    groups = list(dict.fromkeys(row["group"] for row in rows))
    return groups or [OWN_GROUP, CLIENT_GROUP]


def client_summary(rows: list[dict[str, Any]],
                   counts: dict[str, int]) -> list[dict[str, Any]]:
    """What /api/health shows: the file's rows in order, then codes only works know.

    counts: works per client code. Listed codes keep works: 0; unlisted codes sort
    by code with 自家 first. An unlisted code joins group 客户 when the file has
    one, else the file's last group; unlisted 自家 joins 自己, else the first group.
    """
    listed = [{**row, "works": counts.get(row["code"], 0)} for row in rows]
    known = {row["code"] for row in rows}
    groups = client_groups(rows)
    own_group = OWN_GROUP if OWN_GROUP in groups else groups[0]
    client_group = CLIENT_GROUP if CLIENT_GROUP in groups else groups[-1]
    extra = sorted((code for code in counts if code and code not in known),
                   key=lambda code: (code != OWN, code))
    return listed + [{"code": code, "name": code,
                      "kind": "own" if code == OWN else "client",
                      "color": None, "works": counts[code],
                      "group": own_group if code == OWN else client_group} for code in extra]


# -- 整理客户: writing the table back -------------------------------------------
def clean_text(value: object, what: str, forbidden: str = "|") -> str:
    """A table cell: stripped text without | or line breaks (and `forbidden`)."""
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{what}不能为空")
    if any(mark in text for mark in forbidden) or "\n" in text or "\r" in text:
        shown = " ".join(forbidden)
        raise ValueError(f"{what}「{text}」不能有 {shown} 或换行")
    return text


def check_groups(groups: Any) -> list[dict[str, Any]]:
    """The input of save_clients, checked: [{name, clients: [{code, name, color}]}]."""
    if not isinstance(groups, list) or not groups:
        raise ValueError("至少要有一个分组")
    if len(groups) > GROUP_LIMIT:
        raise ValueError(f"最多 {GROUP_LIMIT} 个分组")
    names: set[str] = set()
    codes: set[str] = set()
    result = []
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("分组格式不正确")
        name = clean_text(group.get("name"), "分组名")
        if name in names:
            raise ValueError(f"分组「{name}」重复了")
        names.add(name)
        clients = group.get("clients") or []
        if not isinstance(clients, list):
            raise ValueError(f"分组「{name}」的客户格式不正确")
        rows = []
        for client in clients:
            if not isinstance(client, dict):
                raise ValueError("客户格式不正确")
            code = clean_text(client.get("code"), "简称", "|/-")
            if code in codes:
                raise ValueError(f"简称「{code}」重复了")
            codes.add(code)
            shown = str(client.get("name") or "").strip() or code
            shown = clean_text(shown, "名字")
            color = str(client.get("color") or "").strip()
            if color and not COLOR.fullmatch(color):
                raise ValueError(f"「{code}」的颜色要写成 #rrggbb")
            rows.append({"code": code, "name": shown, "color": color.lower()})
        result.append({"name": name, "clients": rows})
    if len(codes) > ROW_LIMIT:
        raise ValueError(f"最多 {ROW_LIMIT} 个客户")
    return result


def render_table(groups: list[dict[str, Any]]) -> str:
    rows = [f"| {client['code']} | {client['name']} | {group['name']} | {client['color']} |\n"
            for group in groups for client in group["clients"]]
    return HEADER + "".join(rows)


def rewrite(text: str, table: str) -> str:
    """The file with its table replaced; text before and after the table is kept."""
    lines = text.lstrip("﻿").splitlines(keepends=True)
    found = find_table([line.rstrip("\r\n") for line in lines])
    if found is None:
        before = text.lstrip("﻿")
        if not before:
            before = PREAMBLE
        elif not before.endswith("\n\n"):
            before = before.rstrip("\n") + "\n\n"
        return before + table
    start = found[0]
    end = table_end([line.rstrip("\r\n") for line in lines], start)
    after = "".join(lines[end:])
    return "".join(lines[:start - 2]) + table + after


def save_clients(workspace: Path, groups: Any, counts: dict[str, int]) -> list[str]:
    """Write 工作区/客户.md from [{name, clients: [{code, name, color}]}] in display order.

    counts (works per client code) guards the codes works still use: one of them
    missing is refused, nothing is written. Returns the group names written.
    Groups without clients leave no row, so they are gone on the next read.
    """
    checked = check_groups(groups)
    present = {client["code"] for group in checked for client in group["clients"]}
    for code in sorted(counts, key=lambda code: (code != OWN, code)):
        if code and counts[code] and code not in present:
            raise ValueError(f"「{code}」还有 {counts[code]} 件作品，不能删")
    if not workspace.is_dir():
        raise FileError("工作区不存在，先到设置里选好工作区位置")
    path = workspace / CLIENT_FILE
    if path.is_symlink():
        raise FileError(f"{CLIENT_FILE} 不能是替身")
    current = read_text(path) if path.is_file() else ""
    write_atomic(path, rewrite(current, render_table(checked)))
    return [group["name"] for group in checked]


class Clients:
    """客户.md read on demand, parsed again only when the file changed."""

    def __init__(self) -> None:
        self.cached: tuple[tuple[Any, ...], tuple[list[dict[str, Any]], list[str]]] | None = None

    def read(self, workspace: Path) -> tuple[list[dict[str, Any]], list[str]]:
        path = workspace / CLIENT_FILE
        try:
            if path.is_symlink() or not path.is_file():
                key: tuple[Any, ...] = (str(path), None)
            else:
                status = path.stat()
                key = (str(path), status.st_size, status.st_mtime_ns)
        except OSError:
            key = (str(path), None)
        cached = self.cached
        if cached is None or cached[0] != key:
            value = self.load(path) if key[1] is not None else ([], [])
            self.cached = cached = (key, value)
        rows, issues = cached[1]
        return [dict(row) for row in rows], list(issues)

    def save(self, workspace: Path, groups: Any, counts: dict[str, int]) -> list[str]:
        """save_clients, then forget what was cached so the next read is the new file."""
        try:
            return save_clients(workspace, groups, counts)
        finally:
            self.cached = None

    @staticmethod
    def load(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
        try:
            return parse_clients(read_text(path))
        except (FileError, OSError, UnicodeError) as error:
            return [], [f"{CLIENT_FILE}：{error}"]
