# S1.7 Design Checkpoint — Container Portability

**Status: ANALYSIS AND DESIGN ONLY.** No production code, Dockerfile, or container was created; no
test was modified; no frozen file was touched. Every claim below was verified against the actual
frozen source of all three repositories (read directly for this checkpoint), not recalled from
memory.

## 1. Verified starting state

| Item | Commit | Verified |
|---|---|---|
| fastDICOMattrs | `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6` | matches, clean |
| fastDICOMstructure S1.6 | `9b84a2a2b16dade32d6f3f2d6b033e7e89852e9a` | matches, HEAD, clean |

`python3 -m pytest tests/python/` — **278/278 passing**. No discrepancy found. The historical S1.6
implementation report's internal self-reference artifact (`7564cf7`, a pre-amend commit hash) is
noted per the authorization and not touched — `9b84a2a` remains the authoritative S1.6 freeze.

## 2. Current packaging inventory

Neither `fastDICOMattrs` nor `fastDICOMstructure` has **any** Python packaging metadata
(`pyproject.toml`/`setup.py`/`setup.cfg`) anywhere in either repository (re-confirmed by direct
search). `fastDICOMstructure` has no build system of its own at all (no `CMakeLists.txt`/`Makefile`
— confirmed by direct search; the A0 semantic-engine extraction moved all C++ to attrs). Only
`fastDICOMgateway` has a `pyproject.toml` (hatchling-based) and, critically, **an existing,
production-validated Dockerfile** (introduced in its own M3/M4 increments) — this is the single most
important piece of prior evidence for this checkpoint, examined in full in section 3.

## 3. attrs build/install analysis

Directly verified from `fastDICOMattrs/CMakeLists.txt` and `python/fastdicomattrs/__init__.py`:

- CMake ≥3.16, C++20, three build options (`FDS_BUILD_TESTS`/`FDS_BUILD_BENCH`/`FDS_BUILD_ABI`, all
  default `ON`). `cmake --install build --prefix <prefix>` installs the C++ library, the C ABI
  shared library, headers, and a CMake package config via `GNUInstallDirs` (standard `lib`/`include`
  layout) — **this installs a real, standalone compiled artifact**, not a repo-relative hack.
- **The Python binding (`python/fastdicomattrs/__init__.py`) is never installed by CMake at all** —
  it is a plain ctypes wrapper, itself dependency-free (stdlib only), that locates its compiled
  library via a three-tier search: (1) `FASTDICOMATTRS_LIB` environment-variable override (an exact
  path); (2) a small set of repo-relative build-directory names (a pure development convenience,
  documented as such in the source); (3) `ctypes.util.find_library("fastdicomattrs_c")` — a
  standard system-library search (this succeeds if the compiled `.so` was properly installed to a
  loader-visible location, e.g. via `cmake --install` + `ldconfig`).
- **No wheel exists or is built for attrs anywhere in this family.** Attrs is not independently
  `pip install`-able today.
- **`fastDICOMgateway`'s own Dockerfile already solves this cleanly, in production**: a
  `attrs-builder` stage compiles attrs (`-DFDS_BUILD_TESTS=OFF -DFDS_BUILD_BENCH=OFF
  -DFDS_BUILD_ABI=ON`), installs it to `/opt/fastdicomattrs-install`, and separately copies the
  small Python source package alongside it; the runtime stage copies the compiled `.so` into
  `/usr/local/lib`, copies the Python package directly into the base image's own
  `site-packages`, sets `FASTDICOMATTRS_LIB=/usr/local/lib/libfastdicomattrs_c.so` explicitly
  (bypassing the repo-relative search entirely — the intended use of that existing escape hatch,
  not a new invention), and runs `ldconfig`. This is real, already-validated (M3/M4) evidence, not a
  hypothesis.

## 4. Structure build/install analysis

