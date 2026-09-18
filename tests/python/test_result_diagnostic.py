"""Qualification for S1.3 (Result / Diagnostic Completion): ExecutionStatus/
PolicyExecutionStatus semantics, `satisfied`'s re-scoped meaning, the raw
`Replace` atomicity and silent-failure corrections, the stable Diagnostic
code vocabulary, the Policy.apply() exception boundary, RollbackError's
exceptional status, privacy, and the differential proof that this model
resolves the conflations the S1.3 design checkpoint's own evidence-gathering
found.

Byte-fixture-building style mirrors tests/python/test_ensure_and_text.py
(duplicated locally rather than shared, following that file's own stated
convention).
"""

import json
import struct
import sys
import time
import unittest
from dataclasses import asdict
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
_TAG_PATIENT_NAME = (0x0010, 0x0010)  # sensitive fixture literal target for the privacy test
_TAG_PIXEL_DATA = (0x7FE0, 0x0010)
_TAG_AMBIGUOUS = (0x0028, 0x0106)         # SmallestImagePixelValue -- "US or SS", ambiguous
_TAG_BEAM_SEQ = (0x300A, 0x00B0)
_TAG_BEAM_NAME = (0x300A, 0x00C2)
_TAG_BEAM_DESCRIPTION = (0x300A, 0x00C3)

_SENSITIVE_NAME = "Zbigniew^Sekretny"  # a fixture literal that must never appear in a Diagnostic


