"""Qualification for S1.7 (Container Portability): probes A-L, comparing a
native-host invocation of the frozen S1.6 CLI against an equivalent
`docker run` invocation of the S1.7 image for the same underlying DICOM
bytes and Policy.

Requires Docker and the pre-built `fastdicomstructure:s1.7` image (see
Dockerfile) -- every test in this module skips cleanly, individually, when
either is unavailable, mirroring the established pydicom/dcmdump skip
convention used throughout this project's own qualification suites. These
tests are Docker-dependent and image-build-dependent, and are therefore
much slower than the rest of the suite; they are the exception, not the
rule.

Byte-fixture-building style mirrors tests/python/test_cli.py (duplicated
locally, following that file's own stated convention).
"""

import contextlib
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PYTHON_DIR = Path(__file__).resolve().parents[2] / "python"
sys.path.insert(0, str(PYTHON_DIR))

import fastdicomstructure as fds  # noqa: E402

IMAGE = "fastdicomstructure:s1.7"


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True,
                        timeout=10, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False
    return True


_DOCKER_SKIP_REASON = (f"Docker and/or the {IMAGE!r} image are not available in this "
                        "environment (see Dockerfile to build it)")


# ---------------------------------------------------------------------------
# Fixture building (mirrors test_cli.py/test_execution.py exactly)
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

_SENSITIVE_NAME = "Zbigniew^Sekretny^SSN-123-45-6789"  # must never leak into container output


def _build_fixture(patient_name: bytes = None) -> bytes:
    name = patient_name if patient_name is not None else _SENSITIVE_NAME.encode("ascii")
    dataset = (
        _element_short(*_TAG_MODALITY, "CS", b"CT")
        + _element_short(*_TAG_CHARSET, "CS", b"ISO_IR 100")
        + _element_short(*_TAG_PATIENT_ID, "LO", b"12345")
        + _element_short(*_TAG_PATIENT_NAME, "PN", name)
    )
    return b"\x00" * 128 + b"DICM" + _file_meta(b"1.2.840.10008.1.2.1") + dataset


_ACCEPT_AND_ANONYMIZE_POLICY_DOC = {
    "name": "container-probe-policy", "version": "1.0",
    "acceptance": [{"op": "require", "target": {"tag": "(0010,0020)", "scope": "root"}}],
    "mutation": [{"op": "replace_text", "target": {"tag": "(0010,0010)", "scope": "root"},
                  "value": "ANONYMIZED"}],
}

_REJECTING_POLICY_DOC = {
    "name": "container-probe-policy", "version": "1.0",
    "acceptance": [{"op": "require", "target": {"tag": "(0008,0099)", "scope": "root"}}],
}


def _config_doc(policy_doc, source_path=None, destination_path=None, include_destination=True):
    doc = {"schema": "fastdicomstructure-configuration", "schema_version": 1, "policy": policy_doc}
    if source_path is not None:
        doc["source"] = {"type": "filesystem", "options": {"path": str(source_path)}}
    if include_destination and destination_path is not None:
        doc["destination"] = {"type": "filesystem", "options": {"path": str(destination_path)}}
    return doc


def _run_host_cli(*args, timeout=30):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PYTHON_DIR)
    return subprocess.run([sys.executable, "-m", "fastdicomstructure", "run", *args],
                           capture_output=True, text=True, env=env, timeout=timeout)


def _run_container_cli(work_dir, *args, network=None, read_only=False, timeout=60):
    docker_args = ["docker", "run", "--rm", "-v", f"{work_dir}:/work"]
    if network is not None:
        docker_args += ["--network", network]
    if read_only:
        docker_args += ["--read-only"]
    docker_args += [IMAGE, "run", *args]
    return subprocess.run(docker_args, capture_output=True, text=True, timeout=timeout)


