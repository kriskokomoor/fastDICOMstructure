"""Tests for fastdicomstructure.policy.

Byte-fixture-building style mirrors tests/python/test_mutation.py
(duplicated locally rather than shared, following that file's own stated
convention -- see its module docstring).

test_apply_reproduces_gateway_demo_policy is the key evidence test for this
phase: it applies the new declarative Policy abstraction and, independently,
the exact imperative call sequence fastDICOMgateway's transform.py
_apply_demo_policy() makes (erase_recursive / set_value_recursive /
erase_private, in the same order, against the same tags and replacement
value), to two separately-parsed copies of the same input, and asserts the
serialized output is byte-identical. This does not import or modify
fastDICOMgateway -- the imperative sequence is reproduced here from
transform.py's already-published source (read, not linked against) as an
independent reference computation.
"""

import struct
import unittest

import fastdicomstructure as fds
from fastdicomstructure import policy


def _u16(v):
    return struct.pack("<H", v)


def _u32(v):
    return struct.pack("<I", v)


def _tag(group, element):
    return _u16(group) + _u16(element)


def _element_short(group, element, vr, value: bytes) -> bytes:
    if len(value) % 2 != 0:
        value += b"\x00"
    return _tag(group, element) + vr.encode("ascii") + _u16(len(value)) + value


def _element_sq(group, element, item_bytes: bytes) -> bytes:
    return _tag(group, element) + b"SQ" + b"\x00\x00" + _u32(len(item_bytes)) + item_bytes


def _dicom_item(content: bytes) -> bytes:
    return _tag(0xFFFE, 0xE000) + _u32(len(content)) + content


_TAG_MODALITY = (0x0008, 0x0060)
_TAG_PRIVATE = (0x0009, 0x0010)
_TAG_PATIENT_NAME = (0x0010, 0x0010)
_TAG_PATIENT_ID = (0x0010, 0x0020)
_TAG_PATIENT_BIRTH_DATE = (0x0010, 0x0030)
_TAG_OTHER_PATIENT_IDS_SEQ = (0x0010, 0x1002)
_TAG_NESTED_PRIVATE = (0x0009, 0x0011)
_TAG_ABSENT = (0x0099, 0x0099)

_FILE_META_TAGS = {(0x0002, 0x0000), (0x0002, 0x0002), (0x0002, 0x0003), (0x0002, 0x0010)}


def _build_dataset() -> bytes:
    ts_uid = b"1.2.840.10008.1.2.1"  # Explicit VR Little Endian, already even length
    group_body = (
        _element_short(0x0002, 0x0002, "UI", b"1.2.3.4")
        + _element_short(0x0002, 0x0003, "UI", b"1.2.3.4.5")
        + _element_short(0x0002, 0x0010, "UI", ts_uid)
    )
    file_meta = _element_short(0x0002, 0x0000, "UL", _u32(len(group_body))) + group_body

    # Ascending tag order at the top level, like a conformant real-world file.
    dataset = (
        _element_short(*_TAG_MODALITY, "CS", b"CT")
        + _element_short(*_TAG_PRIVATE, "LO", b"PRIVATE")
        + _element_short(*_TAG_PATIENT_NAME, "PN", b"Doe^Jane")
        + _element_short(*_TAG_PATIENT_ID, "LO", b"ID1")
        + _element_short(*_TAG_PATIENT_BIRTH_DATE, "DA", b"20200101")
    )
    return b"\x00" * 128 + b"DICM" + file_meta + dataset


def _build_dataset_with_nested_occurrences() -> bytes:
    """_build_dataset() plus a standard-shaped Other Patient IDs Sequence
    (0010,1002) item carrying a second, nested PatientID (0010,0020) and a
    nested private element (0009,0011) -- occurrences that top-level-only
    operations (erase/set_value) cannot reach, but the recursive ones can.
    """
    base = _build_dataset()
    item_content = (
        _element_short(*_TAG_NESTED_PRIVATE, "LO", b"NESTED-PRIVATE")
        + _element_short(*_TAG_PATIENT_ID, "LO", b"NESTED-ID")
    )
    other_patient_ids_seq = _element_sq(*_TAG_OTHER_PATIENT_IDS_SEQ, _dicom_item(item_content))
    return base + other_patient_ids_seq


