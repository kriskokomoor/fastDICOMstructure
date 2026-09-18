"""Qualification for S1.2 (charset-aware Replace + Ensure): insertion-site
resolution, `Ensure`, `ReplaceText`, `EnsureText`, atomicity/rollback
(including the raw-byte-restoration correction -- see
docs/architecture/S1_2_REPLACE_ENSURE_DESIGN_CHECKPOINT.md section 16a), VR
delegation, charset delegation, duplicate-tag inheritance, non-interference,
encoding-independence, and performance.

Byte-fixture-building style mirrors tests/python/test_locator.py (duplicated
locally rather than shared, following that file's own stated convention).
"""

import struct
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

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
    if len(value) % 2 != 0:
        value += b"\x00"
    return _tag(group, element) + vr.encode("ascii") + _u16(len(value)) + value


def _element_long(group, element, vr, value: bytes) -> bytes:
    if len(value) % 2 != 0:
        value += b"\x00"
    return _tag(group, element) + vr.encode("ascii") + b"\x00\x00" + _u32(len(value)) + value


def _element_implicit(group, element, value: bytes) -> bytes:
    if len(value) % 2 != 0:
        value += b"\x00"
    return _tag(group, element) + _u32(len(value)) + value


def _element_sq(group, element, item_bytes: bytes) -> bytes:
    return _tag(group, element) + b"SQ" + b"\x00\x00" + _u32(len(item_bytes)) + item_bytes


def _dicom_item(content: bytes) -> bytes:
    return _tag(0xFFFE, 0xE000) + _u32(len(content)) + content


def _file_meta(ts_uid: bytes) -> bytes:
    group_body = (
        _element_short(0x0002, 0x0002, "UI", b"1.2.3.4")
        + _element_short(0x0002, 0x0003, "UI", b"1.2.3.4.5")
        + _element_short(0x0002, 0x0010, "UI", ts_uid)
    )
    return _element_short(0x0002, 0x0000, "UL", _u32(len(group_body))) + group_body


_TAG_MODALITY = (0x0008, 0x0060)
_TAG_CHARSET = (0x0008, 0x0005)
_TAG_PATIENT_NAME = (0x0010, 0x0010)
_TAG_PIXEL_DATA = (0x7FE0, 0x0010)
_TAG_PRIVATE_CREATOR = (0x0009, 0x0010)   # odd group, element 0x10-0xFF -> inferred LO
_TAG_PRIVATE_DATA = (0x0009, 0x1010)      # odd group, element >= 0x1000 -> always VRRequired
_TAG_AMBIGUOUS = (0x0028, 0x0106)         # SmallestImagePixelValue -- "US or SS", ambiguous
_TAG_UNKNOWN_STANDARD = (0x0000, 0x0002)  # PS3.7 Command-group element -- a genuine dictionary miss
_TAG_BEAM_SEQ = (0x300A, 0x00B0)
_TAG_BEAM_NAME = (0x300A, 0x00C2)         # existing in items 0/1 -- update-branch target
_TAG_BEAM_DESCRIPTION = (0x300A, 0x00C3)  # absent everywhere -- insert-branch target
_TAG_OTHER_PATIENT_IDS_SEQ = (0x0010, 0x1002)
_TAG_PATIENT_ID = (0x0010, 0x0020)


def _build_fixture() -> bytes:
    """One Explicit VR LE Part10 file covering every S1.2 charset/insertion
    scenario this module needs in one BeamSequence:

    - Item 0: local (0008,0005) override = ISO_IR 144 (Cyrillic). BeamName
      exists ("AAA") -- update-branch target. BeamDescription absent --
      insert-branch target.
    - Item 1: no local override (inherits root's ISO_IR 100/Latin1) --
      sibling isolation target. BeamName exists ("BBB"). BeamDescription
      absent.
    - Item 2: no local override. BeamName absent (with Item 0/1 existing,
      this is the "mixed existing/missing" wildcard case). BeamDescription
      absent.

    Root declares (0008,0005) = ISO_IR 100 (Latin1) so Item 1/2 inheritance
    is exercised against a real, non-default declaration, not merely "no
    declaration at all."
    """
    item0 = _dicom_item(
        _element_short(*_TAG_CHARSET, "CS", b"ISO_IR 144")
        + _element_short(*_TAG_BEAM_NAME, "LO", b"AAA")
    )
    item1 = _dicom_item(_element_short(*_TAG_BEAM_NAME, "LO", b"BBB"))
    item2 = _dicom_item(b"")  # deliberately empty -- both BeamName and BeamDescription absent

    dataset = (
        _element_short(*_TAG_MODALITY, "CS", b"CT")
        + _element_short(*_TAG_CHARSET, "CS", b"ISO_IR 100")
        + _element_short(*_TAG_PRIVATE_CREATOR, "LO", b"ACME")
        + _element_short(*_TAG_PATIENT_NAME, "PN", b"Doe^Jane")
        + _element_sq(*_TAG_BEAM_SEQ, item0 + item1 + item2)
        + _element_long(*_TAG_PIXEL_DATA, "OB", b"\xAA\xBB\xCC\xDD")
    )
    return b"\x00" * 128 + b"DICM" + _file_meta(b"1.2.840.10008.1.2.1") + dataset


def _reparse_cleanly(data: bytes) -> None:
    reparsed = fds.read_buffer(data, fidelity="lossless")
    try:
        blocking = [d for d in reparsed.diagnostics if d.severity != "info"]
        assert not blocking, f"output failed self-verification reparse: {blocking}"
    finally:
        reparsed.close()


