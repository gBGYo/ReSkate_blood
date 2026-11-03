"""Check the real source pack and the native image import contract."""

import json
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw

from tools import prepare_decals as decals


class DecalImportTests(unittest.TestCase):
    def test_all_sources_prepare_with_clear_borders_and_native_header(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = decals.prepare(temporary)
            self.assertEqual(len(list(directory.iterdir())), 20)
            for name in decals.SHAPES:
                data = (directory / f"{name}.rgba").read_bytes()
                self.assertEqual(data[:12], b"BLD1" + struct.pack("<II", 512, 512))
                pixels = np.frombuffer(data[12:], dtype=np.uint8).reshape(512, 512, 4)
                alpha = pixels[..., 3]
                self.assertGreater(int(alpha.max()), 200, name)
                self.assertFalse(alpha[:8].any() or alpha[-8:].any() or alpha[:, :8].any() or alpha[:, -8:].any(), name)

    def test_directional_import_aligns_long_axis_and_uses_opacity_map(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            color = Image.new("RGBA", (1024, 1024), (80, 4, 7, 0))
            color.save(directory / "color.png")
            mask = Image.new("L", (1024, 1024))
            ImageDraw.Draw(mask).rectangle((480, 140, 544, 880), fill=255)
            mask.save(directory / "opacity.png")
            (directory / "recipe.json").write_text(json.dumps({"kind": "smear", "direction_deg": 90}))
            prepared = decals.prepare_image(directory)
            left, top, right, bottom = prepared.getchannel("A").getbbox()
            self.assertGreater(right - left, (bottom - top) * 8)
            self.assertEqual(prepared.getpixel((256, 256)), (80, 4, 7, 255))


if __name__ == "__main__":
    unittest.main()
