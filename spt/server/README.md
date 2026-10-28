# SPT 资产库服务

日常使用的应用入口是 `http://127.0.0.1:8766/workspace/`，由现有应用服务同源挂载新界面和 `/api/spt`。原编辑与账号发布台保留在 `/legacy/`，可往返新首页；没有重装原生组件或替换已有登录存储。

如需独立运行，在软件根目录（`spt/` 的上一级）运行：

```sh
python3 -m spt.server
```

打开 `http://127.0.0.1:8788/`。同一个服务提供 `spt/ui/` 与 API，默认读取软件里的 `工作区/` 文件夹。不会自动寻找其他作品库。独立 8788 模式的 API 前缀为 `/api`，不具备应用的原生发布桥接；账号登录与上传发布从「多媒体」应用中的旧发布台操作。

显式覆盖只读根目录或仅重建索引：

```sh
python3 -m spt.server --workspace 工作区 --reindex-only
```

缓存只在本目录 `.cache/`；其中 `index.sqlite3` 可删除，重新启动或 `POST /api/reindex` 会重建。源作品不增、改、移；视频不复制，文件传输每次最多读取 64 KiB。

`GET /api/items`、`/api/library`、`/api/health` 的 counts 与 `/api/export` 里，作品的 `V*/正文.txt` 每件作品只算一份：发布记录/发布包写明的定稿版本（文件夹在时），否则数字最大的 V 版本；`段NN/` 每段都算，根目录 `提示词*.md` 一直列出。其他版本的条目留在索引里（`item_versions` 表），带 `version` 与 `superseded: true`，`/api/items/<id>` 照样能取；加 `?all_versions=1` 就一起列出和计数。`/api/library` 每类另给 `superseded`（旧版本条数）。`/api/works/<id>` 详情始终给出全部版本。

`GET /api/works` 返回 `{works: [...]}`，详情、封面、文件与 SSE 沿用原契约。`GET /api/dashboard` 只读汇总现有项目中的账号档案、内容记录、指标快照、资料来源与情报；其 `accounts` 和 `posts` 是运营首页的数据来源。独立服务的 `/api/accounts`、`/api/jobs`、`/api/agents` 仍返回各自空集合，本次未新增账号 worker、上传 worker 或自动发布服务。

运营资料中的 `historical` 表示源文件保留的历史采样：粉丝、浏览等显示实际采样日期，未知数值为 `null`；原文圆整数值只供文字展示。Post 按 D1/D3/D7 分开指标及对应采样时间，默认节点的日期不替代其他节点；历史快照也不当作每日增长。`as_of` 是汇总时间，不是实时采样时间。来源称已发布与平台当次核验分开，撤回/删除内容保留在 `history_posts`。情报附来源与日期，并将过期线索标为历史。能力边界见 `/api/health` 与 dashboard 的 `capabilities`。

详情把最新编辑版本与有明确依据的当前采用版本分开。平台核验来自文件记录，`verification_source=file`；并非本次实时访问平台。当前记录含 SHA-256 时，仅对不超过 64 MiB 的本地成品做流式摘要比较，较大文件保留 `not_checked`。没有封面且存在成品时，调用本机 `ffmpeg` 缓存单帧；缺少 ffmpeg 或抽帧失败会保留问题说明。

`spt.yaml` 是可选的人工只读配置，支持 `title/category/cover/ignore`，读取需要 PyYAML。`cover` 必须是作品内图片。服务不创建或修改该文件。无配置时只用 Python 3.11+ 标准库；不需要 watchdog。

文件 API 支持 GET、HEAD、单个 Range 与 416。配置的工作区根在启动时解析一次；其下目录不能通过符号链接替换作品根。读取以 `dir_fd/O_NOFOLLOW` 打开并保留文件 descriptor；路径变化不会令流读取跳到作品外。缓存根、子目录、数据库、SQLite sidecar 与缩略图输出拒绝符号链接，文件输出也拒绝硬链接。

Host/Origin 仅接受本机同端口；无跨源访问。界面通过部署时指定的 API 前缀统一请求 JSON、SSE 和媒体，不跳转到另一端口。文件错误为中文 JSON。外部归档只在详情中作为引用保留，不能经文件 API 访问。

隔离验收：

```sh
python3 -m unittest discover -s spt/server/tests -t . -v
```

所有夹具位于系统临时目录；不会写入真实工作区。覆盖状态推导、当前/撤回记录、文案边界、未知时间、删库一致性、源文件不变、Range/HEAD、Host/Origin，以及链接替换的读写边界。

新界面为黑紫深灰面板与适量玻璃导航；支持减少透明、减少动态及窄屏布局。作品库原有搜索、版本、提示词完整复制、媒体和历史记录功能保留。前端检查：`node --test spt/ui/tests/*.test.cjs`。