`fastDICOMstructure` is pure Python, has zero build system, and **has no packaging metadata either**
— confirmed by exhaustive search (repeating and reconfirming the identical finding from the S1.6
checkpoint). `python -m fastdicomstructure` on a clean machine today requires: (a) the attrs Python
module and its compiled library discoverable exactly as section 3 describes, and (b) the
`fastdicomstructure` package itself present somewhere on `sys.path` — currently achieved only via
`PYTHONPATH`, sibling-directory convention, or (per gateway's own Dockerfile) a raw copy of the
`python/fastdicomstructure` directory into `site-packages`. **There is no `pip install`-able
Structure package today.** This is a genuine, bounded, real packaging gap (section 30/45's own
"packaging blocker rule" applies directly), not an architectural failure of the execution
boundary itself — nothing in `execution.py`/`cli.py`/`adapters/` depends on this gap; it is purely
about how the already-correct code reaches `sys.path`.

## 5. Precise container-portability definition

**Refined from the prompt's own candidate:**

> A clean, Docker-built Linux (x86_64) container image, built from the two frozen repository states
> under a documented toolchain, can invoke the frozen S1.6 CLI (`python -m fastdicomstructure run
> --config <container-visible-path> [--json]`) against bind-mounted Configuration V1 and DICOM
> files, and produce process exit status, structured result semantics, and destination-file
> behavior identical to native-host execution for equivalent inputs — with the image contributing
> only packaging and environmental binding, never a second DICOM, policy, adapter, configuration, or
> execution path.

Explicitly distinguished (the prompt's own required list):

| Term | S1.7 scope |
|---|---|
| Image buildability | **Tested** — a documented `docker build` from the two frozen repo states succeeds |
| Runtime portability | **Tested narrowly** — one container runtime (Docker Engine), one host platform (Linux x86_64) — not claimed across other OCI runtimes or architectures |
| Execution-semantic equivalence | **Tested directly** — probes A–L, section 31 |
| Filesystem binding | **Tested** — bind-mounted work directory, container-visible paths in Configuration V1 |
| Deployment portability | **Not claimed** — that is the P6.4 row's own broader, multi-prerequisite claim; S1.7 satisfies one prerequisite of it, not the whole thing |
| Cloud portability | **Not claimed at all** — explicitly deferred to a future increment (section 23) |

## 6. Host/container equivalence boundary

Compared, per logical input object and Policy, exactly as specified: process exit code; the
`--json` structured `status`/`policy`/`diagnostic` document; `PolicyResult`/`OperationResult`
semantics (decision, execution, satisfied, count); diagnostic codes/messages; destination
existence/nonexistence; resulting DICOM semantics (attrs self-reparse, pydicom, DCMTK where
practical); resulting DICOM bytes (section 10). Configuration documents are **not** required to be
byte-identical between host and container invocations — only their `source`/`destination` path
strings legitimately differ (host path vs. container-visible bind path); the `policy` section is
identical. This is exactly environmental binding, not a semantic difference (section 8).

## 7. Runtime invocation model

```bash
docker run --rm \
    -v <host-work-dir>:/work \
    <image> \
    run --config /work/config.json --json
```

**`ENTRYPOINT ["python", "-m", "fastdicomstructure"]`, exec-form, no shell, `CMD` left unset.**
Docker appends any arguments given after the image name directly to the `ENTRYPOINT` array — `run
--config /work/config.json --json` reaches the frozen CLI's own `argv` completely unmodified, with
no wrapper script of any kind in between. This is the strongest possible guarantee against
accidental argument reinterpretation: there is no intermediate process to reinterpret anything, by
construction, not by discipline. No wrapper script is introduced, permissible or otherwise — none
was found to be genuinely required by the runtime environment.

## 8. Configuration/path-binding analysis

**No Configuration V1 change is required or recommended.** A host path
(`/home/user/work/input.dcm`) and its container-visible bind-mounted counterpart (`/work/input.dcm`)
are simply two different, equally valid strings for the `source.options.path`/
`destination.options.path` fields Configuration V1 already defines — the container-visible
Configuration document names paths as they appear *from the executing process's own point of view*,
exactly as the host Configuration document already does. This is unconditionally environmental
binding, not a new configuration semantic, and is confirmed by direct inspection:
`adapters/filesystem.py`'s `FilesystemSource`/`FilesystemDestination` never inspect or care whether
a path happens to be under a bind mount — a path is a path. No `host_path`/`container_path`/`mount`/
`volume`/`bucket`/`cloud URI` field is proposed, and none is needed. **No architectural reason was
found to change Configuration V1.**

## 9. Filesystem semantic analysis

S1.5's atomic-publish mechanism (`FilesystemDestination.write`) creates its temporary file via
`tempfile.mkstemp(dir=target.parent)` — **always in the same directory as the final target** — and
only then attempts `os.link` (no-overwrite) or `os.replace` (overwrite). This means the
same-filesystem requirement those two syscalls have is satisfied *by construction*, regardless of
where the **source** happens to be mounted: the temp file and its target always share a directory,
hence always share a filesystem. **No cross-mount hazard exists between source and destination
paths** — a real hazard this checkpoint checked for and did not find, not one assumed away.

The one genuine, worth-documenting constraint: on a **native Linux Docker host** (this checkpoint's
own tested scope, section 33), a bind mount is the same underlying filesystem forwarded into the
container's mount namespace at a different path — `link(2)`/`rename(2)` behave identically to host
execution. This is expected to hold, not merely assumed, because bind mounts on Linux are not a
distinct filesystem type with different semantics, only a different mount-namespace view of the
same one. **Explicitly out of tested scope**: non-Linux Docker Desktop hosts (macOS/Windows), which
proxy bind mounts through gRPC-FUSE/VirtioFS or similar and can have different hard-link behavior —
named as a known limitation (section 36), not solved here, consistent with the Linux-only host
scope (section 33).

Permissions/ownership: the destination directory must be writable by whichever UID the container
process runs as (section 12) — a real, testable, operational constraint, not a redesign; the
existing overwrite=false/true and collision-detection behaviors are otherwise unaffected by
containerization and require no change.

## 10. Base-image alternatives

| Candidate | Assessment |
|---|---|
| `python:3.12-slim-bookworm` | **Recommended** — the exact base image `fastDICOMgateway`'s own already-validated (M3/M4) Dockerfile pins; glibc-based, directly compatible with attrs' glibc-linked C++ build; ships a standard `site-packages` layout; small enough without being minimal-to-the-point-of-missing-tools |
| Alpine (musl libc) | Rejected — attrs is built with a standard glibc/libstdc++ toolchain; rebuilding against musl is untested, adds real risk of subtle ABI/locale/charset behavior differences (this project's own charset-table generation tooling is glibc-era-tested), and buys nothing S1.7 needs |
| Distroless | Rejected for now — no package manager to install `libstdc++6` conveniently, no shell for the (already rejected) case of needing one; a reasonable *later* hardening step once the image is stable, not a first proof |
| Full Debian/Ubuntu (non-slim) | Rejected as unnecessarily large — slim already provides everything needed |

## 11. Build-stage alternatives

**Multi-stage, but only where the split is real** (per section 14's own caution against
cargo-culting): attrs genuinely needs a discardable C++ toolchain (compiler, CMake, Ninja) that must
never reach the runtime image — a real builder/runtime split, already proven by gateway's own
Dockerfile. Structure, being pure Python with the new minimal `pyproject.toml` (section 16), needs
**no discardable toolchain at all** — `pip`/`setuptools`/`wheel` are already present in any standard
Python base image, so building its wheel directly in the runtime stage adds nothing that stage
doesn't already need. **Recommendation: two stages, not three** — an `attrs-builder` stage
(identical in spirit to gateway's own), and a `runtime` stage that both consumes attrs' compiled
artifact and builds+installs Structure's own wheel in the same stage. A third, Structure-only
builder stage was considered and rejected as manufacturing a split with no real toolchain
difference to justify it.

## 12. Wheel/source-install analysis

**attrs**: continues via the CMake-install + `FASTDICOMATTRS_LIB` + plain Python-module copy
technique — i.e., Candidate D-adjacent ("another reproducible mechanism," already proven in
production by gateway). Building a real attrs wheel (a compiled-extension package, requiring
`scikit-build-core`/`cibuildwheel`-class tooling) is a materially larger effort, explicitly
out of S1.7's bounded scope (section 30's packaging-blocker analysis).

**Structure**: **built as a real wheel** in the runtime stage from a new, minimal `pyproject.toml`
(section 16), installed via `pip install <wheel>` — a non-editable, genuine package install. This is
the "artifact boundary that would also make future packaging/distribution cleaner" the prompt asks
for: once this exists, a future increment could trivially also build this wheel outside Docker (CI,
local dev) with zero further Dockerfile change.

## 13. Build-context analysis

Directly reusing gateway's own already-validated pattern: **named BuildKit build contexts**, not a
parent-directory context, not vendoring, not a Git dependency, not requiring a published artifact:

```bash
# from within the fastDICOMstructure repository root
docker build -f Dockerfile \
    --build-context attrs=../fastDICOMattrs \
    -t fastdicomstructure:s1.7 .
```

The Dockerfile's own default build context is `fastDICOMstructure` itself (matching where the
deployable artifact — the CLI — lives, section 39); attrs is named explicitly. This requires no
repository restructuring and states exactly what a builder needs: a checkout of both repositories,
side by side or otherwise, with the relative path given via `--build-context`.

## 14. Runtime-user analysis

**Non-root**, following gateway's own exact, already-validated precedent (a fixed UID/GID, e.g.
1000, no home directory, no login shell). Effects analyzed: mounted `--config`/source input need
only be *readable* by that UID (a host-side permission concern for the operator, not something the
image can or should force); the mounted destination directory must be *writable* by that UID for
`FilesystemDestination`'s temp-file-then-publish sequence to succeed — this is a real, testable
operational constraint (documented, not hidden) rather than a code change; no home directory is
needed since the CLI writes nothing outside the explicitly configured destination and reads nothing
outside the explicitly configured `--config`/source paths. `PYTHONDONTWRITEBYTECODE=1` (matching
gateway's own env var, section 25) avoids any implicit expectation of a writable `site-packages` at
runtime. This is one hardening property, not a comprehensive security claim (per the prompt's own
caution) — it is evaluated here only as far as it affects the actual claim being tested.

## 15. Runtime-network analysis

**Expected answer: no network required.** The filesystem-only S1.5 adapters perform no network I/O
of any kind (verified: `adapters/filesystem.py` imports only `os`/`tempfile`/`pathlib`). Proposed as
**Probe L**: a full successful-transform invocation with `--network none`, verifying identical
exit code/output to a networked run — strong, direct evidence that the filesystem execution path is
genuinely self-contained. Not claimed as a comprehensive sandbox/security property, only as evidence
the tested path needs no network.

## 16. Read-only-root-filesystem analysis

**Optional, informative, not a hard freeze criterion** — evaluated as inexpensive to attempt:
`docker run --read-only` with `PYTHONDONTWRITEBYTECODE=1` already set (avoiding `.pyc` writes) and
only the bind-mounted work directory writable. The one concrete risk identified: `tempfile.mkstemp`
inside `FilesystemDestination` needs a writable *destination* directory, which the bind mount
already provides — it does not need a writable root filesystem anywhere else, so `--read-only`
should not conflict with anything the CLI itself does. Recommended as a bonus qualification probe
if implementation time permits, not required for freeze.

## 17. stdout/stderr/privacy analysis

Docker introduces **no new privacy risk** beyond what S1.6 already qualified: `docker run`'s stdout/
stderr are simply the CLI process's own stdout/stderr, captured by the same operating-system
mechanism as any other process — no Docker-specific logging/formatting layer sits in between for a
foreground `docker run` invocation. The one thing genuinely worth naming explicitly, per the
prompt's own instruction: **unmodeled exceptions (`RollbackError`, any unrecognized exception) still
intentionally produce a raw Python traceback to stderr, unchanged** — this is not altered inside the
container, and should not be. If this traceback behavior becomes a concern for a *long-running
service* deployment shape later (S1.8's Cloud Run Service hypothesis, where a captured-log traceback
might reach a different operational audience than a developer running a local CLI), that is recorded
here as an explicit **carry-forward question for that future increment** — not something S1.7
resolves by silently changing the frozen S1.6 exception contract now.

## 18. Exit-code preservation analysis

Because the `ENTRYPOINT` is exec-form with no shell (section 7), the Python CLI process **is**
container PID 1 directly — `docker run`'s own reported exit code is *exactly* that process's exit
code, with no remapping layer of any kind to introduce drift. Proof design (Probe-driven, section
31): for every practical modeled case (success, rejection, malformed DICOM, configuration error,
adapter resolution error, source failure, destination failure) plus the uncaught-exception case
(exit 1), assert `docker run`'s own exit status equals the corresponding native-host invocation's
exit status for equivalent input.

## 19. Process/signal model

A short-lived, one-shot CLI process, not a daemon — `docker run --rm ... run --config ...` starts,
executes exactly one object, and exits on its own; nothing in this design waits for or depends on
external signal delivery. Being PID 1 has one known, minor Linux-kernel quirk (a process running as
PID 1 does not receive default dispositions for unhandled signals the way a non-PID-1 process
would), but this is irrelevant to a process that exits deterministically under its own control
within the timeframe of a qualification probe — no supervisor, init process, or `docker run --init`
is added, matching the prompt's own explicit rejection of `supervisord`/`systemd`/shell process
managers for a single-process CLI image.

## 20. Runtime image-content boundary

**Included**: `python:3.12-slim-bookworm` base, `libstdc++6` (attrs' only runtime shared-library
dependency), attrs' compiled `libfastdicomattrs_c.so` + its plain Python module (copied, per section
12), Structure's own wheel (installed via `pip`), and nothing else.

**Excluded, explicitly**: the C++ compiler/CMake/Ninja toolchain (discarded after the `attrs-builder`
stage); Git metadata; the test suite and test corpus; pydicom and DCMTK (qualification-only tools,
section 21); `fastDICOMgateway` entirely; any cloud SDK or credentials; Claude/Codex tooling.

## 21. External qualification-tool boundary

**pydicom and DCMTK stay entirely out of the runtime image**, used only in the host qualification
environment — matching this checkpoint's own strong preference and, again, matching
`fastDICOMgateway`'s own already-shipped runtime image, which also excludes both. Qualification
Probes (section 31) run pydicom/DCMTK against the container's *output file* (bind-mounted back onto
the host) from the host process, never from inside the image.