def _build_fixture() -> bytes:
    """Root Modality/PatientName/SpecificCharacterSet(ISO_IR 100), plus a
    3-Item BeamSequence: Item 0 has BeamName="AAAA" (existing, even-length --
    update-branch target for raw-mutation-failure/atomicity tests), Item 1
    has BeamName="BBBB", Item 2 has BeamName absent (mixed existing/missing,
    matching test_ensure_and_text.py's own fixture shape). Pixel Data last,
    for non-interference."""
    item0 = _dicom_item(_element_short(*_TAG_BEAM_NAME, "LO", b"AAAA"))
    item1 = _dicom_item(_element_short(*_TAG_BEAM_NAME, "LO", b"BBBB"))
    item2 = _dicom_item(b"")
    dataset = (
        _element_short(*_TAG_MODALITY, "CS", b"CT")
        + _element_short(*_TAG_CHARSET, "CS", b"ISO_IR 100")
        + _element_short(*_TAG_PATIENT_NAME, "PN", _SENSITIVE_NAME.encode("ascii"))
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


def _all_diagnostic_strings(result) -> str:
    """Flattens every Diagnostic field across a PolicyResult (or a bare
    tuple of OperationResult/Diagnostic) into one string, for a mechanical
    privacy sweep."""
    diagnostics = result.diagnostics if hasattr(result, "diagnostics") else result
    parts = []
    for d in diagnostics:
        parts.append(repr(d))
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Basic result-shape qualification (qualification items 2-8)
# ---------------------------------------------------------------------------

class ResultShapeTest(unittest.TestCase):
    def setUp(self):
        self.structure = fds.read_buffer(_build_fixture(), fidelity="lossless")

    def tearDown(self):
        self.structure.close()

    def test_require_satisfied(self):
        result = policy.Require(_TAG_MODALITY).apply(self.structure)
        self.assertEqual(result.execution, policy.ExecutionStatus.COMPLETED)
        self.assertTrue(result.satisfied)
        self.assertEqual(result.diagnostics, ())

    def test_require_unsatisfied_standalone(self):
        result = policy.Require((0x0099, 0x0099)).apply(self.structure)
        self.assertEqual(result.execution, policy.ExecutionStatus.COMPLETED)
        self.assertFalse(result.satisfied)
        self.assertEqual(len(result.diagnostics), 1)
        self.assertEqual(result.diagnostics[0].code, "REQUIREMENT_UNSATISFIED")

    def test_require_unsatisfied_via_policy_rejects_and_marks_later_not_executed(self):
        pol = policy.Policy(
            name="t", version="1.0",
            operations=(policy.Require((0x0099, 0x0099)), policy.Remove(_TAG_MODALITY)),
        )
        result = policy.apply(self.structure, pol)
        self.assertEqual(result.decision, policy.Decision.REJECT)
        self.assertEqual(result.execution, policy.PolicyExecutionStatus.REJECTED)
        self.assertEqual(result.operations[0].execution, policy.ExecutionStatus.COMPLETED)
        self.assertFalse(result.operations[0].satisfied)
        self.assertEqual(result.operations[1].execution, policy.ExecutionStatus.NOT_EXECUTED)
        self.assertIsNone(result.operations[1].satisfied)  # not False -- never evaluated
        self.assertEqual(result.failed_requirement, (0x0099, 0x0099))

    def test_remove_zero_matches_is_clean_no_op(self):
        result = policy.Remove((0x0099, 0x0099)).apply(self.structure)
        self.assertEqual(result.execution, policy.ExecutionStatus.COMPLETED)
        self.assertIsNone(result.satisfied)
        self.assertEqual(result.count, 0)
        self.assertEqual(result.diagnostics, ())

    def test_replace_successful(self):
        result = policy.Replace(_TAG_MODALITY, b"MR").apply(self.structure)
        self.assertEqual(result.execution, policy.ExecutionStatus.COMPLETED)
        self.assertIsNone(result.satisfied)
        self.assertEqual(result.count, 1)

    def test_ensure_root_insertion(self):
        result = policy.Ensure((0x0012, 0x0062), b"YES").apply(self.structure)
        self.assertEqual(result.execution, policy.ExecutionStatus.COMPLETED)
        self.assertTrue(result.satisfied)
        self.assertEqual(result.updated_count, 0)
        self.assertEqual(result.inserted_count, 1)
        self.assertEqual(result.count, 1)

    def test_ensure_mixed_update_and_insert_split_counts(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NAME)
        result = policy.Ensure(locator, b"MARK").apply(self.structure)
        self.assertEqual(result.count, 3)
        self.assertEqual(result.updated_count, 2)   # items 0, 1 existed
        self.assertEqual(result.inserted_count, 1)  # item 2 didn't

    def test_ensure_zero_insertion_sites(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep((0x0099, 0x0099), 0),), tag=(0x0001, 0x0001))
        result = policy.Ensure(locator, b"X").apply(self.structure)
        self.assertEqual(result.execution, policy.ExecutionStatus.COMPLETED)
        self.assertFalse(result.satisfied)
        self.assertEqual(result.count, 0)
        self.assertEqual(result.updated_count, 0)
        self.assertEqual(result.inserted_count, 0)
        self.assertEqual(len(result.diagnostics), 1)
        self.assertEqual(result.diagnostics[0].code, "GUARANTEE_UNESTABLISHED")

    def test_ensure_zero_sites_visible_at_policy_level(self):
        """Reproduces the exact S1.3 design-checkpoint Finding 2 scenario
        and proves the new model resolves it: the diagnostic is now visible
        in PolicyResult.diagnostics even though the Policy continues
        (decision stays ACCEPT, per the checkpoint's own preserved
        recommendation that GUARANTEE_UNESTABLISHED does not reject)."""
        locator = policy.PathLocator(steps=(policy.LocatorStep((0x0099, 0x0099), 0),), tag=(0x0001, 0x0001))
        pol = policy.Policy(
            name="t", version="1.0",
            operations=(policy.Ensure(locator, b"X"), policy.Remove((0x0099, 0x0098))),
        )
        result = policy.apply(self.structure, pol)
        self.assertEqual(result.decision, policy.Decision.ACCEPT)  # Policy continues
        self.assertEqual(result.execution, policy.PolicyExecutionStatus.COMPLETED)
        self.assertEqual(len(result.diagnostics), 1)
        self.assertEqual(result.diagnostics[0].code, "GUARANTEE_UNESTABLISHED")


# ---------------------------------------------------------------------------
# Correction 1 -- raw Replace callback atomicity
# ---------------------------------------------------------------------------

