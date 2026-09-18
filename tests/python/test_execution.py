"""Qualification for S1.5 (Execution Core + Filesystem Adapter Proof):
execute_one/run semantics, the persistence gate (Correction 1), the absence
of any execution-identity field (Correction 2), the execute_one/run scope
separation (Correction 3), the seven-outcome failure taxonomy, the
RollbackError/unexpected-exception boundaries, filesystem adapter safety
(including race-safe no-overwrite publication), security/privacy, and
real-DICOM validation.

Byte-fixture-building style mirrors tests/python/test_result_diagnostic.py
and tests/python/test_configuration.py (duplicated locally, following those
files' own stated convention).
"""

import io
import os
import struct
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

import fastdicomstructure as fds  # noqa: E402
from fastdicomstructure import policy  # noqa: E402
from fastdicomstructure import configuration as cfg  # noqa: E402
from fastdicomstructure import execution  # noqa: E402
from fastdicomstructure import adapters  # noqa: E402
from fastdicomstructure.adapters import filesystem as fs_adapters  # noqa: E402

import fastdicomattrs  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture building
# ---------------------------------------------------------------------------

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


def _element_implicit(group, element, value: bytes) -> bytes:
    if len(value) % 2 != 0:
        value += b"\x00"
    return _tag(group, element) + _u32(len(value)) + value


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
_TAG_PATIENT_ID = (0x0010, 0x0020)
_TAG_AMBIGUOUS = (0x0028, 0x0106)  # SmallestImagePixelValue -- "US or SS", ambiguous -> VR_REQUIRED
_TAG_OTHER_PATIENT_IDS_SEQ = (0x0010, 0x1002)  # for a multi-site rollback probe

_SENSITIVE_NAME = "Zbigniew^Sekretny^SSN-123-45-6789"  # must never leak into any diagnostic


def _element_sq(group, element, item_bytes: bytes) -> bytes:
    return _tag(group, element) + b"SQ" + b"\x00\x00" + _u32(len(item_bytes)) + item_bytes


def _element_sq_implicit(group, element, item_bytes: bytes) -> bytes:
    return _tag(group, element) + _u32(len(item_bytes)) + item_bytes


def _dicom_item(content: bytes) -> bytes:
    return _tag(0xFFFE, 0xE000) + _u32(len(content)) + content


def _build_fixture(explicit: bool = True, patient_name: bytes = None) -> bytes:
    elem = _element_short if explicit else (lambda g, e, vr, v: _element_implicit(g, e, v))
    sq = _element_sq if explicit else _element_sq_implicit
    ts = b"1.2.840.10008.1.2.1" if explicit else b"1.2.840.10008.1.2"
    name = patient_name if patient_name is not None else _SENSITIVE_NAME.encode("ascii")
    item0 = _dicom_item(elem(*_TAG_PATIENT_ID, "LO", b"AAA"))
    item1 = _dicom_item(elem(*_TAG_PATIENT_ID, "LO", b"BBB"))
    dataset = (
        elem(*_TAG_MODALITY, "CS", b"CT")
        + elem(*_TAG_CHARSET, "CS", b"ISO_IR 100")
        + elem(*_TAG_PATIENT_ID, "LO", b"12345")
        + elem(*_TAG_PATIENT_NAME, "PN", name)
        + sq(*_TAG_OTHER_PATIENT_IDS_SEQ, item0 + item1)
    )
    return b"\x00" * 128 + b"DICM" + _file_meta(ts) + dataset


def _accept_and_anonymize_policy() -> policy.Policy:
    return policy.Policy(
        name="probe-policy", version="1.0",
        operations=(
            policy.Require(_TAG_PATIENT_ID),
            policy.ReplaceText(_TAG_PATIENT_NAME, "ANONYMIZED"),
        ),
    )


def _rejecting_policy() -> policy.Policy:
    return policy.Policy(
        name="probe-policy", version="1.0",
        operations=(policy.Require((0x0008, 0x0099)),),  # never present
    )


def _partial_policy() -> policy.Policy:
    return policy.Policy(
        name="probe-policy", version="1.0",
        operations=(
            policy.Remove(_TAG_MODALITY),
            policy.Ensure(_TAG_AMBIGUOUS, b"\x01\x00", vr=None),  # VR_REQUIRED -> PARTIAL
        ),
    )