# ---------------------------------------------------------------------------
# S1.2a -- insertion-site resolution, qualified independently of any
# operation, mirroring test_locator.py's own precedent.
# ---------------------------------------------------------------------------

class InsertionSiteResolutionTest(unittest.TestCase):
    def setUp(self):
        self.structure = fds.read_buffer(_build_fixture(), fidelity="lossless")

    def tearDown(self):
        self.structure.close()

    def test_root_tag_locator_absent_produces_one_insert_site(self):
        sites = policy._resolve_insertion_sites(
            self.structure, policy.TagLocator((0x0012, 0x0062), recursive=False)
        )
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0].parent, [])
        self.assertFalse(sites[0].exists)
        self.assertEqual(sites[0].target_path, [((0x0012, 0x0062), None)])

    def test_root_tag_locator_present_produces_one_update_site(self):
        sites = policy._resolve_insertion_sites(
            self.structure, policy.TagLocator(_TAG_MODALITY, recursive=False)
        )
        self.assertEqual(len(sites), 1)
        self.assertTrue(sites[0].exists)

    def test_recursive_tag_locator_never_inserts(self):
        # _TAG_BEAM_NAME exists at two nested occurrences (items 0 and 1),
        # never at root or anywhere else recursive=True would search --
        # zero matches at any depth other than those two.
        sites = policy._resolve_insertion_sites(
            self.structure, policy.TagLocator(_TAG_BEAM_NAME, recursive=True)
        )
        self.assertEqual(len(sites), 2)
        self.assertTrue(all(s.exists for s in sites))

    def test_recursive_tag_locator_zero_occurrences_is_zero_sites(self):
        sites = policy._resolve_insertion_sites(
            self.structure, policy.TagLocator((0x0099, 0x0099), recursive=True)
        )
        self.assertEqual(sites, [])

    def test_concrete_pathlocator_existing_target_is_update_site(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 0),), tag=_TAG_BEAM_NAME)
        sites = policy._resolve_insertion_sites(self.structure, locator)
        self.assertEqual(len(sites), 1)
        self.assertTrue(sites[0].exists)
        self.assertEqual(sites[0].parent, [(_TAG_BEAM_SEQ, 0)])

    def test_concrete_pathlocator_missing_leaf_existing_parent_is_insert_site(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 0),),
                                      tag=_TAG_BEAM_DESCRIPTION)
        sites = policy._resolve_insertion_sites(self.structure, locator)
        self.assertEqual(len(sites), 1)
        self.assertFalse(sites[0].exists)
        self.assertEqual(sites[0].parent, [(_TAG_BEAM_SEQ, 0)])

    def test_missing_intermediate_sequence_produces_no_sites(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep((0x0099, 0x0099), 0),),
                                      tag=_TAG_BEAM_DESCRIPTION)
        self.assertEqual(policy._resolve_insertion_sites(self.structure, locator), [])

    def test_missing_item_index_produces_no_sites(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 99),),
                                      tag=_TAG_BEAM_DESCRIPTION)
        self.assertEqual(policy._resolve_insertion_sites(self.structure, locator), [])

    def test_non_sq_intermediate_produces_no_sites(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_MODALITY, 0),),
                                      tag=_TAG_BEAM_DESCRIPTION)
        self.assertEqual(policy._resolve_insertion_sites(self.structure, locator), [])

    def test_wildcard_mixed_existing_missing_in_deterministic_order(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),),
                                      tag=_TAG_BEAM_NAME)
        sites = policy._resolve_insertion_sites(self.structure, locator)
        self.assertEqual(len(sites), 3)
        self.assertEqual([s.exists for s in sites], [True, True, False])
        self.assertEqual([s.parent for s in sites],
                          [[(_TAG_BEAM_SEQ, 0)], [(_TAG_BEAM_SEQ, 1)], [(_TAG_BEAM_SEQ, 2)]])

    def test_wildcard_insert_branch_produces_one_site_per_item_all_missing(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),),
                                      tag=_TAG_BEAM_DESCRIPTION)
        sites = policy._resolve_insertion_sites(self.structure, locator)
        self.assertEqual(len(sites), 3)
        self.assertTrue(all(not s.exists for s in sites))

    def test_deterministic_resolution_repeated(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NAME)
        first = policy._resolve_insertion_sites(self.structure, locator)
        second = policy._resolve_insertion_sites(self.structure, locator)
        self.assertEqual(first, second)


# ---------------------------------------------------------------------------
# S1.2b -- raw Ensure
# ---------------------------------------------------------------------------

