"""Prepare editable decal PNGs for the native Blood author (no simulation at build time)."""

import json
from pathlib import Path
import struct

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
FAMILIES = ("splash", "smear", "pool", "drops")
SHAPES = tuple(f"{family}_{number:02d}" for family in FAMILIES for number in range(1, 6))
SIZE = 512


def prepare_image(directory):
    """Align directional marks and fit all visible splatter inside a padded square."""
    directory = Path(directory)
    recipe = json.loads((directory / "recipe.json").read_text(encoding="utf-8"))
    with Image.open(directory / "color.png") as source:
        color = source.convert("RGBA")
    with Image.open(directory / "opacity.png") as source:
        opacity = source.convert("L")
    if color.size != opacity.size or color.width != color.height:
        raise ValueError(f"Decal color and opacity must be matching square images: {directory}")
    if color.width < SIZE or color.width > 4096:
        raise ValueError(f"Decal source must be 512..4096 pixels: {directory}")
    color.putalpha(opacity)
    if recipe["kind"] in ("smear", "drops"):
        # Simulation Y points down the image; PIL positive rotation removes it.
        color = color.rotate(float(recipe["direction_deg"]), Image.Resampling.BICUBIC, expand=True)
    bounds = color.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError(f"Empty decal: {directory}")
    left, top, right, bottom = bounds
    extent = max(right - left, bottom - top)
    side = int(extent * 1.12 + 2)
    x, y = (left + right - side) // 2, (top + bottom - side) // 2
    color = color.crop((x, y, x + side, y + side)).resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    # Straight alpha color, top-to-bottom rows. The native author creates mips
    # and puts alpha into the donor's OSM red channel; it is not color alpha alone.
    return color


def prepare(output, root=REPO):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for name in SHAPES:
        image = prepare_image(Path(root) / "assets/decals" / name)
        (output / f"{name}.rgba").write_bytes(
            b"BLD1" + struct.pack("<II", image.width, image.height) + image.tobytes())
    return output
