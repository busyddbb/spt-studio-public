"""spt add: put a finished piece into the library as one work folder.

Only adds files. It never overwrites, never deletes and never touches the source;
a file that already exists with other content is kept and the new one is saved
next to it. On a Mac, large media are copied as APFS clones (`cp -c`), which take
no extra disk space until one side changes; elsewhere they are plain copies.
"""
from __future__ import annotations
import datetime as dt
import filecmp
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from .scan import IMAGES, RESERVED, VIDEOS

NAME = re.compile(r"[^\s/\\:*?\"<>|.][^/\\:*?\"<>|]{0,59}")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
FINAL_WORDS = re.compile(r"成片|发布版|母版")
# never copy anything that looks like a login, key or account file
SECRET = re.compile(r"账号|^accounts?$|cookie|token|password|密码|secret|\.env|\.pem$", re.I)


class IntakeError(ValueError):
    pass


def name(value: str, label: str) -> str:
    text = str(value or "").strip()
    if not NAME.fullmatch(text) or text.endswith(" "):
        raise IntakeError(f"{label}：1–60 个字，不能以 . 开头，不能有 / \\ : * ? \" < > |")
    return text


def secret(path: Path) -> bool:
    """A login, key or account file, by any part of its path. A folder named exactly 账号 is
    Lemonade's container for client folders (02-运营/账号/<客户>/…), not an account file: the
    files inside are judged by their own names."""
    return any(part != "账号" and SECRET.search(part) for part in path.parts)


def source_files(path: Path) -> list[Path]:
    """Regular files under path (or path itself), skipping hidden, links and secrets."""
    if path.is_symlink() or secret(path) or path.name.startswith("."):
        return []
    if path.is_file():
        return [path]
    found = []
    for item in sorted(path.rglob("*")):   # rglob does not walk into linked folders
        inner = item.relative_to(path)
        if any(part.startswith(".") for part in inner.parts) or item.is_symlink() or secret(inner):
            continue
        if item.is_file() and item.resolve().is_relative_to(path.resolve()):
            found.append(item)
    return found


def copy_new(source: Path, target: Path) -> None:
    """A plain copy into a file that must not exist yet (O_EXCL): never overwrites."""
    try:
        with source.open("rb") as reader, target.open("xb") as writer:
            shutil.copyfileobj(reader, writer, 1024 * 1024)
    except FileExistsError:
        return
    shutil.copystat(source, target)