class ReplaceAtomicityTest(unittest.TestCase):
    def setUp(self):
        self.structure = fds.read_buffer(_build_fixture(), fidelity="lossless")

    def tearDown(self):
        self.structure.close()

    def test_direct_call_rolls_back_and_raises_callback_error(self):
        before0 = self.structure.find([(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_NAME, None)]).value
        before1 = self.structure.find([(_TAG_BEAM_SEQ, 1), (_TAG_BEAM_NAME, None)]).value
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NAME)

        def cb(v):
            if v == before1:
                raise ValueError("boom")
            return b"ZZZZ"

        with self.assertRaises(policy.CallbackError) as ctx:
            policy.Replace(locator, cb).apply(self.structure)
        self.assertEqual(ctx.exception.cause_type, "ValueError")

        after0 = self.structure.find([(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_NAME, None)]).value
        after1 = self.structure.find([(_TAG_BEAM_SEQ, 1), (_TAG_BEAM_NAME, None)]).value
        self.assertEqual(after0, before0, "site 0's successful mutation must be exactly rolled back")
        self.assertEqual(after1, before1)

    def test_policy_apply_reports_callback_failed_rolled_back(self):
        before0 = self.structure.find([(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_NAME, None)]).value
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NAME)

        def cb(v):
            if v == b"BBBB":
                raise ValueError("boom")
            return b"ZZZZ"

        pol = policy.Policy(name="t", version="1.0", operations=(policy.Replace(locator, cb),))
        result = policy.apply(self.structure, pol)

        self.assertEqual(result.execution, policy.PolicyExecutionStatus.PARTIAL)
        self.assertEqual(result.decision, policy.Decision.PARTIAL)
        op = result.operations[0]
        self.assertEqual(op.execution, policy.ExecutionStatus.ROLLED_BACK)
        self.assertEqual(op.count, 0)
        self.assertEqual(len(op.diagnostics), 1)
        self.assertEqual(op.diagnostics[0].code, "CALLBACK_FAILED")
        self.assertEqual(op.diagnostics[0].cause_type, "ValueError")
        self.assertNotIn("boom", repr(op.diagnostics[0]))  # original message never copied

        after0 = self.structure.find([(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_NAME, None)]).value
        self.assertEqual(after0, before0)

    def test_callback_fails_before_any_site_mutation_is_failed_not_rolled_back(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NAME)

        def cb(v):
            raise ValueError("fails immediately on the first site")

        pol = policy.Policy(name="t", version="1.0", operations=(policy.Replace(locator, cb),))
        result = policy.apply(self.structure, pol)
        self.assertEqual(result.operations[0].execution, policy.ExecutionStatus.FAILED)
        self.assertEqual(result.operations[0].diagnostics[0].code, "CALLBACK_FAILED")


# ---------------------------------------------------------------------------
# Correction 2 -- raw Replace set_value(False) is a real failure
# ---------------------------------------------------------------------------

class ReplaceMutationFailureTest(unittest.TestCase):
    def setUp(self):
        self.structure = fds.read_buffer(_build_fixture(), fidelity="lossless")

    def tearDown(self):
        self.structure.close()

    def test_set_value_false_raises_mutation_failed_not_silent_undercount(self):
        oversized = b"X" * 70000  # exceeds Short16's max length -> set_value returns False
        with self.assertRaises(policy._MutationFailed):
            policy.Replace(_TAG_MODALITY, oversized).apply(self.structure)
        # Not silently under-counted: no OperationResult was even returned (it raised).
        self.assertEqual(self.structure.get(_TAG_MODALITY).value, b"CT")  # unchanged

    def test_no_prior_mutation_is_failed(self):
        oversized = b"X" * 70000
        pol = policy.Policy(name="t", version="1.0", operations=(policy.Replace(_TAG_MODALITY, oversized),))
        result = policy.apply(self.structure, pol)
        self.assertEqual(result.operations[0].execution, policy.ExecutionStatus.FAILED)
        self.assertEqual(result.operations[0].diagnostics[0].code, "MUTATION_FAILED")
        self.assertEqual(result.operations[0].count, 0)

    def test_earlier_site_mutation_is_rolled_back(self):
        oversized = b"X" * 70000
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NAME)
        before0 = self.structure.find([(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_NAME, None)]).value

        def cb(v):
            return b"ZZZZ" if v == b"AAAA" else oversized

        pol = policy.Policy(name="t", version="1.0", operations=(policy.Replace(locator, cb),))
        result = policy.apply(self.structure, pol)
        self.assertEqual(result.operations[0].execution, policy.ExecutionStatus.ROLLED_BACK)
        self.assertEqual(result.operations[0].diagnostics[0].code, "MUTATION_FAILED")
        after0 = self.structure.find([(_TAG_BEAM_SEQ, 0), (_TAG_BEAM_NAME, None)]).value
        self.assertEqual(after0, before0)


