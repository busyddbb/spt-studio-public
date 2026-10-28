"""Read existing directory conventions without writing into the workspace."""
from __future__ import annotations
import hashlib
import re
from pathlib import Path

from .files import (FileError, contained, media_fact, read_text, safe_files,
                    timestamp)
from .metrics import read_metrics
from .models import Document, Version, Work
from .parsing import archive_paths, package_sections, parse_records

WORK_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-([^-]+)-(.+)$")
VERSION_NAME = re.compile(r"^(?:V(\d+)|段(\d+))$", re.IGNORECASE)
IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEOS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}


def version_key(path: Path) -> tuple[int, str]:
    match = VERSION_NAME.match(path.name)
    return (int(next(part for part in match.groups() if part))
            if match else -1, path.name)


def natural_key(name: str) -> tuple:
    """01 < 02 < 10: runs of digits compare as numbers, the rest ignores case.

    re.split with a capturing group always alternates text, digits, text…, so the
    tuples compare like with like.
    """
    parts = re.split(r"(\d+)", name.casefold())
    return tuple(int(part) if index % 2 else part
                 for index, part in enumerate(parts))


def read_version(path: Path, work: Path) -> Version:
    files = safe_files(path)
    prompt = path / "正文.txt"
    prompt_ok = prompt in files
    created_at = min((timestamp(item) for item in files),
                     default=timestamp(path))
    version = Version(path.name, read_text(prompt) if prompt_ok else "",
                      prompt.relative_to(work).as_posix() if prompt_ok else None,
                      created_at)
    for item in files:
        if item == prompt:
            continue
        number = re.match(r"(\d+)_", item.name)
        role = "input" if number else "reference"
        if re.match(r"回片\d*", item.stem) and item.suffix.lower() in VIDEOS:
            role = "return"
        if item.suffix.lower() not in IMAGES | VIDEOS:
            continue
        version.media.append(media_fact(item, work, role,
            int(number.group(1)) if number else 0, path.name))
    version.media.sort(key=lambda media: (media.order, media.name))
    return version


def new_work(path: Path, category: str, root: Path) -> Work | None:
    match = WORK_NAME.match(path.name)
    if not match:
        return None
    relative = path.relative_to(root).as_posix()
    identifier = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:20]
    files = safe_files(path, recursive=True)
    times = [timestamp(item) for item in files] or [timestamp(path)]
    return Work(identifier, category, *match.groups(), str(path), relative,
                max(times), min(times))


NOTE_FILE = "说明.md"
# Top-level folders that are not 专业: the library sections and 数据/ (account-level
# 数据记录, see spt/docs/数据记录格式.md).
RESERVED = {"素材", "提示词", "记录", "skills", "便签", "数据"}


def note_documents(root: Path) -> list[Path]:
    files = safe_files(root)
    names = ["记录.md"] + sorted(path.name for path in files
                               if path.name.startswith(("提示词", "参考分工",
                                                        "参考图"))
                               and path.suffix.lower() in {".md", ".txt"})
    return [root / name for name in names if root / name in files]


def read_note(work: Work) -> None:
    from .library import meta, split_frontmatter, first_line
    path = Path(work.path) / NOTE_FILE
    if path not in safe_files(Path(work.path)):
        return
    try:
        values, body = split_frontmatter(read_text(path))
    except FileError as error:
        work.issues.append(str(error))
        return
    work.title = meta(values, "title") or work.title
    work.note = meta(values, "note") or first_line(body)
    work.tags = meta(values, "tags")
    work.tool = meta(values, "tool")
    work.documents.append(Document(NOTE_FILE, body.strip(), timestamp(path)))


def read_documents(work: Work) -> None:
    root = Path(work.path)
    for path in note_documents(root):
        try:
            work.documents.append(Document(path.name, read_text(path),
                                           timestamp(path)))
        except FileError as error:
            work.issues.append(str(error))
    for name in ("发布包.md", "发布记录.md"):
        path = root / name
        if path not in safe_files(root):
            continue
        try:
            text = read_text(path)
        except FileError as error:
            work.issues.append(str(error))
            continue
        work.documents.append(Document(name, text, timestamp(path)))
        work.records.extend(parse_records(text, name, name == "发布包.md"))
        work.archives.extend(archive_paths(text))
        if name == "发布包.md":
            work.package = package_sections(text)