def _reparse_cleanly(data: bytes) -> None:
    reparsed = fds.read_buffer(data, fidelity="lossless")
    try:
        blocking = [d for d in reparsed.diagnostics if d.severity != "info"]
        assert not blocking, f"output failed self-verification reparse: {blocking}"
    finally:
        reparsed.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_container_file(work_dir, container_path: str) -> bytes:
    """Reads a file the container itself wrote, via a follow-up container
    invocation rather than a direct host-side filesystem read.

    Real finding, not a workaround for a defect: `FilesystemDestination`'s
    published output inherits `tempfile.mkstemp`'s own default restrictive
    permission mode (0600) through the temp-file-then-publish sequence
    (S1.5, unmodified) -- so a file the container's non-root `fdsuser`
    (uid 1000) writes onto a bind mount is owned, and readable, only by
    that UID. The *host* user running this test suite is a different UID
    and is correctly denied direct read access -- this is `FilesystemDestination`'s
    existing, frozen behavior working exactly as designed, not something S1.7
    introduces. The container's own `fdsuser` can always read a file it
    itself owns, so this helper reads it back through a second, cheap
    container invocation (`cat`, running as the image's own default user)
    rather than requiring the host process to share that UID."""
    proc = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{work_dir}:/work", "--entrypoint", "cat",
         IMAGE, container_path],
        capture_output=True, timeout=30)
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    return proc.stdout


@contextlib.contextmanager
def _work_dir():
    """`tempfile.TemporaryDirectory()` creates its directory with mode
    0o700 (owner-only) regardless of umask -- readable/traversable only by
    the host user that created it. The container runs as a *different*,
    non-root UID (fdsuser, 1000, matching the image's own runtime-user
    design) that does not map to the host user, so a 0o700 bind-mounted
    directory is completely inaccessible to it: not a container or CLI
    defect, but a real qualification-setup detail this suite must get
    right for the container-side half of every probe to be meaningful at
    all (exactly the concern the S1.7 authorization itself named for
    Probe J). Widened to 0o777 immediately after creation -- test-harness
    permissions only, never anything about the application or image
    itself."""
    with tempfile.TemporaryDirectory() as d:
        os.chmod(d, 0o777)
        yield Path(d)


