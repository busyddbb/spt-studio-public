---
name: spt-library
description: 本地资产库 SPT（作品、提示词、素材、记录、skills）。要找以前做过的作品或提示词、挑衣服/场景/镜头/音乐/画质/动作素材、存新提示词或记录、整理作品文件夹、导出资产总表时用。
---

# SPT 资产库

SPT 软件根目录是本 skill 往上三级的文件夹（`spt/skills/spt-library/` 的上一级的上一级的上一级）。库在软件根目录的 `工作区/`，规则全文在 `spt/AGENTS.md`。第一次用先读那份文件，或调用 `spt_guide`。

接了 SPT 的 MCP 就优先用工具；没有就在软件根目录运行 `spt/bin/spt`：

| 要做的事 | MCP 工具 | 命令 |
|---|---|---|
| 找提示词、素材、作品 | `spt_search` | `spt/bin/spt search 关键词 [--kind prompt\|material\|record\|skill\|work] [--section 分组] [--all-versions]` |
| 取完整内容 | `spt_get` | `spt/bin/spt get <id>` |
| 只要提示词正文 | `spt_get`，看 `text` 字段 | `spt/bin/spt text <id>` |
| 看有哪些分组 | `spt_sections` | `spt/bin/spt sections` |
| 写完文件后 | `spt_reindex` | `spt/bin/spt reindex` |
| 导出总表 | `spt_export` | `spt/bin/spt export --format xlsx` |

作品里的提示词，搜索默认每件作品只给定稿那一版（没定稿就给最新一版）。要看旧版本：搜索加 `--all-versions`（MCP 传 `all_versions: true`，旧版本标 `superseded: true`），或者 `spt get <作品 id>` 看每个版本。

做事顺序：

1. 先搜，有能用的提示词或素材就在它的基础上改，不从零写。
2. 新作品建 `工作区/<专业>/<YYYY-MM-DD-客户-主题>/V1/`，提示词写 `V1/正文.txt`，过程写作品根目录的 `记录.md`。
3. 好用的提示词另存一份到 `工作区/提示词/<分组>/<名称>.md`，带 frontmatter（标题、标签、工具、说明）。
4. 新素材加到 `工作区/素材/<名称>.md` 表格末尾，编号接着往下排。
5. 写完刷新索引。

SPT 只读，不发布。发布和对外发送由用户本人确认；账号密码不进库；删除走废纸篓。
