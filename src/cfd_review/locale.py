"""Small, local-only desktop language catalog and user preference storage."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

LANGUAGES = {"en": "English", "zh-CN": "简体中文"}
DEFAULT_LANGUAGE = "en"

# Source object names and scientific data never pass through this catalog.
ENGLISH = {
    "沿用各自场景场函数": "Use each source scene's field",
    "选择已求解的 .sim，然后读取可导出的表面与场函数。": "Choose a solved .sim, then read its exportable surfaces and fields.",
    "尚未读取仿真内容": "Simulation not read yet",
    "已选 0 个边界": "0 boundaries selected",
    "读取后显示可导出的等值面、平面与表面。": "Read the simulation to list exportable isosurfaces, planes and faces.",
    "选择车体壁面后自动填写 X 范围。": "Select body walls to fill the X range automatically.",
    "使用仿真中已有的系数场函数及其参考量。": "Use the simulation's existing coefficient fields and references.",
    "读取仿真后自动选择可导出的计算体网格。": "An exportable finite-volume mesh is selected after reading.",
    "模板：内置默认": "Template: built-in default",
    "StarCapsule Studio {v0} — SIM 导出": "StarCapsule Studio {v0} — SIM export",
    "选择模板…": "Choose template…", "恢复默认": "Reset template",
    "仿真文件": "Simulation", "选择 .sim…": "Choose .sim…",
    "读取仿真内容": "Read simulation", "STAR 程序（留空自动查找）": "STAR executable (auto-detect if blank)",
    "选择程序…": "Choose executable…", "并行进程 np": "Parallel ranks np",
    "STAR 路径留空时，自动查找本机安装。": "Leave STAR's path blank to detect a local installation.",
    "边界表面": "Boundary surfaces", "搜索边界": "Search boundaries", "清空选择": "Clear selection",
    "Ctrl / Shift 多选车体壁面；各边界可在 HTML 中独立显隐。": "Ctrl / Shift selects multiple walls; each boundary has independent HTML visibility.",
    "源模型为 Y=0 对称半模型：仅在 HTML 中镜像显示": "Source is a Y=0 symmetric half-model: mirror for HTML display only",
    "场函数与颜色范围": "Fields and color limits", "计算体网格": "Finite-volume mesh",
    "颜色下限": "Color minimum", "颜色上限": "Color maximum",
    "Cp 压力系数": "Cp pressure coefficient", "CpT 总压系数": "CpT total pressure coefficient",
    "真实 X 截面（可选）": "Real X sections (optional)",
    "导出截面，用于手动选面与自动扫掠": "Export sections for manual selection and automatic sweep",
    "起点 X (m)": "Start X (m)", "终点 X (m)": "End X (m)", "空间截面数": "Section count",
    "指定 X 列表 (m)": "Explicit X list (m)",
    "列表用逗号分隔；填写后替代起终点和截面数。": "Comma-separated values replace start, end and section count.",
    "使用所选范围": "Use selected bounds", "截面流体区域": "Section fluid regions",
    "HTML 文件": "HTML output", "报告标题": "Report title", "保存位置": "Save location",
    "另存为…": "Save as…", "导出并打开 HTML": "Export and open HTML",
    "取消当前任务": "Cancel task", "打开结果": "Open result", "任务文件夹": "Task folder",
    "已有后处理": "Existing postprocessing",
    "选择源仿真中已有的面对象；可与壁面一起导出。": "Select existing source face objects; export them alongside walls.",
    "搜索后处理": "Search objects", "对象 / 所属场景": "Object / source scene",
    "类型": "Type", "场景着色": "Scene coloring", "图层着色": "Layer coloring",
    "颜色下限 / 上限": "Color min / max", "不透明度": "Opacity",
    "范围留空自动取值；仅改变显示。不透明度 1 为完全不透明。": "Blank limits use the data range. Display only; opacity 1 is fully opaque.",
    "已有截面保留原位置；“仅几何”使用纯色，不携带场值。": "Existing sections retain their position. Geometry only uses a solid color without scalar values.",
    "选择已求解的 STAR-CCM+ 仿真": "Choose a solved STAR-CCM+ simulation",
    "STAR-CCM+ 仿真": "STAR-CCM+ simulation", "所有文件": "All files",
    "选择 STAR-CCM+ 程序": "Choose the STAR-CCM+ executable", "STAR-CCM+ 程序": "STAR-CCM+ executable",
    "保存离线 HTML": "Save offline HTML", "HTML 网页": "HTML document",
    "选择含 template.json 的本地模板文件夹": "Choose a local template folder containing template.json",
    "模板：": "Template: ", "已选择本地模板：{v0}": "Local template selected: {v0}",
    "模板：{v0}": "Template: {v0}",
    "模板无法使用：{v0}；请检查 template.json 与本地素材。": "Cannot use template: {v0}. Check template.json and local assets.",
    "已恢复内置 HTML 模板。当前仿真选择与导出设置保持原样。": "Built-in template restored. Simulation selections and export settings are retained.",
    "并行进程 np 请输入 1–256 的整数。": "Parallel ranks np must be an integer from 1 to 256.",
    "请先选择已求解的 .sim 文件。": "Choose a solved .sim file first.",
    "正在读取保存状态，完成后可选择表面与场函数…": "Reading saved state; select surfaces and fields when ready…",
    "读取保存场；配色仅影响显示。": "Saved fields; colors affect display only.",
    "当前文件没有可导出的体网格；请选择已保存体网格和求解场的 .sim。": "No exportable volume mesh. Choose a .sim with a saved volume mesh and solution fields.",
    "网格清单缺少类型和单元数；请重新点击“读取仿真内容”。": "Mesh type and cell counts are missing. Click Read simulation again.",
    "计算体网格 · {v0}（{v1:,} 单元）": "Finite-volume mesh · {v0} ({v1:,} cells)",
    "不导出": "Do not export", "仅几何": "Geometry only",
    "{v0} 个边界 · STAR {v1}": "{v0} boundaries · STAR {v1}", " · {v0} 步": " · {v0} iterations",
    "{v0} 个边界 · STAR {v1} · {v2} 步": "{v0} boundaries · STAR {v1} · {v2} iterations",
    "所选壁面": "Selected walls", "所选后处理面": "Selected postprocessing faces",
    "选择车体壁面可自动填写 X；也可手动设置。": "Select body walls to fill X, or enter coordinates manually.",
    "所选壁面坐标范围尚未完整取得，可手动填写。": "Selected-wall bounds are incomplete; enter coordinates manually.",
    "{v0}位于 X={v1:.5g} m，可手动扩展。": "{v0} lie at X={v1:.5g} m; expand the range as needed.",
    "{v0} X：{v1:.5g} 至 {v2:.5g} m，可手动扩展。": "{v0}: X {v1:.5g} to {v2:.5g} m; expand as needed.",
    "已将 X 起终点设为所选对象范围；可直接设置截面数量。": "X start/end now match the selected bounds; set the section count as needed.",
    "等值面": "Isosurface", "平面截面": "Plane section", "阈值面": "Threshold surface",
    "圆柱截面": "Cylinder section", "球面截面": "Sphere section", "自定义截面": "Arbitrary section",
    "其他派生部件": "Other derived parts", "纯色（无场值）": "Solid color (no scalar)",
    "已选 {v0} / {v1} 个面对象": "{v0} / {v1} face objects selected",
    "当前清单尚无可导出的面对象。": "No exportable face objects in this inventory.",
    "已选 0 / {v0} 个面对象": "0 / {v0} face objects selected",
    "图层不透明度请输入 0–1 的数值。": "Layer opacity must be a number from 0 to 1.",
    "图层不透明度请输入 0–1 的有限数值。": "Layer opacity must be a finite number from 0 to 1.",
    "图层颜色范围请同时填写有效下限与上限，或同时留空。": "Enter both valid layer color limits, or leave both blank.",
    "图层颜色下限应小于上限，且均为有限值。": "Layer color limits must be finite, with minimum below maximum.",
    "已选 {v0} 个边界": "{v0} boundaries selected",
    "场函数沿用源仿真定义；请按本工况确认系数的参考量。": "Fields use source definitions; verify coefficient references for this case.",
    "请先读取当前仿真内容。": "Read the current simulation first.",
    "请选择清单中可导出的计算体网格。": "Choose an exportable finite-volume mesh from the inventory.",
    "请选择至少一个壁面边界，或在“已有后处理”中选择面对象。": "Select at least one wall boundary or a face object in Existing postprocessing.",
    "导出壁面或新截面时，请至少选择一个已有的 Cp 或 CpT 系数场函数。": "Wall or new-section export requires at least one existing Cp or CpT coefficient field.",
    "{v0} 显示范围请输入有效数值。": "{v0} display limits must be valid numbers.",
    "{v0} 显示下限应小于上限，且均为有限值。": "{v0} display limits must be finite, with minimum below maximum.",
    "请填写递增的 X 列表，或起点、终点与 2–1000 的整数截面数。": "Enter an increasing X list, or start/end and an integer section count from 2 to 1000.",
    "X 截面坐标应为有限值并严格递增，最多 1000 个。": "X positions must be finite and strictly increasing, with at most 1000 sections.",
    "请选择截面所在的流体区域。": "Select the fluid regions for sections.",
    "请选择 HTML 保存位置。": "Choose an HTML save location.",
    "输出文件请使用 .html 或 .htm 扩展名。": "Use an .html or .htm output extension.",
    "该 HTML 已存在，请选择新的文件名以保留原文件。": "That HTML already exists; choose a new filename to preserve it.",
    "正在从保存场导出表面与截面，完成后自动打开 HTML…": "Exporting surfaces and sections from saved fields; HTML opens when complete…",
    "已读取保存状态。选择壁面与需要的场函数后即可导出。": "Saved state read. Select walls and fields to export.",
    "文件已切换，请读取当前仿真内容。": "The file changed. Read the current simulation.",
    "导出完成：{v0}": "Export complete: {v0}",
    "当前任务已取消。可以重新读取或调整导出内容。": "Task cancelled. Read again or adjust export selections.",
    "内存不足，本次任务已由保护机制停止。请关闭其他大程序，尝试将并行进程 np 设为 2，并减少本次导出的截面或等值面；点击“任务文件夹”查看日志。": "Insufficient memory: the guard stopped this task. Close other large applications, try np=2, and export fewer sections or isosurfaces. Open Task folder for logs.",
    "导出数据量或嵌套层级超出本版限制。请减少本次选择的截面或图层，或分开导出；点击“任务文件夹”查看原始计数和日志。": "Export data or nesting exceeds this version's limits. Select fewer sections/layers or export separately. Open Task folder for original counts and logs.",
    "任务失败，请查看任务日志后重试。": "Task failed. Check the task log before retrying.",
    "正在取消当前任务并清理本次 STAR 进程…": "Cancelling this task and cleaning up its owned STAR process…",
    "退出 StarCapsule Studio": "Exit StarCapsule Studio",
    "取消当前读取 / 导出任务并退出？": "Cancel the current read/export task and exit?",
    "正在结束本次任务，完成后退出…": "Stopping this task; the window closes when cleanup finishes…",
    "启动失败：{v0}": "Startup failed: {v0}",
    # Messages from the native controller remain unchanged in its logs/receipts.
    "网格清单缺少原生类型与单元数，请重新点击“读取仿真内容”": "Native mesh types and cell counts are missing. Click Read simulation again.",
    "请选择一个已保存的 STAR .sim 文件": "Choose a saved STAR .sim file.",
    "np 必须为正整数": "np must be a positive integer.",
    "{v0} 需要有限数值 [最小值, 最大值]，且最小值小于最大值": "{v0} requires finite [minimum, maximum] values, with minimum below maximum.",
    "已有任务正在运行，请等待完成或取消当前任务": "A task is already running. Wait for it to finish or cancel it.",
    "无法写入任务回执：{v0}": "Cannot write the task receipt: {v0}",
    "正在读取 SIM 对象清单并核验源文件；首次打开需要一些时间。": "Reading the SIM object inventory and checking the source; initial opening can take some time.",
    "STAR 未返回通过源文件核验的完整对象清单": "STAR did not return a complete inventory with verified source identity.",
    "STAR 对象清单缺少完整的 SIM 身份回执": "The STAR inventory is missing a complete SIM identity receipt.",
    "SIM 在清单读取期间发生变化，请重新读取": "The SIM changed while reading the inventory. Read it again.",
    "对象清单已读取。请选择表面、标量场与截面后导出。": "Inventory read. Select surfaces, scalar fields and sections to export.",
    "请选择清单中具有单元数据的体网格；几何、代理与空网格不能导出结果": "Select an inventoried volume mesh with cell data. Geometry, proxy and empty meshes cannot export results.",
    "{v0} 必须选择当前 SIM 中的现有标量函数": "{v0} must select an existing scalar function in the current SIM.",
    "请至少选择一个壁面或已有后处理面": "Select at least one wall or existing postprocessing face.",
    "表面选择格式错误": "Invalid surface-selection format.",
    "派生部件已与当前 SIM 清单失配": "The derived part no longer matches the current SIM inventory.",
    "表面需要选择至少一个精确边界": "A surface requires at least one exact source boundary.",
    "所选边界已与当前 SIM 清单失配": "A selected boundary no longer matches the current SIM inventory.",
    "后处理图层必须选择当前 SIM 中的精确派生部件": "Each postprocessing layer must select an exact derived part in the current SIM.",
    "所选后处理部件未通过原生三角面类型校验，请选择清单中支持的面部件": "The postprocessing part is not a supported native triangle-face type. Select a supported face part from the inventory.",
    "图层着色函数必须是当前 SIM 中的现有标量函数": "Layer coloring requires an existing scalar function in the current SIM.",
    "当前 SIM 含多个有效体网格，已有后处理面的标量着色需要唯一体网格。请将这些图层的着色改为“仅几何”，或使用仅含一个有效体网格的 SIM 副本；壁面和新建 X 截面可继续使用所选网格导出。": "The SIM contains multiple valid volume meshes; scalar coloring of existing faces requires a unique mesh. Use Geometry only for these layers or a SIM copy with one valid mesh. Walls and new X sections can still use the selected mesh.",
    "X 截面必须为严格递增的有限数值，单位 m": "X sections must be strictly increasing finite values in m.",
    "请为 X 截面选择当前 SIM 中的区域": "Select current SIM regions for the X sections.",
    "标题需要 1–300 个字符": "The title must contain 1 to 300 characters.",
    "请指定 Cp 与 CpT 的显示色标范围": "Specify the Cp and CpT display color limits.",
    "请明确选择全模型或关于 Y=0 对称的半模型": "Specify a full model or a half-model symmetric about Y=0.",
    "表面 Cp": "Surface Cp", "导出选项需要为对象": "Export options must be an object.",
    "请先读取所选 SIM 的对象清单": "Read the selected SIM's object inventory first.",
    "所选 SIM 与对象清单来源不同，请重新读取清单": "The selected SIM differs from the inventory source. Read its inventory again.",
    "SIM 在读取清单后发生变化，请重新读取清单": "The SIM changed after inventory. Read its inventory again.",
    "请选择 HTML 导出位置": "Choose an HTML export location.",
    "导出文件必须使用 .html 或 .htm 扩展名": "The export filename must end in .html or .htm.",
    "导出文件已存在，请选择新名称；现有文件会保留": "The export file already exists. Choose a new name; existing files are preserved.",
    "正在核验 SIM 与对象清单的 SHA-256 身份。": "Checking the SHA-256 identities of the SIM and inventory.",
    "SIM 内容与对象清单来源不同，请重新读取清单": "SIM contents differ from the inventory source. Read the inventory again.",
    "正在从保存场导出所选壁面、真实截面与已有后处理图层。": "Exporting selected walls, real sections and existing postprocessing layers from saved fields.",
    "导出结果未通过源文件与对象清单身份核验": "The export failed source and inventory identity checks.",
    "正在组装离线三维 HTML。": "Assembling the offline 3D HTML.",
    "离线三维 HTML 已导出。": "Offline 3D HTML exported.",
    "正在取消任务并完成源文件核验，请稍候。": "Cancelling the task and completing source verification; please wait.",
}


class LocalizedText(str):
    """Retain the message key while Tk receives an ordinary string."""
    def __new__(cls, text, source, values):
        instance = super().__new__(cls, text)
        instance.source = source
        instance.values = values
        return instance


def normalize_language(language):
    return language if isinstance(language, str) and language in LANGUAGES else DEFAULT_LANGUAGE


def translate(message, *, language=DEFAULT_LANGUAGE, **values):
    if isinstance(message, LocalizedText):
        values = message.values
        message = message.source
    if message not in ENGLISH and not values:
        # Three controller errors interpolate source text; keep that text verbatim.
        for pattern in ("无法写入任务回执：{v0}", "{v0} 必须选择当前 SIM 中的现有标量函数",
                        "{v0} 需要有限数值 [最小值, 最大值]，且最小值小于最大值"):
            prefix, suffix = pattern.split("{v0}")
            if message.startswith(prefix) and message.endswith(suffix):
                end = len(message) - len(suffix) if suffix else len(message)
                values = {"v0": message[len(prefix):end]}
                message = pattern
                break
    text = ENGLISH.get(message, message) if normalize_language(language) == "en" else message
    values = {key: translate(value, language=language) if isinstance(value, LocalizedText) else value
              for key, value in values.items()}
    return LocalizedText(text.format(**values) if values else text, message, values)


def settings_file(path=None):
    selected = path or os.environ.get("STARCAPSULE_SETTINGS")
    if selected:
        return Path(selected).expanduser()
    base = Path(os.environ.get("APPDATA") or (Path.home() / ".config"))
    return base / "StarCapsule" / "settings.json"


def load_language(path=None):
    try:
        target = settings_file(path)
        if target.stat().st_size > 16 * 1024:
            return DEFAULT_LANGUAGE
        config = json.loads(target.read_text(encoding="utf-8"))
        return normalize_language(config.get("language")) if isinstance(config, dict) else DEFAULT_LANGUAGE
    except (OSError, ValueError, TypeError):
        return DEFAULT_LANGUAGE


def save_language(language, path=None):
    """Persist only a UI preference; failure never interrupts an active export."""
    target = settings_file(path)
    temporary = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent,
                                         prefix="settings-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump({"language": normalize_language(language)}, handle, indent=2)
            handle.write("\n")
        temporary.replace(target)
        return True
    except OSError:
        return False
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
