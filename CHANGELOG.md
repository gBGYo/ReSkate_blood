# 0.1.2

- Fix plugin crash when trying to remove unloaded decals

# 0.1.1

- Replaces the four striped ground shapes with 20 generated splashes, smears, pools and droplet clusters.
- Uses splash textures on impact, aligned smears for torso slides and compact stains for smaller contacts.
- Preserves all four pigments and avoids consecutive repeats of each primary decal family.
- Imports editable source PNGs into 512-pixel textures with mipmaps; shares opacity and flat normal textures between pigments.

# 0.1.0

- Blood simulation, settings and UI now run in the sandboxed Luau plugin VM.
- Uses general permission-gated particle/decal APIs and local physics geometry.
- Uses the common level root and resident shader declarations across maps.
- Installs and uninstalls as an ordinary mod; no runtime replacement scripts.
