# fastDICOM release manifest

Authoritative human-readable map of the release candidate spanning three repositories. Produced
during a bounded public-release-preparation increment (2026-09-17). This document does not
authorize publication, a GitHub visibility change, or a version number — see
[`PUBLIC_RELEASE_READINESS_REPORT.md`](PUBLIC_RELEASE_READINESS_REPORT.md) for the recommendation.

## 1. The release-candidate repository tuple

| Repository | Commit | Branch / tracking |
|---|---|---|
| `fastDICOMattrs` | `24efab8a5fecc159ca88f1ad94e03b0d5dee2c61` (internal qualification identifier — not a public tag) | `main`, ahead of `origin/main` by 2 (not pushed) |
| `fastDICOMstructure` | candidate pending — to be established by the closure commit this document's own repository is about to receive, on top of `2efc8ae8a20963f1d18980c00591a0d2217d50ae` | `main`, ahead of `origin/main` by 1 (not pushed), plus uncommitted release-preparation changes |
| `fastDICOMgateway` | `26caca86090a69eaa981236a1b716b7aac36e802` — **not yet closed against attrs `24efab8`** | `main`, ahead of `origin/main` by 3 (not pushed), plus uncommitted release-preparation changes |

**This tuple is a moving target during closure, updated incrementally as each repository's release
candidate is established** — see
[`PUBLIC_RELEASE_READINESS_REPORT.md`](PUBLIC_RELEASE_READINESS_REPORT.md) for the sequence.
Historical note: this table originally recorded attrs at frozen `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6`;
attrs has since advanced through `6409206` (sanitized release-preparation documentation) to
`24efab8` (PS3.6.xml remediation — see `THIRD_PARTY_NOTICES.md`), its current internal
qualification candidate.

This document is deliberately not amended merely to insert the Structure candidate's own SHA once
it exists — that would require the closure commit to know its own hash before being created. The
resulting SHA is recorded here, or in a follow-up closure/attestation note, only after that commit
exists.

No version number is assigned. None of the three repositories has an existing versioning scheme
that clearly dictates one (`fastDICOMstructure`'s `pyproject.toml` declares `version = "0.1.0"` as
a placeholder, not a release decision made here).

## 2. Relationship among the three repositories

```
fastDICOMattrs (structural engine, C++ core + C ABI + Python ctypes binding)
        ^
        | depends on (via PYTHONPATH / sibling checkout; not a PyPI dependency)
fastDICOMstructure (declarative policy + execution + CLI + container)
        ^
        | depends on (via PYTHONPATH / sibling checkout; not a PyPI dependency)
fastDICOMgateway (reference application: HTTP demo, embeds the Structure policy engine)
```

- `fastDICOMattrs` owns DICOM structural/semantic representation, parsing, mutation primitives,
  serialization, the C ABI, and the Python binding. It owns no policy content and depends on
  nothing else in this family.
- `fastDICOMstructure` owns locator semantics, declarative policy (`policy.py`), Configuration V1
  (JSON), execution lifecycle, filesystem adapters, the CLI, and container packaging. It depends on
  `fastDICOMattrs` for everything about DICOM encoding.
- `fastDICOMgateway` is a **bounded reference application**, not the primary reusable library and
  not a complete de-identification or production service. As of S1.8 (gateway commit `26caca8`,
  Structure closure `2efc8ae`), it embeds `fastDICOMstructure`'s policy engine
  (`fastdicomstructure.policy.apply()`) behind an HTTP boundary; it retains its own HTTP handling,
  acceptance gate, output verification, and persistence sink — it does not adopt Structure's
  `execution.run`, Configuration V1, or filesystem adapters.

## 3. Dependency mechanism (as it actually works today)

None of the three is published to PyPI. Each downstream repository locates its native/Python
dependency via an environment-variable override defaulting to a sibling-checkout convention:

- `fastDICOMstructure` locates `fastDICOMattrs` via `FASTDICOMATTRS_REPO` (default: a
  `fastDICOMattrs` directory next to it).
- `fastDICOMgateway` locates `fastDICOMstructure` via `FASTDICOMSTRUCTURE_REPO` (default: a
  `fastDICOMstructure` directory next to it), and transitively needs `fastDICOMattrs` built the
  same way.