def clone(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        try:
            subprocess.run(["cp", "-c", "-n", str(source), str(target)], check=True,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=600)
        except (OSError, subprocess.SubprocessError):   # FileNotFoundError: no cp
            pass
    if not target.exists():   # not a Mac, not APFS, or cp failed: a plain copy
        copy_new(source, target)


def free_name(target: Path) -> Path:
    for number in range(2, 1000):
        candidate = target.with_name(f"{target.stem}-收录{number}{target.suffix}")
        if not candidate.exists():
            return candidate
    raise IntakeError(f"{target.name} 重名太多")


def next_version(folder: Path, taken: set[str]) -> str:
    names = [item.name for item in folder.glob("V*")] if folder.exists() else []
    numbers = [int(match.group(1)) for label in names + sorted(taken)
               if (match := re.fullmatch(r"V(\d+)", label, re.I))]
    return f"V{max(numbers, default=0) + 1}"


def plan(folder: Path, finals: Iterable[Path], cover: Path | None, prompts: Iterable[Path],
         records: Iterable[Path], versions: Iterable[Path], extras: Iterable[Path]) -> list[tuple[Path, str]]:
    steps: list[tuple[Path, str]] = []
    images: list[Path] = []
    for item in finals:
        for path in source_files(item):
            suffix = path.suffix.lower()
            if suffix in VIDEOS and not FINAL_WORDS.search(path.stem):
                steps.append((path, f"成片_{path.name}"))
            else:
                steps.append((path, path.name))
            if suffix in IMAGES:
                images.append(path)
    cover = cover or (images[0] if images else None)
    if cover:
        for path in source_files(cover)[:1]:
            steps.append((path, "封面" + path.suffix.lower()))
    prompt_files = [path for item in prompts for path in source_files(item)]
    for index, path in enumerate(prompt_files, 1):
        stem = "提示词" if len(prompt_files) == 1 else f"提示词-{index}"
        steps.append((path, stem + (".txt" if path.suffix.lower() == ".txt" else ".md")))
    record_files = [path for item in records for path in source_files(item)]
    for index, path in enumerate(record_files):
        steps.append((path, "记录.md" if index == 0 else f"资料/{path.name}"))
    taken: set[str] = set()
    for item in versions:
        files = source_files(item)
        if not files:
            continue
        label = next_version(folder, taken)
        taken.add(label)
        base = item if item.is_dir() else item.parent
        for path in files:
            steps.append((path, f"{label}/{path.relative_to(base).as_posix()}"))
    for item in extras:
        base = item.parent
        for path in source_files(item):
            steps.append((path, f"资料/{path.relative_to(base).as_posix()}"))
    return steps


def note_text(title: str, tags: str, tool: str, note: str, source: str) -> str:
    lines = ["---"]
    for key, value in (("标题", title), ("标签", tags), ("工具", tool), ("说明", note), ("来源", source)):
        if value:
            lines.append(f"{key}: {' '.join(str(value).split())}")
    lines.append("---")
    lines.append(f"{dt.date.today().isoformat()} 用 spt add 收录" + (f"，原件在 {source}" if source else "") + "。")
    return "\n".join(lines) + "\n"


def add_work(workspace: Path, field: str, client: str, topic: str, date: str = "",
             title: str = "", tags: str = "", tool: str = "", note: str = "", source: str = "",
             finals: Iterable[Path] = (), cover: Path | None = None, prompts: Iterable[Path] = (),
             records: Iterable[Path] = (), versions: Iterable[Path] = (), extras: Iterable[Path] = (),
             dry_run: bool = False) -> dict[str, Any]:
    workspace = workspace.resolve()
    field = name(field, "专业")
    if field in RESERVED:
        raise IntakeError(f"「{field}」是保留名，不能当专业")
    client = name(client, "客户")
    if "-" in client:
        raise IntakeError("客户名里不能有 -（自己的作品写 自家）")
    topic = name(topic, "主题")
    date = date or dt.date.today().isoformat()
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        raise IntakeError("日期格式应为 2026-10-21") from None
    if not DATE.fullmatch(date):
        raise IntakeError("日期格式应为 2026-10-21")
    if (workspace / field).is_symlink():
        raise IntakeError("专业文件夹不能是替身")
    folder = workspace / field / f"{date}-{client}-{topic}"
    if folder.is_symlink() or not folder.resolve().is_relative_to(workspace):
        raise IntakeError("作品文件夹不在工作区里")
    inputs = [Path(item).expanduser() for group in (finals, prompts, records, versions, extras) for item in group]
    inputs += [Path(cover).expanduser()] if cover else []
    for item in inputs:
        if not item.exists():
            raise IntakeError(f"找不到：{item}")
        if item.resolve().is_relative_to(folder.resolve()):
            raise IntakeError(f"来源已经在这个作品里：{item}")
    steps = plan(folder, [Path(p).expanduser() for p in finals], Path(cover).expanduser() if cover else None,
                 [Path(p).expanduser() for p in prompts], [Path(p).expanduser() for p in records],
                 [Path(p).expanduser() for p in versions], [Path(p).expanduser() for p in extras])
    result: dict[str, Any] = {"folder": folder.relative_to(workspace).as_posix(), "created": not folder.exists(),
                              "copied": [], "skipped": [], "conflicts": [], "dry_run": dry_run}
    if not steps and not (title or note):
        raise IntakeError("没有可收录的文件")
    seen: set[str] = set()
    for source_path, relative in steps:
        if relative in seen:
            relative = free_name(folder / relative).relative_to(folder).as_posix()
        seen.add(relative)
        target = folder / relative
        if not target.resolve().is_relative_to(folder.resolve()):
            raise IntakeError(f"文件名不安全：{relative}")
        if target.exists():
            if target.is_file() and filecmp.cmp(source_path, target, shallow=False):
                result["skipped"].append(relative)
                continue
            target = free_name(target)
            result["conflicts"].append({"kept": relative, "new": target.relative_to(folder).as_posix()})
        if not dry_run:
            clone(source_path, target)
        result["copied"].append(target.relative_to(folder).as_posix())
    note_file = folder / "说明.md"
    if not note_file.exists() and (title or tags or tool or note or source):
        if not dry_run:
            folder.mkdir(parents=True, exist_ok=True)
            note_file.write_text(note_text(title, tags, tool, note, source), encoding="utf-8")
        result["copied"].append("说明.md")
    return result
