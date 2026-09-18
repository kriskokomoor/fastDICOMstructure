# Public release readiness report

Bounded public-release-preparation increment. 2026-09-17. Scope: `fastDICOMattrs`,
`fastDICOMstructure`, `fastDICOMgateway`. This report documents what was found and changed; it
does not authorize publication, a visibility change, or a version number.

## 1. Exact repository tuple

| Repository | Commit |
|---|---|
| `fastDICOMattrs` | `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6` |
| `fastDICOMstructure` | `2efc8ae8a20963f1d18980c00591a0d2217d50ae` |
| `fastDICOMgateway` | `26caca86090a69eaa981236a1b716b7aac36e802` |

**This table is the starting tuple this report's remediation narrative below begins from — it is
not the current tuple.** attrs has since advanced to `24efab8a5fecc159ca88f1ad94e03b0d5dee2c61`
(§10); see [`FASTDICOM_RELEASE_MANIFEST.md`](FASTDICOM_RELEASE_MANIFEST.md) for the current,
incrementally-updated tuple as each repository's closure completes.

All three matched the expected starting state exactly (clean working trees; Structure had exactly
one untracked file, its own newly-written strategic review). `2efc8ae` was confirmed descended from
S1.7 `ffa117f` (two commits: design/implementation docs, then the closure freeze). Gateway's
`26caca8` was confirmed descended from the pre-S1.8 baseline `e4cba92`, changing only
`transform.py` (plus a new test file and report). See
[`FASTDICOM_RELEASE_MANIFEST.md`](FASTDICOM_RELEASE_MANIFEST.md) for the full tuple record.

## 2. Intended release architecture

- **`fastDICOMattrs`** — lightweight native DICOM structural/semantic transformation engine
  (Core).
- **`fastDICOMstructure`** — declarative policy and execution layer built on attrs (Core).
- **`fastDICOMgateway`** — bounded reference application demonstrating the policy layer embedded
  behind HTTP/network execution. Not the primary reusable library; not a complete de-identification
  solution; not production-ready.

This model was checked against actual source (not assumed) via three independent read-only audits
plus direct inspection, and matches reality with one refinement: attrs additionally owns a small
validation/benchmark surface (`corpus.py`, `bench/`) that embeds demonstration policy code for its
own testing purposes — this is validation tooling, not production policy duplication, and is
already correctly scoped in attrs' own docs after this increment's corrections (§3 below).

## 3. `fastDICOMattrs` remediation performed

- Corrected the README's Implicit VR "opacity" claim (was blanket; now narrowed to dictionary-less
  private elements and a small fixed set of permanently ambiguous-VR entries), reflecting A1.1/A1.4
  landing after that prose was written.
- Corrected the README's claim that the real-world validation corpus covers Implicit VR "the way
  the rest of this list has" — it does not; Implicit VR is validated against real pydicom-bundled
  fixtures, not a corpus of comparable scale.
- Relabeled two architecture diagrams (README) that assigned "transformation policy," "PII-tag
  policy," and "audit evidence" to the `fastDICOMattrs` box — those are `fastDICOMstructure`'s
  responsibilities; attrs owns structural validation and mutation primitives only.
- Softened "complete DICOM attribute semantics" language in README and `docs/architecture.md` to
  "structural DICOM attribute semantics within documented scope boundaries," pointing at the new
  `docs/SUPPORTED_SCOPE.md`. Left `ADR-001-ATTRS-NAMING-AND-LAYERING.md`'s original decision-record
  wording untouched (it describes an architectural ownership boundary at the time of a decision,
  not a technical completeness claim, and ADRs are historical decision records — see §4 on
  evidence preservation).
- Added an addendum (not a rewrite) to `docs/architecture.md` §11's "No data dictionary" claim,
  which had become self-contradictory against that same document's own later A1.7 addendum in §9.
- Fixed a broken relative link to `python/examples/pipeline_demo.py` (moved to `fastDICOMstructure`
  at A0; the link 404s from within this repository) — now points at the correct repository.
