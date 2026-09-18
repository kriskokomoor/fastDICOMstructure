"""Direct qualification of Structure Locator Model v1 (`policy.resolve_locator`,
`policy.TagLocator`, `policy.PathLocator`, `policy.LocatorStep`), independent of
the policy operations built on top of it.

Byte-fixture-building style mirrors tests/python/test_policy.py (duplicated
locally rather than shared, following that file's own stated convention).

Test-to-requirement mapping (see docs/architecture/S1_1_LOCATOR_MODEL_REPORT.md
"Tests" section, which cites this file by test name): each `test_*` method in
`LocatorEngineTest` corresponds 1:1 to one of the 20 numbered scenarios in the
S1.1 authorization's "TEST REQUIREMENTS -- LOCATOR ENGINE" section.
"""

import struct
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

# test_policy.py's bare `import fastdicomstructure` only works when pytest
# has already imported test_pipeline_demo.py first (whose own import of
# pipeline_demo.py has the side effect of putting python/ on sys.path) --
# alphabetically, "test_locator.py" collects before "test_pipeline_demo.py",
# so this file cannot rely on that incidental ordering and inserts the path
# itself, mirroring test_pipeline_demo.py's own bootstrap.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

import fastdicomstructure as fds  # noqa: E402
from fastdicomstructure import policy  # noqa: E402

import fastdicomattrs  # noqa: E402


def _u16(v):
    return struct.pack("<H", v)


def _u32(v):
    return struct.pack("<I", v)


def _tag(group, element):
    return _u16(group) + _u16(element)


def _element_short(group, element, vr, value: bytes) -> bytes:
    """Explicit VR LE, short (2-byte length) VR form -- CS/LO/PN/DA/UI/UL/IS/DS/etc."""
    if len(value) % 2 != 0:
        value += b"\x00"
    return _tag(group, element) + vr.encode("ascii") + _u16(len(value)) + value


def _element_long(group, element, vr, value: bytes) -> bytes:
    """Explicit VR LE, long (2-reserved-bytes + 4-byte length) VR form -- OB/OW/etc."""
    if len(value) % 2 != 0:
        value += b"\x00"
    return _tag(group, element) + vr.encode("ascii") + b"\x00\x00" + _u32(len(value)) + value


def _element_sq(group, element, item_bytes: bytes) -> bytes:
    return _tag(group, element) + b"SQ" + b"\x00\x00" + _u32(len(item_bytes)) + item_bytes


def _dicom_item(content: bytes) -> bytes:
    return _tag(0xFFFE, 0xE000) + _u32(len(content)) + content


_TAG_MODALITY = (0x0008, 0x0060)
_TAG_PRIVATE = (0x0009, 0x0010)
_TAG_PATIENT_NAME = (0x0010, 0x0010)
_TAG_PIXEL_DATA = (0x7FE0, 0x0010)
_TAG_EMPTY_SEQ = (0x0010, 0x1002)  # zero Items, on purpose
_TAG_BEAM_SEQ = (0x300A, 0x00B0)
_TAG_BEAM_NUMBER = (0x300A, 0x00C0)
_TAG_CONTROL_POINT_SEQ = (0x300A, 0x0111)
_TAG_CUMULATIVE_METERSET_WEIGHT = (0x300A, 0x0114)
_TAG_UNKNOWN = (0x0099, 0x0099)  # never present anywhere in the fixture
_TAG_ABSENT_EVERYWHERE_LEAF = (0x300A, 0x00C6)  # never present under any Control Point


def _control_point_item(weight: bytes) -> bytes:
    return _dicom_item(_element_short(*_TAG_CUMULATIVE_METERSET_WEIGHT, "DS", weight))


def _beam_item(number: bytes, control_points: bytes) -> bytes:
    content = b""
    if number is not None:
        content += _element_short(*_TAG_BEAM_NUMBER, "IS", number)
    content += _element_sq(*_TAG_CONTROL_POINT_SEQ, control_points)
    return _dicom_item(content)


