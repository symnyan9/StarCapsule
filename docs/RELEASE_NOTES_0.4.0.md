# StarCapsule Studio 0.4.0

**Prerelease · 2026-10-19** · [简体中文](#简体中文)

One portable HTML now adapts to desktop and tablet review, with on-demand loading and an offline gzip compatibility layer. Original exported meshes and scientific precision are retained.

## What changed since 0.3.1

| Area | Changes in 0.4.0 |
| --- | --- |
| Tablet review | Auto/manual review profile, landscape/portrait layouts, settings/catalog drawers, larger touch targets, one-finger rotation, two-finger zoom/pan and source-valued tap picking |
| More room for the model | A single project/comparison header; case selection shares the camera toolbar; camera presets and details open on demand; picked values use a highlighted in-canvas overlay |
| On-demand loading | Large HTML reports keep surface cores, real X sections and eligible additional layers in independent embedded slots; opening does not decode the full case library |
| Working memory | At most two decoded sections per resident case; hidden layers release GPU resources and decoded working copies; mobile starts with one canvas while retaining desktop comparison states |
| Offline compatibility | Native gzip decoding remains preferred; bundled pako 2.2.0 covers a missing native decoder, including the interface absent on iPadOS 16.3.1 |
| Task feedback | Status for local reading, decompression, model/layer preparation and saving; decompression reports measured decoded bytes |
| A/B synchronization | Explain the four links, disable them with one live view and fix feedback during overlapping linked section changes |
| Data/display fixes | Preserve signed zero during upgrade/save; explicitly fitting a large section can include its complete extent |

Compose two compatible half-models on a computer, export one HTML and transfer it to a tablet for a single-camera comparison. Both sources, attributed picks and actual shared X sections remain available. Desktop controls and two-view comparison remain available in the same file.

Multi-case import, A/B comparison, half-model stitching, color-limit editing, comments, custom themes, English/Chinese UI and lossless gzip were already available in 0.3.1. This release improves their layout, loading, compatibility and synchronization.

## Install and update reports

For Windows x64, download **StarCapsule-Studio-0.4.0-Windows-x64.zip**, extract the entire archive and double-click **Install.cmd**. Close the existing application before upgrading; keep your jobs, reports and custom templates. **Launch.cmd** also supports portable use. Python/Tk is included. Other assets are:

- `starcapsule_studio-0.4.0-py3-none-any.whl` — offline Python installation.
- `StarCapsule-v0.4.0-source.zip` — source, documentation, synthetic fixtures and checks.
- `StarCapsule-Studio-0.4.0-demo.html` — standalone **synthetic** review example.
- `StarCapsule-Studio-0.4.0-half-comparison-demo.html` — **synthetic** precomposed two-source, one-camera comparison, with automatic tablet layout.

Both HTML examples default to English and can switch to Chinese in **More**.

Reading `.sim` still requires a compatible, licensed local STAR-CCM+ installation. The current native API profile is 19.02.009; another version needs its own validation. Viewing the selected results needs a local HTML environment with JavaScript and WebGL, with no STAR, Python, CDN or server.

Updating the desktop application changes future exports. **It does not update HTML already copied elsewhere.** Refresh an older report without opening STAR, using a new output filename:

```powershell
starcapsule upgrade old-review.html --output updated-review.html
```

From a source checkout, use `python run.py` in place of `starcapsule`. See the [installation guide](INSTALL.md) for the bundled Windows runtime command. Language and review mode are in the HTML's **More** menu. Select **简体中文** there without resetting the review.

From the extracted Windows package folder, no PATH change is needed:

```powershell
.\runtime\python.exe -I -m cfd_review upgrade old-review.html --output updated-review.html
```

## Compatibility and limits

Release-candidate checks passed **221 unit tests** on bundled CPython 3.14.2 / Tk 8.6.15 with no failures, errors or skips, including native Tk desktop checks. **467 offline Chromium assertions** passed across Studio, language, gzip fallback, mobile review, mobile composition, compact layout, compression and picking, with no page errors or external requests. These checks did not start STAR or establish new native-SIM or physical-device qualification. The compact suite excluded eight optional comparisons requiring a historical layout baseline. See [Validation](VALIDATION.md) for the exact breakdown; Windows package/installation acceptance is recorded separately.

- Tablet-first support retains original meshes and values. The mobile display profile lowers render resolution and sweep frame rate; it does not simplify or round source data.
- Large reports use the v2 embedded bundle when decoded project JSON reaches 8 MiB. Smaller and older report formats remain readable. The portable file still contains unvisited data; this is deferred loading, not data removal.
- Prefer **Export HTML** for delivery: it preserves untouched packed slots. **Save project** expands complete JSON and can require more temporary memory. Without native `CompressionStream`, edited slots can save as plain JSON and make the HTML larger; unvisited packed v2 slots remain compressed.
- The gzip fallback retains byte bounds, strict UTF-8 and gzip CRC32/size checks. It solves missing decompression support, not a host app's missing JavaScript/WebGL or limited CPU/GPU memory.
- A user screenshot shows a previous report rendering in HTML Viewer Q on iPadOS 16.3.1. Automated checks use desktop Chromium with tablet/touch emulation; full physical iPad/Safari qualification and universal phone or large-model capacity are not established.
- Current changes do not promise a particular file-size reduction, RAM reduction or opening speed across devices. See [Validation](VALIDATION.md) and the [tablet guide](MOBILE_REVIEW.md) for the exercised scope.

Public demo data is synthetic. The authorized real-case screenshot remains a rendered illustration only; no real simulation files, vehicle geometry or scientific arrays are included. Original code is MIT licensed; bundled Three.js/OrbitControls and pako retain their notices. STAR and its license are not distributed.

Designed by **Symn · Jilin University**. Inspired by **Gsmart, part of JLU Racing at Jilin University**.

---

# 简体中文

**0.4.0 预发布 · 2026-10-19**

同一份离线 HTML 适配桌面和平板，新增按需加载与内置 gzip 解压兼容。保留原始导出网格及科学数据精度。

## 相比 0.3.1 的更新

| 方面 | 0.4.0 的变化 |
| --- | --- |
| 平板审阅 | 自动/手动切换审阅模式，适配横竖屏；目录与设置抽屉、大触控目标、单指旋转、双指缩放平移、轻触读取源值 |
| 扩大核心画面 | 项目与对比操作共用顶部；工况选择并入相机工具栏；预设与详情按需展开；取点使用画布内高亮浮层 |
| 按需加载 | 较大报告分别内嵌工况核心、真实 X 截面及符合条件的附加图层，打开时不展开整个工况库 |
| 工作内存 | 每个驻留工况最多缓存两个解压截面；隐藏图层释放 GPU 资源和解压副本；平板默认单画布，同时保留桌面对比状态 |
| 离线兼容 | 优先原生 gzip 解压；内置 pako 2.2.0，覆盖 iPadOS 16.3.1 等缺少原生接口的环境 |
| 任务提示 | 读取、解压、准备模型/图层和保存时显示状态；解压进度使用实际字节数 |
| A/B 联动 | 解释四项联动用途，单视口禁用，修复快速连续切片时的反馈同步问题 |
| 数据与显示修正 | 升级/保存保留负零；显式选择“完整截面”时允许适配整个大切面 |

可以先在电脑上拼接两个符合条件的半模型，导出 HTML 后交给平板，以一个相机查看两侧工况。来源标识、取点和双方实际共有的 X 截面保留。桌面控件与双视口对比仍可在同一文件中使用。

多工况导入、A/B 对比、半车拼接、色标修改、批注、自定义主题、中英文和无损 gzip 在 0.3.1 已有。本次更新主要改善布局、加载、兼容性和联动行为。

## 安装与旧报告升级

Windows x64 下载 **StarCapsule-Studio-0.4.0-Windows-x64.zip**，完整解压后双击 **Install.cmd**。升级前关闭原程序，保留已有任务、报告和自定义模板；也可直接使用 **Launch.cmd** 便携运行。完整包内置 Python/Tk。其他附件为：

- `starcapsule_studio-0.4.0-py3-none-any.whl`：离线安装到已有 Python 环境。
- `StarCapsule-v0.4.0-source.zip`：源码、说明、合成样例和检查工具。
- `StarCapsule-Studio-0.4.0-demo.html`：独立的**合成数据**审阅示例。
- `StarCapsule-Studio-0.4.0-half-comparison-demo.html`：预先拼好的**合成数据**双来源、单画布对比，自动适配平板。

两份示例默认英文，均可在 **“更多”** 中切换中文。

读取 `.sim` 仍需要本机兼容且有许可的 STAR-CCM+；当前原生 API 配置为 19.02.009，其他版本需要单独验证。查看选定结果只需支持本地 HTML、JavaScript 和 WebGL 的环境，无需 STAR、Python、CDN 或服务器。

更新电脑软件会更新以后导出的 HTML，**不会自动修改已经转交的旧文件**。无需启动 STAR，可使用新文件名升级旧报告：

```powershell
starcapsule upgrade old-review.html --output updated-review.html
```

源码目录可用 `python run.py` 替代 `starcapsule`；完整 Windows 包的内置运行时命令见[安装说明](INSTALL.zh-CN.md)。HTML 的语言与审阅模式位于 **“更多”** 菜单，切换简体中文会保留当前观察状态。

在完整 Windows 包的解压目录，无需修改 PATH 即可运行：

```powershell
.\runtime\python.exe -I -m cfd_review upgrade old-review.html --output updated-review.html
```

## 兼容性与边界

发布候选使用内置 CPython 3.14.2 / Tk 8.6.15 通过 **221 项单元测试**，包含原生 Tk 桌面检查，失败、错误和跳过均为 0。Studio、语言、gzip 兼容、移动审阅、移动拼接、紧凑布局、压缩及取点共 **467 项离线 Chromium 检查**通过，无页面错误或外部请求。此次未启动 STAR，不作为新的原生 SIM 导出或实体设备验收。紧凑布局套件未计入 8 项依赖历史布局基线的可选对比；精确分项见[验收记录](VALIDATION.md)，Windows 打包与安装另行验收。

- 优先兼容平板，原始网格与数值保留。移动模式降低渲染分辨率和扫掠帧率，不对源数据减面或舍入。
- 解码后的工程 JSON 达到 8 MiB 时采用 v2 分块封装；小报告及旧格式仍可读。完整 HTML 继续携带尚未查看的数据，按需加载不等于删除内容。
- 转交优先使用 **“导出 HTML”**，可保留未改动的压缩块；**“保存工程”** 会展开完整 JSON，可能需要更多临时内存。缺少原生 `CompressionStream` 时，编辑块可能以普通 JSON 保存，文件会变大，未查看的 v2 压缩块仍原样保留。
- 解压兼容层保留字节上限、严格 UTF-8 及 gzip CRC32/大小校验。它补齐解压能力；打开 App 仍需支持 JavaScript、WebGL，且具有足够 CPU/GPU 内存。
- 用户截图已显示此前报告在 iPadOS 16.3.1 的 HTML Viewer Q 中渲染。自动检查采用桌面 Chromium 的平板/触控模拟，尚不等于实体 iPad/Safari 的完整验收，也不保证任意手机或大模型都能运行。
- 本次变化不承诺固定的文件缩减、运行内存缩减或跨设备打开速度。具体已测范围见[验收记录](VALIDATION.md)与[平板指南](MOBILE_REVIEW.md#平板与移动审阅)。

公开示例采用合成数据。已授权实车截图仅用于展示，不包含真实仿真文件、车体几何或场值数组。原创代码采用 MIT；Three.js/OrbitControls 与 pako 保留各自许可，安装包不分发 STAR 或其许可。

Designed by **Symn · Jilin University**。灵感来自吉林大学 **JLU Racing 旗下 Gsmart** 的仿真与设计评审工作流。
