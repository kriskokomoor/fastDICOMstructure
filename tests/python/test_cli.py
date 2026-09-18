"""Qualification for S1.6 (Thin CLI Consumer): probes A-L, the black-box
and instrumentation delegation proofs (Probe J), security/privacy
qualification (including the narrow, approved --config path-disclosure
exception), real-DICOM validation, and a startup-overhead smoke check.

Byte-fixture-building style mirrors tests/python/test_execution.py
(duplicated locally, following that file's own stated convention).
"""

import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

PYTHON_DIR = Path(__file__).resolve().parents[2] / "python"
sys.path.insert(0, str(PYTHON_DIR))

import fastdicomstructure as fds  # noqa: E402
from fastdicomstructure import policy  # noqa: E402
from fastdicomstructure import configuration as cfg  # noqa: E402
from fastdicomstructure import execution  # noqa: E402
from fastdicomstructure import adapters  # noqa: E402
from fastdicomstructure import cli  # noqa: E402

import fastdicomattrs  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture building (mirrors test_execution.py exactly)
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
_TAG_PATIENT_ID = (0x0010, 0x0020)
_TAG_AMBIGUOUS = (0x0028, 0x0106)  # SmallestImagePixelValue -- ambiguous -> VR_REQUIRED
_TAG_OTHER_PATIENT_IDS_SEQ = (0x0010, 0x1002)  # for a multi-site rollback probe

_SENSITIVE_NAME = "Zbigniew^Sekretny^SSN-123-45-6789"  # must never leak into CLI output


def _build_fixture(patient_name: bytes = None) -> bytes:
    name = patient_name if patient_name is not None else _SENSITIVE_NAME.encode("ascii")
    item0 = _dicom_item(_element_short(*_TAG_PATIENT_ID, "LO", b"AAA"))
    item1 = _dicom_item(_element_short(*_TAG_PATIENT_ID, "LO", b"BBB"))
    dataset = (
        _element_short(*_TAG_MODALITY, "CS", b"CT")
        + _element_short(*_TAG_CHARSET, "CS", b"ISO_IR 100")
        + _element_short(*_TAG_PATIENT_ID, "LO", b"12345")
        + _element_short(*_TAG_PATIENT_NAME, "PN", name)
        + _element_sq(*_TAG_OTHER_PATIENT_IDS_SEQ, item0 + item1)
    )
    return b"\x00" * 128 + b"DICM" + _file_meta(b"1.2.840.10008.1.2.1") + dataset


_ACCEPT_AND_ANONYMIZE_POLICY_DOC = {
    "name": "cli-probe-policy", "version": "1.0",
    "acceptance": [{"op": "require", "target": {"tag": "(0010,0020)", "scope": "root"}}],
    "mutation": [{"op": "replace_text", "target": {"tag": "(0010,0010)", "scope": "root"},
                  "value": "ANONYMIZED"}],
}

_REJECTING_POLICY_DOC = {
    "name": "cli-probe-policy", "version": "1.0",
    "acceptance": [{"op": "require", "target": {"tag": "(0008,0099)", "scope": "root"}}],
}

_PARTIAL_POLICY_DOC = {
    "name": "cli-probe-policy", "version": "1.0",
    "mutation": [
        {"op": "remove", "target": {"tag": "(0008,0060)", "scope": "root"}},
        {"op": "ensure_text", "target": {"tag": "(0028,0106)", "scope": "root"}, "value": "1"},
    ],
}


def _write_config(directory, policy_doc, source_path=None, destination_path=None,
                   include_destination=True) -> Path:
    doc = {"schema": "fastdicomstructure-configuration", "schema_version": 1, "policy": policy_doc}
    if source_path is not None:
        doc["source"] = {"type": "filesystem", "options": {"path": str(source_path)}}
    if include_destination and destination_path is not None:
        doc["destination"] = {"type": "filesystem", "options": {"path": str(destination_path)}}
    path = Path(directory) / "config.json"
    path.write_text(json.dumps(doc))
    return path


def _run_cli_subprocess(*args, timeout=30):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PYTHON_DIR)
    return subprocess.run([sys.executable, "-m", "fastdicomstructure", "run", *args],
                           capture_output=True, text=True, env=env, timeout=timeout)


