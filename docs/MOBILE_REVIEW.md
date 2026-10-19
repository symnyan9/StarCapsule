# Tablet and mobile review

[简体中文](#平板与移动审阅)

The HTML **More** menu offers **Auto**, **Mobile review**, and **Desktop review**. Auto selects the mobile profile on small screens or touch-first devices, including tablets. The desktop exporter itself remains a Windows application.

Project and comparison actions share one header; case selection shares the camera toolbar. Camera presets, project options and case details open in menus instead of adding rows. Picked values use a highlighted overlay inside the canvas. **A/B sync** is explained and disabled with one live view; it controls synchronization between two views, not visibility.

Mobile review starts with one live canvas while retaining the two saved desktop views. Open **Compare** when needed, or select another case. The catalog and scientific settings open as drawers. Drag with one finger to rotate; pinch with two fingers to zoom and pan. Enable **Pick**, then tap a triangle to read its source scalar and position. Color limits, real-plane sweep, comments, full-model display, and source attribution remain available. Touch controls are enlarged, rendering uses DPR 1, and sweep playback is capped at 6 frames/s. Display quality settings do not alter source geometry or scalar precision.

The default tablet fit emphasizes the body; **Fit section** explicitly includes the full exported plane, including a large far field. A task indicator reports local read/decompression/geometry preparation and HTML packaging. Decompression shows actual decoded bytes; phases without a measurable fraction stay indeterminate. The indicator clears on completion or failure and adds no permanent toolbar row.

For presentation, compose the two genuine half-models on the computer, **Export HTML**, and transfer that file to the tablet. It opens as one camera/canvas displaying the two source halves. Matching sections load as they are selected; the tablet does not have to perform the original composition. Source identities and real common-X positions remain attached.

Reports with at least 8 MiB of decoded project JSON use independently embedded case, section, and eligible layer slots. Opening loads selected case surfaces and current sections, not the complete case library. Each resident case caches at most two decoded sections. Additional layers in a split report load when shown and release their render resources and decoded working copy when hidden. On a fresh mobile view, these layers start hidden; an explicit saved layer setting is respected. A layer-only case retains its inline layer representation. Raw meshes and scientific values are never automatically decimated or rounded.

**Export HTML** retains unvisited compressed slots, all cases, source values, comments and review state. Use it for portable delivery. **Save project** explicitly materializes complete JSON, which can temporarily need considerably more memory. Ordinary JSON retains its 500 MiB limit.

All viewer code, compressed data and template assets remain inside the HTML. No CDN, server, worker download, account or network request is required. The operating system must open it in an environment that actually executes local HTML JavaScript and WebGL; a mail/file preview is not equivalent to a full browser. In particular, iPadOS file-opening and preview behavior must be checked on the intended device. Copying a file to Files does not by itself prove its viewer runs there.

### Gzip compatibility on older iPads

Safari gained native Compression Streams in [Safari / iPadOS 16.4](https://webkit.org/blog/13966/webkit-features-in-safari-16-4/#compression-streams-api). Earlier systems such as iPadOS 16.3.1 can report a missing gzip interface with older StarCapsule HTML. This message describes a missing browser API; it does not mean the report is corrupt or needs manual decompression.

New or upgraded reports prefer native `DecompressionStream` and use bundled **pako 2.2.0** inflate when that API is missing or cannot construct a gzip stream. The fallback runs offline, retains bounded decoded-byte and strict UTF-8 checks, and verifies gzip CRC32 and uncompressed size. It changes neither source meshes nor numeric precision. This covers gzip decoding, not the host app's JavaScript/WebGL support or its memory budget. A user-provided screenshot shows an earlier report rendering in **HTML Viewer Q on iPadOS 16.3.1**; that observation is **not a controlled full-device qualification** of all review, saving or large-data paths.

Use the `upgrade` command below to create a revised HTML; installing a newer desktop application does not change HTML already copied to a tablet. Without native `CompressionStream`, saving edited data slots may produce plain JSON and a larger HTML; unvisited packed v2 slots remain compressed.

Validation uses offline `file://` Chromium with tablet landscape/portrait and touch emulation, plus desktop regression checks. It is **not physical iPad, Safari/WebKit, or universal mobile-capacity acceptance**. Large full-resolution meshes can still exceed a particular browser's CPU/GPU memory budget. File size and installed RAM are not browser-memory guarantees.

Old HTML contains its old engine. Update it without STAR using a new output filename:

```powershell
starcapsule upgrade old-review.html --output tablet-review.html
```

## 平板与移动审阅

HTML 顶部 **“更多”** 菜单提供 **自动 / 移动审阅 / 桌面审阅**。自动模式识别较窄屏幕或触控优先设备；电脑保留完整桌面控件。桌面导出程序继续在 Windows 上运行。

项目与对比操作合并为一行，工况选择并入相机工具栏；视角预设、项目选项与工况详情按需展开。取点读数作为画布内高亮浮层显示。“A/B 联动”仅控制两个视口之间的同步，单视口时禁用并说明用途。

平板默认只建立一个三维画布，保留已保存的两份桌面视图。需要时可主动打开并排对比，或切换工况。目录和科学设置使用抽屉；单指旋转，双指缩放和平移，启用“取点”后轻触三角面读取数值。移动渲染分辨率和扫掠帧率降低，原始网格与场值精度保持。

默认视角聚焦车体；“完整截面”用于显式查看包含远场的整个切面。长任务显示读取、解压、检查网格、加载图层或打包的状态提示；解压显示实际字节进度，其余阶段不编造百分比。任务完成或失败后提示自动收起，不永久占用展示空间。

可以在电脑上完成左右半车拼接，导出 HTML 后交给平板展示。平板直接打开同一画布中的两侧结果，按需读取真实共同截面；保留两侧工况来源、旋转缩放、色标、取点和批注。

较大报告将工况核心、截面和附加图层分别内嵌在一个 HTML 内。首屏读取所选工况表面和当前截面；每个驻留工况最多缓存两个解压截面。分离的三维图层按需加载，隐藏后释放渲染资源及解压工作副本。新移动视图默认隐藏这些附加图层，已有明确保存的显隐状态仍受尊重。仅含图层的工况保留原内联存储方式。

“导出 HTML”保留未查看的数据块、全部工况、原始数值、显示设置和批注；“保存工程”会显式展开完整 JSON，因此临时内存可能明显增大。旧文件需通过上面的 `upgrade` 命令另存升级，不必重跑 STAR。

文件仍自包含、可离线运行。设备必须使用实际执行本地 HTML、JavaScript 和 WebGL 的打开方式；聊天软件、邮件或系统文件预览不能作为浏览器验收。iPadOS 的具体本地打开入口仍需在目标设备上检查。

Safari / iPadOS 从 [16.4](https://webkit.org/blog/13966/webkit-features-in-safari-16-4/#compression-streams-api) 开始提供原生压缩流接口。16.3.1 等较早系统打开旧版 HTML 时，可能提示缺少 gzip 接口；这表示浏览器缺少功能，文件不需要手动解压。

新版或升级后的 HTML 优先使用原生 `DecompressionStream`；接口缺失或无法建立 gzip 解压流时，改用内嵌的 **pako 2.2.0** 离线解压。两条路径均限制解压字节数、严格检查 UTF-8，并校验 gzip 的 CRC32 和原始大小，不降低网格或数值精度。这只补齐 gzip 解压能力；打开文件的 App 仍需支持 JavaScript、WebGL 并有足够内存。用户截图已显示此前报告在 **iPadOS 16.3.1 的 HTML Viewer Q** 中渲染，但这**不等于对全部审阅、保存及大数据路径的完整实体设备验收**。

已发到平板的旧 HTML 需要另存升级版本；只更新电脑软件不会自动改写旧文件。设备缺少原生 `CompressionStream` 时，修改后保存的数据块可能以普通 JSON 写出，文件会变大；未查看的 v2 压缩块仍原样保留。

目前验证范围是桌面 Chromium 的平板横竖屏与触控模拟，以及桌面回归；尚未完成实体 iPad 或 Safari/WebKit 验收。文件小于 200 MB 也不代表任意平板都能承载全部原始网格。
