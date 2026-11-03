"""Exercise real Qt controls and asynchronous rendering without opening a window."""

from dataclasses import replace
import importlib.util
import os
from pathlib import Path
import tempfile
import time
import unittest

AVAILABLE = all(importlib.util.find_spec(name) for name in ("numpy", "PIL", "scipy", "PySide6"))
if AVAILABLE:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from tools import decal_gui as gui


@unittest.skipUnless(AVAILABLE, "Optional Qt GUI dependencies are not installed")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        gui.configure_app(cls.app)

    def setUp(self):
        self.window = gui.DecalWindow(replace(gui.lab.preset("pool"), size=64, parcels=1000))
        self.window.show()
        self.wait_for_preview()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def wait_for(self, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(0.005)
        self.fail("GUI did not complete: " + self.window.status.text())

    def wait_for_preview(self):
        self.wait_for(lambda: self.window.result is not None and self.window.result.revision == self.window.revision)

    def test_material_control_updates_without_resimulating_shape(self):
        first = self.window.result
        control = self.window.controls["absorption_mm"]
        control.spin.setValue(0.1)
        self.wait_for_preview()
        self.assertTrue(self.window.result.reused_shape)
        self.assertIs(first.height, self.window.result.height)
        self.assertEqual(self.window.result.recipe.absorption_mm, 0.1)
        self.assertNotEqual(first.maps["opacity.png"].tobytes(), self.window.result.maps["opacity.png"].tobytes())

    def test_family_changes_show_relevant_controls_and_restore_settings(self):
        self.window.controls["contact_angle_deg"].spin.setValue(22)
        self.window.kind.setCurrentIndex(gui.lab.KINDS.index("smear"))
        self.assertTrue(self.window.groups["Drag path"].isVisible())
        self.assertFalse(self.window.controls["contact_angle_deg"].isVisible())
        self.window.kind.setCurrentIndex(gui.lab.KINDS.index("pool"))
        self.assertFalse(self.window.groups["Drag path"].isVisible())
        self.assertEqual(self.window.controls["contact_angle_deg"].value(), 22)
        self.wait_for_preview()
        self.assertEqual(self.window.result.recipe.kind, "pool")

    def test_fine_splatter_controls_regenerate_surrounding_detail(self):
        first = self.window.result
        self.window.controls["fine_splatter"].spin.setValue(0.7)
        self.window.controls["splatter_length_mm"].spin.setValue(10)
        self.window.controls["splatter_spread_mm"].spin.setValue(18)
        self.wait_for_preview()
        self.assertFalse(self.window.result.reused_shape)
        self.assertEqual(self.window.result.recipe.fine_splatter, 0.7)
        self.assertEqual(self.window.result.recipe.splatter_length_mm, 10)
        self.assertEqual(self.window.result.recipe.splatter_spread_mm, 18)
        self.assertGreater(self.window.result.stats["fine_fragment_count"], 0)
        self.assertNotEqual(first.maps["opacity.png"].tobytes(), self.window.result.maps["opacity.png"].tobytes())
        self.assertTrue(self.window.controls["viscosity_mpas"].isVisible())
        self.window.controls["fine_splatter"].spin.setValue(0)
        self.wait_for_preview()
        self.assertEqual(first.maps["opacity.png"].tobytes(), self.window.result.maps["opacity.png"].tobytes())

    def test_all_map_views_and_zoom_render(self):
        for name in ("Color", "Opacity", "Thickness", "Roughness", "Normals"):
            self.window.map_view.setCurrentText(name)
            self.app.processEvents()
            self.assertFalse(self.window.view.item.pixmap().isNull())
            self.assertEqual(self.window.background.isEnabled(), name == "Color")
        self.window.view.actual_size()
        self.assertAlmostEqual(self.window.view.transform().m11(), 1)
        self.window.view.fit()
        self.assertTrue(self.window.view.fitted)

    def test_preview_keeps_event_loop_alive_and_discards_stale_results(self):
        beats = []
        heartbeat = QTimer()
        heartbeat.setInterval(10)
        heartbeat.timeout.connect(lambda: beats.append(time.monotonic()))
        heartbeat.start()
        try:
            self.window.set_recipe(replace(gui.lab.preset("splash"), size=256, parcels=2000, seed=10))
            self.window.seed.setValue(11)
            self.window.seed.setValue(12)
            self.wait_for_preview()
            self.assertEqual(self.window.result.recipe.seed, 12)
            self.assertGreater(len(beats), 5)
        finally:
            heartbeat.stop()

    def test_export_is_full_resolution_snapshot(self):
        self.window.set_recipe(replace(gui.lab.preset("pool"), size=512, seed=17))
        self.wait_for_preview()
        self.assertEqual(self.window.result.recipe.size, 256)
        with tempfile.TemporaryDirectory() as temp:
            self.window.start_export(Path(temp))
            self.window.seed.setValue(18)
            self.wait_for(lambda: not self.window.exporting)
            self.assertIsNotNone(self.window.last_export)
            saved = gui.lab.load_recipe(self.window.last_export / "recipe.json")
            self.assertEqual(saved.seed, 17)
            self.assertEqual(saved.size, 512)
            with gui.lab.Image.open(self.window.last_export / "color.png") as image:
                self.assertEqual(image.size, (512, 512))


if __name__ == "__main__":
    unittest.main()
