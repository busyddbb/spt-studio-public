"""Read the library sections (素材 / 提示词 / 记录 / skills) into items.

The workspace root holds works under 专业 folders plus four reserved sections.
Everything here is read-only: files are facts, the index is a cache.
"""
from __future__ import annotations
import hashlib
import os
import re
from pathlib import Path

from .facts import superseded_versions
from .files import FileError, read_text, safe_files, timestamp
from .models import Item, Work

SECTIONS = {"素材": "material", "提示词": "prompt", "记录": "record",
            "skills": "skill", "便签": "note"}
TEXT_SUFFIXES = {".md", ".txt"}
MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov",
                  ".m4v", ".webm"}
SIDECAR = "说明.md"
SOURCE_FILE = "SPT.yaml"
SOURCE_KINDS = {"skills": "skill", "技能": "skill", "prompts": "prompt",
                "提示词": "prompt", "records": "record", "记录": "record"}
DENIED_PARTS = {"账号", "accounts", ".git", "node_modules", ".env"}
SOURCE_DEPTH = 4
SKILL_FILE = "SKILL.md"
SKILL_DEPTH = 3
UNSORTED = "未分类"
META_KEYS = {
    "title": ("标题", "title", "name"),
    "note": ("说明", "description", "note", "简介"),
    "tags": ("标签", "tags"),
    "tool": ("工具", "tool", "model"),
    "status": ("状态", "status"),
}


def item_id(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:20]


def split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---"):
        return {}, text
    match = re.match(r"^---[ \t]*\n(.*?)\n---[ \t]*(?:\n|$)", text, re.S)
    if not match:
        return {}, text
    try:
        import yaml
        value = yaml.safe_load(match.group(1)) or {}
    except Exception:
        return {}, text
    return (value if isinstance(value, dict) else {}), text[match.end():]


def meta(values: dict[str, object], field: str) -> str:
    for key in META_KEYS[field]:
        value = values.get(key)
        if isinstance(value, (list, tuple)):
            return ", ".join(str(part).strip() for part in value if part)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def first_heading(body: str) -> str:
    match = re.search(r"^#{1,3}\s+(.+)$", body, re.M)
    return match.group(1).strip() if match else ""


def first_line(body: str, limit: int = 140) -> str:
    for line in body.splitlines():
        text = line.strip().lstrip("-*> ").strip()
        if text and not text.startswith(("#", "|", "```", "---")):
            return text[:limit]
    return ""


def without_heading(body: str, title: str) -> str:
    lines = body.splitlines()
    if lines and re.fullmatch(r"#{1,3}\s+" + re.escape(title), lines[0].strip()):
        return "\n".join(lines[1:]).strip()
    return body


def table_rows(text: str) -> tuple[list[str], list[list[str]]] | None:
    lines = [line.strip() for line in text.splitlines()]
    for index in range(len(lines) - 1):
        header, rule = lines[index], lines[index + 1]
        if header.startswith("|") and re.fullmatch(r"\|[\s:|-]+\|?", rule):
            columns = cells(header)
            rows = []
            for line in lines[index + 2:]:
                if not line.startswith("|"):
                    break
                rows.append(cells(line))
            return columns, rows
    return None


def cells(line: str) -> list[str]:
    return [part.strip() for part in line.strip().strip("|").split("|")]


def section_of(path: Path, base: Path, fallback: str = UNSORTED) -> str:
    parts = path.relative_to(base).parts
    return parts[0] if len(parts) > 1 else fallback


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def text_column(columns: list[str]) -> int | None:
    for index, name in enumerate(columns):
        if "写法" in name or "提示词" in name or name.lower() == "prompt":
            return index
    return None


def column(columns: list[str], row: list[str], *names: str) -> str:
    for name in names:
        if name in columns:
            index = columns.index(name)
            if index < len(row):
                return row[index]
    return ""


