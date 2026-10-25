"""Package Blood's scripts with locally generated effects from build/assets/Patch."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

REPO = Path(__file__).resolve().parents[1]
METADATA = (
    "reskate-plugin.json", "manifest.json", "CHANGELOG.md", "icon.png", "LICENSE",
)
COMMON_ROOT = "Win32/levels/game/dingolevel_root/dingolevel_root.toc"
DEFAULT_ASSETS = REPO / "build/assets/Patch"
AUTHOR_SOURCES = (
    "assets/build.json", "tools/asset_author/CMakeLists.txt",
    "tools/asset_author/resource_libraries/CMakeLists.txt",
    "tools/asset_author/blood_asset_author.cpp", "tools/asset_author/blood_assets.h",
    "tools/asset_author/blood_ground_asset.h",
)


def author_source_hash(root=REPO):
    digest = hashlib.sha256()
    for name in AUTHOR_SOURCES:
        digest.update(name.encode("utf-8") + b"\0")
        # Git's newline conversion must not invalidate an otherwise identical recipe.
        digest.update((Path(root) / name).read_text(encoding="utf-8").encode("utf-8") + b"\0")
    return digest.hexdigest()


def asset_payload(directory, root=REPO):
    directory = Path(directory)
    lock_path = directory / "assets.lock.json"
    if not lock_path.is_file():
        raise ValueError("Blood assets have not been built. Run python tools/build_assets.py --help for build options.")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    config = json.loads((Path(root) / "assets/build.json").read_text(encoding="utf-8"))
    if lock["skate_sha256"] != config["skate_sha256"]:
        raise ValueError("Blood assets do not match the supported Skate build; rebuild them")
    if lock.get("author_sources") != author_source_hash(root):
        raise ValueError("Blood asset recipes changed or were not recorded; rebuild with tools/build_assets.py")
    assets = lock["files"]
    if not {"layout.toc", ".reskate-studio-patch", COMMON_ROOT} <= assets.keys():
        raise ValueError("Missing common-root Blood assets in assets.lock.json")
    files = {}
    for name, identity in assets.items():
        path = PurePosixPath(name)
        if (path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name
                or path.as_posix() != name):
            raise ValueError(f"Invalid asset path: {name}")
        if name not in {"layout.toc", ".reskate-studio-patch"} and not (
            path.parts[0] in {"Win32", "Data"} and path.suffix.lower() in {".toc", ".cas"}
        ):
            raise ValueError(f"Not a compiled Blood asset: {name}")
        data = (directory / name).read_bytes()
        if len(data) != identity["size"] or hashlib.sha256(data).hexdigest() != identity["sha256"]:
            raise ValueError(f"Asset checksum mismatch: {name}")
        files[name] = data

    stamp = files[".reskate-studio-patch"].decode("utf-8").splitlines()
    if (not stamp or stamp[0] != "ReSkate Studio native Patch v1"
            or f"skate_sha256={config['skate_sha256']}" not in stamp):
        raise ValueError("Blood assets do not match the supported Skate build")
    return files


def validate_effects(plugin):
    # Match the runtime's private_effect_asset/parse_manifest contract: a bad
    # namespace rejects the entire plugin before its menu can be registered.
    effects = plugin.get("effects", [])
    if (not isinstance(effects, list) or len(effects) > 128
            or ("effects" in plugin and "effects" not in plugin.get("permissions", []))):
        raise ValueError("ReSkate effects need the effects permission and at most 128 asset names")
    for name in effects:
        if (not isinstance(name, str) or len(name) > 240
                or not re.fullmatch(r"(?:effects/reskate/|world/materials/decal/reskate_)[a-z0-9_/-]+", name)
                or name.endswith("/") or "//" in name):
            raise ValueError(f"ReSkate rejects effect asset path: {name!r}; use effects/reskate/ or world/materials/decal/reskate_")


def payload(root=REPO, version=None, assets=None):
    root = Path(root)
    directory = Path(assets) if assets is not None else root / "build/assets/Patch"
    files = asset_payload(directory, root)
    for name in METADATA:
        files[name] = (root / name).read_bytes()
    # Mod browsers display this description instead of the repository's build docs.
    files["README.md"] = (root / "MOD_README.md").read_bytes()
    for path in sorted((root / "plugin").rglob("*.lua")):
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    plugin = json.loads(files["reskate-plugin.json"])
    validate_effects(plugin)
    if plugin["entry"] not in files:
        raise ValueError("The plugin entry script is missing")
    manifest = json.loads(files["manifest.json"])
    version = manifest["version_number"] if version is None else version
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("version must be major.minor.patch")
    manifest["version_number"] = version
    files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    for name, data in files.items():
        if data.startswith(b"MZ"):
            raise ValueError(f"A plugin package cannot contain a program: {name}")
    return files, version


def package(output=REPO / "dist", version=None, root=REPO, assets=None):
    files, version = payload(root, version, assets)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / f"gBGYo_Blood-{version}.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, data in sorted(files.items()):
            # Fixed metadata makes the same inputs produce the same release checksum.
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    archive_path.with_suffix(".zip.sha256").write_text(
        f"{digest}  {archive_path.name}\n", encoding="ascii"
    )
    return archive_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="Override manifest.json's major.minor.patch version")
    parser.add_argument("--output", type=Path, default=REPO / "dist")
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS, help="Generated Patch directory containing assets.lock.json")
    args = parser.parse_args()
    try:
        result = package(args.output, args.version, assets=args.assets)
    except (ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")
    print(f"Package: {result}")


if __name__ == "__main__":
    main()
