#!/usr/bin/env python3
"""Minimal declarative-JSON-policy example, run through the real CLI.

This is deliberately small and synthetic-only. It is NOT a de-identification
product, NOT a complete example of every declarative operation this project
supports, and NOT a demonstration of any deployment surface (filesystem,
container, network) beyond a single local file in, single local file out.

What it shows, end to end:

    1. A synthetic, in-code-built DICOM object (no external/real patient
       data anywhere -- see build_synthetic_input() below).
    2. A small, portable Configuration V1 JSON policy document
       (example_policy.json, next to this script) that a reader can open
       and read on its own, independent of this script.
    3. Running that policy through the actual public CLI entry point
       (`python -m fastdicomstructure run --config ... --json`), the same
       way an external user would, against a local source/destination file
       pair this script adds to the policy document at run time (the
       policy document itself carries no paths, so it stays portable).
    4. The CLI's own structured JSON result, printed unmodified.
    5. An independent read-back of the output file using this project's
       own library (not a de-identification claim -- just confirming the
       four declarative operations above actually took effect).

Run after installing fastDICOMattrs and fastDICOMstructure per this
repository's README ("Getting started: an external clean install"):

    PYTHONPATH=python FASTDICOMATTRS_REPO=/path/to/fastDICOMattrs \
        python3 python/examples/run_json_policy_example.py
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fastdicomstructure as fds  # noqa: E402  (path insert must come first)

_EXAMPLE_DIR = Path(__file__).resolve().parent
_POLICY_PATH = _EXAMPLE_DIR / "example_policy.json"


def _u16(value: int) -> bytes:
    return struct.pack("<H", value)


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _tag(group: int, element: int) -> bytes:
    return _u16(group) + _u16(element)


def _element_short(group: int, element: int, vr: str, value: bytes) -> bytes:
    if len(value) % 2 != 0:
        value += b"\x00"
    return _tag(group, element) + vr.encode("ascii") + _u16(len(value)) + value


def _element_long(group: int, element: int, vr: str, value: bytes) -> bytes:
    if len(value) % 2 != 0:
        value += b"\x00"
    return _tag(group, element) + vr.encode("ascii") + b"\x00\x00" + _u32(len(value)) + value


def build_synthetic_input() -> bytes:
    """A small, entirely synthetic Explicit VR Little Endian object.

    Every value here is made up for this example. Nothing is read from,
    or derived from, any real DICOM file or real patient.
    """
    ts_uid = b"1.2.840.10008.1.2.1"  # Explicit VR Little Endian
    group_body = (
        _element_short(0x0002, 0x0002, "UI", b"1.2.840.10008.5.1.4.1.1.7")
        + _element_short(0x0002, 0x0003, "UI", b"1.2.3.4.5.6.7.8")
        + _element_short(0x0002, 0x0010, "UI", ts_uid)
    )
    file_meta = _element_short(0x0002, 0x0000, "UL", _u32(len(group_body))) + group_body

    dataset = (
        _element_short(0x0008, 0x0060, "CS", b"CT")            # Modality
        + _element_short(0x0009, 0x0010, "LO", b"EXAMPLE1.0")  # private creator
        + _element_short(0x0009, 0x1001, "LO", b"vendor-specific value")  # private data
        + _element_short(0x0010, 0x0010, "PN", b"DOE^JANE")    # PatientName
        + _element_short(0x0010, 0x0020, "LO", b"87654321")    # PatientID
        + _element_long(0x7FE0, 0x0010, "OW", bytes(range(256)) * 4)  # Pixel Data (placeholder)
    )
    return b"\x00" * 128 + b"DICM" + file_meta + dataset


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        input_path = tmp_path / "incoming.dcm"
        output_path = tmp_path / "processed.dcm"
        config_path = tmp_path / "config.json"

        input_path.write_bytes(build_synthetic_input())

        policy_document = json.loads(_POLICY_PATH.read_text())
        policy_document["source"] = {"type": "filesystem", "options": {"path": str(input_path)}}
        policy_document["destination"] = {
            "type": "filesystem",
            "options": {"path": str(output_path), "overwrite": True},
        }
        config_path.write_text(json.dumps(policy_document, indent=2))

        print(f"== Declarative policy (from {_POLICY_PATH.name}) ==")
        print(_POLICY_PATH.read_text())

        print("== Running: python -m fastdicomstructure run --config ... --json ==")
        completed = subprocess.run(
            [sys.executable, "-m", "fastdicomstructure", "run", "--config", str(config_path), "--json"],
            cwd=_EXAMPLE_DIR.parents[1],
            capture_output=True,
            text=True,
        )
        print(completed.stdout)
        if completed.returncode != 0:
            print(f"(CLI exited with status {completed.returncode}; see stderr below)", file=sys.stderr)
            print(completed.stderr, file=sys.stderr)
            return completed.returncode

        print("== Independent read-back of the output file (this project's own library) ==")
        result = json.loads(completed.stdout)
        if result.get("status") != "succeeded":
            print(f"policy did not succeed (status={result.get('status')}); nothing to read back")
            return 1

        structure = fds.read(str(output_path), fidelity="lossless")
        try:
            assert structure.decode_text([((0x0010, 0x0010), None)]) == ["ANONYMIZED"], \
                "PatientName should have been replaced"
            assert (0x0009, 0x1001) not in structure, "the private element should have been removed"
            assert (0x0009, 0x0010) not in structure, "the private creator should have been removed"
            assert structure.get((0x0008, 0x0060)).value == b"CT", \
                "Modality should be preserved (not targeted by this policy)"
            print("  OK: PatientName replaced, private group removed, Modality preserved.")
        finally:
            structure.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