def _element_long(group, element, vr, value: bytes) -> bytes:
    """Explicit VR LE, long (2-reserved-bytes + 4-byte length) VR form -- OB/OW/etc."""
    if len(value) % 2 != 0:
        value += b"\x00"
    return _tag(group, element) + vr.encode("ascii") + b"\x00\x00" + _u32(len(value)) + value


def _element_implicit(group, element, value: bytes) -> bytes:
    """Implicit VR Little Endian element (or Sequence container): tag(4) +
    length(4) + value/content, no VR field on the wire at all -- the same
    shape whether `value` is a leaf's encoded bytes or a Sequence's
    concatenated Item bytes."""
    if len(value) % 2 != 0:
        value += b"\x00"
    return _tag(group, element) + _u32(len(value)) + value


_TAG_PIXEL_DATA = (0x7FE0, 0x0010)


def _build_dataset_with_three_nested_patient_ids() -> bytes:
    """_build_dataset() plus an Other Patient IDs Sequence with three
    sibling Items, each carrying its own distinct nested PatientID --
    proves wildcard Remove/Replace touch exactly all matching occurrences,
    and that a Replace callback receives each occurrence's own original
    value.
    """
    base = _build_dataset()
    items = b"".join(
        _dicom_item(_element_short(*_TAG_PATIENT_ID, "LO", value))
        for value in (b"NESTED-A", b"NESTED-B", b"NESTED-C")
    )
    other_patient_ids_seq = _element_sq(*_TAG_OTHER_PATIENT_IDS_SEQ, items)
    return base + other_patient_ids_seq


def _build_dataset_with_three_nested_patient_ids_and_pixel_data() -> bytes:
    return _build_dataset_with_three_nested_patient_ids() + _element_long(
        *_TAG_PIXEL_DATA, "OB", b"\xAA\xBB\xCC\xDD"
    )


def _build_explicit_vr_le_encoding_fixture() -> bytes:
    """A root Modality plus a nested PatientID under Other Patient IDs
    Sequence, Explicit VR Little Endian -- the encoding-independence
    counterpart to _build_implicit_vr_le_encoding_fixture(), same semantic
    content, different wire encoding."""
    ts_uid = b"1.2.840.10008.1.2.1"
    group_body = (
        _element_short(0x0002, 0x0002, "UI", b"1.2.3.4")
        + _element_short(0x0002, 0x0003, "UI", b"1.2.3.4.5")
        + _element_short(0x0002, 0x0010, "UI", ts_uid)
    )
    file_meta = _element_short(0x0002, 0x0000, "UL", _u32(len(group_body))) + group_body
    item_content = _element_short(*_TAG_PATIENT_ID, "LO", b"NESTED-ID")
    seq = _element_sq(*_TAG_OTHER_PATIENT_IDS_SEQ, _dicom_item(item_content))
    dataset = _element_short(*_TAG_MODALITY, "CS", b"CT") + seq
    return b"\x00" * 128 + b"DICM" + file_meta + dataset


def _build_implicit_vr_le_encoding_fixture() -> bytes:
    """Same semantic content as _build_explicit_vr_le_encoding_fixture(),
    Implicit VR Little Endian. File Meta stays Explicit VR LE regardless
    (DICOM standard requirement); only the main dataset's encoding
    switches -- both tags used (Modality, Other Patient IDs Sequence,
    PatientID) are standard PS3.6 dictionary tags, so attrs' Implicit VR
    dictionary-based VR inference (already frozen/qualified in attrs'
    own A1.4 report) resolves them without this module reimplementing any
    of that.
    """
    ts_uid = b"1.2.840.10008.1.2"  # Implicit VR Little Endian, already even length
    group_body = (
        _element_short(0x0002, 0x0002, "UI", b"1.2.3.4")
        + _element_short(0x0002, 0x0003, "UI", b"1.2.3.4.5")
        + _element_short(0x0002, 0x0010, "UI", ts_uid)
    )
    file_meta = _element_short(0x0002, 0x0000, "UL", _u32(len(group_body))) + group_body
    item_content = _element_implicit(*_TAG_PATIENT_ID, b"NESTED-ID")
    seq = _element_implicit(*_TAG_OTHER_PATIENT_IDS_SEQ, _dicom_item(item_content))
    dataset = _element_implicit(*_TAG_MODALITY, b"CT") + seq
    return b"\x00" * 128 + b"DICM" + file_meta + dataset


