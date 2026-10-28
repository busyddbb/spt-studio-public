"""Typed facts extracted from files, never platform state."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Media:
    name: str
    path: str
    role: str
    mime_type: str
    size: int
    modified_at: str
    order: int = 0
    version: str = ""
    sha256: str | None = None


@dataclass
class Version:
    name: str
    prompt: str
    prompt_path: str | None
    created_at: str
    media: list[Media] = field(default_factory=list)


@dataclass
class Record:
    platform: str
    url: str
    published_at: str | None
    sha256: str | None
    verified: bool
    state: str
    source_path: str
    source_heading: str
    evidence: str
    account: str = ""


@dataclass
class Document:
    name: str
    text: str
    modified_at: str


@dataclass
class Item:
    """One library entry: a prompt, material, record or skill."""
    id: str
    kind: str
    section: str
    title: str
    text: str
    body: str
    note: str
    tags: str
    tool: str
    source: str
    path: str
    file: str | None
    modified_at: str
    work_id: str | None = None
    code: str = ""
    status: str = ""
    # The client code of the work this came from (日期-客户-主题); None for items
    # that stand on their own under 提示词/、记录/、素材/.
    client: str | None = None
    # Only for a work's V*/正文.txt (and 段*/正文.txt): the folder it came from.
    # superseded: another version stands for the work, so lists, search and counts
    # leave this one out unless all versions are asked for. adopted: this is the
    # 定稿 named in 发布记录.md / 发布包.md. Kept in item_versions, not in items.
    version: str | None = None
    superseded: bool = False
    adopted: bool = False


@dataclass
class Observation:
    """One row of a work's 数据/表现.csv: the numbers seen at one moment.

    at is UTC ISO; age_hours is hours since the work's publication on that
    platform (None without a publish time). Unknown numbers stay None, never 0.
    """
    at: str
    platform: str
    account: str
    path: str
    age_hours: float | None = None
    views: float | None = None
    reach: float | None = None
    likes: float | None = None
    comments: float | None = None
    saves: float | None = None
    shares: float | None = None
    profile_visits: float | None = None
    follows: float | None = None
    ctr: float | None = None
    three_sec_rate: float | None = None
    completion_rate: float | None = None
    avg_watch_sec: float | None = None
    source: str = ""
    note: str = ""


@dataclass
class Retention:
    """One point of a retention curve (数据/留存.csv); rows sharing `at` are one curve."""
    at: str
    platform: str
    account: str
    second: float
    rate: float
    path: str


@dataclass
class Analysis:
    """One 数据/分析/*.md: a few 键: 值 header lines, then free text."""
    path: str
    date: str
    platform: str
    account: str
    node: str
    conclusion: str
    body: str
    modified_at: str
    tags: list[str] = field(default_factory=list)


@dataclass
class AccountObservation:
    """One row of 工作区/数据/账号/<平台>-<账号>/表现.csv."""
    platform: str
    account: str
    at: str
    path: str
    followers: float | None = None
    views: float | None = None
    reach: float | None = None
    interactions: float | None = None
    likes: float | None = None
    comments: float | None = None
    saves: float | None = None
    shares: float | None = None
    profile_visits: float | None = None
    follows: float | None = None
    source: str = ""
    note: str = ""


@dataclass
class Work:
    id: str
    category: str
    date: str
    client: str
    title: str
    path: str
    relative_path: str
    updated_at: str
    created_at: str
    note: str = ""
    tags: str = ""
    tool: str = ""
    status: str = "wip"
    verified: bool = False
    latest_version: str | None = None
    current_version: str | None = None
    media_match: str = "not_checked"
    expected_sha256: str | None = None
    cover_source: str | None = None
    cover_cache: str | None = None
    # Which rule found the cover: 封面 | spt.yaml | 版本图 | 根目录图 | 视频抽帧 | None.
    # cover_source stays the picture's path inside the work (None for a video frame).
    cover_rule: str | None = None
    versions: list[Version] = field(default_factory=list)
    finals: list[Media] = field(default_factory=list)
    records: list[Record] = field(default_factory=list)
    package: dict[str, str] = field(default_factory=dict)
    documents: list[Document] = field(default_factory=list)
    archives: list[str] = field(default_factory=list)
    basis: list[tuple[str, str, str]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    # 数据记录 (spt/docs/数据记录格式.md): the work's 数据/ folder
    observations: list[Observation] = field(default_factory=list)
    retention: list[Retention] = field(default_factory=list)
    analyses: list[Analysis] = field(default_factory=list)