class EnsureRawTest(unittest.TestCase):
    def setUp(self):
        self.structure = fds.read_buffer(_build_fixture(), fidelity="lossless")

    def tearDown(self):
        self.structure.close()

    def test_root_absent_inserts_default_scope(self):
        op = policy.Ensure((0x0012, 0x0062), b"YES")
        self.assertEqual(op.locator, policy.TagLocator((0x0012, 0x0062), recursive=False))
        result = op.apply(self.structure)
        self.assertEqual(result.count, 1)
        self.assertTrue(result.satisfied)
        self.assertEqual(self.structure.get((0x0012, 0x0062)).value, b"YES ")

    def test_root_present_updates(self):
        result = policy.Ensure(_TAG_MODALITY, b"MR").apply(self.structure)
        self.assertEqual(result.count, 1)
        self.assertEqual(self.structure.get(_TAG_MODALITY).value, b"MR")

    def test_concrete_nested_update_and_insert(self):
        update_locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 0),),
                                             tag=_TAG_BEAM_NAME)
        result = policy.Ensure(update_locator, b"ZZZZ").apply(self.structure)
        self.assertEqual(result.count, 1)
        self.assertEqual(self.structure.find([(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_NAME, None)]).value, b"ZZZZ")

        insert_locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 1),),
                                             tag=_TAG_BEAM_DESCRIPTION)
        result2 = policy.Ensure(insert_locator, b"DESC").apply(self.structure)
        self.assertEqual(result2.count, 1)
        self.assertEqual(self.structure.find([(_TAG_BEAM_SEQ, 1), (_TAG_BEAM_DESCRIPTION, None)]).value,
                          b"DESC")

    def test_missing_structural_parent_is_no_synthesis_no_op(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep((0x0099, 0x0099), 0),), tag=(0x0001, 0x0001))
        result = policy.Ensure(locator, b"X").apply(self.structure)
        self.assertEqual(result.count, 0)
        self.assertFalse(result.satisfied)
        self.assertFalse((0x0099, 0x0099) in self.structure)

    def test_wildcard_mixed_existing_missing_one_pass(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NAME)
        result = policy.Ensure(locator, b"MARK").apply(self.structure)
        self.assertEqual(result.count, 3)
        for item_index in range(3):
            value = self.structure.find([(_TAG_BEAM_SEQ, item_index), (_TAG_BEAM_NAME, None)]).value
            self.assertEqual(value, b"MARK")

    def test_ensure_rejects_callback(self):
        with self.assertRaises(ValueError):
            policy.Ensure(_TAG_MODALITY, lambda v: v)

    # -- VR delegation matrix (all delegated to attrs, none reimplemented) --

    def test_vr_explicit_used_verbatim(self):
        result = policy.Ensure((0x0041, 0x0010), b"X", vr="LO").apply(self.structure)
        self.assertEqual(result.count, 1)
        self.assertEqual(self.structure.get((0x0041, 0x0010)).vr, "LO")

    def test_vr_unambiguous_inferred(self):
        result = policy.Ensure(_TAG_PATIENT_ID, b"ID1", vr=None).apply(self.structure)
        self.assertEqual(result.count, 1)
        self.assertEqual(self.structure.get(_TAG_PATIENT_ID).vr, "LO")

    def test_vr_ambiguous_raises_vr_required(self):
        with self.assertRaises(fastdicomattrs.VRRequiredError):
            policy.Ensure(_TAG_AMBIGUOUS, b"\x01\x00", vr=None).apply(self.structure)
        self.assertFalse(_TAG_AMBIGUOUS in self.structure)

    def test_vr_unknown_standard_tag_raises_vr_required(self):
        with self.assertRaises(fastdicomattrs.VRRequiredError):
            policy.Ensure(_TAG_UNKNOWN_STANDARD, b"AB", vr=None).apply(self.structure)

    def test_vr_private_data_always_requires_explicit(self):
        with self.assertRaises(fastdicomattrs.VRRequiredError):
            policy.Ensure(_TAG_PRIVATE_DATA, b"SECRET", vr=None).apply(self.structure)

    def test_vr_private_creator_declaration_inferred_lo(self):
        result = policy.Ensure((0x0009, 0x0011), b"BLOCK11", vr=None).apply(self.structure)
        self.assertEqual(result.count, 1)
        self.assertEqual(self.structure.get((0x0009, 0x0011)).vr, "LO")

    # -- atomicity / raw rollback --

    def test_atomic_rollback_restores_raw_bytes_on_later_site_failure(self):
        """Forces item 1's forward mutation to fail *after* item 0's forward
        mutation has already genuinely succeeded (using the real,
        un-mocked `set_value` for every other call, including item 0's
        rollback) -- proving both (a) a prior success is correctly rolled
        back, and (b) that rollback itself succeeds completely under
        perfectly ordinary conditions (the expected normal case), since
        `_MutationFailed` -- not `RollbackError` -- is what's raised here.
        """
        before0 = self.structure.find([(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_NAME, None)]).value
        before1 = self.structure.find([(_TAG_BEAM_SEQ, 1), (_TAG_BEAM_NAME, None)]).value

        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NAME)
        real_set_value = fastdicomattrs.Structure.set_value
        call_count = {"n": 0}

        def flaky_set_value(self, path, value):
            call_count["n"] += 1
            if call_count["n"] == 2:
                return False  # simulate the second (item 1) forward mutation failing
            return real_set_value(self, path, value)  # every other call, including rollback, is real

        with mock.patch.object(fastdicomattrs.Structure, "set_value", flaky_set_value):
            with self.assertRaises(policy._MutationFailed):
                policy.Ensure(locator, b"NEWVAL").apply(self.structure)

        after0 = self.structure.find([(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_NAME, None)]).value
        after1 = self.structure.find([(_TAG_BEAM_SEQ, 1), (_TAG_BEAM_NAME, None)]).value
        self.assertEqual(after0, before0)
        self.assertEqual(after1, before1)

    def test_rollback_failure_surfaces_as_rollback_error_not_silent_success(self):
        """Deliberately forces the *rollback* attempt itself to fail (item
        0's forward mutation succeeds, item 1's forward mutation fails
        triggering rollback, and item 0's own rollback attempt is then also
        forced to fail) -- proving this is surfaced as `RollbackError`
        rather than silently reported as if the operation had merely failed
        cleanly. This scenario cannot occur naturally under attrs' own
        documented contracts (section 16a); it is constructed here only to
        prove the failure-handling code path itself is real, not vestigial.
        """
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NAME)
        real_set_value = fastdicomattrs.Structure.set_value
        forward_calls = {"n": 0}

        def flaky(self, path, value):
            forward_calls["n"] += 1
            if forward_calls["n"] == 1:
                return real_set_value(self, path, value)  # item 0 forward: succeeds
            if forward_calls["n"] == 2:
                return False  # item 1 forward: fails, triggers rollback
            return False  # the rollback attempt on item 0 -- forced to fail too

        with mock.patch.object(fastdicomattrs.Structure, "set_value", flaky):
            with self.assertRaises(policy.RollbackError) as ctx:
                policy.Ensure(locator, b"NEWVAL").apply(self.structure)
        self.assertIsInstance(ctx.exception.forward_error, policy._MutationFailed)
        self.assertEqual(len(ctx.exception.failed_undo_actions), 1)
        self.assertEqual(ctx.exception.failed_undo_actions[0][0], "restore_raw")
        self.assertIs(ctx.exception.__cause__, ctx.exception.forward_error)

    # -- duplicate-tag regression --

    def test_duplicate_tag_in_one_container_updates_first_occurrence_only(self):
        """PS3.5 prohibits duplicate tags within one container; attrs' own
        path resolution (verified from source -- see the S1.2 design
        checkpoint section 3/19) resolves to the *first* match and stops, at
        every level, for every path-based primitive. Structure inherits this
        automatically and builds no duplicate-detection machinery of its
        own -- this is the one regression test proving that inherited
        behavior against a genuinely non-canonical fixture."""
        item_with_duplicates = _dicom_item(
            _element_short(*_TAG_PATIENT_ID, "LO", b"FIRST")
            + _element_short(*_TAG_PATIENT_ID, "LO", b"SECOND")
        )
        seq = _element_sq(*_TAG_OTHER_PATIENT_IDS_SEQ, item_with_duplicates)
        dataset = _element_short(*_TAG_MODALITY, "CS", b"CT") + seq
        full = b"\x00" * 128 + b"DICM" + _file_meta(b"1.2.840.10008.1.2.1") + dataset
        s = fds.read_buffer(full, fidelity="lossless")
        try:
            locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_OTHER_PATIENT_IDS_SEQ, 0),),
                                         tag=_TAG_PATIENT_ID)
            result = policy.Ensure(locator, b"UPDATED\x00").apply(s)
            self.assertEqual(result.count, 1)
            seq_element = s.get(_TAG_OTHER_PATIENT_IDS_SEQ)
            values = [e.value for e in list(seq_element.items())[0] if e.tag == _TAG_PATIENT_ID]
            self.assertEqual(values, [b"UPDATED\x00", b"SECOND"])
        finally:
            s.close()


