# AI 使用入口

默认数据和操作在本地，CLI 与 MCP 共用 SQLite 数据库。默认读真实数据；演示必须显式指定。没有可触发外部平台发布或广告花费的工具。

## CLI

读取真实工作台：

```bash
python3 app/cli.py state
```

读取有证据的规则观察：

```bash
python3 app/cli.py analyze --account-id ACCOUNT_ID
```

导入数据：

```bash
python3 app/cli.py import_metrics --kind social --csv-file /绝对路径/内容数据.csv
```

创建草稿的 JSON 参数文件：

```json
{
  "title": "同一素材的两个开头",
  "body": "通用主稿，供尚未单独改写的平台使用。",
  "platform_variants": {
    "instagram": "Instagram 的独立正文。",
    "tiktok": "TikTok 的独立正文。"
  },
  "account_ids": ["用 state 返回的真实账号 ID"],
  "media_ids": ["用 list_media 返回的本地素材 ID"],
  "scheduled_at": "2026-10-20T09:00:00-07:00"
}
```

```bash
python3 app/cli.py create_draft --input-file /绝对路径/草稿.json
```

可以用 `--input-file -` 读取标准输入。失败返回 `{"error":"原因"}` 并以非0状态退出。账号档案使用 `create_account`，参数为 platform/name/handle/brand/notes。平台 ID：instagram、facebook、tiktok、youtube、google_business、google_ads、xiaohongshu。

`create_draft` / `update_draft` 的 CLI、MCP 和 HTTP 入口均支持 `platform_variants`，默认 `{}`。键使用上述平台 ID（排除 `google_ads`），值必须是字符串，每平台最多 30000 字。未选为当前目标的平台版本也会保留；空字符串表示沿用 `body`。更新时省略该字段会保留原版本，传入对象会整体替换，传 `{}` 会清除所有平台版本。读取及导出会带回此字段，旧草稿自动补空对象。

修改或删除已批准的平台版本会将该草稿退回 `review`，需重新检查后再批准。不能在同一次请求中修改版本并设置 `status: approved`；此类请求会被拒绝且不覆盖原稿。AI 应先读取现有版本，合并本次改写后完整回写，避免误删其他平台正文。

## MCP

本地 stdio 入口：

```toml
[mcp_servers.media_workspace]
command = "/opt/homebrew/bin/python3"
args = ["<SPT 文件夹>/app/mcp_server.py"]
```

本次提供并验证入口，未擅自修改 Codex 全局配置。也可以直接由 Codex 使用 CLI，无需启动网页服务。

目前共 **23 个工具**。原有 12 个工具：list_media、register_media、get_overview、list_accounts、get_content_metrics、analyze_metrics、create_account、create_draft、update_draft、import_metrics_csv、export_drafts、get_product_research。新增 11 个内容计划工具见下表。

建议给 AI 的指令：

> 读取本地多媒体工作台的真实账号和最新数据，按同一平台分别比较。列出依据、样本量和采集时间，再为我指定的账号起草下一批内容。不要把演示数值、空值、已批准草稿或本地排期当作真实运营结果。

## 按账号使用内容计划

