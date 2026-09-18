# S1.7 Implementation Report — Container Portability

## 1. Starting commits

| Item | Commit |
|---|---|
| fastDICOMattrs | `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6` (unchanged throughout S1.7) |
| fastDICOMstructure | `9b84a2a2b16dade32d6f3f2d6b033e7e89852e9a` (S1.6 freeze) |

Both verified via `git rev-parse HEAD` immediately before implementation began; the working tree
contained only the accepted, unimplemented `S1_7_CONTAINER_PORTABILITY_DESIGN_CHECKPOINT.md`.
Baseline: `python3 -m pytest tests/python/` — **278/278 passing**.

## 2. Exact files changed/added

```text
Dockerfile                                                NEW
.dockerignore                                             NEW
pyproject.toml                                            NEW
tests/python/test_container.py                            NEW (21 tests)
docs/architecture/S1_7_CONTAINER_PORTABILITY_IMPLEMENTATION_REPORT.md   NEW (this report)
docs/architecture/PRODUCT_CAPABILITY_MAP.md               MODIFIED -- P5.3 promoted, P6.4 annotated
```

**Untouched, verified by SHA-256 hash comparison before and after implementation (section 8)**:
`policy.py`, `configuration.py`, `execution.py`, `adapters/__init__.py`, `adapters/filesystem.py`,
`cli.py`, `__main__.py`. No file in `fastDICOMattrs` or `fastDICOMgateway` was touched.

## 3. Packaging implementation

Added a minimal `pyproject.toml` (setuptools backend, 18 lines): package name
`fastdicomstructure`, `requires-python = ">=3.9"` (the actual evidence-based floor — every module
uses `from __future__ import annotations`, but `policy.py`'s module-level `Tag = tuple[int, int]`
type-alias assignment is a real runtime expression using builtin-generic subscripting, which
requires Python ≥3.9 regardless of that future-import), `package-dir`/`packages.find` pointing at
`python/fastdicomstructure`. **No dependency on `fastdicomattrs` is declared** (it is not
PyPI-installable — declaring it would create an unresolvable requirement, not a real one). **No
console-script entry point** — `python -m fastdicomstructure` remains the sole documented
invocation. No application-semantic or Docker-specific content of any kind.

**Verified independently, outside the container build**: `python -m build --wheel` produced
`fastdicomstructure-0.1.0-py3-none-any.whl` (52,881 bytes) containing exactly the eight expected
modules; installed into a clean, freshly-created virtualenv via `pip install <wheel>` (no
`PYTHONPATH`, no editable flag); `pip show fastdicomstructure` confirmed a real, non-editable
registration (`Location: .../site-packages`, a real `dist-info` directory, no `.pth`/editable
marker). Importing `fastdicomstructure` from that clean venv with `PYTHONPATH` explicitly unset
failed only at the *expected*, already-documented point — `ModuleNotFoundError: No module named
'fastdicomattrs'` — confirming Structure itself imports correctly as an installed package; the
only remaining unmet need is attrs, exactly as anticipated (section 30 below).

## 4. Docker architecture

Implemented the selected two-stage architecture (Candidate B) exactly as designed, adapted directly
from `fastDICOMgateway`'s own already-validated Dockerfile:

```text
attrs-builder (python:3.12-slim-bookworm + build-essential/cmake/ninja-build)
    COPY --from=attrs .   (named build context)
    cmake -DFDS_BUILD_TESTS=OFF -DFDS_BUILD_BENCH=OFF -DFDS_BUILD_ABI=ON
    cmake --install --prefix /opt/fastdicomattrs-install
    plain-copy python/fastdicomattrs alongside it
        |
        v
runtime (python:3.12-slim-bookworm + libstdc++6 only)
    COPY compiled .so -> /usr/local/lib ; ldconfig
    COPY attrs' Python module -> site-packages (no wheel exists for it)
    COPY pyproject.toml/README/LICENSE/python -> pip install .  (Structure's own real wheel)
    rm -rf the build context copy afterward
    ENV FASTDICOMATTRS_LIB=/usr/local/lib/libfastdicomattrs_c.so, PYTHONDONTWRITEBYTECODE=1, PYTHONUNBUFFERED=1
    non-root user fdsuser (uid/gid 1000, no home, no login shell)
    WORKDIR /work
    ENTRYPOINT ["python", "-m", "fastdicomstructure"]
```