def read_content(work: Work) -> None:
    root = Path(work.path)
    paths = [path for path in root.iterdir() if path.is_dir()
             and not path.is_symlink() and VERSION_NAME.match(path.name)]
    for path in sorted(paths, key=version_key, reverse=True):
        try:
            work.versions.append(read_version(path, root))
        except FileError as error:
            work.issues.append(str(error))
    work.latest_version = work.versions[0].name if work.versions else None
    for order, path in enumerate(safe_files(root)):
        video = path.suffix.lower() in VIDEOS
        if video and re.search(r"成片|发布版|母版", path.stem):
            work.finals.append(media_fact(path, root, "final", order))
        cover = path.stem == "封面" and path.suffix.lower() in IMAGES
        if not work.cover_source and cover:
            work.cover_source = path.relative_to(root).as_posix()
            work.cover_rule = "封面"
    work.finals.sort(key=lambda media: ("发布版" not in media.name,
                                        "母版" in media.name, media.name))
    read_documents(work)


def choose_cover(work: Work) -> None:
    """Without 封面.*: the first picture of the version that stands for the work,
    else the first picture in the work's root folder.

    Runs after infer_status, which is where current_version comes from: the 定稿
    when its folder is there, else the newest version folder. Pictures sort in
    natural order (01 < 02 < 10). Videos are left to covers.thumbnail, which takes
    a frame from the first 成片 when nothing here applied.
    """
    if work.cover_source:
        return
    by_name = {version.name: version for version in work.versions}
    chosen = by_name.get(work.current_version or "") or \
        (work.versions[0] if work.versions else None)
    if chosen:
        pictures = [media for media in chosen.media
                    if Path(media.name).suffix.lower() in IMAGES]
        if pictures:
            first = min(pictures, key=lambda media: natural_key(media.name))
            work.cover_source, work.cover_rule = first.path, "版本图"
            return
    root = Path(work.path)
    pictures = [path for path in safe_files(root)
                if path.suffix.lower() in IMAGES]
    if pictures:
        first = min(pictures, key=lambda path: natural_key(path.name))
        work.cover_source = first.relative_to(root).as_posix()
        work.cover_rule = "根目录图"


def parse_override(path: Path) -> dict[str, object]:
    try:
        import yaml
    except ImportError as error:
        raise ValueError("需要PyYAML才能读取人工配置") from error
    try:
        value = yaml.safe_load(read_text(path)) or {}
    except yaml.YAMLError as error:
        raise ValueError("spt.yaml 格式错误") from error
    if not isinstance(value, dict):
        raise ValueError("spt.yaml 必须是映射")
    return value


def apply_override(work: Work) -> bool:
    path = Path(work.path) / "spt.yaml"
    if path not in safe_files(Path(work.path)):
        return True
    try:
        value = parse_override(path)
        for key in ("title", "category"):
            if key in value and isinstance(value[key], str):
                setattr(work, key, value[key])
        if isinstance(value.get("cover"), str):
            cover = contained(Path(work.path), str(value["cover"]))
            if cover.suffix.lower() not in IMAGES:
                raise ValueError("cover必须指向作品内图片")
            work.cover_source = cover.relative_to(Path(work.path)).as_posix()
            work.cover_rule = "spt.yaml"
        return value.get("ignore") is not True
    except (ValueError, FileError, OSError) as error:
        work.issues.append("未采用spt.yaml：" + str(error))
        return True


def scan_work(path: Path, category: str, root: Path,
              issues: list[str] | None = None) -> Work | None:
    """One work folder read completely; None when it is not a work or opts out.

    issues: index-wide problems (数据/ rows that could not be read) go here too.
    """
    work = new_work(path, category, root)
    if work is None or not apply_override(work):
        return None
    read_note(work)
    read_content(work)
    read_metrics(work, root, [] if issues is None else issues)
    return work


def scan_works(root: Path, issues: list[str] | None = None) -> list[Work]:
    if not root.is_dir():
        return []
    works = []
    for category in sorted(root.iterdir()):
        hidden = category.name.startswith(".") or category.is_symlink()
        if not category.is_dir() or hidden or category.name in RESERVED:
            continue
        for path in sorted(category.iterdir()):
            if not path.is_dir() or path.is_symlink():
                continue
            work = scan_work(path, category.name, root, issues)
            if work:
                works.append(work)
    return works
