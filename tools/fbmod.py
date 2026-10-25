"""Encode Blood asset-author output as a Studio FBMOD (ported from feature/blood)."""

import hashlib
import json
from pathlib import Path
import struct


def pack(fmt, *values):
    return struct.pack("<" + fmt, *values)


def terminated(value):
    return value.encode("utf-8") + b"\0"


def bundle_hash(name):
    value = 5381
    for byte in name.lower().encode("utf-8"):
        value = ((value * 33) ^ byte) & 0xffffffff
    return value


def package(authored, output, version):
    authored, output = Path(authored), Path(output)
    source = json.loads((authored / "resources.json").read_text(encoding="utf-8"))
    rows = [pack("Bi", 0, -1) + terminated(name) + pack("I", 0)
            for name in ["Icon", "Screenshot0", "Screenshot1", "Screenshot2", "Screenshot3"]]
    payloads = []
    names = set()
    for asset in source["resources"]:
        identity = (asset["kind"], asset["name"])
        if identity in names:
            raise ValueError(f"Duplicate blood dependency: {identity}")
        names.add(identity)
        path = (authored / asset["file"]).resolve()
        if not path.is_relative_to(authored.resolve()):
            raise ValueError(f"Asset payload is outside the authored directory: {asset['file']}")
        payload = path.read_bytes()
        row = (pack("Bi", asset["kind"], len(payloads)) + terminated(asset["name"])
               + hashlib.sha1(payload).digest() + pack("qBi", asset["size"], 8 if asset["added"] else 0, 0)
               + terminated("") + pack("II", 1, bundle_hash(asset["target"])))
        if asset["kind"] == 2:
            meta = bytes.fromhex(asset["meta"])
            row += pack("IQI", asset["type"], asset["rid"], len(meta)) + meta
        elif asset["kind"] == 3:
            row += pack("IIIIiiI", 0, 0, asset["logical_offset"], asset["logical_size"], 0, -1, 0)
        elif asset["kind"] != 1:
            raise ValueError(f"Unknown asset kind: {asset['kind']}")
        rows.append(row)
        payloads.append(payload)
    profile = b"Skate"
    header = pack("QIQiB", 0x01005954534f5246, 6, 0, len(payloads), len(profile)) + profile + pack("I", 0)
    details = b"".join(terminated(s) for s in ["gBGYo Blood", "gBGYo", "Gameplay", version,
                       "Dynamic impact spray, droplets, wound streams, and ground blood smears.", ""])
    body = header + details + pack("I", len(rows)) + b"".join(rows)
    body = body[:12] + pack("Q", len(body)) + body[20:]
    offset = 0
    manifest = b""
    for payload in payloads:
        manifest += pack("QQ", offset, len(payload))
        offset += len(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(body + manifest + b"".join(payloads))
    print(f"Packaged {len(payloads)} Blood payloads", flush=True)
