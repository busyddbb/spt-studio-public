#!/bin/zsh
# 双击打开 SPT。第一次如果提示无法打开：右键这个文件 › 打开。
cd -- "$(dirname -- "$0")"
for py in /opt/homebrew/bin/python3 /usr/local/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /usr/bin/python3; do
  if [[ -x $py ]] && $py -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    exec $py ./启动.py "$@"
  fi
done
print -r -- "没有找到 Python 3。请先安装：终端运行 xcode-select --install，或从 python.org 下载安装 Python 3，然后再双击本文件。"
read -k1 '?按任意键关闭…'