- Fixed README's Catch2 version claim (said "2.x," `tests/CMakeLists.txt` actually requires 3) and
  documented the real gap: Ubuntu's `apt` package is still 2.13.8, so Catch2 3 must be built from
  source, or the test suite skipped via `-DFDS_BUILD_TESTS=OFF` (confirmed by direct build
  reproduction — see §6).
- Corrected `docs/benchmarks.md`'s "CPU time" claim — the benchmark measures wall-clock only
  (`time.perf_counter()`); reworded to "processing time (wall-clock)."
- Fixed a leftover copy-paste line in the README's own License section ("...matching
  `fastDICOMattrs`," inside `fastDICOMattrs`' own README).
- Created `docs/SUPPORTED_SCOPE.md`: demonstrated / partial / unsupported / intentionally
  unresolved, each row citing its freeze report.
- Created `THIRD_PARTY_NOTICES.md` for the vendored NEMA PS3.6 XML (see §5).

**Not changed:** any production code, test, or frozen A-series/A0 freeze report. No VR, charset, or
transfer-syntax support was broadened.

## 4. `fastDICOMstructure` remediation performed

- CI (`.github/workflows/ci.yml`): pinned the `fastDICOMattrs` checkout to the exact frozen commit
  (was checking out attrs' moving default branch, contradicting every design doc's "frozen at
  46bf7d3" claim); added an explicit `pip install pytest` step (previously relied on it being
  present by chance).
- Rewrote `CONTRIBUTING.md`'s build/test section, which described a pre-A0 C++/CMake/ctest
  workflow this pure-Python repository no longer has, and referenced a `corpus.py` /
  `requirements-dev.txt` / `tests/fixtures/README.md` that do not exist here (that tooling stayed
  in `fastDICOMattrs`). Replaced with the actual Python-only flow and a concrete clone/build
  sequence.
- Fixed `docs/architecture/PRODUCT_CAPABILITY_MAP.md`'s provenance footer, which cited an S1.3
  freeze commit while the document's own body already discussed S1.4–S1.8 — updated to the current
  tuple with a note explaining the correction.
- Added a dated, clearly labeled **erratum** to `docs/architecture/S1_6_THIN_CLI_IMPLEMENTATION_REPORT.md`
  (per the evidence-preservation rule, the original freeze-commit claim was left as originally
  written, not edited in place): the report's cited freeze commit `7564cf7` is unreachable from
  `main`; the actual reachable freeze is `9b84a2a`, verified to differ only in that report's own
  section 17 (documentation-only, no production-code difference against the S1.5 freeze).
- Removed a stale build docstring from `python/examples/pipeline_demo.py` (`cmake --build build`
  — leftover from before this file moved out of `fastDICOMattrs`; this repository has no CMake).
- Added a "Getting started: an external clean install" section to README with the exact verified
  clone/build/test sequence (§6).
- **Created the minimal public example required by this increment**:
  `python/examples/example_policy.json` (a small, standalone, portable Configuration V1 document —
  require PatientID, replace PatientName, remove one private tag, remove all private elements,
  insert a de-identification-method note) and `python/examples/run_json_policy_example.py` (builds
  a synthetic DICOM object, runs the policy through the real CLI, prints the structured result, and
  independently re-reads the output with the library itself). Verified working, twice: once in the
  original development checkout, once from the fresh external checkout in §6. Synthetic data only;
  no UID remapping, OCR, streaming, or batch orchestration added.

**Not changed:** `policy.py`, `configuration.py`, `execution.py`, `adapters/`, or any test. No new
packaging architecture was introduced — the existing sibling-checkout + environment-variable
mechanism was verified to actually work externally (§6) and was documented, not replaced.

## 5. `fastDICOMgateway` remediation performed

- `transform.py`: corrected the docstring claiming `fastDICOMstructure` "has no
  pyproject.toml/setup.py" — it has one; the real gap (no installable native dependency
  declaration) is now stated precisely.
- `transform.py`: reworded two comments claiming UIDs are "never patient data." The original
  claims were true only of this project's own synthetic fixtures; the endpoints accept arbitrary
  caller-supplied bytes, and UIDs from a real object can be institution/patient-correlatable in
  practice. The comments now scope the claim to this project's synthetic test/demo inputs
  explicitly and warn against relying on it for real clinical input.
