"""Build this repo's Blood author, then generate and compile the plugin's assets."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

if __package__:
    from . import fbmod
    from .package import REPO, COMMON_ROOT, asset_payload, author_source_hash, validate_effects
else:
    import fbmod
    from package import REPO, COMMON_ROOT, asset_payload, author_source_hash, validate_effects

RESOURCE_LIBRARIES = ("game_archives", "native_db", "frostbite", "json", "mods", "mod_list",
                      "content_cache", "lz4", "miniz", "zstd")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_author(reskate_source, reskate_build=None, root=REPO):
    """Compile local Blood recipes against external, general-purpose resource libraries."""
    root, source = Path(root).resolve(), Path(reskate_source).resolve()
    if not (source / "Engine/Vfs/game_bundles.h").is_file() or not (source / "CMakeLists.txt").is_file():
        raise ValueError(f"ReSkate resource sources were not found at {source}")
    dependencies = Path(reskate_build).resolve() if reskate_build else root / "build/resource-libraries"
    if reskate_build is None:
        # The checkout stays read-only; only the general library target is built.
        print("Building general ReSkate resource libraries...", flush=True)
        subprocess.run(["cmake", "-S", str(root / "tools/asset_author/resource_libraries"),
                        "-B", str(dependencies), "-G", "Visual Studio 17 2022", "-A", "x64",
                        f"-DRESKATE_SOURCE_DIR={source}"], check=True)
        subprocess.run(["cmake", "--build", str(dependencies), "--config", "Release",
                        "--target", "dingosdk_mods", "--parallel", "4"], check=True)
    libraries = dependencies / "Release"
    for name in RESOURCE_LIBRARIES:
        if not (libraries / f"dingosdk_{name}.lib").is_file():
            raise ValueError(f"Missing resource library: {libraries / f'dingosdk_{name}.lib'}")
    native_build = root / "build/asset-author"
    print("Building this repository's Blood asset author...", flush=True)
    subprocess.run(["cmake", "-S", str(root / "tools/asset_author"), "-B", str(native_build),
                    "-G", "Visual Studio 17 2022", "-A", "x64",
                    f"-DRESKATE_SOURCE_DIR={source}", f"-DRESKATE_LIBRARY_DIR={libraries}"], check=True)
    subprocess.run(["cmake", "--build", str(native_build), "--config", "Release",
                    "--target", "blood_asset_author", "--parallel", "4"], check=True)
    executable = native_build / "bin/blood_asset_author.exe"
    if not executable.is_file():
        raise ValueError(f"The local Blood author was not built: {executable}")
    return executable


def validate_authored(authored, plugin):
    resources = json.loads((authored / "resources.json").read_text(encoding="utf-8"))["resources"]
    rows = {(row["kind"], row["name"]): row for row in resources}
    bundle = plugin["resident"][0]["bundle"]
    for name in plugin["effects"]:
        row = rows.get((1, name), {})
        kind = "EffectBlueprint" if name.startswith("effects/") else "EnvironmentDecalVolumeTemplateData"
        if not row.get("added") or row.get("target") != bundle or row.get("root_type") != kind:
            raise ValueError(f"Missing or incompatible authored Blood effect: {name}")
    for depot in plugin["resident"][0]["shaders"]:
        row = rows.get((2, depot["name"]), {})
        if not row.get("added") or row.get("target") != bundle:
            raise ValueError(f"Missing resident Blood shader: {depot['name']}")


def record_assets(patch, config, author, compiler, root=REPO):
    paths = [patch / "layout.toc", patch / ".reskate-studio-patch", patch / COMMON_ROOT]
    for directory in ("Win32", "Data"):
        paths.extend(path for path in (patch / directory).rglob("*")
                     if path.is_file() and path.suffix.lower() in {".toc", ".cas"})
    files = {}
    for path in sorted(set(paths)):
        files[path.relative_to(patch).as_posix()] = {"size": path.stat().st_size, "sha256": sha256(path)}
    lock = {"game_build": config["game_build"], "skate_sha256": config["skate_sha256"],
            "author_sources": author_source_hash(root),
            "tools": {"asset_author": sha256(author), "studio_cli": sha256(compiler)}, "files": files}
    (patch / "assets.lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")


def build(game, compiler, reskate_source, output=REPO / "build/assets", root=REPO, reskate_build=None):
    game, compiler = Path(game).resolve(), Path(compiler).resolve()
    root, output = Path(root).resolve(), Path(output).resolve()
    config = json.loads((root / "assets/build.json").read_text(encoding="utf-8"))
    if sha256(game / "Skate.exe") != config["skate_sha256"]:
        raise ValueError(f"Blood assets require Skate build {config['game_build']} from assets/build.json")
    if not compiler.is_file():
        raise ValueError(f"Build tool was not found: {compiler}")
    plugin = json.loads((root / "reskate-plugin.json").read_text(encoding="utf-8"))
    validate_effects(plugin)
    author = build_author(reskate_source, reskate_build, root)
    version = json.loads((root / "manifest.json").read_text(encoding="utf-8"))["version_number"]
    output.mkdir(parents=True, exist_ok=True)
    # Each compiler run starts empty so a rebuild cannot inherit an obsolete asset.
    # Temporary cleanup is confined to this newly created child of the output directory.
    with tempfile.TemporaryDirectory(prefix=".blood-build-", dir=output) as temporary:
        work = Path(temporary).resolve()
        if not work.is_relative_to(output) or work == output:
            raise ValueError("Temporary build directory is outside the output directory")
        authored, fbmod_path, compiled = work / "authored", work / "blood.fbmod", work / "compiled"
        print("Authoring Blood effects from the supported game files...", flush=True)
        subprocess.run([str(author), str(game), str(authored)], check=True, cwd=work)
        validate_authored(authored, plugin)
        fbmod.package(authored, fbmod_path, version)
        print("Compiling the Blood asset patch...", flush=True)
        subprocess.run([str(compiler), "compile-mod", str(game), str(compiled), str(fbmod_path)], check=True, cwd=work)
        patch = compiled / "Patch"
        # The merge verifier needs the resident declarations to test all maps.
        for name in ("reskate-plugin.json", "manifest.json"):
            shutil.copyfile(root / name, patch / name)
        print("Verifying all 52 effects in the common level root...", flush=True)
        subprocess.run([str(author), str(game), str(patch), "--verify-merge"], check=True, cwd=work)
        record_assets(patch, config, author, compiler, root)
        files = asset_payload(patch, root)
        destination = output / "Patch"
        # Publish only verified asset files; the lock lists exactly this build's payload.
        # Old unlisted files cannot enter a release, and no game files are changed.
        for name, data in files.items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        shutil.copyfile(patch / "assets.lock.json", destination / "assets.lock.json")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True, help="Supported game directory containing Skate.exe")
    parser.add_argument("--reskate-source", type=Path, required=True, help="External ReSkate checkout providing general resource libraries")
    parser.add_argument("--reskate-build", type=Path, help="Reuse its existing x64 Release library build instead of building libraries locally")
    parser.add_argument("--studio-cli", type=Path, required=True, help="External ReSkate Studio reskate_cli.exe")
    parser.add_argument("--output", type=Path, default=REPO / "build/assets")
    args = parser.parse_args()
    try:
        result = build(args.game, args.studio_cli, args.reskate_source, args.output, reskate_build=args.reskate_build)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Blood asset build failed: {error}\n")
    print(f"Assets: {result}")
    print(f'Package with: python tools/package.py --assets "{result}"')


if __name__ == "__main__":
    main()