@unittest.skipUnless(_docker_available(), _DOCKER_SKIP_REASON)
class ProbeATest(unittest.TestCase):
    """Successful transform: host vs. container, plus a third comparison
    against direct in-process execution.run_configured (S1.6's own
    established differential-qualification convention)."""

    def test_successful_transform_host_container_equivalence(self):
        with _work_dir() as work:
            
            (work / "in.dcm").write_bytes(_build_fixture())

            host_cfg = work / "config_host.json"
            host_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, work / "in.dcm", work / "out_host.dcm")))

            container_cfg = work / "config_container.json"
            container_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, "/work/in.dcm", "/work/out_container.dcm")))

            host_proc = _run_host_cli("--config", str(host_cfg), "--json")
            container_proc = _run_container_cli(
                work, "--config", "/work/config_container.json", "--json")

            self.assertEqual(host_proc.returncode, 0, host_proc.stderr)
            self.assertEqual(container_proc.returncode, 0, container_proc.stderr)

            host_doc = json.loads(host_proc.stdout)
            container_doc = json.loads(container_proc.stdout)
            self.assertEqual(host_doc["status"], container_doc["status"])
            self.assertEqual(host_doc["policy"]["decision"], container_doc["policy"]["decision"])
            self.assertEqual(host_doc["policy"]["execution"], container_doc["policy"]["execution"])
            self.assertEqual(host_doc["policy"]["operations"], container_doc["policy"]["operations"])

            out_host = work / "out_host.dcm"
            self.assertTrue(out_host.exists())
            # The container's output is owned by its own non-root UID
            # (0600, inherited from tempfile.mkstemp -- see
            # _read_container_file's docstring) and is read back through a
            # follow-up container invocation, not a direct host-side
            # filesystem read.
            container_bytes = _read_container_file(work, "/work/out_container.dcm")

            host_bytes = out_host.read_bytes()
            host_hash = hashlib.sha256(host_bytes).hexdigest()
            container_hash = hashlib.sha256(container_bytes).hexdigest()
            self.assertEqual(host_hash, container_hash,
                              f"host={host_hash} container={container_hash} -- byte identity is a "
                              "hard S1.7 criterion")

            _reparse_cleanly(host_bytes)
            _reparse_cleanly(container_bytes)

    def test_successful_transform_matches_direct_library_call(self):
        from fastdicomstructure import configuration as cfg, execution

        with _work_dir() as work:
            
            (work / "in.dcm").write_bytes(_build_fixture())
            container_cfg = work / "config_container.json"
            container_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, "/work/in.dcm", "/work/out_container.dcm")))

            container_proc = _run_container_cli(
                work, "--config", "/work/config_container.json", "--json")
            self.assertEqual(container_proc.returncode, 0, container_proc.stderr)
            container_doc = json.loads(container_proc.stdout)

            direct_cfg_doc = _config_doc(_ACCEPT_AND_ANONYMIZE_POLICY_DOC,
                                          work / "in.dcm", work / "out_direct.dcm")
            direct_config = cfg.load_configuration(direct_cfg_doc)
            direct_result = execution.run_configured(direct_config)

            self.assertEqual(container_doc["policy"]["decision"], direct_result.policy_result.decision.value)
            self.assertEqual(container_doc["policy"]["execution"], direct_result.policy_result.execution.value)
            container_bytes = _read_container_file(work, "/work/out_container.dcm")
            self.assertEqual(container_bytes, (work / "out_direct.dcm").read_bytes())

    def test_pydicom_validates_both_outputs(self):
        try:
            import pydicom
        except ImportError:
            self.skipTest("pydicom not available in this environment")

        with _work_dir() as work:
            
            (work / "in.dcm").write_bytes(_build_fixture())
            host_cfg = work / "config_host.json"
            host_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, work / "in.dcm", work / "out_host.dcm")))
            container_cfg = work / "config_container.json"
            container_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, "/work/in.dcm", "/work/out_container.dcm")))

            self.assertEqual(_run_host_cli("--config", str(host_cfg)).returncode, 0)
            self.assertEqual(_run_container_cli(
                work, "--config", "/work/config_container.json").returncode, 0)

            ds_host = pydicom.dcmread(str(work / "out_host.dcm"))
            ds_container = pydicom.dcmread(io.BytesIO(_read_container_file(work, "/work/out_container.dcm")))
            for ds in (ds_host, ds_container):
                self.assertEqual(str(ds.PatientName), "ANONYMIZED")
                self.assertEqual(ds.Modality, "CT")

    def test_dcmtk_dcmdump_validates_both_outputs(self):
        dcmdump = shutil.which("dcmdump")
        if dcmdump is None:
            self.skipTest("dcmdump (DCMTK) not available in this environment")

        with _work_dir() as work:
            
            (work / "in.dcm").write_bytes(_build_fixture())
            host_cfg = work / "config_host.json"
            host_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, work / "in.dcm", work / "out_host.dcm")))
            container_cfg = work / "config_container.json"
            container_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, "/work/in.dcm", "/work/out_container.dcm")))

            self.assertEqual(_run_host_cli("--config", str(host_cfg)).returncode, 0)
            self.assertEqual(_run_container_cli(
                work, "--config", "/work/config_container.json").returncode, 0)

            dump_host = subprocess.run([dcmdump, str(work / "out_host.dcm")],
                                        capture_output=True, text=True, timeout=30)
            self.assertEqual(dump_host.returncode, 0, dump_host.stderr)
            self.assertIn("ANONYMIZED", dump_host.stdout)

            # dcmdump needs a real path host-side-readable path; the
            # container's own output is copied out via _read_container_file
            # (see its docstring) into a fresh, host-owned temp file first.
            container_bytes = _read_container_file(work, "/work/out_container.dcm")
            copy_path = work / "out_container_copy.dcm"
            copy_path.write_bytes(container_bytes)
            dump_container = subprocess.run([dcmdump, str(copy_path)],
                                             capture_output=True, text=True, timeout=30)
            self.assertEqual(dump_container.returncode, 0, dump_container.stderr)
            self.assertIn("ANONYMIZED", dump_container.stdout)


@unittest.skipUnless(_docker_available(), _DOCKER_SKIP_REASON)
class ProbeBTest(unittest.TestCase):
    def test_policy_rejection_equivalence(self):
        with _work_dir() as work:
            
            (work / "in.dcm").write_bytes(_build_fixture())
            host_cfg = work / "config_host.json"
            host_cfg.write_text(json.dumps(_config_doc(
                _REJECTING_POLICY_DOC, work / "in.dcm", work / "out_host.dcm")))
            container_cfg = work / "config_container.json"
            container_cfg.write_text(json.dumps(_config_doc(
                _REJECTING_POLICY_DOC, "/work/in.dcm", "/work/out_container.dcm")))

            host_proc = _run_host_cli("--config", str(host_cfg), "--json")
            container_proc = _run_container_cli(work, "--config", "/work/config_container.json", "--json")

            self.assertEqual(host_proc.returncode, 14)
            self.assertEqual(container_proc.returncode, 14)
            self.assertEqual(json.loads(host_proc.stdout)["status"],
                              json.loads(container_proc.stdout)["status"])
            self.assertFalse((work / "out_host.dcm").exists())
            self.assertFalse((work / "out_container.dcm").exists())