def _reparse_cleanly(data: bytes) -> None:
    """Mirrors fastDICOMgateway's transform.py _verify_output: reparses
    written bytes and fails if the reparse reports anything beyond an
    informational diagnostic."""
    reparsed = fds.read_buffer(data, fidelity="lossless")
    try:
        blocking = [d for d in reparsed.diagnostics if d.severity != "info"]
        assert not blocking, f"output failed self-verification reparse: {blocking}"
    finally:
        reparsed.close()


class PolicyResultSemanticsTest(unittest.TestCase):
    def setUp(self):
        self.structure = fds.read_buffer(_build_dataset(), fidelity="lossless")

    def tearDown(self):
        self.structure.close()

    def test_accept_when_no_operation_changes_anything(self):
        pol = policy.Policy(
            name="noop",
            version="1.0.0",
            operations=(
                policy.Require(_TAG_MODALITY),  # present -> satisfied, no mutation
                policy.Remove(_TAG_ABSENT),  # absent -> 0 removed
            ),
        )
        result = policy.apply(self.structure, pol)
        self.assertEqual(result.decision, policy.Decision.ACCEPT)
        self.assertEqual(result.elements_touched, 0)
        self.assertIsNone(result.failed_requirement)
        self.assertFalse(self.structure.is_modified)

    def test_transform_when_an_operation_changes_something(self):
        pol = policy.Policy(
            name="remove-name",
            version="1.0.0",
            operations=(policy.Remove(_TAG_PATIENT_NAME),),
        )
        result = policy.apply(self.structure, pol)
        self.assertEqual(result.decision, policy.Decision.TRANSFORM)
        self.assertEqual(result.elements_touched, 1)
        self.assertNotIn(_TAG_PATIENT_NAME, self.structure)
        self.assertTrue(self.structure.is_modified)

    def test_reject_when_required_tag_is_absent(self):
        pol = policy.Policy(
            name="require-absent",
            version="1.0.0",
            operations=(
                policy.Require(_TAG_ABSENT),
                policy.Remove(_TAG_PATIENT_NAME),  # must not run -- require failed first
            ),
        )
        result = policy.apply(self.structure, pol)
        self.assertEqual(result.decision, policy.Decision.REJECT)
        self.assertEqual(result.failed_requirement, _TAG_ABSENT)
        self.assertEqual(len(result.diagnostics), 1)
        self.assertEqual(result.diagnostics[0].severity, "error")
        # The Remove after the failing Require did not run: no mutation at all.
        self.assertFalse(self.structure.is_modified)
        self.assertIn(_TAG_PATIENT_NAME, self.structure)

    def test_replace_recursive_with_callback_is_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            policy.Replace(_TAG_PATIENT_ID, lambda v: v.upper(), recursive=True)

    def test_replace_with_callback_non_recursive(self):
        pol = policy.Policy(
            name="uppercase-id",
            version="1.0.0",
            operations=(policy.Replace(_TAG_PATIENT_ID, lambda v: v.upper(), recursive=False),),
        )
        result = policy.apply(self.structure, pol)
        self.assertEqual(result.decision, policy.Decision.TRANSFORM)
        self.assertEqual(result.elements_touched, 1)
        # "ID1" is odd-length, so _element_short NUL-padded it to "ID1\x00"
        # when building the fixture; .upper() leaves the NUL pad untouched.
        self.assertEqual(self.structure.get(_TAG_PATIENT_ID).value, b"ID1\x00")