def _reparse_cleanly(data: bytes) -> None:
    reparsed = fds.read_buffer(data, fidelity="lossless")
    try:
        blocking = [d for d in reparsed.diagnostics if d.severity != "info"]
        assert not blocking, f"output failed self-verification reparse: {blocking}"
    finally:
        reparsed.close()


def _flaky_replace_text_patches():
    """A CLI-reachable (JSON-representable) variant of
    tests/python/test_execution.py's own proven RollbackError technique.
    `replace_text`'s forward mutation goes through `Structure.set_text`
    (which raises on failure, unlike the raw bool-return `set_value`), but
    `_apply_sites_atomically`'s own rollback *restoration* always uses
    `Structure.set_value` regardless of the forward mutation's own kind
    (policy.py's own documented design: rollback restores raw bytes,
    never semantic text). So: patch `set_text` so site 0 (root
    _TAG_PATIENT_ID) succeeds and site 1 (the first nested occurrence)
    raises, triggering rollback of site 0; patch `set_value` so that
    rollback's own restore attempt for site 0 is forced to fail too,
    producing RollbackError."""
    real_set_text = fastdicomattrs.Structure.set_text
    calls = {"n": 0}

    def flaky_set_text(self, path, values):
        calls["n"] += 1
        if calls["n"] == 1:
            return real_set_text(self, path, values)
        raise ValueError("simulated forward mutation failure")

    def flaky_set_value(self, path, value):
        return False  # rollback's own restore attempt for site 0: forced to fail

    return flaky_set_text, flaky_set_value


# ---------------------------------------------------------------------------
# Probe A -- successful configured CLI execution
# ---------------------------------------------------------------------------

class ProbeATest(unittest.TestCase):
    def test_successful_configured_cli_execution(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "in.dcm")
            dst = Path(d, "out.dcm")
            src.write_bytes(_build_fixture())
            config_path = _write_config(d, _ACCEPT_AND_ANONYMIZE_POLICY_DOC, src, dst)

            proc = _run_cli_subprocess("--config", str(config_path), "--json")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            doc = json.loads(proc.stdout)
            self.assertEqual(doc["status"], "succeeded")
            self.assertEqual(doc["policy"]["decision"], "transform")
            self.assertNotIn("output_bytes", proc.stdout)

            self.assertTrue(dst.exists())
            _reparse_cleanly(dst.read_bytes())
            reparsed = fds.read(str(dst), fidelity="lossless")
            try:
                self.assertEqual(reparsed.decode_text(_TAG_PATIENT_NAME), ["ANONYMIZED"])
            finally:
                reparsed.close()

    def test_human_readable_default_output(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "in.dcm")
            dst = Path(d, "out.dcm")
            src.write_bytes(_build_fixture())
            config_path = _write_config(d, _ACCEPT_AND_ANONYMIZE_POLICY_DOC, src, dst)

            proc = _run_cli_subprocess("--config", str(config_path))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("SUCCEEDED", proc.stdout)
            self.assertIn("decision=transform", proc.stdout)
            # No attempt to parse this as JSON -- it deliberately is not.
            with self.assertRaises(json.JSONDecodeError):
                json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# Probe B -- policy rejection
# ---------------------------------------------------------------------------

class ProbeBTest(unittest.TestCase):
    def test_policy_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "in.dcm")
            dst = Path(d, "out.dcm")
            src.write_bytes(_build_fixture())
            config_path = _write_config(d, _REJECTING_POLICY_DOC, src, dst)

            proc = _run_cli_subprocess("--config", str(config_path), "--json")
            self.assertEqual(proc.returncode, 14, proc.stderr)
            doc = json.loads(proc.stdout)
            self.assertEqual(doc["status"], "policy_rejected")
            self.assertEqual(doc["policy"]["diagnostics"][0]["code"], "REQUIREMENT_UNSATISFIED")
            self.assertIsNone(doc["diagnostic"])  # not duplicated
            self.assertFalse(dst.exists())
            self.assertNotIn(_SENSITIVE_NAME, proc.stdout)
            self.assertNotIn(_SENSITIVE_NAME, proc.stderr)


# ---------------------------------------------------------------------------
# Probe C -- malformed DICOM
# ---------------------------------------------------------------------------

