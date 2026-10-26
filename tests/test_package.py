"""Check the standalone mod's payload, declarations and release archive."""

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from tools import package as packer

REPO = Path(__file__).resolve().parents[1]


class RepositoryTests(unittest.TestCase):
    def test_declared_effects_without_building_assets(self):
        plugin = json.loads((REPO / "reskate-plugin.json").read_text())
        packer.validate_effects(plugin)
        self.assertEqual(plugin["api"], 1)
        self.assertEqual(plugin["side"], "client")
        self.assertEqual(set(plugin["permissions"]), {
            "effects", "events.physics", "events.physics.geometry", "skater.read", "menu", "storage", "console",
        })
        effects = {
            f"effects/reskate/gbgyo_blood/ebp_blood_{kind}{tier}{color}"
            for kind in ("spray", "droplets", "trail")
            for tier in ("", "_light", "_heavy")
            for color in ("", "_green", "_blue", "_pink")
        } | {
            f"world/materials/decal/reskate_blood/reskate_blood{variant}{color}_dv"
            for variant in ("", "_broken", "_clotted", "_drop")
            for color in ("", "_green", "_blue", "_pink")
        }
        self.assertEqual(len(plugin["effects"]), 52)
        self.assertEqual(set(plugin["effects"]), effects)
        resident, = plugin["resident"]
        self.assertEqual(resident["bundle"], packer.COMMON_ROOT[:-4].lower())
        self.assertEqual(len(resident["shaders"]), 20)
        self.assertEqual({root for depot in resident["shaders"] for root in depot["roots"]}, effects)
        for effect in effects:
            self.assertTrue(any(effect == root or (root.endswith("/") and effect.startswith(root))
                                for root in resident["roots"]), effect)