## 22. Reproducibility scope

**Precise claim, not overclaimed**: S1.7 is reproducible from the two frozen repository states
(exact commits, section 1) under a documented container toolchain (a pinned base-image *tag*,
`python:3.12-slim-bookworm`, plus the exact `cmake`/build flags already specified) — **not** a
fully pinned, digest-level, hash-locked supply-chain build. Recorded as pinned: Python version (via
the base-image tag), base-image tag (not yet a content digest — a `@sha256:...` digest pin is a
cheap, recommended future strengthening, not claimed now), attrs commit, Structure commit (both via
the build-context checkouts). Recorded as *not* pinned/attested: transitive OS package versions
pulled by `apt-get install` at build time (`libstdc++6`'s exact version floats with the base image
tag's own update cadence) — a real, named gap, not hidden.

## 23. Cloud Run relationship

**Not designed here, analyzed only as requested.** A short-lived CLI image proves container
packaging, execution equivalence, filesystem binding, and process/exit-code portability — it does
**not** automatically prove compatibility with Cloud Run Service's HTTP lifecycle (no HTTP server
exists in this image at all), Cloud Run Job's own object-acquisition conventions, Cloud Storage
event triggers, DICOMweb/network destinations, cloud identity/credentials, Cloud Run's ephemeral
filesystem semantics, concurrency, or retries. None of these is tested or claimed by S1.7.

