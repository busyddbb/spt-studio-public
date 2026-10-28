"""Build a shareable SPT zip: the software plus an empty 工作区, never the owner's content."""
from __future__ import annotations
import argparse
import datetime as dt
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "spt" / "templates"
SECTIONS = ("提示词", "素材", "记录", "skills", "便签")
# Copied as-is (minus caches). Everything else at the top level stays behind:
# 工作区 (rebuilt empty), data/ (databases, logs), native/build (the app goes to the top).
INCLUDE = ("README.md", "使用说明.md", "启动.py", "启动SPT.command", "启动SPT.bat",
           "app", "docs", "native", "spt", "tests", "windows", "scripts",
           "requirements.txt", "requirements-windows.txt", "安装与使用-Windows.md",
           "安装Windows.bat", "停止SPT后台.bat")
SKIP_NAMES = {".DS_Store", "__pycache__", ".cache", ".claude", ".git", "build", "历史",
              "edge-profile", "chrome-profile"}   # the Windows app window's browser data (data/ stays behind anyway)
SKIP_FILES = {
    Path("spt/docs/一键迁移提示词.md"),   # written for the owner's own folders
    Path("spt/settings.local.json"),
    Path("spt/settings.share.json"),
    Path("app/projects.json"),
    Path("spt/server/dashboard_sources.json"),      # the owner's own workspace location
    Path("spt/docs/验收图片"),             # old screenshots of the owner's client work
}
APP = ROOT / "native" / "build" / "SPT.app"
DITTO = Path("/usr/bin/ditto")   # macOS only: copies SPT.app into the package
# Only the shared copy gets this file; /api/health then reports share: true and the
# UI hides tools the recipient does not need. The owner's folder never has it.
SHARE_FLAG = Path("spt/settings.share.json")


def ignore(folder: str, names: list[str]) -> set[str]:
    relative = Path(folder).resolve().relative_to(ROOT)
    return {name for name in names
            if name in SKIP_NAMES or name.endswith(".pyc")
            or relative / name in SKIP_FILES}


def stage(target: Path) -> None:
    for name in INCLUDE:
        source = ROOT / name
        if source.is_dir():
            shutil.copytree(source, target / name, ignore=ignore, symlinks=True)
        elif source.is_file():
            shutil.copy2(source, target / name)
    # The owner's project list points at their own folders.
    (target / "app" / "projects.json").write_text("[]\n", encoding="utf-8")
    # Saved news and research notes are the owner's own.
    (target / "spt" / "server" / "dashboard_sources.json").write_text(
        '{"checked_at": "2026-10-27", "news": [], "research": []}\n', encoding="utf-8")
    workspace = target / "工作区"
    for section in SECTIONS:
        (workspace / section).mkdir(parents=True)
    shutil.copy2(TEMPLATES / "工作区-README.md", workspace / "README.md")
    shutil.copy2(TEMPLATES / "工作区-AGENTS.md", workspace / "AGENTS.md")
    (target / SHARE_FLAG).write_text('{"share": false}\n', encoding="utf-8")
    if APP.is_dir() and DITTO.is_file():
        subprocess.run(["/usr/bin/ditto", str(APP), str(target / "SPT.app")], check=True)


def write_zip(folder: Path, zip_path: Path) -> None:
    """folder → zip_path with the folder itself at the top (like ditto --keepParent).

    Written with zipfile on every system, not ditto: zipfile marks the Chinese names
    as UTF-8, so Windows unzips 启动SPT.bat and 使用说明.md with their real names
    (ditto's zip shows them garbled there and adds __MACOSX/). File modes (the
    executable bit of .command and the app) and links inside SPT.app are kept.
    """
    with zipfile.ZipFile(zip_path, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            name = path.relative_to(folder.parent).as_posix()
            if path.is_symlink():
                info = zipfile.ZipInfo(name)
                info.external_attr = (stat.S_IFLNK | 0o755) << 16
                archive.writestr(info, os.readlink(path))
            elif path.is_dir():
                archive.write(path, name + "/")
            else:
                archive.write(path, name)
                if path.suffix in {".command", ".sh"} or path.parent == folder / "spt/bin" \
                        or ".app/Contents/MacOS/" in name:
                    info = archive.getinfo(name)
                    info.create_system = 3
                    info.external_attr = (stat.S_IFREG | 0o755) << 16


def personal_paths(target: Path) -> list[str]:
    """Text files in the package that still mention this Mac's home folder."""
    home = str(Path.home()).encode()
    found = []
    for path in sorted(target.rglob("*")):
        if path.is_file() and not path.is_symlink() and ".app/" not in path.as_posix() \
                and path.stat().st_size < 2 * 1024 * 1024 and home in path.read_bytes():
            found.append(path.relative_to(target).as_posix())
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="打包 SPT 给别人用（只带空的工作区）")
    desktop = Path.home() / "Desktop"
    parser.add_argument("--out", type=Path, default=desktop if desktop.is_dir() else Path.home(),
                        help="zip 放在哪个文件夹，默认桌面")
    args = parser.parse_args(argv)
    if not APP.is_dir():
        print("提示：还没有 native/build/SPT.app，分享包里不会有可双击的应用。"
              "需要的话先运行 native/build.sh。", file=sys.stderr)
    out = args.out.expanduser().resolve()
    zip_path = out / f"SPT-{dt.date.today():%Y%m%d}.zip"
    if zip_path.exists():
        print(f"已经有 {zip_path}，请先移到废纸篓或改用 --out 换个位置。", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="spt-share-") as scratch:
        target = Path(scratch) / "SPT"
        target.mkdir()
        stage(target)
        leftovers = personal_paths(target)
        if leftovers:
            print("注意：这些文件里还写着本机路径（不影响使用，分享前可看一眼）：", file=sys.stderr)
            for name in leftovers:
                print("  " + name, file=sys.stderr)
        write_zip(target, zip_path)
    size = zip_path.stat().st_size / 1024 / 1024
    print(f"已生成：{zip_path}（{size:.1f} MB）")
    print("里面是空的工作区和存放说明，不含你的作品、数据库、账号和项目列表。")
    print(f"分享包里多了 {SHARE_FLAG.as_posix()}，对方的 SPT 保留通用版全部工具；你自己的文件夹不受影响。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
