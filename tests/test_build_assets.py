"""Exercise the asset build workflow without a game installation or native tools."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import build_assets as builder
from tools import package as packer

REPO = Path(__file__).resolve().parents[1]


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="blood-build-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(REPO / "assets", self.root / "assets")
        shutil.copytree(REPO / "tools/asset_author", self.root / "tools/asset_author")
        for name in ("reskate-plugin.json", "manifest.json"):
            shutil.copyfile(REPO / name, self.root / name)
        self.game = self.root / "game"
        self.game.mkdir()
        (self.game / "Skate.exe").write_bytes(b"test game")
        self.config = json.loads((self.root / "assets/build.json").read_text())
        self.config["skate_sha256"] = builder.sha256(self.game / "Skate.exe")
        (self.root / "assets/build.json").write_text(json.dumps(self.config))
        self.author, self.compiler = self.root / "author.exe", self.root / "studio.exe"
        self.author.write_bytes(b"author")
        self.compiler.write_bytes(b"studio")
        self.output = self.root / "build/assets"
        self.plugin = json.loads((self.root / "reskate-plugin.json").read_text())

    def run_build(self):
        with patch.object(builder, "build_author", return_value=self.author):
            return builder.build(self.game, self.compiler, self.root / "external-sdk", self.output, self.root)

    def fake_tool(self, args, **kwargs):
        self.assertTrue(kwargs["check"])
        if args[-1] == "--verify-merge":
            mod = Path(args[2])
            self.assertEqual(json.loads((mod / "reskate-plugin.json").read_text()), self.plugin)
            self.assertTrue((mod / "manifest.json").is_file())
        elif args[0] == str(self.author):
            authored = Path(args[2])
            authored.mkdir()
            (authored / "payload.cas").write_bytes(b"authored payload")
            rows = []
            names = [(1, name) for name in self.plugin["effects"]]
            names += [(2, depot["name"]) for depot in self.plugin["resident"][0]["shaders"]]
            for kind, name in names:
                rows.append({"kind": kind, "name": name, "added": True, "file": "payload.cas", "size": 16,
                             "target": self.plugin["resident"][0]["bundle"], "meta": "", "type": 0, "rid": 1,
                             "root_type": "EffectBlueprint" if name.startswith("effects/") else "EnvironmentDecalVolumeTemplateData"})
            (authored / "resources.json").write_text(json.dumps({"resources": rows}))
        else:
            self.assertEqual(args[1], "compile-mod")
            self.assertTrue(Path(args[4]).is_file())
            mod = Path(args[3]) / "Patch"
            for name in ("layout.toc", packer.COMMON_ROOT, "Win32/configurations/layout/defaultinstallpackage/cas_01.cas"):
                target = mod / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"compiled asset")
            (mod / ".reskate-studio-patch").write_text(
                f"ReSkate Studio native Patch v1\nskate_sha256={self.config['skate_sha256']}\n")
            (mod / "initfs_win32").write_bytes(b"unneeded compiler output")

    def test_build_validates_and_publishes_only_assets(self):
        with patch.object(builder.subprocess, "run", side_effect=self.fake_tool) as run:
            result = self.run_build()
        self.assertEqual(run.call_count, 3)
        files = packer.asset_payload(result, self.root)
        self.assertEqual(len(files), 4)
        self.assertNotIn("initfs_win32", files)
        self.assertFalse((result / "reskate-plugin.json").exists())
        lock = json.loads((result / "assets.lock.json").read_text())
        self.assertEqual(lock["tools"]["asset_author"], hashlib.sha256(b"author").hexdigest())
        self.assertEqual(list(self.output.iterdir()), [result])

    def test_wrong_game_never_starts_tools(self):
        (self.game / "Skate.exe").write_bytes(b"wrong game")
        with patch.object(builder.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "Skate build"):
                self.run_build()
        run.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_missing_tool_is_reported_before_building(self):
        self.compiler.unlink()
        with self.assertRaisesRegex(ValueError, "Build tool was not found"):
            self.run_build()
        self.assertFalse(self.output.exists())

    def test_failed_compile_keeps_previous_output(self):
        with patch.object(builder.subprocess, "run", side_effect=self.fake_tool):
            result = self.run_build()
        before = packer.asset_payload(result, self.root)
        def fail_compile(args, **kwargs):
            if args[0] == str(self.compiler):
                raise subprocess.CalledProcessError(1, args)
            self.fake_tool(args, **kwargs)
        with patch.object(builder.subprocess, "run", side_effect=fail_compile):
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_build()
        self.assertEqual(packer.asset_payload(result, self.root), before)

    def test_missing_authored_effect_is_refused_before_compile(self):
        def incomplete_author(args, **kwargs):
            self.fake_tool(args, **kwargs)
            source = Path(args[2]) / "resources.json"
            source.write_text('{"resources": []}')
        with patch.object(builder.subprocess, "run", side_effect=incomplete_author) as run:
            with self.assertRaisesRegex(ValueError, "authored Blood effect"):
                self.run_build()
        self.assertEqual(run.call_count, 1)
        self.assertFalse((self.output / "Patch").exists())


class NativeAuthorBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="blood-native-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "plugin"
        self.root.mkdir()
        self.sdk = Path(self.temp.name) / "generic-sdk"
        (self.sdk / "Engine/Vfs").mkdir(parents=True)
        (self.sdk / "Engine/Vfs/game_bundles.h").touch()
        (self.sdk / "CMakeLists.txt").touch()

    def libraries(self, directory):
        (directory / "Release").mkdir(parents=True, exist_ok=True)
        for name in builder.RESOURCE_LIBRARIES:
            (directory / f"Release/dingosdk_{name}.lib").write_bytes(b"generic library")

    def fake_cmake(self, args, **kwargs):
        self.assertEqual(args[0], "cmake")
        self.assertTrue(kwargs["check"])
        if "--target" not in args:
            return
        target = args[args.index("--target") + 1]
        directory = Path(args[args.index("--build") + 1])
        if target == "dingosdk_mods":
            self.libraries(directory)
        else:
            self.assertEqual(target, "blood_asset_author")
            (directory / "bin").mkdir(parents=True, exist_ok=True)
            (directory / "bin/blood_asset_author.exe").write_bytes(b"locally built author")

    def test_builds_local_recipes_with_only_general_external_libraries(self):
        with patch.object(builder.subprocess, "run", side_effect=self.fake_cmake) as run:
            executable = builder.build_author(self.sdk, root=self.root)
        calls = [call.args[0] for call in run.call_args_list]
        self.assertEqual(len(calls), 4)
        self.assertEqual(Path(calls[0][2]), self.root / "tools/asset_author/resource_libraries")
        self.assertEqual(Path(calls[2][2]), self.root / "tools/asset_author")
        self.assertIn(f"-DRESKATE_SOURCE_DIR={self.sdk}", calls[0])
        self.assertEqual(executable, self.root / "build/asset-author/bin/blood_asset_author.exe")
        self.assertFalse((self.sdk / "build").exists())
        self.assertFalse((self.sdk / "Extension/Blood").exists())

    def test_reuses_prebuilt_general_libraries_but_builds_author_locally(self):
        dependencies = Path(self.temp.name) / "prebuilt"
        self.libraries(dependencies)
        with patch.object(builder.subprocess, "run", side_effect=self.fake_cmake) as run:
            executable = builder.build_author(self.sdk, dependencies, self.root)
        self.assertEqual(run.call_count, 2)
        self.assertTrue(executable.is_relative_to(self.root))
        self.assertIn(f"-DRESKATE_LIBRARY_DIR={dependencies / 'Release'}", run.call_args_list[0].args[0])

    def test_missing_general_library_has_a_clear_error(self):
        dependencies = Path(self.temp.name) / "prebuilt"
        with patch.object(builder.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "Missing resource library"):
                builder.build_author(self.sdk, dependencies, self.root)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