# ---------------------------------------------------------------------------
# S1.2c -- ReplaceText / EnsureText, charset qualification (both update and
# insert branches), SpecificCharacterSet boundary, callback.
# ---------------------------------------------------------------------------

class ReplaceTextEnsureTextTest(unittest.TestCase):
    def setUp(self):
        self.structure = fds.read_buffer(_build_fixture(), fidelity="lossless")

    def tearDown(self):
        self.structure.close()

    # -- update branch: inheritance / override / sibling isolation --

    def test_update_branch_root_inheritance(self):
        # Root declares ISO_IR 100 (Latin1); PatientName has no local
        # override -- 'é' (U+00E9) is Latin1-representable.
        policy.ReplaceText(_TAG_PATIENT_NAME, "Müller^Anna").apply(self.structure)
        self.assertEqual(self.structure.decode_text(_TAG_PATIENT_NAME), ["Müller^Anna"])

    def test_update_branch_local_override(self):
        # Item 0 locally overrides to ISO_IR 144 (Cyrillic).
        path = [(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_NAME, None)]
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 0),), tag=_TAG_BEAM_NAME)
        policy.ReplaceText(locator, "Рей").apply(self.structure)  # Cyrillic -- representable there
        self.assertEqual(self.structure.decode_text(path), ["Рей"])

    def test_update_branch_override_rejects_out_of_repertoire_character(self):
        # Same Cyrillic-override Item -- a Latin1-only character ('é') is
        # NOT representable under Item 0's own ISO_IR 144 override, proving
        # the override actually took effect rather than silently falling
        # back to root's Latin1.
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 0),), tag=_TAG_BEAM_NAME)
        with self.assertRaises(fastdicomattrs.UnrepresentableCharacterError):
            policy.ReplaceText(locator, "café").apply(self.structure)

    def test_update_branch_sibling_isolation(self):
        # Item 1 is Item 0's sibling and declares no override of its own --
        # it must inherit ROOT's Latin1, never leak Item 0's Cyrillic
        # override. 'é' (Latin1) succeeds; a Cyrillic-only character would
        # not (proven in the next test).
        path = [(_TAG_BEAM_SEQ, 1), (_TAG_BEAM_NAME, None)]
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 1),), tag=_TAG_BEAM_NAME)
        policy.ReplaceText(locator, "café").apply(self.structure)
        self.assertEqual(self.structure.decode_text(path), ["café"])

    def test_update_branch_sibling_isolation_rejects_neighbors_repertoire(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 1),), tag=_TAG_BEAM_NAME)
        with self.assertRaises(fastdicomattrs.UnrepresentableCharacterError):
            policy.ReplaceText(locator, "Рей").apply(self.structure)  # Cyrillic, Item 1 has no override

    # -- insert branch: the A1.7 freeze-critical parent-container resolution --

    def test_insert_branch_root_inheritance(self):
        op = policy.EnsureText((0x0012, 0x0063), "café")  # root, no override -> inherits root Latin1
        result = op.apply(self.structure)
        self.assertEqual(result.count, 1)
        self.assertEqual(self.structure.decode_text((0x0012, 0x0063)), ["café"])

    def test_insert_branch_local_override(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 0),),
                                      tag=_TAG_BEAM_DESCRIPTION)
        policy.EnsureText(locator, "Рей").apply(self.structure)
        path = [(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_DESCRIPTION, None)]
        self.assertEqual(self.structure.decode_text(path), ["Рей"])

    def test_insert_branch_override_rejects_out_of_repertoire_character(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 0),),
                                      tag=_TAG_BEAM_DESCRIPTION)
        with self.assertRaises(fastdicomattrs.UnrepresentableCharacterError):
            policy.EnsureText(locator, "café").apply(self.structure)
        self.assertFalse((0x300A, 0x00C3) in
                          [e.tag for e in list(self.structure.get(_TAG_BEAM_SEQ).items())[0]])

    def test_insert_branch_sibling_isolation(self):
        # This is the exact A1.7 freeze-critical property (design checkpoint
        # section 14): the insert branch resolves charset context at the
        # PARENT CONTAINER, not naively via the element-locator walker that
        # would stop one step short and silently miss a sibling's override.
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 1),),
                                      tag=_TAG_BEAM_DESCRIPTION)
        policy.EnsureText(locator, "café").apply(self.structure)
        path = [(_TAG_BEAM_SEQ, 1), (_TAG_BEAM_DESCRIPTION, None)]
        self.assertEqual(self.structure.decode_text(path), ["café"])

    def test_insert_branch_sibling_isolation_rejects_neighbors_repertoire(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 1),),
                                      tag=_TAG_BEAM_DESCRIPTION)
        with self.assertRaises(fastdicomattrs.UnrepresentableCharacterError):
            policy.EnsureText(locator, "Рей").apply(self.structure)

    def test_wildcard_ensure_text_mixed_existing_missing(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NAME)
        # ASCII-only value: representable under every item's effective
        # context (root Latin1 or item 0's Cyrillic override alike) --
        # isolates the mixed existing/missing structural behavior from any
        # charset-representability failure.
        result = policy.EnsureText(locator, "MARK").apply(self.structure)
        self.assertEqual(result.count, 3)
        for item_index in range(3):
            path = [(_TAG_BEAM_SEQ, item_index), (_TAG_BEAM_NAME, None)]
            self.assertEqual(self.structure.decode_text(path), ["MARK"])

    # -- SpecificCharacterSet boundary --

    def test_specific_character_set_rejected_by_replace_text(self):
        with self.assertRaises(fastdicomattrs.FdsError):
            policy.ReplaceText(_TAG_CHARSET, "ISO_IR 192").apply(self.structure)

    def test_specific_character_set_rejected_by_ensure_text(self):
        with self.assertRaises(fastdicomattrs.FdsError):
            policy.EnsureText(_TAG_CHARSET, "ISO_IR 192").apply(self.structure)

    def test_raw_replace_on_specific_character_set_does_not_transcode_dataset(self):
        # Raw Replace succeeds (it's a raw operation, no text-VR check) --
        # but changing the declaration must NOT retroactively transcode any
        # already-encoded text element. No such capability exists at any
        # layer of this family; prove PatientName's raw bytes are
        # byte-identical before and after.
        before = self.structure.get(_TAG_PATIENT_NAME).value
        policy.Replace(_TAG_CHARSET, b"ISO_IR 192").apply(self.structure)
        after = self.structure.get(_TAG_PATIENT_NAME).value
        self.assertEqual(before, after)
        self.assertEqual(self.structure.get(_TAG_CHARSET).value, b"ISO_IR 192")

    def test_ensure_text_rejects_callback(self):
        with self.assertRaises(ValueError):
            policy.EnsureText(_TAG_PATIENT_NAME, lambda values: values)

    # -- ReplaceText callback --

    def test_replace_text_callback_receives_decoded_text_per_occurrence(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NAME)

        def uppercase(values):
            return [v.upper() for v in values]

        result = policy.ReplaceText(locator, uppercase).apply(self.structure)
        self.assertEqual(result.count, 2)  # only items 0/1 have BeamName; item 2 has none
        self.assertEqual(
            self.structure.decode_text([(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_NAME, None)]), ["AAA"]
        )
        self.assertEqual(
            self.structure.decode_text([(_TAG_BEAM_SEQ, 1), (_TAG_BEAM_NAME, None)]), ["BBB"]
        )

    def test_replace_text_recursive_bare_tag_callback_forbidden(self):
        with self.assertRaises(ValueError):
            policy.ReplaceText(_TAG_BEAM_NAME, lambda v: v, recursive=True)

    # -- freeze-critical: raw-byte rollback, non-canonical original padding --

    def test_text_rollback_restores_exact_raw_bytes_not_merely_same_decoded_text(self):
        """Item 0's ORIGINAL BeamName is deliberately encoded with a
        non-canonical NUL pad byte (real DICOM text padding must be SPACE
        0x20 per PS3.5 6.4/A1.6 section 15 -- some real-world non-conformant
        files use NUL anyway). If rollback were implemented as
        decode_text(before) -> set_text(after-failure, saved_text) (the
        original, rejected design), attrs' own encoder would re-pad with
        SPACE, silently changing the trailing byte even though the decoded
        text matches -- this test would then pass under a
        decode_text-equality assertion while *failing* a raw-byte-equality
        one. Asserting raw-byte equality here is what actually catches that
        design defect; it is why the design checkpoint's correction (S1.2
        section 16a) specifies restoring via `set_value` with the exact
        captured original bytes, never via re-encoding.
        """
        odd_length_text = b"AAAAA"  # 5 bytes, odd -- forces a pad byte to exist at all
        non_canonical_item0 = _dicom_item(
            _element_short(*_TAG_CHARSET, "CS", b"ISO_IR 144")
            + (_tag(*_TAG_BEAM_NAME) + b"LO" + _u16(6) + odd_length_text + b"\x00")  # NUL pad, not SPACE
        )
        item1 = _dicom_item(_element_short(*_TAG_BEAM_NAME, "LO", b"BBB"))
        dataset = (
            _element_short(*_TAG_MODALITY, "CS", b"CT")
            + _element_short(*_TAG_CHARSET, "CS", b"ISO_IR 100")
            + _element_sq(*_TAG_BEAM_SEQ, non_canonical_item0 + item1)
        )
        data = b"\x00" * 128 + b"DICM" + _file_meta(b"1.2.840.10008.1.2.1") + dataset
        s = fds.read_buffer(data, fidelity="lossless")
        try:
            path0 = [(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_NAME, None)]
            before0_raw = s.find(path0).value
            self.assertEqual(before0_raw, b"AAAAA\x00")  # confirm the non-canonical pad is really there
            self.assertEqual(s.decode_text(path0), ["AAAAA"])  # decodes fine despite non-canonical pad

            locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),),
                                          tag=_TAG_BEAM_NAME)

            def value_for(decoded):
                # Item 0 decodes to ["AAAAA"] -> succeed with a Cyrillic
                # replacement (representable under its own override).
                # Item 1 decodes to ["BBB"] -> return a Cyrillic-only
                # character that Item 1's inherited Latin1 context cannot
                # represent, forcing failure there.
                if decoded == ["AAAAA"]:
                    return "Рей"
                return "Рей"  # also fails for item 1 (Latin1-only context)

            with self.assertRaises(fastdicomattrs.UnrepresentableCharacterError):
                policy.ReplaceText(locator, value_for).apply(s)

            after0_raw = s.find(path0).value
            self.assertEqual(
                after0_raw, before0_raw,
                "rollback must restore the EXACT original raw bytes (including the non-canonical "
                "NUL pad), not a re-encoded (space-padded) equivalent of the same decoded text",
            )
        finally:
            s.close()


