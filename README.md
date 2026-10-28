# SPT Studio · 本地资产库与运营台

把作品、提示词、素材、便签、发布记录和数据放在自己的电脑上管理。文件就是资料，SPT 负责搜索、预览、整理、发布队列和复盘。

**Windows 用户先看 [Windows 安装与使用](安装与使用-Windows.md)。** 下载 [最新发布包](https://github.com/busyddbb/spt-studio-public/releases/latest)，选择 `SPT-Windows-Portable.zip`，完整解压后按说明安装、启动。

仓库和发布包从空资料库开始，不带任何人的账号、密码、登录状态、作品或运营数据。使用资产库无需注册 SPT 账号；要操作平台时，由你在本机官方页面登录自己的账号。详见 [分享与隐私](docs/分享与隐私.md)。

## 功能

| 功能 | Windows | macOS |
|---|---|---|
| 作品、提示词、素材、Skills 的搜索、预览、复制与导出 | 支持 | 支持 |
| 便签看板、日历、客户整理、工作区设置 | 支持 | 支持 |
| 账号档案、官方后台、独立本机会话 | Playwright 浏览器运行时 | 原生 WebKit 应用 |
| rednote 图文及单视频自动发布、排期、原任务预览和取消 | 支持 Windows 执行器 | 支持原生执行器 |
| rednote、TikTok、Instagram、Facebook 读数据 | 支持 Windows 读数器 | 支持原生读数器 |
| 发布记录、数据导入、走势与复盘 | 支持 | 支持 |
| Claude、Codex 的 CLI / MCP 接入 | 支持 | 支持 |

自动发布要先预览作品并授权该次任务。其他平台保留官方后台操作入口；它们不在当前自动发布适配范围内。排期在本机执行，运行时需保持开启、联网，电脑不能睡眠。平台页面发生变化或结果不明时，程序会停下等待核对。

## Windows 快速开始

1. 安装 [Python](https://www.python.org/downloads/windows/) 3.11 或更高版本，勾选 **Add python.exe to PATH**。
2. 把发布包完整解压到普通可写目录，例如 `D:\SPT`。不要直接在 ZIP 中启动，也不要放进 `Program Files`。
3. 双击 **`安装Windows.bat`**，它会建立本机依赖环境并安装 Chromium；完成后双击 **`启动SPT.bat`**。
4. 在「资产库」加入自己的作品；需要发布和读数时，先添加账号档案，并在 SPT 打开的官方后台登录。

这是 Python 便携源码版，需要本机 Python；不是免环境 `.exe` 安装器。

## macOS 快速开始

1. 下载 [最新 Release](https://github.com/busyddbb/spt-studio-public/releases/latest) 的 **`SPT-macOS-Universal.zip`**，完整解压并保留整个 SPT 文件夹。
2. 安装 Python 3.11 或更高版本，在解压后的 SPT 根目录安装依赖：

```sh
python3 -m pip install -r requirements.txt
```

3. 双击包内 **`SPT.app`**，首次按提示选择完整的 SPT 文件夹。完整自动执行功能建议使用 macOS 14 或更高版本。

Mac 包中的应用是为分享版重新构建的 Apple silicon / Intel 通用应用，使用 `local.spt.studio` 身份，不附带登录状态。它使用本机签名，没有 Apple 公证；首次打开按 [Mac 应用说明](native/README.md) 处理系统提示。

需要自行构建时下载 `SPT-Universal-Source.zip`，先安装依赖，再运行：

```sh
xcode-select --install
./native/build.sh
open native/build/SPT.app
```

通用源码包不含预编译 `.app` 或已安装依赖；只打开资产库也可运行 `启动SPT.command`。

## 资料放哪里

资料默认在 `工作区/`，也可以在「设置 → 工作区」选择专用文件夹。

```text
工作区/
├── 电影/2026-10-27-自家-雨夜重逢/
│   ├── 成片.mp4、封面.jpg
│   ├── 提示词.md、记录.md
│   └── V1/、V2/
├── 提示词/分组/名称.md
├── 素材/
├── 记录/
├── 便签/
└── skills/
```

[使用说明](使用说明.md) 包含作品收录、账号、发布、读数据、备份升级和 AI 接入；[工作区存放说明](工作区/README.md) 介绍文件命名。

## 运行与验证说明

Windows 与 macOS 共用界面、资产索引和持久发布队列，使用各自的浏览器执行器。安装和自动化验证状态以具体 Release 的说明及仓库检查结果为准。本地测试、模拟页面或 CI 通过，不代表每个平台的真实账号、网络和页面都已完成端到端验证。

平台可能要求重新登录、验证码或人工确认。首次使用自动发布前，请先用自己的测试内容核对账号、媒体顺序、标题、正文、话题与可见范围；已经提交但结果不明时，先在原任务和官方后台核对，避免重复发布。

## 目录

| 位置 | 内容 |
|---|---|
| `工作区/` | 你自己的作品和资料 |
| `app/` | 本机服务、发布数据和持久队列 |
| `spt/` | 界面、资产索引、CLI、MCP 和存放规则 |
| `windows/` | Windows 浏览器运行时、发布和读数执行器 |
| `native/` | macOS 原生应用源码 |
| `data/` | 首次运行后生成的本机数据与浏览器资料，不随发布包分发 |
| `docs/` | 通用说明和数据模板 |