class PolicyNestedStructureTest(unittest.TestCase):
    def setUp(self):
        self.structure = fds.read_buffer(_build_dataset_with_nested_occurrences(),
                                          fidelity="lossless")

    def tearDown(self):
        self.structure.close()

    def test_recursive_remove_reaches_nested_occurrence(self):
        pol = policy.Policy(
            name="remove-id-everywhere",
            version="1.0.0",
            operations=(policy.Remove(_TAG_PATIENT_ID),),  # recursive=True by default
        )
        result = policy.apply(self.structure, pol)
        self.assertEqual(result.decision, policy.Decision.TRANSFORM)
        # One top-level + one nested occurrence.
        self.assertEqual(result.elements_touched, 2)

    def test_private_tag_policy_reaches_nested_private_element(self):
        pol = policy.Policy(
            name="strip-private",
            version="1.0.0",
            operations=(policy.PrivateTagPolicy(remove=True),),
        )
        result = policy.apply(self.structure, pol)
        self.assertEqual(result.decision, policy.Decision.TRANSFORM)
        # One top-level (0009,0010) + one nested (0009,0011).
        self.assertEqual(result.elements_touched, 2)

    def test_allow_list_prune_keeps_only_listed_tags_at_every_depth(self):
        allowed = _FILE_META_TAGS | {_TAG_MODALITY, _TAG_PATIENT_ID, _TAG_OTHER_PATIENT_IDS_SEQ}
        pol = policy.Policy(
            name="allow-list",
            version="1.0.0",
            operations=(policy.AllowListPrune(tuple(allowed)),),
        )
        result = policy.apply(self.structure, pol)
        self.assertEqual(result.decision, policy.Decision.TRANSFORM)
        # Removed: PatientName, PatientBirthDate, the top-level private
        # element, and (inside the kept sequence's item) the nested private
        # element -- five listed tags stay, everything else present in the
        # fixture goes.
        self.assertGreater(result.elements_touched, 0)
        self.assertNotIn(_TAG_PATIENT_NAME, self.structure)
        self.assertNotIn(_TAG_PATIENT_BIRTH_DATE, self.structure)
        self.assertNotIn(_TAG_PRIVATE, self.structure)
        self.assertIn(_TAG_PATIENT_ID, self.structure)
        self.assertIn(_TAG_MODALITY, self.structure)
        seq = self.structure.get(_TAG_OTHER_PATIENT_IDS_SEQ)
        self.assertIsNotNone(seq)
        remaining_nested_tags = [e.tag for e in list(seq.items())[0]]
        self.assertEqual(remaining_nested_tags, [_TAG_PATIENT_ID])

        # The pruned structure must still reparse cleanly -- the allow-list
        # in this test deliberately includes the File Meta tags needed for
        # that (see AllowListPrune's docstring: this is the caller's
        # responsibility, not something the operation guarantees).
        _reparse_cleanly(self.structure.write_bytes())

    def test_replace_recursive_reaches_every_occurrence_with_one_value(self):
        pol = policy.Policy(
            name="replace-id-everywhere",
            version="1.0.0",
            operations=(policy.Replace(_TAG_PATIENT_ID, b"DEMO"),),  # recursive=True by default
        )
        result = policy.apply(self.structure, pol)
        self.assertEqual(result.elements_touched, 2)
        self.assertEqual(self.structure.get(_TAG_PATIENT_ID).value, b"DEMO")
        seq = self.structure.get(_TAG_OTHER_PATIENT_IDS_SEQ)
        nested_values = [e.value for e in list(seq.items())[0] if e.tag == _TAG_PATIENT_ID]
        self.assertEqual(nested_values, [b"DEMO"])


class PolicyDeterminismTest(unittest.TestCase):
    def test_repeated_independent_execution_is_identical(self):
        data = _build_dataset_with_nested_occurrences()
        pol = policy.Policy(
            name="remove-name-and-id",
            version="1.0.0",
            operations=(
                policy.Remove(_TAG_PATIENT_NAME),
                policy.Replace(_TAG_PATIENT_ID, b"DEMO"),
                policy.PrivateTagPolicy(remove=True),
            ),
        )
        structure_a = fds.read_buffer(data, fidelity="lossless")
        structure_b = fds.read_buffer(data, fidelity="lossless")
        try:
            result_a = policy.apply(structure_a, pol)
            result_b = policy.apply(structure_b, pol)

            self.assertEqual(result_a.decision, result_b.decision)
            self.assertEqual(
                [(r.kind, r.tag, r.count, r.satisfied) for r in result_a.operations],
                [(r.kind, r.tag, r.count, r.satisfied) for r in result_b.operations],
            )
            self.assertEqual(structure_a.write_bytes(), structure_b.write_bytes())
        finally:
            structure_a.close()
            structure_b.close()


