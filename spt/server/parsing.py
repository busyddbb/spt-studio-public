"""Conservative Markdown facts, separating current and historical records."""
from __future__ import annotations
import re
from urllib.parse import urlsplit

from .models import Record

ALIASES = {
    "instagram": "instagram", "instagramreels": "instagram",
    "facebook": "facebook", "facebookreels": "facebook",
    "tiktok": "tiktok", "youtube": "youtube",
    "googlebusinessprofile": "google_business",
    "google_business_profile": "google_business",
    "google_business": "google_business", "google商家资料": "google_business",
    "google商家": "google_business", "rednote": "xiaohongshu",
    "小红书": "xiaohongshu", "xiaohongshu": "xiaohongshu",
}
URL_PATTERN = re.compile(r"https?://[^\s<>；;，。)\]`]+")
SHA_PATTERN = re.compile(r"(?i)(?:sha[- ]?256)[^\da-f]*([\da-f]{64})")
VERIFY_PATTERN = re.compile(
    r"(?:已核验|公开全文.{0,8}核对|公开正文.{0,8}一致|播放.{0,8}已核|"
    r"公开.{0,12}核验|逐字.{0,8}一致)")


def platform_name(text: str) -> str | None:
    clean = re.sub(r"[\s#·：:]", "", text).lower().strip()
    return ALIASES.get(clean)


def url_platform(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").lower()
    domains = {"instagram.com": "instagram", "facebook.com": "facebook",
               "tiktok.com": "tiktok", "youtube.com": "youtube",
               "posts.gle": "google_business",
               "share.google": "google_business",
               "rednote.com": "xiaohongshu", "xiaohongshu.com": "xiaohongshu"}
    return next((value for domain, value in domains.items()
                 if host == domain or host.endswith("." + domain)), None)


def headings(text: str, level: int) -> list[tuple[str, str]]:
    pattern = re.compile(rf"^{'#' * level} (.+)$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    if not matches:
        return [("", text)]
    return [(match.group(1), text[match.end():matches[index + 1].start()
             if index + 1 < len(matches) else len(text)])
            for index, match in enumerate(matches)]


def package_sections(text: str) -> dict[str, str]:
    return {platform: body.strip() for title, body in headings(text, 2)
            if (platform := platform_name(title))}


def result_sections(text: str, package: bool) -> list[tuple[str, str, str]]:
    if package:
        return [(title, body, "current") for title, body in headings(text, 2)
                if re.search(r"实际发布结果|发布记录|归档凭证", title)]
    sections = headings(text, 1)
    explicit = [index for index, (title, _) in enumerate(sections)
                if re.search(r"当前采用|当前更正", title)]
    selected = explicit[0] if explicit else 0
    prior = sections[selected][1] if sections else ""
    withdrawn = bool(re.search(r"(?:此前|之前|旧|原).{0,24}(?:撤下|移除|删除)", prior))
    historical = "withdrawn" if withdrawn else "history"
    return [(title, body, "current" if index == selected else historical)
            for index, (title, body) in enumerate(sections)]


def section_sha(title: str, body: str) -> str | None:
    match = SHA_PATTERN.search(title + "\n" + body)
    return match.group(1).lower() if match else None


TIME_PATTERN = (r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?"
                r"(?:\s*(?:PDT|PST|UTC|Z|[+-]\d{2}:?\d{2}))?)?")
# 「发布时间：2026-10-23T00:13:19.637-07:00」 on a line of its own (the publishing queue's form)
TIME_LINE = re.compile(r"^\s*[-*]?\s*发布时间\s*[:：]\s*(" + TIME_PATTERN + ")")


def record_time(line: str, title: str, body: str = "") -> str | None:
    if re.search(r"unknown|approximate|约|精确发布时间.*未知", line, re.I):
        return None
    match = re.search(TIME_PATTERN, line)
    if match:
        return match.group(0)
    stated = [found.group(1) for text in body.splitlines()
              if (found := TIME_LINE.match(text))]
    if len(stated) == 1:
        return stated[0]
    date = re.search(r"\d{4}-\d{2}-\d{2}", title)
    return date.group(0) if date else None


def record_verified(line: str, body: str) -> bool:
    negative = r"源记录称已发|平台未核|未核验|未经核验"
    if re.search(negative, line):
        return False
    if VERIFY_PATTERN.search(line):
        return True
    statements = re.split(r"[。\n]", body)
    global_checks = [text for text in statements
                     if re.search(r"四个?平台|全部平台|各平台|所有平台", text)]
    return any(VERIFY_PATTERN.search(text) and not re.search(negative, text)
               for text in global_checks)


def parse_records(text: str, source: str, package: bool) -> list[Record]:
    records = []
    for title, body, state in result_sections(text, package):
        checksum = section_sha(title, body)
        for line in body.splitlines():
            for url in URL_PATTERN.findall(line):
                if not (platform := url_platform(url)):
                    continue
                account = re.search(r"/@([^/]+)", url)
                records.append(Record(platform, url, record_time(line, title, body),
                    checksum, record_verified(line, body), state, source,
                    title,
                    line.strip(), account.group(1) if account else ""))
    return records


def current_version(text: str) -> str | None:
    match = re.search(r"(?i)(?<![A-Za-z0-9])V\s*(\d+)", text)
    return "V" + match.group(1) if match else None


def archive_paths(text: str) -> list[str]:
    archive_lines = "\n".join(line for line in text.splitlines()
                              if re.search(r"归档|证据", line))
    matches = re.findall(r"<(/Users/[^>]+)>|`(/Users/[^`]+)`", archive_lines)
    return list(dict.fromkeys(first or second for first, second in matches))
