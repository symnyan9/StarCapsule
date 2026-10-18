"""Language switching uses synthetic inventory only and never starts STAR."""
from __future__ import annotations

import json
from pathlib import Path
from queue import Queue
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from cfd_review.gui import ExportApp
from cfd_review.locale import LANGUAGES, load_language, normalize_language, save_language, translate


def inventory():
    return {
        "starVersion": "synthetic", "iteration": 30,
        "representations": ["Volume Mesh Ω"],
        "regions": [{"name": "Fluid Ω", "boundaries": ["机翼 α"]}],
        "representationDetails": [{"name": "Volume Mesh Ω", "type": "FvRepresentation",
                                    "isFiniteVolume": True, "cellCount": 120, "exportable": True}],
        "fields": [{"functionName": "PressureCoefficient", "type": "SCALAR"},
                   {"functionName": "TotalPressureCoefficient", "type": "SCALAR"},
                   {"functionName": "自定义 Q Ω", "type": "SCALAR"}],
        "derivedPartDetails": [{"name": "涡结构 Ω", "type": "IsoPart", "exportableMesh": True}],
        "sceneDetails": [{"name": "自定义场景", "displayers": [{"derivedPartNames": ["涡结构 Ω"],
                                                       "fieldFunction": "自定义 Q Ω"}]}],
        "boundaryDetails": [{"region": "Fluid Ω", "name": "机翼 α",
                              "bounds": {"units": "m", "min": [-1, 0, 0], "max": [2, 1, 1]}}],
    }


class FakeController:
    def __init__(self):
        self.events = Queue()
        self.busy = False
        self.calls = []

    def export(self, options):
        self.calls.append(("export", options))
        self.busy = True

    def cancel(self):
        self.calls.append(("cancel",))