This was independently re-verified during this increment from a genuinely fresh, non-development
checkout (see §6) — the sibling-checkout convention itself works correctly and is not tied to any
one machine's home-directory layout; the gap is that it was previously **undocumented as an
explicit external-user recipe** with pinned commits. `fastDICOMstructure`'s README and
`CONTRIBUTING.md`, and `fastDICOMattrs`' README, now include exact clone/checkout/build sequences
(see §6).

## 4. Platform assumptions

- Linux x86_64, verified. macOS/Windows/ARM are untested by any evidence in this tuple.
- C++20 compiler, CMake ≥ 3.16 for `fastDICOMattrs`.
- **Catch2 3.x is required to build and run `fastDICOMattrs`' C++ test suite, but is not
  obtainable via Ubuntu's `apt` package** (`catch2` there is 2.13.8). Building only the library, C
  ABI, and Python binding (`-DFDS_BUILD_TESTS=OFF`) does **not** require Catch2 at all. This is a
  real, previously undocumented external-install gap — see §6 and
  `PUBLIC_RELEASE_READINESS_REPORT.md` §6.
- Python ≥ 3.9 (`fastDICOMstructure`'s stated `requires-python`); this qualification pass used
  Python 3.14.2.
- Docker, for `fastDICOMstructure`'s S1.7 container qualification and `fastDICOMgateway`'s image —
  optional; the relevant tests skip individually, not as a suite failure, when Docker or the
  prebuilt image is unavailable.

## 5. Owner-of-record for each area of documentation

| Area | Owning repository | Notes |
|---|---|---|
| DICOM structural/semantic correctness, parsing, mutation, dictionary, charset | `fastDICOMattrs` | See its `docs/SUPPORTED_SCOPE.md` |
| Declarative policy semantics, Configuration V1, execution/adapter contracts, CLI | `fastDICOMstructure` | See its `docs/architecture/PRODUCT_CAPABILITY_MAP.md` |
| HTTP demo behavior, network/persistence boundary observation (M1–M5), S1.8 substitution | `fastDICOMgateway` | See its `docs/EVIDENCE_INDEX.md` and `docs/S1_8_STRUCTURE_POLICY_INTEGRATION_REPORT.md` |

## 6. External clean-install qualification (performed this increment)

Performed in a directory outside all normal development checkouts
(`/tmp/.../scratchpad/external-qualify/`), using fresh `git clone` of the exact commits in §1 (via
local paths standing in for the published GitHub URLs — the two remotes are not confirmed publicly
current at these commits; see §1's "ahead of origin" note) and a fresh Python virtual environment
with only `pytest`/`pydicom` installed:

1. `fastDICOMattrs` configured and built cleanly with `-DFDS_BUILD_TESTS=OFF -DFDS_BUILD_BENCH=OFF`
   (no Catch2 needed for this path) — library + C ABI built successfully.
2. The Python binding (`ctypes`-based) loaded and resolved the freshly built `.so` automatically,
   with no environment variable set, via its documented default search path.
3. `fastDICOMstructure`, cloned as a **true sibling directory** of `fastDICOMattrs` (same parent,
   default directory names) — the documented default resolution worked with **no**
   `FASTDICOMATTRS_REPO` override needed.
4. `fastDICOMstructure`'s Python test suite: **278/278 passed** (299 total minus the 21
   Docker-dependent container tests, excluded from this fresh-checkout run since no
   `fastdicomstructure:s1.7` image existed there yet).
5. The new minimal JSON-policy example (`python/examples/run_json_policy_example.py`, added this
   increment — see §9 of the readiness report) ran end to end: synthetic input → declarative JSON
   policy → real CLI (`python -m fastdicomstructure run --config ... --json`) → independent
   read-back via the library itself. Succeeded.
6. The documented S1.7 container build command
   (`docker build -f Dockerfile --build-context attrs=../fastDICOMattrs -t ... .`) succeeded from
   the fresh checkout. **Caveat:** Docker's layer cache from an earlier local build of
   `fastdicomstructure:s1.7` was reused for several base/dependency layers; the application layer
   (`COPY python`, `pip install .`) was rebuilt fresh from the new checkout's content. This is not
   a fully cold-cache reproduction on a machine that has never built this image.
7. A functional smoke test against the freshly built image succeeded once the host bind-mount
   directory's permissions matched the image's fixed non-root UID (1000) — an ordinary Docker
   bind-mount consideration, not a defect, but worth documenting: the image does not adapt to an
   arbitrary host UID.

**Net finding:** the documented sibling-checkout convention is real and portable, not an
undocumented author-machine trick. The one genuine undocumented-external-dependency gap is Catch2
3.x for `fastDICOMattrs`' own C++ test suite (not needed for the Python/Structure/gateway path).

## 7. Historical evidence tuples that do NOT describe the current tuple

These must not be read as qualifying the commit tuple in §1. Preserved here, not altered at their
source:

| Evidence | Its own commit(s) | What it actually qualifies | Does NOT qualify |
|---|---|---|---|
| Gateway M1–M5 (persistence-boundary, container, Cloud Run, real-store retrieval) | `7b0fe11`…`ab3afb2` (gateway), various `fastDICOMstructure` pre-A0/pre-S1.8 commits | The gateway's original **imperative** fixed-policy `transform.py`, at each milestone's own cited commit | Current S1.8 gateway (`26caca8`) or current Structure (`2efc8ae`) — S1.8's own report proves byte-identical output, but M1–M5's *runtime observations* (Cloud Run logs, container diffs) were not re-run against S1.8 |
| Adversarial remediation / `POST_REMEDIATION_EVIDENCE_REFRESH.md` | Refresh JSON recorded then-current HEADs **while the working tree was dirty** | The corrected recursive-mutation/Explicit-VR-acceptance behavior, using an in-process `TestClient`, not Cloud Run | A clean-checkout reproduction — the disclosed dirty tree means checking out the JSON's recorded commit alone does not reproduce the refresh run |
| Gateway `v0.1.0-demo` tag (`bcde8c3`) | Cites gateway `ab3afb2`, Structure `4eb44cb` | An earlier, pre-A0/pre-S1.8 demonstration snapshot | The current tuple in §1 |
| `fastDICOMstructure` S1.6 freeze | Report cites `7564cf7` (unreachable on `main`); reachable freeze is `9b84a2a` | The thin-CLI consumer behavior — verified equivalent between the two commits (documentation-only diff) | Use `9b84a2a` in any downstream citation; see the report's own added erratum |
| `fastDICOMattrs` historical benchmark (`docs/benchmarks.md`) | A pre-publication working tree, not independently commit-pinned in the report | The attrs-native file-path read/transform/write timing only | Current end-to-end Structure/gateway performance — no comparable measurement exists yet for that path (see the resource-characterization increment proposed separately, not begun here) |

## 8. Known limitations carried into this manifest (not fixed this increment)

- No CI job builds/exercises the S1.7 container image or its 21-test qualification suite; those
  tests only run when a developer has manually built `fastdicomstructure:s1.7` locally.
  `Structure`'s CI now pins `fastDICOMattrs` to the exact frozen commit and installs `pytest`
  explicitly (fixed this increment), but container qualification remains manual.
  **Classification: non-blocking limitation** (self-contained, not silently misrepresented — the
  gap is now documented here and in the readiness report).
- `fastDICOMgateway`'s `pyproject.toml` uses open lower-bound dependency versions with no upper
  bound or lockfile; its `Dockerfile` `BASE_IMAGE` is a mutable tag, not a content digest.
  **Classification: non-blocking limitation**, documented, not remediated this increment (no
  compatibility testing was performed to choose safe upper bounds).
- Several evidence/documentation files across `fastDICOMstructure` and `fastDICOMgateway`
  contained the repository owner's personal email address, a GCP numeric project identifier, a
  live-looking Cloud Run hostname, and local absolute filesystem paths from the development
  machine — found during the privacy/release scan. **Per the release owner's explicit
  instruction, these were redacted** in a follow-up pass (each edited historical file carries a
  dated, explicit redaction note; see `PUBLIC_RELEASE_READINESS_REPORT.md` §9 for the full list and
  the evidence-integrity reasoning). No test or integrity hash regressed.
- `fastDICOMattrs/thirdparty/dicom_standard/PS3.6.xml`'s redistribution status was researched
  against NEMA/DICOM Standards Committee's own published policy and resolved to **disposition B —
  recommend exclusion** (see `THIRD_PARTY_NOTICES.md`). **Not yet removed** — this is the one
  remaining action item before `fastDICOMattrs` can be made public.