class ProbeCTest(unittest.TestCase):
    def test_malformed_dicom_lenient_diagnostic_path(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "in.dcm")
            dst = Path(d, "out.dcm")
            src.write_bytes(b"not a dicom file at all, contains " + _SENSITIVE_NAME.encode())
            config_path = _write_config(d, _ACCEPT_AND_ANONYMIZE_POLICY_DOC, src, dst)

            proc = _run_cli_subprocess("--config", str(config_path), "--json")
            self.assertEqual(proc.returncode, 13, proc.stderr)
            doc = json.loads(proc.stdout)
            self.assertEqual(doc["status"], "parse_failed")
            self.assertIsNone(doc["policy"])
            self.assertEqual(doc["diagnostic"]["code"], "DICOM_PARSE_FAILED")
            self.assertFalse(dst.exists())
            self.assertNotIn(_SENSITIVE_NAME, proc.stdout)

    def test_malformed_dicom_raised_fds_error_path(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "in.dcm")
            ts_uid = b"1.2.840.99999.1.1"  # unsupported transfer syntax
            group_body = (
                _element_short(0x0002, 0x0002, "UI", b"1.2.3.4")
                + _element_short(0x0002, 0x0003, "UI", b"1.2.3.4.5")
                + _element_short(0x0002, 0x0010, "UI", ts_uid)
            )
            file_meta = _element_short(0x0002, 0x0000, "UL", _u32(len(group_body))) + group_body
            src.write_bytes(b"\x00" * 128 + b"DICM" + file_meta
                             + _element_short(*_TAG_MODALITY, "CS", b"CT"))
            dst = Path(d, "out.dcm")
            config_path = _write_config(d, _ACCEPT_AND_ANONYMIZE_POLICY_DOC, src, dst)

            proc = _run_cli_subprocess("--config", str(config_path), "--json")
            self.assertEqual(proc.returncode, 13, proc.stderr)
            doc = json.loads(proc.stdout)
            self.assertEqual(doc["diagnostic"]["cause_type"], "FdsError")


# ---------------------------------------------------------------------------
# Probe D -- invalid Configuration V1
# ---------------------------------------------------------------------------

class ProbeDTest(unittest.TestCase):
    def test_invalid_configuration_fails_before_acquisition(self):
        with tempfile.TemporaryDirectory() as d:
            # A source that would raise loudly (IsADirectoryError) if ever
            # opened -- proves acquisition was never attempted.
            src = Path(d)  # a directory, not a file
            doc = {
                "schema": "fastdicomstructure-configuration", "schema_version": 1,
                "policy": {"name": "t"},  # missing required "version"
                "source": {"type": "filesystem", "options": {"path": str(src)}},
            }
            config_path = Path(d, "config.json")
            config_path.write_text(json.dumps(doc))

            proc = _run_cli_subprocess("--config", str(config_path), "--json")
            self.assertEqual(proc.returncode, 10, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result["status"], "configuration_error")
            self.assertEqual(result["code"], "MISSING_REQUIRED_FIELD")


# ---------------------------------------------------------------------------
# Probe E -- unknown adapter / invalid adapter options
# ---------------------------------------------------------------------------

class ProbeETest(unittest.TestCase):
    def test_unknown_adapter_type(self):
        with tempfile.TemporaryDirectory() as d:
            doc = {
                "schema": "fastdicomstructure-configuration", "schema_version": 1,
                "policy": {"name": "t", "version": "1.0"},
                "source": {"type": "future-adapter", "options": {}},
            }
            config_path = Path(d, "config.json")
            config_path.write_text(json.dumps(doc))

            proc = _run_cli_subprocess("--config", str(config_path), "--json")
            self.assertEqual(proc.returncode, 11, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result["status"], "adapter_resolution_error")
            self.assertEqual(result["code"], "ADAPTER_TYPE_UNKNOWN")

    def test_invalid_adapter_options(self):
        with tempfile.TemporaryDirectory() as d:
            doc = {
                "schema": "fastdicomstructure-configuration", "schema_version": 1,
                "policy": {"name": "t", "version": "1.0"},
                "source": {"type": "filesystem", "options": {}},  # missing "path"
            }
            config_path = Path(d, "config.json")
            config_path.write_text(json.dumps(doc))

            proc = _run_cli_subprocess("--config", str(config_path), "--json")
            self.assertEqual(proc.returncode, 11, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result["code"], "ADAPTER_OPTIONS_INVALID")


# ---------------------------------------------------------------------------
# Probe F -- source/destination collision
# ---------------------------------------------------------------------------