@unittest.skipUnless(_docker_available(), _DOCKER_SKIP_REASON)
class ProbeCTest(unittest.TestCase):
    def test_malformed_dicom_equivalence(self):
        with _work_dir() as work:
            
            (work / "in.dcm").write_bytes(b"not a dicom file at all")
            host_cfg = work / "config_host.json"
            host_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, work / "in.dcm", work / "out_host.dcm")))
            container_cfg = work / "config_container.json"
            container_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, "/work/in.dcm", "/work/out_container.dcm")))

            host_proc = _run_host_cli("--config", str(host_cfg), "--json")
            container_proc = _run_container_cli(work, "--config", "/work/config_container.json", "--json")

            self.assertEqual(host_proc.returncode, 13)
            self.assertEqual(container_proc.returncode, 13)
            self.assertFalse((work / "out_host.dcm").exists())
            self.assertFalse((work / "out_container.dcm").exists())


@unittest.skipUnless(_docker_available(), _DOCKER_SKIP_REASON)
class ProbeDTest(unittest.TestCase):
    def test_existing_destination_overwrite_false_equivalence(self):
        with _work_dir() as work:
            
            (work / "in.dcm").write_bytes(_build_fixture())
            (work / "out_host.dcm").write_bytes(b"pre-existing host content")
            (work / "out_container.dcm").write_bytes(b"pre-existing container content")

            host_cfg = work / "config_host.json"
            host_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, work / "in.dcm", work / "out_host.dcm")))
            container_cfg = work / "config_container.json"
            container_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, "/work/in.dcm", "/work/out_container.dcm")))

            host_proc = _run_host_cli("--config", str(host_cfg), "--json")
            container_proc = _run_container_cli(work, "--config", "/work/config_container.json", "--json")

            self.assertEqual(host_proc.returncode, 17)
            self.assertEqual(container_proc.returncode, 17)
            self.assertEqual((work / "out_host.dcm").read_bytes(), b"pre-existing host content")
            self.assertEqual((work / "out_container.dcm").read_bytes(), b"pre-existing container content")


@unittest.skipUnless(_docker_available(), _DOCKER_SKIP_REASON)
class ProbeETest(unittest.TestCase):
    def test_source_destination_collision_equivalence(self):
        with _work_dir() as work:
            
            original = _build_fixture()
            (work / "same.dcm").write_bytes(original)

            container_cfg = work / "config_container.json"
            container_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, "/work/same.dcm", "/work/same.dcm")))
            host_cfg = work / "config_host.json"
            host_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, work / "same.dcm", work / "same.dcm")))

            host_proc = _run_host_cli("--config", str(host_cfg), "--json")
            self.assertEqual(host_proc.returncode, 11)
            self.assertEqual((work / "same.dcm").read_bytes(), original)

            container_proc = _run_container_cli(work, "--config", "/work/config_container.json", "--json")
            self.assertEqual(container_proc.returncode, 11)
            self.assertEqual((work / "same.dcm").read_bytes(), original)


@unittest.skipUnless(_docker_available(), _DOCKER_SKIP_REASON)
class ProbeFTest(unittest.TestCase):
    def test_destination_less_policy_check_equivalence(self):
        with _work_dir() as work:
            
            (work / "in.dcm").write_bytes(_build_fixture())

            host_cfg = work / "config_host.json"
            host_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, work / "in.dcm",
                destination_path=None, include_destination=False)))
            container_cfg = work / "config_container.json"
            container_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, "/work/in.dcm",
                destination_path=None, include_destination=False)))

            host_proc = _run_host_cli("--config", str(host_cfg), "--json")
            container_proc = _run_container_cli(work, "--config", "/work/config_container.json", "--json")

            self.assertEqual(host_proc.returncode, 0)
            self.assertEqual(container_proc.returncode, 0)
            self.assertEqual(sorted(p.name for p in work.iterdir()),
                              sorted(["in.dcm", "config_host.json", "config_container.json"]))


