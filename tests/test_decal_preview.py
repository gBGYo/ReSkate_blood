"""Preview cancellation, material reuse and export snapshots for the decal GUI."""

from dataclasses import replace
import importlib.util
from pathlib import Path
from queue import Queue
import tempfile
import threading
import unittest

AVAILABLE = all(importlib.util.find_spec(name) for name in ("numpy", "PIL", "scipy"))
if AVAILABLE:
    import numpy as np
    from tools import generate_decals as lab
    from tools import decal_preview as live


@unittest.skipUnless(AVAILABLE, "Optional decal lab dependencies are not installed")
class PreviewTests(unittest.TestCase):
    def recipe(self, **changes):
        return replace(lab.preset("pool"), **({"size": 64, "parcels": 1000} | changes))

    def worker(self, simulate=None):
        replies = Queue()
        worker = live.LatestRenderer(lambda *args: replies.put(args), simulate)
        self.addCleanup(worker.close)
        return worker, replies

    def test_material_edit_reuses_identical_thickness(self):
        worker, replies = self.worker()
        first_recipe = self.recipe()
        worker.request(first_recipe)
        _, first, error = replies.get(timeout=10)
        self.assertIsNone(error)
        second_recipe = replace(first_recipe, deep_rgb=(12, 90, 4), absorption_mm=0.06)
        worker.request(second_recipe)
        _, second, error = replies.get(timeout=10)
        self.assertIsNone(error)
        self.assertTrue(second.reused_shape)
        self.assertIs(first.height, second.height)
        self.assertFalse(np.array_equal(first.maps["color.png"], second.maps["color.png"]))

    def test_latest_geometry_cancels_old_work_and_skips_pending_intermediate(self):
        started, release = threading.Event(), threading.Event()
        calls = []

        def simulate(recipe, cancelled):
            calls.append(recipe.seed)
            if len(calls) == 1:
                started.set()
                release.wait(timeout=5)
                if cancelled():
                    raise InterruptedError()
            return lab.Surface(recipe, cancelled=cancelled).generate()

        worker, replies = self.worker(simulate)
        worker.request(self.recipe(seed=1))
        self.assertTrue(started.wait(timeout=5))
        worker.request(self.recipe(seed=2))
        last = worker.request(self.recipe(seed=3))
        release.set()
        revision, result, error = replies.get(timeout=10)
        self.assertEqual(revision, last)
        self.assertIsNone(error)
        self.assertEqual(result.recipe.seed, 3)
        self.assertEqual(calls, [1, 3])
        self.assertTrue(replies.empty())

    def test_material_changes_during_simulation_do_not_restart_it(self):
        started, release = threading.Event(), threading.Event()
        calls = []

        def simulate(recipe, cancelled):
            calls.append(recipe)
            started.set()
            release.wait(timeout=5)
            self.assertFalse(cancelled())
            return lab.Surface(recipe).generate()

        worker, replies = self.worker(simulate)
        recipe = self.recipe()
        worker.request(recipe)
        self.assertTrue(started.wait(timeout=5))
        edited = replace(recipe, wet_roughness=0.8)
        worker.invalidate(edited)
        revision = worker.request(edited)
        release.set()
        returned, result, error = replies.get(timeout=10)
        self.assertIsNone(error)
        self.assertEqual(returned, revision)
        self.assertEqual(len(calls), 1)
        self.assertTrue(result.reused_shape)
        self.assertEqual(result.recipe.wet_roughness, 0.8)

    def test_generation_errors_do_not_kill_worker(self):
        def simulate(recipe, cancelled):
            if recipe.seed == 1:
                raise ValueError("test surface failure")
            return lab.Surface(recipe).generate()
        worker, replies = self.worker(simulate)
        worker.request(self.recipe(seed=1))
        _, result, error = replies.get(timeout=5)
        self.assertIsNone(result)
        self.assertIn("surface failure", error)
        worker.request(self.recipe(seed=2))
        _, result, error = replies.get(timeout=5)
        self.assertIsNone(error)
        self.assertEqual(result.recipe.seed, 2)

    def test_export_uses_requested_resolution_and_never_overwrites(self):
        worker, replies = self.worker()
        worker.request(self.recipe(size=64))
        _, cached, _ = replies.get(timeout=5)
        recipe = self.recipe(size=128, deep_rgb=(20, 50, 90))
        with tempfile.TemporaryDirectory() as temp:
            first = live.export_variant(recipe, Path(temp), cached)
            second = live.export_variant(recipe, Path(temp), cached)
            self.assertNotEqual(first, second)
            self.assertTrue(first.is_dir())
            self.assertTrue(second.is_dir())
            saved = lab.load_recipe(first / "recipe.json")
            self.assertEqual(saved.size, 128)
            self.assertEqual(tuple(saved.deep_rgb), recipe.deep_rgb)
            with lab.Image.open(first / "color.png") as image:
                self.assertEqual(image.size, (128, 128))
            self.assertEqual(len(list(Path(temp).iterdir())), 2)

    def test_all_simulations_support_cooperative_cancellation(self):
        for kind in lab.KINDS:
            with self.subTest(kind=kind):
                surface = lab.Surface(replace(self.recipe(), kind=kind), cancelled=lambda: True)
                with self.assertRaises(InterruptedError):
                    surface.generate()

    def test_gui_relevant_fields_are_in_geometry_key(self):
        recipe = self.recipe()
        self.assertNotEqual(live.geometry_key(recipe), live.geometry_key(replace(recipe, size=128)))
        self.assertNotEqual(live.geometry_key(recipe), live.geometry_key(replace(recipe, volume_ml=6)))
        self.assertNotEqual(live.geometry_key(recipe), live.geometry_key(replace(recipe, fine_splatter=0.5)))
        self.assertEqual(live.geometry_key(recipe), live.geometry_key(replace(recipe, deep_rgb=[2, 5, 8])))

    def test_draft_is_not_reused_for_full_quality_at_same_resolution(self):
        worker, replies = self.worker()
        recipe = self.recipe()
        worker.request(recipe, draft=True)
        _, draft, error = replies.get(timeout=5)
        self.assertIsNone(error)
        self.assertTrue(draft.draft)
        worker.request(recipe, draft=False)
        _, full, error = replies.get(timeout=5)
        self.assertIsNone(error)
        self.assertFalse(full.reused_shape)
        self.assertFalse(full.draft)


if __name__ == "__main__":
    unittest.main()