class ProbeFTest(unittest.TestCase):
    def test_source_destination_collision_rejected_before_acquisition(self):
        with tempfile.TemporaryDirectory() as d:
            same_path = Path(d, "same.dcm")
            original = _build_fixture()
            same_path.write_bytes(original)
            config_path = _write_config(d, _ACCEPT_AND_ANONYMIZE_POLICY_DOC, same_path, same_path)

            proc = _run_cli_subprocess("--config", str(config_path), "--json")
            self.assertEqual(proc.returncode, 11, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result["code"], "SOURCE_DESTINATION_COLLISION")
            self.assertEqual(same_path.read_bytes(), original)  # never touched


# ---------------------------------------------------------------------------
# Probe G -- destination already exists
# ---------------------------------------------------------------------------

class ProbeGTest(unittest.TestCase):
    def test_existing_destination_rejected_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "in.dcm")
            dst = Path(d, "out.dcm")
            src.write_bytes(_build_fixture())
            dst.write_bytes(b"pre-existing content")
            config_path = _write_config(d, _ACCEPT_AND_ANONYMIZE_POLICY_DOC, src, dst)

            proc = _run_cli_subprocess("--config", str(config_path), "--json")
            self.assertEqual(proc.returncode, 17, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result["status"], "destination_failed")
            self.assertEqual(result["diagnostic"]["code"], "DESTINATION_ALREADY_EXISTS")
            self.assertEqual(dst.read_bytes(), b"pre-existing content")  # untouched


# ---------------------------------------------------------------------------
# Probe H -- modeled partial policy execution
# ---------------------------------------------------------------------------

class ProbeHTest(unittest.TestCase):
    def test_modeled_partial_policy_execution(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "in.dcm")
            dst = Path(d, "out.dcm")
            src.write_bytes(_build_fixture())
            config_path = _write_config(d, _PARTIAL_POLICY_DOC, src, dst)

            proc = _run_cli_subprocess("--config", str(config_path), "--json")
            self.assertEqual(proc.returncode, 15, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result["status"], "policy_partial")
            self.assertFalse(dst.exists())
            self.assertIsNone(result["diagnostic"])  # PolicyResult remains sole authority


# ---------------------------------------------------------------------------
# Probe I -- raw rollback/internal exception (must be in-process)
# ---------------------------------------------------------------------------

class ProbeITest(unittest.TestCase):
    def test_rollback_error_propagates_uncaught_from_cli_main(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "in.dcm")
            src.write_bytes(_build_fixture())
            flaky_set_text, flaky_set_value = _flaky_replace_text_patches()
            doc = {
                "schema": "fastdicomstructure-configuration", "schema_version": 1,
                "policy": {
                    "name": "flaky-cli", "version": "1.0",
                    "mutation": [{"op": "replace_text",
                                  "target": {"tag": "(0010,0020)", "scope": "recursive"},
                                  "value": "ZZZZZZ"}],
                },
                "source": {"type": "filesystem", "options": {"path": str(src)}},
            }
            config_path = Path(d, "config.json")
            config_path.write_text(json.dumps(doc))

            argv = ["run", "--config", str(config_path)]
            with mock.patch.object(fastdicomattrs.Structure, "set_text", flaky_set_text), \
                    mock.patch.object(fastdicomattrs.Structure, "set_value", flaky_set_value):
                with self.assertRaises(policy.RollbackError):
                    cli.main(argv)


# ---------------------------------------------------------------------------
# Probe J -- direct architecture delegation
# ---------------------------------------------------------------------------

