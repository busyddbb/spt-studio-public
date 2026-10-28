"""便签: short notes in groups, one Markdown file per note.

工作区/便签/<分组>/<编号>.md is the note; the folder is the group (called a
"rope" in the code). The order of groups and of the notes in each group lives in
便签/.布局.json, so moving a note never rewrites its file. A note may carry a
日期 for the calendar view; without one it shows on the day it was written.
Taking a note down moves it to 便签/.已撤下/<分组>/ — nothing is deleted — and
放回 moves it back to the place it hung. Deleting (a note, or the whole shelf)
moves files to the system Trash, never past it.

Claude and Codex may edit note files directly. A save that carries the
updated_at the person saw is refused when the file has changed since.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import re
import secrets
import stat
import threading
from pathlib import Path
from typing import Any

from .files import BINARY, NOFOLLOW, NONBLOCK, FileError, is_link, move_to_trash, write_atomic

FOLDER = "便签"
LAYOUT = ".布局.json"
TAKEN_DOWN = ".已撤下"
DEFAULT_ROPE = "随手记"
COLORS = ("lilac", "mint", "pink", "butter", "sky")
TEXT_LIMIT = 20_000
ROPE_LIMIT = 24
NOTE_LIMIT = 500
SHELF_LIMIT = 30      # taken-down notes offered for 放回, newest first
SHELF_TEXT = 200      # characters of each one shown in the drawer
NOTE_ID = re.compile(r"\d{8}-\d{6}-[a-z0-9]{4}")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
ROPE_NAME = re.compile(r"[^\s/\\:*?\"<>|.][^/\\:*?\"<>|]{0,29}")
CONFLICT = "这张便签刚被改过（可能是 Claude 或 Codex），先看看新内容再保存"
GONE = "这张便签已经不在「已撤下」里了"
OCCUPIED = "原位置已经有同名便签"
_LOCK = threading.Lock()


class NoteConflict(RuntimeError):
    """The note changed on disk after the person opened it; `note` is what is there now."""

    def __init__(self, note: dict[str, Any] | None) -> None:
        super().__init__(CONFLICT)
        self.note = note


def now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def stamp(moment: float) -> str:
    """The updated_at a note shows: local time, to the second."""
    return dt.datetime.fromtimestamp(moment).astimezone().isoformat(timespec="seconds")


def instant(value: object) -> dt.datetime | None:
    """Read an updated_at back, whatever time zone it was written in."""
    text = str(value or "").strip()
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.astimezone()   # no zone given: local time
    return moment.replace(microsecond=0)


def same_moment(first: object, second: object) -> bool:
    moment = instant(first)
    return moment is not None and moment == instant(second)


def read_note(path: Path, rope: str) -> dict[str, Any] | None:
    """One note as the board shows it, or None when the file cannot be shown.

    The time and the text come from the same open file, so updated_at always
    belongs to the text the person sees. Links and anything but a plain file
    are skipped.
    """
    if not NOTE_ID.fullmatch(path.stem):
        return None
    try:
        if is_link(path):      # O_NOFOLLOW is 0 on Windows
            return None
        descriptor = os.open(path, os.O_RDONLY | NOFOLLOW | NONBLOCK | BINARY)
    except OSError:
        return None
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_size > TEXT_LIMIT * 4:
            return None
        chunks, size = [], 0
        while size <= TEXT_LIMIT * 4:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        text = b"".join(chunks).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    finally:
        os.close(descriptor)
    shade, day, body = parse(text.replace("\r\n", "\n").replace("\r", "\n"))
    stem = path.stem
    return {"id": stem, "rope": rope, "text": body, "color": shade, "date": day,
            "created": f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}",
            "updated_at": stamp(status.st_mtime)}


def index_in(value: object, size: int) -> int:
    """Where to insert: the given position kept inside the list, else the end."""
    if not isinstance(value, int) or isinstance(value, bool):
        return size
    return max(0, min(value, size))


def rope_name(value: object) -> str:
    name = str(value or "").strip()
    if not ROPE_NAME.fullmatch(name) or name.endswith(" "):
        raise ValueError("分组名称：1–30 个字，不能以 . 开头，不能有 / \\ : * ? \" < > |")
    return name


def note_id(value: object) -> str:
    text = str(value or "")
    if not NOTE_ID.fullmatch(text):
        raise ValueError("便签编号不正确")
    return text


def color(value: object) -> str:
    return value if value in COLORS else COLORS[0]


def note_date(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        dt.date.fromisoformat(text)
    except ValueError:
        raise ValueError("日期格式应为 2026-10-28") from None
    if not DATE.fullmatch(text):
        raise ValueError("日期格式应为 2026-10-28")
    return text


def parse(text: str) -> tuple[str, str, str]:
    """Return (color, date, body) from a note file."""
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            head, body = text[4:end], text[end + 4:].lstrip("\n")
            shade = re.search(r"^颜色:\s*(\S+)\s*$", head, re.M)
            day = re.search(r"^日期:\s*(\S+)\s*$", head, re.M)
            day_text = day.group(1) if day and DATE.fullmatch(day.group(1)) else ""
            return color(shade.group(1) if shade else ""), day_text, body.rstrip("\n")
    return COLORS[0], "", text.rstrip("\n")


def render(body: str, shade: str, day: str = "") -> str:
    return f"---\n颜色: {shade}\n" + (f"日期: {day}\n" if day else "") + f"---\n{body.strip()}\n"


class Notes:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    @property
    def root(self) -> Path:
        return self.workspace / FOLDER

    def check_root(self) -> None:
        if not self.workspace.is_dir():
            raise FileError("工作区不存在，先到设置里选好工作区位置")
        if self.root.is_symlink():
            raise FileError("便签文件夹不能是替身")

    def rope_path(self, name: str) -> Path:
        path = self.root / rope_name(name)
        if path.is_symlink():
            raise FileError("分组文件夹不能是替身")
        return path

    def note_path(self, rope: str, identifier: str) -> Path:
        path = self.rope_path(rope) / f"{note_id(identifier)}.md"
        if path.is_symlink():
            raise FileError("便签文件不能是替身")
        return path

    def shelf_path(self, rope: str) -> Path:
        """便签/.已撤下/<分组>: where taken-down notes of a group wait."""
        base = self.root / TAKEN_DOWN
        path = base / rope_name(rope)
        if base.is_symlink() or path.is_symlink():
            raise FileError("撤下文件夹不能是替身")
        return path

    def layout(self) -> dict[str, Any]:
        try:
            value = json.loads((self.root / LAYOUT).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = {}
        ropes = [name for name in value.get("ropes", []) if isinstance(name, str)]
        order = value.get("order") if isinstance(value.get("order"), dict) else {}
        return {"ropes": ropes, "order": {key: [item for item in items if isinstance(item, str)]
                                           for key, items in order.items()
                                           if isinstance(items, list)}}

    def save_layout(self, layout: dict[str, Any]) -> None:
        write_atomic(self.root / LAYOUT, json.dumps(layout, ensure_ascii=False, indent=1))

    def rope_names(self) -> list[str]:
        if not self.root.is_dir():
            return []
        found = [path.name for path in self.root.iterdir()
                 if path.is_dir() and not path.is_symlink() and ROPE_NAME.fullmatch(path.name)]
        saved = self.layout()["ropes"]
        return [name for name in saved if name in found] + sorted(set(found) - set(saved))

    def notes_in(self, name: str, order: list[str]) -> list[dict[str, Any]]:
        """Every note of a group in board order: the saved order first, unknown files after."""
        notes = [note for note in (read_note(path, name)
                                   for path in (self.root / name).glob("*.md")) if note]
        rank = {identifier: index for index, identifier in enumerate(order)}
        notes.sort(key=lambda note: (rank.get(note["id"], len(rank)), note["id"]))
        return notes

    def read_rope(self, name: str, order: list[str]) -> list[dict[str, Any]]:
        return self.notes_in(name, order)[:NOTE_LIMIT]

    def order_of(self, layout: dict[str, Any], name: str) -> list[str]:
        """The ids of a group as the board shows them, past the display limit too."""
        return [note["id"] for note in self.notes_in(name, layout["order"].get(name, []))]

    def snapshot(self) -> dict[str, Any]:
        order = self.layout()["order"]
        ropes = []
        for name in self.rope_names():
            notes = self.notes_in(name, order.get(name, []))
            ropes.append({"name": name, "notes": notes[:NOTE_LIMIT],
                          "hidden": max(0, len(notes) - NOTE_LIMIT)})
        return {"ropes": ropes, "shelf": self.shelf(),
                "folder": f"{self.workspace.name}/{FOLDER}",
                "ready": self.workspace.is_dir(), "colors": list(COLORS)}

    def shelf(self) -> list[dict[str, Any]]:
        """The most recently taken-down notes, newest first, for the 「已撤下」 drawer.

        Moving a file keeps its edit time but updates its status-change time, so
        that later time is when the note was taken down.
        """
        base = self.root / TAKEN_DOWN
        found = []
        try:
            if self.root.is_symlink() or base.is_symlink() or not base.is_dir():
                return []
            for folder in base.iterdir():
                name = folder.name
                if (folder.is_symlink() or not folder.is_dir()
                        or not ROPE_NAME.fullmatch(name) or name.endswith(" ")):
                    continue
                for path in folder.glob("*.md"):
                    if not NOTE_ID.fullmatch(path.stem):
                        continue
                    try:
                        status = path.lstat()
                    except OSError:
                        continue
                    if stat.S_ISREG(status.st_mode):
                        found.append((max(status.st_ctime, status.st_mtime), path.stem, name, path))
        except OSError:
            return []
        found.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        shelf = []
        for moment, _, rope, path in found:
            note = read_note(path, rope)
            if note is None:
                continue
            shelf.append({"id": note["id"], "rope": rope, "text": note["text"][:SHELF_TEXT],
                          "color": note["color"], "updated_at": note["updated_at"],
                          "taken_down_at": stamp(moment)})
            if len(shelf) >= SHELF_LIMIT:
                break
        return shelf

    # -- writes ---------------------------------------------------------
    def save(self, value: dict[str, Any]) -> dict[str, Any]:
        """Write a note; returns it as the board shows it (with its new updated_at).

        An edit may carry the updated_at the person saw when opening the note:
        if the file has changed since, NoteConflict is raised and nothing is written.
        """
        text = str(value.get("text") or "")
        if not text.strip():
            raise ValueError("便签是空的")
        if len(text) > TEXT_LIMIT:
            raise ValueError("便签太长了，拆成几张吧")
        with _LOCK:
            self.check_root()
            rope = rope_name(value.get("rope") or DEFAULT_ROPE)
            identifier = value.get("id")
            day = note_date(value.get("date")) if "date" in value else None
            if identifier:
                path = self.note_path(rope, identifier)
                if not path.is_file():
                    raise FileNotFoundError(path)
                seen = value.get("updated_at")
                if seen not in (None, "") and not same_moment(stamp(path.stat().st_mtime), seen):
                    raise NoteConflict(read_note(path, rope))
                if day is None:   # not sent: keep the date the note already has
                    day = parse(path.read_text(encoding="utf-8"))[1]
            else:
                if len(self.rope_names()) >= ROPE_LIMIT and not self.rope_path(rope).is_dir():
                    raise ValueError(f"最多 {ROPE_LIMIT} 个分组")
                identifier = f"{now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
                path = self.note_path(rope, identifier)
                layout, names = self.layout(), self.rope_names()
                existing = self.order_of(layout, rope) if rope in names else []
                layout["ropes"] = names if rope in names else names + [rope]
                layout["order"][rope] = existing + [identifier]
                write_atomic(path, render(text, color(value.get("color")), day or ""))
                self.save_layout(layout)
                return read_note(path, rope) or {"id": identifier, "rope": rope}
            write_atomic(path, render(text, color(value.get("color")), day or ""))
            return read_note(path, rope) or {"id": identifier, "rope": rope}

    def move(self, value: dict[str, Any]) -> dict[str, Any]:
        with _LOCK:
            self.check_root()
            source_rope, target_rope = rope_name(value.get("rope")), rope_name(value.get("to"))
            identifier = note_id(value.get("id"))
            source = self.note_path(source_rope, identifier)
            if not source.is_file():
                raise FileNotFoundError(source)
            target_folder = self.rope_path(target_rope)
            if not target_folder.is_dir():
                raise ValueError("目标分组不存在")
            layout = self.layout()
            current = {name: self.order_of(layout, name) for name in {source_rope, target_rope}}
            if identifier in current[source_rope]:
                current[source_rope].remove(identifier)
            target = current[target_rope]
            index = index_in(value.get("index"), len(target))
            target.insert(index, identifier)
            if source_rope != target_rope:
                os.replace(source, target_folder / source.name)
            layout["order"].update(current)
            self.save_layout(layout)
            return {"id": identifier, "rope": target_rope, "index": index}

    def take_down(self, value: dict[str, Any]) -> dict[str, Any]:
        """Move a note to 便签/.已撤下/<分组>/; `index` is where it hung, for 放回."""
        with _LOCK:
            self.check_root()
            rope, identifier = rope_name(value.get("rope")), note_id(value.get("id"))
            source = self.note_path(rope, identifier)
            if not source.is_file():
                raise FileNotFoundError(source)
            shelf = self.shelf_path(rope)
            layout = self.layout()
            shown = self.order_of(layout, rope)
            index = shown.index(identifier) if identifier in shown else len(shown)
            shelf.mkdir(parents=True, exist_ok=True)
            os.replace(source, shelf / source.name)
            if identifier in layout["order"].get(rope, []):
                layout["order"][rope].remove(identifier)
                self.save_layout(layout)
            return {"id": identifier, "rope": rope, "index": index,
                    "kept_in": f"{FOLDER}/{TAKEN_DOWN}/{rope}"}

    def restore(self, value: dict[str, Any]) -> dict[str, Any]:
        """放回: move a taken-down note back into its group at `index` (else at the end).

        The group folder is made again if it was put away meanwhile. Returns the
        note as the board shows it.
        """
        with _LOCK:
            self.check_root()
            rope, identifier = rope_name(value.get("rope")), note_id(value.get("id"))
            source = self.shelf_path(rope) / f"{identifier}.md"
            if source.is_symlink():
                raise FileError("便签文件不能是替身")
            if not source.is_file():
                raise ValueError(GONE)
            target = self.note_path(rope, identifier)
            if target.exists():
                raise ValueError(OCCUPIED)
            names = self.rope_names()
            if not target.parent.is_dir():
                if len(names) >= ROPE_LIMIT:
                    raise ValueError(f"已经有 {ROPE_LIMIT} 个分组了，先收起一个再放回")
                target.parent.mkdir(parents=True)
            layout = self.layout()
            shown = self.order_of(layout, rope)
            shown.insert(index_in(value.get("index"), len(shown)), identifier)
            os.replace(source, target)
            layout["ropes"] = names if rope in names else names + [rope]
            layout["order"][rope] = shown
            self.save_layout(layout)
            return read_note(target, rope) or {"id": identifier, "rope": rope}

    def delete(self, value: dict[str, Any]) -> dict[str, Any]:
        """Move one note to the system Trash: from the board, or with `shelf` from 已撤下.

        `trashed` is the name the file has in the Trash (it gets a number when a
        note of the same name is already there).
        """
        with _LOCK:
            self.check_root()
            rope, identifier = rope_name(value.get("rope")), note_id(value.get("id"))
            if value.get("shelf"):
                source = self.shelf_path(rope) / f"{identifier}.md"
                if source.is_symlink():
                    raise FileError("便签文件不能是替身")
                if not source.is_file():
                    raise ValueError(GONE)
                return {"id": identifier, "rope": rope, "trashed": move_to_trash(source).name}
            source = self.note_path(rope, identifier)
            if not source.is_file():
                raise FileNotFoundError(source)
            layout = self.layout()
            trashed = move_to_trash(source)
            if identifier in layout["order"].get(rope, []):
                layout["order"][rope].remove(identifier)
                self.save_layout(layout)
            return {"id": identifier, "rope": rope, "trashed": trashed.name}

    def clear_shelf(self, value: dict[str, Any] | None = None) -> dict[str, Any]:
        """Move everything under 便签/.已撤下/ to the system Trash (`value` is unused).

        Each group folder goes whole (so the Trash shows 随手记/, not loose
        files), groups that were put away whole included; a link goes as the link.
        `trashed` counts the note files that went.
        """
        with _LOCK:
            self.check_root()
            base = self.root / TAKEN_DOWN
            if self.root.is_symlink() or base.is_symlink():
                raise FileError("撤下文件夹不能是替身")
            if not base.is_dir():
                return {"trashed": 0}
            files = 0
            for entry in sorted(base.iterdir()):
                if entry.is_dir() and not entry.is_symlink():
                    files += sum(len(names) for _, _, names in os.walk(entry, followlinks=False))
                else:
                    files += 1
                move_to_trash(entry)
            return {"trashed": files}

    def rope(self, value: dict[str, Any]) -> dict[str, Any]:
        action = value.get("action")
        with _LOCK:
            self.check_root()
            layout = self.layout()
            names = self.rope_names()
            if action == "create":
                name = rope_name(value.get("name"))
                if name in names:
                    raise ValueError("已经有这个分组了")
                if len(names) >= ROPE_LIMIT:
                    raise ValueError(f"最多 {ROPE_LIMIT} 个分组")
                self.rope_path(name).mkdir(parents=True)
                layout["ropes"] = names + [name]
            elif action == "rename":
                name, new = rope_name(value.get("name")), rope_name(value.get("to"))
                if name not in names:
                    raise FileNotFoundError(name)
                if new in names:
                    raise ValueError("已经有这个分组了")
                os.replace(self.rope_path(name), self.rope_path(new))
                layout["ropes"] = [new if item == name else item for item in names]
                if name in layout["order"]:
                    layout["order"][new] = layout["order"].pop(name)
            elif action == "remove":
                name = rope_name(value.get("name"))
                folder = self.rope_path(name)
                if name not in names:
                    raise FileNotFoundError(name)
                if self.read_rope(name, []):
                    raise ValueError("分组里还有便签，先撤下或挪走")
                shelf = self.root / TAKEN_DOWN
                if shelf.is_symlink():
                    raise FileError("撤下文件夹不能是替身")
                shelf.mkdir(exist_ok=True)
                kept = shelf / f"{name}-{now():%Y%m%d-%H%M%S}"
                os.replace(folder, kept)   # nothing is deleted: the folder is kept aside
                layout["ropes"] = [item for item in names if item != name]
                layout["order"].pop(name, None)
            elif action == "reorder":
                wanted = [rope_name(item) for item in value.get("ropes") or []]
                layout["ropes"] = [item for item in wanted if item in names] + \
                    [item for item in names if item not in wanted]
            else:
                raise ValueError("不支持的操作")
            self.save_layout(layout)
            return {"ropes": layout["ropes"]}