# ---------------------------------------------------------------------------
# S1.2d -- non-interference, encoding-independence, performance, independent
# validation, and full-suite integration.
# ---------------------------------------------------------------------------

class NonInterferenceTest(unittest.TestCase):
    """Pixel Data is not reachable via Structure.get/find/iter_elements at
    all (S1.1 finding, unaffected by S1.2) -- so, as in S1.1's own
    non-interference tests, Pixel Data preservation is checked via the
    trailing bytes of write_bytes() output, which never change shape for an
    untouched, source-backed Pixel Data element regardless of what else in
    the file changes."""

    _PIXEL_DATA_ENCODING = _element_long(*_TAG_PIXEL_DATA, "OB", b"\xAA\xBB\xCC\xDD")

    def setUp(self):
        self.structure = fds.read_buffer(_build_fixture(), fidelity="lossless")

    def tearDown(self):
        self.structure.close()

    def _assert_pixel_data_untouched(self):
        tail = self.structure.write_bytes()[-len(self._PIXEL_DATA_ENCODING):]
        self.assertEqual(tail, self._PIXEL_DATA_ENCODING)

    def test_successful_wildcard_ensure_preserves_unrelated_elements_and_pixel_data(self):
        self._assert_pixel_data_untouched()
        modality_before = self.structure.get(_TAG_MODALITY).value
        patient_name_before = self.structure.get(_TAG_PATIENT_NAME).value

        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NAME)
        result = policy.Ensure(locator, b"MARK").apply(self.structure)
        self.assertEqual(result.count, 3)

        self.assertEqual(self.structure.get(_TAG_MODALITY).value, modality_before)
        self.assertEqual(self.structure.get(_TAG_PATIENT_NAME).value, patient_name_before)
        self._assert_pixel_data_untouched()

    def test_successful_wildcard_ensure_text_preserves_unrelated_elements_and_pixel_data(self):
        self._assert_pixel_data_untouched()
        modality_before = self.structure.get(_TAG_MODALITY).value

        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),),
                                      tag=_TAG_BEAM_DESCRIPTION)
        result = policy.EnsureText(locator, "MARK").apply(self.structure)
        self.assertEqual(result.count, 3)

        self.assertEqual(self.structure.get(_TAG_MODALITY).value, modality_before)
        self._assert_pixel_data_untouched()

    def test_failed_operation_preserves_unrelated_elements_and_pixel_data(self):
        modality_before = self.structure.get(_TAG_MODALITY).value
        patient_name_before = self.structure.get(_TAG_PATIENT_NAME).value
        beam_name0_before = self.structure.find([(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_NAME, None)]).value
        beam_name1_before = self.structure.find([(_TAG_BEAM_SEQ, 1), (_TAG_BEAM_NAME, None)]).value

        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NAME)
        # Item 0 (Cyrillic override) succeeds with "Рей"; Item 1 (Latin1
        # inherited) cannot represent it -- forces a mid-batch failure and
        # rollback after Item 0's mutation already applied.
        with self.assertRaises(fastdicomattrs.UnrepresentableCharacterError):
            policy.ReplaceText(locator, "Рей").apply(self.structure)

        self.assertEqual(self.structure.get(_TAG_MODALITY).value, modality_before)
        self.assertEqual(self.structure.get(_TAG_PATIENT_NAME).value, patient_name_before)
        self.assertEqual(
            self.structure.find([(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_NAME, None)]).value, beam_name0_before
        )
        self.assertEqual(
            self.structure.find([(_TAG_BEAM_SEQ, 1), (_TAG_BEAM_NAME, None)]).value, beam_name1_before
        )
        self._assert_pixel_data_untouched()


