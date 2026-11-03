"""Numerical invariants and editable-output workflow for the optional art tool."""

from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

AVAILABLE = all(importlib.util.find_spec(name) for name in ("numpy", "PIL", "scipy"))
if AVAILABLE:
    import numpy as np
    from PIL import Image
    from tools import generate_decals as lab


@unittest.skipUnless(AVAILABLE, "Optional decal lab dependencies are not installed")
class DecalLabTests(unittest.TestCase):
    def recipe(self, kind="splash", **changes):
        return replace(lab.preset(kind), **({"size": 96, "parcels": 1000} | changes))

    def radius(self, height, recipe):
        y, x = np.indices(height.shape)
        total = height.sum()
        cx, cy = (x * height).sum() / total, (y * height).sum() / total
        return np.sqrt((((x-cx)**2 + (y-cy)**2) * height).sum() / total) * recipe.canvas_mm / recipe.size

    def test_all_families_account_for_liquid_and_have_empty_borders(self):
        for kind in lab.KINDS:
            with self.subTest(kind=kind):
                recipe = self.recipe(kind)
                height, stats = lab.Surface(recipe).generate()
                self.assertTrue(np.isfinite(height).all())
                self.assertGreater(height.max(), 0)
                self.assertGreaterEqual(height.min(), 0)
                self.assertAlmostEqual(stats["balance_error_ml"], 0, places=10)
                self.assertAlmostEqual(height.sum() * (recipe.canvas_mm / recipe.size)**2 / 1000, stats["deposited_ml"], places=10)
                self.assertLess(stats["edge_ml"], recipe.volume_ml * 0.001)
                if kind == "smear":
                    self.assertGreater(stats["carried_away_ml"], 0)

    def test_particle_transfer_does_not_wrap_across_edges(self):
        surface = lab.Surface(self.recipe(canvas_mm=100))
        surface.deposit(np.array([0, 100, -100, 0]), np.array([0, 0, 0, 100]), np.array([2, 3, 4, 5]))
        self.assertAlmostEqual(surface.volume.sum(), 2)
        self.assertAlmostEqual(surface.escaped_mm3, 12)
        self.assertEqual(surface.volume[0].sum() + surface.volume[-1].sum(), 0)
        self.assertEqual(surface.volume[:, 0].sum() + surface.volume[:, -1].sum(), 0)

    def test_seed_is_repeatable_and_changes_shape(self):
        recipe = self.recipe("pool")
        first, _ = lab.Surface(recipe).generate()
        same, _ = lab.Surface(recipe).generate()
        other, _ = lab.Surface(replace(recipe, seed=43)).generate()
        np.testing.assert_array_equal(first, same)
        self.assertFalse(np.array_equal(first, other))

    def test_viscosity_reduces_impact_footprint(self):
        low = self.recipe(viscosity_mpas=1)
        high = replace(low, viscosity_mpas=60)
        first, _ = lab.Surface(low).generate()
        second, _ = lab.Surface(high).generate()
        self.assertLess(self.radius(second, high), self.radius(first, low) * 0.85)

    def test_resolution_preserves_physical_pool_size(self):
        small = self.recipe("pool", size=96)
        large = replace(small, size=192)
        first, _ = lab.Surface(small).generate()
        second, _ = lab.Surface(large).generate()
        self.assertAlmostEqual(self.radius(first, small) / self.radius(second, large), 1, delta=0.025)

    def test_clipping_is_reported_and_volume_still_balances(self):
        recipe = self.recipe("pool", canvas_mm=40)
        _, stats = lab.Surface(recipe).generate()
        self.assertGreater(stats["outside_canvas_ml"], recipe.volume_ml * 0.1)
        self.assertAlmostEqual(stats["balance_error_ml"], 0, places=10)

    def test_editable_master_rebuilds_all_maps_without_changing_source(self):
        recipe = self.recipe("pool")
        height, stats = lab.Surface(recipe).generate()
        with tempfile.TemporaryDirectory() as temp:
            source, destination = Path(temp) / "original", Path(temp) / "edited"
            lab.export(source, recipe, height, stats)
            original_color = (source / "color.png").read_bytes()
            with Image.open(source / "thickness.png") as image:
                pixels = np.array(image, dtype=np.uint16)
            pixels[:, :recipe.size // 2] = 0
            Image.fromarray(pixels).save(source / "thickness.png")
            lab.rebake(source, destination, {"deep_rgb": [50, 2, 4]})
            self.assertEqual((source / "color.png").read_bytes(), original_color)
            with Image.open(destination / "color.png") as image:
                rgba = np.array(image)
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(rgba[:, :recipe.size // 2, 3].max(), 0)
                self.assertGreater(rgba[:, recipe.size // 2:, 3].max(), 200)
            for filename in ("opacity.png", "roughness.png", "normal.png", "thickness.png"):
                with Image.open(destination / filename) as image:
                    self.assertEqual(image.size, (recipe.size, recipe.size))
            self.assertTrue(np.isfinite(np.load(destination / "thickness_mm.npy")).all())
            self.assertEqual(lab.load_recipe(source / "recipe.json").seed, recipe.seed)
            metadata = json.loads((destination / "metadata.json").read_text())
            self.assertLess(metadata["statistics"]["deposited_ml"], stats["deposited_ml"])

    def test_invalid_parameters_are_rejected(self):
        for changes in ({"viscosity_mpas": 0}, {"speed_m_s": float("nan")}, {"seed": -1},
                        {"size": 1}, {"deep_rgb": [20, 30]}, {"parcels": 1.5},
                        {"fine_splatter": -0.1}, {"fine_splatter": 1.1},
                        {"splatter_length_mm": -1}, {"splatter_spread_mm": float("nan")}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.recipe(**changes).validate()

    def test_rebake_does_not_silently_accept_physics_changes(self):
        with self.assertRaisesRegex(ValueError, "material settings"):
            lab.rebake(Path("unused"), Path("unused"), {"viscosity_mpas": 12})

    def test_fine_splatter_adds_surrounding_detail_without_shuffling_body(self):
        recipe = self.recipe("pool", size=192)
        original, _ = lab.Surface(recipe).generate()
        edited, stats = lab.Surface(replace(recipe, fine_splatter=1)).generate()
        # Every original texel remains after the small liquid transfer. All
        # other differences are added fragments, not a freshly randomized body.
        np.testing.assert_array_less(original * 0.96 - 1e-12, edited)
        self.assertGreater(np.count_nonzero((original < 1e-6) & (edited > 0.002)), 100)
        dense = original > original.max() * 0.5
        self.assertTrue(np.all(edited[dense] >= original[dense] * 0.95))
        self.assertGreater(stats["fine_fragment_count"], 0)
        self.assertAlmostEqual(stats["balance_error_ml"], 0, places=10)

    def test_fine_splatter_conserves_volume_for_all_families_with_clipping(self):
        for kind in lab.KINDS:
            with self.subTest(kind=kind):
                recipe = self.recipe(kind, fine_splatter=0.8, canvas_mm=80, splatter_spread_mm=60)
                height, stats = lab.Surface(recipe).generate()
                self.assertTrue(np.isfinite(height).all())
                self.assertGreater(stats["fine_splatter_ml"], 0)
                self.assertGreater(stats["outside_canvas_ml"], 0)
                self.assertAlmostEqual(stats["balance_error_ml"], 0, places=10)

    def test_scatter_distance_moves_detail_outward(self):
        recipe = self.recipe("pool", size=192)
        original, _ = lab.Surface(recipe).generate()
        close, _ = lab.Surface(replace(recipe, fine_splatter=1, splatter_length_mm=0, splatter_spread_mm=0)).generate()
        far, _ = lab.Surface(replace(recipe, fine_splatter=1, splatter_length_mm=0, splatter_spread_mm=30)).generate()
        close_detail = np.maximum(0, close - original * 0.96)
        far_detail = np.maximum(0, far - original * 0.96)
        self.assertGreater(self.radius(far_detail, recipe), self.radius(close_detail, recipe) * 1.10)

    def test_legacy_recipes_keep_fine_splatter_off_and_new_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "recipe.json"
            path.write_text('{"kind":"pool", "seed":42, "size":96}', encoding="utf-8")
            legacy = lab.load_recipe(path)
            self.assertEqual(legacy.fine_splatter, 0)
            recipe = replace(legacy, fine_splatter=0.6, splatter_length_mm=9, splatter_spread_mm=18)
            height, stats = lab.Surface(recipe).generate()
            lab.export(Path(temp), recipe, height, stats)
            restored = lab.load_recipe(path)
            self.assertEqual(restored.fine_splatter, recipe.fine_splatter)
            self.assertEqual(restored.splatter_length_mm, recipe.splatter_length_mm)
            self.assertEqual(restored.splatter_spread_mm, recipe.splatter_spread_mm)
            repeated, _ = lab.Surface(restored).generate()
            np.testing.assert_array_equal(height, repeated)


if __name__ == "__main__":
    unittest.main()