# ---------------------------------------------------------------------------
# Diagnostic code coverage -- one real trigger per reachable code
# ---------------------------------------------------------------------------

class DiagnosticCodeCoverageTest(unittest.TestCase):
    def setUp(self):
        self.structure = fds.read_buffer(_build_fixture(), fidelity="lossless")

    def tearDown(self):
        self.structure.close()

    def _apply_and_get_code(self, operation):
        pol = policy.Policy(name="t", version="1.0", operations=(operation,))
        result = policy.apply(self.structure, pol)
        return result.operations[0].diagnostics[0].code, result.operations[0].execution

    def test_vr_required(self):
        code, execution = self._apply_and_get_code(policy.Ensure(_TAG_AMBIGUOUS, b"\x01\x00", vr=None))
        self.assertEqual(code, "VR_REQUIRED")
        self.assertEqual(execution, policy.ExecutionStatus.FAILED)

    def test_text_operation_unsupported(self):
        code, execution = self._apply_and_get_code(policy.ReplaceText(_TAG_CHARSET, "ISO_IR 192"))
        self.assertEqual(code, "TEXT_OPERATION_UNSUPPORTED")
        self.assertEqual(execution, policy.ExecutionStatus.FAILED)

    def test_character_unrepresentable(self):
        # Root declares ISO_IR 100 (Latin1); a Cyrillic-only character is
        # not representable there.
        code, execution = self._apply_and_get_code(policy.ReplaceText(_TAG_PATIENT_NAME, "Рей"))
        self.assertEqual(code, "CHARACTER_UNREPRESENTABLE")
        self.assertEqual(execution, policy.ExecutionStatus.FAILED)

    def test_mutation_failed(self):
        oversized = b"X" * 70000
        code, execution = self._apply_and_get_code(policy.Replace(_TAG_MODALITY, oversized))
        self.assertEqual(code, "MUTATION_FAILED")
        self.assertEqual(execution, policy.ExecutionStatus.FAILED)

    def test_callback_failed(self):
        def cb(v):
            raise RuntimeError("boom")
        code, execution = self._apply_and_get_code(policy.Replace(_TAG_MODALITY, cb, recursive=False))
        self.assertEqual(code, "CALLBACK_FAILED")
        self.assertEqual(execution, policy.ExecutionStatus.FAILED)

    def test_requirement_unsatisfied(self):
        code, execution = self._apply_and_get_code(policy.Require((0x0099, 0x0099)))
        self.assertEqual(code, "REQUIREMENT_UNSATISFIED")
        self.assertEqual(execution, policy.ExecutionStatus.COMPLETED)  # not a failure

    def test_guarantee_unestablished(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep((0x0099, 0x0099), 0),), tag=(0x0001, 0x0001))
        code, execution = self._apply_and_get_code(policy.Ensure(locator, b"X"))
        self.assertEqual(code, "GUARANTEE_UNESTABLISHED")
        self.assertEqual(execution, policy.ExecutionStatus.COMPLETED)  # not a failure

    def test_invalid_unicode_is_not_reachable_from_python_str_input(self):
        """Documented, not fabricated: A1.7's own freeze report (section 21)
        states InvalidUnicodeInputError "is not reachable via the str-based
        Python surface as built," because a Python str passed through
        .encode("utf-8") cannot itself produce malformed UTF-8 bytes. This
        test records that INVALID_UNICODE's code path exists and is
        documented in DIAGNOSTIC_CODES, but is not independently triggerable
        here -- exactly the same limitation attrs' own Python binding
        already has, not a new S1.3 gap."""
        self.assertIn("INVALID_UNICODE", policy.DIAGNOSTIC_CODES)

    def test_already_exists_is_not_reachable_through_normal_ensure_use(self):
        """Documented, not fabricated: _resolve_insertion_sites's own
        exists=False check and insert()'s full-container duplicate check
        should always agree (both use the same underlying find/scan), so
        AlreadyExistsError has no natural trigger through Ensure/EnsureText's
        own normal flow. Kept in DIAGNOSTIC_CODES for defensive completeness
        (Policy.apply() would still classify it correctly if it somehow
        occurred), not claimed as a common case."""
        self.assertIn("ALREADY_EXISTS", policy.DIAGNOSTIC_CODES)


