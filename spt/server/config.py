"""Explicit local paths; no workspace discovery or migration.

The workspace is 工作区/ next to the software unless the person picks another
folder in 设置 (saved in spt/settings.local.json, never shared) or SPT_WORKSPACE
is set.
"""
from __future__ import annotations
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

INSTALLED_SKILLS = (("Claude", "~/.claude/skills"), ("Codex", "~/.codex/skills"))
SPT_ROOT = Path(__file__).resolve().parents[1]
SETTINGS = SPT_ROOT / "settings.local.json"
# Written by 打包分享 into the shared copy only: {"share": true}. The owner's folder has no such file.
SHARE_SETTINGS = SPT_ROOT / "settings.share.json"
DEFAULT_WORKSPACE = SPT_ROOT.parent / "工作区"
DENIED_WORKSPACE_PARTS = {"账号", "accounts", ".git", "node_modules", "Library"} \
    | ({"AppData"} if os.name == "nt" else set())   # Windows keeps app and login data there


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def read_settings() -> dict:
    return read_json(SETTINGS)


def share_mode() -> bool:
    """True inside a copy made by 打包分享; the UI then hides tools only the owner needs."""
    return read_json(SHARE_SETTINGS).get("share") is True


def custom_workspace() -> Path | None:
    value = read_settings().get("workspace")
    return Path(value).expanduser() if isinstance(value, str) and value.strip() else None


def check_workspace(value: str) -> Path:
    """A folder SPT may index: an existing directory that is not too broad or private."""
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        raise ValueError("请填写完整路径，例如 ~/Documents/我的工作区")
    if not path.is_dir():
        raise ValueError("这个文件夹不存在")
    real = path.resolve()
    home = Path.home().resolve()
    root = Path(real.anchor)   # "/" on a Mac, "C:\\" on Windows
    if real in {root, home, home / "Desktop", home / "Documents", home / "Downloads"} \
            or real.parent == root or real.parent == Path("/Volumes"):
        raise ValueError("范围太大了：请选一个专门放作品的文件夹")
    if any(part in DENIED_WORKSPACE_PARTS for part in real.parts):
        raise ValueError("这个位置包含账号或系统资料，SPT 不读")
    if real == SPT_ROOT.parent.resolve() or real.is_relative_to(SPT_ROOT.resolve()):
        raise ValueError("工作区不能是软件文件夹本身")
    return path


def save_workspace(value: str | None) -> Path:
    """Save a custom workspace (or clear it with an empty value). Returns the folder now used."""
    settings = read_settings()
    if value and value.strip():
        path = check_workspace(value)
        settings["workspace"] = str(path)
    else:
        settings.pop("workspace", None)
        path = DEFAULT_WORKSPACE
    handle, temporary = tempfile.mkstemp(prefix=".settings-", dir=SETTINGS.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(settings, stream, ensure_ascii=False, indent=1)
        os.replace(temporary, SETTINGS)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return path


@dataclass(frozen=True)
class Config:
    workspace: Path
    cache: Path
    ui: Path
    port: int = 8788
    skill_roots: tuple[tuple[str, Path], ...] = ()

    @property
    def resolved_workspace(self) -> Path:
        return self.workspace.expanduser().resolve()

    @property
    def database(self) -> Path:
        return self.cache / "index.sqlite3"


def installed_skill_roots() -> tuple[tuple[str, Path], ...]:
    if os.environ.get("SPT_SKIP_INSTALLED_SKILLS") == "1":
        return ()
    roots = ((label, Path(path).expanduser()) for label, path in INSTALLED_SKILLS)
    return tuple((label, path) for label, path in roots if path.is_dir())


def workspace_source() -> str:
    if os.environ.get("SPT_WORKSPACE"):
        return "env"
    return "custom" if custom_workspace() else "default"


def default_config(port: int = 8788) -> Config:
    server = Path(__file__).resolve().parent
    workspace = os.environ.get("SPT_WORKSPACE")
    cache = os.environ.get("SPT_CACHE")
    return Config(Path(workspace).expanduser() if workspace
                  else custom_workspace() or DEFAULT_WORKSPACE,
                  Path(cache).expanduser() if cache else server / ".cache",
                  server.parent / "ui", port, installed_skill_roots())
