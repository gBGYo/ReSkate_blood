# Blood plugin

Blood plugin adds local impact spray, droplets, persistent trails and smears as a ReSkate plugin.
Other players' falls do not emit blood.

## Build

For standalone, editable blood texture experiments, see the
[Blood decal lab](tools/decal_lab/README.md). It generates PNGs from a simplified
fluid model without building or installing game assets. Run `decal_lab.cmd` for
the live desktop GUI; it uses uv and a dedicated `.venv-decal-lab` environment.

Requires Windows, Python 3.10+ with Pillow, CMake 3.24+, Visual Studio 2022 with the C++ workload,
Skate build **20260929**, a ReSkate source checkout and ReSkate Studio's `reskate_cli.exe`.
From this repository's root, run in PowerShell (replace the example paths):

```powershell
uv venv .venv-decal-lab --python 3.12 # Only if this custom environment does not exist yet.
uv pip install --python .venv-decal-lab/Scripts/python.exe -r tools/decal_lab/requirements.txt
.venv-decal-lab/Scripts/python.exe tools/build_assets.py `
  --game "C:/path/to/skate" `
  --reskate-source "C:/path/to/ReSkate" `
  --studio-cli "C:/path/to/reskate_cli.exe"
.venv-decal-lab/Scripts/python.exe tools/package.py
```

After both commands succeed, the plugin ZIP is at `dist/gBGYo_Blood-<version>.zip`,
with a SHA-256 sidecar. See [Repository and packaging](#repository-and-packaging) for details.

## Install

Import the ZIP in the launcher's MODS page, or extract it into `Mods/gBGYo_Blood` beside the game.
Requires a ReSkate runtime with the generalized `reskate.effects` plugin API and `physics_step`
contact geometry/body poses. The manifest requests both `events.physics` and
`events.physics.geometry`; without the geometry permission, impacts cannot be detected.
The generated assets target Skate build **20260929**.

## Usage

Open the **Blood** plugin page in the ReSkate menu and enable **Blood effects**. It starts off.
The page saves effect size, minimum impact damage, reduced effects, trail density, smear width
and length, bleeding duration, mark lifetime and red/green/blue/pink pigments. **Clear marks** removes
the current scene. The `blood` console command shows status; `blood test` runs the Lua model checks.

Loading, replay, Noclip and the park editor suspend effects. Recovery stops bleeding while keeping
ground stains; changing maps, teleporting, disabling or reloading the plugin clears them.

## Repository and packaging

The mod browser description lives in [MOD_README.md](MOD_README.md). Packaging includes
it as the ZIP's `README.md`; this repository README is for development and is not bundled.

This repository contains the Lua plugin, manifests, Blood asset-author sources and build scripts. Compiled assets are
generated locally under ignored `build/assets/`. The release ZIP puts `layout.toc`, `Win32/`
and `.reskate-studio-patch` at the installed mod root, alongside `reskate-plugin.json` and
`plugin/`. It includes 36 particle effects and 80 decal materials (20 shapes in four colors).
Its 84 resident shader declarations are split into four groups for the same common bundle,
within ReSkate's limits of 128 effects and 32 shader depots per group.
Particle assets use the `effects/reskate/gbgyo_blood/` namespace; the runtime requires the
`effects/reskate/` prefix for private particle assets. Regenerate compiled assets with
`tools/build_assets.py` before packaging so their names match the plugin declarations.

Blood's native author lives in `tools/asset_author/`: particle recipes, texture import,
colors, material bindings, deterministic asset identities and merge verification. It builds
as this repository's `blood_asset_author.exe`.

Editable ground texture sources live in [assets/decals](assets/decals/README.md).
The build aligns directional textures, fits their complete splatter into a padded square,
and imports color and opacity at 512 pixels with a full mip chain. Opacity maps are shared
between pigments, and all ground materials share a flat normal. The laboratory's generic
normal and roughness maps are not imported until their native packing is verified.

Building requires Windows, Python 3.10+ with Pillow, CMake 3.24+, Visual Studio 2022 with the C++ workload,
your supported Skate installation, ReSkate Studio's `reskate_cli.exe`, and a ReSkate source
checkout providing the general resource libraries. The checkout supplies archive, EBX, texture,
compression and mod-merge APIs; it does not need the Blood feature or its executable.
The resource dependencies were validated with ReSkate `feature/effects` at `4f07b44`.

From this plugin repository, build and generate assets:

```powershell
.venv-decal-lab/Scripts/python.exe tools/build_assets.py `
  --game "C:/path/to/skate" `
  --reskate-source "C:/path/to/ReSkate" `
  --studio-cli "C:/path/to/reskate_cli.exe"
```

The command checks the game's hash, builds the general resource libraries into
`build/resource-libraries/`, and builds the local generator into
`build/asset-author/bin/blood_asset_author.exe`. SDK sources remain in the external checkout;
the dependency build uses only the resource libraries, without building ReSkate's runtime,
launcher or plugin host. All build output stays under this repository's ignored `build/`.

The generator validates the authored effects and shaders, Studio compiles a fresh patch,
and the local author verifies that all 116 effect roots survive a mod merge. The resulting
asset payload and checksum manifest are written to `build/assets/Patch`.
Game files are read without installing or deploying the mod. A failed build does not publish
its incomplete compiler output.

If you already have matching x64 Release resource libraries from the same checkout, add
`--reskate-build "C:/path/to/ReSkate/build/vs2022-x64"` to reuse them. The Blood generator
is still built from this repository. Otherwise, the command builds its dependencies for you;
subsequent builds are incremental.

Package the generated assets with the current Lua sources:

```powershell
.venv-decal-lab/Scripts/python.exe tools/package.py
```

Output: `dist/gBGYo_Blood-x.y.z.zip` and its SHA-256 sidecar. Packaging validates the generated
`assets.lock.json` and includes only the mod files. Lua-only edits reuse the existing asset
build; regenerate assets when the author or game asset inputs change. Packaging checks a hash
of the local author, importer, source PNGs, recipes and effect declarations and refuses a stale build after a change. It also
reports missing builds. The Python tests do not require built
assets or a game installation.

Both commands accept `--output <directory>`. For a custom asset build location, pass its
`Patch` subdirectory to `python tools/package.py --assets <directory>/Patch`. The packager
also accepts `--version <major.minor.patch>` to override the package version.

## Validation

```powershell
.venv-decal-lab/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" -v
.venv-decal-lab/Scripts/python.exe tools/test_plugin.py --luau C:/path/to/luau.exe
```

The Python tests check the build workflow with fake tools, recipe freshness, asset integrity,
manifest declarations and ZIP contents using temporary fixtures. The second command uses a
standalone Luau interpreter to run 26 model/decal tests and the plugin
lifecycle checks with a fake effects service. It also accepts `luau` on PATH by default.
In the game, `blood test` runs the same model/decal tests.

Native rendering still needs an in-game check: falls and slides, each color, walls and moving
vehicles, recovery, teleport, replay, Noclip, park editing, reload and map changes. In a
multiplayer session, confirm that only local falls emit blood and try a stadium map.