@unittest.skipUnless(_docker_available(), _DOCKER_SKIP_REASON)
class ProbeGTest(unittest.TestCase):
    def test_invalid_configuration_equivalence(self):
        with _work_dir() as work:
            
            doc = {"schema": "fastdicomstructure-configuration", "schema_version": 1,
                   "policy": {"name": "t"}}  # missing required "version"
            (work / "config.json").write_text(json.dumps(doc))

            host_proc = _run_host_cli("--config", str(work / "config.json"), "--json")
            container_proc = _run_container_cli(work, "--config", "/work/config.json", "--json")

            self.assertEqual(host_proc.returncode, 10)
            self.assertEqual(container_proc.returncode, 10)


@unittest.skipUnless(_docker_available(), _DOCKER_SKIP_REASON)
class ProbeHTest(unittest.TestCase):
    def test_unknown_adapter_type_equivalence(self):
        with _work_dir() as work:
            
            doc = {"schema": "fastdicomstructure-configuration", "schema_version": 1,
                   "policy": {"name": "t", "version": "1.0"},
                   "source": {"type": "future-adapter", "options": {}}}
            (work / "config.json").write_text(json.dumps(doc))

            host_proc = _run_host_cli("--config", str(work / "config.json"), "--json")
            container_proc = _run_container_cli(work, "--config", "/work/config.json", "--json")

            self.assertEqual(host_proc.returncode, 11)
            self.assertEqual(container_proc.returncode, 11)


@unittest.skipUnless(_docker_available(), _DOCKER_SKIP_REASON)
class ProbeITest(unittest.TestCase):
    def test_source_acquisition_failure_equivalence(self):
        with _work_dir() as work:
            
            # No in.dcm ever written -- the configured source is missing.
            host_cfg = work / "config_host.json"
            host_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, work / "in.dcm", work / "out_host.dcm")))
            container_cfg = work / "config_container.json"
            container_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, "/work/in.dcm", "/work/out_container.dcm")))

            host_proc = _run_host_cli("--config", str(host_cfg), "--json")
            container_proc = _run_container_cli(work, "--config", "/work/config_container.json", "--json")

            self.assertEqual(host_proc.returncode, 12)
            self.assertEqual(container_proc.returncode, 12)


@unittest.skipUnless(_docker_available(), _DOCKER_SKIP_REASON)
class ProbeJTest(unittest.TestCase):
    def test_destination_failure_equivalence(self):
        """An unwritable/invalid destination condition, chosen so it is
        meaningful under the container's own non-root (uid 1000) user: a
        destination directory that does not exist (mkstemp fails
        identically regardless of which UID is asking) -- portable across
        both host and container invocations without depending on host-side
        ownership of a directory the container user does not own."""
        with _work_dir() as work:
            
            (work / "in.dcm").write_bytes(_build_fixture())

            host_cfg = work / "config_host.json"
            host_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, work / "in.dcm",
                work / "does-not-exist" / "out_host.dcm")))
            container_cfg = work / "config_container.json"
            container_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, "/work/in.dcm",
                "/work/does-not-exist/out_container.dcm")))

            host_proc = _run_host_cli("--config", str(host_cfg), "--json")
            container_proc = _run_container_cli(work, "--config", "/work/config_container.json", "--json")

            self.assertEqual(host_proc.returncode, 17)
            self.assertEqual(container_proc.returncode, 17)
            self.assertFalse((work / "does-not-exist").exists())