# ---------------------------------------------------------------------------
# RollbackError boundary -- never converted into an ordinary PolicyResult
# ---------------------------------------------------------------------------

class RollbackErrorBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.structure = fds.read_buffer(_build_fixture(), fidelity="lossless")

    def tearDown(self):
        self.structure.close()

    def test_rollback_error_propagates_through_policy_apply(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NAME)
        real_set_value = fastdicomattrs.Structure.set_value
        calls = {"n": 0}

        def flaky(self, path, value):
            calls["n"] += 1
            if calls["n"] == 1:
                return real_set_value(self, path, value)  # site 0 forward: succeeds
            if calls["n"] == 2:
                return False  # site 1 forward: fails, triggers rollback
            return False  # site 0's own rollback attempt: forced to fail too

        pol = policy.Policy(name="t", version="1.0", operations=(policy.Replace(locator, b"ZZZZ"),))
        with mock.patch.object(fastdicomattrs.Structure, "set_value", flaky):
            with self.assertRaises(policy.RollbackError):
                policy.apply(self.structure, pol)

    def test_unrecognized_exception_propagates_through_policy_apply(self):
        class _BespokeOperation(policy.PolicyOperation):
            def apply(self, structure):
                raise KeyError("not a recognized policy-execution failure")

        # Register a synthetic kind mapping so Policy.apply's bookkeeping
        # (which only runs after the exception, for NOT_EXECUTED placeholders)
        # would work if it got that far -- it must not, since KeyError is
        # unrecognized and must propagate before any placeholder is built.
        pol = policy.Policy(name="t", version="1.0", operations=(_BespokeOperation(),))
        with self.assertRaises(KeyError):
            policy.apply(self.structure, pol)


# ---------------------------------------------------------------------------
# Freeze-critical: three-operation Policy -- operation atomicity + whole-
# policy non-atomicity + complete result visibility, all at once
# ---------------------------------------------------------------------------

class ThreeOperationPolicyTest(unittest.TestCase):
    def setUp(self):
        self.structure = fds.read_buffer(_build_fixture(), fidelity="lossless")

    def tearDown(self):
        self.structure.close()

    def test_op1_committed_op2_rolled_back_op3_not_executed(self):
        op1 = policy.Ensure((0x0012, 0x0062), b"YES")           # will succeed
        op2 = policy.Ensure(_TAG_AMBIGUOUS, b"\x01\x00", vr=None)  # will fail: VR required
        op3 = policy.Ensure((0x0012, 0x0063), b"SHOULD-NOT-RUN")   # would succeed if it ran

        pol = policy.Policy(name="three-op", version="1.0", operations=(op1, op2, op3))
        result = policy.apply(self.structure, pol)

        self.assertEqual(result.execution, policy.PolicyExecutionStatus.PARTIAL)
        self.assertEqual(result.decision, policy.Decision.PARTIAL)
        self.assertEqual(len(result.operations), 3)

        self.assertEqual(result.operations[0].execution, policy.ExecutionStatus.COMPLETED)
        self.assertEqual(result.operations[1].execution, policy.ExecutionStatus.FAILED)
        self.assertEqual(result.operations[1].diagnostics[0].code, "VR_REQUIRED")
        self.assertEqual(result.operations[2].execution, policy.ExecutionStatus.NOT_EXECUTED)

        # op1's mutation remains; op3 never touched the structure.
        self.assertEqual(self.structure.get((0x0012, 0x0062)).value, b"YES ")
        self.assertIsNone(self.structure.get((0x0012, 0x0063)))

        # Exactly one diagnostic, for op2, correctly indexed.
        self.assertEqual(len(result.diagnostics), 1)
        self.assertEqual(result.diagnostics[0].operation_index, 1)


# ---------------------------------------------------------------------------
# Differential test: three cases the OLD (S1.2) model conflated
# ---------------------------------------------------------------------------