- `docs/EVIDENCE_INDEX.md` and `docs/PUBLICATION_BRIEF.md`: added a note that M1–M5 describe the
  gateway's original **imperative** policy implementation, and that S1.8 (proven byte-identical)
  is what qualifies the current transform implementation — previously neither document mentioned
  S1.8 at all.
- `README.md`: added a note to "Relationship to fastDICOMstructure" that the demonstration policy
  is, as of S1.8, expressed as a `fastdicomstructure.policy.Policy` and applied via
  `policy.apply()`, not via direct `fastDICOMattrs` mutation calls.

**Confirmed already accurate (no change needed):** the "not a general policy engine" framing;
`docs/DEMO_RELEASE.md`'s explicit non-production, unauthenticated-demo framing; the absence of any
"complete de-identification" or "PHI-safe" claim in README/docs.

### 5a. `transform.py` executable-semantics verification (this pass)

Diffed the current working tree against gateway HEAD `26caca8` line by line. Every changed line
falls inside a docstring (`_add_fastdicomstructure_to_path`'s module-level docstring;
`TransformResult`'s class docstring) or a `#` comment above the M5 UID tag constants. No
executable statement, no constant value, no function signature, and no control-flow line changed.
**Confirmed: ZERO executable semantic changes.**

### 5b. Identifier-hygiene remediation (this pass)

Personal email, GCP project identifier, a numeric-project-ID-bearing service-account address, and
a Cloud Run hostname were redacted from 9 tracked files (evidence markdown and JSON) — see §9 for
the full list and the per-file evidence-integrity reasoning. Each edited historical file now
carries an explicit, dated redaction note.

One of the 9 files, `src/fastdicom_gateway/validation/publication_refresh.py`, is **source code**,
not documentation: its `main()` had `parser.add_argument("--project", default="<the real GCP
project ID>")`. Changed to `parser.add_argument("--project", required=True)`. This **is** an
executable change, in a distinct file from `transform.py` and outside this project's HTTP
request-handling runtime — `publication_refresh.py` is a manually operator-invoked CLI tool for
regenerating M2/M3/M5 evidence, not `app.py`/`sink.py`/production `transform.py`. No test imports
`publication_refresh.main` or depends on its former default (confirmed by grep across `tests/`);
the full suite was re-run after this change and remained **77 passed, 1 skipped**, no regression.
The change only affects a future operator who omits `--project` — they must now supply it
explicitly instead of silently getting a placeholder that was never a real, usable value anyway.

**Not changed:** `app.py`, `sink.py`, any test, or any evidence JSON's substantive content (only
the 9 identifier values described in §9). No authentication was added. No functionality was
expanded.

## 6. External-layout clean-install qualification

Performed outside all normal development checkouts, in a scratch directory, using fresh `git
clone` of the exact commits in §1 and a fresh Python virtual environment containing only
`pytest`/`pydicom`:

- **Environment:** Ubuntu (kernel 6.8.0-138-generic), Python 3.14.2, CMake 3.22.1, GCC 11.4.0,
  Docker (daemon already present on the host).
- `fastDICOMattrs` configured (`-DFDS_BUILD_TESTS=OFF -DFDS_BUILD_BENCH=OFF
  -DCMAKE_BUILD_TYPE=Release`) and built cleanly. **Finding:** the C++ test suite could not have
  been built with this same command (`-DFDS_BUILD_TESTS=ON` requires Catch2 3, not available via
  `apt`); this is the one genuine undocumented-external-dependency gap found in this repository,
  now documented in its README.
- The Python `ctypes` binding loaded and auto-resolved the freshly built `.so` — no environment
  variable needed.
- `fastDICOMstructure`, cloned as a true sibling directory (default names, same parent) — the
  documented default sibling resolution worked with **no** `FASTDICOMATTRS_REPO` override.
  Non-committed pending example files (§4) were copied in to test them (they cannot be cloned
  before being committed).
- `fastDICOMstructure`'s Python suite: **278/278 passed** in 5.87s (299 total minus 21
  Docker-dependent container tests, which need a locally built image not present in this fresh
  checkout).