## 24. Cloud Run Job hypothesis

**Evaluated, not designed or deployed.** The current execution model — one invocation, one
configured source, one object, zero-or-one destination, then the process exits — is structurally
much closer to **Cloud Run Job** (a container run to completion once per task, with the container's
own exit code determining task success/failure) than to **Cloud Run Service** (which expects a
long-running HTTP listener bound to a platform-supplied `$PORT`, fundamentally mismatched with a CLI
that parses `--config` once and exits). Notably, this family already has *both* deployable shapes
represented, just not on the same artifact: `fastDICOMgateway`'s own Dockerfile is already the
Service-shaped precedent (a real, deployed-to-Cloud-Run uvicorn service); a future Structure CLI
image would be the Job-shaped counterpart. **S1.7's own choices do not foreclose this** — nothing
proposed here (exec-form entrypoint, no HTTP server, filesystem-only I/O) would need to change for
a later Cloud Run Job proof; it would only need Job-specific invocation wiring (e.g., how the task
learns which object to process), which is explicitly S1.8's concern, not S1.7's.

## 25. Host-platform scope

Verified: this qualification environment is **Linux x86_64** (`uname -m` → `x86_64`), with Docker
Engine 28.1.1 available. **No claim is made for ARM64, macOS container runtimes, Windows containers,
or multi-architecture images** — none of these is tested. Multi-arch work is explicitly not part of
S1.7 (strong default, per the prompt): one clean Linux x86_64 target is the whole claim.