class DifferentialConflationTest(unittest.TestCase):
    def setUp(self):
        self.structure = fds.read_buffer(_build_fixture(), fidelity="lossless")

    def tearDown(self):
        self.structure.close()

    def test_zero_matches_vs_zero_sites_vs_modeled_failure_are_structurally_distinct(self):
        # A. Remove resolves zero targets.
        result_a = policy.Remove((0x0099, 0x0099)).apply(self.structure)
        self.assertEqual(result_a.execution, policy.ExecutionStatus.COMPLETED)
        self.assertIsNone(result_a.satisfied)
        self.assertEqual(result_a.diagnostics, ())

        # B. Ensure has zero insertion sites.
        locator = policy.PathLocator(steps=(policy.LocatorStep((0x0099, 0x0099), 0),), tag=(0x0001, 0x0001))
        result_b = policy.Ensure(locator, b"X").apply(self.structure)
        self.assertEqual(result_b.execution, policy.ExecutionStatus.COMPLETED)
        self.assertFalse(result_b.satisfied)
        self.assertEqual(result_b.diagnostics[0].code, "GUARANTEE_UNESTABLISHED")

        # C. Ensure/Replace hits a modeled mutation failure.
        pol_c = policy.Policy(
            name="t", version="1.0",
            operations=(policy.Ensure(_TAG_AMBIGUOUS, b"\x01\x00", vr=None),),
        )
        result_c = policy.apply(self.structure, pol_c)
        self.assertIn(result_c.operations[0].execution,
                      (policy.ExecutionStatus.FAILED, policy.ExecutionStatus.ROLLED_BACK))
        self.assertTrue(result_c.operations[0].diagnostics)

        # All three distinguishable by structured fields alone -- no
        # exception-message parsing, no inspection of mutated Structure.
        self.assertNotEqual((result_a.execution, result_a.satisfied),
                             (result_b.execution, result_b.satisfied))
        self.assertNotEqual(result_b.diagnostics[0].code if result_b.diagnostics else None,
                             result_c.operations[0].diagnostics[0].code)


# ---------------------------------------------------------------------------
# Privacy / PHI
# ---------------------------------------------------------------------------

class PrivacyTest(unittest.TestCase):
    def setUp(self):
        self.structure = fds.read_buffer(_build_fixture(), fidelity="lossless")

    def tearDown(self):
        self.structure.close()

    def test_no_diagnostic_leaks_the_sensitive_fixture_literal(self):
        """Triggers every reachable diagnostic code against a fixture
        carrying a known sensitive literal (_SENSITIVE_NAME, the fixture's
        own PatientName) and proves that literal never appears in any
        produced Diagnostic's string representation -- a mechanical,
        code-independent privacy sweep, not a per-field assumption."""
        results = []
        results.append(policy.Require((0x0099, 0x0099)).apply(self.structure))
        locator = policy.PathLocator(steps=(policy.LocatorStep((0x0099, 0x0099), 0),), tag=(0x0001, 0x0001))
        results.append(policy.Ensure(locator, b"X").apply(self.structure))

        pol = policy.Policy(
            name="t", version="1.0",
            operations=(policy.Ensure(_TAG_AMBIGUOUS, b"\x01\x00", vr=None),),
        )
        policy_result = policy.apply(self.structure, pol)

        def cb(v):
            raise ValueError(f"leaked value would be {v!r}")  # deliberately tries to leak

        pol2 = policy.Policy(name="t2", version="1.0",
                             operations=(policy.Replace(_TAG_PATIENT_NAME, cb, recursive=False),))
        policy_result2 = policy.apply(self.structure, pol2)

        haystacks = [_all_diagnostic_strings(r) for r in results]
        haystacks.append(_all_diagnostic_strings(policy_result))
        haystacks.append(_all_diagnostic_strings(policy_result2))
        combined = " ".join(haystacks)

        self.assertNotIn(_SENSITIVE_NAME, combined)
        self.assertNotIn(_SENSITIVE_NAME.encode("ascii").hex(), combined)
        self.assertNotIn("leaked value would be", combined)  # the callback's own message text


# ---------------------------------------------------------------------------
# Explicit/Implicit equivalence at the diagnostic level
# ---------------------------------------------------------------------------