class EncodingIndependenceTest(unittest.TestCase):
    """A single locator-based Ensure/EnsureText policy must produce the same
    semantic outcome regardless of Explicit vs. Implicit VR Little Endian
    source encoding -- mirrors S1.1's own PolicyEncodingIndependenceTest."""

    def _build_explicit(self) -> bytes:
        item = _dicom_item(_element_short(*_TAG_BEAM_NAME, "LO", b"AAA"))
        dataset = (
            _element_short(*_TAG_MODALITY, "CS", b"CT")
            + _element_short(*_TAG_CHARSET, "CS", b"ISO_IR 100")
            + _element_sq(*_TAG_BEAM_SEQ, item)
        )
        return b"\x00" * 128 + b"DICM" + _file_meta(b"1.2.840.10008.1.2.1") + dataset

    def _build_implicit(self) -> bytes:
        item = _dicom_item(_element_implicit(*_TAG_BEAM_NAME, b"AAA"))
        dataset = (
            _element_implicit(*_TAG_MODALITY, b"CT")
            + _element_implicit(*_TAG_CHARSET, b"ISO_IR 100")
            + _element_implicit(*_TAG_BEAM_SEQ, item)
        )
        return b"\x00" * 128 + b"DICM" + _file_meta(b"1.2.840.10008.1.2") + dataset

    def test_ensure_update_and_insert_equivalent_explicit_and_implicit(self):
        explicit = fds.read_buffer(self._build_explicit(), fidelity="lossless")
        implicit = fds.read_buffer(self._build_implicit(), fidelity="lossless")
        try:
            self.assertTrue(explicit.is_explicit_vr)
            self.assertFalse(implicit.is_explicit_vr)

            update_locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 0),),
                                                 tag=_TAG_BEAM_NAME)
            insert_locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 0),),
                                                 tag=_TAG_BEAM_DESCRIPTION)

            r1e = policy.Ensure(update_locator, b"BBBB").apply(explicit)
            r1i = policy.Ensure(update_locator, b"BBBB").apply(implicit)
            r2e = policy.Ensure(insert_locator, b"DESC").apply(explicit)
            r2i = policy.Ensure(insert_locator, b"DESC").apply(implicit)

            self.assertEqual(r1e.count, r1i.count)
            self.assertEqual(r2e.count, r2i.count)
            self.assertEqual(
                explicit.find([(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_NAME, None)]).value,
                implicit.find([(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_NAME, None)]).value,
            )
            self.assertEqual(
                explicit.find([(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_DESCRIPTION, None)]).value,
                implicit.find([(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_DESCRIPTION, None)]).value,
            )
        finally:
            explicit.close()
            implicit.close()

    def test_ensure_text_equivalent_explicit_and_implicit(self):
        explicit = fds.read_buffer(self._build_explicit(), fidelity="lossless")
        implicit = fds.read_buffer(self._build_implicit(), fidelity="lossless")
        try:
            locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, 0),),
                                          tag=_TAG_BEAM_DESCRIPTION)
            policy.EnsureText(locator, "café").apply(explicit)
            policy.EnsureText(locator, "café").apply(implicit)
            path = [(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_DESCRIPTION, None)]
            self.assertEqual(explicit.decode_text(path), implicit.decode_text(path))
        finally:
            explicit.close()
            implicit.close()