## 26. Candidate implementation alternatives

### Candidate A — minimal single-stage image

Copy both repositories' source into one image; install a full C++ toolchain in the *runtime* image
itself; build attrs there; plain-copy Structure. **Rejected**: bloats the runtime image with a
compiler/CMake/Ninja that should never reach it (directly conflicting with section 20's own image
boundary), and does not fix Structure's packaging gap (still a raw source copy, not a real install).

### Candidate B — multi-stage, adapted wheel build (recommended)

An `attrs-builder` stage (identical in spirit to gateway's own, already validated) produces the
compiled artifact + attrs' Python module; a `runtime` stage consumes both and additionally builds
and installs Structure's own new wheel directly (no separate Structure builder stage needed, since
pure Python requires no discardable toolchain — section 11). **Selected.**

### Candidate C — externally prepared artifacts

Require attrs' and Structure's wheels/artifacts to be built entirely *outside* Docker (a separate CI
step), with the Dockerfile only consuming pre-built artifacts. **Rejected for S1.7 specifically**:
this would weaken the "reproducible from the two frozen repository states under a documented
container toolchain" claim (section 22) unless that separate external step were *also* fully
specified and pinned — more infrastructure than this narrow claim needs. A reasonable direction for
later, more mature packaging/distribution work (e.g. once attrs has real `cibuildwheel`-class
tooling), not chosen now.

