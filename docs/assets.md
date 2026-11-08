# Assets — 图片素材

> 场景默认用代码绘制的矢量图形。把 PNG 放进 `assets/`，代码会自动改用图片；
> **没有图片就退回矢量**，所以应用永远能跑。

## 为什么需要素材

代码能画「干净等距矢量」，画不出手绘笔触和像素细节。想要 pixtuoid / 星露谷那种质感，
必须用真正的像素或手绘素材。

## 目录

```
assets/
├── desk.png
├── plant.png
├── sofa.png
└── ...
```

## 文件名与用途

| 文件 | 用途 | 建议宽度（像素） |
|---|---|---|
| `desk.png` | 工位（桌 + 椅 + 显示器） | 96–160 |
| `chair.png` | 独立椅子 | 48–96 |
| `plant.png` | 盆栽 | 48–96 |
| `sofa.png` | 沙发（含茶几、灯） | 128–192 |
| `table.png` | 会议桌 / 茶几 | 128–192 |
| `fridge.png` | 冰箱 | 64–96 |
| `cooler.png` | 饮水机 | 48–64 |
| `shelf.png` | 书架 | 96–128 |
| `printer.png` | 打印机 | 64–96 |
| `door.png` | 大门 | 128–192 |
| `whiteboard.png` | 白板 | 96–128 |
| `board.png` | 公告板 | 96–128 |
| `clock.png` | 挂钟 | 48–64 |

全部可选。先放 `desk.png` 和 `plant.png` 就能看出效果。

## 锚点与缩放

- 图片的**底部中心**对齐地面点，所以素材要画成「站在地上」的姿态。
- 图片会按调用方给的世界宽度等比缩放，不需要精确像素尺寸。
- 建议用**等距（isometric）角度**的素材，否则和地板的透视对不上。

## 去哪里找

- itch.io 搜 `isometric office tileset`、`isometric furniture`、`top-down office`。
- 注意许可证：MIT / CC0 / 已购买才可随项目分发；把许可文件一起放进 `assets/LICENSE-*`。
- **不要**直接使用 pixtuoid 的 `.sprite`：它的代码是 MIT，但**美术资源单独授权**，
  而且那是俯视角度，不是等距。

## 换成像素风

素材是像素画时，把 `SceneWidget.pixel_scale` 设为 2 或 3，
场景会按低分辨率渲染再放大，边缘更硬，和像素素材更搭。
默认是 1（矢量清晰）。
