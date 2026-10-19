# 安装 StarCapsule Studio

[English](INSTALL.md) · [离线审阅指南](REVIEW.zh-CN.md)

## Windows x64 完整包

1. 下载 `StarCapsule-Studio-0.4.0-Windows-x64.zip`，将压缩包**完整解压**。
2. 双击 **Install.cmd**。包内包含 Python/Tk，无需另装 Python，也无需管理员权限。
3. 从桌面 **StarCapsule Studio** 快捷方式启动。也可直接双击解压目录内 **Launch.cmd** 便携运行。

安装器默认英文；需要中文安装提示时，在解压目录打开 PowerShell，运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -Language zh-CN
```

软件和新报告默认英文，桌面顶部或 HTML 的 **“更多”** 菜单选择 **简体中文** 即可切换。桌面记住本地偏好；导出的 HTML 与工程 JSON 分别保存自己的语言。仿真对象名和用户文字保留原文。

更新已有安装时，先关闭 StarCapsule，再运行新版安装器；保留已有任务、导出报告和自定义模板。更新软件只影响以后导出，已经交付的旧 HTML 不会自动改变。无需重跑 STAR，可另存升级：

```powershell
starcapsule upgrade old-review.html --output updated-review.html
```

如果命令未加入 PATH，可在安装目录使用内置运行时：

```powershell
.\runtime\python.exe -I -m cfd_review upgrade old-review.html --output updated-review.html
```

路径含空格时加引号；命令默认保留原文件，请使用新的输出文件名。

## 源码或 Python wheel

需要 Python 3.10+，桌面界面还需要 Tkinter。源码目录可运行 `python run.py gui` 或双击 **Open Studio.cmd**。wheel 可离线安装：

```powershell
python -m pip install --no-index starcapsule_studio-0.4.0-py3-none-any.whl
starcapsule-gui
```

## 导出与查看条件

读取 `.sim` 需要用户自己的兼容 STAR-CCM+ 安装及有效许可。软件在后台启动专属导出进程，无需手动启动 STAR 图形界面。安装包不包含 STAR 软件或许可；当前原生 API 配置为 19.02.009，其他版本需要单独验证。

查看环境需支持本地 HTML、JavaScript 和 WebGL。同一份 HTML 提供桌面和平板布局；优先原生 gzip 解压，缺少接口时使用内嵌离线解压组件。数据与查看器均已内嵌，不执行脚本或 WebGL 的系统文件预览无法展示模型。实体 iPad/Safari 的完整验收仍待完成，选择交付设备前请阅读[平板指南](MOBILE_REVIEW.md#平板与移动审阅)。

导出时若采用 STAR 网络许可，仍需能访问对应许可服务器。已测环境和范围见[验收记录](VALIDATION.md)，本版变化与兼容性见 [0.4.0 中英文更新说明](RELEASE_NOTES_0.4.0.md#简体中文)。