class PolicyReproducesGatewayDemoTest(unittest.TestCase):
    """See module docstring."""

    def test_apply_reproduces_gateway_demo_policy(self):
        data = _build_dataset_with_nested_occurrences()

        # -- Declarative: the new policy abstraction --------------------
        pol = policy.Policy(
            name="gateway-demo-equivalent",
            version="1.0.0",
            operations=(
                policy.Remove(_TAG_PATIENT_NAME),
                policy.Replace(_TAG_PATIENT_ID, b"DEMO"),
                policy.Remove(_TAG_PATIENT_BIRTH_DATE),
                policy.PrivateTagPolicy(remove=True),
            ),
        )
        via_policy = fds.read_buffer(data, fidelity="lossless")

        # -- Imperative: fastDICOMgateway's transform.py _apply_demo_policy,
        # reproduced call-for-call against an independently parsed copy of
        # the same bytes. Not a call into fastDICOMgateway's code -- this
        # phase does not import or modify that repository.
        via_gateway_sequence = fds.read_buffer(data, fidelity="lossless")

        try:
            result = policy.apply(via_policy, pol)

            gw_touched = 0
            gw_touched += via_gateway_sequence.erase_recursive(_TAG_PATIENT_NAME)
            gw_touched += via_gateway_sequence.set_value_recursive(_TAG_PATIENT_ID, b"DEMO")
            gw_touched += via_gateway_sequence.erase_recursive(_TAG_PATIENT_BIRTH_DATE)
            gw_private_removed = via_gateway_sequence.erase_private()

            # Same counts, computed two different ways.
            self.assertEqual(result.decision, policy.Decision.TRANSFORM)
            self.assertEqual(result.elements_touched, gw_touched + gw_private_removed)

            # Same output bytes.
            policy_bytes = via_policy.write_bytes()
            gateway_bytes = via_gateway_sequence.write_bytes()
            self.assertEqual(policy_bytes, gateway_bytes)

            # Same self-verification-by-reparse gateway itself performs.
            _reparse_cleanly(policy_bytes)
        finally:
            via_policy.close()
            via_gateway_sequence.close()