- The new JSON-policy example ran end to end and passed its own internal assertions.
- The documented S1.7 container build command succeeded from the fresh checkout (with a
  Docker-layer-cache caveat — several base/dependency layers were cache-hits from an earlier local
  build; the application layer was rebuilt fresh from the new checkout's content, so this is not a
  fully cold-cache reproduction). A functional smoke test against the freshly built image succeeded
  once the host bind-mount directory's permissions matched the image's fixed non-root UID (1000) —
  an ordinary Docker consideration, not a defect.

**Conclusion:** the sibling-checkout convention is real, portable, and not an undocumented
author-machine trick. Documentation now states the exact recipe explicitly (previously it was
implicit and untested from a clean layout). The Catch2 3 gap is a real, previously-undocumented
external-build limitation, now documented as workaround-required, not release-blocking (it only
affects attrs' own C++ test suite, not the library, Python binding, Structure, or gateway).

## 7. Test results

| Suite | Result | Environment |
|---|---|---|
| `fastDICOMattrs` native (`ctest`) | **312/312 passed**, 1.12s | existing local `build/` (Catch2 3, manually installed previously) |
| `fastDICOMattrs` Python | **65/65 passed**, 4.61s | scratch venv, pytest 9.1.1, Python 3.14.2 |
| `fastDICOMstructure` Python (full, incl. container) | **299 passed + 3 subtests**, ~30s | scratch venv; includes 21 Docker-dependent tests, which ran (not skipped) because `fastdicomstructure:s1.7` was already built locally (2026-09-15) |
| `fastDICOMstructure` Python (fresh external checkout, excl. container) | **278/278 passed**, 5.87s | see §6 |
| `fastDICOMgateway` full suite (`tests/`) | **77 passed, 1 skipped**, 28.76s, 2 deprecation warnings | gateway's own `.venv`, pytest 9.1.1 |
| `fastDICOMgateway` `test_app.py` alone (the broad `TestClient` suite) | **17/17 passed**, 0.86s | same |

The skip is `test_m4_end_to_end_run_passes_against_live_service` — expected, requires live Cloud
Run credentials not available in this environment.

**On the previously reported stall:** the earlier strategic review reported that a broader gateway
`TestClient` run progressed through 8 tests and then stalled, uncounted, cause unestablished. This
increment re-ran the full `tests/` directory (all 8 files, 78 collected items) to completion twice
(once as the full suite, once isolating `test_app.py`) with no stall, no hang, and no anomalous
duration. **Classification: PRE-EXISTING NON-RELEASE-BLOCKING ISSUE (not reproduced).** The
original stall's cause was never established and could not be investigated further without
open-ended debugging, which this increment's scope excludes; since the suite now runs cleanly and
completely in this environment, it is not treated as a release blocker. If it recurs, it warrants
its own bounded investigation.

## 8. Third-party provenance and licensing findings

- **`thirdparty/dicom_standard/PS3.6.xml`** (`fastDICOMattrs`) — **resolved to a concrete
  disposition this pass.** Researched against the authoritative "Policies and Procedures for the
  DICOM Standards Committee" (April 2020, DICOM Standards Committee/MITA-NEMA). §10.2 places the
  Standard's copyright, in any format, with the Secretariat. §10.3 grants a narrow, royalty-free
  permission to copy/publish *excerpts* of the Standard for incorporation into other works (product
  manuals, guidelines, educational material), conditioned on non-modification and attribution, and
  closes with: "To copy, use, publish, and distribute portions of a DICOM Standards Publication for
  which permission is not granted hereby, written permission must be obtained." Committing the
  complete docbook XML source of an entire Part (not an excerpt incorporated into another work) is
  not one of the enumerated permitted uses, and no separate license/terms file exists alongside the
  source XML tree on NEMA's own server (checked directly). **Disposition: B — permission unclear,
  recommend exclusion.** `THIRD_PARTY_NOTICES.md` now states this finding, its authoritative basis,
  and the recommended remediation: either obtain written permission, or move to a
  reproducible-acquisition model (document the retrieval URL/steps/SHA-256 already in
  `PROVENANCE.md`; fetch and hash-verify at build time instead of committing the file). **The file
  was not removed in this pass** — it was committed at `290cb90`, well before the frozen HEAD
  (`46bf7d3`); removing it now would be a new, ordinary forward commit (`git rm` + adjust the
  generator's build-time expectations), not a history rewrite, and does not erase that historical
  commit's own record. This is recommended as a **separate, specifically scoped follow-up commit,
  required before this repository is made public** — it does not block authorizing the other
  release-preparation commits proposed in this report, which do not touch this file.
  Generated dictionary tables are a materially different, considerably weaker concern (extracted
  facts, not the Standard's text/expression) and are not recommended for exclusion — see
  `THIRD_PARTY_NOTICES.md` for the reasoning.
- **Generated dictionary tables** (`src/dictionary_data.generated.*`): clear generation provenance,
  cites source/edition/hash in file headers. No issue.
- **Generated charset tables** (`src/charset_tables.generated.*`): derived from Python's standard
  library `codecs` module reflecting standard (ISO/IEC 8859, TIS 620) encodings, not a vendored
  third-party file. No issue.
- **Fixture data** (all three repositories): synthetic, built in-code. No real patient data or
  third-party corpus is committed anywhere. The real-world corpora referenced in
  `docs/corpus-results.md`/`docs/benchmarks.md` (public TCIA collections CMB-MEL, NLST) are not
  committed — only aggregate results are.
- No other vendored/adapted third-party code was found in any of the three repositories during
  this pass.

## 9. Privacy / release scan findings

Scanned tracked files in all three repositories' current trees (git working tree via `git
ls-files`/`git grep`) for: disallowed file suffixes (`.dcm .pem .key .p12 .env .zip .tar .so .pdf
.db .sqlite`), absolute local paths, a literal username, Cloud Run URLs, `gcr.io`/artifact-registry
identifiers, email addresses, and AWS/PEM key patterns. No build artifacts (`build/`, `.venv/`,
`__pycache__/`, `.pytest_cache/`) are tracked in any repository.

| Repository | Findings before remediation | After remediation |
|---|---|---|
| `fastDICOMattrs` | Clean outside the PS3.6.xml disposition (§8). | Unchanged (no identifier issue here). |
| `fastDICOMstructure` | Five occurrences of the author's local absolute path in example shell commands, across four historical implementation reports. | **Redacted** to `/path/to/...` placeholders, each with an explicit dated redaction note; the untracked, gitignored-equivalent `.claude/settings.local.json` also contains local paths but is not tracked by git and will never be part of any commit — no action needed. |
| `fastDICOMgateway` | Personal email address (2 files); GCP project identifier (7 files, including one hardcoded as a CLI default in `src/fastdicom_gateway/validation/publication_refresh.py`); GCP numeric project ID embedded in a default-compute-service-account email (2 files); Cloud Run service hostname (3 files); local absolute paths (3 files). No secrets/keys/tokens. | **Redacted** to consistent `<redacted-...>`/`/path/to/...` placeholders across all 9 affected files, each with an explicit dated redaction note stating the substitution is value-level only. The one source-code instance (`publication_refresh.py`'s `--project` default) was changed to `required=True` instead of a placeholder default, so a future run cannot silently target a fake project; this is a real (but narrowly scoped, non-production, operator-tool-only) behavior change — see §5b. |

The release owner's explicit preference (received this pass) resolved the disposition question:
exclude these values from the public repositories where doing so does not compromise the
evidentiary record. Per §4's per-file evidence-integrity check, none of the redacted values were
material to any reported measurement, count, hash, or conclusion — each is an environment/identity
label, not a result. No integrity hash recorded elsewhere references any of the edited JSON files
by content hash, so none was invalidated. Every edited historical file now carries its own
dated, explicit redaction note (per §4's transparency requirement) rather than silently appearing
to have originally run against a placeholder.

No committed DICOM objects, archives, or binaries were found in any of the three repositories.

## 10. Remaining blockers

1. **`thirdparty/dicom_standard/PS3.6.xml` removal** (`fastDICOMattrs`) — **resolved and executed**
   in a subsequent commit (`24efab8a5fecc159ca88f1ad94e03b0d5dee2c61`, child of the sanitized
   release-preparation commit `6409206e37f192802197250ef86bf4d61892cc82`, itself child of the
   frozen `46bf7d3` baseline this report otherwise describes). See that commit and
   `THIRD_PARTY_NOTICES.md` for the executed remediation, verified reproducibility, and updated
   qualification results. No longer an open blocker.

**Publication mechanism superseded.** "Made public" in this report originally implied pushing
these repositories' existing history directly. That assumption is superseded:
[`PUBLIC_REPOSITORY_HISTORY_AND_PROVENANCE.md`](PUBLIC_REPOSITORY_HISTORY_AND_PROVENANCE.md)
documents and experimentally qualifies a clean-history publication model — a public repository is
built from an exported snapshot of the qualified tree, with no Git ancestry to the private
repository's history (which stays private, unchanged, and authoritative for its own frozen
evidence). Read every "made public" / "public push" statement elsewhere in this report against
that model, not against a direct push of this repository.

## 11. Non-blocking limitations

- Catch2 3.x is not available via `apt`; building `fastDICOMattrs`' C++ test suite requires
  building Catch2 from source. Documented; does not block the library/Python/Structure/gateway
  path.
- No CI job builds or exercises the S1.7 container image; those 21 tests only run when a developer
  has manually built the image locally.
- `fastDICOMgateway`'s dependencies have no upper-bound pins or lockfile; its Docker base image tag
  is mutable, not digest-pinned.
- The previously reported gateway `TestClient` stall did not reproduce in this environment (§7);
  classified as pre-existing, non-release-blocking, unresolved.
- No current-tuple Cloud Run/load/concurrency qualification exists (M4/M5 predate S1.8).

## 12. Claims currently supportable

See [`PUBLIC_CLAIMS_AND_LIMITATIONS.md`](PUBLIC_CLAIMS_AND_LIMITATIONS.md) in full. Summary:
lightweight native DICOM structural transformation, source-preserving mutation within stated
bounds, declarative metadata policy, local/CLI/tested-container execution, one verified
application integration, tested bulk-Pixel-Data preservation without decoding, open-source
reference implementation.

## 13. Claims intentionally withheld

"Fast"/"low memory"/"scalable"/"privacy-preserving"/"de-identification"/"cloud-ready"/"high
throughput"/"general purpose" — each requires the specific qualification listed in
`PUBLIC_CLAIMS_AND_LIMITATIONS.md`, none is supportable as an unqualified claim today.

## 14. Exact proposed public release artifacts

- Three git repositories at the tuple in §1, each plus its pending release-preparation commit
  (not yet made — see the companion pre-commit closure pass for exact staging lists).
- This manifest (`FASTDICOM_RELEASE_MANIFEST.md`) and the claims document
  (`PUBLIC_CLAIMS_AND_LIMITATIONS.md`) as the canonical release-facing documents.
- `fastDICOMattrs/docs/SUPPORTED_SCOPE.md` and `THIRD_PARTY_NOTICES.md` as new supporting
  documents.
- `fastDICOMstructure/python/examples/{example_policy.json,run_json_policy_example.py}` as the
  minimal public example.
- A separate, not-yet-made follow-up commit removing `fastDICOMattrs/thirdparty/dicom_standard/PS3.6.xml`
  (or replacing it with a reproducible-acquisition build step), required before `fastDICOMattrs`
  is made public (§8, §10).
- No new version tag, no container image push, no GitHub release object — none were created or
  proposed as artifacts by this increment.

## 15. Recommendation

**READY AFTER MINOR REMEDIATION.**

The identifier-hygiene decision is now resolved and executed (§9): redaction is done, with
transparent per-file notes, verified against no test/integrity-hash regression. One item remains
open and unexecuted: removing (or replacing the acquisition model for) the vendored
`PS3.6.xml` file (§8, §10) — a specific, bounded, already-designed follow-up commit, not open
technical work. It blocks making `fastDICOMattrs` public; it does not block committing this pass's
documentation/CI/example changes across all three repositories. No code defect, no failing test,
no architecture problem, and no over-broad claim survives this pass's corrections.
