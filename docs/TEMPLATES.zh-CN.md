# 自定义离线 HTML 模板

[English](TEMPLATES.md)

引擎界面默认英文，可切换简体中文，并将语言保存在 `project.ui.language`。源对象名及使用者自己写的模板文段保留原文；需要双语外层文案时由模板作者提供。内置 Engineering Blue 外层文案跟随界面语言。

模板负责报告的外观；软件负责嵌入模型、原始场值、三维引擎和交互功能。选择模板后，导出结果仍是可以单独复制打开的 HTML 文件。

## 使用方法

1. 从软件顶部的“选择模板…”选择含 `template.json` 的文件夹。
2. 修改模板中的标题、CSS、图像和字体，再运行模板校验。
3. 正常选择 SIM 和后处理对象并导出；“恢复默认”切回内置外观。

Windows 完整安装包的 `templates/engineering-blue` 提供可编辑示例。也可用以下命令复制到自己的目录；目标目录应为新建或空目录。升级时保留自己的模板，并从新版示例创建新的设计起点。多工况、取点、透明阈值及保存恢复见[离线审阅指南](REVIEW.zh-CN.md)。

```powershell
starcapsule templates --output "D:\MyReviewTemplates"
starcapsule validate-template "D:\MyReviewTemplates\engineering-blue"
```

模板路径通过界面选取，不需要修改软件源码。批处理导出可以使用 `build ... --template 文件夹`。示例采用相对资源路径，便于整体转交给其他用户或 AI。

## 最低接入条件

- 一个 `template.json` 清单，声明名称、版本和 HTML/CSS 文件路径。
- 使用完整 HTML 时保留一个 `<div id="app">`，为审阅应用提供至少 **1200 × 760 CSS px** 的空间。双视图对比适合更宽的桌面窗口；外层标题和页脚应额外预留空间。
- 完整保留数据与引擎的七个必需占位块及其顺序；可选的第八块用于模板 CSS。准确的元素 ID、占位符和放置位置见 [接口规范](TEMPLATES.md#required-layout-slots)。
- 图片、字体等素材放在模板文件夹内，路径均相对此文件夹。导出时软件会自动内嵌支持的本地素材。
- 模板只编辑外观，保持场值、坐标、单位、来源标识、取点和几何数据的含义。
- 使用静态 HTML/CSS；软件校验离线资源和引擎接口。结构校验通过后，还应打开导出结果检查字距、溢出和操作空间。

只改配色和字体时，可以提供 CSS 文件并沿用内置 HTML，减少接口误改。

## 给设计 AI 的提示词

> 请修改随附的 StarCapsule Studio 模板，使外观符合我的要求。仅调整模板文件夹里的 HTML 外层布局、CSS，以及有权使用的静态图片和字体。保留一个 div id="app"，为应用留出至少 1200 × 760 CSS px。严格保留 docs/TEMPLATES.md 中七个必需数据/引擎占位块的容器、ID 和顺序，可选 TEMPLATE_CSS 紧跟两块引擎 CSS。脚本占位块放在 app 之后、直接位于 body。保留 Designed by Symn 署名和依赖许可说明。所有资源路径相对模板文件夹；不要添加 JavaScript、事件属性、远程资源或 CSS import。保持科学数据、计算口径和交互引擎原样。交付含 template.json 的完整可编辑文件夹，并运行 validate-template，再打开导出 HTML 检查实际效果。

## 创作者署名

官方软件和导出的 HTML 由核心代码固定显示 **Designed by Symn**，模板和设置中没有关闭开关。HTML 署名独立于模板内容，正常模板 CSS 无法覆盖它；全屏查看也会显示。

这保证官方流程中的署名，源码和 HTML 的可编辑性意味着第三方仍能修改代码。项目目前采用 MIT 许可：需按许可保留版权和许可声明，MIT 本身不要求保留界面上的可见水印。