## 5. Exact build command

```bash
DOCKER_BUILDKIT=1 docker build -f Dockerfile \
    --build-context attrs=../fastDICOMattrs \
    -t fastdicomstructure:s1.7 .
```

Executed from within the `fastDICOMstructure` repository root, exactly as the design checkpoint
specified. Build succeeded on the first attempt (both stages), producing image
`fastdicomstructure:s1.7` (verified: `docker images` lists it, **136MB**, characterization only —
no size target was set or claimed).

## 6. Runtime invocation

```bash
docker run --rm -v <host-work-dir>:/work fastdicomstructure:s1.7 run --config /work/config.json --json
```

Verified directly: `ENTRYPOINT ["python", "-m", "fastdicomstructure"]` is exec-form with no shell;
`docker run IMAGE run --config ... --json` reaches `fastdicomstructure.cli.main()`'s own `argv`
unmodified — confirmed by every probe below observing exactly the exit codes and structured output
the frozen S1.6 CLI itself defines, with no translation layer anywhere.

## 7. Image/runtime dependency characterization

Confirmed directly (not assumed): the runtime image contains no C++ compiler, CMake, or Ninja
(`which cc g++ cmake ninja` returns nothing inside the running container); no pydicom or DCMTK
(`import pydicom` raises `ModuleNotFoundError`; `which dcmdump` fails); the runtime user is
non-root (`id` reports `uid=1000(fdsuser)`); `fastdicomstructure`/`fastdicomattrs` both import from
real installed locations (`/usr/local/lib/python3.12/site-packages/...`), and
`fastdicomattrs._find_library()` resolves to exactly `/usr/local/lib/libfastdicomattrs_c.so` — the
explicitly-set `FASTDICOMATTRS_LIB` override, not the repo-relative development search path. No
cloud SDK, credentials, test corpus, or gateway code exists in the image (never copied in; excluded
from the build context by `.dockerignore` and the Dockerfile's own selective `COPY` list).

## 8. Protected-file hash verification

SHA-256 recorded before any implementation work and re-verified after implementation and
qualification were complete:

```text
PASS -- all seven hashes identical before/after:
    policy.py, configuration.py, execution.py,
    adapters/__init__.py, adapters/filesystem.py,
    cli.py, __main__.py
```

No protected application-semantic file required any change for container portability to work — the
central S1.7 hypothesis held.

## 9. Probe A–L results (complete table)

All twelve probes implemented in `tests/python/test_container.py`; **21/21 container tests pass**.

| Probe | Result | Exit code (host / container) |
|---|---|---|
| A — successful transform | PASS — matching structured JSON, both outputs reparse cleanly, pydicom confirms both, DCMTK confirms both, `sha256` identical (section 13), and container output additionally matches a direct in-process `execution.run_configured` call byte-for-byte | 0 / 0 |
| B — policy rejection | PASS — matching `status`, no destination created either side | 14 / 14 |
| C — malformed DICOM | PASS — no destination created either side | 13 / 13 |
| D — existing destination, `overwrite=false` | PASS — pre-existing destination content proven unchanged on both sides (distinct literals per side, both preserved exactly) | 17 / 17 |
| E — source/destination collision | PASS — source content proven byte-unchanged on both sides | 11 / 11 |
| F — destination-less policy-check mode | PASS — directory contents proven to contain only the source/config files afterward, no output DICOM either side | 0 / 0 |
| G — invalid Configuration V1 | PASS | 10 / 10 |
| H — unknown adapter type | PASS | 11 / 11 |
| I — source acquisition failure | PASS | 12 / 12 |
| J — destination failure (missing destination directory — meaningful under the non-root container user, portable regardless of host-side directory ownership) | PASS — no partial output either side | 17 / 17 |
| K — privacy | PASS — sensitive literal (in a DICOM value and in a bind-mounted path component) confirmed absent from container stdout/stderr; the approved narrow `--config`-path exception confirmed still working identically in the container | n/a |
| L — no-network execution (`--network none`) | PASS — identical successful result to the networked run | 0 |

## 10. Native/container exit-code comparison

Every probe above asserts host and container exit codes directly against each other (not merely
against an expected constant) — all pairs equal. No remapping layer exists (exec-form entrypoint,
section 6).

## 11. Structured-result comparison

For every probe with a `--json`-capable outcome, the `status`, `policy.decision`,
`policy.execution`, and `policy.operations` fields were compared field-by-field between host and
container invocations (Probe A/B) and independently against a direct `execution.run_configured`
call (Probe A's second test) — all equal.

## 12. Destination-behavior comparison

Verified per-probe: Probe A (destination created both sides, content proven equal — section 13);
Probe B/C/F (destination absent both sides, or no output DICOM at all for F); Probe D (pre-existing
destination content byte-preserved both sides, using distinct literals to prove neither side
touched the other's file); Probe E (source content byte-preserved both sides); Probe J (no partial
output either side, target directory confirmed absent).

## 13. SHA-256 differential evidence

**Hard criterion, met.** For Probe A's successful transform:

```text
sha256(host_output)      == sha256(container_output)
```

verified equal in `test_successful_transform_host_container_equivalence` (both computed and
compared programmatically, not eyeballed) — no environmental nondeterminism was observed, matching
the design checkpoint's own expectation. A third comparison (container output vs. a direct
in-process `execution.run_configured` call on the same input) is also byte-identical
(`test_successful_transform_matches_direct_library_call`).

**One genuine implementation-time finding, directly relevant to this evidence and reported rather
than hidden**: `FilesystemDestination`'s published output file inherits `tempfile.mkstemp`'s own
default restrictive permission mode (`0600`) through the temp-file-then-publish sequence — this is
existing, frozen, unmodified S1.5 behavior, verified directly (`ls -l` inside a manual debug session
showed `-rw------- 1 <container-uid> <container-uid>` on a container-written output file). A
consequence: **a file the container's `fdsuser` (uid 1000) writes onto a bind mount is not
host-user-readable unless the host user happens to share that UID.** This is not a defect in the
image or the CLI — it is `FilesystemDestination`'s own conservative, already-frozen choice, now
visible for the first time because S1.7 is the first place a *different* UID (the host operator)
needs to read the container's output back. The qualification suite works around this correctly (not
around a bug) by reading container-written files through a second, cheap container invocation
(`docker run --entrypoint cat`, running as the same `fdsuser` that owns the file) rather than a
direct host-side filesystem read — documented in `_read_container_file`'s own docstring in
`tests/python/test_container.py`. This is recorded here as an operational note for future operators:
a deployment wanting host-side read access to container-produced output should either match UIDs
(e.g. `docker run --user $(id -u):$(id -g)`) or read the output back through a container invocation.

