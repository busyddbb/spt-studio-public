# SPT macOS 原生应用

原生应用在本机窗口中显示 SPT 界面，并负责按账号隔离的官方 WebKit 页面、rednote 发布执行器和适配平台的数据读取。Python 服务监听本机 `127.0.0.1:8766`。

Mac 用户优先下载 [最新 Release](https://github.com/busyddbb/spt-studio-public/releases/latest) 的 `SPT-macOS-Universal.zip`。它包含为分享版重新构建的 `SPT.app`，支持 Apple silicon 与 Intel，使用通用身份 `local.spt.studio`，不带任何账号或登录状态。

完整自动执行功能建议使用 macOS 14 或更高版本；构建脚本的部署目标是 macOS 12，较早系统上的具体功能以系统可用性检查为准。仓库和 `SPT-Universal-Source.zip` 提供源码，不含预编译应用。

## 打开 Mac 发布包

完整解压 `SPT-macOS-Universal.zip`，安装 Python 3.11+，在 SPT 根目录执行：

```sh
python3 -m pip install -r requirements.txt
```

随后双击包内 `SPT.app`，按提示选择完整的 SPT 文件夹。不要只复制应用而丢掉软件目录。发布包里的应用未经过 Apple 公证；首次打开的系统提示见下文。

## 从源码构建

使用仓库或通用源码包时，在软件根目录运行：

```sh
python3 -m pip install -r requirements.txt
xcode-select --install
./native/build.sh
open native/build/SPT.app
```

需要 Python 3.11+、`requirements.txt` 中的依赖和 macOS Command Line Tools。源码包不包含已安装依赖；应先完成依赖安装，再使用完整资产解析和封面功能。产物为 `native/build/SPT.app`，包含 Apple silicon 与 Intel 架构。默认 bundle identity 为 `local.spt.studio`；构建使用本机 ad-hoc 签名，没有 Apple 公证。

第一次打开若 macOS 提示无法验证开发者，可按系统提示，在确认来源后右键应用 →「打开」，或到「系统设置 → 隐私与安全性」处理。不要全局关闭系统安全功能。

应用能从源码目录或同级 SPT 文件夹定位服务；找不到时会让使用者选择文件夹。移动应用到其他位置后，保留完整的软件目录，首次按提示选择。关闭窗口不等于退出应用；需要后台任务继续时，保持应用、网络和电脑唤醒。

## 现有功能范围

- 资产库、搜索、便签、工作区设置、导出和 Agent 接入使用共用网页与 Python 服务。
- 平台账号页使用账号隔离的 WebKit 会话，首次由使用者手动登录。
- `PublishingQueue.swift` 与 `RednoteUpload.swift` 领取本机持久队列中的任务，自动发布范围为 rednote 图文组和单视频。
- `MetricsReader.swift` 读取 rednote、TikTok、Instagram、Facebook 已适配的官方页面可见数据。
- `PublishingQueueDOM.js` 与 `MetricsReaderDOM.js` 是页面识别及核对的共用脚本，Windows 执行器复用相同业务规则。

其他平台保留官方后台入口，不应据此声称已具备所有平台的自动发布。

## 发布队列

作品先预览，账号、媒体、正文、话题、设置和重复任务经过核对后，由本机服务授予单次提交许可。未授权时只准备草稿。页面无法识别、进程丢失或提交结果不明时保留原任务，停止自动重传。

排期由本机执行，平台定时开关保持关闭。截图、回执和状态写回原作品；原媒体保留原位。自定义视频封面需要在官方预览中核对。

## 本机桥与会话

只有本机 SPT 主页面能调用素材选择、官方账号页、队列预览等本机桥。请求只传账号、草稿、任务 ID，可信路径与媒体指纹由本机服务重新取得；外部平台页面没有本地控制桥。

登录会话由系统 WebKit 和本机存储管理，不随源码或 Release 分发。不要为分享复制自己的应用支持目录、Keychain、浏览器资料、数据库或日志。

## 验证

后端队列与接口测试位于 `tests/`；公开 DOM 的离线测试包含 `tests/native-queue-dom.test.cjs`、`tests/metrics-reader-dom.test.cjs` 和对应 Swift harness。具体发布版本的验证结果见 Release。

本地模拟与编译通过不等于真实平台端到端验收。真实账号、验证码、平台控件变化、网络和提交后的审核结果，需要按实际页面核对。