class PolicyLocatorMigrationTest(unittest.TestCase):
    """Proves the S1.1 migration: bare-tag normalization, locator-capable
    Require/Remove/Replace, and _collect_tags' removal. See test_locator.py
    for direct engine-level qualification; this class qualifies the
    operations built on top of it.
    """

    def test_bare_tag_normalizes_to_expected_tag_locator_scope(self):
        # Require: root-only, exactly __contains__'s historical scope.
        self.assertEqual(policy.Require(_TAG_MODALITY).locator,
                          policy.TagLocator(_TAG_MODALITY, recursive=False))
        # Remove/Replace: recursive=True default, matching pre-S1.1 erase_recursive.
        self.assertEqual(policy.Remove(_TAG_PATIENT_NAME).locator,
                          policy.TagLocator(_TAG_PATIENT_NAME, recursive=True))
        self.assertEqual(policy.Remove(_TAG_PATIENT_NAME, recursive=False).locator,
                          policy.TagLocator(_TAG_PATIENT_NAME, recursive=False))
        self.assertEqual(policy.Replace(_TAG_PATIENT_ID, b"X").locator,
                          policy.TagLocator(_TAG_PATIENT_ID, recursive=True))

    def test_collect_tags_removed(self):
        self.assertFalse(hasattr(policy, "_collect_tags"))

    def test_require_zero_one_many_matches(self):
        structure = fds.read_buffer(_build_dataset_with_three_nested_patient_ids(), fidelity="lossless")
        try:
            concrete = policy.PathLocator(
                steps=(policy.LocatorStep(_TAG_OTHER_PATIENT_IDS_SEQ, 1),), tag=_TAG_PATIENT_ID
            )
            wildcard = policy.PathLocator(
                steps=(policy.LocatorStep(_TAG_OTHER_PATIENT_IDS_SEQ, "*"),), tag=_TAG_PATIENT_ID
            )
            absent = policy.PathLocator(
                steps=(policy.LocatorStep(_TAG_OTHER_PATIENT_IDS_SEQ, "*"),), tag=_TAG_ABSENT
            )

            self.assertTrue(policy.Require(concrete).apply(structure).satisfied)
            wildcard_result = policy.Require(wildcard).apply(structure)
            self.assertTrue(wildcard_result.satisfied)
            self.assertEqual(wildcard_result.count, 3)
            absent_result = policy.Require(absent).apply(structure)
            self.assertFalse(absent_result.satisfied)
            self.assertEqual(absent_result.count, 0)
        finally:
            structure.close()

    def test_remove_concrete_locator_touches_only_requested_occurrence(self):
        structure = fds.read_buffer(_build_dataset_with_three_nested_patient_ids(), fidelity="lossless")
        try:
            locator = policy.PathLocator(
                steps=(policy.LocatorStep(_TAG_OTHER_PATIENT_IDS_SEQ, 1),), tag=_TAG_PATIENT_ID
            )
            result = policy.apply(
                structure,
                policy.Policy(name="remove-middle", version="1.0.0", operations=(policy.Remove(locator),)),
            )
            self.assertEqual(result.elements_touched, 1)
            # Root-level PatientID (a different occurrence entirely) is untouched.
            self.assertEqual(structure.get(_TAG_PATIENT_ID).value, b"ID1\x00")
            seq = structure.get(_TAG_OTHER_PATIENT_IDS_SEQ)
            remaining = [[e.tag for e in item] for item in seq.items()]
            self.assertEqual(remaining, [[_TAG_PATIENT_ID], [], [_TAG_PATIENT_ID]])
        finally:
            structure.close()

    def test_remove_wildcard_touches_all_three_and_only_those(self):
        structure = fds.read_buffer(_build_dataset_with_three_nested_patient_ids(), fidelity="lossless")
        try:
            locator = policy.PathLocator(
                steps=(policy.LocatorStep(_TAG_OTHER_PATIENT_IDS_SEQ, "*"),), tag=_TAG_PATIENT_ID
            )
            result = policy.apply(
                structure,
                policy.Policy(name="remove-all-nested", version="1.0.0", operations=(policy.Remove(locator),)),
            )
            self.assertEqual(result.elements_touched, 3)
            self.assertEqual(structure.get(_TAG_PATIENT_ID).value, b"ID1\x00")  # root untouched
            seq = structure.get(_TAG_OTHER_PATIENT_IDS_SEQ)
            remaining = [[e.tag for e in item] for item in seq.items()]
            self.assertEqual(remaining, [[], [], []])
        finally:
            structure.close()

    def test_replace_wildcard_callback_receives_per_occurrence_original_value(self):
        structure = fds.read_buffer(_build_dataset_with_three_nested_patient_ids(), fidelity="lossless")
        try:
            locator = policy.PathLocator(
                steps=(policy.LocatorStep(_TAG_OTHER_PATIENT_IDS_SEQ, "*"),), tag=_TAG_PATIENT_ID
            )
            result = policy.apply(
                structure,
                policy.Policy(
                    name="lowercase-nested-ids", version="1.0.0",
                    operations=(policy.Replace(locator, lambda v: v.lower()),),
                ),
            )
            self.assertEqual(result.elements_touched, 3)
            self.assertEqual(structure.get(_TAG_PATIENT_ID).value, b"ID1\x00")  # root untouched
            seq = structure.get(_TAG_OTHER_PATIENT_IDS_SEQ)
            nested_values = [e.value for item in seq.items() for e in item if e.tag == _TAG_PATIENT_ID]
            self.assertEqual(nested_values, [b"nested-a", b"nested-b", b"nested-c"])
        finally:
            structure.close()


class PolicyEncodingIndependenceTest(unittest.TestCase):
    """A single locator-based policy definition must produce the same
    intended semantic outcome regardless of source encoding. This is a
    structure-policy claim, not a re-proof of attrs' own parser -- attrs
    already qualified Implicit VR mutation itself (A1.4/A1.7 reports); this
    only proves *policy* behavior doesn't vary with source encoding.
    """

    def _remove_nested_patient_id_policy(self) -> policy.Policy:
        locator = policy.PathLocator(
            steps=(policy.LocatorStep(_TAG_OTHER_PATIENT_IDS_SEQ, 0),), tag=_TAG_PATIENT_ID
        )
        return policy.Policy(name="remove-nested-patient-id", version="1.0.0",
                              operations=(policy.Remove(locator),))

    def test_same_locator_policy_same_semantic_outcome_explicit_and_implicit(self):
        explicit = fds.read_buffer(_build_explicit_vr_le_encoding_fixture(), fidelity="lossless")
        implicit = fds.read_buffer(_build_implicit_vr_le_encoding_fixture(), fidelity="lossless")
        try:
            self.assertTrue(explicit.is_explicit_vr)
            self.assertFalse(implicit.is_explicit_vr)

            nested_path = [(_TAG_OTHER_PATIENT_IDS_SEQ, 0), (_TAG_PATIENT_ID, None)]
            self.assertIsNotNone(explicit.find(nested_path))
            self.assertIsNotNone(implicit.find(nested_path))

            result_explicit = policy.apply(explicit, self._remove_nested_patient_id_policy())
            result_implicit = policy.apply(implicit, self._remove_nested_patient_id_policy())

            self.assertEqual(result_explicit.decision, policy.Decision.TRANSFORM)
            self.assertEqual(result_implicit.decision, policy.Decision.TRANSFORM)
            self.assertEqual(result_explicit.elements_touched, result_implicit.elements_touched)
            self.assertIsNone(explicit.find(nested_path))
            self.assertIsNone(implicit.find(nested_path))
        finally:
            explicit.close()
            implicit.close()


