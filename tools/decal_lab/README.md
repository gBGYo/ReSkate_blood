# Blood decal lab

An offline, physics-inspired texture generator. It creates editable splashes,
sliding smears, settled pools and drop trails. It does not modify the Lua plugin,
compile game assets or install anything in Skate.

## Desktop GUI

Double-click **`decal_lab.cmd`** in the repository root, or run it from PowerShell:

```powershell
.\decal_lab.cmd
```

The launcher uses **uv** to create a dedicated **`.venv-decal-lab`** environment
with Python 3.12 and install the art/GUI dependencies there. Its package cache is
under `build/uv-cache`; system Python packages are not modified. Both directories
are ignored by Git. uv must be on PATH; see the
[uv installation instructions](https://docs.astral.sh/uv/getting-started/installation/).

Choose a decal family and move the sliders, or type a value and press Enter. The
preview refreshes automatically after a short pause. Each family remembers its
settings while the window is open. **New seed** changes the pattern; keeping the
seed fixed makes parameter comparisons easier.

- **Shape** controls the liquid, surface, movement and physical canvas size.
  Settings that do not affect the selected family are hidden.
- **Fine splatter**, at the top of Shape, adds small tapered streaks and droplets
  around the main blood deposit. **Amount** controls density (0 is off),
  **Streak length** controls their length (0 makes droplets only), and
  **Scatter distance** controls how far they land from the edge. These work with
  every family, including pools and smears. The main shape stays fixed as you
  adjust them. Try Amount **0.6**, Streak length **8 mm**, Scatter distance **12 mm**.
- **Material** controls pigment, opacity and reflective roughness. These changes
  reuse the current thickness field rather than rerunning the simulation.
- Select **Color**, **Opacity**, **Thickness**, **Roughness** or **Normals** above
  the preview. Color can be shown on light, dark or checker backgrounds, or both
  light and dark side by side. This is an unlit preview, not an in-game render.
- Wheel to zoom, drag to pan, or choose **Fit** / **1:1**.
- **Fast preview** uses at most 256 pixels per side and 24 impact integration steps,
  keeping the same seed and parcel count. **Full resolution** uses the selected
  output size and the original 80 steps. Fine detail and opacity can differ in the
  approximation. Export always uses the full simulation and selected output size.
- **Load recipe** opens existing JSON recipes. **Save recipe** records the current
  parameters. **Export textures** creates a new dated variant folder under the
  destination you select; existing artwork is never replaced. An export captures
  the settings at the time you click it, even if you keep adjusting the preview.

Simulation runs in a background worker. New shape edits cancel superseded work;
slider changes do not accumulate a long queue of old previews. Expensive settings
still take time to compute. A requested export finishes even if the window closes.

To use an existing recipe at startup:

```powershell
.\decal_lab.cmd --config build/decal_lab/splash_42/recipe.json
```

## Command line

For manual setup from the repository root:

```powershell
uv --cache-dir build/uv-cache venv --python 3.12 .venv-decal-lab
uv --cache-dir build/uv-cache pip install --python .venv-decal-lab/Scripts/python.exe -r tools/decal_lab/requirements-gui.txt
$decalPython = (Resolve-Path .venv-decal-lab/Scripts/python.exe).Path
& $decalPython tools/generate_decals.py
```

The examples below use `$decalPython` from this setup. The CLI generator itself
requires only `requirements.txt`; the GUI adds PySide6 Essentials.

Open `build/decal_lab/contact_sheet.png`. The default run makes three variants of
each family, with seeds 42, 43 and 44, at 512x512. Each is shown on light and dark
backgrounds. These are unlit color/opacity previews; wet highlights will come from
the game material when the assets are integrated.

## Change a result

Keep the seed and canvas size fixed while comparing parameters. For example:

```powershell
& $decalPython tools/generate_decals.py --kind splash --count 1 --seed 42 --set viscosity_mpas=12 --output build/thick_blood
& $decalPython tools/generate_decals.py --kind splash --count 1 --seed 42 --set speed_m_s=6 --output build/fast_impact
& $decalPython tools/generate_decals.py --kind smear --count 1 --set drag_curve=-0.25 --set drag_width_mm=55 --output build/wide_smear
& $decalPython tools/generate_decals.py --kind pool --count 1 --set fine_splatter=0.6 --set splatter_length_mm=8 --set splatter_spread_mm=12 --output build/pool_with_splatter
```

Every variant has a complete `recipe.json`. Edit it in a text editor and reuse it:

```powershell
& $decalPython tools/generate_decals.py --config build/decal_lab/splash_42/recipe.json --count 1 --output build/my_splash
```

`--set NAME=JSON` overrides individual recipe values. `--size 1024` increases export
resolution. `--count 1` is useful during iteration; omit it to generate consecutive
seeds. Existing output is protected: choose a new directory, or explicitly use
`--overwrite`. Overwrite replaces generated files; it does not remove unrelated files.

| Parameter | Meaning and expected effect |
| --- | --- |
| `volume_ml` | Total liquid volume. More liquid makes larger and/or thicker marks. |
| `speed_m_s` | Incoming impact speed; higher speeds generally spread farther and eject more droplets. For smears, this is sliding speed. Unused for settled pools. |
| `viscosity_mpas` | Dynamic viscosity in mPa s. Higher values limit impact spread, reduce smear transfer and shorten fine streaks. Does not affect the settled pool body. |
| `surface_tension_mnm` | Surface tension in mN/m. Limits impact spreading when capillarity dominates; sets the pool depth scale. |
| `density_kg_m3` | Liquid density used in inertial/capillary scales. |
| `surface_roughness` | 0..1 substrate irregularity: uneven friction, pinning and splash breakup. This is separate from material roughness. |
| `angle_deg` | 0 means a perpendicular impact; larger values elongate it. Not used for pools/smears. |
| `direction_deg` | Direction on the image; positive angles turn clockwise because image Y points down. |
| `contact_angle_deg` | Pool wetting angle. Smaller angles give shallower, wider pools. Used only for pools. |
| `drag_length_mm`, `drag_width_mm` | Smear travel distance and contact width. |
| `drag_curve` | Smear bend, -0.5..0.5. Zero produces a straight slide. |
| `canvas_mm` | Physical width of the square image. Increasing it adds surrounding space without rescaling the simulation. |
| `absorption_mm` | Thickness scale for opacity: smaller values make thin liquid more opaque. |
| `deep_rgb`, `thin_rgb` | Three sRGB byte values for dense and thin liquid. |
| `wet_roughness`, `dry_roughness` | Material roughness of thick and thin deposits; 0 is smooth, 1 is rough. |
| `parcels` | Impact sampling budget. Larger values reduce particle sampling artifacts but take longer. |
| `fine_splatter` | 0..1 density of fine rim streaks and satellite droplets. Default 0 preserves existing recipes. |
| `splatter_length_mm` | Fine streak runout at the reference viscosity (4 mPa s), 0..30 mm. Actual lengths vary; 0 produces droplets only. |
| `splatter_spread_mm` | Scatter distance from the main body's edge, 0..60 mm. A portion stays attached to the rim. |

The values are starting points for artwork, not measured properties of a particular
blood sample. The simulated surface is flat and horizontal. Gravity acts on airborne
droplets; wall drips and sloping surfaces are not implemented.

If the tool reports clipping, increase `canvas_mm` with the same seed. Cropping is
reported as lost volume rather than silently fitting the mark to the image. A larger
canvas can require a higher resolution to retain fine droplets. Particle footprints
and the final raster filter impose a minimum detail size, so very small features can
change slightly between resolutions.

Fine splatter uses a separate seeded random stream, so changing these three
controls does not shuffle the main body. At most 4% of the deposited volume is
transferred to this optional layer, slightly thinning the center while preserving
its silhouette. Fragment positions follow the large deposits' outer boundaries;
short streaks use a slowing trajectory and finite liquid supply. This is an
art-directed approximation of secondary breakup, not a separate resolved fluid
simulation. Very fine marks are easier to inspect in Full resolution at 512 or
1024 pixels. Saved recipes and exported material maps include the fine detail.

## Edit the images

Each variant contains:

| File | Use |
| --- | --- |
| `color.png` | Dark red artwork with straight alpha, without baked lighting. |
| `opacity.png` | Grayscale coverage/opacity, black outside the blood. |
| `thickness.png` | **Editable master**, 16-bit grayscale. Black is no blood; white's thickness in mm is recorded in `metadata.json`. |
| `thickness_mm.npy` | Float32 thickness data for numerical inspection. |
| `roughness.png` | Linear scalar roughness, black smooth and white rough. |
| `normal.png` | Linear RGB tangent normal, +X right, +Y up, +Z out. |
| `preview_light.png`, `preview_dark.png` | Unlit previews on checker backgrounds. |
| `recipe.json`, `metadata.json` | Reproducible inputs, map conventions, thickness scale and volume accounting. |

For consistent edits, paint **thickness.png** in an image editor that preserves
16-bit grayscale, keeping its resolution unchanged. Make holes with black, add or
join liquid with gray, and lighten areas to make them thicker. Keep the recipe and
metadata beside it. Then regenerate all material maps:

```powershell
& $decalPython tools/generate_decals.py --rebake build/decal_lab/splash_42
```

This writes to `build/decal_lab/splash_42_edited`, preserving the source. Use
`--output` to choose another destination. Material settings also work with rebake:

```powershell
& $decalPython tools/generate_decals.py --rebake build/decal_lab/splash_42 --set absorption_mm=0.015 --set 'deep_rgb=[58,2,5]' --output build/darker_splash
```

Rebake reads thickness.png, **not** edits made to color.png or opacity.png. You can
edit those maps individually for final artwork, but rebuilding will derive them
again from thickness. The 16-bit master is normalized to its recorded maximum;
its quantization can remove extremely thin traces on rebake.

These maps use generic conventions. They are **not ready-packed Frostbite assets**.
The existing native author still generates its original textures. Integration needs
image import and verification of the donor material's actual channel packing,
normal convention and roughness versus smoothness interpretation.

## What the model simulates

Impacts distribute liquid into moving parcels. Their expansion uses Weber and
Reynolds numbers, a capillary time scale, a viscous spreading limit and spatially
varying linear drag. Parcels transfer finite amounts of liquid to the surface along
their paths. Perturbed rim sectors form ligaments; a fraction of the liquid takes
ballistic trajectories under gravity and deposits as secondary drops.

The inertial spread scaling `beta ~ We^(1/4)` is motivated by
[Clanet et al., *Maximal deformation of an impacting drop* (2004)](https://researchportal.ip-paris.fr/fr/publications/maximal-deformation-of-an-impacting-drop/).
That study includes low-viscosity drops on particular surfaces. Applying its scaling
here does not validate this model for blood. The viscous cap, rim perturbations,
breakup fraction and adhesion rates are artistic approximations.

Smears transport a finite liquid supply along a curved contact path. Uneven contact
channels lose liquid according to local friction, viscosity and travel. Liquid still
on the contact when it lifts is recorded as carried away. Pools use an equilibrium
approximation: capillary length and contact angle set a characteristic depth,
volume sets area, and substrate pinning perturbs the edge. Pool viscosity and impact
speed are intentionally absent from that equilibrium construction. The depth scale
uses `2 * capillary_length * sin(contact_angle / 2)`, the large-puddle relation
given in [Dong (2017), equation 135](https://www.math.purdue.edu/~sdong/PDF/Nphase_ContAngle_JCP2017.pdf).

All deposits add **volume**, not alpha. Overlap therefore increases film thickness.
Opacity uses an exponential thickness response; color and roughness are derived
from that same thickness. Volume transferred outside the canvas is accounted for.
This is a reduced model for art generation, not a Navier-Stokes solver: it omits
explicit pressure coupling between parcels, dynamic coalescence, non-Newtonian
rheology, drying, absorption into the substrate and full 3D fluid motion.

## Validation

With the optional dependencies installed:

```powershell
& $decalPython -m unittest tests.test_generate_decals tests.test_decal_preview tests.test_decal_gui -v
```

The checks cover volume accounting, no wrapping at canvas boundaries, reproducible
seeds, the effect of viscosity, physical scale across resolutions, map export and
rebaking an edited thickness master. Without these dependencies the art tests skip;
asset-build and import tests require Pillow, and import tests also use NumPy.
Packaging itself uses only the Python standard library. Preview tests also check
superseded-job cancellation, material-map reuse, export resolution and preservation
of existing output folders. The GUI checks run Qt offscreen and exercise its real
controls, map views, event loop and export workflow.
