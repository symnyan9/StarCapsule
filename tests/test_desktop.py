"""Desktop contract checks. SIM fixtures/native adapter calls are synthetic mocks.

Native Tk interactions run when a display exists. These checks never launch STAR
and make no claim about CFD correctness or a particular user's SIM fields.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
from queue import Queue
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from cfd_review.desktop import DesktopController
from cfd_review.star import CancelledError, _execute_owned, _run, prepare_macro


def inventory():
    return {
        "schema": "cfd-review-star-inventory", "version": 1,
        "iteration": 30, "representations": ["Geometry", "Latest Surface/Volume", "Volume Mesh"],
        "representationDetails": [
            {"name": "Geometry", "type": "GeometryRepresentation", "isFiniteVolume": False,
             "cellCount": None, "exportable": False},
            {"name": "Latest Surface/Volume", "type": "ProxyRepresentation", "isFiniteVolume": False,
             "cellCount": None, "exportable": False},
            {"name": "Volume Mesh", "type": "FvRepresentation", "isFiniteVolume": True,
             "cellCount": 120, "exportable": True}],
        "regions": [{"name": "Fluid A", "boundaries": ["Body", "Inlet"]},
                    {"name": "Fluid B", "boundaries": ["Body"]}],
        "derivedParts": ["Existing section"],
        "fields": [{"name": "Pressure coefficient", "functionName": "PressureCoefficient", "type": "SCALAR"},
                   {"name": "Total pressure coefficient", "functionName": "TotalPressureCoefficient", "type": "SCALAR"},
                   {"name": "Velocity", "functionName": "Velocity", "type": "VECTOR"}],
    }


def source_identity(path):
    stat = path.stat()
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": stat.st_size, "mtimeNs": stat.st_mtime_ns}


def synthetic_case():
    return {"schema": "cfd-review-case", "version": 1, "id": "mock", "name": "Synthetic triangle",
            "data": {"meta": {"title": "Synthetic", "source": "Unit test only", "sourceKey": "mock-v1",
                     "units": "m", "axis": {"up": "z"}, "isDemo": True, "halfCar": False,
                     "ranges": {"Cp": [-3, 3], "CpT": [-.5, 1]}, "surfaceRange": [-3, 3]},
                     "parts": [{"id": "p", "name": "Triangle", "positions": [0, 0, 0, 0, 1, 0, 0, 0, 1],
                                "indices": [0, 1, 2], "cp": [1, 2, 3]}], "sections": []}}


class DesktopControllerChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sim = self.root / "示例 case (mock).sim"
        self.sim.write_bytes(b"SYNTHETIC mock fixture, not a STAR file")
        self.identity = source_identity(self.sim)
        self.controller = DesktopController(self.root / "jobs")
        self.output = self.root / "report.html"

    def receipt(self, **extra):
        return {"status": "complete", "sourceUnchanged": True,
                "sourceBefore": copy.deepcopy(self.identity), "sourceAfter": copy.deepcopy(self.identity), **extra}

    def wait(self, worker):
        worker.join(10)
        self.assertFalse(worker.is_alive(), "mock desktop worker did not complete")
        self.assertFalse(self.controller.busy)
        messages = []
        while not self.controller.events.empty():
            messages.append(self.controller.events.get_nowait())
        self.assertTrue(messages)
        return messages[-1]

    def read_inventory(self):
        with patch("cfd_review.desktop.inspect_sim", return_value=self.receipt(inventory=inventory())) as native:
            result = self.wait(self.controller.inspect(self.sim, np=2))
        self.assertEqual(result["type"], "inventory")
        self.assertTrue(native.call_args.kwargs["run"])
        self.assertTrue(native.call_args.kwargs["compile_api"])
        return result

    def options(self):
        return {"sim": str(self.sim), "output_html": str(self.output), "title": "Synthetic review",
                "representation": "Volume Mesh", "cp_function": "PressureCoefficient",
                "cpt_function": "TotalPressureCoefficient", "np": 2,
                "surfaces": [{"id": "body-b", "name": "Second body",
                              "boundaries": [{"region": "Fluid B", "name": "Body"}]}],
                "section_regions": ["Fluid A"], "x_sections": [-.2, 0, .2],
                "ranges": {"Cp": [-2, 1], "CpT": [-.5, 1]}, "surface_range": [-2, 1], "half_car": False}

    def native_export(self, config, output, **kwargs):
        Path(output).mkdir(parents=True)
        (Path(output) / "case.json").write_text(json.dumps(synthetic_case()), encoding="utf-8")
        return self.receipt()

    def test_inventory_is_async_copied_and_source_preserved(self):
        threads = []
        def native(*args, **kwargs):
            threads.append(threading.get_ident())
            return self.receipt(inventory=inventory())
        with patch("cfd_review.desktop.inspect_sim", side_effect=native):
            self.assertEqual(self.wait(self.controller.inspect(self.sim))["type"], "inventory")
        self.assertNotEqual(threads[0], threading.get_ident())
        self.assertEqual(self.controller.source_path, str(self.sim.resolve()))
        value = self.controller.inventory
        value["regions"].clear()
        self.assertEqual(len(self.controller.inventory["regions"]), 2)
        self.assertEqual(source_identity(self.sim), self.identity)

    def test_unverified_inventory_cannot_enable_export(self):
        invalid = self.receipt(inventory=inventory(), sourceUnchanged=False)
        with patch("cfd_review.desktop.inspect_sim", return_value=invalid):
            self.assertEqual(self.wait(self.controller.inspect(self.sim))["type"], "error")
        self.assertIsNone(self.controller.inventory)
        with self.assertRaises(ValueError):
            self.controller.export(self.options())

    def test_exact_selection_generates_html_without_guessing_fields(self):
        self.read_inventory()
        with patch("cfd_review.desktop.export_sim", side_effect=self.native_export) as native:
            result = self.wait(self.controller.export(self.options()))
        self.assertEqual(result["type"], "complete")
        cfg = native.call_args.args[0]
        self.assertEqual(cfg["surfaces"][0]["boundaries"], [{"region": "Fluid B", "name": "Body"}])
        self.assertEqual(cfg["fields"], {"Cp": {"function": "PressureCoefficient"},
                                         "CpT": {"function": "TotalPressureCoefficient"}})
        self.assertEqual(cfg["xSections"], [-.2, 0, .2])
        self.assertEqual(cfg["meta"]["sourceSha256"], self.identity["sha256"])
        self.assertTrue(self.output.read_text(encoding="utf-8").startswith("<!doctype html>"))
        self.assertEqual(source_identity(self.sim), self.identity)

    def test_exported_html_keeps_selected_language_out_of_native_scientific_config(self):
        from cfd_review.report import load_report_document
        self.read_inventory()
        for language in ("en", "zh-CN"):
            options = self.options()
            options.update(language=language, output_html=str(self.root / (language + ".html")))
            with patch("cfd_review.desktop.export_sim", side_effect=self.native_export) as native:
                result = self.wait(self.controller.export(options))
            self.assertEqual(result["type"], "complete")
            self.assertNotIn("language", native.call_args.args[0]["meta"])
            project = load_report_document(options["output_html"])
            self.assertEqual(project["ui"]["language"], language)
            self.assertEqual(project["cases"][0]["data"], synthetic_case()["data"])

    def test_unknown_export_language_fails_before_native_job(self):
        options = self.options()
        options["language"] = "fr"
        with patch("cfd_review.desktop.export_sim") as native, self.assertRaisesRegex(ValueError, "Language"):
            self.controller.export(options)
        native.assert_not_called()

    def test_cpt_only_export_keeps_missing_cp_missing(self):
        self.read_inventory()
        options = self.options()
        options["cp_function"] = None
        options["x_sections"] = []
        options["section_regions"] = []
        with patch("cfd_review.desktop.export_sim", side_effect=self.native_export) as native:
            self.assertEqual(self.wait(self.controller.export(options))["type"], "complete")
        self.assertEqual(native.call_args.args[0]["fields"], {"CpT": {"function": "TotalPressureCoefficient"}})

    def test_invalid_or_out_of_inventory_choices_rejected_before_native_export(self):
        self.read_inventory()
        for update in ({"representation": "Not present"}, {"cp_function": "Velocity"},
                       {"cp_function": None, "cpt_function": None},
                       {"surfaces": [{"id": "p", "name": "Wrong", "boundaries": [{"region": "Fluid C", "name": "Body"}]}]},
                       {"x_sections": [0, 0]}, {"x_sections": [1, 0]}, {"x_sections": [float("nan")]},
                       {"x_sections": [float("inf")]}, {"section_regions": []},
                       {"ranges": {"Cp": [1, -1], "CpT": [0, 1]}}, {"np": True}):
            with self.subTest(update=update), patch("cfd_review.desktop.export_sim") as native:
                options = self.options()
                options.update(update)
                with self.assertRaises(ValueError):
                    self.controller.export(options)
                native.assert_not_called()
                self.assertFalse(self.controller.busy)

    def test_existing_output_is_preserved_without_starting_export(self):
        self.read_inventory()
        self.output.write_text("KEEP", encoding="utf-8")
        with patch("cfd_review.desktop.export_sim") as native, self.assertRaises(ValueError):
            self.controller.export(self.options())
        native.assert_not_called()
        self.assertEqual(self.output.read_text(), "KEEP")

    def test_output_created_during_job_is_preserved(self):
        self.read_inventory()
        def native(config, output, **kwargs):
            self.output.write_text("CREATED ELSEWHERE", encoding="utf-8")
            return self.native_export(config, output, **kwargs)
        with patch("cfd_review.desktop.export_sim", side_effect=native):
            self.assertEqual(self.wait(self.controller.export(self.options()))["type"], "error")
        self.assertEqual(self.output.read_text(), "CREATED ELSEWHERE")

    def test_stale_source_bytes_rejected_even_if_size_and_mtime_match(self):
        self.read_inventory()
        self.sim.write_bytes(b"X" * self.identity["size"])
        os.utime(self.sim, ns=(self.sim.stat().st_atime_ns, self.identity["mtimeNs"]))
        with patch("cfd_review.desktop.export_sim") as native:
            event = self.wait(self.controller.export(self.options()))
        self.assertEqual(event["type"], "error")
        native.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_failure_clears_busy_and_keeps_source(self):
        self.read_inventory()
        with patch("cfd_review.desktop.export_sim", side_effect=ValueError("Mock license failure")):
            event = self.wait(self.controller.export(self.options()))
        self.assertEqual(event["type"], "error")
        self.assertIn("Mock license failure", event["message"])
        self.assertEqual(source_identity(self.sim), self.identity)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.controller.cancel())

    def test_cancel_and_concurrent_job_guard(self):
        started = threading.Event()
        def native(*args, **kwargs):
            started.set()
            if not kwargs["cancel_event"].wait(5):
                raise AssertionError("controller did not cancel the mock worker")
            raise CancelledError("Synthetic cancelled worker")
        with patch("cfd_review.desktop.inspect_sim", side_effect=native):
            worker = self.controller.inspect(self.sim)
            self.assertTrue(started.wait(2))
            with self.assertRaises(ValueError):
                self.controller.inspect(self.sim)
            self.assertTrue(self.controller.cancel())
            event = self.wait(worker)
        self.assertEqual(event["type"], "cancelled")
        self.assertEqual(source_identity(self.sim), self.identity)
        self.assertIsNone(self.controller.inventory)


class OwnedCancellationChecks(unittest.TestCase):
    def test_cancelled_native_run_still_finalizes_source_identity_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sim = root / "synthetic.sim"
            sim.write_bytes(b"SYNTHETIC cancellation fixture, not a STAR file")
            original = source_identity(sim)
            plan = prepare_macro({}, root / "native", "inspect")
            cancel = threading.Event()
            def stop(*args, **kwargs):
                cancel.set()
                raise CancelledError("Synthetic cancelled native process")
            with patch("cfd_review.star.find_star", return_value=Path("mock-star.exe")), \
                 patch("cfd_review.star.memory_status", return_value=None), \
                 patch("cfd_review.star._execute_owned", side_effect=stop), self.assertRaises(CancelledError):
                _run(plan, sim, cancel_event=cancel)
            receipt = json.loads((root / "native/run-receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "cancelled")
            self.assertFalse(receipt["runtimeValidated"])
            self.assertTrue(receipt["sourceUnchanged"])
            self.assertEqual(receipt["sourceBefore"], original)
            self.assertEqual(receipt["sourceAfter"], original)

    def test_cancel_before_launch_never_starts_process(self):
        cancel = threading.Event()
        cancel.set()
        with patch("cfd_review.star.subprocess.Popen") as popen, self.assertRaises(CancelledError):
            _execute_owned(["mock-star"], ".", "unused.log", 60, cancel_event=cancel)
        popen.assert_not_called()

    def test_cancel_after_launch_stops_only_its_owned_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            cancel = threading.Event()
            process = MagicMock(pid=424242, returncode=None)
            process.poll.return_value = None
            def launch(*args, **kwargs):
                cancel.set()
                return process
            with patch("cfd_review.star.subprocess.Popen", side_effect=launch), \
                 patch("cfd_review.star.subprocess.run") as kill, \
                 patch("cfd_review.star.os.killpg", create=True) as killpg, \
                 self.assertRaises(CancelledError):
                _execute_owned(["mock-star", "a.sim"], tmp, Path(tmp) / "mock.log", 60, cancel_event=cancel)
            if os.name == "nt":
                self.assertEqual(kill.call_args.args[0], ["taskkill", "/PID", "424242", "/T", "/F"])
                killpg.assert_not_called()
            else:
                self.assertEqual(killpg.call_args.args[0], 424242)
                kill.assert_not_called()
            process.wait.assert_called_once_with(timeout=20)
            receipt = json.loads((Path(tmp) / "resource-samples.json").read_text())
            self.assertEqual(receipt["ownedPid"], 424242)


class FakeController:
    """No solver/adapter calls: captures the native GUI's requests only."""
    def __init__(self):
        self.events = Queue()
        self.busy = False
        self.calls = []

    def inspect(self, sim, **kwargs):
        self.calls.append(("inspect", sim, kwargs))
        self.busy = True

    def export(self, options):
        self.calls.append(("export", copy.deepcopy(options)))
        self.busy = True

    def cancel(self):
        self.calls.append(("cancel",))
        return self.busy


class NativeTkChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import tkinter as tk
        except ImportError as error:
            raise unittest.SkipTest(f"Native Tk unavailable: {error}") from error
        try:
            probe = tk.Tk()
            probe.withdraw()
            # Drain Tcl's deferred theme notifications before destroying this
            # interpreter; otherwise a later root can surface stale callbacks.
            probe.update_idletasks()
            probe.update()
            probe.destroy()
        except tk.TclError as error:
            raise unittest.SkipTest(f"Native Tk/display unavailable: {error}") from error

    def setUp(self):
        import tkinter as tk
        from cfd_review.gui import ExportApp
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.sim = self.folder / "Synthetic GUI.sim"
        self.sim.write_bytes(b"SYNTHETIC GUI fixture, not a STAR file")
        self.root = tk.Tk()
        self.root.withdraw()
        self.controller = FakeController()
        self.app = ExportApp(self.root, controller=self.controller,
                             language="zh-CN", settings_path=self.folder / "settings.json")
        self.addCleanup(self.close)
        error_patch = patch("cfd_review.gui.messagebox.showerror")
        self.error = error_patch.start()
        self.addCleanup(error_patch.stop)
        self.app.vars["sim"].set(str(self.sim))
        self.app.vars["output"].set(str(self.folder / "review.html"))
        self.app.vars["title"].set("Synthetic GUI review")

    def close(self):
        if self.app._timer is not None:
            self.root.after_cancel(self.app._timer)
        self.app.progress.stop()
        self.root.update_idletasks()
        self.root.update()
        self.root.destroy()

    def select_body_b(self):
        iid = next(i for i, b in self.app.boundary_items.items() if b == {"region": "Fluid B", "name": "Body"})
        self.app.boundary_tree.selection_set(iid)
        self.app._boundary_selected()

    def ready(self):
        self.app.apply_inventory(inventory())
        self.select_body_b()

    def test_native_picker_read_and_queue_inventory_populate_exact_objects(self):
        with patch("cfd_review.gui.filedialog.askopenfilename", return_value=str(self.sim)) as dialog:
            self.app.choose_sim()
        self.assertEqual(self.app.vars["sim"].get(), str(self.sim))
        self.assertEqual(self.app.vars["title"].get(), self.sim.stem)
        self.assertIn("*.sim", str(dialog.call_args.kwargs["filetypes"]))
        self.app.read_button.invoke()
        self.assertEqual(self.controller.calls[0][0], "inspect")
        self.assertEqual(str(self.app.read_button["state"]), "disabled")
        self.controller.busy = False
        self.controller.events.put({"type": "inventory", "sim": str(self.sim), "inventory": inventory()})
        self.root.after_cancel(self.app._timer)
        self.app._timer = None
        self.app.poll_events()
        self.assertEqual(len(self.app.boundary_items), 3)
        self.assertEqual(self.app._selected_boundaries, set())
        self.assertEqual(self.app.region_list.get(0, "end"), ("Fluid A", "Fluid B"))
        self.assertNotIn("Velocity", self.app.field_combos["cp_function"]["values"])
        self.assertEqual(str(self.app.field_combos["cp_function"]["state"]), "readonly")

    def test_coefficient_menus_only_offer_matching_coefficient_and_layers_keep_scalars(self):
        sample = inventory()
        other_scalars = ["Pressure", "Qcriterion", "PartitionId"]
        sample["fields"].extend({"name": name, "functionName": name, "type": "SCALAR"}
                                for name in other_scalars)
        self.app.apply_inventory(sample)
        for key, name in (("cp_function", "PressureCoefficient"),
                          ("cpt_function", "TotalPressureCoefficient")):
            self.assertEqual(self.app.field_combos[key]["values"], ("不导出", name))
            self.assertEqual(self.app.vars[key].get(), name)
            self.assertEqual(str(self.app.field_combos[key]["state"]), "readonly")
        for name in other_scalars:
            self.assertIn(name, self.app.layer_field_combo["values"])
        self.assertNotIn("Velocity", self.app.layer_field_combo["values"])

    def test_missing_coefficients_do_not_offer_other_scalars_as_substitutes(self):
        sample = inventory()
        sample["fields"] = [{"name": name, "functionName": name, "type": "SCALAR"}
                            for name in ("Pressure", "Qcriterion", "PartitionId")]
        self.app.apply_inventory(sample)
        for key in ("cp_function", "cpt_function"):
            self.assertEqual(self.app.field_combos[key]["values"], ("不导出",))
            self.assertEqual(self.app.vars[key].get(), "不导出")
            self.assertEqual(str(self.app.field_combos[key]["state"]), "readonly")
        self.assertIn("Pressure", self.app.layer_field_combo["values"])

    def test_search_keeps_exact_cross_region_selection(self):
        self.ready()
        self.app.vars["search"].set("Inlet")
        self.root.update()
        self.assertEqual(len(self.app.boundary_items), 1)
        self.assertEqual(self.app._selected_boundaries, {("Fluid B", "Body")})
        self.app.vars["search"].set("")
        self.root.update()
        choices = self.app._collect_options()["surfaces"]
        self.assertEqual(choices[0]["boundaries"], [{"region": "Fluid B", "name": "Body"}])

    def test_only_populated_fv_mesh_shown_and_default_raw_name_preserved(self):
        self.ready()
        labels = self.app.representation_combo["values"]
        self.assertEqual(len(labels), 1)
        self.assertIn("计算体网格", labels[0])
        self.assertIn("Volume Mesh", labels[0])
        self.assertIn("120 单元", labels[0])
        self.assertNotIn("Geometry", str(labels))
        self.assertNotIn("Latest Surface/Volume", str(labels))
        self.assertEqual(self.app.vars["representation"].get(), labels[0])
        self.assertEqual(self.app._collect_options()["representation"], "Volume Mesh")
        # A raw/programmatically injected label must not bypass the allowed menu.
        self.app.vars["representation"].set("Geometry")
        with self.assertRaisesRegex(ValueError, "计算体网格"):
            self.app._collect_options()

    def test_user_named_fv_mesh_is_not_guessed_or_normalized(self):
        sample = inventory()
        raw = "  自定义计算网格 Ω  "
        sample["representations"][2] = raw
        sample["representationDetails"][2]["name"] = raw
        self.app.apply_inventory(sample)
        self.select_body_b()
        self.assertEqual(len(self.app.representation_combo["values"]), 1)
        self.assertEqual(self.app._collect_options()["representation"], raw)
        self.assertEqual(str(self.app.export_button["state"]), "normal")

    def test_missing_or_empty_native_mesh_disables_export_with_recovery(self):
        for missing in (True, False):
            with self.subTest(missing_native_details=missing):
                sample = inventory()
                if missing:
                    del sample["representationDetails"]
                else:
                    sample["representationDetails"][2].update(cellCount=0, exportable=False)
                self.app.apply_inventory(sample)
                self.select_body_b()
                self.assertEqual(self.app.representation_combo["values"], "")
                self.assertEqual(str(self.app.representation_combo["state"]), "disabled")
                self.assertEqual(str(self.app.export_button["state"]), "disabled")
                self.assertEqual(str(self.app.read_button["state"]), "normal")
                self.assertIn("重新点击" if missing else "已保存体网格", self.app.status.get())
                with self.assertRaises(ValueError):
                    self.app._collect_options()
        self.assertEqual(self.controller.calls, [])

    def test_explicit_no_export_and_x_list_override_keep_source_functions(self):
        self.ready()
        self.assertIn("不导出", self.app.field_combos["cp_function"]["values"])
        self.app.vars["cp_function"].set("不导出")
        self.app.vars["section_enabled"].set(True)
        self.app.vars["x_list"].set("-0.2, 0, 0.2")
        for key in ("x_start", "x_end", "x_count"):
            self.app.vars[key].set("ignored when list supplied")
        self.app.region_list.selection_set(0)
        options = self.app._collect_options()
        self.assertEqual(options["cp_function"], "")
        self.assertEqual(options["cpt_function"], "TotalPressureCoefficient")
        self.assertEqual(options["x_sections"], [-.2, 0, .2])

    def test_export_captures_cpt_only_planes_and_resets_after_cancellation(self):
        self.ready()
        self.app.vars["cp_function"].set("")
        self.app.vars["section_enabled"].set(True)
        self.app.vars["x_start"].set("-0.2")
        self.app.vars["x_end"].set("0.2")
        self.app.vars["x_count"].set("3")
        self.app.region_list.selection_set(0)
        self.app.export_button.invoke()
        self.assertEqual(self.controller.calls[-1][0], "export")
        options = self.controller.calls[-1][1]
        self.assertEqual(options["x_sections"], [-.2, 0, .2])
        self.assertEqual(options["section_regions"], ["Fluid A"])
        self.assertEqual(options["cp_function"], "")
        self.assertEqual(options["cpt_function"], "TotalPressureCoefficient")
        self.assertEqual(str(self.app.export_button["state"]), "disabled")
        self.assertEqual(str(self.app.cancel_button["state"]), "normal")
        self.app.cancel_button.invoke()
        self.assertEqual(self.controller.calls[-1][0], "cancel")
        self.controller.busy = False
        self.app._handle_event({"type": "cancelled", "message": "Synthetic cancellation"})
        self.assertEqual(str(self.app.export_button["state"]), "normal")
        self.assertEqual(str(self.app.read_button["state"]), "normal")

    def test_invalid_plane_and_color_inputs_rejected_before_export(self):
        self.ready()
        self.app.vars["section_enabled"].set(True)
        self.app.vars["x_list"].set("0, 1")
        self.app.region_list.selection_set(0)
        for key, bad in (("x_list", "0,nan"), ("x_list", "1,0"), ("x_list", "0,0"),
                         ("x_list", "0,inf"), ("cp_min", "nan"), ("cp_max", "-10")):
            with self.subTest(key=key, bad=bad):
                original = self.app.vars[key].get()
                self.app.vars[key].set(bad)
                with self.assertRaises(ValueError):
                    self.app._collect_options()
                self.app.vars[key].set(original)
        self.assertEqual(self.controller.calls, [])

    def test_failure_recovers_controls_and_source_change_invalidates_selection(self):
        self.ready()
        self.app._set_working(True)
        self.app._handle_event({"type": "error", "message": "Synthetic native failure"})
        self.error.assert_called_once()
        self.assertFalse(self.app._working)
        self.assertEqual(str(self.app.export_button["state"]), "normal")
        self.app.vars["sim"].set(str(self.folder / "Another.sim"))
        self.assertIsNone(self.app.inventory)
        self.assertEqual(len(self.app.boundary_items), 0)
        self.assertEqual(str(self.app.export_button["state"]), "disabled")

    def test_memory_guard_explains_recovery_keeps_raw_log_and_job_access(self):
        self.ready()
        for raw in ("Owned STAR stopped by memory guard (physical <192 MiB for 3 samples or commit <1.5 GiB)",
                    "Insufficient initial memory: require >=1 GiB physical and >=6 GiB commit before opening STAR"):
            with self.subTest(raw=raw):
                self.app._set_working(True)
                self.app._handle_event({"type": "error", "message": raw, "job_directory": str(self.folder)})
                self.assertIn("内存不足", self.error.call_args.args[1])
                self.assertIn("np 设为 2", self.app.status.get())
                self.assertIn("任务文件夹", self.app.status.get())
                self.assertIn(raw, self.app.log.get("1.0", "end"))
                self.assertEqual(str(self.app.folder_button["state"]), "normal")
                self.assertEqual(str(self.app.export_button["state"]), "normal")
                self.assertFalse(self.app._working)
        self.assertEqual(self.controller.calls, [], "memory failures must not trigger an automatic retry")

    def test_data_budget_errors_explain_smaller_exports_and_preserve_original_detail(self):
        self.ready()
        for budget in ("structure", "numeric-data", "nesting depth", "complexity"):
            raw = f"document: JSON {budget} limit exceeded (synthetic count: 30000001)"
            with self.subTest(budget=budget):
                self.app._set_working(True)
                self.app._handle_event({"type": "error", "message": raw, "job_directory": str(self.folder)})
                self.assertIn("超出本版限制", self.error.call_args.args[1])
                self.assertIn("分开导出", self.app.status.get())
                self.assertIn(raw, self.app.log.get("1.0", "end"))
                self.assertEqual(str(self.app.folder_button["state"]), "normal")
                self.assertFalse(self.app._working)
        self.assertEqual(self.controller.calls, [], "data budget failures must not retry or change source data")

    def test_completed_export_opens_only_selected_local_html(self):
        self.ready()
        html = self.folder / "selected output.html"
        html.write_text("<!doctype html><title>Synthetic GUI result</title>", encoding="utf-8")
        self.app._set_working(True)
        with patch("cfd_review.gui.webbrowser.open") as browser:
            self.app._handle_event({"type": "complete", "html": str(html)})
        browser.assert_called_once_with(html.as_uri())
        self.assertFalse(self.app._working)
        self.assertEqual(str(self.app.open_button["state"]), "normal")

    def test_failed_reinspection_cannot_reenable_previous_inventory(self):
        self.ready()
        self.app.read_button.invoke()
        self.assertIsNone(self.app.inventory)
        self.assertEqual(len(self.app.boundary_items), 0)
        self.controller.busy = False
        self.app._handle_event({"type": "error", "message": "Synthetic reinspection failure"})
        self.assertIsNone(self.app.inventory)
        self.assertEqual(str(self.app.export_button["state"]), "disabled")
        with self.assertRaises(ValueError):
            self.app._collect_options()

    def test_native_template_picker_validates_and_passes_selected_folder_to_export(self):
        self.ready()
        folder = self.folder / "Local template"
        folder.mkdir()
        validator = MagicMock(return_value={"name": "Local engineering theme", "path": str(folder)})
        module = MagicMock(validate_template=validator)
        with patch.dict("sys.modules", {"cfd_review.templates": module}), \
                patch("cfd_review.gui.filedialog.askdirectory", return_value=str(folder)) as dialog:
            self.app.template_button.invoke()
        validator.assert_called_once_with(str(folder))
        self.assertTrue(dialog.call_args.kwargs["mustexist"])
        self.assertEqual(self.app.vars["template"].get(), str(folder.resolve()))
        self.assertTrue(self.app.template_summary.get().startswith("模板：Local engineering"))
        self.app.export_button.invoke()
        self.assertEqual(self.controller.calls[-1][1]["template"], str(folder.resolve()))
        self.assertEqual(self.app.credit_label.cget("text"), "Designed by Symn")

    def test_template_choice_survives_sim_change_and_resets_only_explicitly(self):
        folder = self.folder / "Persistent template"
        folder.mkdir()
        module = MagicMock(validate_template=MagicMock(return_value={"name": "Persistent template"}))
        with patch.dict("sys.modules", {"cfd_review.templates": module}), \
                patch("cfd_review.gui.filedialog.askdirectory", return_value=str(folder)):
            self.app.choose_template()
        summary = self.app.template_summary.get()
        self.app.vars["sim"].set(str(self.folder / "Another source.sim"))
        self.assertEqual(self.app.vars["template"].get(), str(folder.resolve()))
        self.assertEqual(self.app.template_summary.get(), summary)
        self.assertIsNone(self.app.inventory)
        self.app.template_reset_button.invoke()
        self.assertEqual(self.app.vars["template"].get(), "")
        self.assertEqual(self.app.template_summary.get(), "模板：内置默认")
        self.assertEqual(self.app.credit_label.cget("text"), "Designed by Symn")

    def test_invalid_template_rejected_without_star_or_previous_choice_loss(self):
        self.ready()
        original = str(self.folder / "Previous template")
        self.app.vars["template"].set(original)
        self.app.template_summary.set("模板：Previous")
        module = MagicMock(validate_template=MagicMock(side_effect=ValueError("Missing template.json")))
        with patch.dict("sys.modules", {"cfd_review.templates": module}), \
                patch("cfd_review.gui.filedialog.askdirectory", return_value=str(self.folder)):
            self.app.choose_template()
        self.error.assert_called_once()
        self.assertIn("template.json", self.error.call_args.args[1])
        self.assertEqual(self.app.vars["template"].get(), original)
        self.assertEqual(self.app.template_summary.get(), "模板：Previous")
        self.assertEqual(self.controller.calls, [])

    def test_selected_surface_bounds_autofill_preserve_manual_values_and_reset(self):
        sample = inventory()
        sample["boundaryDetails"] = [
            {"region": "Fluid A", "name": "Body", "bounds": {"min": [-.4, 0, 0], "max": [.6, 1, 1], "units": "m"}},
            {"region": "Fluid B", "name": "Body", "bounds": {"min": [1.4, 0, 0], "max": [2.4, 1, 1], "units": "m"}},
        ]
        sample["derivedPartDetails"] = [
            {"name": "Long wake", "type": "IsoPart", "exportableMesh": True,
             "bounds": {"min": [0, 0, 0], "max": [1000, 1, 1], "units": "m"}},
        ]
        self.app.apply_inventory(sample)
        self.select_body_b()
        self.assertEqual((self.app.vars["x_start"].get(), self.app.vars["x_end"].get()), ("1.4", "2.4"))
        self.app.derived_tree.selection_set(next(iter(self.app.derived_items)))
        self.app._derived_selected()
        self.assertEqual(self.app.vars["x_end"].get(), "2.4", "wake extent must not replace vehicle length")
        self.app.vars["x_start"].set("-1")
        body_a = next(i for i, b in self.app.boundary_items.items() if b == {"region": "Fluid A", "name": "Body"})
        self.app.boundary_tree.selection_add(body_a)
        self.app._boundary_selected()
        self.assertEqual(self.app.vars["x_start"].get(), "-1")
        self.app.vars["x_list"].set("0,1,2")
        self.app.bounds_button.invoke()
        self.assertEqual((self.app.vars["x_start"].get(), self.app.vars["x_end"].get()), ("-0.4", "2.4"))
        self.assertEqual(self.app.vars["x_list"].get(), "")
        self.app._boundary_bounds[("Fluid A", "Body")]["units"] = "mm"
        self.app._update_x_bounds()
        self.assertIsNone(self.app._selection_bounds)
        self.assertEqual(str(self.app.bounds_button["state"]), "disabled")

    def test_existing_postprocessing_layers_only_uses_real_scalar_and_mesh_types(self):
        sample = inventory()
        sample["fields"].append({"name": "Vorticity magnitude", "functionName": "VorticityMagnitude", "type": "SCALAR"})
        sample["derivedPartDetails"] = [
            {"name": "Q wake", "type": "IsoPart", "exportableMesh": True, "criterion": "QCriterion", "threshold": 100},
            {"name": "Probe point", "type": "PointPart", "exportableMesh": False},
        ]
        sample["sceneDetails"] = [
            {"name": "Geometry", "displayers": [{"derivedPartNames": ["Q wake"]}]},
            {"name": "Vortex", "displayers": [{"derivedPartNames": ["Q wake"], "fieldFunction": "VorticityMagnitude"}]},
            {"name": "Empty scene", "displayers": []},
        ]
        self.app.apply_inventory(sample)
        self.assertEqual(len(self.app.derived_items), 1)
        self.assertNotIn("Velocity", self.app.layer_field_combo["values"])
        item = next(iter(self.app.derived_items))
        self.assertEqual(self.app.derived_tree.item(item, "values")[0], "等值面")
        self.app.derived_tree.selection_set(item)
        self.app._derived_selected()
        self.app.vars["cp_function"].set("")
        self.app.vars["cpt_function"].set("")
        options = self.app._collect_options()
        self.assertEqual(options["surfaces"], [])
        self.assertEqual(options["layers"][0]["derivedPart"], "Q wake")
        self.assertEqual(options["layers"][0]["fieldFunction"], "VorticityMagnitude")
        self.assertEqual(options["layers"][0]["threshold"], 100)
        self.app.vars["layer_function"].set("仅几何")
        self.assertNotIn("fieldFunction", self.app._collect_options()["layers"][0])
        self.app.vars["layer_opacity"].set("nan")
        with self.assertRaises(ValueError):
            self.app._collect_options()


if __name__ == "__main__":
    unittest.main()
