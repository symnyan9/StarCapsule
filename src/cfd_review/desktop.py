"""Small, asynchronous desktop workflow around the existing native STAR adapter.

The GUI selects exact inventoried objects. This module never guesses pressure
references, opens a SIM itself, or calls a solver. Worker messages use Queue so
Tk widgets are touched only by the main thread.
"""
from __future__ import annotations

import copy
from collections import Counter
import json
import math
from pathlib import Path
from queue import Queue
import threading
import time
import uuid

from .mesh_io import sha256
from .report import build_report, project_from_cases
from .star import CancelledError, _check_cancelled, export_sim, inspect_sim
from .templates import validate_template


def exportable_representations(inventory):
    """Return exact populated FV sources, never infer eligibility from a name.

    Older inventories must be read again: a list of presentation names cannot
    distinguish real finite-volume data from geometry or a latest-mesh proxy.
    Native mesh presence is not a convergence or solution-quality claim.
    """
    if (not isinstance(inventory, dict) or
            not isinstance(inventory.get("representationDetails"), list) or
            not isinstance(inventory.get("representations"), list)):
        raise ValueError("网格清单缺少原生类型与单元数，请重新点击“读取仿真内容”")
    names = inventory["representations"]
    details = inventory["representationDetails"]
    # Ambiguous duplicate source names cannot be selected exactly.
    raw_counts = Counter(name for name in names if isinstance(name, str))
    detail_counts = Counter(row["name"] for row in details
                            if isinstance(row, dict) and isinstance(row.get("name"), str))
    result = []
    for row in details:
        if not isinstance(row, dict):
            continue
        name, count = row.get("name"), row.get("cellCount")
        if (not isinstance(name, str) or not name.strip() or
                raw_counts.get(name) != 1 or detail_counts.get(name) != 1 or
                not isinstance(row.get("type"), str) or not row["type"].strip() or
                row.get("isFiniteVolume") is not True or row.get("exportable") is not True or
                type(count) is not int or count <= 0):
            continue
        result.append(copy.deepcopy(row))
    return sorted(result, key=lambda row: (row["name"] != "Volume Mesh", row["name"]))


