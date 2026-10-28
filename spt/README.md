# SPT · 本地资产库与运营台

SPT 把你做过的东西放在一处管：作品、提示词、素材、记录、skills。每样都能预览、看说明、一键复制提示词，也能导出成一张完整的表格。运营账号、便签和发布入口也在这里。

日常从 Windows 完整版或 Mac 应用进入（见软件根目录的 README），界面入口是 `http://127.0.0.1:8766/workspace/`，同源 API 前缀为 `/api/spt`。

## 资产库

库根目录是软件里的 `工作区/` 文件夹（真实文件夹，不是链接，软件整个拷给别人也能用）。给人看的存放说明是 `工作区/README.md`，给 agent 的完整规则是 [AGENTS.md](AGENTS.md)，两份内容一致。

| 类型 | 放哪里 | 一键复制的是 |
|---|---|---|
| 作品 | `<专业>/<YYYY-MM-DD-客户-主题>/`，版本放 `V1/`、`V2/` | 各版本的 `正文.txt`、作品里的 `提示词*.md` |
| 提示词 | `提示词/<分组>/<名称>.md` | 提示词正文 |
| 素材 | `素材/<名称>.md` 素材表；`素材/<分组>/` 图片和视频 | 「写法」列；图片复制路径 |
| 记录 | `记录/<日期-主题>.md`；作品里的 `记录.md` | 全文 |
| Skills | `skills/<名字>/SKILL.md`；Claude、Codex 已安装的自动读入 | 路径 |

不想搬的目录（例如另一个笔记库的方法和提示词）写进库根目录的 `SPT.yaml`，SPT 只读收录。模板见 [templates/SPT.yaml](templates/SPT.yaml)。

界面：资产库顶部切换五种类型，下面按分组筛选，卡片右上角一键复制，点开看完整内容（Markdown 会排好版）。「导出」可选 Excel、CSV、Markdown，导出全部或只导出当前类型。

## 给 agent 用

```sh
spt/bin/spt search 小笼包 --kind prompt     # 搜索
spt/bin/spt get <id>                        # 完整内容
spt/bin/spt export --format xlsx            # 导出总表
spt/bin/spt guide                           # 打印目录规则
```

MCP（只读，stdio）：`spt/bin/spt-mcp`，工具有 `spt_guide`、`spt_search`、`spt_get`、`spt_sections`、`spt_export`、`spt_reindex`。接入方法见应用内「设置 › Agent 接入」。库内 skill 在 [skills/spt-library](skills/spt-library/SKILL.md)。

索引查询不改作品；发布执行器仅处理用户在界面明确授权的任务。新作品由 agent 按 AGENTS.md 写入或用 spt add 收录。

## 分享与迁移

- 分享给别人：运行 `spt/bin/打包分享`，在桌面生成一个 zip，只带空的工作区和存放说明，不带你的作品、账号和数据库。
- 把旧作品收进来：见根目录 [使用说明](../使用说明.md)。

## 运行与检查

独立运行：`python3 -m spt.server`，然后打开 `http://127.0.0.1:8788/`。环境变量 `SPT_WORKSPACE`、`SPT_CACHE` 可临时指向别的库和缓存；`SPT_SKIP_INSTALLED_SKILLS=1` 不读已安装的 skills。

索引不会新建、修改或移动工作区里的文件。数据库、封面缩略图和导出文件只放在 `server/.cache/`，可随时删掉重建。

```sh
python3 -m unittest spt.server.tests.test_safety spt.server.tests.test_indexer spt.server.tests.test_http spt.server.tests.test_dashboard spt.server.tests.test_library
node --test spt/ui/tests/core.test.cjs spt/ui/tests/dashboard.test.cjs spt/ui/tests/library.test.cjs
```

- [服务说明](server/README.md)
