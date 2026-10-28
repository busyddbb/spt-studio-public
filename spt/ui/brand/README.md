# SPT Studio 标志

**一句话：** 一张折了角的便签纸，也是一只小幽灵。资产、便签都收在它身上，夜里也帮你看着。

## 文件

| 文件 | 用在哪 |
|---|---|
| `spt-symbol.svg` | 主标志，深色底（夜灯主题）用 |
| `spt-symbol-light.svg` | 浅色底（白天主题）用，颜色稍深一点 |
| `spt-symbol-black.svg` / `spt-symbol-white.svg` | 单色：黑白打印、印章、刻字 |
| `spt-symbol-mono.svg` | 跟随文字颜色（`currentColor`），放进界面时用 |
| `spt-symbol-small.svg` / `spt-symbol-small-black.svg` | 32 px 以下专用：眼睛更大、去掉腮红、折角更大 |
| `spt-app-icon.svg` / `spt-app-icon-small.svg` | 应用图标（圆角方块），小尺寸用 small |
| `spt-lockup-dark.svg` / `spt-lockup-light.svg` | 标志 + 「spt STUDIO」字标，深色 / 浅色底 |
| `spt-lockup-black.svg` / `spt-lockup-white.svg` | 单色组合 |
| `spt-wordmark.svg` | 只有字标，跟随文字颜色 |
| `favicon-32.png`、`apple-touch-icon.png` | 浏览器标签、手机主屏 |

PNG 和 Mac 的 `native/SPT.icns` 都是从这些 SVG 生成的，改了 SVG 后在软件根目录运行：

```sh
swift native/make-icon.swift <输出文件夹>
iconutil -c icns <输出文件夹>/SPT.iconset -o native/SPT.icns
```

Windows 的 `native/SPT.ico`（16、32、48、256 px，桌面快捷方式「SPT」用它）也是从 `spt-app-icon.svg`（32 px 以下用 `spt-app-icon-small.svg`）生成的：按这几个尺寸几乎满幅画成 PNG，再用 Pillow 存成一个 .ico。运行时不需要 Pillow。

## 颜色

| 名字 | 色值 | 用途 |
|---|---|---|
| 薰衣草 | `#c9b8ff` | 幽灵身体（深色底） |
| 深薰衣草 | `#a58cf2` | 折角 |
| 白天薰衣草 | `#b39cfb` / 折角 `#8f73e8` | 浅色底时的身体和折角 |
| 夜色 | `#1e1b2e` | 眼睛、应用图标底色 |
| 腮红 | `#ff9ec4` | 只在 32 px 以上出现 |

## 规矩

- 四周至少留出一只眼睛宽的空白。
- 最小尺寸：屏幕上 16 px（用 small 版），印刷 6 mm。
- 不要拉伸、旋转、加描边、阴影或渐变；不要把折角挪到别的角。
- 照片或花底上放不清楚时，用应用图标（带深色方块）那一版。
- 字标是手画的线条字，不依赖任何字体；界面里小字「STUDIO」可以用系统圆体代替。

## 上线前

商标查询和反向图片搜索还没做，正式对外前建议查一下。
