# 安装 StarCapsule Studio

[English](INSTALL.md) · [离线审阅指南](REVIEW.zh-CN.md)

## Windows x64 完整包

1. 下载 `StarCapsule-Studio-0.3.1-Windows-x64.zip`，将压缩包**完整解压**。
2. 双击 **Install.cmd**。包内包含 Python/Tk，无需另装 Python，也无需管理员权限。
3. 从桌面 **StarCapsule Studio** 快捷方式启动。也可直接双击解压目录内 **Launch.cmd** 便携运行。

安装器默认英文；需要中文安装提示时，在解压目录打开 PowerShell，运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -Language zh-CN
```

软件和新报告默认英文，顶部选择 **简体中文** 即可切换。桌面记住本地偏好；导出的 HTML 与工程 JSON 分别保存自己的语言。仿真对象名和用户文字保留原文。

## 源码或 Python wheel

需要 Python 3.10+，桌面界面还需要 Tkinter。源码目录可运行 `python run.py gui` 或双击 **Open Studio.cmd**。wheel 可离线安装：

```powershell
python -m pip install --no-index starcapsule_studio-0.3.1-py3-none-any.whl
starcapsule-gui
```

## 导出与查看条件

读取 `.sim` 需要用户自己的兼容 STAR-CCM+ 安装及有效许可。软件在后台启动专属导出进程，无需手动启动 STAR 图形界面。安装包不包含 STAR 软件或许可；当前原生 API 配置为 19.02.009，其他版本需要单独验证。

查看导出的 HTML 只需支持 WebGL 和原生 gzip 解压的桌面浏览器；选定数据与查看器均已内嵌。导出时若采用 STAR 网络许可，仍需能访问对应许可服务器。已测环境和范围见[验收记录](VALIDATION.md)。