def table_items(path: Path, root: Path, text: str,
                modified: str) -> list[Item] | None:
    table = table_rows(text)
    if not table:
        return None
    columns, rows = table
    target = text_column(columns)
    if not columns or columns[0] != "编号" or target is None:
        return None
    source = relative(path, root)
    items = []
    for row in rows:
        if not row or not row[0] or len(row) <= target:
            continue
        code, prompt = row[0], row[target]
        name = row[1] if len(row) > 1 and 1 != target else ""
        details = "\n".join(f"- **{key}**：{value}"
                            for key, value in zip(columns, row) if value)
        rejected = any("不采用" in cell for cell in row)
        items.append(Item(
            item_id("material", source, code), "material", path.stem,
            name or code, prompt, details,
            column(columns, row, "来源"),
            column(columns, row, "适合类型", "色系"),
            "", "素材表", source, None, modified,
            code=code, status="不采用" if rejected else ""))
    return items


def document_item(path: Path, root: Path, kind: str, section: str,
                  preview: str | None) -> Item:
    raw = read_text(path)
    values, body = split_frontmatter(raw)
    body = body.strip()
    title = meta(values, "title") or first_heading(body) or (
        first_line(body, 40) if kind == "note" else "") or path.stem
    return Item(item_id(kind, relative(path, root)), kind, section, title,
                without_heading(body, title), body, meta(values, "note") or first_line(body),
                meta(values, "tags"), meta(values, "tool"), "库",
                relative(path, root), preview, timestamp(path),
                status=meta(values, "status"))


def media_item(path: Path, root: Path, base: Path,
               sidecar: Path | None) -> Item:
    values, body = ({}, "")
    if sidecar:
        values, body = split_frontmatter(read_text(sidecar))
        body = body.strip()
    folders = path.relative_to(base).parts[1:-1]
    tags = meta(values, "tags") or " / ".join(folders)
    return Item(item_id("material", relative(path, root)), "material",
                section_of(path, base), meta(values, "title") or path.stem,
                meta(values, "note") or first_line(body), body,
                meta(values, "note") or first_line(body), tags,
                meta(values, "tool"), "库", relative(path, root),
                relative(path, root), timestamp(path))


def section_items(base: Path, root: Path, kind: str,
                  issues: list[str]) -> list[Item]:
    files = safe_files(base, recursive=True)
    media = {path.with_suffix(""): path for path in files
             if path.suffix.lower() in MEDIA_SUFFIXES}
    items: list[Item] = []
    for path in files:
        suffix = path.suffix.lower()
        try:
            if suffix in TEXT_SUFFIXES:
                if path.name in {"README.md", SIDECAR}:
                    continue
                preview = media.get(path.with_suffix(""))
                if kind == "material" and preview:
                    continue
                if kind == "material" and suffix == ".md":
                    rows = table_items(path, root, read_text(path),
                                       timestamp(path))
                    if rows is not None:
                        items.extend(rows)
                        continue
                items.append(document_item(
                    path, root, kind, section_of(path, base, path.stem
                                                 if kind == "material"
                                                 else UNSORTED),
                    relative(preview, root) if preview else None))
            elif suffix in MEDIA_SUFFIXES and kind == "material":
                sidecar = path.with_suffix(".md")
                folder_note = path.parent / SIDECAR
                note = (sidecar if sidecar in files else
                        folder_note if folder_note in files else None)
                items.append(media_item(path, root, base, note))
        except FileError as error:
            issues.append(f"{relative(path, root)}：{error}")
    return items


def walk_files(base: Path, depth_limit: int,
               accept) -> list[Path]:
    found = []
    for current, folders, names in os.walk(base, followlinks=True):
        depth = len(Path(current).relative_to(base).parts)
        folders[:] = [name for name in folders if not name.startswith(".")
                      and name not in DENIED_PARTS and depth < depth_limit]
        found += [Path(current) / name for name in names
                  if not name.startswith(".") and accept(name)]
    return sorted(found)