def _build_fixture() -> bytes:
    """One Explicit VR LE Part10 file exercising every Locator V1 shape this
    module needs: a root leaf, a private tag, Pixel Data, a zero-Item
    Sequence, and a two-level BeamSequence/ControlPointSequence structure
    with 3 sibling Beam Items --

    - Item 0: BeamNumber="1", two Control Points (weights "0.0", "0.5") --
      the extra Control Point makes multi-level wildcard expansion produce
      a non-uniform, order-checkable result.
    - Item 1: BeamNumber ABSENT (on purpose -- "target absent from one
      matched Item"), one Control Point (weight "1.0").
    - Item 2: BeamNumber="3", one Control Point (weight "2.0").
    """
    ts_uid = b"1.2.840.10008.1.2.1"  # Explicit VR Little Endian, already even length
    group_body = (
        _element_short(0x0002, 0x0002, "UI", b"1.2.3.4")
        + _element_short(0x0002, 0x0003, "UI", b"1.2.3.4.5")
        + _element_short(0x0002, 0x0010, "UI", ts_uid)
    )
    file_meta = _element_short(0x0002, 0x0000, "UL", _u32(len(group_body))) + group_body

    beam_items = (
        _beam_item(b"1", _control_point_item(b"0.0") + _control_point_item(b"0.5"))
        + _beam_item(None, _control_point_item(b"1.0"))
        + _beam_item(b"3", _control_point_item(b"2.0"))
    )

    # Ascending tag order at the top level, like a conformant real-world
    # file -- Pixel Data (7FE0,0010) last, per standard convention.
    dataset = (
        _element_short(*_TAG_MODALITY, "CS", b"CT")
        + _element_short(*_TAG_PRIVATE, "LO", b"PRIVATE")
        + _element_short(*_TAG_PATIENT_NAME, "PN", b"Doe^Jane")
        + _element_sq(*_TAG_EMPTY_SEQ, b"")  # zero Items
        + _element_sq(*_TAG_BEAM_SEQ, beam_items)
        + _element_long(*_TAG_PIXEL_DATA, "OB", b"\x01\x02\x03\x04")
    )
    return b"\x00" * 128 + b"DICM" + file_meta + dataset