class LanguagePreferenceChecks(unittest.TestCase):
    def test_default_invalid_and_bounded_local_preference(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "settings.json"
            self.assertEqual(load_language(target), "en")
            self.assertTrue(save_language("zh-CN", target))
            self.assertEqual(json.loads(target.read_text())["language"], "zh-CN")
            self.assertEqual(load_language(target), "zh-CN")
            for text in ('{"language": "unknown"}', '[]', '{"language": []}', 'not json', ' ' * 16385):
                target.write_text(text, encoding="utf-8")
                self.assertEqual(load_language(target), "en")
            self.assertEqual(normalize_language({}), "en")

    def test_nested_localized_values_retranslate_without_touching_source_name(self):
        source = translate("所选壁面", language="en")
        message = translate("{v0} X：{v1:.5g} 至 {v2:.5g} m，可手动扩展。", v0=source, v1=-1, v2=2)
        self.assertIn("Selected walls", message)
        self.assertIn("所选壁面", translate(message, language="zh-CN"))
        self.assertEqual(translate("机翼 α", language="en"), "机翼 α")

    def test_unwritable_preference_is_nonfatal(self):
        with patch("cfd_review.locale.Path.mkdir", side_effect=OSError("synthetic read-only folder")):
            self.assertFalse(save_language("zh-CN", "synthetic/settings.json"))


class DesktopLanguageChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            root = tk.Tk()
            root.withdraw()
            root.update()
            root.destroy()
        except tk.TclError as error:
            raise unittest.SkipTest(f"Native Tk/display unavailable: {error}") from error

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.settings = self.folder / "settings.json"
        self.root = tk.Tk()
        self.root.withdraw()
        self.controller = FakeController()
        self.app = ExportApp(self.root, self.controller, settings_path=self.settings)
        self.addCleanup(self.close)
        error_patch = patch("cfd_review.gui.messagebox.showerror")
        self.dialog = error_patch.start()
        self.addCleanup(error_patch.stop)
        self.app.vars["sim"].set(str(self.folder / "Synthetic.sim"))
        self.app.vars["output"].set(str(self.folder / "review.html"))
        self.app.vars["title"].set("用户 title Ω")

    def close(self):
        if self.app._timer is not None:
            self.root.after_cancel(self.app._timer)
        self.app.progress.stop()
        self.root.update_idletasks()
        self.root.update()
        self.root.destroy()

    def ready(self):
        self.app.apply_inventory(inventory())
        item = next(iter(self.app.boundary_items))
        self.app.boundary_tree.selection_set(item)
        self.app._boundary_selected()
        item = next(iter(self.app.derived_items))
        self.app.derived_tree.selection_set(item)
        self.app._derived_selected()

    def test_default_english_widgets_dialogs_and_export_language(self):
        self.assertEqual(self.app.language, "en")
        self.assertEqual(self.app.read_button.cget("text"), "Read simulation")
        self.assertEqual(self.app.content_tabs.tab(0, "text"), "Boundary surfaces")
        self.assertEqual(self.app.language_combo.cget("values"), tuple(LANGUAGES.values()))
        self.ready()
        self.assertEqual(self.app.field_combos["cp_function"].cget("values"),
                         ("Do not export", "PressureCoefficient"))
        self.assertIn("120 cells", self.app.vars["representation"].get())
        options = self.app._collect_options()
        self.assertEqual(options["language"], "en")
        self.assertEqual(options["title"], "用户 title Ω")
        self.assertEqual(options["representation"], "Volume Mesh Ω")
        self.assertEqual(options["layers"][0]["fieldFunction"], "自定义 Q Ω")
        with patch("cfd_review.gui.filedialog.askopenfilename", return_value="") as dialog:
            self.app.choose_sim()
        self.assertEqual(dialog.call_args.kwargs["title"], "Choose a solved STAR-CCM+ simulation")

    def test_switch_preserves_inventory_selection_inputs_and_source_names(self):
        self.ready()
        original_inventory = self.app.inventory
        self.app.vars["x_start"].set("-1.234")
        self.app.vars["x_end"].set("3.456")
        self.app.vars["cp_function"].set("Do not export")
        self.app.vars["layer_function"].set("Geometry only")
        self.app.vars["half_car"].set(True)
        self.app.vars["np"].set("3")
        selected = set(self.app._selected_boundaries)
        layers = set(self.app._selected_derived)
        self.app.set_language("zh-CN")
        self.root.update()
        self.assertIs(self.app.inventory, original_inventory)
        self.assertEqual(self.app._selected_boundaries, selected)
        self.assertEqual(self.app._selected_derived, layers)
        self.assertEqual(self.app.vars["x_start"].get(), "-1.234")
        self.assertEqual(self.app.vars["x_end"].get(), "3.456")
        self.assertEqual(self.app.vars["cp_function"].get(), "不导出")
        self.assertEqual(self.app.vars["layer_function"].get(), "仅几何")
        self.assertEqual(self.app.vars["np"].get(), "3")
        self.assertTrue(self.app.vars["half_car"].get())
        self.assertEqual(self.app.vars["title"].get(), "用户 title Ω")
        self.assertIn("120 单元", self.app.vars["representation"].get())
        self.assertEqual(self.app.read_button.cget("text"), "读取仿真内容")
        self.assertEqual(self.app.content_tabs.tab(1, "text"), "已有后处理")
        self.assertEqual(self.app._collect_options()["language"], "zh-CN")
        self.app.set_language("en")
        self.root.update()
        self.assertEqual(self.app.vars["layer_function"].get(), "Geometry only")
        self.assertEqual(self.app._collect_options()["cp_function"], "")
        self.assertEqual(self.app._collect_options()["layers"][0]["name"], "涡结构 Ω")
        self.assertIn("30 iterations", self.app.inventory_summary.get())
        self.assertEqual(self.controller.calls, [])

    def test_language_change_while_busy_keeps_job_and_retranslates_status(self):
        self.ready()
        self.app.start_export()
        self.assertEqual(len(self.controller.calls), 1)
        self.assertTrue(self.app._working)
        self.assertIn("Exporting surfaces", self.app.status.get())
        self.app.set_language("zh-CN")
        self.assertIn("正在从保存场", self.app.status.get())
        self.assertTrue(self.app._working)
        self.assertTrue(self.controller.busy)
        self.assertEqual(len(self.controller.calls), 1)
        self.assertEqual(str(self.app.export_button.cget("state")), "disabled")
        self.assertEqual(str(self.app.language_combo.cget("state")), "readonly")
        self.assertEqual(load_language(self.settings), "zh-CN")
        self.app.set_language("en")
        self.assertIn("Exporting surfaces", self.app.status.get())

    def test_english_validation_and_recovery_messages_keep_raw_logs(self):
        self.ready()
        self.app.vars["np"].set("bad")
        with self.assertRaisesRegex(ValueError, "integer from 1 to 256"):
            self.app._collect_options()
        raw = "Owned STAR stopped by memory guard (synthetic)"
        with patch("cfd_review.gui.messagebox.showerror") as dialog:
            self.app._handle_event({"type": "error", "message": raw})
        self.assertIn("Insufficient memory", dialog.call_args.args[1])
        self.assertIn(raw, self.app.log.get("1.0", "end"))
        self.assertEqual(self.controller.calls, [])

    def test_saved_choice_is_loaded_on_next_window(self):
        self.app.set_language("zh-CN")
        root = tk.Tk()
        root.withdraw()
        other = ExportApp(root, FakeController(), settings_path=self.settings)
        try:
            self.assertEqual(other.language, "zh-CN")
            self.assertEqual(other.read_button.cget("text"), "读取仿真内容")
        finally:
            root.after_cancel(other._timer)
            root.update()
            root.destroy()

    def test_native_job_statuses_follow_language_and_keep_original_log(self):
        self.ready()
        raw = "正在组装离线三维 HTML。"
        self.app._handle_event({"type": "status", "message": raw})
        self.assertEqual(self.app.status.get(), "Assembling the offline 3D HTML.")
        self.assertIn(raw, self.app.log.get("1.0", "end"))
        self.app.set_language("zh-CN")
        self.assertEqual(self.app.status.get(), raw)
        self.app.set_language("en")
        with patch("cfd_review.gui.messagebox.showerror") as dialog:
            self.app._handle_event({"type": "error", "message": "Cp 必须选择当前 SIM 中的现有标量函数"})
        self.assertEqual(dialog.call_args.args[1], "Cp must select an existing scalar function in the current SIM.")


if __name__ == "__main__":
    unittest.main()