def skill_files(base: Path) -> list[Path]:
    return walk_files(base, SKILL_DEPTH, lambda name: name == SKILL_FILE)


def text_files(base: Path) -> list[Path]:
    return walk_files(base, SOURCE_DEPTH, lambda name: Path(name).suffix
                      .lower() in TEXT_SUFFIXES and name not in
                      {"README.md", SIDECAR, SKILL_FILE})


def shown_path(path: Path, root: Path) -> str:
    if path.is_relative_to(root):
        return relative(path, root)
    home = Path.home()
    return "~/" + path.relative_to(home).as_posix() if path.is_relative_to(home) \
        else str(path)


def denied(path: Path) -> bool:
    return any(part in DENIED_PARTS for part in path.parts)


def read_sources(root: Path, issues: list[str]) -> list[dict[str, object]]:
    path = root / SOURCE_FILE
    if not path.is_file() or path.is_symlink():
        return []
    try:
        import yaml
        value = yaml.safe_load(read_text(path)) or {}
    except Exception as error:
        issues.append(f"{SOURCE_FILE}：无法读取（{error}）")
        return []
    sources = []
    for key, entries in (value.items() if isinstance(value, dict) else []):
        kind = SOURCE_KINDS.get(str(key))
        for entry in entries if kind and isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            folder = Path(str(entry.get("路径") or entry.get("path") or ""))
            folder = folder.expanduser()
            label = str(entry.get("名称") or entry.get("name") or folder.name)
            if not folder.is_absolute() or denied(folder) or \
                    not folder.is_dir():
                issues.append(f"{SOURCE_FILE}：跳过 {folder}")
                continue
            sources.append({"kind": kind, "label": label, "path": folder,
                            "prompts": entry.get("提示词",
                                                 entry.get("prompts")) is True})
    return sources


def source_document(path: Path, root: Path, kind: str, section: str,
                    source: str) -> Item:
    item = document_item(path, path.parent, kind, section, None)
    item.id = item_id(kind, str(path.resolve()))
    item.source = source
    item.path = shown_path(path, root)
    return item


def source_items(root: Path, source: dict[str, object],
                 issues: list[str]) -> list[Item]:
    base, label = Path(source["path"]), str(source["label"])
    items = []
    for path in text_files(base):
        if denied(path):
            continue
        try:
            items.append(source_document(path, root, str(source["kind"]),
                                         section_of(path, base, label), label))
        except (FileError, OSError) as error:
            issues.append(f"{shown_path(path, root)}：{error}")
    return items


def skill_prompts(skill: Path, root: Path, label: str,
                  issues: list[str]) -> list[Item]:
    folder = skill.parent / "prompts"
    if not folder.is_dir():
        return []
    items = []
    for path in text_files(folder):
        try:
            items.append(source_document(path, root, "prompt",
                                         skill.parent.name, label))
        except (FileError, OSError) as error:
            issues.append(f"{shown_path(path, root)}：{error}")
    return items


def skill_item(path: Path, section: str, shown: str) -> Item:
    raw = read_text(path)
    values, body = split_frontmatter(raw)
    name = meta(values, "title") or path.parent.name
    note = meta(values, "note") or first_line(body.strip())
    return Item(item_id("skill", str(path.resolve())), "skill", section,
                name, note, body.strip(), note, meta(values, "tags"), "",
                section, shown, None, timestamp(path))


def manifest_sources(bucket: Path, cache: dict[Path, dict[str, str]]) -> dict[str, str]:
    if bucket not in cache:
        try:
            import json
            value = json.loads((bucket / "manifest.json").read_text(encoding="utf-8"))
            cache[bucket] = {str(entry.get("skillId") or entry.get("name")): str(entry.get("source") or "")
                             for entry in value.get("skills", []) if isinstance(entry, dict)}
        except (OSError, ValueError, AttributeError):
            cache[bucket] = {}
    return cache[bucket]