class _CountingDestination:
    """A destination test double -- never touches DICOM, only counts and
    optionally records calls, exactly matching the real adapter contract
    (bytes in, nothing out)."""

    def __init__(self, fail_with: Exception = None):
        self.calls = []
        self._fail_with = fail_with

    def write(self, data: bytes) -> None:
        self.calls.append(data)
        if self._fail_with is not None:
            raise self._fail_with


class _CountingSource:
    def __init__(self, data: bytes = None, fail_with: Exception = None):
        self._data = data
        self._fail_with = fail_with
        self.calls = 0

    def acquire(self) -> bytes:
        self.calls += 1
        if self._fail_with is not None:
            raise self._fail_with
        return self._data


def _reparse_cleanly(data: bytes) -> None:
    reparsed = fds.read_buffer(data, fidelity="lossless")
    try:
        blocking = [d for d in reparsed.diagnostics if d.severity != "info"]
        assert not blocking, f"output failed self-verification reparse: {blocking}"
    finally:
        reparsed.close()


# ---------------------------------------------------------------------------
# Probe A -- successful filesystem transformation
# ---------------------------------------------------------------------------

class ProbeATest(unittest.TestCase):
    def test_successful_filesystem_transformation(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.dcm")
            dst = os.path.join(d, "out.dcm")
            with open(src, "wb") as f:
                f.write(_build_fixture())

            source = fs_adapters.FilesystemSource({"path": src})
            destination = fs_adapters.FilesystemDestination({"path": dst})
            result = execution.run(source, _accept_and_anonymize_policy(), destination)

            self.assertEqual(result.outcome, execution.ExecutionOutcome.SUCCEEDED)
            self.assertEqual(result.policy_result.execution, policy.PolicyExecutionStatus.COMPLETED)
            self.assertEqual(result.policy_result.decision, policy.Decision.TRANSFORM)
            self.assertIsNotNone(result.output_bytes)
            self.assertIsNone(result.diagnostic)

            self.assertTrue(os.path.exists(dst))
            _reparse_cleanly(Path(dst).read_bytes())
            reparsed = fds.read(dst, fidelity="lossless")
            try:
                self.assertEqual(reparsed.decode_text(_TAG_PATIENT_NAME), ["ANONYMIZED"])
            finally:
                reparsed.close()


# ---------------------------------------------------------------------------
# Probe B -- acceptance rejection
# ---------------------------------------------------------------------------

class ProbeBTest(unittest.TestCase):
    def test_acceptance_rejection_skips_destination(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.dcm")
            dst = os.path.join(d, "out.dcm")
            original = _build_fixture()
            with open(src, "wb") as f:
                f.write(original)

            source = fs_adapters.FilesystemSource({"path": src})
            destination = _CountingDestination()
            result = execution.run(source, _rejecting_policy(), destination)

            self.assertEqual(result.outcome, execution.ExecutionOutcome.POLICY_REJECTED)
            self.assertEqual(result.policy_result.execution, policy.PolicyExecutionStatus.REJECTED)
            self.assertIsNone(result.output_bytes)
            self.assertIsNone(result.diagnostic)  # not duplicated -- PolicyResult already carries it
            self.assertEqual(len(result.policy_result.diagnostics), 1)
            self.assertEqual(result.policy_result.diagnostics[0].code, "REQUIREMENT_UNSATISFIED")

            self.assertEqual(destination.calls, [])  # never invoked
            self.assertFalse(os.path.exists(dst))
            self.assertEqual(Path(src).read_bytes(), original)  # source untouched


# ---------------------------------------------------------------------------
# Probe C -- malformed DICOM
# ---------------------------------------------------------------------------

class ProbeCTest(unittest.TestCase):
    def test_malformed_dicom_is_parse_failed(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.dcm")
            with open(src, "wb") as f:
                f.write(b"not a dicom file at all, contains " + _SENSITIVE_NAME.encode())

            source = fs_adapters.FilesystemSource({"path": src})
            destination = _CountingDestination()
            result = execution.run(source, _accept_and_anonymize_policy(), destination)

            self.assertEqual(result.outcome, execution.ExecutionOutcome.PARSE_FAILED)
            self.assertIsNone(result.policy_result)
            self.assertIsNone(result.output_bytes)
            self.assertEqual(result.diagnostic.code, "DICOM_PARSE_FAILED")
            # attrs' read_buffer is lenient for this input (a blocking
            # diagnostic, not a raised FdsError) -- cause_type is None,
            # not "FdsError"; see test_parse_failure_raises_fds_error below
            # for the raising case.
            self.assertIsNone(result.diagnostic.cause_type)
            self.assertNotIn(_SENSITIVE_NAME, result.diagnostic.message)
            self.assertEqual(destination.calls, [])

    def test_parse_failure_raises_fds_error(self):
        """A distinct scenario from the lenient-parse case above: an input
        attrs itself refuses outright (raises FdsError), not merely flags
        via .diagnostics -- an explicitly declared, wholly unsupported
        Transfer Syntax UID. Both are PARSE_FAILED; this one additionally
        carries a cause_type."""
        ts_uid = b"1.2.840.99999.1.1"  # not a real/supported transfer syntax
        group_body = (
            _element_short(0x0002, 0x0002, "UI", b"1.2.3.4")
            + _element_short(0x0002, 0x0003, "UI", b"1.2.3.4.5")
            + _element_short(0x0002, 0x0010, "UI", ts_uid)
        )
        file_meta = _element_short(0x0002, 0x0000, "UL", _u32(len(group_body))) + group_body
        data = b"\x00" * 128 + b"DICM" + file_meta + _element_short(*_TAG_MODALITY, "CS", b"CT")

        result = execution.execute_one(data, _accept_and_anonymize_policy())
        self.assertEqual(result.outcome, execution.ExecutionOutcome.PARSE_FAILED)
        self.assertEqual(result.diagnostic.code, "DICOM_PARSE_FAILED")
        self.assertEqual(result.diagnostic.cause_type, "FdsError")


# ---------------------------------------------------------------------------
# Probe D -- modeled policy failure (PARTIAL)
# ---------------------------------------------------------------------------

class ProbeDTest(unittest.TestCase):
    def test_modeled_policy_failure_skips_destination(self):
        data = _build_fixture()
        destination = _CountingDestination()
        source = _CountingSource(data=data)
        result = execution.run(source, _partial_policy(), destination)

        self.assertEqual(result.outcome, execution.ExecutionOutcome.POLICY_PARTIAL)
        self.assertEqual(result.policy_result.execution, policy.PolicyExecutionStatus.PARTIAL)
        self.assertIsNone(result.output_bytes)
        self.assertIsNone(result.diagnostic)  # PolicyResult remains the sole authority for cause
        self.assertEqual(result.policy_result.operations[1].diagnostics[0].code, "VR_REQUIRED")
        self.assertEqual(destination.calls, [])


# ---------------------------------------------------------------------------
# Probe E -- rollback failure / uncertain state
# ---------------------------------------------------------------------------

class ProbeETest(unittest.TestCase):
    def _flaky_policy_and_patch(self):
        # TagLocator(recursive=True) over _TAG_PATIENT_ID matches 3 sites in
        # the shared fixture (root, plus two nested under
        # _TAG_OTHER_PATIENT_IDS_SEQ) -- enough for "site 0 forward
        # succeeds, site 1 forward fails (triggers rollback), site 0's own
        # rollback attempt is forced to fail too", mirroring
        # tests/python/test_result_diagnostic.py's own proven RollbackError
        # technique exactly.
        locator = policy.TagLocator(_TAG_PATIENT_ID, recursive=True)
        pol = policy.Policy(name="t", version="1.0", operations=(policy.Replace(locator, b"ZZZZZZ"),))
        real_set_value = fastdicomattrs.Structure.set_value
        calls = {"n": 0}

        def flaky(self, path, value):
            calls["n"] += 1
            if calls["n"] == 1:
                return real_set_value(self, path, value)  # site 0 forward: succeeds
            if calls["n"] == 2:
                return False  # site 1 forward: fails, triggers rollback
            return False  # site 0's own rollback attempt: forced to fail too

        return pol, flaky

    def test_rollback_error_propagates_through_execute_one(self):
        data = _build_fixture()
        pol, flaky = self._flaky_policy_and_patch()
        with mock.patch.object(fastdicomattrs.Structure, "set_value", flaky):
            with self.assertRaises(policy.RollbackError):
                execution.execute_one(data, pol)

    def test_rollback_error_propagates_through_run_and_destination_never_invoked(self):
        data = _build_fixture()
        pol, flaky = self._flaky_policy_and_patch()
        source = _CountingSource(data=data)
        destination = _CountingDestination()
        with mock.patch.object(fastdicomattrs.Structure, "set_value", flaky):
            with self.assertRaises(policy.RollbackError):
                execution.run(source, pol, destination)
        self.assertEqual(destination.calls, [])  # no ExecutionResult was ever constructed


# ---------------------------------------------------------------------------
# Probe F -- destination failure
# ---------------------------------------------------------------------------

class ProbeFTest(unittest.TestCase):
    def test_destination_write_failure(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.dcm")
            original = _build_fixture()
            with open(src, "wb") as f:
                f.write(original)
            # A destination directory that does not exist -> mkstemp fails
            # -> DESTINATION_WRITE_FAILED, deterministically, portably.
            dst = os.path.join(d, "does-not-exist", "out.dcm")

            source = fs_adapters.FilesystemSource({"path": src})
            destination = fs_adapters.FilesystemDestination({"path": dst})
            result = execution.run(source, _accept_and_anonymize_policy(), destination)

            self.assertEqual(result.outcome, execution.ExecutionOutcome.DESTINATION_FAILED)
            self.assertEqual(result.policy_result.execution, policy.PolicyExecutionStatus.COMPLETED)
            self.assertIsNotNone(result.output_bytes)  # execute_one's own success is preserved
            self.assertEqual(result.diagnostic.code, "DESTINATION_WRITE_FAILED")
            self.assertEqual(Path(src).read_bytes(), original)  # source unaffected
            self.assertFalse(os.path.exists(dst))

    def test_destination_commit_failure_leaves_no_partial_target(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.dcm")
            with open(src, "wb") as f:
                f.write(_build_fixture())
            dst = os.path.join(d, "out.dcm")

            source = fs_adapters.FilesystemSource({"path": src})
            destination = fs_adapters.FilesystemDestination({"path": dst})
            with mock.patch("os.link", side_effect=OSError("simulated commit failure")):
                result = execution.run(source, _accept_and_anonymize_policy(), destination)

            self.assertEqual(result.outcome, execution.ExecutionOutcome.DESTINATION_FAILED)
            self.assertEqual(result.diagnostic.code, "DESTINATION_COMMIT_FAILED")
            self.assertFalse(os.path.exists(dst))  # no partial/failed file ever visible at target
            # no stray temp file left behind either
            self.assertEqual(list(Path(d).glob(".fds-tmp-*")), [])


# ---------------------------------------------------------------------------
# Probe G -- unsupported adapter type
# ---------------------------------------------------------------------------

class ProbeGTest(unittest.TestCase):
    def test_unsupported_adapter_type_rejected_before_acquisition(self):
        doc = {
            "schema": "fastdicomstructure-configuration", "schema_version": 1,
            "policy": {"name": "t", "version": "1.0"},
            "source": {"type": "future-adapter", "options": {}},
        }
        config = cfg.load_configuration(doc)  # S1.4 accepts the opaque envelope
        self.assertEqual(config.source.type, "future-adapter")

        with self.assertRaises(adapters.AdapterResolutionError) as ctx:
            adapters.resolve_source(config.source)
        self.assertEqual(ctx.exception.code, "ADAPTER_TYPE_UNKNOWN")
        # No ExecutionResult of any kind exists for this case -- it never
        # got far enough to acquire anything, let alone execute.


# ---------------------------------------------------------------------------
# Probe H -- direct bytes caller (deployment neutrality)
# ---------------------------------------------------------------------------

class ProbeHTest(unittest.TestCase):
    def test_direct_bytes_caller_matches_filesystem_path(self):
        data = _build_fixture()
        pol = _accept_and_anonymize_policy()

        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.dcm")
            dst = os.path.join(d, "out.dcm")
            with open(src, "wb") as f:
                f.write(data)
            source = fs_adapters.FilesystemSource({"path": src})
            destination = fs_adapters.FilesystemDestination({"path": dst})
            via_run = execution.run(source, pol, destination)

        direct = execution.execute_one(data, pol)  # no Configuration, no adapter of any kind

        self.assertEqual(direct.outcome, execution.ExecutionOutcome.SUCCEEDED)
        self.assertEqual(via_run.outcome, execution.ExecutionOutcome.SUCCEEDED)
        self.assertEqual(direct.output_bytes, via_run.output_bytes)
        self.assertEqual(direct.policy_result.decision, via_run.policy_result.decision)
        self.assertEqual(direct.policy_result.execution, via_run.policy_result.execution)


# ---------------------------------------------------------------------------
# Additional differential tests
# ---------------------------------------------------------------------------

class DifferentialTest(unittest.TestCase):
    def test_execute_one_matches_direct_policy_apply(self):
        data = _build_fixture()
        pol = _accept_and_anonymize_policy()

        structure = fds.read_buffer(data, fidelity="lossless")
        try:
            direct_result = policy.apply(structure, pol)
        finally:
            structure.close()

        via_execute_one = execution.execute_one(data, pol)
        self.assertEqual(via_execute_one.policy_result, direct_result)

    def test_run_delegates_to_execute_one_exactly_once(self):
        data = _build_fixture()
        pol = _accept_and_anonymize_policy()
        source = _CountingSource(data=data)
        destination = _CountingDestination()

        real_execute_one = execution.execute_one
        calls = []

        def spy(d, p):
            calls.append((d, p))
            return real_execute_one(d, p)

        with mock.patch.object(execution, "execute_one", side_effect=spy):
            result = execution.run(source, pol, destination)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], (data, pol))
        self.assertEqual(result.outcome, execution.ExecutionOutcome.SUCCEEDED)

    def test_destination_invocation_counts_across_outcomes(self):
        cases = [
            (_accept_and_anonymize_policy(), 1),
            (_rejecting_policy(), 0),
            (_partial_policy(), 0),
        ]
        for pol, expected_calls in cases:
            with self.subTest(policy=pol.name, expected=expected_calls):
                destination = _CountingDestination()
                source = _CountingSource(data=_build_fixture())
                execution.run(source, pol, destination)
                self.assertEqual(len(destination.calls), expected_calls)

        # rollback-exception case -> destination never invoked
        destination = _CountingDestination()
        pol_flaky, flaky = ProbeETest()._flaky_policy_and_patch()
        source = _CountingSource(data=_build_fixture())
        with mock.patch.object(fastdicomattrs.Structure, "set_value", flaky):
            with self.assertRaises(policy.RollbackError):
                execution.run(source, pol_flaky, destination)
        self.assertEqual(destination.calls, [])

    def test_serialization_not_called_for_rejected_partial_or_rollback(self):
        real_write_bytes = fastdicomattrs.Structure.write_bytes
        calls = {"n": 0}

        def counting(self):
            calls["n"] += 1
            return real_write_bytes(self)

        with mock.patch.object(fastdicomattrs.Structure, "write_bytes", counting):
            execution.execute_one(_build_fixture(), _rejecting_policy())
            execution.execute_one(_build_fixture(), _partial_policy())
        self.assertEqual(calls["n"], 0)

        pol_flaky, flaky = ProbeETest()._flaky_policy_and_patch()
        with mock.patch.object(fastdicomattrs.Structure, "write_bytes", counting), \
                mock.patch.object(fastdicomattrs.Structure, "set_value", flaky):
            with self.assertRaises(policy.RollbackError):
                execution.execute_one(_build_fixture(), pol_flaky)
        self.assertEqual(calls["n"], 0)

        with mock.patch.object(fastdicomattrs.Structure, "write_bytes", counting):
            result = execution.execute_one(_build_fixture(), _accept_and_anonymize_policy())
        self.assertEqual(calls["n"], 1)
        self.assertEqual(result.outcome, execution.ExecutionOutcome.SUCCEEDED)

    def test_unexpected_exception_propagates_not_converted_to_execution_result(self):
        class _BespokeOperation(policy.PolicyOperation):
            def apply(self, structure):
                raise KeyError("not a recognized policy-execution failure")

        pol = policy.Policy(name="t", version="1.0", operations=(_BespokeOperation(),))
        with self.assertRaises(KeyError):
            execution.execute_one(_build_fixture(), pol)

        source = _CountingSource(data=_build_fixture())
        destination = _CountingDestination()
        with self.assertRaises(KeyError):
            execution.run(source, pol, destination)
        self.assertEqual(destination.calls, [])


# ---------------------------------------------------------------------------
# Filesystem safety tests
# ---------------------------------------------------------------------------

class FilesystemSafetyTest(unittest.TestCase):
    def test_missing_source_is_source_failed(self):
        source = fs_adapters.FilesystemSource({"path": "/nonexistent/definitely-not-here.dcm"})
        destination = _CountingDestination()
        result = execution.run(source, _accept_and_anonymize_policy(), destination)
        self.assertEqual(result.outcome, execution.ExecutionOutcome.SOURCE_FAILED)
        self.assertEqual(result.diagnostic.code, "SOURCE_ACQUISITION_FAILED")
        self.assertIsNone(result.policy_result)
        self.assertEqual(destination.calls, [])

    @unittest.skipIf(os.geteuid() == 0, "permission bits are not enforced for root")
    def test_unreadable_source_is_source_failed(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.dcm")
            with open(src, "wb") as f:
                f.write(_build_fixture())
            os.chmod(src, 0o000)
            try:
                source = fs_adapters.FilesystemSource({"path": src})
                result = execution.run(source, _accept_and_anonymize_policy(), None)
                self.assertEqual(result.outcome, execution.ExecutionOutcome.SOURCE_FAILED)
            finally:
                os.chmod(src, 0o644)

    def test_existing_destination_rejected_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            dst = os.path.join(d, "out.dcm")
            with open(dst, "wb") as f:
                f.write(b"pre-existing content")
            destination = fs_adapters.FilesystemDestination({"path": dst})
            with self.assertRaises(execution.DestinationWriteError) as ctx:
                destination.write(b"new content")
            self.assertEqual(ctx.exception.category, "DESTINATION_ALREADY_EXISTS")
            self.assertEqual(Path(dst).read_bytes(), b"pre-existing content")  # untouched

    def test_explicit_overwrite_true_replaces_existing(self):
        with tempfile.TemporaryDirectory() as d:
            dst = os.path.join(d, "out.dcm")
            with open(dst, "wb") as f:
                f.write(b"old content")
            destination = fs_adapters.FilesystemDestination({"path": dst, "overwrite": True})
            destination.write(b"new content")
            self.assertEqual(Path(dst).read_bytes(), b"new content")

    def test_source_destination_collision_rejected_before_acquisition(self):
        with tempfile.TemporaryDirectory() as d:
            same_path = os.path.join(d, "same.dcm")
            with open(same_path, "wb") as f:
                f.write(_build_fixture())
            source = fs_adapters.FilesystemSource({"path": same_path})
            destination = fs_adapters.FilesystemDestination({"path": same_path})
            with self.assertRaises(adapters.AdapterResolutionError) as ctx:
                adapters.check_source_destination_collision(source, destination)
            self.assertEqual(ctx.exception.code, "SOURCE_DESTINATION_COLLISION")

    def test_non_filesystem_pair_never_false_positives_collision_check(self):
        source = _CountingSource(data=b"x")
        destination = _CountingDestination()
        adapters.check_source_destination_collision(source, destination)  # no-op, no raise

    def test_temp_file_cleanup_on_write_failure(self):
        with tempfile.TemporaryDirectory() as d:
            dst = os.path.join(d, "out.dcm")
            destination = fs_adapters.FilesystemDestination({"path": dst})

            class _ExplodingFile:
                def __init__(self, fd):
                    self._fd = fd

                def __enter__(self):
                    return self

                def __exit__(self, *exc_info):
                    os.close(self._fd)
                    return False

                def write(self, data):
                    raise OSError("simulated disk full")

            def fake_fdopen(fd, mode):
                return _ExplodingFile(fd)

            with mock.patch("os.fdopen", side_effect=fake_fdopen):
                with self.assertRaises(execution.DestinationWriteError) as ctx:
                    destination.write(b"data")
            self.assertEqual(ctx.exception.category, "DESTINATION_WRITE_FAILED")
            self.assertEqual(list(Path(d).iterdir()), [])  # temp file removed, no target created

    def test_temp_file_cleanup_on_commit_failure(self):
        with tempfile.TemporaryDirectory() as d:
            dst = os.path.join(d, "out.dcm")
            destination = fs_adapters.FilesystemDestination({"path": dst})
            with mock.patch("os.link", side_effect=OSError("simulated commit failure")):
                with self.assertRaises(execution.DestinationWriteError) as ctx:
                    destination.write(b"data")
            self.assertEqual(ctx.exception.category, "DESTINATION_COMMIT_FAILED")
            self.assertEqual(list(Path(d).iterdir()), [])  # temp file removed, no target created

    def test_race_safe_no_overwrite_no_check_then_act_window(self):
        """Proves there is no window in which a naive check-then-rename
        implementation could have already passed its "does not exist"
        check before a concurrent creator wins: the target is created here,
        *after* the destination adapter object already exists (simulating a
        concurrent creator that appeared after any hypothetical earlier
        check), and `write()` -- which performs no separate existence check
        of its own, only the atomic `os.link` publish step -- still
        correctly detects and refuses to overwrite it, every time."""
        with tempfile.TemporaryDirectory() as d:
            dst = os.path.join(d, "out.dcm")
            destination = fs_adapters.FilesystemDestination({"path": dst})
            with open(dst, "wb") as f:
                f.write(b"concurrently created")
            with self.assertRaises(execution.DestinationWriteError) as ctx:
                destination.write(b"my content")
            self.assertEqual(ctx.exception.category, "DESTINATION_ALREADY_EXISTS")
            self.assertEqual(Path(dst).read_bytes(), b"concurrently created")

    def test_race_safe_no_overwrite_under_real_concurrency(self):
        """A genuine concurrency stress test (test infrastructure only --
        no concurrency framework is added to the adapter itself): many
        repeated trials of two threads racing to publish to the same
        non-existent target with overwrite=False must always produce
        exactly one winner and one DESTINATION_ALREADY_EXISTS loser, never
        two winners and never a corrupted/mixed target."""
        for _ in range(20):
            with tempfile.TemporaryDirectory() as d:
                dst = os.path.join(d, "out.dcm")
                payload_a = b"A" * 64
                payload_b = b"B" * 64
                outcomes = []
                lock = threading.Lock()

                def attempt(payload):
                    destination = fs_adapters.FilesystemDestination({"path": dst})
                    try:
                        destination.write(payload)
                        with lock:
                            outcomes.append("won")
                    except execution.DestinationWriteError as exc:
                        with lock:
                            outcomes.append(exc.category)

                t1 = threading.Thread(target=attempt, args=(payload_a,))
                t2 = threading.Thread(target=attempt, args=(payload_b,))
                t1.start(); t2.start()
                t1.join(); t2.join()

                self.assertEqual(outcomes.count("won"), 1, outcomes)
                self.assertEqual(outcomes.count("DESTINATION_ALREADY_EXISTS"), 1, outcomes)
                final = Path(dst).read_bytes()
                self.assertIn(final, (payload_a, payload_b))  # never mixed/corrupted


# ---------------------------------------------------------------------------
# Security / privacy qualification
# ---------------------------------------------------------------------------

class SecurityQualificationTest(unittest.TestCase):
    def test_parse_failure_diagnostic_does_not_leak_sensitive_bytes(self):
        source = _CountingSource(data=b"garbage " + _SENSITIVE_NAME.encode() + b" not dicom")
        result = execution.run(source, _accept_and_anonymize_policy(), None)
        self.assertEqual(result.outcome, execution.ExecutionOutcome.PARSE_FAILED)
        self.assertNotIn(_SENSITIVE_NAME, result.diagnostic.message)
        self.assertNotIn(_SENSITIVE_NAME, repr(result.diagnostic))
        self.assertNotIn(_SENSITIVE_NAME, repr(result))

    def test_source_acquisition_exception_text_does_not_leak(self):
        class _Boom(Exception):
            def __str__(self):
                return f"failed reading /patients/{_SENSITIVE_NAME}/file.dcm: permission denied"

        source = _CountingSource(fail_with=execution.SourceAcquisitionError(_Boom()))
        result = execution.run(source, _accept_and_anonymize_policy(), None)
        self.assertEqual(result.outcome, execution.ExecutionOutcome.SOURCE_FAILED)
        self.assertNotIn(_SENSITIVE_NAME, result.diagnostic.message)
        self.assertNotIn(_SENSITIVE_NAME, repr(result.diagnostic))
        self.assertEqual(result.diagnostic.cause_type, "_Boom")

    def test_destination_failure_exception_text_does_not_leak(self):
        class _Boom(Exception):
            def __str__(self):
                return f"cannot write to /output/{_SENSITIVE_NAME}.dcm"

        source = _CountingSource(data=_build_fixture())
        destination = _CountingDestination(
            fail_with=execution.DestinationWriteError(_Boom(), category="DESTINATION_WRITE_FAILED"))
        result = execution.run(source, _accept_and_anonymize_policy(), destination)
        self.assertEqual(result.outcome, execution.ExecutionOutcome.DESTINATION_FAILED)
        self.assertNotIn(_SENSITIVE_NAME, result.diagnostic.message)
        self.assertNotIn(_SENSITIVE_NAME, repr(result))

    def test_adapter_resolution_error_does_not_echo_options(self):
        with self.assertRaises(adapters.AdapterResolutionError) as ctx:
            fs_adapters.FilesystemSource({"path": f"/patients/{_SENSITIVE_NAME}", "extra": "bad"})
        self.assertNotIn(_SENSITIVE_NAME, str(ctx.exception))
        self.assertNotIn(_SENSITIVE_NAME, ctx.exception.message)

    def test_execution_diagnostic_codes_closed_and_stable(self):
        self.assertEqual(len(execution.EXECUTION_DIAGNOSTIC_CODES),
                          len(set(execution.EXECUTION_DIAGNOSTIC_CODES)))


# ---------------------------------------------------------------------------
# Real-DICOM qualification -- pydicom / DCMTK
# ---------------------------------------------------------------------------

class RealDicomQualificationTest(unittest.TestCase):
    def test_pydicom_confirms_filesystem_executed_policy_output(self):
        try:
            import pydicom
        except ImportError:
            self.skipTest("pydicom not available in this environment")

        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.dcm")
            dst = os.path.join(d, "out.dcm")
            with open(src, "wb") as f:
                f.write(_build_fixture())
            source = fs_adapters.FilesystemSource({"path": src})
            destination = fs_adapters.FilesystemDestination({"path": dst})
            result = execution.run(source, _accept_and_anonymize_policy(), destination)
            self.assertEqual(result.outcome, execution.ExecutionOutcome.SUCCEEDED)

            _reparse_cleanly(Path(dst).read_bytes())
            ds = pydicom.dcmread(dst)
            self.assertEqual(str(ds.PatientName), "ANONYMIZED")
            self.assertEqual(ds.Modality, "CT")

    def test_dcmtk_dcmdump_confirms_filesystem_executed_policy_output(self):
        import shutil
        import subprocess

        dcmdump = shutil.which("dcmdump")
        if dcmdump is None:
            self.skipTest("dcmdump (DCMTK) not available in this environment")

        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.dcm")
            dst = os.path.join(d, "out.dcm")
            with open(src, "wb") as f:
                f.write(_build_fixture())
            source = fs_adapters.FilesystemSource({"path": src})
            destination = fs_adapters.FilesystemDestination({"path": dst})
            result = execution.run(source, _accept_and_anonymize_policy(), destination)
            self.assertEqual(result.outcome, execution.ExecutionOutcome.SUCCEEDED)

            _reparse_cleanly(Path(dst).read_bytes())
            proc = subprocess.run([dcmdump, dst], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("ANONYMIZED", proc.stdout)


# ---------------------------------------------------------------------------
# Explicit / Implicit VR LE regression (smoke-level only)
# ---------------------------------------------------------------------------

class EncodingRegressionTest(unittest.TestCase):
    def test_execute_one_equivalent_across_transfer_syntaxes(self):
        results = {}
        for explicit in (True, False):
            data = _build_fixture(explicit=explicit)
            result = execution.execute_one(data, _accept_and_anonymize_policy())
            results[explicit] = (result.outcome, result.policy_result.decision,
                                  result.policy_result.execution)
        self.assertEqual(results[True], results[False])


# ---------------------------------------------------------------------------
# Performance -- pathological-regression smoke test only
# ---------------------------------------------------------------------------

class PerformanceSmokeTest(unittest.TestCase):
    def test_execution_wrapper_overhead_is_not_pathological(self):
        data = _build_fixture()
        pol = _accept_and_anonymize_policy()

        structure = fds.read_buffer(data, fidelity="lossless")
        try:
            start = time.perf_counter()
            for _ in range(50):
                policy.apply(structure, policy.Policy(name="t", version="1", operations=()))
            direct_apply_time = (time.perf_counter() - start) / 50
        finally:
            structure.close()

        start = time.perf_counter()
        for _ in range(50):
            execution.execute_one(data, pol)
        wrapped_time = (time.perf_counter() - start) / 50

        # Only a pathological-overhead guard (parse+apply+serialize should
        # not be orders of magnitude slower than a bare no-op apply call on
        # an already-parsed structure) -- no throughput/scalability claim.
        self.assertLess(wrapped_time, max(direct_apply_time * 1000, 0.05))

    def test_source_read_and_destination_write_timing_are_separable(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.dcm")
            dst = os.path.join(d, "out.dcm")
            with open(src, "wb") as f:
                f.write(_build_fixture())
            source = fs_adapters.FilesystemSource({"path": src})
            destination = fs_adapters.FilesystemDestination({"path": dst})

            t0 = time.perf_counter()
            data = source.acquire()
            t1 = time.perf_counter()
            result = execution.execute_one(data, _accept_and_anonymize_policy())
            t2 = time.perf_counter()
            destination.write(result.output_bytes)
            t3 = time.perf_counter()

        # No assertion beyond "each stage completes and is independently
        # timeable" -- recorded as characterization, not a product claim.
        self.assertGreaterEqual(t1, t0)
        self.assertGreaterEqual(t2, t1)
        self.assertGreaterEqual(t3, t2)


if __name__ == "__main__":
    unittest.main()
