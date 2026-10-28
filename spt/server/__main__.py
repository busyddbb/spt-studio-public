"""Run the workspace module alongside existing publishing services."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

from .api import Server
from .config import Config, default_config
from .indexer import Indexer
from .watcher import Watcher


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SPT 资产库只读索引服务")
    parser.add_argument("--workspace", type=Path, help="显式指定只读作品根目录")
    parser.add_argument("--port", type=int, default=8788, help="本机端口，默认8788")
    parser.add_argument("--reindex-only", action="store_true", help="重建索引后退出")
    return parser.parse_args()


def main() -> None:
    options = arguments()
    if not 1 <= options.port <= 65535:
        raise SystemExit("端口必须在1至65535之间")
    if options.workspace:
        # Same as SPT_WORKSPACE: 设置 shows it as fixed by the launch command instead of offering to change it.
        os.environ["SPT_WORKSPACE"] = str(options.workspace.expanduser())
    base = default_config(options.port)
    config = Config(options.workspace or base.workspace, base.cache,
                    base.ui, options.port, base.skill_roots)
    indexer = Indexer(config)
    result = indexer.reindex()
    if options.reindex_only:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    Watcher(indexer).start()
    with Server(indexer) as server:
        print(f"SPT：http://127.0.0.1:{options.port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
