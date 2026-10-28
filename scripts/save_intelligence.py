#!/usr/bin/env python3
"""先校验，再把草稿原子地换成 spt/server/dashboard_sources.json。

用法：python3 scripts/save_intelligence.py <草稿.json>

校验不通过：打印第一处问题，退出码 1，正式文件不动。
通过：旧文件备份到 spt/server/.cache/sources-history/，草稿整理后写到正式文件
同目录的临时文件，再 os.replace 换上去，所以正式文件任何时刻都是完整的 JSON。
环境变量 SPT_INTEL_TARGET 可以指定别的目标文件（测试用）。
"""
from __future__ import annotations
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # 软件根目录
TARGET = Path(os.environ.get("SPT_INTEL_TARGET")
              or ROOT / "spt/server/dashboard_sources.json")
VALIDATOR = ROOT / "spt/server/tools/validate_sources.py"
HISTORY = TARGET.parent / ".cache" / "sources-history"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("用法：python3 save_sources.py <草稿.json>", file=sys.stderr)
        return 2
    draft = Path(argv[0])
    if draft.exists() and draft.resolve() == TARGET.resolve():
        print("草稿不能就是正式文件：先复制一份到 spt/server/.cache/ 再改",
              file=sys.stderr)
        return 2
    check = subprocess.run([sys.executable, "-I", str(VALIDATOR), str(draft)],
                           capture_output=True, text=True)
    sys.stdout.write(check.stdout)
    sys.stderr.write(check.stderr)
    if check.returncode:
        return check.returncode
    data = json.loads(draft.read_text(encoding="utf-8-sig"))
    if TARGET.exists():
        HISTORY.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(TARGET, HISTORY / f"dashboard_sources.{stamp}.json")
    temp = TARGET.with_name(TARGET.name + f".tmp-{os.getpid()}")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    os.replace(temp, TARGET)
    print(f"已写入：{TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
