#!/usr/bin/env python3
"""Minimal pre-persistence ingestion pipeline demo.

This is the literal, runnable proof of the README's "demonstrate the
library in a minimal pre-persistence ingestion pipeline" success criterion.
It walks README.md's own architecture diagram end to end, using nothing but
this library's public API:

    Untrusted DICOM input
            |
            v
    fastDICOMstructure
      - structural parsing
      - tag inspection
      - transformation policy
      - private-tag screening
      - audit evidence
            |
    accepted / transformed
            |
            v
    Trusted persistence

This script is deliberately *not* a framework: no PACS, no queue, no audit
database, no HTTP endpoint -- those are the deployment concerns README.md's
"Explicitly out of scope" section names as belonging to an application built
*around* this library, not to the library itself. "Trusted persistence"
here is just a local output file, standing in for wherever a real deployment
would put it (a VNA, DICOMweb store, cloud bucket -- irrelevant to this
demo).

The "untrusted input" is a synthetic object matching README.md's own worked
example verbatim (built in Python, no external DICOM data needed), and the
policy applied is README.md's own, verbatim:

    preserve  (0008,0060) Modality
    remove    (0010,0010) PatientName
    hash      (0010,0020) PatientID
    preserve  (0018,0050) SliceThickness
    remove    private elements
    passthru  (7FE0,0010) PixelData

Run after building fastDICOMattrs (see this repository's README, "Getting started"):
    PYTHONPATH=python python3 python/examples/pipeline_demo.py
"""

from __future__ import annotations

import hashlib
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fastdicomstructure as fds


# ---------------------------------------------------------------------------
# "Untrusted DICOM input" -- synthesized to match README.md's worked example
# table exactly. A real 512MB Pixel Data element is stood in for by a small
# placeholder buffer here purely so this demo runs in milliseconds; nothing
# about how the library handles it depends on its size -- see docs/
# benchmarks.md for what happens to read/write time and memory as Pixel Data
# grows toward that real-world scale.
# ---------------------------------------------------------------------------

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
    # Long-form VRs (OB/OW/UN/SQ/... -- see include/fastdicomstructure/vr.hpp
    # is_long_form()) use tag + VR(2) + 2 reserved bytes + 4-byte length,
    # unlike every other VR's tag + VR(2) + 2-byte length. Pixel Data is
    # always OB or OW, so it always needs this form.
    if len(value) % 2 != 0:
        value += b"\x00"
    return _tag(group, element) + vr.encode("ascii") + b"\x00\x00" + _u32(len(value)) + value


def build_untrusted_input() -> bytes:
    ts_uid = b"1.2.840.10008.1.2.1"  # Explicit VR Little Endian, already even length
    group_body = (
        _element_short(0x0002, 0x0002, "UI", b"1.2.840.10008.5.1.4.1.1.7")  # SOP Class UID
        + _element_short(0x0002, 0x0003, "UI", b"1.2.3.4.5.6.7.8")           # SOP Instance UID
        + _element_short(0x0002, 0x0010, "UI", ts_uid)
    )
    file_meta = _element_short(0x0002, 0x0000, "UL", _u32(len(group_body))) + group_body

    dataset = (
        _element_short(0x0008, 0x0060, "CS", b"CT")           # Modality
        + _element_short(0x0010, 0x0010, "PN", b"DOE^JOHN")   # PatientName
        + _element_short(0x0010, 0x0020, "LO", b"12345678")   # PatientID
        + _element_short(0x0018, 0x0050, "DS", b"1.0")        # SliceThickness
        + _element_short(0x0019, 0x0010, "LO", b"Vendor-specific private data")  # Private Element
        + _element_long(0x7FE0, 0x0010, "OW", bytes(range(256)) * 4)  # Pixel Data (placeholder)
    )
    return b"\x00" * 128 + b"DICM" + file_meta + dataset


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def structural_parse_and_inspect(data: bytes) -> fds.Structure:
    """"structural parsing" + "tag inspection" boxes of the diagram."""
    structure = fds.read_buffer(data, fidelity="lossless")
    for diagnostic in structure.diagnostics:
        print(f"  [{diagnostic.severity}] {diagnostic.message}")
    blocking = [d for d in structure.diagnostics if d.severity != "info"]
    if blocking:
        structure.close()
        raise RuntimeError("input rejected: structural parsing produced diagnostics")
    print(f"  parsed {len(structure)} top-level elements "
          f"({structure.transfer_syntax_uid}, "
          f"pixel data: {structure.pixel_data_kind or 'none'})")
    for element in structure:
        marker = " (private)" if element.tag[0] & 1 else ""
        print(f"    {element!r}{marker}")
    return structure