class EncodingEquivalenceTest(unittest.TestCase):
    def _build_explicit(self) -> bytes:
        dataset = (
            _element_short(*_TAG_MODALITY, "CS", b"CT")
            + _element_short(*_TAG_CHARSET, "CS", b"ISO_IR 100")
        )
        return b"\x00" * 128 + b"DICM" + _file_meta(b"1.2.840.10008.1.2.1") + dataset

    def _build_implicit(self) -> bytes:
        dataset = (
            _element_implicit(*_TAG_MODALITY, b"CT")
            + _element_implicit(*_TAG_CHARSET, b"ISO_IR 100")
        )
        return b"\x00" * 128 + b"DICM" + _file_meta(b"1.2.840.10008.1.2") + dataset

    def test_same_semantic_failure_produces_same_diagnostic_code(self):
        explicit = fds.read_buffer(self._build_explicit(), fidelity="lossless")
        implicit = fds.read_buffer(self._build_implicit(), fidelity="lossless")
        try:
            # Same ambiguous-VR insertion attempt against both encodings.
            pol = policy.Policy(
                name="t", version="1.0",
                operations=(policy.Ensure(_TAG_AMBIGUOUS, b"\x01\x00", vr=None),),
            )
            result_e = policy.apply(explicit, pol)
            result_i = policy.apply(implicit, pol)
            self.assertEqual(result_e.operations[0].diagnostics[0].code,
                              result_i.operations[0].diagnostics[0].code)
            self.assertEqual(result_e.operations[0].execution, result_i.operations[0].execution)
        finally:
            explicit.close()
            implicit.close()


# ---------------------------------------------------------------------------
# Non-interference (successful and failed policy execution)
# ---------------------------------------------------------------------------

class NonInterferenceTest(unittest.TestCase):
    _PIXEL_DATA_ENCODING = _element_long(*_TAG_PIXEL_DATA, "OB", b"\xAA\xBB\xCC\xDD")

    def setUp(self):
        self.structure = fds.read_buffer(_build_fixture(), fidelity="lossless")

    def tearDown(self):
        self.structure.close()

    def _assert_pixel_data_untouched(self):
        tail = self.structure.write_bytes()[-len(self._PIXEL_DATA_ENCODING):]
        self.assertEqual(tail, self._PIXEL_DATA_ENCODING)

    def test_partial_policy_execution_preserves_unrelated_elements_and_pixel_data(self):
        modality_before = self.structure.get(_TAG_MODALITY).value
        pol = policy.Policy(
            name="t", version="1.0",
            operations=(policy.Ensure(_TAG_AMBIGUOUS, b"\x01\x00", vr=None),),
        )
        result = policy.apply(self.structure, pol)
        self.assertEqual(result.execution, policy.PolicyExecutionStatus.PARTIAL)
        self.assertEqual(self.structure.get(_TAG_MODALITY).value, modality_before)
        self._assert_pixel_data_untouched()


# ---------------------------------------------------------------------------
# Independent validation
# ---------------------------------------------------------------------------