class ProbeJTest(unittest.TestCase):
    def test_black_box_equivalence_cli_vs_direct_library_call(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "in.dcm")
            dst_cli = Path(d, "out_cli.dcm")
            dst_direct = Path(d, "out_direct.dcm")
            data = _build_fixture()
            src.write_bytes(data)

            config_path = _write_config(d, _ACCEPT_AND_ANONYMIZE_POLICY_DOC, src, dst_cli)
            proc = _run_cli_subprocess("--config", str(config_path), "--json")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            cli_doc = json.loads(proc.stdout)

            config_path_direct = _write_config(d, _ACCEPT_AND_ANONYMIZE_POLICY_DOC, src, dst_direct)
            config_direct = cfg.load_configuration_json(config_path_direct.read_text())
            direct_result = execution.run_configured(config_direct)

            self.assertEqual(cli_doc["policy"]["decision"], direct_result.policy_result.decision.value)
            self.assertEqual(cli_doc["policy"]["execution"], direct_result.policy_result.execution.value)
            self.assertEqual(dst_cli.read_bytes(), dst_direct.read_bytes())  # byte-identical

    def test_instrumentation_shows_exactly_one_parse_apply_serialize(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "in.dcm")
            dst = Path(d, "out.dcm")
            src.write_bytes(_build_fixture())
            config_path = _write_config(d, _ACCEPT_AND_ANONYMIZE_POLICY_DOC, src, dst)

            real_apply = policy.apply
            real_write_bytes = fastdicomattrs.Structure.write_bytes
            counts = {"apply": 0, "write_bytes": 0}

            def counting_apply(structure, pol):
                counts["apply"] += 1
                return real_apply(structure, pol)

            def counting_write_bytes(self):
                counts["write_bytes"] += 1
                return real_write_bytes(self)

            with mock.patch.object(policy, "apply", side_effect=counting_apply), \
                    mock.patch.object(fastdicomattrs.Structure, "write_bytes", counting_write_bytes):
                exit_code = cli.main(["run", "--config", str(config_path), "--json"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(counts["apply"], 1)
            self.assertEqual(counts["write_bytes"], 1)
            self.assertTrue(dst.exists())


# ---------------------------------------------------------------------------
# Probe K -- destination-less "policy check" invocation
# ---------------------------------------------------------------------------

class ProbeKTest(unittest.TestCase):
    def test_destination_less_policy_check(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "in.dcm")
            src.write_bytes(_build_fixture())
            config_path = _write_config(d, _ACCEPT_AND_ANONYMIZE_POLICY_DOC, src,
                                         destination_path=None, include_destination=False)

            proc = _run_cli_subprocess("--config", str(config_path), "--json")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            doc = json.loads(proc.stdout)
            self.assertEqual(doc["status"], "succeeded")
            self.assertNotIn("output_bytes", proc.stdout)
            # no destination was ever configured -- nothing else in the
            # directory besides the source and config themselves
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()),
                              sorted(["in.dcm", "config.json"]))


# ---------------------------------------------------------------------------
# Probe L -- CLI usage errors
# ---------------------------------------------------------------------------

class ProbeLTest(unittest.TestCase):
    def test_missing_config_flag(self):
        proc = _run_cli_subprocess()
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")

    def test_unreadable_config_path(self):
        proc = _run_cli_subprocess("--config", "/definitely/not/here/config.json")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("/definitely/not/here/config.json", proc.stderr)  # approved exception
        self.assertEqual(proc.stdout, "")

    def test_configuration_with_no_source(self):
        with tempfile.TemporaryDirectory() as d:
            doc = {
                "schema": "fastdicomstructure-configuration", "schema_version": 1,
                "policy": {"name": "t", "version": "1.0"},
            }
            config_path = Path(d, "config.json")
            config_path.write_text(json.dumps(doc))
            proc = _run_cli_subprocess("--config", str(config_path))
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, "")


# ---------------------------------------------------------------------------
# Security / privacy qualification
# ---------------------------------------------------------------------------

