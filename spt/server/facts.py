"""Explain status separately from current-publication media matching."""
from __future__ import annotations
from pathlib import Path

from .files import digest
from .models import Work
from .parsing import current_version, result_sections, section_sha
from .scan import VERSION_NAME

PUBLISH_DOCUMENTS = {"发布包.md", "发布记录.md"}


def superseded_versions(work: Work) -> set[str]:
    """V folders whose prompt the 提示词 list, search and counts leave out by default.

    One version stands for the work: the 定稿 that 发布记录.md / 发布包.md name
    (current_version, matched by name like the detail's is_current) when that
    folder is there, otherwise the newest V folder, whether or not it has a
    正文.txt of its own. Every other V folder is superseded. 段 folders are parts
    of one long film, not versions, so they never replace each other.
    """
    numbered = {version.name: int(match.group(1)) for version in work.versions
                if (match := VERSION_NAME.match(version.name)) and match.group(1)}
    if not numbered:
        return set()
    final = work.current_version if work.current_version in numbered else \
        max(numbered, key=lambda name: (numbered[name], name))
    return set(numbered) - {final}


def select_current(work: Work) -> None:
    documents = sorted((doc for doc in work.documents
                        if doc.name in PUBLISH_DOCUMENTS),
                       key=lambda doc: doc.name != "发布记录.md")
    for document in documents:
        sections = result_sections(document.text, document.name == "发布包.md")
        for title, body, state in sections:
            if state != "current":
                continue
            version = current_version(title)
            if version:
                work.current_version = version
                work.basis.append(("selection", title, document.name))
            checksum = section_sha(title, body)
            if checksum:
                work.expected_sha256 = checksum
            if version:
                return
    for document in work.documents:
        first_line = document.text.splitlines()[0] if document.text else ""
        version = current_version(first_line)
        if version and document.name == "发布包.md":
            work.current_version = version
            work.basis.append(("selection", "发布包.md 的标题写着定稿是 " + version,
                               document.name))
            return


def compare_media(work: Work) -> None:
    if not work.expected_sha256:
        work.media_match = "not_applicable"
        return
    if not work.finals:
        work.media_match = "mismatch"
        work.issues.append("源发布记录存在当前成品指纹，但本地未发现根目录成品")
        return
    for media in work.finals:
        media.sha256 = digest(Path(work.path) / media.path)
    known = [media.sha256 for media in work.finals if media.sha256]
    if work.expected_sha256 in known:
        work.media_match = "match"
    elif len(known) == len(work.finals):
        work.media_match = "mismatch"
        work.issues.append("本地成片与源记录当前采用版本的SHA-256不一致；不可据此重发")
    else:
        work.media_match = "not_checked"
        work.issues.append("大文件未全量计算指纹，当前发布版本与本地成片尚未核对")


def infer_status(work: Work) -> None:
    current = [record for record in work.records if record.state == "current"]
    if current:
        work.status = "published"
        work.verified = all(record.verified for record in current)
        if not work.verified:
            work.issues.append("发布状态来自源记录，平台未核")
        sources = dict.fromkeys(item.source_path for item in current)
        text = f"发布记录里有 {len(current)} 个平台的发布链接；SPT 没有上平台核对"
        work.basis.append(("status", text, ", ".join(sources)))
    elif work.finals:
        package = any(document.name == "发布包.md" for document in work.documents)
        work.status = "ready" if package else "cut"
        text = "作品文件夹里有成片，也有发布包" if package else "作品文件夹里有成片，还没有发布包"
        sources = ", ".join(media.path for media in work.finals)
        work.basis.append(("status", text, sources))
    else:
        sources = ", ".join(version.name for version in work.versions)
        work.basis.append(("status", "只有制作中的版本，还没有成片和发布记录",
                           sources))
    select_current(work)
    compare_media(work)
    if work.versions and not work.current_version:
        work.basis.append(("selection", "最新改的一版不等于定稿",
                           work.latest_version or ""))
    if work.media_match == "mismatch":
        work.verified = False