class IndependentValidationTest(unittest.TestCase):
    def test_pydicom_confirms_successful_multi_operation_policy_output(self):
        try:
            import pydicom
            import io
        except ImportError:
            self.skipTest("pydicom not available in this environment")

        structure = fds.read_buffer(_build_fixture(), fidelity="lossless")
        try:
            pol = policy.Policy(
                name="successful-multi-op", version="1.0",
                operations=(
                    policy.Require(_TAG_MODALITY),
                    policy.ReplaceText(_TAG_PATIENT_NAME, "Anonymous"),
                    policy.EnsureText((0x0012, 0x0063), "fastDICOMstructure policy X"),
                ),
            )
            result = policy.apply(structure, pol)
            self.assertEqual(result.execution, policy.PolicyExecutionStatus.COMPLETED)
            self.assertEqual(result.decision, policy.Decision.TRANSFORM)
            output = structure.write_bytes()
        finally:
            structure.close()

        _reparse_cleanly(output)
        ds = pydicom.dcmread(io.BytesIO(output))
        self.assertEqual(str(ds.PatientName), "Anonymous")
        self.assertEqual(str(ds[(0x0012, 0x0063)].value), "fastDICOMstructure policy X")
        self.assertEqual(ds.Modality, "CT")

    def test_dcmtk_dcmdump_confirms_successful_multi_operation_policy_output(self):
        import shutil
        import subprocess
        import tempfile

        dcmdump = shutil.which("dcmdump")
        if dcmdump is None:
            self.skipTest("dcmdump (DCMTK) not available in this environment")

        structure = fds.read_buffer(_build_fixture(), fidelity="lossless")
        try:
            pol = policy.Policy(
                name="successful-multi-op", version="1.0",
                operations=(
                    policy.Require(_TAG_MODALITY),
                    policy.ReplaceText(_TAG_PATIENT_NAME, "Anonymous"),
                ),
            )
            result = policy.apply(structure, pol)
            self.assertEqual(result.execution, policy.PolicyExecutionStatus.COMPLETED)
            output = structure.write_bytes()
        finally:
            structure.close()

        _reparse_cleanly(output)
        with tempfile.NamedTemporaryFile(suffix=".dcm") as f:
            f.write(output)
            f.flush()
            result = subprocess.run([dcmdump, f.name], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Anonymous", result.stdout)


# ---------------------------------------------------------------------------
# Performance -- detect pathological regression only
# ---------------------------------------------------------------------------

class PerformanceTest(unittest.TestCase):
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

    def test_successful_multi_operation_policy_is_fast(self):
        pol = policy.Policy(
            name="t", version="1.0",
            operations=(
                policy.Require(_TAG_MODALITY),
                policy.Remove((0x0099, 0x0099)),
                policy.Replace(_TAG_MODALITY, b"MR"),
            ),
        )
        start = time.perf_counter()
        result = policy.apply(self.structure, pol)
        elapsed = time.perf_counter() - start
        self.assertEqual(result.execution, policy.PolicyExecutionStatus.COMPLETED)
        self.assertLess(elapsed, 1.0)

    def test_wildcard_replace_over_1000_items_is_reasonably_fast(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_NAME)
        start = time.perf_counter()
        result = policy.Replace(locator, b"MARK").apply(self.structure)
        elapsed = time.perf_counter() - start
        self.assertEqual(result.count, self._item_count)
        self.assertLess(elapsed, 10.0)

    def test_wildcard_ensure_over_1000_items_is_reasonably_fast(self):
        locator = policy.PathLocator(steps=(policy.LocatorStep(_TAG_BEAM_SEQ, "*"),), tag=_TAG_BEAM_DESCRIPTION)
        start = time.perf_counter()
        result = policy.Ensure(locator, b"MARK").apply(self.structure)
        elapsed = time.perf_counter() - start
        self.assertEqual(result.count, self._item_count)
        self.assertLess(elapsed, 10.0)


# ---------------------------------------------------------------------------
# JSON-authorability (design proof only -- no JSON loader/schema)
# ---------------------------------------------------------------------------

class JSONAuthorabilityTest(unittest.TestCase):
    """Proves the recommended Result/Diagnostic shapes are already
    JSON-serializable as plain dataclasses -- a design proof, not a
    committed schema, mirroring S1.1/S1.2's own JSON-authorability probes."""

    def setUp(self):
        self.structure = fds.read_buffer(_build_fixture(), fidelity="lossless")

    def tearDown(self):
        self.structure.close()

    def test_policy_result_round_trips_through_json_losslessly_as_plain_data(self):
        pol = policy.Policy(
            name="t", version="1.0",
            operations=(policy.Ensure(_TAG_AMBIGUOUS, b"\x01\x00", vr=None),),
        )
        result = policy.apply(self.structure, pol)

        def _to_jsonable(obj):
            if hasattr(obj, "value") and isinstance(obj, (policy.Decision, policy.ExecutionStatus,
                                                           policy.PolicyExecutionStatus)):
                return obj.value
            if hasattr(obj, "__dataclass_fields__"):
                return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
            if isinstance(obj, tuple):
                return [_to_jsonable(v) for v in obj]
            return obj

        # asdict() already recurses into nested dataclasses/tuples, but
        # Decision/ExecutionStatus/PolicyExecutionStatus are str Enums --
        # asdict() leaves them as Enum instances, not plain str, so convert
        # explicitly before handing to json.dumps.
        raw = asdict(result)
        raw["decision"] = result.decision.value
        raw["execution"] = result.execution.value
        for i, op in enumerate(raw["operations"]):
            op["execution"] = result.operations[i].execution.value

        text = json.dumps(raw)
        reloaded = json.loads(text)
        self.assertEqual(reloaded["execution"], "partial")
        self.assertEqual(reloaded["operations"][0]["diagnostics"][0]["code"], "VR_REQUIRED")
        self.assertEqual(reloaded["policy_name"], "t")


if __name__ == "__main__":
    unittest.main()