内容计划参考[公开帖的方法结构](https://x.com/JessiCao_JC/status/2110614414890283326)：账号定位、真实问题、12 篇内容、每 4 篇复盘、追问进入下一批。全部读写都需要真实的 `account_id`，不同账号分别保存。

| 新工具 / CLI 动作 | 参数与结果 |
| --- | --- |
| `planning_workspace` | `{account_id}`；返回 `strategy`、`questions`、`batches[].cards`、`observations` 和参考来源。 |
| `save_strategy` | `{account_id,audience,scenario,problem,materials,pillars}`；`pillars` 必须是 3 个非空且不同的栏目名称。 |
| `add_question` | 必填 `{account_id,question,context,source_type}`；可填 `source_url`、`source_note`、`pillar`、`materials`、`material_ready`、`priority`、`status`。 |
| `update_question` | `{id,account_id,...要改的字段}`；编辑或搁置问题，不改写已生成计划卡的快照。 |
| `create_batch` | `{account_id,name?,question_ids?}`；返回含 12 张 `cards` 的 `batch`。需先保存定位。 |
| `update_plan_item` | `{id,account_id,...要改的字段}`；可写 `question_id`、`content_type`、`pillar`、`title`、`material_plan`、`material_ready`、`reader_action`、`expected_feedback`、`variable`、`body`、`media_ids`。 |
| `create_plan_draft` | `{id,account_id}`；返回 `card`、`draft`、`reused`、`draft_sync_status`。同一计划卡再次调用会复用既有草稿。 |
| `observe_plan_item` | 必填 `{id,account_id,post_url,published_at,observed_at}`；可填 `views`、`impressions`、`saves`、`comments`、`follows`、`production_minutes`、`reader_question`、`next_answer`、`next_materials`、`note`。 |
| `review_batch` | `{batch_id,account_id,group}`，`group` 为 1、2 或 3；返回本组 4 篇的最新观察、缺失篇号、窗口时长和可计算的收藏率。 |
| `promote_feedback` | `{observation_id,account_id}`；从追问生成新问题并保留来源，多次调用不会重复创建。 |
| `export_content_plan` | `{batch_id,account_id}`；导出定位、问题来源、该批计划卡和观察历史的本地 JSON 交接包。 |

其中 `id` 在 `update_question` 中是问题 ID，在 `update_plan_item`、`create_plan_draft`、`observe_plan_item` 中是计划卡 ID。不要把这些参数写成 `item_id` 或 `question_id`；`update_plan_item.question_id` 专门用于关联一个已有问题。

推荐执行顺序：

1. 用 `list_accounts` 找到用户指定账号，再读 `planning_workspace`；缺定位时，把用户提供或已确认的受众、场景、问题、材料和 3 个栏目写入 `save_strategy`。
2. 用 `add_question` 保存真实搜索问题、评论或工作记录及上下文。`source_type` 为 `search/comment/work_record/other`；优先级 `1` 高、`2` 中、`3` 低。`material_ready` 只能在材料确实齐备时设为 `true`。
3. 调用 `create_batch`。默认优先使用有材料且优先级高的待选问题；只选 `inbox`，入批后标为 `selected`，`parked` 表示已搁置。默认下一批跳过已用问题；显式传 `question_ids` 可有意复用。框架固定为 3 篇方法、4 篇案例、3 篇过程、2 篇模板，分成 3 组，每组 4 篇。问题不足就保留空卡，不生成虚构问题或案例。
4. AI 读取定位、问题上下文、材料和计划卡，通过 `update_plan_item` 回写用户所需的标题、正文、读者行动、预期反馈和单个观察变量。`content_type` 为 `method/case/process/template`。用 `register_media` 登记已有素材后，把真实 `media_ids` 关联到计划卡；不要根据文件名假称已看过素材。
5. 标题、正文、真实问题关联和材料计划齐备后，调用 `create_plan_draft` 形成待审核草稿。材料尚缺时可以保存本地草稿，卡片的 `material_gap` 仍会提示。之后修改计划不会覆盖原草稿：`draft_sync_status` 为 `changed` 时需明确检查并通过原有 `update_draft` 编辑草稿，遵守原有审核流程。
6. 用户实际发布并提供数据后，调用 `observe_plan_item` 记录。`post_url` 无法提供时传空字符串；发布时间、采集时间必须真实且采集不早于发布。阅读、曝光、收藏、评论、涨粉为非负整数，制作分钟可用小数。未知指标传 `null` 或省略；不要填 0 代替未知。每次记录保留历史。
7. 每组 4 篇可调用 `review_batch`；不足 4 篇也可以查看。只使用每篇最新采集时间的观察，阅读/播放与曝光不混用。收藏率只在阅读/播放量大于 0 且收藏数已知时计算。至少 2 篇有记录且观察窗口最大差不超过 1 小时，才标记窗口接近；始终按计划顺序展示，不自动排名、不推断因果。
8. 观察里已有真实 `reader_question`、具体 `next_answer`、所需 `next_materials` 后，调用 `promote_feedback`。新问题带原问题及观察记录来源，进入 `inbox`，材料默认为尚未齐备。完成本批后用 `export_content_plan` 导出交接包。

`ai_mode` 固定为 `structured_local`：工作台提供结构化上下文与可回写操作，`create_batch` 本身没有调用外部 AI 模型。当前协作的 AI 可以通过 CLI 或已配置的 MCP 阅读这些上下文、起草并回写；这不代表工作台已经接通某个外部模型账号。来源、案例、结果仍须来自用户材料。人工观察只是手工记录，不是平台回执；导出包中的 `delivery: local_only`、`published: false` 也不会被转换成已发布状态。

CLI 示例（`ACCOUNT_ID`、`CARD_ID`、`BATCH_ID` 都要替换为实际返回的 ID）：

```bash
python3 app/cli.py planning_workspace --account-id ACCOUNT_ID
python3 app/cli.py save_strategy --input-file /绝对路径/账号定位.json
python3 app/cli.py create_batch --input-file /绝对路径/批次参数.json
python3 app/cli.py update_plan_item --input-file /绝对路径/计划卡正文.json
python3 app/cli.py export_content_plan --input-file /绝对路径/导出参数.json
```

其中批次参数文件最少为 `{"account_id":"ACCOUNT_ID"}`；导出参数最少为 `{"account_id":"ACCOUNT_ID","batch_id":"BATCH_ID"}`。计划卡正文文件格式如下，内容应使用当前账号已核实的材料：

```json
{
  "id": "CARD_ID",
  "account_id": "ACCOUNT_ID",
  "title": "基于该卡真实问题写出的标题",
  "body": "基于用户材料完成的具体正文",
  "material_plan": "本篇实际要使用的材料及缺口",
  "material_ready": false,
  "reader_action": "希望读者完成的一项具体行动",
  "expected_feedback": "本篇要观察的读者回应",
  "variable": "本篇只改变的一项因素"
}
```

## HTTP API

本机服务 `http://127.0.0.1:8766`：

- GET `/api/state?dataset=real&account_id=...`：账号、最新快照、摘要、草稿；account_id 可省略。
- GET `/api/research`：选型证据；GET `/api/template?kind=social`：空白模板（ads 为广告模板）。
- POST `/api/accounts`：创建账号；PATCH `/api/accounts/ID`：修改显示名、品牌和备注。
- POST `/api/drafts`：创建草稿；PATCH `/api/drafts/ID`：编辑或改变本地审核状态。
- POST `/api/import`：`{kind,csv_text,filename}`，原子校验后入库。
- POST `/api/analyze`：`{dataset,account_id?}`，规则观察。
- GET `/api/export/drafts`：JSON 交接包。
- GET `/api/planning?account_id=ACCOUNT_ID`：读取该账号的完整内容计划工作区。
- POST `/api/planning/action`：`{"action":"动作名称","arguments":{"account_id":"ACCOUNT_ID",...}}`；动作可使用上述新增工具表中除 `export_content_plan` 外的名称，字段与工具一致。
- GET `/api/planning/export?account_id=ACCOUNT_ID&batch_id=BATCH_ID`：下载该账号、该批次的内容计划 JSON 交接包。

写操作需 `Content-Type: application/json`。跨站写入被拒绝；服务不监听公网。


## 本地素材

`register_media` 参数为 `{"paths":["/本机绝对路径/视频.mp4"]}`；只登记位置，不复制或外传。`list_media` 读取素材状态；两者已提供 CLI 和 MCP。草稿 create/update 接受 `media_ids`；同一个 ID 可给多个账号、草稿复用。更改素材会撤回批准。导出交接包含 `media_assets` 的文件引用，不包含视频二进制。

HTTP：

- GET `/api/media`：素材、状态、服务是否保存密钥，不返回密钥。
- POST `/api/media/register`：`{paths:[...]}`。
- POST `/api/media/local/init`：`{name,size}`，浏览器回退分块会话。
- POST `/api/media/local/ID/chunk`：二进制 `application/octet-stream`，`X-Upload-Offset` 指定起始字节，每块最多 4 MiB。
- POST `/api/media/local/ID/finish`、`/discard`：完成接收或清理未完成临时文件。
- POST `/api/media/provider`：`{api_key}`，仅保存本机；空字符串清除。不要把密钥放聊天、URL或日志。
- POST `/api/media/action`：`{id,action:"start"|"retry"|"cancel"}`。start/retry 在凭据存在时会外传指定素材，需真实用户意图，不能当纯本地操作。

CLI `media_action` 使用相同参数，但需先启动常驻服务执行队列；本地 MCP 未暴露外传动作。无凭据进入 waiting_credentials；保存凭据不会自动开始。`uploaded_to_provider` 不是已发布；实际平台发布仍未实现。Postiz 接口仅经本机模拟服务验证，未使用真实账号测试。