| Criterion | A | B (selected) | C |
|---|---|---|---|
| Reproducibility | Medium | High | High, but only if the external step is also pinned (not assumed here) |
| Isolation from dev environment | Low (compiler in runtime) | High | Highest |
| Build-context requirements | Simple but wasteful | Two named contexts, documented | Requires an undocumented external pipeline |
| Complexity | Low | Low-medium | Adds an external dependency S1.7 doesn't otherwise need |
| Runtime image cleanliness | Poor | Good | Good |
| Future S1.8 suitability | Poor | Good | Good, but premature |
| Risk of masking packaging defects | High (never really "installs" anything) | Low (Structure gets a real wheel) | Lowest, but at the cost of scope |
| Risk of over-engineering | Low | Low | Medium (solves a problem S1.7 doesn't have yet) |

## 27. Selected architecture

Candidate B: two-stage Docker build (`attrs-builder` → `runtime`), named build contexts
(`--build-context attrs=../fastDICOMattrs`), non-root runtime user, exec-form
`ENTRYPOINT ["python", "-m", "fastdicomstructure"]`, `python:3.12-slim-bookworm` base, Structure
installed as a real wheel built from a new minimal `pyproject.toml`, attrs installed via the
existing CMake+`FASTDICOMATTRS_LIB`+copy technique already proven by `fastDICOMgateway`.

## 28. Anti-pattern disposition

| Anti-pattern | Disposition |
|---|---|
| Copying arbitrary sibling development trees into runtime `PYTHONPATH` | **Rejected** as the mechanism — the runtime never sets `PYTHONPATH`; attrs' *specific, minimal* Python module is placed directly into `site-packages` (matching gateway's own proven pattern), which is a deliberate, narrow, named exception, not "arbitrary trees" |
| `PYTHONPATH` as the primary installation mechanism | **Rejected** for the image; remains fine, unchanged, for host-side development |
| Mounting source repositories at runtime | **Rejected** — only the work directory (config + DICOM files) is ever bind-mounted |
| Editable pip installs in production runtime | **Rejected** — Structure is installed as a real, non-editable wheel |
| Container-specific policy logic | **Rejected** — none introduced |
| Container-specific configuration schema | **Rejected** — Configuration V1 unchanged (section 8) |
| Wrapper that rewrites Configuration V1 | **Rejected** — no wrapper exists |
| Wrapper that remaps CLI exit codes | **Rejected** — exec-form entrypoint, PID 1 is the CLI itself |
| Wrapper that catches `RollbackError` | **Rejected** — unchanged S1.6 exception boundary |
| DICOM parsing in entrypoint | **Rejected** — the entrypoint *is* the frozen CLI, nothing additional |
| Automatic retries | **Rejected** — none added |
| Cloud SDK in S1.7 runtime | **Rejected** — none installed |
| Privileged container | **Rejected** — non-root, no `--privileged` |
| Host networking | **Rejected** — default bridge or `--network none` (Probe L) suffices |
| Embedding credentials | **Rejected** — none needed, filesystem-only |
| Baking test DICOM corpus into runtime | **Rejected** — qualification files are bind-mounted, not baked in |
| Baking configuration into image | **Rejected** — `--config` is always supplied via the mounted work directory |

## 29. Expected implementation diff

```text
fastDICOMstructure/
    Dockerfile                                          NEW
    .dockerignore                                       NEW
    pyproject.toml                                       NEW (minimal packaging metadata only --
                                                          section 30; no console-script entry point,
                                                          no application-semantic content)
    tests/python/test_container.py                       NEW (probes A-L; skips cleanly when Docker
                                                          is unavailable, mirroring the established
                                                          pydicom/dcmdump skip convention)
    docs/architecture/
        S1_7_CONTAINER_PORTABILITY_IMPLEMENTATION_REPORT.md   NEW
        PRODUCT_CAPABILITY_MAP.md                             MODIFIED (P5.3 -> CURRENT, P6.4 annotated)
```

**No change to `policy.py`, `configuration.py`, `execution.py`, `adapters/__init__.py`,
`adapters/filesystem.py`, `cli.py`, or `__main__.py` is expected** — none of these is
application-semantic packaging, and no evidence gathered here requires touching any of them. If
implementation evidence contradicts this, that is a major finding to stop and report, per the
authorization's own instruction — not silently absorbed.

## 30. Packaging blockers

One genuine, bounded packaging gap was found (section 4): **Structure has no installable package
definition.** The required fix — a minimal `pyproject.toml` (name, version, Python-version
requirement, package discovery pointing at `python/fastdicomstructure`; deliberately **no**
console-script entry point, keeping `python -m fastdicomstructure` as the sole documented invocation
per S1.6's own frozen contract) — is small (on the order of 20–30 lines) and does not touch any
application-semantic file. **This is judged small enough to remain part of S1.7 itself; no
`S1.7a`/`S1.7b` split is warranted.** Attrs' own, materially larger packaging gap (no wheel, no
independent installability) is explicitly **not** fixed by S1.7 — it continues via the
already-production-proven CMake+environment-variable+copy technique, recorded as a known,
carried-forward limitation (section 36), not a blocker to this narrower claim.

## 31. Probes A–L

All twelve designed as concrete, executable tests (`tests/python/test_container.py`), each running
both a native-host invocation and an equivalent `docker run` invocation against the same fixture,
comparing the dimensions listed in section 6.

