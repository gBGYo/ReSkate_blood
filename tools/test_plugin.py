"""Run Blood's Lua tests with a standalone Luau interpreter (no SDK required)."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]


def runner():
    # ReSkate resolves bare module names relative to plugin/. Bundle the unchanged
    # sources in closures to supply that resolution in the standalone interpreter.
    parts = ["local reskate\nlocal factories = {}\nlocal declared_effects = {}\n"]
    plugin = json.loads((REPO / "reskate-plugin.json").read_text(encoding="utf-8"))
    for asset in plugin["effects"]:
        parts.append(f"declared_effects[{json.dumps(asset)}] = true\n")
    for path in sorted((REPO / "plugin").glob("*.lua")):
        parts.append(f"factories[{json.dumps(path.stem)}] = function(require)\n")
        parts.append(path.read_text(encoding="utf-8"))
        parts.append("\nend\n")
    parts.append("""
local function load_plugin()
    local cache = {}
    local require
    require = function(name)
        assert(factories[name], "Missing plugin module: " .. name)
        if cache[name] == nil then cache[name] = factories[name](require) end
        return cache[name]
    end
    require("main")
end
""")
    parts.append((REPO / "tests/lifecycle.lua").read_text(encoding="utf-8"))
    return "".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--luau", default="luau", help="Path to the standalone Luau interpreter")
    args = parser.parse_args()
    executable = shutil.which(args.luau)
    if not executable:
        parser.error("Luau was not found; pass --luau C:/path/to/luau.exe")
    with tempfile.TemporaryDirectory(prefix="blood-luau-") as directory:
        script = Path(directory) / "blood-tests.luau"
        script.write_text(runner(), encoding="utf-8")
        subprocess.run([executable, str(script)], check=True, timeout=60)


if __name__ == "__main__":
    main()
