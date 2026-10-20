# 数字艺术装置 · 课堂演示

五支由乐曲分析数据驱动的音乐影像 + 一台音轨标注台，纯前端、单页、无后端。
同一份目录既能本地双击打开，也能原样挂到 GitHub Pages。

## 打开

- **本地**：解压后双击 `index.html`。六张卡片中，五支装置用随包演示数据打开；标注台需要你自己载入音频。
- **云端**：<https://screamingmaggot.github.io/digital-art-devices/>（部署后生效）。
- 文件选择器、音频播放、标注台“送进装置”都不需要联网；页面本身不发起任何网络请求。

## 结构

```
index.html            启动台（六入口）
player.html           播放壳：iframe + 演示数据投递 + 返回
devices/a|b|c|d|mv.html   五支装置（单文件，画面 = f(features, t)）
annotator.html        音轨标注台（浏览器内近似分析；完整 analyze.py 需本地 Python）
demo/
  demo.mp3            自制 30s / 96 BPM 演示曲
  features.json       analyze.py 对它的分析结果
  timeline.json       同一份乐谱导出的真值（D 的音符）
  demo.js             base64 音频 + 两个 JSON（file:// 也能投递）
tools/
  make_demo.py        演示曲/乐谱/数据生成器（需原始工程的 Python 环境）
  check_site.py       本地验收：六入口、投递、D timeline、标注台送包
```

## 演示数据

演示曲是**用代码合成**的（`tools/make_demo.py`，numpy 振荡器 + 噪声鼓组），
不含任何原曲、采样或第三方音频。分析器把它读成 **192 BPM**（96 的倍层级，常见的 octave 歧义）；
因为曲子是我们写的，按作曲真值在 features 里**人工切回 96**（`bpm_basis` 写明原因），
bundle 的 `bpm_source` 写“人工输入”。这不是用默认值顶替不可信数据。

## 边界（如实说明）

- 标注台在网页里走**浏览器内近似分析**；完整的 `analyze.py`/MERT 需要本地 Python，云端静态站跑不了。
- 浏览器内分析的结果现在也能“送进装置”（会先序列化成 schema 2 的 features），但精度低于 `analyze.py`。
- 仓库里**没有任何原曲或带原声的成片**；音频只在访问者本机浏览器里处理。
- 五支装置仍是纯函数：无墙钟动画、无随机数；演示数据清零即停。

## 验收

`python tools/check_site.py` 会分别以 `file://` 和本地 `http://` 打开站点，检查：

- 启动台 6 个入口；
- 五支装置都收到演示 bundle（`__BUNDLE__.received`）且 `dur=60`；
- D 的 timeline 装载（`#btnTim` 带 ✔）；
- 标注台载入 `demo.mp3` → 浏览器分析 → “送进装置” → 装置回执；
- 无 JS 页面错误。

最近一次结果见提交信息/`tools/_check_site.log`（本地文件，不随仓库发布）。

## 许可

代码 MIT（见 `LICENSE`）。画面与文案的著作权归作者。
