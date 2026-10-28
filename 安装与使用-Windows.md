# Windows 安装与使用

Windows 下载 `SPT-Windows-Portable.zip`；Mac 用户请改用 `SPT-macOS-Universal.zip`，通用源码位于 `SPT-Universal-Source.zip`。

适用于 Windows 10 / 11。完整功能包括资产库、便签、账号管理、rednote 自动发布与排期，以及已适配平台的数据读取。所有账号由你在本机登录，下载包不含他人的账号或登录状态。

## 1. 下载与安装

1. 到 [最新 Release](https://github.com/busyddbb/spt-studio-public/releases/latest) 下载 **`SPT-Windows-Portable.zip`**。
2. 右键 ZIP →「全部解压」，把整个 SPT 文件夹放到普通可写目录，例如 `D:\SPT` 或你的「文档」文件夹。不要拆散内部文件，不要直接在 ZIP 中运行。
3. 安装 [Python 3.11 或更高版本](https://www.python.org/downloads/windows/)，选择适合电脑的 64 位版本，勾选 **Add python.exe to PATH**。
4. 双击 **`安装Windows.bat`**。脚本会在软件目录中建立 `.venv`，安装依赖并下载隔离的 Chromium；首次安装需要联网。

如果需要手工安装，在 SPT 文件夹的地址栏输入 `cmd` 并回车，依次运行：

```bat
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-windows.txt
.venv\Scripts\python -m playwright install chromium
```

资产库本身不需要第三方云服务订阅，也不需要 SPT 账号。

## 2. 启动

双击 **`启动SPT.bat`**。程序会启动本机服务和 Windows 浏览器执行器，打开 SPT 界面。浏览器运行时由安装脚本准备；若提示依赖缺失，先重新运行 `安装Windows.bat`。

本机界面地址为：

```text
http://127.0.0.1:8766/workspace/
```

不要双击 `spt/ui/index.html`，它不能代替后台服务。

打开普通浏览器访问本机地址可查看资产库；自动发布、平台账号页和读数需要 Windows 执行器仍在运行。首次启动后可使用程序创建的桌面快捷方式。

关闭 SPT 界面只关闭窗口，后台执行器仍会处理排期、发布和读数。需要结束后台时，双击 **`停止SPT后台.bat`**；它会停止 Windows 执行器，本机网页服务可以继续运行。也可以在软件根目录执行：

```bat
.venv\Scripts\python -m windows.runtime --stop
```

执行器日志在 `data/windows-runtime.log`，服务日志在 `data/server.log`。

## 3. 放入第一件作品

在 `工作区` 中按以下结构新建文件夹：

```text
工作区/
└── 电影/
    └── 2026-10-27-自家-雨夜重逢/
        ├── 成片.mp4
        ├── 封面.jpg
        ├── 提示词.md
        └── 记录.md
```

作品文件夹必须按 `日期-客户-主题` 命名，自己的作品可以用「自家」。可复用提示词放进 `工作区\提示词\分组\名称.md`；图片素材放进 `工作区\素材\分组\`。放好后点界面的「刷新」。完整规则见 [工作区说明](工作区/README.md)。

已有作品也能用命令收录，先预览再正式执行：

```bat
.venv\Scripts\python -m spt.server.cli add --field 电影 --client 自家 --topic 雨夜重逢 --final "D:\我的作品\成片.mp4" --cover "D:\我的作品\封面.jpg" --dry-run
```

确认结果后去掉 `--dry-run` 再运行。收录只新增，不移动、不覆盖原文件。

## 4. 添加账号与首次登录

1. 打开「设置 → 账号与数据」，添加自己的账号档案，准确填写平台和账号名称。
2. 在「发布 → 平台入口」打开对应的官方后台。
3. 在官方页面手动完成登录、验证码等要求，确认当前账号正确。

每个账号使用独立的本机浏览器资料，保存在 `data/windows/`。SPT 资产库无需平台登录；自动发布和读数使用你自己刚完成的本机会话。不要把 `data/`、浏览器资料或本机配置提交到 GitHub，也不要发给别人。

## 5. 自动发布与排期

当前自动发布范围与 macOS 版一致：**rednote 图文组和单视频**。其他平台从官方后台入口操作。

1. 给作品准备 `发布标题.txt`、`发布正文.txt`、`发布话题.txt` 和按顺序的成品。第一张图作为图文封面；作品展示用的根目录封面不应重复上传为正文图片。
2. 在资产库打开作品，点「发布」，检查媒体顺序、标题、正文、话题和目标账号。
3. 选择立即执行或排期。只有明确授权该次后台自动提交，队列才会走到提交；未授权时只准备草稿。
4. 到「发布队列」查看进度。需要处理登录或检查原页面时，打开该任务的预览；取消操作也在原任务中完成。
5. 查看发布结果和写回作品的 `发布记录.md`、回执及截图。

自动发布不等于授权未来所有内容。每次任务都需按界面确认；程序在媒体、正文、话题、账号或结果无法核对时停止。上传完成、审核中、已发布是不同状态。

排期由本机执行。电脑需保持开机、联网、不睡眠，Windows 执行器不能退出。平台自身的定时发布选项不与本机排期同时开启。进程中断、平台提示异常或提交后结果不明时，先检查原任务和官方后台，不要重新建任务重发。

## 6. 读取与整理数据

已适配 **rednote、TikTok、Instagram、Facebook** 的数据读取。先在本机官方后台完成对应账号登录，再到「数据」点「读数据」。登录失效或账号不匹配时，按提示返回原账号页面处理。

程序从公开页面可见信息读取，不把未知值写成 0。可匹配的发布数据记到作品的 `数据/表现.csv`；作品有发布时间时，可计算 D1 / D3 / D7 节点。未匹配到的内容或不支持的平台，可以导入官方导出的 CSV，或手动记录真实数字。

程序运行时会按服务的间隔安排自动读数。读数需要执行器可用、网络正常，以及平台允许当前会话访问。

## 7. 命令行与 AI 接入

在 SPT 根目录运行；Windows 不使用 `spt/bin/spt` 这个 shell 脚本：

```bat
.venv\Scripts\python -m spt.server.cli search 夜景
.venv\Scripts\python -m spt.server.cli sections
.venv\Scripts\python -m spt.server.cli reindex
.venv\Scripts\python -m spt.server.cli add --help
.venv\Scripts\python -m spt.server.cli metrics --help
```

MCP 使用 `spt.server.mcp_server` 模块，并把工作目录设为 SPT 根目录：

```bat
.venv\Scripts\python -m spt.server.mcp_server
```

让 Claude、Codex 先读 `工作区/AGENTS.md` 和 `spt/AGENTS.md`。AI 生成的作品、提示词和记录留在自己的工作区，账号密码不写进资料文件。

## 8. 封面、备份和升级

`安装Windows.bat` 会一并安装 YAML 解析、图片缩略图、视频截帧和浏览器自动化所需的依赖，不需要另行安装系统 ffmpeg。源码包本身不包含已安装依赖，缺少依赖会影响相关完整功能。作品也可以直接使用你准备的 `封面.jpg`。

升级前先退出 SPT，备份自己的 `工作区/`、`data/` 和 `spt/settings.local.json`（若存在）。新版本解压到新目录后，按实际路径恢复资料，不覆盖正在运行的文件。工作区若放在外接盘或其他位置，仍需单独备份那个目录。

`data/` 中可能有本机登录资料，仅限自己的电脑安全保管。换电脑请重新登录平台；不要通过公开压缩包或 GitHub 迁移会话。

## 9. 常见问题

| 情况 | 处理 |
|---|---|
| 提示找不到 Python | 重新安装 Python 并勾选 PATH；重新打开命令行，运行 `py -3 --version` |
| 缺少 Playwright 或浏览器 | 重新运行 `安装Windows.bat`；查看安装窗口中的错误 |
| 黑窗口一闪而过或界面没开 | 在 SPT 文件夹打开命令行执行 `.venv\Scripts\python 启动.py`，保留显示的错误；检查 `data/windows-runtime.log` 和 `data/server.log` |
| 提示端口 8766 被占用 | 检查是否已经有一份 SPT 在运行，先使用原窗口；避免同时运行两份不同目录的软件 |
| 资产库能用，但自动发布或读数无反应 | 确认通过 `启动SPT.bat` 启动，Windows 执行器未退出，再查看原队列的错误信息 |
| 平台要求重新登录或验证码 | 在 SPT 的对应官方账号页手动完成，然后检查原任务；不要反复重新入队 |
| 文件没出现 | 点「刷新」，检查文件夹名和「设置 → 资产库」列出的原因 |
| 左栏没有数据、情报或发布 | 在「设置 → 账号与数据」添加账号或导入资料，这些页面按实际内容显示 |
| 视频没封面 | 重新运行 `安装Windows.bat` 确保依赖齐全，再刷新；也可以手动放 `封面.jpg` |

## 10. 验证范围

发布包的安装验证、Windows CI 和本地测试结果以对应 Release 为准。模拟平台页面能验证浏览器执行流程、队列和字段核对；它不能证明真实平台页面、账号风控、验证码和当前网络已验收。真实发布前，使用自己的测试内容核对一遍完整流程。