| Probe | Scenario | Compared |
|---|---|---|
| A | Successful transform, real Configuration V1, semantically equivalent host/container documents | exit 0 both; identical structured JSON `status`/`policy` fields; destination exists both; `sha256` of the two output files equal (section 32); both reparse cleanly with attrs; pydicom confirms semantics on both; DCMTK where practical |
| B | Policy rejection (`Require` fails) | identical exit code (14) both; identical `status`; destination absent both |
| C | Malformed DICOM (both the lenient-diagnostic and raised-`FdsError` sub-cases, reusing S1.5/S1.6's own established fixtures) | identical exit code (13) both; no destination either |
| D | Existing destination, `overwrite=false` | identical exit code (17) both; pre-existing destination content unchanged both |
| E | Source/destination collision | identical exit code (11) both; source content unchanged both; no acquisition attempted either |
| F | Destination-less policy-check mode | identical exit 0 both; no output DICOM produced either |
| G | Invalid Configuration V1 | identical exit code (10) both |
| H | Unknown adapter type / invalid options | identical exit code (11) both |
| I | Source acquisition failure (missing file) | identical exit code (12) both |
| J | Destination failure (unwritable/missing target directory) | identical exit code (17) both; no partial output file either |
| K | Privacy | a sensitive literal injected into a DICOM value, a bind-mounted path component, and a simulated failure context — confirmed absent from container stdout/stderr, matching S1.6's own established contract exactly |
| L | No-network execution | Probe A's successful scenario re-run with `--network none`; identical exit code and output to the networked run |

## 32. Byte-identity differential

For Probe A specifically: `sha256(host_output) == sha256(container_output)` is proposed as a
**freeze criterion**, not merely a nice-to-have. No environmental nondeterminism was identified in
the write path (verified: attrs' serialization is a pure function of input bytes + mutations, with
no timestamp, hostname, locale, or random content anywhere in the DICOM write path across S1.1–S1.6)
— if qualification evidence contradicts this expectation, that finding must be reported explicitly,
not silently weakened into a looser "semantically equivalent" comparison. This is stronger evidence
than reparsing alone, and is additionally compared against a direct in-process
`execution.run_configured` call (S1.6's own established differential-qualification convention) as a
third data point, not just host-vs-container.

## 33. Product Capability Map implications

Reviewed the actual current rows (not assumed):

- **P5.3 (Container)**: currently `CANDIDATE` ("structurally unblocked, not demonstrated"). **A
  successful S1.7 implementation, qualified per this checkpoint, would justify promotion to
  `CURRENT`** — its own stated success criterion ("a containerized invocation produces
  byte-identical output to a local one") is exactly what Probe A/section 32 tests.
- **P5.4 (Cloud/serverless)**: remains `CANDIDATE` — no cloud work is performed or claimed.
- **P5.5 (Gateway convergence)**: unaffected, remains `DEFERRED/BLOCKED`.
- **P6.3 (Scalability)**: unaffected, remains `CANDIDATE`.
- **P6.4 (Deployment portability)**: its own listed prerequisite is `P5.2-P5.4`. S1.6 already
  satisfied P5.2; a successful S1.7 would satisfy P5.3 — **two of three prerequisites**, with P5.4
  still outstanding. **Remains `CANDIDATE`**, annotated to record which prerequisites are now met,
  not promoted (matching the row's own current wording exactly, not an assumption).
- No other row is affected.

**Nothing is promoted by this checkpoint** — design only.

## 34. Falsifiable S1.7 claim

> The frozen S1.6 `fastdicomstructure` CLI (`python -m fastdicomstructure run --config <path>
> [--json]`) can execute unchanged inside a Docker-built, clean Linux x86_64 container image,
> against bind-mounted Configuration V1 and DICOM files naming container-visible filesystem paths,
> and — for host and container inputs that are semantically equivalent (identical Policy, identical
> underlying DICOM bytes, container-visible path strings substituted for host paths) — produce
> identical process exit status, identical structured JSON result semantics, identical destination
> existence/nonexistence behavior, and byte-identical successful-transform output, without any
> container-specific DICOM, policy, configuration, adapter, or execution logic.

**Not claimed**: cloud portability, scalability, streaming, protocol interoperability,
multi-architecture portability, or performance superiority — none of these is tested.

## 35. Implementation freeze criteria

1. Start from the exact S1.6 freeze commit (`9b84a2a`).
2. All 278 existing tests remain green.
3. attrs remains at exactly `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6`, clean.
4. `policy.py`, `configuration.py`, `execution.py`, `adapters/__init__.py`,
   `adapters/filesystem.py`, `cli.py`, `__main__.py` byte-for-byte unchanged.
5. The image builds from a documented, reproducible-from-frozen-commits context (named build
   contexts, no undocumented host-path dependency).
6. The runtime image relies on neither a `PYTHONPATH` sibling-directory hack nor a mounted source
   repository — Structure is a real, installed (non-editable) wheel.
7. No editable install anywhere in the runtime stage.
8. `ENTRYPOINT` is the frozen CLI directly (`python -m fastdicomstructure`), exec-form, no wrapper.
9. Configuration V1 is unchanged.
10. No container-specific execution logic exists anywhere in the image.
11. Probes A–L all pass.
12. Host/container exit codes match for every probe.
13. Host/container structured JSON results semantically match for every probe.
14. Successful-transform output byte hashes match (`sha256`) between host and container.
15. Output independently reparses (attrs) and validates (pydicom; DCMTK where practical) on both.
16. Rejected/failed executions preserve the "no destination output" guarantee identically on both.
17. `overwrite=false` behavior is preserved identically.
18. Source/destination collision behavior is preserved identically.
19. No sensitive-literal regression in container stdout/stderr (Probe K).
20. The successful filesystem-only path works with `--network none` (Probe L).
21. The runtime image excludes pydicom, DCMTK, the C++ toolchain, test corpora, and any
    qualification-only dependency.
22. No file in `fastDICOMgateway` is touched.
23. No Cloud Run/cloud-specific work is introduced.
24. `PRODUCT_CAPABILITY_MAP.md`'s P5.3 is promoted only after the above evidence exists; P5.4/P5.5/
    P6.3/P6.4 are not auto-promoted.
25. No performance or scalability claim is made — build/startup timing is characterization only.
26. Exactly one candidate S1.7 freeze commit.
27. Full test suite rerun after that commit.
28. Structure working tree clean after commit.
29. attrs working tree clean and at its exact frozen commit after commit.

## 36. Limitations/non-claims

- attrs' own packaging gap (no wheel, no independent installability) is not fixed — recorded as a
  carried-forward limitation, explicitly out of S1.7's bounded scope.
- Non-Linux Docker Desktop hard-link/bind-mount behavior is untested and not claimed.
- No multi-architecture (ARM64) image is built or claimed.
- No registry publication occurs; a locally built image is sufficient evidence for this checkpoint's
  claim.
- No SBOM, image signing, provenance attestation, vulnerability-scanning policy, or reproducible-
  build attestation is produced — legitimate future production concerns, not this hypothesis.
- The unmodeled-exception traceback-to-stderr behavior is unchanged and not reconsidered for a
  service-shaped deployment context — explicitly carried forward as an S1.8-relevant open question
  (section 17), not resolved now.
- No claim of comprehensive container security ("secure container") is made merely from a non-root
  user, `--network none`, or `--read-only` — each is one narrow, named hardening property.

## 37. Recommended S1.8 relationship

Not designed here. This checkpoint's evidence (section 24) suggests **Cloud Run Job**, not Cloud Run
Service, is the structurally closer fit to the current one-shot, filesystem-only execution model —
recorded as a hypothesis for S1.8's own future, separately-authorized design checkpoint to evaluate
on its own evidence, not settled now. Nothing in S1.7's own architecture forecloses either direction.

## 38. Final recommendation

No architectural contradiction was found in the frozen S1.5/S1.6 execution surface itself — every
protected file is expected to remain untouched, and the "same invocation, same architecture" claim
(section 3's central question) is judged achievable. The one real finding — Structure's own missing
packaging metadata — is a bounded, small, already-scoped-in correction (section 30), not a reason to
split or delay this increment, and gateway's own already-production-validated Dockerfile provides
direct, reusable evidence (not merely a hypothesis) for nearly every remaining design question:
attrs' build/install technique, the base image, the non-root user, the named-build-context approach,
and the excluded-tooling boundary are all already proven to work in a real, deployed image one layer
up this same dependency chain.

**READY FOR S1.7 IMPLEMENTATION WITH CONDITIONS**

Conditions: (1) the one Structure `pyproject.toml` addition (section 30) is implemented exactly as
scoped — packaging metadata only, no console-script entry point, no application-semantic content;
(2) if implementation evidence contradicts the "no protected file needs to change" expectation
(section 29), STOP and report rather than silently expanding scope, per the standing discipline this
entire engagement has followed since S1.1.

```text
attrs: FROZEN @ 46bf7d3
S1.1: FROZEN @ bdc324c
S1.2: FROZEN @ 53ecb83
S1.3: FROZEN @ 25615dd
S1.4: FROZEN @ 8879ca7
S1.5: FROZEN @ 350f88c
S1.6: FROZEN @ 9b84a2a
S1.7: DESIGN CHECKPOINT ONLY — READY FOR S1.7 IMPLEMENTATION WITH CONDITIONS
S1.8: NOT STARTED
```

No production code, Dockerfile, or container was created; no test was modified; no frozen file was
touched; nothing was committed during this checkpoint.