class LocatorEngineTest(unittest.TestCase):
    def setUp(self):
        self.structure = fds.read_buffer(_build_fixture(), fidelity="lossless")

    def tearDown(self):
        self.structure.close()

    # 1. root tag
    def test_root_tag(self):
        matches = policy.resolve_locator(self.structure, policy.TagLocator(_TAG_MODALITY, recursive=False))
        self.assertEqual(matches, [[(_TAG_MODALITY, None)]])

    # 2. concrete one-level nested
    def test_concrete_one_level_nested(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 0),), tag=_TAG_BEAM_NUMBER)
        matches = policy.resolve_locator(self.structure, locator)
        self.assertEqual(matches, [[(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_NUMBER, None)]])
        self.assertEqual(self.structure.find(matches[0]).value, b"1\x00")

    # 3. concrete multi-level nested
    def test_concrete_multi_level_nested(self):
        locator = policy.PathLocator(
            steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 0), policy.LocatorStep(_TAG_CONTROL_POINT_SEQ, 1)),
            tag=_TAG_CUMULATIVE_METERSET_WEIGHT,
        )
        matches = policy.resolve_locator(self.structure, locator)
        self.assertEqual(len(matches), 1)
        self.assertEqual(self.structure.find(matches[0]).value, b"0.5\x00")

    # 4. wildcard one level
    def test_wildcard_one_level(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NUMBER)
        matches = policy.resolve_locator(self.structure, locator)
        # Item 1 has no BeamNumber -- 2 matches (Items 0 and 2), not 3.
        self.assertEqual(len(matches), 2)
        values = [self.structure.find(m).value for m in matches]
        self.assertEqual(values, [b"1\x00", b"3\x00"])

    # 5. wildcard multiple levels
    def test_wildcard_multiple_levels(self):
        locator = policy.PathLocator(
            steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"), policy.LocatorStep(_TAG_CONTROL_POINT_SEQ, "*")),
            tag=_TAG_CUMULATIVE_METERSET_WEIGHT,
        )
        matches = policy.resolve_locator(self.structure, locator)
        values = [self.structure.find(m).value for m in matches]
        self.assertEqual(values, [b"0.0\x00", b"0.5\x00", b"1.0\x00", b"2.0\x00"])

    # 6. exact then wildcard
    def test_exact_then_wildcard(self):
        locator = policy.PathLocator(
            steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 0), policy.LocatorStep(_TAG_CONTROL_POINT_SEQ, "*")),
            tag=_TAG_CUMULATIVE_METERSET_WEIGHT,
        )
        matches = policy.resolve_locator(self.structure, locator)
        values = [self.structure.find(m).value for m in matches]
        self.assertEqual(values, [b"0.0\x00", b"0.5\x00"])

    # 7. wildcard then exact
    def test_wildcard_then_exact(self):
        locator = policy.PathLocator(
            steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"), policy.LocatorStep(_TAG_CONTROL_POINT_SEQ, 0)),
            tag=_TAG_CUMULATIVE_METERSET_WEIGHT,
        )
        matches = policy.resolve_locator(self.structure, locator)
        values = [self.structure.find(m).value for m in matches]
        self.assertEqual(values, [b"0.0\x00", b"1.0\x00", b"2.0\x00"])

    # 8. multiple sibling Items matched independently
    def test_multiple_sibling_items_matched_independently(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NUMBER)
        matches = policy.resolve_locator(self.structure, locator)
        # Distinct concrete paths (different Item index), not aliases of one element.
        self.assertNotEqual(matches[0], matches[1])
        self.assertEqual(matches[0][0], (_TAG_BEAM_SEQ, 0))
        self.assertEqual(matches[1][0], (_TAG_BEAM_SEQ, 2))

    # 9. empty Sequence
    def test_empty_sequence(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_EMPTY_SEQ, "*"),), tag=_TAG_PATIENT_NAME)
        matches = policy.resolve_locator(self.structure, locator)
        self.assertEqual(matches, [])

    # 10. missing Sequence
    def test_missing_sequence(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_UNKNOWN, "*"),), tag=_TAG_MODALITY)
        matches = policy.resolve_locator(self.structure, locator)
        self.assertEqual(matches, [])

    # 11. Sequence exists but Item index does not
    def test_invalid_item_index(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 5),), tag=_TAG_BEAM_NUMBER)
        matches = policy.resolve_locator(self.structure, locator)
        self.assertEqual(matches, [])

    # 12. intermediate element exists but is not SQ
    def test_intermediate_non_sq_element(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_MODALITY, 0),), tag=_TAG_PATIENT_NAME)
        matches = policy.resolve_locator(self.structure, locator)
        self.assertEqual(matches, [])

    # 13. target element absent from one matched Item
    def test_target_absent_from_one_matched_item(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NUMBER)
        matches = policy.resolve_locator(self.structure, locator)
        matched_items = {path[0][1] for path in matches}
        self.assertEqual(matched_items, {0, 2})  # Item 1 excluded, not errored

    # 14. target element absent in all matching Items
    def test_target_absent_everywhere(self):
        locator = policy.PathLocator(
            steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_ABSENT_EVERYWHERE_LEAF
        )
        matches = policy.resolve_locator(self.structure, locator)
        self.assertEqual(matches, [])

    # 15. private target element
    def test_private_target_element(self):
        locator = policy.TagLocator(_TAG_PRIVATE, recursive=False)
        matches = policy.resolve_locator(self.structure, locator)
        self.assertEqual(len(matches), 1)

    # 16. unknown target tag
    def test_unknown_target_tag(self):
        locator = policy.TagLocator(_TAG_UNKNOWN, recursive=True)
        matches = policy.resolve_locator(self.structure, locator)
        self.assertEqual(matches, [])

    # 17. Pixel Data target -- discovery only, no materialization
    def test_pixel_data_target_never_resolves_and_never_materializes(self):
        """Pixel Data (7FE0,0010) is not part of attrs' ordinary element
        graph at all -- fastDICOMattrs' DicomStructure holds it in a
        dedicated pixel_data_ member never surfaced through
        element_count/element_at/find (confirmed: absent from both
        Structure.get and Structure.iter_elements(recursive=True) even
        though Structure.pixel_data_kind reports it present). A locator
        naming it therefore always resolves to zero matches -- a stronger
        structural guarantee of "no materialization" than merely avoiding
        `.value`: Pixel Data is outside the reachable graph resolve_locator
        walks, so no locator can ever match it, let alone read its value.
        The `mock.patch` below still asserts `.value` is never touched, as
        a second, independent check. Recorded as an S1.1 finding in the
        report ("Defects/limitations discovered"), not a Locator V1 defect:
        it follows from attrs' own frozen object model, unrelated to this
        module's engine.
        """
        self.assertEqual(self.structure.pixel_data_kind, "native")
        locator = policy.TagLocator(_TAG_PIXEL_DATA, recursive=False)
        with mock.patch.object(
            fastdicomattrs.Element, "value",
            new_callable=mock.PropertyMock,
            side_effect=AssertionError("resolve_locator must not read .value"),
        ):
            matches = policy.resolve_locator(self.structure, locator)
        self.assertEqual(matches, [])

    # 18. deterministic ordering (same live Structure, resolved twice)
    def test_deterministic_ordering(self):
        locator = policy.PathLocator(
            steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"), policy.LocatorStep(_TAG_CONTROL_POINT_SEQ, "*")),
            tag=_TAG_CUMULATIVE_METERSET_WEIGHT,
        )
        first = policy.resolve_locator(self.structure, locator)
        second = policy.resolve_locator(self.structure, locator)
        self.assertEqual(first, second)

    # 19. repeated resolution identical (independently parsed copies)
    def test_repeated_resolution_identical_across_independent_parses(self):
        data = _build_fixture()
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NUMBER)
        a = fds.read_buffer(data, fidelity="lossless")
        b = fds.read_buffer(data, fidelity="lossless")
        try:
            self.assertEqual(policy.resolve_locator(a, locator), policy.resolve_locator(b, locator))
        finally:
            a.close()
            b.close()

    # 20. malformed locator rejected
    def test_malformed_locator_rejected(self):
        with self.assertRaises(policy.MalformedLocatorError):
            policy.TagLocator((0x0010,))  # wrong arity
        with self.assertRaises(policy.MalformedLocatorError):
            policy.TagLocator((0x0010, "0010"))  # non-int component
        with self.assertRaises(policy.MalformedLocatorError):
            policy.LocatorStep(_TAG_BEAM_SEQ, -1)  # negative index
        with self.assertRaises(policy.MalformedLocatorError):
            policy.LocatorStep(_TAG_BEAM_SEQ, "all")  # not "*" and not an int
        with self.assertRaises(policy.MalformedLocatorError):
            policy.LocatorStep(_TAG_BEAM_SEQ, True)  # bool is not a valid index, even though it's an int subclass
        with self.assertRaises(policy.MalformedLocatorError):
            policy.PathLocator(steps=(), tag=(1, 2, 3))  # wrong leaf-tag arity

    # -- additional invariants ------------------------------------------------

    def test_locator_equality_and_hash(self):
        a = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NUMBER)
        b = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NUMBER)
        c = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 0),), tag=_TAG_BEAM_NUMBER)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertNotEqual(a, c)

    def test_path_locator_accepts_plain_tuples_for_steps(self):
        locator = policy.PathLocator(steps=((_TAG_BEAM_SEQ, 0),), tag=_TAG_BEAM_NUMBER)
        self.assertEqual(locator.steps, (policy.LocatorStep(_TAG_BEAM_SEQ, 0),))

    def test_root_pathlocator_equivalent_to_root_scope_tag_locator(self):
        path_form = policy.PathLocator(steps=(), tag=_TAG_MODALITY)
        tag_form = policy.TagLocator(_TAG_MODALITY, recursive=False)
        self.assertEqual(
            policy.resolve_locator(self.structure, path_form),
            policy.resolve_locator(self.structure, tag_form),
        )

    def test_is_pattern_reflects_wildcard_presence(self):
        concrete = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 0),), tag=_TAG_BEAM_NUMBER)
        pattern = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NUMBER)
        self.assertFalse(concrete.is_pattern)
        self.assertTrue(pattern.is_pattern)