class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="blood-package-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "mod"
        self.root.mkdir()
        for name in (*packer.METADATA, "MOD_README.md", "README.md"):
            shutil.copyfile(REPO / name, self.root / name)
        shutil.copytree(REPO / "plugin", self.root / "plugin")
        shutil.copytree(REPO / "assets", self.root / "assets")
        shutil.copytree(REPO / "tools/asset_author", self.root / "tools/asset_author")
        self.assets = self.root / "build/assets/Patch"
        config = json.loads((self.root / "assets/build.json").read_text())
        self.lock = {"skate_sha256": config["skate_sha256"],
                     "author_sources": packer.author_source_hash(self.root), "files": {}}
        for name in ("layout.toc", packer.COMMON_ROOT, "Win32/configurations/layout/defaultinstallpackage/cas_01.cas"):
            self.write_asset(name, b"test asset")
        self.write_asset(".reskate-studio-patch",
                         f"ReSkate Studio native Patch v1\nskate_sha256={config['skate_sha256']}\n".encode())
        self.save_lock()

    def test_package_contents_and_checksum(self):
        with tempfile.TemporaryDirectory(prefix="blood-release-") as directory:
            path = packer.package(Path(directory), root=self.root)
            expected, _ = packer.payload(self.root)
            with zipfile.ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(set(archive.namelist()), set(expected))
                for name, data in expected.items():
                    self.assertEqual(archive.read(name), data, name)
                    self.assertNotIn(Path(name).suffix.lower(), {".exe", ".dll", ".cpp", ".h", ".ps1", ".bat", ".cmd"})
                    self.assertFalse(data.startswith(b"MZ"), name)
                self.assertNotIn("assets.lock.json", archive.namelist())
                self.assertEqual(archive.read("README.md"), (self.root / "MOD_README.md").read_bytes())
                self.assertNotEqual(archive.read("README.md"), (self.root / "README.md").read_bytes())
                self.assertNotIn("MOD_README.md", archive.namelist())
                self.assertFalse(any(n.startswith(("tools/", "tests/", "build/", ".git/")) for n in archive.namelist()))
            self.assertEqual(path.with_suffix(".zip.sha256").read_text().split()[0],
                             hashlib.sha256(path.read_bytes()).hexdigest())
    def write_asset(self, name, data):
        path = self.assets / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.lock["files"][name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def save_lock(self):
        (self.assets / "assets.lock.json").write_text(json.dumps(self.lock), encoding="utf-8")

    def test_missing_build_explains_how_to_generate_assets(self):
        (self.assets / "assets.lock.json").unlink()
        with self.assertRaisesRegex(ValueError, "tools/build_assets.py"):
            packer.payload(self.root)

    def test_external_asset_directory(self):
        files, _ = packer.payload(self.root, assets=self.assets)
        self.assertIn(packer.COMMON_ROOT, files)

    def test_changed_recipe_requires_a_rebuild(self):
        recipe = self.root / "tools/asset_author/blood_assets.h"
        recipe.write_text(recipe.read_text() + "\n// changed pigment\n")
        with self.assertRaisesRegex(ValueError, "asset recipes changed"):
            packer.payload(self.root)

    def test_missing_common_root_is_refused(self):
        del self.lock["files"][packer.COMMON_ROOT]
        self.save_lock()
        with self.assertRaisesRegex(ValueError, "common-root"):
            packer.payload(self.root)

    def test_missing_asset_is_refused(self):
        (self.assets / packer.COMMON_ROOT).unlink()
        with self.assertRaises(FileNotFoundError):
            packer.payload(self.root)

    def test_modified_asset_is_refused(self):
        (self.assets / packer.COMMON_ROOT).write_bytes(b"corrupted asset")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            packer.payload(self.root)

    def test_wrong_game_build_is_refused(self):
        self.write_asset(".reskate-studio-patch", b"ReSkate Studio native Patch v1\nskate_sha256=wrong\n")
        self.save_lock()
        with self.assertRaisesRegex(ValueError, "supported Skate"):
            packer.payload(self.root)

    def test_sdk_and_installer_files_are_excluded(self):
        for name in ("ReSkate.dll", "Install.bat", "plugin/old.dll"):
            (self.root / name).write_bytes(b"MZold program")
        (self.assets / "Win32/old.dll").write_bytes(b"MZold program")
        files, _ = packer.payload(self.root)
        self.assertFalse(any(name.endswith((".dll", ".bat")) for name in files))

    def test_asset_paths_cannot_include_programs_or_escape_the_mod(self):
        for name in ("../other.toc", "C:/other.toc", "Win32/../other.toc", "Win32\\other.toc", "Win32/old.dll"):
            with self.subTest(name=name):
                self.lock["files"][name] = {"size": 0, "sha256": ""}
                self.save_lock()
                with self.assertRaises(ValueError):
                    packer.payload(self.root)
                del self.lock["files"][name]

    def test_executable_disguised_as_asset_is_refused(self):
        self.write_asset(packer.COMMON_ROOT, b"MZprogram")
        self.save_lock()
        with self.assertRaisesRegex(ValueError, "program"):
            packer.payload(self.root)

    def test_missing_entry_script_is_refused(self):
        (self.root / "plugin/main.lua").unlink()
        with self.assertRaisesRegex(ValueError, "entry script"):
            packer.payload(self.root)

    def test_effect_paths_rejected_by_runtime_cannot_be_packaged(self):
        path = self.root / "reskate-plugin.json"
        plugin = json.loads(path.read_text())
        for name in ("effects/gbgyo_blood/ebp_blood_spray", "effects/gestures/ebp_gesture_applause",
                     "world/materials/decal/gbgyo_blood/blood_dv", "effects/reskate/",
                     "effects/reskate/blood/", "effects/reskate//blood", "effects/reskate/Blood",
                     "effects/reskate/../blood", "effects/reskate/" + "b" * 226, None):
            with self.subTest(name=name):
                plugin["effects"][0] = name
                path.write_text(json.dumps(plugin))
                with self.assertRaisesRegex(ValueError, "ReSkate rejects effect asset path"):
                    packer.package(Path(self.temp.name) / "out", root=self.root)

    def test_effects_need_runtime_permission_and_fit_its_limit(self):
        path = self.root / "reskate-plugin.json"
        original = path.read_text()
        for case in ("permission", "count", "type"):
            with self.subTest(case=case):
                plugin = json.loads(original)
                if case == "permission":
                    plugin["permissions"].remove("effects")
                elif case == "count":
                    plugin["effects"] = [plugin["effects"][0]] * 129
                else:
                    plugin["effects"] = "effects/reskate/gbgyo_blood/ebp_blood_spray"
                path.write_text(json.dumps(plugin))
                with self.assertRaisesRegex(ValueError, "ReSkate effects need"):
                    packer.payload(self.root)

    def test_version_and_reproducible_archive(self):
        out = Path(self.temp.name) / "out"
        original_manifest = (self.root / "manifest.json").read_bytes()
        first = packer.package(out, "1.2.3", self.root)
        digest = hashlib.sha256(first.read_bytes()).hexdigest()
        with zipfile.ZipFile(first) as archive:
            self.assertEqual(json.loads(archive.read("manifest.json"))["version_number"], "1.2.3")
        self.assertEqual(first.name, "gBGYo_Blood-1.2.3.zip")
        second = packer.package(out, "1.2.3", self.root)
        self.assertEqual(hashlib.sha256(second.read_bytes()).hexdigest(), digest)
        self.assertEqual((self.root / "manifest.json").read_bytes(), original_manifest)
        for invalid in ("1.2", "../escape", "1.2.3-beta", ""):
            with self.subTest(version=invalid), self.assertRaisesRegex(ValueError, "major.minor.patch"):
                packer.package(out, invalid, self.root)


if __name__ == "__main__":
    unittest.main()
