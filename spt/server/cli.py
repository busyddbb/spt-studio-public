"""Command line for agents and people: python3 -m spt.server.cli <command>."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from . import agent, metrics_cli
from .intake import IntakeError, add_work


def output(value: object) -> None:
    json.dump(value, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="spt", description="SPT 资产库（查询只读；add 只新增文件）")
    root.add_argument("--fresh", action="store_true", help="先重建索引")
    commands = root.add_subparsers(dest="command", required=True)
    find = commands.add_parser("search", help="搜索作品/提示词/素材/记录/skills")
    find.add_argument("query", nargs="?", default="")
    find.add_argument("--kind", default="", choices=("",) + agent.KINDS)
    find.add_argument("--section", default="", help="分组，例如 衣服、运营")
    find.add_argument("--client", default="",
                      help="客户简称，例如 AK、自家：只列这个客户的作品和作品里的提示词、记录")
    find.add_argument("--limit", type=int, default=30)
    find.add_argument("--all-versions", action="store_true",
                      help="作品的旧版本提示词也列出（默认每件作品只列定稿那一版，没定稿就列最新一版）")
    show = commands.add_parser("get", help="按 id 取完整内容")
    show.add_argument("id")
    text = commands.add_parser("text", help="只打印条目的提示词/正文，便于复制")
    text.add_argument("id")
    commands.add_parser("sections", help="各类数量与分组")
    commands.add_parser("reindex", help="重建索引")
    commands.add_parser("guide", help="打印库的放置规则（AGENTS.md）")
    dump = commands.add_parser("export", help="导出完整表格")
    dump.add_argument("--format", default="xlsx", choices=("xlsx", "csv", "md"))
    dump.add_argument("--kind", default="", choices=("",) + agent.KINDS + ("metrics",),
                      help="只导出一种；metrics 是数据记录（一行一次记录）")
    dump.add_argument("--out", type=Path)
    dump.add_argument("--all-versions", action="store_true",
                      help="作品的旧版本提示词也导出")
    add = commands.add_parser("add", help="把做好的作品收进工作区（只新增，不覆盖、不删除、不动原件）")
    add.add_argument("--field", required=True, help="专业，例如 电影、运营、品牌视觉")
    add.add_argument("--client", required=True, help="客户，不能有 -；自己的作品写 自家")
    add.add_argument("--topic", required=True, help="主题")
    add.add_argument("--date", default="", help="YYYY-MM-DD，默认今天")
    add.add_argument("--title", default="", help="展示名")
    add.add_argument("--tags", default="", help="标签，逗号分隔")
    add.add_argument("--tool", default="", help="生成工具，例如 即梦 4.0、Seedance")
    add.add_argument("--note", default="", help="一句话说明")
    add.add_argument("--source", default="", help="原件所在的项目文件夹，写进 说明.md")
    add.add_argument("--final", action="append", default=[], type=Path, help="成片/成图（可多次）")
    add.add_argument("--cover", type=Path, help="封面图；不给就用第一张成图")
    add.add_argument("--prompt", action="append", default=[], type=Path, help="作品级提示词文件（可多次）")
    add.add_argument("--record", action="append", default=[], type=Path, help="制作记录；第一份存成 记录.md")
    add.add_argument("--version", action="append", default=[], type=Path, help="一个版本的文件夹，依次存成 V1、V2…")
    add.add_argument("--extra", action="append", default=[], type=Path, help="其他资料，放进 资料/")
    add.add_argument("--dry-run", action="store_true", help="只列出会做什么，不写文件")
    metrics_cli.add_parser(commands)   # spt metrics … (数据记录)
    return root


def main(argv: list[str] | None = None) -> int:
    options = parser().parse_args(argv)
    if options.command == "guide":
        print(agent.guide())
        return 0
    if options.command == "add":
        from .config import default_config
        try:
            result = add_work(default_config().resolved_workspace, options.field, options.client,
                              options.topic, options.date, options.title, options.tags, options.tool,
                              options.note, options.source, options.final, options.cover,
                              options.prompt, options.record, options.version, options.extra,
                              options.dry_run)
        except IntakeError as error:
            print(str(error), file=sys.stderr)
            return 2
        if not options.dry_run:
            agent.open_indexer(True)
        output(result)
        return 0
    indexer = agent.open_indexer(options.fresh or options.command == "reindex")
    if options.command == "metrics":
        return metrics_cli.run(options, indexer)
    if options.command == "reindex":
        health = indexer.health()
        output({key: health[key] for key in ("indexed_at", "counts", "issues")})
    elif options.command == "search":
        output(agent.search(indexer, options.query, options.kind,
                            options.section, options.limit,
                            options.all_versions, options.client))
    elif options.command in ("get", "text"):
        value = agent.get(indexer, options.id)
        if value is None:
            print("没有这个 id，先 search 一下", file=sys.stderr)
            return 1
        if options.command == "text":
            print(value.get("text") or "\n\n".join(
                version["prompt"] for version in value.get("versions", [])))
        else:
            output(value)
    elif options.command == "sections":
        output(agent.sections(indexer))
    elif options.command == "export":
        print(agent.export_file(indexer, options.format, options.kind,
                                options.out, options.all_versions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