class PerformanceTest(unittest.TestCase):
    """Detects obviously pathological behavior in insertion-site resolution
    and Ensure/EnsureText's undo logging -- no micro-benchmarking, no
    optimization. See the S1.2 implementation report's "Performance"
    section for the numbers this recorded."""

    @classmethod
    def setUpClass(cls):
        item_count = 1000
        items = b"".join(
            _dicom_item(_element_short(*_TAG_BEAM_NAME, "LO", str(i).encode("ascii")))
            for i in range(item_count)
        )
        dataset = (
            _element_short(*_TAG_MODALITY, "CS", b"CT")
            + _element_sq(*_TAG_BEAM_SEQ, items)
        )
        cls._item_count = item_count
        cls._data = b"\x00" * 128 + b"DICM" + _file_meta(b"1.2.840.10008.1.2.1") + dataset

    def setUp(self):
        self.structure = fds.read_buffer(self._data, fidelity="lossless")

    def tearDown(self):
        self.structure.close()

    def _time(self, fn):
        start = time.perf_counter()
        result = fn()
        return time.perf_counter() - start, result

    def test_root_ensure_is_fast(self):
        elapsed, result = self._time(lambda: policy.Ensure(_TAG_MODALITY, b"MR").apply(self.structure))
        self.assertEqual(result.count, 1)
        self.assertLess(elapsed, 1.0)

    def test_deep_concrete_ensure_is_fast(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, self._item_count - 1),),
                                      tag=_TAG_BEAM_DESCRIPTION)
        elapsed, result = self._time(lambda: policy.Ensure(locator, b"X").apply(self.structure))
        self.assertEqual(result.count, 1)
        self.assertLess(elapsed, 1.0)

    def test_one_level_wildcard_ensure_over_1000_items(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NAME)
        elapsed, result = self._time(lambda: policy.Ensure(locator, b"MARK").apply(self.structure))
        self.assertEqual(result.count, self._item_count)
        self.assertLess(elapsed, 10.0)

    def test_one_level_wildcard_ensure_text_over_1000_items(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),),
                                      tag=_TAG_BEAM_DESCRIPTION)
        elapsed, result = self._time(lambda: policy.EnsureText(locator, "MARK").apply(self.structure))
        self.assertEqual(result.count, self._item_count)
        self.assertLess(elapsed, 15.0)

    def test_multi_level_wildcard_insertion_site_resolution_scales(self):
        # Reuse the S1.1-style multi-level shape at smaller scale (400x5) to
        # confirm _resolve_insertion_sites itself (not just Ensure's
        # mutation cost) doesn't regress the linear-traversal property S1.1
        # already established for resolve_locator.
        inner_seq_tag = (0x300A, 0x0111)
        cp_tag = (0x300A, 0x0114)
        items = b"".join(
            _dicom_item(
                _element_sq(*inner_seq_tag,
                             b"".join(_dicom_item(_element_short(*cp_tag, "DS", str(j).encode()))
                                      for j in range(5)))
            )
            for _ in range(400)
        )
        dataset = _element_short(*_TAG_MODALITY, "CS", b"CT") + _element_sq(*_TAG_BEAM_SEQ, items)
        data = b"\x00" * 128 + b"DICM" + _file_meta(b"1.2.840.10008.1.2.1") + dataset
        structure = fds.read_buffer(data, fidelity="lossless")
        try:
            locator = policy.PathLocator(
                steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"), policy.LocatorStep(inner_seq_tag, "*")),
                tag=cp_tag,
            )
            elapsed, sites = self._time(lambda: policy._resolve_insertion_sites(structure, locator))
            self.assertEqual(len(sites), 2000)
            self.assertLess(elapsed, 5.0)
        finally:
            structure.close()