class PolicyNonInterferenceTest(unittest.TestCase):
    """Pixel Data (7FE0,0010) is not reachable through Structure.get/find/
    iter_elements at all -- see test_locator.py,
    test_pixel_data_target_never_resolves_and_never_materializes, for why
    (it lives outside attrs' ordinary element graph by attrs' own design).
    So "Pixel Data untouched" is checked here the only way it can be from
    Python: the fixture places it last and its own 16-byte encoding never
    changes shape (same tag/VR/reserved/length/value every time), so its
    trailing bytes in the serialized output are compared byte-for-byte
    before and after the policy runs.
    """

    _PIXEL_DATA_ENCODING = _element_long(*_TAG_PIXEL_DATA, "OB", b"\xAA\xBB\xCC\xDD")

    def setUp(self):
        self.structure = fds.read_buffer(
            _build_dataset_with_three_nested_patient_ids_and_pixel_data(), fidelity="lossless"
        )

    def tearDown(self):
        self.structure.close()

    def _assert_pixel_data_untouched(self):
        tail = self.structure.write_bytes()[-len(self._PIXEL_DATA_ENCODING):]
        self.assertEqual(tail, self._PIXEL_DATA_ENCODING)

    def test_wildcard_replace_touches_only_targeted_occurrences(self):
        self._assert_pixel_data_untouched()  # sanity: true before any mutation too
        modality_before = self.structure.get(_TAG_MODALITY).value
        private_before = self.structure.get(_TAG_PRIVATE).value
        root_patient_id_before = self.structure.get(_TAG_PATIENT_ID).value

        locator = policy.PathLocator(
            steps=(policy.LocatorStep(_TAG_OTHER_PATIENT_IDS_SEQ, "*"),), tag=_TAG_PATIENT_ID
        )
        result = policy.apply(
            self.structure,
            policy.Policy(name="lowercase-nested-ids", version="1.0.0",
                           operations=(policy.Replace(locator, lambda v: v.lower()),)),
        )
        self.assertEqual(result.elements_touched, 3)

        self.assertEqual(self.structure.get(_TAG_MODALITY).value, modality_before)
        self.assertEqual(self.structure.get(_TAG_PRIVATE).value, private_before)
        self.assertEqual(self.structure.get(_TAG_PATIENT_ID).value, root_patient_id_before)
        self._assert_pixel_data_untouched()

        seq = self.structure.get(_TAG_OTHER_PATIENT_IDS_SEQ)
        nested_values = [e.value for item in seq.items() for e in item if e.tag == _TAG_PATIENT_ID]
        self.assertEqual(nested_values, [b"nested-a", b"nested-b", b"nested-c"])

    def test_concrete_remove_leaves_sibling_items_and_pixel_data_untouched(self):
        locator = policy.PathLocator(
            steps=(policy.LocatorStep(_TAG_OTHER_PATIENT_IDS_SEQ, 1),), tag=_TAG_PATIENT_ID
        )
        result = policy.apply(
            self.structure,
            policy.Policy(name="remove-middle", version="1.0.0", operations=(policy.Remove(locator),)),
        )
        self.assertEqual(result.elements_touched, 1)

        seq = self.structure.get(_TAG_OTHER_PATIENT_IDS_SEQ)
        items = list(seq.items())
        self.assertEqual(len(items), 3)  # the Item itself survives; only its element was removed
        remaining = [[e.tag for e in item] for item in items]
        self.assertEqual(remaining, [[_TAG_PATIENT_ID], [], [_TAG_PATIENT_ID]])
        self._assert_pixel_data_untouched()


if __name__ == "__main__":
    unittest.main()