## 14. attrs/pydicom/DCMTK validation evidence

Both host and container Probe-A outputs independently confirmed by **pydicom**
(`PatientName == "ANONYMIZED"`, `Modality == "CT"`) and **DCMTK `dcmdump`** (return code 0, output
contains `"ANONYMIZED"`) — both tools invoked from the host qualification environment only, never
present inside the runtime image (section 7). Both outputs also pass attrs' own lossless
self-reparse check with no blocking diagnostics.

## 15. Privacy evidence

A known sensitive literal (`"Zbigniew^Sekretny^SSN-123-45-6789"`) was injected into (a) a rejected
object's own `PatientName` DICOM value and (b) a bind-mounted directory-name path component;
confirmed absent from container stdout and stderr in both JSON and human-readable rendering —
matching S1.6's own established privacy contract exactly, with no regression introduced by
containerization. The one approved narrow exception (an unreadable `--config` argument's own path
may be echoed) was separately confirmed to still work identically inside the container, and to
remain scoped only to that one argument.

## 16. `--network none` evidence

Probe L: the full successful-transform scenario re-run with `docker run --network none` produced
an identical result (exit 0, identical `status: "succeeded"`, destination file created) to the
networked run — direct evidence the filesystem-only execution path needs no network access.

## 17. Optional `--read-only` result