class SecurityQualificationTest(unittest.TestCase):
    def test_sensitive_source_destination_path_never_echoed(self):
        with tempfile.TemporaryDirectory() as d:
            sensitive_dir = Path(d, _SENSITIVE_NAME)
            sensitive_dir.mkdir()
            src = sensitive_dir / "in.dcm"
            src.write_bytes(_build_fixture())
            dst = sensitive_dir / "out.dcm"
            dst.write_bytes(b"pre-existing")  # force DESTINATION_ALREADY_EXISTS
            config_path = _write_config(d, _ACCEPT_AND_ANONYMIZE_POLICY_DOC, src, dst)

            proc = _run_cli_subprocess("--config", str(config_path), "--json")
            self.assertNotIn(_SENSITIVE_NAME, proc.stdout)
            self.assertNotIn(_SENSITIVE_NAME, proc.stderr)

            proc_text = _run_cli_subprocess("--config", str(config_path))
            self.assertNotIn(_SENSITIVE_NAME, proc_text.stdout)
            self.assertNotIn(_SENSITIVE_NAME, proc_text.stderr)

    def test_sensitive_config_path_is_echoed_only_for_config_read_failure(self):
        sensitive_missing_path = f"/tmp/{_SENSITIVE_NAME}/config.json"
        proc = _run_cli_subprocess("--config", sensitive_missing_path)
        # This IS the one approved, narrow exception (Correction 2): the
        # --config argument itself may be echoed on a read failure.
        self.assertIn(sensitive_missing_path, proc.stderr)

    def test_sensitive_dicom_value_never_leaks_on_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "in.dcm")
            src.write_bytes(_build_fixture(patient_name=_SENSITIVE_NAME.encode()))
            dst = Path(d, "out.dcm")
            config_path = _write_config(d, _REJECTING_POLICY_DOC, src, dst)

            proc = _run_cli_subprocess("--config", str(config_path), "--json")
            self.assertNotIn(_SENSITIVE_NAME, proc.stdout)
            self.assertNotIn(_SENSITIVE_NAME, proc.stderr)

    def test_no_rendering_path_uses_bare_repr_or_str(self):
        source = Path(cli.__file__).read_text()
        # A crude but meaningful static check: no rendering helper calls
        # str(exc)/repr(exc) or repr(config)/repr(result) anywhere.
        self.assertNotIn("str(exc)", source)
        self.assertNotIn("repr(exc)", source)
        self.assertNotIn("repr(config)", source)
        self.assertNotIn("repr(result)", source)

    def test_json_output_never_contains_output_bytes_key(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "in.dcm")
            dst = Path(d, "out.dcm")
            src.write_bytes(_build_fixture())
            config_path = _write_config(d, _ACCEPT_AND_ANONYMIZE_POLICY_DOC, src, dst)
            proc = _run_cli_subprocess("--config", str(config_path), "--json")
            doc = json.loads(proc.stdout)
            self.assertNotIn("output_bytes", json.dumps(doc))


# ---------------------------------------------------------------------------
# Real-DICOM qualification -- pydicom / DCMTK
# ---------------------------------------------------------------------------

class RealDicomQualificationTest(unittest.TestCase):
    def test_pydicom_confirms_cli_executed_policy_output(self):
        try:
            import pydicom
        except ImportError:
            self.skipTest("pydicom not available in this environment")

        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "in.dcm")
            dst = Path(d, "out.dcm")
            src.write_bytes(_build_fixture())
            config_path = _write_config(d, _ACCEPT_AND_ANONYMIZE_POLICY_DOC, src, dst)

            proc = _run_cli_subprocess("--config", str(config_path), "--json")
            self.assertEqual(proc.returncode, 0, proc.stderr)

            _reparse_cleanly(dst.read_bytes())
            ds = pydicom.dcmread(str(dst))
            self.assertEqual(str(ds.PatientName), "ANONYMIZED")
            self.assertEqual(ds.Modality, "CT")

    def test_dcmtk_dcmdump_confirms_cli_executed_policy_output(self):
        import shutil

        dcmdump = shutil.which("dcmdump")
        if dcmdump is None:
            self.skipTest("dcmdump (DCMTK) not available in this environment")

        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "in.dcm")
            dst = Path(d, "out.dcm")
            src.write_bytes(_build_fixture())
            config_path = _write_config(d, _ACCEPT_AND_ANONYMIZE_POLICY_DOC, src, dst)

            proc = _run_cli_subprocess("--config", str(config_path), "--json")
            self.assertEqual(proc.returncode, 0, proc.stderr)

            _reparse_cleanly(dst.read_bytes())
            dump = subprocess.run([dcmdump, str(dst)], capture_output=True, text=True, timeout=30)
        self.assertEqual(dump.returncode, 0, dump.stderr)
        self.assertIn("ANONYMIZED", dump.stdout)


# ---------------------------------------------------------------------------
# Performance -- bounded startup/orchestration smoke check only
# ---------------------------------------------------------------------------

class PerformanceSmokeTest(unittest.TestCase):
    def test_cli_startup_and_orchestration_overhead_is_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "in.dcm")
            dst = Path(d, "out.dcm")
            src.write_bytes(_build_fixture())
            config_path = _write_config(d, _ACCEPT_AND_ANONYMIZE_POLICY_DOC, src, dst)

            start = time.perf_counter()
            proc = _run_cli_subprocess("--config", str(config_path))
            elapsed = time.perf_counter() - start

        self.assertEqual(proc.returncode, 0, proc.stderr)
        # A generous bound -- only rules out pathological overhead (an
        # accidental heavy import, a hang); not a throughput/performance
        # claim of any kind.
        self.assertLess(elapsed, 10.0)


if __name__ == "__main__":
    unittest.main()