class LocatorPerformanceTest(unittest.TestCase):
    """Detects obviously pathological behavior only -- no micro-benchmarking,
    no optimization. See docs/architecture/S1_1_LOCATOR_MODEL_REPORT.md
    "Performance" for the measured numbers this recorded.
    """

    @classmethod
    def setUpClass(cls):
        item_count = 2000
        items = b"".join(
            _dicom_item(_element_short(*_TAG_BEAM_NUMBER, "IS", str(i).encode("ascii")))
            for i in range(item_count)
        )
        ts_uid = b"1.2.840.10008.1.2.1"
        group_body = (
            _element_short(0x0002, 0x0002, "UI", b"1.2.3.4")
            + _element_short(0x0002, 0x0003, "UI", b"1.2.3.4.5")
            + _element_short(0x0002, 0x0010, "UI", ts_uid)
        )
        file_meta = _element_short(0x0002, 0x0000, "UL", _u32(len(group_body))) + group_body
        dataset = (
            _element_short(*_TAG_MODALITY, "CS", b"CT")
            + _element_sq(*_TAG_BEAM_SEQ, items)
        )
        cls._item_count = item_count
        cls._data = b"\x00" * 128 + b"DICM" + file_meta + dataset

    def setUp(self):
        self.structure = fds.read_buffer(self._data, fidelity="lossless")

    def tearDown(self):
        self.structure.close()

    def _time(self, locator) -> float:
        start = time.perf_counter()
        matches = policy.resolve_locator(self.structure, locator)
        elapsed = time.perf_counter() - start
        return elapsed, matches

    def test_root_tag_resolution_is_fast(self):
        elapsed, matches = self._time(policy.TagLocator(_TAG_MODALITY, recursive=False))
        self.assertEqual(len(matches), 1)
        self.assertLess(elapsed, 1.0)

    def test_deep_concrete_locator_resolution_is_fast(self):
        locator = policy.PathLocator(
            steps=(policy.LocatorStep(_TAG_BEAM_SEQ, self._item_count - 1),), tag=_TAG_BEAM_NUMBER
        )
        elapsed, matches = self._time(locator)
        self.assertEqual(len(matches), 1)
        self.assertLess(elapsed, 1.0)

    def test_large_wildcard_resolution_scales_linearly_enough(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NUMBER)
        elapsed, matches = self._time(locator)
        self.assertEqual(len(matches), self._item_count)
        # Generous bound: a quadratic-in-item-count regression on 2000 items
        # would be far slower than this; a linear traversal is not.
        self.assertLess(elapsed, 5.0)


if __name__ == "__main__":
    unittest.main()