def built_in_skill(path: Path, base: Path, cache: dict[Path, dict[str, str]]) -> bool:
    """Skills that ship with Claude or Codex rather than ones the person installed.

    Codex keeps its own in .system (already skipped as a dot folder). The Claude app
    syncs Anthropic's skills into synced/<bucket>/; its manifest says where each came from.
    """
    try:
        parts = path.relative_to(base).parts
    except ValueError:
        return False
    if len(parts) < 4 or parts[0] != "synced":
        return False
    source = manifest_sources(base / parts[0] / parts[1], cache).get(parts[2], "anthropic")
    return source.startswith("anthropic")


def skill_items(root: Path, skill_roots: tuple[tuple[str, Path], ...],
                issues: list[str],
                extra: list[dict[str, object]] = ()) -> list[Item]:
    sources = [("库内", root / "skills", False)]
    sources += [(str(source["label"]), Path(source["path"]),
                 bool(source["prompts"])) for source in extra]
    sources += [(f"{label} 已安装", path, False) for label, path in skill_roots]
    installed = {path for _, path in skill_roots}
    manifests: dict[Path, dict[str, str]] = {}
    seen: set[str] = set()
    items = []
    for section, base, prompts in sources:
        if not base.is_dir():
            continue
        for path in skill_files(base):
            real = str(path.resolve())
            if real in seen or denied(path) or (
                    base in installed and built_in_skill(path, base, manifests)):
                continue
            seen.add(real)
            shown = shown_path(path, root)
            try:
                items.append(skill_item(path, section, shown))
            except (FileError, OSError) as error:
                issues.append(f"{shown}：{error}")
            if prompts:
                items += skill_prompts(path, root, section, issues)
    return items


def scan_library(root: Path, skill_roots: tuple[tuple[str, Path], ...] = (),
                 issues: list[str] | None = None) -> list[Item]:
    issues = [] if issues is None else issues
    items: list[Item] = []
    if not root.is_dir():
        return items
    for name, kind in SECTIONS.items():
        base = root / name
        if kind == "skill" or not base.is_dir() or base.is_symlink():
            continue
        items.extend(section_items(base, root, kind, issues))
    sources = read_sources(root, issues)
    for source in sources:
        if source["kind"] != "skill":
            items.extend(source_items(root, source, issues))
    items.extend(skill_items(root, skill_roots, issues,
                             [source for source in sources
                              if source["kind"] == "skill"]))
    return items


def work_items(work: Work, root: Path) -> list[Item]:
    """Every version's prompt stays an item; older ones are flagged, not dropped.

    Root 提示词*.md files are not versioned and are always listed.
    """
    base = work.relative_path
    older = superseded_versions(work)
    items = []
    for version in work.versions:
        if not version.prompt.strip():
            continue
        cover = next((media for media in version.media
                      if media.role in {"input", "return"}
                      and media.mime_type.startswith("image/")), None)
        path = f"{base}/{version.prompt_path}"
        items.append(Item(
            item_id("prompt", path), "prompt", work.category,
            f"{work.title} · {version.name}", version.prompt.strip(),
            version.prompt.strip(), work.note, work.client, work.tool,
            "作品", path, f"{base}/{cover.path}" if cover else None,
            version.created_at, work.id, version=version.name,
            superseded=version.name in older,
            adopted=version.name == work.current_version,
            client=work.client))
    for document in work.documents:
        stem = document.name.rsplit(".", 1)[0]
        if stem.startswith("提示词"):
            kind, label = "prompt", stem
        elif stem == "记录":
            kind, label = "record", "记录"
        else:
            continue
        values, body = split_frontmatter(document.text)
        body = body.strip()
        path = f"{base}/{document.name}"
        items.append(Item(
            item_id(kind, path), kind, work.category,
            meta(values, "title") or f"{work.title} · {label}", body, body,
            meta(values, "note") or first_line(body), work.client,
            meta(values, "tool") or work.tool, "作品", path, None,
            document.modified_at, work.id, client=work.client))
    return items