def _identity(path):
    before = path.stat()
    digest = sha256(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("SIM changed while its identity was being checked; inspect it again")
    return {"sha256": digest, "size": after.st_size, "mtimeNs": after.st_mtime_ns}


def _sim_path(value):
    path = Path(value).expanduser().resolve()
    if path.suffix.lower() != ".sim" or not path.is_file():
        raise ValueError("请选择一个已保存的 STAR .sim 文件")
    return path


def _np(value):
    if type(value) is not int or value < 1:
        raise ValueError("np 必须为正整数")
    return value


def _range(value, name):
    if (not isinstance(value, list) or len(value) != 2 or
            any(type(v) not in (int, float) or not math.isfinite(v) for v in value) or
            value[0] >= value[1]):
        raise ValueError(f"{name} 需要有限数值 [最小值, 最大值]，且最小值小于最大值")
    return list(value)


def _json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


class DesktopController:
    """One owned background job; inspect/export return a joinable Thread.

    A terminal event is queued only after ``busy`` becomes false. Logs, native
    exports and receipts stay in a unique job directory; only the chosen final
    HTML is copied to the user's destination.
    """

    def __init__(self, work_root):
        self.work_root = Path(work_root).expanduser().resolve()
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.events = Queue()
        self._lock = threading.Lock()
        self._busy = False
        self._cancel_event = None
        self._inventory = None
        self._inventory_identity = None
        self._source_path = None
        self.last_job_directory = None
        self.worker = None

    @property
    def busy(self):
        with self._lock:
            return self._busy

    @property
    def inventory(self):
        with self._lock:
            return copy.deepcopy(self._inventory)

    @property
    def inventory_identity(self):
        with self._lock:
            return copy.deepcopy(self._inventory_identity)

    @property
    def source_path(self):
        with self._lock:
            return self._source_path

    def _status(self, message, phase, job):
        self.events.put({"type": "status", "message": message, "phase": phase,
                         "job_directory": str(job)})

    def _start(self, operation, sim, action, clear_inventory=False):
        with self._lock:
            if self._busy:
                raise ValueError("已有任务正在运行，请等待完成或取消当前任务")
            job = self.work_root / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) +
                                    "-" + operation + "-" + uuid.uuid4().hex[:10])
            job.mkdir()
            self._busy = True
            self._cancel_event = threading.Event()
            self.last_job_directory = job
            if clear_inventory:
                self._inventory = self._inventory_identity = self._source_path = None
            self.worker = threading.Thread(target=self._work,
                args=(operation, sim, job, self._cancel_event, action),
                name="cfd-review-" + operation, daemon=True)
            worker = self.worker
        worker.start()
        return worker

    def _work(self, operation, sim, job, cancel, action):
        receipt = {"schema": "cfd-review-desktop-job", "version": 1,
                   "operation": operation, "sim": str(sim), "status": "running",
                   "startedUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        terminal = None
        try:
            _json(job / "desktop-job.json", receipt)
            terminal = action(job, cancel)
            receipt["status"] = "complete"
            if "html" in terminal:
                receipt["html"] = terminal["html"]
        except Exception as error:
            cancelled = isinstance(error, CancelledError)
            receipt.update(status="cancelled" if cancelled else "failed", error=str(error))
            terminal = {"type": "cancelled" if cancelled else "error", "message": str(error)}
        finally:
            receipt["finishedUtc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            try:
                _json(job / "desktop-job.json", receipt)
            except OSError as error:
                terminal = {"type": "error", "message": f"无法写入任务回执：{error}"}
            with self._lock:
                self._busy = False
            terminal["job_directory"] = str(job)
            self.events.put(terminal)

    def inspect(self, sim, star=None, np=2):
        """Read the saved source inventory in an owned native STAR process."""
        sim, np = _sim_path(sim), _np(np)

        def action(job, cancel):
            self._status("正在读取 SIM 对象清单并核验源文件；首次打开需要一些时间。", "inventory", job)
            result = inspect_sim(sim, job / "native", star=star, np=np,
                                 run=True, compile_api=True, cancel_event=cancel)
            _check_cancelled(cancel)
            inventory = result.get("inventory")
            if (result.get("status") != "complete" or result.get("sourceUnchanged") is not True or
                    not isinstance(inventory, dict) or inventory.get("schema") != "cfd-review-star-inventory"):
                raise ValueError("STAR 未返回通过源文件核验的完整对象清单")
            identity = result.get("sourceAfter") or result.get("sourceBefore")
            if not isinstance(identity, dict) or set(identity) != {"sha256", "size", "mtimeNs"}:
                raise ValueError("STAR 对象清单缺少完整的 SIM 身份回执")
            if result.get("sourceBefore") != identity:
                raise ValueError("SIM 在清单读取期间发生变化，请重新读取")
            _check_cancelled(cancel)
            with self._lock:
                self._inventory = copy.deepcopy(inventory)
                self._inventory_identity = copy.deepcopy(identity)
                self._source_path = str(sim)
            return {"type": "inventory", "message": "对象清单已读取。请选择表面、标量场与截面后导出。",
                    "inventory": inventory, "sim": str(sim), "identity": identity}

        return self._start("inventory", sim, action, clear_inventory=True)

    def _export_config(self, options, inventory, identity, sim):
        representation = options.get("representation")
        representations = exportable_representations(inventory)
        if representation not in {row["name"] for row in representations}:
            raise ValueError("请选择清单中具有单元数据的体网格；几何、代理与空网格不能导出结果")
        scalar_functions = {f.get("functionName"):f for f in inventory.get("fields", [])
                            if isinstance(f, dict) and str(f.get("type", "")).upper() == "SCALAR"}
        fields = {}
        for key, option in (("Cp", "cp_function"), ("CpT", "cpt_function")):
            name = options.get(option)
            if name:
                if name not in scalar_functions:
                    raise ValueError(f"{key} 必须选择当前 SIM 中的现有标量函数")
                fields[key] = {"function": name}
        exact_boundaries = {(r["name"], b) for r in inventory.get("regions", [])
                            for b in r.get("boundaries", [])}
        surfaces = copy.deepcopy(options.get("surfaces",[]))
        layers = copy.deepcopy(options.get("layers",[]))
        if not isinstance(surfaces, list) or not isinstance(layers,list) or not(surfaces or layers):
            raise ValueError("请至少选择一个壁面或已有后处理面")
        for surface in surfaces:
            if not isinstance(surface, dict):
                raise ValueError("表面选择格式错误")
            if surface.get("derivedPart"):
                if surface["derivedPart"] not in inventory.get("derivedParts", []):
                    raise ValueError("派生部件已与当前 SIM 清单失配")
            else:
                boundaries = surface.get("boundaries")
                if not isinstance(boundaries, list) or not boundaries:
                    raise ValueError("表面需要选择至少一个精确边界")
                for boundary in boundaries:
                    if (not isinstance(boundary, dict) or
                            (boundary.get("region"), boundary.get("name")) not in exact_boundaries):
                        raise ValueError("所选边界已与当前 SIM 清单失配")
        part_details={p.get("name"):p for p in inventory.get("derivedPartDetails",[]) if isinstance(p,dict)}
        for layer in layers:
            if not isinstance(layer,dict) or layer.get("derivedPart") not in inventory.get("derivedParts",[]):
                raise ValueError("后处理图层必须选择当前 SIM 中的精确派生部件")
            detail=part_details.get(layer["derivedPart"],{})
            if detail.get("exportableMesh") is not True:
                raise ValueError("所选后处理部件未通过原生三角面类型校验，请选择清单中支持的面部件")
            function=layer.get("fieldFunction")
            if function:
                if function not in scalar_functions:
                    raise ValueError("图层着色函数必须是当前 SIM 中的现有标量函数")
                layer["fieldFunction"]=function
                if scalar_functions[function].get("magnitudeOf"):
                    layer["magnitudeOf"]=scalar_functions[function]["magnitudeOf"]
                else:
                    layer.pop("magnitudeOf",None)
            else:
                layer.pop("fieldFunction",None)
                layer.pop("magnitudeOf",None)
                layer.pop("field",None)
            part_type=detail.get("type","")
            layer["sourcePartType"]=part_type
            layer["kind"]="section" if part_type=="PlaneSection" else ("isosurface" if part_type=="IsoPart" else "surface")
            for key in ("criterion","threshold","isoValues","thresholdRange"):
                if key in detail:
                    layer[key]=copy.deepcopy(detail[key])
        if len(representations) > 1 and any(layer.get("fieldFunction") for layer in layers):
            raise ValueError("当前 SIM 含多个有效体网格，已有后处理面的标量着色需要唯一体网格。"
                             "请将这些图层的着色改为“仅几何”，或使用仅含一个有效体网格的 SIM 副本；"
                             "壁面和新建 X 截面可继续使用所选网格导出。")
        x_sections = options.get("x_sections", [])
        if (not isinstance(x_sections, list) or
                any(type(x) not in (int, float) or not math.isfinite(x) for x in x_sections) or
                any(a >= b for a, b in zip(x_sections, x_sections[1:]))):
            raise ValueError("X 截面必须为严格递增的有限数值，单位 m")
        regions = options.get("section_regions", [])
        exact_regions = {r["name"] for r in inventory.get("regions", [])}
        if (not isinstance(regions, list) or any(r not in exact_regions for r in regions) or
                (x_sections and not regions)):
            raise ValueError("请为 X 截面选择当前 SIM 中的区域")
        title = options.get("title", sim.stem)
        if not isinstance(title, str) or not title.strip() or len(title) > 300:
            raise ValueError("标题需要 1–300 个字符")
        ranges = options.get("ranges")
        if not isinstance(ranges, dict):
            raise ValueError("请指定 Cp 与 CpT 的显示色标范围")
        ranges = {key: _range(ranges.get(key), key) for key in ("Cp", "CpT")}
        half_car = options.get("half_car")
        if type(half_car) is not bool:
            raise ValueError("请明确选择全模型或关于 Y=0 对称的半模型")
        meta = {"title": title.strip(), "source": sim.name, "sourceSha256": identity["sha256"],
                "units": "m", "axis": {"up": "z"}, "isDemo": False,
                "halfCar": half_car, "scalarMirror": half_car,
                "ranges": ranges, "surfaceRange": _range(options.get("surface_range"), "表面 Cp"),
                "coefficientReference": {"existingScalarFunctions": copy.deepcopy(fields)}}
        if half_car:
            meta["mirrorAxis"] = "y"
        config = {"schema": "cfd-review-star-config", "version": 1,
                  "id": "case-" + uuid.uuid4().hex[:16], "name": title.strip(),
                  "sim": str(sim), "representation": representation, "meta": meta,
                  "fields": fields, "surfaces": surfaces,
                  "sectionRegions": list(regions), "xSections": list(x_sections),"layers":layers}
        # Reuse the native trust-boundary validator before starting a job.
        from .star import _validate_config
        return _validate_config(config)

    def export(self, options):
        """Export inventoried selections and publish a new standalone HTML."""
        if not isinstance(options, dict):
            raise ValueError("导出选项需要为对象")
        options = copy.deepcopy(options)
        language = options.get("language", "en")
        if language not in ("en", "zh-CN"):
            raise ValueError("Language must be en or zh-CN")
        template=options.get("template") or None
        if template is not None:
            template=validate_template(template)["path"]
        with self._lock:
            if self._busy:
                raise ValueError("已有任务正在运行，请等待完成或取消当前任务")
            inventory = copy.deepcopy(self._inventory)
            identity = copy.deepcopy(self._inventory_identity)
            source_path = self._source_path
        if inventory is None or identity is None or source_path is None:
            raise ValueError("请先读取所选 SIM 的对象清单")
        sim = _sim_path(options.get("sim") or source_path)
        if str(sim) != source_path:
            raise ValueError("所选 SIM 与对象清单来源不同，请重新读取清单")
        stat = sim.stat()
        if (stat.st_size, stat.st_mtime_ns) != (identity["size"], identity["mtimeNs"]):
            raise ValueError("SIM 在读取清单后发生变化，请重新读取清单")
        output_html = options.get("output_html")
        if not isinstance(output_html, (str, Path)) or not str(output_html).strip():
            raise ValueError("请选择 HTML 导出位置")
        output_html = Path(output_html).expanduser().resolve()
        if output_html.suffix.lower() not in (".html", ".htm"):
            raise ValueError("导出文件必须使用 .html 或 .htm 扩展名")
        if output_html.exists():
            raise ValueError("导出文件已存在，请选择新名称；现有文件会保留")
        np = _np(options.get("np", 2))
        config = self._export_config(options, inventory, identity, sim)

        def action(job, cancel):
            self._status("正在核验 SIM 与对象清单的 SHA-256 身份。", "identity", job)
            _check_cancelled(cancel)
            if _identity(sim) != identity:
                raise ValueError("SIM 内容与对象清单来源不同，请重新读取清单")
            _check_cancelled(cancel)
            _json(job / "export-config.json", config)
            self._status("正在从保存场导出所选壁面、真实截面与已有后处理图层。", "export", job)
            result = export_sim(config, job / "native", star=options.get("star"), np=np,
                                run=True, compile_api=True, cancel_event=cancel)
            _check_cancelled(cancel)
            if (result.get("status") != "complete" or result.get("sourceUnchanged") is not True or
                    result.get("sourceBefore") != identity or result.get("sourceAfter") != identity):
                raise ValueError("导出结果未通过源文件与对象清单身份核验")
            case_path = job / "native" / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            self._status("正在组装离线三维 HTML。", "html", job)
            project = project_from_cases([case], config["name"])
            project["ui"] = {"language": language}
            built = build_report(project, job / "report.html", template=template)
            _check_cancelled(cancel)
            output_html.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation protects pre-existing files even if one appeared
            # while STAR ran. Cancelled partial copies are removed only if ours.
            created_identity = None
            try:
                with output_html.open("xb") as target, built.open("rb") as source:
                    import os
                    created_identity = os.fstat(target.fileno())
                    while chunk := source.read(1024 * 1024):
                        _check_cancelled(cancel)
                        target.write(chunk)
                    _check_cancelled(cancel)
            except Exception:
                if created_identity is not None:
                    try:
                        current = output_html.stat()
                        if (current.st_ino, current.st_dev) == (created_identity.st_ino, created_identity.st_dev):
                            output_html.unlink()
                    except FileNotFoundError:
                        pass
                raise
            return {"type": "complete", "message": "离线三维 HTML 已导出。", "html": str(output_html)}

        return self._start("export", sim, action)

    def cancel(self):
        """Request cancellation; the adapter finalizes owned-process receipts."""
        with self._lock:
            if not self._busy or self._cancel_event is None:
                return False
            self._cancel_event.set()
            job = self.last_job_directory
        self._status("正在取消任务并完成源文件核验，请稍候。", "cancelling", job)
        return True