def apply_transformation_policy(structure: fds.Structure) -> dict:
    """"transformation policy" + "private-tag screening" boxes of the
    diagram. Returns an audit record of exactly what changed -- the
    "audit evidence" box.
    """
    audit: dict = {"preserved": [], "removed": [], "hashed": [], "private_removed": 0}

    # preserve (0008,0060) Modality, (0018,0050) SliceThickness -- no code
    # needed: not touching an element already preserves it.
    audit["preserved"].append((0x0008, 0x0060))
    audit["preserved"].append((0x0018, 0x0050))

    # remove (0010,0010) PatientName
    if structure.erase((0x0010, 0x0010)):
        audit["removed"].append((0x0010, 0x0010))

    # hash (0010,0020) PatientID
    patient_id = structure.get((0x0010, 0x0020))
    if patient_id is not None:
        digest = hashlib.sha256(patient_id.value).hexdigest().encode("ascii")
        structure.set_value((0x0010, 0x0020), digest)
        audit["hashed"].append(((0x0010, 0x0020), digest.decode("ascii")))

    # remove private elements
    audit["private_removed"] = structure.erase_private()

    # passthru (7FE0,0010) Pixel Data -- no code needed: the mutation API
    # has no way to reach Pixel Data at all, by design (see
    # docs/architecture.md section 8). It is never decoded, copied, or even
    # touched by this pipeline.
    audit["preserved"].append((0x7FE0, 0x0010))

    return audit


def persist(structure: fds.Structure, path: Path) -> fds.WriteStats:
    """"accepted / transformed" -> "Trusted persistence" boxes of the
    diagram. A real deployment would write to a VNA/DICOMweb/cloud store
    here instead of a local file -- irrelevant to this library, see the
    module docstring.
    """
    return structure.write_with_stats(str(path))


def verify_round_trip(path: Path) -> None:
    """Reparse the bytes just written and check the demonstrated policy.

    This is a round-trip check through the same library, not independent
    DICOM conformance validation.
    """
    reparsed = fds.read(str(path), fidelity="lossless")
    try:
        assert (0x0010, 0x0010) not in reparsed, "PatientName should have been removed"
        assert (0x0019, 0x0010) not in reparsed, "the private element should have been removed"
        assert reparsed.get((0x0008, 0x0060)).value == b"CT", "Modality should be preserved"
        tags = [element.tag for element in reparsed]
        assert tags == sorted(tags), "tag order should still be ascending"
    finally:
        reparsed.close()


def main() -> int:
    print("== Untrusted DICOM input ==")
    data = build_untrusted_input()
    print(f"  {len(data)} bytes\n")

    print("== fastDICOMstructure: structural parsing / tag inspection ==")
    structure = structural_parse_and_inspect(data)
    print()

    print("== fastDICOMstructure: transformation policy / private-tag screening ==")
    audit = apply_transformation_policy(structure)
    print()

    print("== accepted / transformed -> Trusted persistence ==")
    with tempfile.TemporaryDirectory() as directory:
        out_path = Path(directory, "trusted_store", "accepted.dcm")
        out_path.parent.mkdir()
        stats = persist(structure, out_path)
        print(f"  wrote {stats.bytes_written} bytes to {out_path}")
        print(f"  {stats.source_backed_value_bytes} bytes preserved verbatim from the original "
              f"source, {stats.regenerated_value_bytes} bytes regenerated "
              f"({stats.preserved_fraction:.1%} preserved)\n")

        print("== audit evidence ==")
        print(f"  preserved: {audit['preserved']}")
        print(f"  removed:   {audit['removed']}")
        for tag, digest in audit["hashed"]:
            print(f"  hashed:    {tag} -> {digest}")
        print(f"  private elements removed: {audit['private_removed']}\n")

        print("== round-trip verification (re-parsing the file just written) ==")
        verify_round_trip(out_path)
        print("  OK: PatientName and private elements are gone, Modality is preserved, "
              "tag order is ascending\n")

    structure.close()
    print("Pipeline complete: the original untrusted object never became part of the "
          "persistent imaging environment (README.md \"Longer-term application\").")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
