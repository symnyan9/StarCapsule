"""Native, local SIM selection and export workflow (stdlib Tk only)."""
from __future__ import annotations

import math
import os
from pathlib import Path
import queue
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from .locale import ENGLISH, LANGUAGES, LocalizedText, load_language, normalize_language, save_language, translate


class ExportApp:
    """Tk widgets stay on the main thread; the controller owns STAR work."""

    def __init__(self, root, controller=None, *, language=None, settings_path=None):
        self.root = root
        self.settings_path = settings_path
        self.language = normalize_language(language) if language is not None else load_language(settings_path)
        self._localized_strings = {}
        self._localized_widgets = []
        work_root = Path(os.environ.get("CFD_REVIEW_WORK_ROOT", str(
            Path.cwd().parent / "CFD-Review-Studio-data" / "jobs"))).expanduser()
        if controller is None:
            from .desktop import DesktopController
            controller = DesktopController(work_root)
        self.controller = controller
        output_root = Path(os.environ.get("CFD_REVIEW_OUTPUT", str(work_root.parent / "exports")))
        self.vars = {
            key: tk.StringVar(root, value=value) for key, value in {
                "sim": "", "star": "", "np": "2", "title": "", "output": "",
                "representation": "", "cp_function": "", "cpt_function": "",
                "x_start": "", "x_end": "", "x_count": "21", "x_list": "",
                "cp_min": "-3", "cp_max": "3", "cpt_min": "-0.5", "cpt_max": "1",
                "search": "", "derived_search": "", "template": "", "layer_function": self._tr('沿用各自场景场函数'),
                "layer_min": "", "layer_max": "", "layer_opacity": "0.7", "layer_units": "",
            }.items()
        }
        self.vars["section_enabled"] = tk.BooleanVar(root, value=False)
        self.vars["half_car"] = tk.BooleanVar(root, value=False)
        self.output_root = output_root
        self.template_root = Path(os.environ.get("CFD_REVIEW_TEMPLATES", str(Path.cwd() / "templates"))).expanduser()
        self.inventory = None
        self._inventory_sim = None
        self._working = False
        self._closing = False
        self._last_html = None
        self._last_job = None
        self._timer = None
        self.boundary_items = {}
        self._all_boundaries = []
        self._selected_boundaries = set()
        self._rebuilding_tree = False
        self.derived_items = {}
        self._all_derived = []
        self._selected_derived = set()
        self._rebuilding_derived = False
        self._boundary_bounds = {}
        self._selection_bounds = None
        self._last_auto_bounds = None
        self._representation_names = {}
        self._representations = []
        self._editable = []
        self._inventory_controls = []
        self._section_controls = []
        self.status = tk.StringVar(root, value=self._tr('选择已求解的 .sim，然后读取可导出的表面与场函数。'))
        self.inventory_summary = tk.StringVar(root, value=self._tr('尚未读取仿真内容'))
        self.selection_summary = tk.StringVar(root, value=self._tr('已选 0 个边界'))
        self.derived_summary = tk.StringVar(root, value=self._tr('读取后显示可导出的等值面、平面与表面。'))
        self.bounds_summary = tk.StringVar(root, value=self._tr('选择车体壁面后自动填写 X 范围。'))
        self.reference_hint = tk.StringVar(root, value=self._tr('使用仿真中已有的系数场函数及其参考量。'))
        self.representation_hint = tk.StringVar(root, value=self._tr('读取仿真后自动选择可导出的计算体网格。'))
        self.template_summary = tk.StringVar(root, value=self._tr('模板：内置默认'))
        self._style()
        self._build()
        self._register_localized_widgets()
        self.vars["sim"].trace_add("write", self._source_changed)
        self.vars["search"].trace_add("write", lambda *_: self._render_boundaries())
        self.vars["derived_search"].trace_add("write", lambda *_: self._render_derived())
        self.vars["section_enabled"].trace_add("write", lambda *_: self._refresh_state())
        self.vars["cp_function"].trace_add("write", lambda *_: self._show_references())
        self.vars["cpt_function"].trace_add("write", lambda *_: self._show_references())
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._refresh_state()
        self._timer = self.root.after(100, self.poll_events)

    def _tr(self, message, **values):
        return translate(message, language=self.language, **values)

    def _set_text(self, variable, message):
        self._localized_strings[str(variable)] = (variable, message)
        variable.set(self._tr(message))

    def _register_localized_widgets(self):
        """Remember UI labels only; source tree items and editable values stay untouched."""
        reverse = {value: key for key, value in ENGLISH.items()}
        def source(text):
            return text if text in ENGLISH else reverse.get(text)
        def visit(widget):
            if "text" in widget.keys():
                key = source(str(widget.cget("text")))
                if key:
                    self._localized_widgets.append((widget, "text", key))
            if isinstance(widget, ttk.Notebook):
                for tab in widget.tabs():
                    key = source(widget.tab(tab, "text"))
                    if key:
                        self._localized_widgets.append((widget, ("tab", tab), key))
            if isinstance(widget, ttk.Treeview):
                for column in ("#0", *widget.cget("columns")):
                    key = source(widget.heading(column, "text"))
                    if key:
                        self._localized_widgets.append((widget, ("heading", column), key))
            for child in widget.winfo_children():
                visit(child)
        visit(self.root)
        for name in ("status", "inventory_summary", "selection_summary", "derived_summary",
                     "bounds_summary", "reference_hint", "representation_hint", "template_summary"):
            variable = getattr(self, name)
            self._set_text(variable, source(variable.get()) or variable.get())

    def set_language(self, language):
        """Update existing widgets without re-reading STAR or discarding an active job."""
        language = normalize_language(language)
        if language == self.language:
            return
        sentinels = {}
        for key in ("cp_function", "cpt_function", "layer_function"):
            for source in ("不导出", "沿用各自场景场函数", "仅几何"):
                if self.vars[key].get() == self._tr(source):
                    sentinels[key] = source
        raw_representation = self._representation_names.get(self.vars["representation"].get())
        self.language = language
        self.language_var.set(LANGUAGES[language])
        from . import __version__
        self.root.title(self._tr("StarCapsule Studio {v0} — SIM 导出", v0=__version__))
        for widget, option, source in self._localized_widgets:
            if isinstance(option, tuple):
                getattr(widget, option[0])(option[1], text=self._tr(source))
            else:
                widget.configure(**{option: self._tr(source)})
        for variable, message in list(self._localized_strings.values()):
            variable.set(self._tr(message))
        for key, source in sentinels.items():
            self.vars[key].set(self._tr(source))
        for key in ("cp_function", "cpt_function"):
            options = list(self.field_combos[key].cget("values"))
            if options:
                options[0] = self._tr("不导出")
                self.field_combos[key].configure(values=options)
        options = list(self.layer_field_combo.cget("values"))
        if options:
            self.layer_field_combo.configure(values=[self._tr("沿用各自场景场函数"), self._tr("仅几何"), *options[2:]])
        self._representation_names = {
            self._tr("计算体网格 · {v0}（{v1:,} 单元）", v0=row["name"], v1=row["cellCount"]): row["name"]
            for row in self._representations
        }
        self.representation_combo.configure(values=list(self._representation_names))
        if raw_representation is not None:
            self.vars["representation"].set(next(label for label, raw in self._representation_names.items()
                                                  if raw == raw_representation))
        self._render_boundaries()
        self._render_derived()
        self._show_references()
        self._refresh_state()
        if not save_language(language, self.settings_path):
            self._append_log("Language changed for this session; could not save the local preference.")

    def _style(self):
        from . import __version__
        root = self.root
        root.title(self._tr('StarCapsule Studio {v0} — SIM 导出', v0=__version__))
        width = min(1280, max(1040, root.winfo_screenwidth() - 80))
        height = min(870, max(700, root.winfo_screenheight() - 110))
        root.geometry(f"{width}x{height}")
        root.minsize(1040, 780)
        root.configure(background="#f3f5f7")
        style = ttk.Style(root)
        # clam keeps the same readable field/button geometry across Windows themes.
        if "clam" in style.theme_names():
            style.theme_use("clam")
        font = ("Microsoft YaHei UI", 10) if os.name == "nt" else ("TkDefaultFont", 10)
        style.configure(".", font=font, foreground="#26313b")
        style.configure("TFrame", background="#f3f5f7")
        style.configure("TLabel", background="#f3f5f7")
        style.configure("Muted.TLabel", foreground="#586574")
        style.configure("Section.TLabel", font=(font[0], 12, "bold"))
        style.configure("TLabelframe", background="#f3f5f7", bordercolor="#ccd4dc", relief="solid")
        style.configure("TLabelframe.Label", background="#f3f5f7", font=(font[0], 11, "bold"))
        style.configure("TButton", padding=(12, 6))
        style.configure("Primary.TButton", background="#1764c0", foreground="#ffffff", padding=(16, 8))
        style.configure("Header.TButton", background="#35434f", foreground="#ffffff", padding=(10, 5))
        style.map("Header.TButton", background=[("disabled", "#34404a"), ("pressed", "#465765"), ("active", "#435563")],
                  foreground=[("disabled", "#b5c0c9"), ("!disabled", "#ffffff")])
        style.configure("Credit.TLabel", font=("Segoe UI", 9), foreground="#465360", background="#f3f5f7")
        style.map("Primary.TButton", background=[("disabled", "#dce2e8"), ("pressed", "#124d94"), ("active", "#1255a6")],
                  foreground=[("disabled", "#6a7681"), ("!disabled", "#ffffff")])
        style.configure("TEntry", padding=5)
        style.configure("TProgressbar", thickness=6)
        style.configure("TCombobox", padding=4)
        style.configure("TCheckbutton", background="#f3f5f7", padding=(0, 3))
        style.configure("Treeview", rowheight=26, background="#ffffff", fieldbackground="#ffffff", bordercolor="#ccd4dc")
        style.map("Treeview", background=[("selected", "#1764c0")], foreground=[("selected", "#ffffff")])

    def _entry(self, parent, key, *, width=None, inventory=False, section=False):
        widget = ttk.Entry(parent, textvariable=self.vars[key], **({"width": width} if width else {}))
        self._editable.append(widget)
        if inventory:
            self._inventory_controls.append(widget)
        if section:
            self._section_controls.append(widget)
        return widget

    def _build(self):
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)
        header = tk.Frame(root, background="#202a34", padx=20, pady=10)
        header.grid(row=0, column=0, sticky="ew")
        tk.Label(header, text="StarCapsule Studio", background="#202a34", foreground="white",
                 font=("Segoe UI", 18, "bold")).pack(side="left")
        language_bar = tk.Frame(header, background="#202a34")
        language_bar.pack(side="left", padx=(18, 0))
        self.language_var = tk.StringVar(root, value=LANGUAGES[self.language])
        self.language_combo = ttk.Combobox(language_bar, textvariable=self.language_var,
                                            values=list(LANGUAGES.values()), state="readonly", width=10)
        self.language_combo.pack(side="left")
        self.language_combo.bind("<<ComboboxSelected>>", lambda _event: self.set_language(
            next(code for code, label in LANGUAGES.items() if label == self.language_var.get())))
        template_bar = tk.Frame(header, background="#202a34")
        template_bar.pack(side="right")
        tk.Label(template_bar, textvariable=self.template_summary, background="#202a34", foreground="#d0d9e3",
                 font=("Microsoft YaHei UI", 10), wraplength=320, justify="right").pack(side="left", padx=(0, 10))
        self.template_button = ttk.Button(template_bar, text=self._tr('选择模板…'), style="Header.TButton", command=self.choose_template)
        self.template_button.pack(side="left")
        self.template_reset_button = ttk.Button(template_bar, text=self._tr('恢复默认'), style="Header.TButton", command=self.reset_template)
        self.template_reset_button.pack(side="left", padx=(7, 0))
        source = ttk.Frame(root, padding=(18, 10, 18, 4))
        source.grid(row=1, column=0, sticky="ew")
        source.columnconfigure(1, weight=1)
        ttk.Label(source, text=self._tr('仿真文件')).grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.sim_entry = self._entry(source, "sim")
        self.sim_entry.grid(row=0, column=1, sticky="ew")
        self.sim_button = ttk.Button(source, text=self._tr('选择 .sim…'), command=self.choose_sim)
        self.sim_button.grid(row=0, column=2, padx=(8, 0))
        self.read_button = ttk.Button(source, text=self._tr('读取仿真内容'), command=self.inspect_sim)
        self.read_button.grid(row=0, column=3, padx=(8, 0))
        runtime = ttk.Frame(source)
        runtime.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        runtime.columnconfigure(1, weight=1)
        ttk.Label(runtime, text=self._tr('STAR 程序（留空自动查找）')).grid(row=0, column=0, sticky="w", padx=(0, 10))
        star_entry = self._entry(runtime, "star")
        star_entry.grid(row=0, column=1, sticky="ew")
        self.star_button = ttk.Button(runtime, text=self._tr('选择程序…'), command=self.choose_star)
        self.star_button.grid(row=0, column=2, padx=(8, 12))
        ttk.Label(runtime, text=self._tr('并行进程 np')).grid(row=0, column=3, padx=(0, 6))
        self._entry(runtime, "np", width=5).grid(row=0, column=4)
        star_entry.bind("<FocusIn>", lambda _: self._set_text(self.status, self._tr('STAR 路径留空时，自动查找本机安装。')))

        body = ttk.Frame(root, padding=(18, 8, 18, 8))
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=5, uniform="body")
        body.columnconfigure(1, weight=4, uniform="body")
        body.rowconfigure(0, weight=1)
        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.content_tabs = ttk.Notebook(left)
        self.content_tabs.grid(row=0, column=0, sticky="nsew")
        surfaces = ttk.Frame(self.content_tabs, padding=10)
        self.content_tabs.add(surfaces, text=self._tr('边界表面'))
        surfaces.columnconfigure(0, weight=1)
        surfaces.rowconfigure(2, weight=1)
        ttk.Label(surfaces, textvariable=self.inventory_summary, style="Muted.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        search = self._entry(surfaces, "search", inventory=True)
        search.grid(row=1, column=0, sticky="ew", pady=(7, 7))
        ttk.Label(surfaces, text=self._tr('搜索边界'), style="Muted.TLabel").grid(row=1, column=1, padx=(10, 0))
        self.boundary_tree = ttk.Treeview(surfaces, selectmode="extended", show="tree", height=5)
        self.boundary_tree.grid(row=2, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(surfaces, orient="vertical", command=self.boundary_tree.yview)
        scroll.grid(row=2, column=1, sticky="ns")
        self.boundary_tree.configure(yscrollcommand=scroll.set)
        self.boundary_tree.bind("<<TreeviewSelect>>", self._boundary_selected)
        selection_bar = ttk.Frame(surfaces)
        selection_bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        ttk.Label(selection_bar, textvariable=self.selection_summary).pack(side="left")
        self.clear_button = ttk.Button(selection_bar, text=self._tr('清空选择'), command=self.clear_boundaries)
        self.clear_button.pack(side="right")
        ttk.Label(surfaces, text=self._tr('Ctrl / Shift 多选车体壁面；各边界可在 HTML 中独立显隐。'), style="Muted.TLabel", wraplength=450).grid(row=4, column=0, columnspan=2, sticky="w", pady=(5, 0))
        self._inventory_controls.append(self.clear_button)
        self._build_derived_tab()
        symmetry = ttk.Checkbutton(left, text=self._tr('源模型为 Y=0 对称半模型：仅在 HTML 中镜像显示'), variable=self.vars["half_car"])
        symmetry.grid(row=1, column=0, sticky="w", pady=(7, 0))
        self._editable.append(symmetry)
        self._inventory_controls.append(symmetry)

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        fields = ttk.LabelFrame(right, text=self._tr('场函数与颜色范围'), padding=6)
        fields.grid(row=0, column=0, sticky="ew")
        fields.columnconfigure(1, weight=1)
        ttk.Label(fields, text=self._tr('计算体网格')).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.representation_combo = ttk.Combobox(fields, textvariable=self.vars["representation"], state="readonly", width=24)
        self.representation_combo.grid(row=0, column=1, columnspan=3, sticky="ew")
        self.field_combos = {}
        self._inventory_controls.append(self.representation_combo)
        self.representation_help = ttk.Label(fields, textvariable=self.representation_hint, style="Muted.TLabel", wraplength=280)
        self.representation_help.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(fields, text=self._tr('颜色下限'), style="Muted.TLabel").grid(row=1, column=2, pady=(4, 0))
        ttk.Label(fields, text=self._tr('颜色上限'), style="Muted.TLabel").grid(row=1, column=3, pady=(4, 0))
        for row, name, key in ((2, self._tr('Cp 压力系数'), "cp_function"), (3, self._tr('CpT 总压系数'), "cpt_function")):
            ttk.Label(fields, text=name, wraplength=140).grid(row=row, column=0, sticky="w", pady=(3, 0))
            combo = ttk.Combobox(fields, textvariable=self.vars[key], state="readonly", width=23)
            combo.grid(row=row, column=1, sticky="ew", pady=(3, 0))
            self.field_combos[key] = combo
            self._inventory_controls.append(combo)
            lo = "cp_min" if row == 2 else "cpt_min"
            hi = "cp_max" if row == 2 else "cpt_max"
            self._entry(fields, lo, width=6, inventory=True).grid(row=row, column=2, padx=(8, 4), pady=(3, 0))
            self._entry(fields, hi, width=6, inventory=True).grid(row=row, column=3, pady=(3, 0))
        ttk.Label(fields, textvariable=self.reference_hint, style="Muted.TLabel", wraplength=510).grid(row=4, column=0, columnspan=4, sticky="w", pady=(3, 0))

        planes = ttk.LabelFrame(right, text=self._tr('真实 X 截面（可选）'), padding=6)
        planes.grid(row=1, column=0, sticky="ew", pady=(7, 0))
        planes.columnconfigure(1, weight=1)
        enable = ttk.Checkbutton(planes, text=self._tr('导出截面，用于手动选面与自动扫掠'), variable=self.vars["section_enabled"])
        enable.grid(row=0, column=0, columnspan=4, sticky="w")
        self._editable.append(enable)
        self._inventory_controls.append(enable)
        interval = ttk.Frame(planes)
        interval.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(3, 0))
        for col, text, key in ((0, self._tr('起点 X (m)'), "x_start"), (2, self._tr('终点 X (m)'), "x_end"), (4, self._tr('空间截面数'), "x_count")):
            ttk.Label(interval, text=text).grid(row=0, column=col, sticky="w", padx=(0, 4))
            self._entry(interval, key, width=7 if col != 4 else 4, section=True).grid(row=0, column=col + 1, sticky="ew", padx=(0, 8) if col != 4 else 0)
            interval.columnconfigure(col + 1, weight=1)
        ttk.Label(planes, text=self._tr('指定 X 列表 (m)')).grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(3, 0))
        self._entry(planes, "x_list", section=True).grid(row=2, column=1, columnspan=3, sticky="ew", pady=(3, 0))
        ttk.Label(planes, text=self._tr('列表用逗号分隔；填写后替代起终点和截面数。'), style="Muted.TLabel").grid(row=3, column=0, columnspan=4, sticky="w", pady=(2, 0))
        bounds_row = ttk.Frame(planes)
        bounds_row.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(3, 2))
        bounds_row.columnconfigure(0, weight=1)
        ttk.Label(bounds_row, textvariable=self.bounds_summary, style="Muted.TLabel", wraplength=350).grid(row=0, column=0, sticky="w")
        self.bounds_button = ttk.Button(bounds_row, text=self._tr('使用所选范围'), command=self.use_selection_bounds)
        self.bounds_button.grid(row=0, column=1, padx=(7, 0))
        self.region_list = tk.Listbox(planes, height=2, selectmode=tk.MULTIPLE, exportselection=False,
                                     relief="solid", borderwidth=1, font=("Microsoft YaHei UI", 10),
                                     selectbackground="#1764c0", selectforeground="white", highlightthickness=1,
                                     highlightcolor="#1764c0", highlightbackground="#ccd4dc")
        ttk.Label(planes, text=self._tr('截面流体区域')).grid(row=5, column=0, sticky="nw", padx=(0, 8), pady=(2, 0))
        self.region_list.grid(row=5, column=1, columnspan=2, sticky="ew")
        region_scroll = ttk.Scrollbar(planes, orient="vertical", command=self.region_list.yview)
        region_scroll.grid(row=5, column=3, sticky="ns")
        self.region_list.configure(yscrollcommand=region_scroll.set)

        output = ttk.LabelFrame(body, text=self._tr('HTML 文件'), padding=6)
        output.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        output.columnconfigure(1, weight=2)
        output.columnconfigure(3, weight=3)
        ttk.Label(output, text=self._tr('报告标题')).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self._entry(output, "title").grid(row=0, column=1, sticky="ew")
        ttk.Label(output, text=self._tr('保存位置')).grid(row=0, column=2, sticky="w", padx=(14, 8))
        self._entry(output, "output").grid(row=0, column=3, sticky="ew")
        self.output_button = ttk.Button(output, text=self._tr('另存为…'), command=self.choose_output)
        self.output_button.grid(row=0, column=4, padx=(8, 0))

        footer = ttk.Frame(root, padding=(18, 4, 18, 6))
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        actions = ttk.Frame(footer)
        actions.grid(row=0, column=0, sticky="ew")
        self.export_button = ttk.Button(actions, text=self._tr('导出并打开 HTML'), style="Primary.TButton", command=self.start_export)
        self.export_button.pack(side="right")
        self.cancel_button = ttk.Button(actions, text=self._tr('取消当前任务'), command=self.cancel)
        self.cancel_button.pack(side="right", padx=(0, 8))
        self.open_button = ttk.Button(actions, text=self._tr('打开结果'), command=self.open_result)
        self.open_button.pack(side="left")
        self.folder_button = ttk.Button(actions, text=self._tr('任务文件夹'), command=self.open_folder)
        self.folder_button.pack(side="left", padx=(8, 0))
        self.credit_label = ttk.Label(actions, text="Designed by Symn", style="Credit.TLabel")
        self.credit_label.pack(side="left", padx=(18, 0))
        self.progress = ttk.Progressbar(footer, mode="indeterminate")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(3, 2))
        ttk.Label(footer, textvariable=self.status, wraplength=1150).grid(row=2, column=0, sticky="w")
        self.log = tk.Text(footer, height=1, state="disabled", wrap="word", relief="flat", background="#e9edf1",
                           foreground="#4f5c6b", font=("Microsoft YaHei UI", 9), padx=8, pady=3)
        self.log.grid(row=3, column=0, sticky="ew", pady=(4, 0))

    def _build_derived_tab(self):
        tab = ttk.Frame(self.content_tabs, padding=10)
        self.content_tabs.add(tab, text=self._tr('已有后处理'))
        self.derived_tab = tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        ttk.Label(tab, text=self._tr('选择源仿真中已有的面对象；可与壁面一起导出。'), style="Muted.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self._entry(tab, "derived_search", inventory=True).grid(row=1, column=0, sticky="ew", pady=(6, 6))
        ttk.Label(tab, text=self._tr('搜索后处理'), style="Muted.TLabel").grid(row=1, column=1, padx=(8, 0))
        self.derived_tree = ttk.Treeview(tab, columns=("type", "field"), show="tree headings", height=4, selectmode="extended")
        self.derived_tree.heading("#0", text=self._tr('对象 / 所属场景'))
        self.derived_tree.heading("type", text=self._tr('类型'))
        self.derived_tree.heading("field", text=self._tr('场景着色'))
        self.derived_tree.column("#0", width=250, minwidth=150, stretch=True)
        self.derived_tree.column("type", width=100, minwidth=75, stretch=False)
        self.derived_tree.column("field", width=140, minwidth=80, stretch=False)
        self.derived_tree.grid(row=2, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.derived_tree.yview)
        scrollbar.grid(row=2, column=1, sticky="ns")
        self.derived_tree.configure(yscrollcommand=scrollbar.set)
        self.derived_tree.bind("<<TreeviewSelect>>", self._derived_selected)
        summary = ttk.Frame(tab)
        summary.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        ttk.Label(summary, textvariable=self.derived_summary, style="Muted.TLabel").pack(side="left")
        clear = ttk.Button(summary, text=self._tr('清空选择'), command=self.clear_derived)
        clear.pack(side="right")
        self._inventory_controls.append(clear)
        settings = ttk.Frame(tab)
        settings.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text=self._tr('图层着色')).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.layer_field_combo = ttk.Combobox(settings, textvariable=self.vars["layer_function"], state="readonly")
        self.layer_field_combo.grid(row=0, column=1, columnspan=5, sticky="ew")
        self._inventory_controls.append(self.layer_field_combo)
        ttk.Label(settings, text=self._tr('颜色下限 / 上限')).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._entry(settings, "layer_min", width=7, inventory=True).grid(row=1, column=1, sticky="ew", pady=(6, 0))
        self._entry(settings, "layer_max", width=7, inventory=True).grid(row=1, column=2, sticky="ew", padx=(5, 8), pady=(6, 0))
        ttk.Label(settings, text=self._tr('不透明度')).grid(row=1, column=3, sticky="w", pady=(6, 0))
        self._entry(settings, "layer_opacity", width=5, inventory=True).grid(row=1, column=4, sticky="ew", pady=(6, 0))
        ttk.Label(settings, text="0–1", style="Muted.TLabel").grid(row=1, column=5, padx=(5, 0), pady=(6, 0))
        settings.columnconfigure(2, weight=1)
        ttk.Label(settings, text=self._tr('范围留空自动取值；仅改变显示。不透明度 1 为完全不透明。'), style="Muted.TLabel", wraplength=450).grid(row=2, column=0, columnspan=6, sticky="w", pady=(6, 0))
        ttk.Label(tab, text=self._tr('已有截面保留原位置；“仅几何”使用纯色，不携带场值。'), style="Muted.TLabel", wraplength=450).grid(row=5, column=0, columnspan=2, sticky="w", pady=(5, 0))

    def choose_sim(self):
        selected = filedialog.askopenfilename(parent=self.root, title=self._tr('选择已求解的 STAR-CCM+ 仿真'),
                                              filetypes=[(self._tr('STAR-CCM+ 仿真'), "*.sim"), (self._tr('所有文件'), "*.*")])
        if selected:
            self.vars["sim"].set(selected)
            self.vars["title"].set(Path(selected).stem)
            self.vars["output"].set(str(self.output_root / (Path(selected).stem + "-review.html")))

    def choose_star(self):
        selected = filedialog.askopenfilename(parent=self.root, title=self._tr('选择 STAR-CCM+ 程序'),
                                              filetypes=[(self._tr('STAR-CCM+ 程序'), "starccm+*"), (self._tr('所有文件'), "*.*")])
        if selected:
            self.vars["star"].set(selected)

    def choose_output(self):
        current = Path(self.vars["output"].get()) if self.vars["output"].get() else self.output_root / "review.html"
        selected = filedialog.asksaveasfilename(parent=self.root, title=self._tr('保存离线 HTML'), defaultextension=".html",
                                                initialdir=str(current.parent), initialfile=current.name,
                                                confirmoverwrite=False, filetypes=[(self._tr('HTML 网页'), "*.html")])
        if selected:
            self.vars["output"].set(selected)

    def choose_template(self):
        current = Path(self.vars["template"].get()) if self.vars["template"].get() else self.template_root
        selected = filedialog.askdirectory(parent=self.root, title=self._tr('选择含 template.json 的本地模板文件夹'),
                                          initialdir=str(current), mustexist=True)
        if not selected:
            return
        try:
            from .templates import validate_template
            info = validate_template(selected)
            selected = str(Path(selected).expanduser().resolve())
            name = " ".join(str(info.get("name") or Path(selected).name).split())
            self.vars["template"].set(selected)
            self._set_text(self.template_summary, self._tr('模板：{v0}', v0=name if len(name) <= 20 else name[:19] + "…"))
            self._set_text(self.status, self._tr('已选择本地模板：{v0}', v0=selected))
        except (ValueError, OSError) as error:
            self._error(self._tr('模板无法使用：{v0}；请检查 template.json 与本地素材。', v0=error))

    def reset_template(self):
        self.vars["template"].set("")
        self._set_text(self.template_summary, self._tr('模板：内置默认'))
        self._set_text(self.status, self._tr('已恢复内置 HTML 模板。当前仿真选择与导出设置保持原样。'))

    def _source_changed(self, *_):
        self.inventory = None
        self._inventory_sim = None
        self._all_boundaries = []
        self._selected_boundaries.clear()
        self.boundary_items.clear()
        self.boundary_tree.delete(*self.boundary_tree.get_children())
        self._all_derived = []
        self._selected_derived.clear()
        self.derived_items.clear()
        self.derived_tree.delete(*self.derived_tree.get_children())
        self._boundary_bounds.clear()
        self._selection_bounds = None
        self._last_auto_bounds = None
        self._representation_names.clear()
        self._representations = []
        self.representation_combo.configure(values=[])
        self._set_text(self.representation_hint, self._tr('读取仿真后自动选择可导出的计算体网格。'))
        self._set_text(self.bounds_summary, self._tr('选择车体壁面后自动填写 X 范围。'))
        self.region_list.configure(state="normal")
        self.region_list.delete(0, tk.END)
        for key in ("representation", "cp_function", "cpt_function"):
            self.vars[key].set("")
        self.vars["half_car"].set(False)
        self.vars["section_enabled"].set(False)
        for key in ("x_start", "x_end", "x_list"):
            self.vars[key].set("")
        self._set_text(self.inventory_summary, self._tr('尚未读取仿真内容'))
        self._set_text(self.selection_summary, self._tr('已选 0 个边界'))
        self._set_text(self.derived_summary, self._tr('读取后显示可导出的等值面、平面与表面。'))
        self.vars["layer_function"].set(self._tr('沿用各自场景场函数'))
        self.vars["layer_min"].set("")
        self.vars["layer_max"].set("")
        self.vars["layer_units"].set("")
        self._refresh_state()

    def _np(self):
        try:
            value = int(self.vars["np"].get())
        except ValueError:
            raise ValueError(self._tr('并行进程 np 请输入 1–256 的整数。')) from None
        if not 1 <= value <= 256:
            raise ValueError(self._tr('并行进程 np 请输入 1–256 的整数。'))
        return value

    def inspect_sim(self):
        try:
            sim = self.vars["sim"].get().strip()
            if not sim:
                raise ValueError(self._tr('请先选择已求解的 .sim 文件。'))
            self.controller.inspect(sim, star=self.vars["star"].get().strip() or None, np=self._np())
            self._source_changed()
            self._set_working(True, self._tr('正在读取保存状态，完成后可选择表面与场函数…'))
        except (ValueError, OSError, RuntimeError) as error:
            self._error(str(error))

    def apply_inventory(self, inventory):
        self.inventory = inventory
        self._inventory_sim = str(Path(self.vars["sim"].get()).expanduser().resolve())
        self._selected_boundaries.clear()
        self._all_boundaries = []
        self._boundary_bounds.clear()
        for detail in inventory.get("boundaryDetails", []):
            self._boundary_bounds[(detail.get("region"), detail.get("name"))] = detail.get("bounds")
        self.region_list.configure(state="normal")
        self.region_list.delete(0, tk.END)
        for region in inventory.get("regions", []):
            name = region["name"]
            for detail in region.get("boundaryDetails", []):
                self._boundary_bounds[(name, detail.get("name"))] = detail.get("bounds")
            self.region_list.insert(tk.END, name)
            for boundary in region.get("boundaries", []):
                # The native inventory emits names; accepting name records keeps UI tests simple.
                boundary_name = boundary["name"] if isinstance(boundary, dict) else boundary
                self._all_boundaries.append({"region": name, "name": boundary_name})
        self.vars["search"].set("")
        self._render_boundaries()
        from .desktop import exportable_representations
        try:
            representations = exportable_representations(inventory)
            mesh_message = self._tr('读取保存场；配色仅影响显示。')
            if not representations:
                mesh_message = self._tr('当前文件没有可导出的体网格；请选择已保存体网格和求解场的 .sim。')
        except ValueError:
            representations = []
            mesh_message = self._tr('网格清单缺少类型和单元数；请重新点击“读取仿真内容”。')
        self._representations = representations
        self._representation_names = {
            self._tr('计算体网格 · {v0}（{v1:,} 单元）', v0=row['name'], v1=row['cellCount']): row["name"]
            for row in representations
        }
        self.representation_combo.configure(values=list(self._representation_names))
        self.vars["representation"].set(next(iter(self._representation_names), ""))
        self._set_text(self.representation_hint, mesh_message)
        field_names = sorted({f["functionName"] for f in inventory.get("fields", [])
                              if f.get("functionName") and str(f.get("type", "SCALAR")).upper() == "SCALAR"})
        for key, default in (("cp_function", "PressureCoefficient"), ("cpt_function", "TotalPressureCoefficient")):
            self.field_combos[key].configure(values=[self._tr('不导出')] + ([default] if default in field_names else []))
            self.vars[key].set(default if default in field_names else self._tr('不导出'))
        self.layer_field_combo.configure(values=[self._tr('沿用各自场景场函数'), self._tr('仅几何')] + field_names)
        self._populate_derived(inventory, field_names)
        version = inventory.get("starVersion", "")
        steps = inventory.get("iteration")
        text = self._tr('{v0} 个边界 · STAR {v1}', v0=len(self._all_boundaries), v1=version)
        if steps is not None:
            text = self._tr('{v0} 个边界 · STAR {v1} · {v2} 步', v0=len(self._all_boundaries), v1=version, v2=steps)
        self._set_text(self.inventory_summary, text)
        self._show_references()
        self._update_x_bounds()
        self._refresh_state()
        if not self._representation_names:
            self._set_text(self.status, mesh_message)

    @staticmethod
    def _x_extent(bounds):
        if not isinstance(bounds, dict) or bounds.get("units") != "m":
            return None
        low, high = bounds.get("min"), bounds.get("max")
        if not isinstance(low, (list, tuple)) or not isinstance(high, (list, tuple)) or len(low) != 3 or len(high) != 3:
            return None
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in (*low, *high)):
            return None
        if low[0] > high[0]:
            return None
        return float(low[0]), float(high[0])

    def _update_x_bounds(self, force=False):
        # Vehicle-wall extents define car length; a downstream wake is a separate layer.
        if self._selected_boundaries:
            extents = [self._x_extent(self._boundary_bounds.get(key)) for key in self._selected_boundaries]
            source = self._tr('所选壁面')
        else:
            extents = [self._x_extent(part.get("bounds")) for part in self._all_derived
                       if part["name"] in self._selected_derived]
            source = self._tr('所选后处理面')
        self._selection_bounds = None
        if not extents:
            self._set_text(self.bounds_summary, self._tr('选择车体壁面后自动填写 X 范围。'))
        elif any(extent is None for extent in extents):
            self._set_text(self.bounds_summary, self._tr('选择车体壁面可自动填写 X；也可手动设置。') if not self._selected_boundaries
                                    else self._tr('所选壁面坐标范围尚未完整取得，可手动填写。'))
        else:
            start, end = min(e[0] for e in extents), max(e[1] for e in extents)
            if start == end:
                self._set_text(self.bounds_summary, self._tr('{v0}位于 X={v1:.5g} m，可手动扩展。', v0=source, v1=start))
            else:
                self._selection_bounds = (start, end)
                self._set_text(self.bounds_summary, self._tr('{v0} X：{v1:.5g} 至 {v2:.5g} m，可手动扩展。', v0=source, v1=start, v2=end))
                current = (self.vars["x_start"].get(), self.vars["x_end"].get())
                if force or all(not value for value in current) or current == self._last_auto_bounds:
                    formatted = (f"{start:.12g}", f"{end:.12g}")
                    self.vars["x_start"].set(formatted[0])
                    self.vars["x_end"].set(formatted[1])
                    self._last_auto_bounds = formatted
        self.bounds_button.configure(state="normal" if self._selection_bounds is not None and not self._working else "disabled")

    def use_selection_bounds(self):
        self._update_x_bounds(force=True)
        if self._selection_bounds is not None:
            self.vars["x_list"].set("")
            self._set_text(self.status, self._tr('已将 X 起终点设为所选对象范围；可直接设置截面数量。'))

    def _populate_derived(self, inventory, scalar_names):
        self._all_derived = []
        self._selected_derived.clear()
        scene_parts = {}
        for scene in inventory.get("sceneDetails", []):
            for displayer in scene.get("displayers", []):
                for name in displayer.get("derivedPartNames", displayer.get("inputPartNames", [])):
                    previous = scene_parts.get(name)
                    if previous is None or (previous.get("sceneFieldFunction") not in scalar_names and displayer.get("fieldFunction") in scalar_names):
                        scene_parts[name] = {"scene": scene["name"], "sceneFieldFunction": displayer.get("fieldFunction")}
        for detail in inventory.get("derivedPartDetails", []):
            # A mesh-capable type is confirmed by the adapter, not guessed from its label.
            if detail.get("exportableMesh") is not True:
                continue
            part = dict(detail)
            part.update(scene_parts.get(part["name"], {}))
            if part.get("sceneFieldFunction") not in scalar_names:
                part.pop("sceneFieldFunction", None)
            self._all_derived.append(part)
        self.vars["derived_search"].set("")
        self._render_derived()

    def _render_derived(self):
        self._rebuilding_derived = True
        self.derived_tree.delete(*self.derived_tree.get_children())
        self.derived_items.clear()
        query = self.vars["derived_search"].get().strip().casefold()
        groups = {}
        selected = []
        for index, part in enumerate(self._all_derived):
            name = part["name"]
            kind = part.get("type", "")
            type_label = {
                "IsoPart": self._tr('等值面'), "PlaneSection": self._tr('平面截面'),
                "ThresholdPart": self._tr('阈值面'), "CylinderSection": self._tr('圆柱截面'),
                "SphereSection": self._tr('球面截面'), "ArbitrarySection": self._tr('自定义截面'),
            }.get(kind, kind)
            scene = part.get("scene", self._tr('其他派生部件'))
            if query and query not in (name + " " + kind + " " + type_label + " " + scene).casefold():
                continue
            if scene not in groups:
                group = "s" + str(len(groups))
                self.derived_tree.insert("", "end", iid=group, text=scene, open=True)
                groups[scene] = group
            item = f"d{index:05d}"
            self.derived_tree.insert(groups[scene], "end", iid=item, text=name,
                                     values=(type_label, part.get("sceneFieldFunction", self._tr('纯色（无场值）'))))
            self.derived_items[item] = part
            if name in self._selected_derived:
                selected.append(item)
        if selected:
            self.derived_tree.selection_set(selected)
        self._rebuilding_derived = False
        total = len(self._all_derived)
        self._set_text(self.derived_summary, self._tr('已选 {v0} / {v1} 个面对象', v0=len(self._selected_derived), v1=total) if total else self._tr('当前清单尚无可导出的面对象。'))

    def _derived_selected(self, _event=None):
        if self._rebuilding_derived:
            return
        visible = {p["name"] for p in self.derived_items.values()}
        self._selected_derived.difference_update(visible)
        for item in self.derived_tree.selection():
            if item in self.derived_items:
                self._selected_derived.add(self.derived_items[item]["name"])
        self._set_text(self.derived_summary, self._tr('已选 {v0} / {v1} 个面对象', v0=len(self._selected_derived), v1=len(self._all_derived)))
        self._update_x_bounds()

    def clear_derived(self):
        self._selected_derived.clear()
        self.derived_tree.selection_remove(self.derived_tree.selection())
        self._set_text(self.derived_summary, self._tr('已选 0 / {v0} 个面对象', v0=len(self._all_derived)))
        self._update_x_bounds()

    def _layer_options(self):
        self._derived_selected()
        parts = [p for p in self._all_derived if p["name"] in self._selected_derived]
        if not parts:
            return []
        try:
            opacity = float(self.vars["layer_opacity"].get())
        except ValueError:
            raise ValueError(self._tr('图层不透明度请输入 0–1 的数值。')) from None
        if not math.isfinite(opacity) or not 0 <= opacity <= 1:
            raise ValueError(self._tr('图层不透明度请输入 0–1 的有限数值。'))
        raw_range = [self.vars["layer_min"].get().strip(), self.vars["layer_max"].get().strip()]
        color_range = None
        if any(raw_range):
            try:
                color_range = [float(v) for v in raw_range]
            except ValueError:
                raise ValueError(self._tr('图层颜色范围请同时填写有效下限与上限，或同时留空。')) from None
            if not all(math.isfinite(v) for v in color_range) or color_range[0] >= color_range[1]:
                raise ValueError(self._tr('图层颜色下限应小于上限，且均为有限值。'))
        choice = self.vars["layer_function"].get()
        result = []
        for index, part in enumerate(parts):
            layer = {"id": f"layer-{index + 1}", "name": part["name"], "derivedPart": part["name"],
                     "opacity": opacity, "visible": True}
            field = part.get("sceneFieldFunction") if choice == self._tr('沿用各自场景场函数') else (None if choice == self._tr('仅几何') else choice)
            if field:
                layer.update(fieldFunction=field, field=field)
                if self.vars["layer_units"].get().strip():
                    layer["units"] = self.vars["layer_units"].get().strip()
                if color_range is not None:
                    layer["colorRange"] = color_range
            criterion = part.get("criterion") or part.get("scalarFunction")
            if criterion:
                layer["criterion"] = criterion
            if part.get("threshold") is not None:
                layer["threshold"] = part["threshold"]
            result.append(layer)
        return result

    def _render_boundaries(self):
        self._rebuilding_tree = True
        self.boundary_tree.delete(*self.boundary_tree.get_children())
        self.boundary_items.clear()
        query = self.vars["search"].get().strip().casefold()
        groups = {}
        selected = []
        for index, boundary in enumerate(self._all_boundaries):
            key = (boundary["region"], boundary["name"])
            if query and query not in (boundary["region"] + " " + boundary["name"]).casefold():
                continue
            if boundary["region"] not in groups:
                group = "r" + str(len(groups))
                self.boundary_tree.insert("", "end", iid=group, text=boundary["region"], open=True)
                groups[boundary["region"]] = group
            item = f"b{index:05d}"
            self.boundary_tree.insert(groups[boundary["region"]], "end", iid=item, text=boundary["name"])
            self.boundary_items[item] = boundary
            if key in self._selected_boundaries:
                selected.append(item)
        if selected:
            self.boundary_tree.selection_set(selected)
        self._rebuilding_tree = False
        self._set_text(self.selection_summary, self._tr('已选 {v0} 个边界', v0=len(self._selected_boundaries)))
        self._update_x_bounds()

    def _boundary_selected(self, _event=None):
        if self._rebuilding_tree:
            return
        visible = {(b["region"], b["name"]) for b in self.boundary_items.values()}
        self._selected_boundaries.difference_update(visible)
        for item in self.boundary_tree.selection():
            if item in self.boundary_items:
                b = self.boundary_items[item]
                self._selected_boundaries.add((b["region"], b["name"]))
        self._set_text(self.selection_summary, self._tr('已选 {v0} 个边界', v0=len(self._selected_boundaries)))
        self._update_x_bounds()

    def clear_boundaries(self):
        self._selected_boundaries.clear()
        self.boundary_tree.selection_remove(self.boundary_tree.selection())
        self._set_text(self.selection_summary, self._tr('已选 0 个边界'))
        self._update_x_bounds()

    def _show_references(self):
        if not self.inventory:
            self._set_text(self.reference_hint, self._tr('使用仿真中已有的系数场函数及其参考量。'))
            return
        references = []
        for label, key in (("Cp", "cp_function"), ("CpT", "cpt_function")):
            field = next((f for f in self.inventory.get("fields", [])
                          if f.get("functionName") == self.vars[key].get()), {})
            ref = field.get("coefficientReference")
            if ref:
                references.append(f"{label}: ρ={ref.get('densityKgM3')} kg/m³, U={ref.get('velocityMS')} m/s, p={ref.get('pressurePa')} Pa")
        self._set_text(self.reference_hint, "; ".join(references) if references else self._tr('场函数沿用源仿真定义；请按本工况确认系数的参考量。'))

    def _collect_options(self):
        if self.inventory is None or self._inventory_sim != str(Path(self.vars["sim"].get()).expanduser().resolve()):
            raise ValueError(self._tr('请先读取当前仿真内容。'))
        representation = self._representation_names.get(self.vars["representation"].get())
        if representation is None:
            raise ValueError(self.representation_hint.get() if not self._representation_names
                             else self._tr('请选择清单中可导出的计算体网格。'))
        self._boundary_selected()
        selected = [b for b in self._all_boundaries if (b["region"], b["name"]) in self._selected_boundaries]
        layers = self._layer_options()
        if not selected and not layers:
            raise ValueError(self._tr('请选择至少一个壁面边界，或在“已有后处理”中选择面对象。'))
        fields = {label: "" if self.vars[key].get() == self._tr('不导出') else self.vars[key].get()
                  for label, key in (("Cp", "cp_function"), ("CpT", "cpt_function"))}
        if (selected or self.vars["section_enabled"].get()) and not any(fields.values()):
            raise ValueError(self._tr('导出壁面或新截面时，请至少选择一个已有的 Cp 或 CpT 系数场函数。'))
        ranges = {}
        for field, lo, hi in (("Cp", "cp_min", "cp_max"), ("CpT", "cpt_min", "cpt_max")):
            try:
                limits = [float(self.vars[lo].get()), float(self.vars[hi].get())]
            except ValueError:
                raise ValueError(self._tr('{v0} 显示范围请输入有效数值。', v0=field)) from None
            if not all(math.isfinite(v) for v in limits) or limits[0] >= limits[1]:
                raise ValueError(self._tr('{v0} 显示下限应小于上限，且均为有限值。', v0=field))
            ranges[field] = limits
        sections = []
        regions = []
        if self.vars["section_enabled"].get():
            try:
                if self.vars["x_list"].get().strip():
                    sections = [float(v) for v in re.split(r"[,，;；\s]+", self.vars["x_list"].get().strip()) if v]
                else:
                    start = float(self.vars["x_start"].get())
                    end = float(self.vars["x_end"].get())
                    count = int(self.vars["x_count"].get())
                    if not 2 <= count <= 1000 or start >= end:
                        raise ValueError
                    sections = [start + (end - start) * i / (count - 1) for i in range(count)]
            except (ValueError, OverflowError):
                raise ValueError(self._tr('请填写递增的 X 列表，或起点、终点与 2–1000 的整数截面数。')) from None
            if not sections or len(sections) > 1000 or not all(math.isfinite(v) for v in sections) or any(a >= b for a, b in zip(sections, sections[1:])):
                raise ValueError(self._tr('X 截面坐标应为有限值并严格递增，最多 1000 个。'))
            regions = [self.region_list.get(i) for i in self.region_list.curselection()]
            if not regions:
                raise ValueError(self._tr('请选择截面所在的流体区域。'))
        output = self.vars["output"].get().strip()
        if not output:
            raise ValueError(self._tr('请选择 HTML 保存位置。'))
        target = Path(output).expanduser().resolve()
        if target.suffix.lower() not in (".html", ".htm"):
            raise ValueError(self._tr('输出文件请使用 .html 或 .htm 扩展名。'))
        if target.exists():
            raise ValueError(self._tr('该 HTML 已存在，请选择新的文件名以保留原文件。'))
        return {"sim": self.vars["sim"].get().strip(), "output_html": str(target),
                "title": self.vars["title"].get().strip() or Path(self.vars["sim"].get()).stem,
                "representation": representation, "cp_function": fields["Cp"], "cpt_function": fields["CpT"],
                "surfaces": [{"id": f"boundary-{i + 1}", "name": b["region"] + " / " + b["name"], "boundaries": [dict(b)]}
                             for i, b in enumerate(selected)],
                "layers": layers,
                "section_regions": regions, "x_sections": sections, "ranges": ranges,
                "surface_range": ranges["Cp"], "half_car": bool(self.vars["half_car"].get()),
                "star": self.vars["star"].get().strip() or None, "np": self._np(),
                "template": self.vars["template"].get().strip() or None, "language": self.language}

    def start_export(self):
        try:
            options = self._collect_options()
            self.controller.export(options)
            self._set_working(True, self._tr('正在从保存场导出表面与截面，完成后自动打开 HTML…'))
        except (ValueError, OSError, RuntimeError) as error:
            self._error(str(error))

    def _set_working(self, working, message=None):
        self._working = working
        if working:
            self.progress.start(12)
        else:
            self.progress.stop()
        if message:
            self._set_text(self.status, message)
            self._append_log(message)
        self._refresh_state()

    def _refresh_state(self):
        busy = self._working or self._closing
        for control in self._editable:
            control.configure(state="disabled" if busy else "normal")
        for control in self._inventory_controls:
            state = "disabled" if busy or self.inventory is None else ("readonly" if isinstance(control, ttk.Combobox) else "normal")
            control.configure(state=state)
        sections = not busy and self.inventory is not None and self.vars["section_enabled"].get()
        for control in self._section_controls:
            control.configure(state="normal" if sections else "disabled")
        self.region_list.configure(state="normal" if sections else "disabled")
        self.boundary_tree.configure(selectmode="none" if busy or self.inventory is None else "extended")
        self.derived_tree.configure(selectmode="none" if busy or self.inventory is None else "extended")
        self.bounds_button.configure(state="normal" if self._selection_bounds is not None and not busy else "disabled")
        for control in (self.sim_button, self.star_button, self.output_button, self.template_button, self.template_reset_button):
            control.configure(state="disabled" if busy else "normal")
        self.read_button.configure(state="normal" if not busy and bool(self.vars["sim"].get().strip()) else "disabled")
        self.representation_combo.configure(state="readonly" if not busy and self._representation_names else "disabled")
        self.export_button.configure(state="normal" if not busy and self.inventory is not None and self._representation_names else "disabled")
        self.cancel_button.configure(state="normal" if self._working and not self._closing else "disabled")
        self.open_button.configure(state="normal" if self._last_html and not busy else "disabled")
        self.folder_button.configure(state="normal" if (self._last_html or self._last_job) and not busy else "disabled")

    def poll_events(self):
        self._timer = None
        try:
            while True:
                self._handle_event(self.controller.events.get_nowait())
        except queue.Empty:
            pass
        if self._closing and not getattr(self.controller, "busy", False):
            self.root.destroy()
            return
        if self.root.winfo_exists():
            self._timer = self.root.after(100, self.poll_events)

    def _handle_event(self, event):
        kind = event.get("type")
        raw_message = event.get("message", "")
        message = self._tr(raw_message)
        if event.get("job_directory"):
            self._last_job = Path(event["job_directory"])
        if kind == "status":
            self._set_text(self.status, message)
            self._append_log(raw_message)
        elif kind == "inventory":
            same_source = not event.get("sim") or str(Path(event["sim"]).expanduser().resolve()) == str(Path(self.vars["sim"].get()).expanduser().resolve())
            if same_source:
                self.apply_inventory(event["inventory"])
                self._set_working(False, (message or self._tr('已读取保存状态。选择壁面与需要的场函数后即可导出。'))
                                  if self._representation_names else self.representation_hint.get())
            else:
                self._set_working(False, self._tr('文件已切换，请读取当前仿真内容。'))
        elif kind == "complete":
            self._last_html = Path(event["html"]).resolve()
            self._set_working(False, message or self._tr('导出完成：{v0}', v0=self._last_html))
            self.open_result()
        elif kind == "cancelled":
            self._set_working(False, message or self._tr('当前任务已取消。可以重新读取或调整导出内容。'))
        elif kind == "error":
            self._set_working(False)
            if message.startswith(("Owned STAR stopped by memory guard", "Insufficient initial memory:")):
                self._error(self._tr('内存不足，本次任务已由保护机制停止。请关闭其他大程序，尝试将并行进程 np 设为 2，并减少本次导出的截面或等值面；点击“任务文件夹”查看日志。'))
                self._append_log(message)
            elif message.startswith(("document: JSON structure limit exceeded",
                                     "document: JSON numeric-data limit exceeded",
                                     "document: JSON nesting depth limit exceeded",
                                     "document: JSON complexity limit exceeded")):
                self._error(self._tr('导出数据量或嵌套层级超出本版限制。请减少本次选择的截面或图层，或分开导出；点击“任务文件夹”查看原始计数和日志。'))
                self._append_log(message)
            else:
                self._error(message or self._tr('任务失败，请查看任务日志后重试。'))

    def _append_log(self, message):
        self.log.configure(state="normal")
        self.log.insert(tk.END, str(message) + "\n")
        if int(self.log.index("end-1c").split(".")[0]) > 200:
            self.log.delete("1.0", "50.0")
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    def _error(self, message):
        message = self._tr(message)
        self._set_text(self.status, message)
        self._append_log(message)
        messagebox.showerror("StarCapsule Studio", message, parent=self.root)

    def cancel(self):
        self.controller.cancel()
        self._set_text(self.status, self._tr('正在取消当前任务并清理本次 STAR 进程…'))
        self.cancel_button.configure(state="disabled")

    def open_result(self):
        if self._last_html and self._last_html.is_file():
            webbrowser.open(self._last_html.as_uri())

    def open_folder(self):
        folder = self._last_job if self._last_job else (self._last_html.parent if self._last_html else None)
        if folder and folder.is_dir():
            if os.name == "nt":
                os.startfile(str(folder))
            else:
                webbrowser.open(folder.as_uri())

    def close(self):
        if getattr(self.controller, "busy", False) or self._working:
            if not messagebox.askyesno(self._tr('退出 StarCapsule Studio'), self._tr('取消当前读取 / 导出任务并退出？'), parent=self.root):
                return
            self._closing = True
            self.controller.cancel()
            self._set_text(self.status, self._tr('正在结束本次任务，完成后退出…'))
            self._refresh_state()
        else:
            if self._timer is not None:
                self.root.after_cancel(self._timer)
            self.root.destroy()


def main():
    try:
        root = tk.Tk()
    except tk.TclError as error:
        print(f"StarCapsule Studio cannot open a desktop window: {error}")
        return 1
    try:
        ExportApp(root)
        root.mainloop()
        return 0
    except Exception as error:
        messagebox.showerror("StarCapsule Studio", translate('启动失败：{v0}', language=load_language(), v0=error), parent=root)
        root.destroy()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