**Attempted, not required for freeze.** `docker run --read-only` (only the bind-mounted `/work`
writable) with `PYTHONDONTWRITEBYTECODE=1` already set: a full successful transform completed with
exit 0 and correct output, confirmed both via the automated probe (`OptionalReadOnlyRootTest`) and
an isolated manual re-check with a clean directory. No issue was found — `tempfile.mkstemp`'s only
required writable location (the destination's own directory) is exactly the bind-mounted, writable
`/work`; nothing else in the CLI's execution path needs to write anywhere else.

## 18. Full test-suite result

```text
Baseline (S1.6 freeze, before S1.7 work):  278 passing
After S1.7 implementation:                 299 passing (278 pre-existing + 21 new, all in
                                            tests/python/test_container.py)
```

No existing test file was modified. Every container-dependent test is individually gated by
`@unittest.skipUnless(_docker_available(), ...)` (checking both `docker` on `PATH` and the
`fastdicomstructure:s1.7` image's presence) — none is hidden or silently disabled; in this
qualification environment, Docker and the built image were both available, so all 21 ran to
completion (none skipped). pydicom- and DCMTK-dependent sub-probes within Probe A are separately,
individually gated the same established way (both tools were available here, so both ran).

## 19. Product Capability Map disposition

- **P5.3 (Container)**: `CANDIDATE` → **`CURRENT`** — the row's own stated success criterion ("a
  containerized invocation produces byte-identical output to a local one") is directly evidenced by
  section 13.
- **P6.4 (Deployment portability)**: left `CANDIDATE`, annotated — two of its three prerequisites
  (P5.2, P5.3) are now demonstrated; P5.4 (cloud/serverless) remains outstanding. Not promoted.
- **Left unchanged, as required**: P5.4, P5.5, P6.3, and every other row — none is touched or
  promotable by S1.7's own scope.

## 20. Deviations from the checkpoint

None of substance. The selected architecture (Candidate B), base image, non-root user, named build
context, and entrypoint shape were implemented exactly as designed. Two small, non-architectural
refinements were needed during qualification-harness construction, neither touching any protected
file or the image itself:

1. Test-harness work directories needed `chmod 0o777` immediately after creation — `tempfile.
   TemporaryDirectory()`'s default `0o700` mode is invisible to the container's non-root UID. A
   qualification-setup detail, not a design deviation.
2. Reading a container-written output file back on the host requires going through a second
   container invocation rather than a direct filesystem read, per section 13's own finding — this
   is `FilesystemDestination`'s existing, frozen behavior surfacing for the first time, not a change
   to it.

## 21. Limitations/non-claims

Exactly as scoped, none exceeded: no cloud portability, no Cloud Run compatibility, no
multi-architecture portability, no macOS/Windows Docker Desktop equivalence claim, no scalability,
no streaming, no protocol interoperability, no performance superiority claim, no comprehensive
container security claim, no supply-chain reproducibility/SBOM/signing/provenance claim, and attrs'
own wheel/independent-installability gap remains unfixed (continues via the CMake +
`FASTDICOMATTRS_LIB` + plain-copy technique, exactly as the design checkpoint scoped). Build/image
size/startup timing are recorded as characterization only (section 5, 137MB image; qualification
suite completed in ~18–22s including all Docker invocations) — no performance or scalability claim
is made from any of it.

## 22. Recommendation

**READY FOR FREEZE.** All twelve probes pass; the hard byte-identity criterion is met; every
protected file is confirmed byte-for-byte unchanged; the full test suite (299 tests) passes; the
runtime-image boundary (no compiler, no qualification tooling, non-root user, installed-package
imports) is directly verified, not assumed. This increment has not been committed — per
authorization, it is presented here for independent review before any freeze commit is made.