@unittest.skipUnless(_docker_available(), _DOCKER_SKIP_REASON)
class ProbeKTest(unittest.TestCase):
    def test_privacy_no_regression_in_container(self):
        with _work_dir() as work:
            
            sensitive_dir = work / _SENSITIVE_NAME
            sensitive_dir.mkdir()
            (sensitive_dir / "in.dcm").write_bytes(_build_fixture(patient_name=_SENSITIVE_NAME.encode()))

            # rejected -- the sensitive DICOM value is never transformed
            container_cfg = work / "config_container.json"
            container_cfg.write_text(json.dumps(_config_doc(
                _REJECTING_POLICY_DOC, f"/work/{_SENSITIVE_NAME}/in.dcm",
                f"/work/{_SENSITIVE_NAME}/out.dcm")))

            proc = _run_container_cli(work, "--config", "/work/config_container.json", "--json")
            self.assertNotIn(_SENSITIVE_NAME, proc.stdout)
            self.assertNotIn(_SENSITIVE_NAME, proc.stderr)

            proc_text = _run_container_cli(work, "--config", "/work/config_container.json")
            self.assertNotIn(_SENSITIVE_NAME, proc_text.stdout)
            self.assertNotIn(_SENSITIVE_NAME, proc_text.stderr)

    def test_config_path_disclosure_unchanged_in_container(self):
        with _work_dir() as work:
            
            proc = _run_container_cli(work, "--config", "/work/does-not-exist.json")
            self.assertEqual(proc.returncode, 2)
            self.assertIn("/work/does-not-exist.json", proc.stderr)


@unittest.skipUnless(_docker_available(), _DOCKER_SKIP_REASON)
class ProbeLTest(unittest.TestCase):
    def test_no_network_execution(self):
        with _work_dir() as work:
            
            (work / "in.dcm").write_bytes(_build_fixture())
            container_cfg = work / "config_container.json"
            container_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, "/work/in.dcm", "/work/out.dcm")))

            proc = _run_container_cli(work, "--config", "/work/config_container.json", "--json",
                                       network="none")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((work / "out.dcm").exists())
            doc = json.loads(proc.stdout)
            self.assertEqual(doc["status"], "succeeded")


@unittest.skipUnless(_docker_available(), _DOCKER_SKIP_REASON)
class OptionalReadOnlyRootTest(unittest.TestCase):
    """Informative only -- not a required S1.7 freeze criterion."""

    def test_read_only_root_filesystem(self):
        with _work_dir() as work:
            
            (work / "in.dcm").write_bytes(_build_fixture())
            container_cfg = work / "config_container.json"
            container_cfg.write_text(json.dumps(_config_doc(
                _ACCEPT_AND_ANONYMIZE_POLICY_DOC, "/work/in.dcm", "/work/out.dcm")))

            proc = _run_container_cli(work, "--config", "/work/config_container.json", "--json",
                                       read_only=True)
            # Recorded, not asserted as a hard requirement -- see the
            # implementation report for the observed result either way.
            self.assertIn(proc.returncode, (0, 1, 2, 12, 13, 14, 15, 16, 17),
                          f"unexpected returncode {proc.returncode}: {proc.stderr}")


@unittest.skipUnless(_docker_available(), _DOCKER_SKIP_REASON)
class RuntimeImageBoundaryTest(unittest.TestCase):
    def test_runtime_image_has_no_compiler_toolchain(self):
        proc = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "/bin/sh", IMAGE, "-c",
             "which cc g++ cmake ninja 2>/dev/null; true"],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.stdout.strip(), "")

    def test_runtime_image_has_no_qualification_tooling(self):
        which_proc = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "which", IMAGE, "dcmdump"],
            capture_output=True, text=True, timeout=30)
        self.assertNotEqual(which_proc.returncode, 0)  # dcmdump absent -> `which` fails
        self.assertEqual(which_proc.stdout.strip(), "")

        pydicom_proc = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "python", IMAGE, "-c", "import pydicom"],
            capture_output=True, text=True, timeout=30)
        self.assertNotEqual(pydicom_proc.returncode, 0)
        self.assertIn("ModuleNotFoundError", pydicom_proc.stderr)

    def test_runtime_user_is_non_root(self):
        proc = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "id", IMAGE],
            capture_output=True, text=True, timeout=30)
        self.assertNotIn("uid=0", proc.stdout)

    def test_structure_and_attrs_import_from_installed_locations(self):
        proc = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "python", IMAGE, "-c",
             "import fastdicomstructure as fds, fastdicomattrs as fda; "
             "print(fds.__file__); print(fda.__file__); print(fda._find_library())"],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.strip().splitlines()
        self.assertIn("site-packages/fastdicomstructure", lines[0])
        self.assertIn("site-packages/fastdicomattrs", lines[1])
        self.assertEqual(lines[2], "/usr/local/lib/libfastdicomattrs_c.so")


if __name__ == "__main__":
    unittest.main()