class IndependentValidationTest(unittest.TestCase):
    """Differential validation against independent implementations --
    pydicom (a separate Python DICOM library) and DCMTK's dcmdump (a
    separate C++ implementation) -- reading this library's own output, not
    this library re-checking itself."""

    def test_pydicom_confirms_ensure_text_and_replace_text_output(self):
        try:
            import pydicom
            import io
        except ImportError:
            self.skipTest("pydicom not available in this environment")

        structure = fds.read_buffer(_build_fixture(), fidelity="lossless")
        try:
            policy.ReplaceText(_TAG_PATIENT_NAME, "Müller^Anna").apply(structure)
            policy.EnsureText((0x0012, 0x0063), "café").apply(structure)
            output = structure.write_bytes()
        finally:
            structure.close()

        _reparse_cleanly(output)

        ds = pydicom.dcmread(io.BytesIO(output))
        self.assertEqual(str(ds.PatientName), "Müller^Anna")
        self.assertEqual(str(ds[(0x0012, 0x0063)].value), "café")
        self.assertEqual(ds.Modality, "CT")
        self.assertEqual(ds.SpecificCharacterSet, "ISO_IR 100")

    def test_dcmtk_dcmdump_confirms_ensure_text_output(self):
        import shutil
        import subprocess
        import tempfile

        dcmdump = shutil.which("dcmdump")
        if dcmdump is None:
            self.skipTest("dcmdump (DCMTK) not available in this environment")

        structure = fds.read_buffer(_build_fixture(), fidelity="lossless")
        try:
            # (0012,0062) PatientIdentityRemoved is CS (not text-governed) --
            # raw Ensure. (0012,0063) DeidentificationMethod is LO (text-
            # governed) -- EnsureText, exercising the charset-aware path.
            policy.Ensure((0x0012, 0x0062), b"YES").apply(structure)
            policy.EnsureText((0x0012, 0x0063), "POLICY-X").apply(structure)
            output = structure.write_bytes()
        finally:
            structure.close()

        _reparse_cleanly(output)

        with tempfile.NamedTemporaryFile(suffix=".dcm") as f:
            f.write(output)
            f.flush()
            result = subprocess.run([dcmdump, f.name], capture_output=True, text=True, timeout=30)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PatientIdentityRemoved", result.stdout)
        self.assertIn("YES", result.stdout)
        self.assertIn("DeidentificationMethod", result.stdout)
        self.assertIn("POLICY-X", result.stdout)


if __name__ == "__main__":
    unittest.main()
