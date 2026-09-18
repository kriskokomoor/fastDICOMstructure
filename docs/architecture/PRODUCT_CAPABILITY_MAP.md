# fastDICOMstructure Product Capability Map

**Status: tracking artifact, not an implementation backlog.** These are product
capabilities and aspirations for the fastDICOMstructure/fastDICOMattrs family, as
chartered by the Post-A1 Ruthless Inventory's proposed implementation progression
(`docs/architecture/POST_A1_RUTHLESS_INVENTORY.md`, section 17). Recording a
capability here is not authorization to build it, and a status below reflects only
what has actually been built and evidenced in this repository as of the commit
noted at the bottom -- never what a lower-level primitive merely makes possible.
In particular: attrs supplying a primitive (e.g. `read_buffer`, path-aware
mutation) does not by itself make the corresponding structure-layer capability
`CURRENT` unless structure has actually built and tested the capability on top of
it.

Statuses used: `CURRENT`, `PARTIAL`, `PLANNED`, `DEFERRED`, `CANDIDATE`, `BLOCKED`.

## P1 -- Policy

| ID | Capability | Status | Owning layer | Dependency/prerequisite | Intended validation | Current evidence |
|---|---|---|---|---|---|---|
| P1.1 | Acceptance policy | PARTIAL | structure (`policy.Require`) | none further for presence-only acceptance | Require satisfied/unsatisfied against bare/concrete/wildcard locators | `tests/python/test_policy.py::PolicyLocatorMigrationTest::test_require_zero_one_many_matches`; presence-only -- no value/VR/content conditions exist (that is a different, not-yet-designed capability: "policy conditions," per the inventory's own stated separation of "where is it" from "should policy apply") |
| P1.2 | Mutation policy | **CURRENT** | structure (`policy.Remove`/`Replace`/`ReplaceText`/`Ensure`/`EnsureText`/`AllowListPrune`/`PrivateTagPolicy`) | none further -- raw and charset-aware mutation, and set-or-insert semantics, now exist across bare/concrete/wildcard locators, fully VR- and charset-delegated to attrs, operation-atomic | Remove/Replace/ReplaceText/Ensure/EnsureText correctness across bare/concrete/wildcard locators, VR-inference matrix, charset inheritance/override/sibling-isolation on both update and insert branches, atomicity/rollback (including raw-byte-exact restoration), Explicit/Implicit equivalence, non-interference, independent pydicom/DCMTK validation | `docs/architecture/S1_2_REPLACE_ENSURE_IMPLEMENTATION_REPORT.md` (this increment's freeze report); `tests/python/test_ensure_and_text.py` (57 tests); `tests/python/test_locator.py`/`test_policy.py` (48 S1.1 tests, unchanged). **Advanced from PARTIAL to CURRENT by S1.2 -- see "S1.2 traceability" below.** |
| P1.3 | Nested/pattern targeting | **CURRENT** | structure (`policy.TagLocator`/`PathLocator`/`LocatorStep`/`resolve_locator`) | none -- built entirely on frozen attrs A1.7 (`find`/`iter_elements`) | 20-scenario engine qualification + policy migration + encoding-independence + non-interference + performance | `docs/architecture/S1_1_LOCATOR_MODEL_REPORT.md` (S1.1's freeze report); `tests/python/test_locator.py` (27 tests); `tests/python/test_policy.py` migration/integration classes. Unchanged by S1.2, which builds on this without modifying it. |
| P1.4 | De-identification/anonymization | DEFERRED | structure | P1.2 (now `CURRENT`) composed into an actual named de-identification policy/profile, end-to-end against a real fixture | The de-identification stress case walked through in the inventory, section 9, and the S1.2 checkpoint's own design probe, end-to-end against a real fixture, as a *product capability* (not merely a demonstrated Python snippet) | Still none. S1.2's design checkpoint (section 22) demonstrated the proposed vocabulary expresses every worked de-identification example cleanly, and `tests/python/test_ensure_and_text.py` exercises `ReplaceText`/`Ensure`/`EnsureText` against real de-identification-shaped tags (`PatientIdentityRemoved`, `DeidentificationMethod`, `PatientName`) -- but no named, reusable de-identification policy/profile was built or qualified as its own artifact. Every ingredient P1.4 needs is now `CURRENT` (P1.2) or already was (P1.3); assembling them into an actual capability remains undone, per this increment's own explicit exclusion ("Do not implement... a complete de-identification profile") |
| P1.5 | Audit/results/errors | **CURRENT** | structure (`policy.OperationResult`/`PolicyResult`/`Diagnostic`/`ExecutionStatus`/`PolicyExecutionStatus`) | none further for the V1 definition (stable structured outcomes; stable diagnostic codes; policy-level partial/rejected/completed distinction; deterministic aggregation; privacy-safe diagnostics; modeled expected-failure boundary) | `execution`/`satisfied`/diagnostic-`code` sufficiency for every currently-reachable outcome, tested per operation and per Policy; raw-byte-exact rollback proof; privacy sweep against a known sensitive fixture literal; three-operation partial-execution demonstration | `docs/architecture/S1_3_RESULT_DIAGNOSTIC_IMPLEMENTATION_REPORT.md` (this increment's freeze report); `tests/python/test_result_diagnostic.py` (37 tests). **Advanced from PARTIAL to CURRENT by S1.3 -- see "S1.3 traceability" below.** |
| P1.6 | Bulk-data-aware policy | CANDIDATE | structure (a distinct future policy concept, deliberately not `Locator`/`resolve_locator`) + attrs (narrow additive C ABI/Python surface, not yet built) | attrs exposing more of `PixelDataReference`'s already-computed metadata past the ABI (presence/kind already cross today; extent/position/fragment detail do not); a Structure-side policy concept that is not a `TagLocator`/`PathLocator` special case | Presence/reject/route-by-kind policies against a real fixture without reading payload bytes; a report-size policy once extent is exposed | Presence, kind, extent, and eventually policy actions over payloads attrs represents as dedicated bulk-data references rather than ordinary Elements -- Pixel Data is the current concrete case, not the only one this capability is scoped to (see `docs/architecture/S1_1_PIXEL_DATA_DISCOVERABILITY_REVIEW.md`, sections 4-7, for the full analysis). Current evidence: attrs' C++ layer already has `PixelDataReference` (tag/VR/encapsulation/extent-via-`SourceSpan`/position), all zero-copy and never decoded; the C ABI/Python surface exposes only presence/kind (`fds_structure_pixel_data_kind`/`Structure.pixel_data_kind`) -- extent, position, and fragment metadata are computed in C++ but do not cross the ABI; Locator V1 (S1.1) deliberately does not, and must not, special-case `(7FE0,0010)` inside `resolve_locator` (section 6 of the review); no remove/replace-Pixel-Data primitive exists at any layer; no generalized "is this bulk data" abstraction beyond Pixel Data specifically exists yet (an explicit SHOULD-gap named in `ATTRS_CONTRACT_V1_AND_GAP_ANALYSIS.md`, section I) |

## P2 -- Configuration

| ID | Capability | Status | Owning layer | Dependency/prerequisite | Intended validation | Current evidence |
|---|---|---|---|---|---|---|
| P2.1 | Single declarative JSON configuration | **CURRENT** | structure (`fastdicomstructure.configuration`) | none further for the V1 definition (a fully closed, fail-closed loader exists: `load_configuration`/`load_configuration_json`, `Configuration`, `ConfigurationError`) | Round-trip JSON -> Configuration -> Policy -> apply -> expected PolicyResult, for all six V1 declarative operations | `docs/architecture/S1_4_JSON_CONFIGURATION_IMPLEMENTATION_REPORT.md` (this increment's freeze report); `tests/python/test_configuration.py` (74 tests) -- semantic equivalence vs. direct Python construction (byte-identical output), acceptance-safety differential, raw/callback negative controls, a 40-case validation-negative matrix, round-trip, real-DICOM (pydicom + DCMTK), Explicit/Implicit VR LE equivalence, and a mechanical security sweep. **Advanced from PLANNED to CURRENT by S1.4.** |
| P2.2 | Source configuration | **CURRENT** | structure (`adapters.resolve_source`, `adapters.filesystem.FilesystemSource`) | none further for the filesystem instance (C-STORE/DICOMweb/database remain their own, separately-authorized adapters) | A JSON policy document names an input adapter/location, resolved and executed | `docs/architecture/S1_5_EXECUTION_ARCHITECTURE_IMPLEMENTATION_REPORT.md`; `tests/python/test_execution.py` -- a `source` envelope resolves through the closed registry and `FilesystemSource.acquire()` executes end-to-end (Probe A/B/C/G). **Advanced from PLANNED to CURRENT by S1.5**, filesystem only -- see that row's own note on P4.x. |
| P2.3 | Destination configuration | **CURRENT** | structure (`adapters.resolve_destination`, `adapters.filesystem.FilesystemDestination`) | none further for the filesystem instance | A JSON policy document names an output adapter/location, resolved and executed | Same evidence as P2.2, destination side (Probe A/F), plus atomic-publish/no-overwrite safety qualification. **Advanced from PLANNED to CURRENT by S1.5**, filesystem only. |
| P2.4 | Acceptance-policy configuration | **CURRENT** | structure | P2.1, P1.1 | `Require`-shaped JSON round-trips through the loader and executes with semantics equivalent to direct construction | `tests/python/test_configuration.py` -- `require` fully representable (`acceptance` array, `require`-only), the acceptance-safety differential test proves the JSON restriction removes the direct-Python mutation-before-Require footgun |
| P2.5 | Mutation-policy configuration | **CURRENT** | structure | P2.1, P1.2 | `Remove`/`ReplaceText`/`EnsureText`/`AllowListPrune`/`PrivateTagPolicy`-shaped JSON round-trips through the loader and executes with semantics equivalent to direct construction | `tests/python/test_configuration.py` -- covers the declarative **text**-mutation subset only; raw-byte `Replace`/`Ensure` and callback-based operations are explicitly excluded by design (S1.4 design checkpoint section 6a/7) and remain Python-only, not covered by this capability |

## P3 -- Input

| ID | Capability | Status | Owning layer | Dependency/prerequisite | Intended validation | Current evidence |
|---|---|---|---|---|---|---|
| P3.1 | Filesystem input | CURRENT | attrs, re-exported by structure | none | `fastdicomstructure.read(path)` parses a file | Pre-existing re-export (`python/fastdicomstructure/__init__.py`); unaffected by S1.1 |
| P3.2 | Memory input | CURRENT | attrs, re-exported by structure | none | `fastdicomstructure.read_buffer(bytes)` parses a buffer | Same as P3.1; used throughout this increment's own test fixtures |
| P3.3 | Streaming input | BLOCKED | attrs (would need a new primitive) | attrs has no streaming parse primitive (`fds_parse_stream` is an acknowledged stub per attrs' own ABI design doc) | N/A until attrs exposes it | None; explicitly out of scope for S1.1 and not attempted |
| P3.x | Future protocol-specific sources | CANDIDATE | structure (adapters, not core) | P5's adapter split | Adapter-specific | None built |

## P4 -- Output

| ID | Capability | Status | Owning layer | Dependency/prerequisite | Intended validation | Current evidence |
|---|---|---|---|---|---|---|
| P4.1 | Filesystem | CURRENT | attrs, re-exported by structure | none | `structure.write(path)`/`write_with_stats(path)` | Pre-existing re-export; used in this increment's reparse-cleanliness checks (inherited pattern from `test_policy.py`) |
| P4.2 | Memory/stream (buffer, not true streaming) | CURRENT (memory only) | attrs, re-exported by structure | none | `structure.write_bytes()`/`write_bytes_with_stats()` | Pre-existing re-export; used throughout this increment's non-interference tests (byte-identity checks) |
| P4.3 | DICOM C-STORE | CANDIDATE | structure (a future adapter) | P5's adapter split; a DICOM network stack this family does not currently have | An adapter sends a policy-transformed Structure via C-STORE | None |
| P4.4 | DICOMweb/WADO-RS | CANDIDATE | structure (a future adapter) | same as P4.3, HTTP stack instead | An adapter serves/accepts a policy-transformed Structure via WADO-RS | None |
| P4.5 | Database | CANDIDATE | structure (a future adapter) | same shape as P4.3/P4.4 | An adapter persists policy results/metadata to a database | None |
| P4.x | Extensible output adapters | **CURRENT** (filesystem only) | structure (`adapters/`) | none further for the closed-registry pattern itself; a second adapter (C-STORE/DICOMweb/database) is its own future increment | One thin local file-in/file-out adapter around `policy.apply()` | `docs/architecture/S1_5_EXECUTION_ARCHITECTURE_IMPLEMENTATION_REPORT.md`; `tests/python/test_execution.py` (36 tests) -- the closed adapter boundary (I/O only, never DICOM/policy semantics) is proven with exactly one concrete pair, filesystem; the registry pattern itself (not any second adapter) is what is `CURRENT`. **Advanced from PLANNED to CURRENT by S1.5.** |

## P5 -- Execution / Deployment

| ID | Capability | Status | Owning layer | Dependency/prerequisite | Intended validation | Current evidence |
|---|---|---|---|---|---|---|
| P5.1 | Local/library execution | CURRENT | structure (`policy.apply`) | none | `apply(structure, policy) -> PolicyResult`, in-memory, no I/O coupling | Every test in this repository calls `policy.apply` this way; `policy.py` imports nothing filesystem- or network-shaped |
| P5.2 | CLI | **CURRENT** | structure (`fastdicomstructure.cli`, `python -m fastdicomstructure run`) | P5.1 (already true) | A CLI invocation produces the same `PolicyResult` as a library call | `docs/architecture/S1_6_THIN_CLI_IMPLEMENTATION_REPORT.md`; `tests/python/test_cli.py` (26 tests) -- a real subprocess invocation produces byte-identical destination output and an equivalent `PolicyResult` (decision/execution) to a direct, in-process `execution.run_configured` call for identical input (Probe J, both black-box and instrumentation techniques); probes A-L cover success, rejection, malformed input, invalid Configuration, adapter resolution failure, source/destination collision, no-overwrite safety, partial policy execution, uncaught RollbackError propagation, a destination-less policy-check mode, and CLI usage errors. **Advanced from PLANNED to CURRENT by S1.6.** |
| P5.3 | Container | **CURRENT** | structure (`Dockerfile`, `python -m fastdicomstructure` as the container `ENTRYPOINT`) | P5.1/P5.2 (already true) | A containerized invocation produces byte-identical output to a local one | `docs/architecture/S1_7_CONTAINER_PORTABILITY_IMPLEMENTATION_REPORT.md`; `tests/python/test_container.py` (21 tests) -- a Docker-built Linux x86_64 image, invoking the frozen S1.6 CLI unchanged (exec-form entrypoint, no wrapper), produces `sha256`-identical successful-transform output to native-host execution, plus matching exit codes/structured results across probes A-L (rejection, malformed DICOM, existing destination, collision, destination-less mode, configuration error, adapter resolution error, source failure, destination failure, privacy, no-network). **Advanced from CANDIDATE to CURRENT by S1.7.** |
| P5.4 | Cloud function/serverless | CANDIDATE | structure/deployment (outside this repo) | same as P5.3 | Same falsifiable claim as P5.3, serverless context | None built or measured |
| P5.5 | Pipeline component (fastDICOMgateway integration) | **CURRENT** | structure + fastDICOMgateway (cross-repo) | S1.5's local adapter (satisfied), a coordinated, separately-authorized change to fastDICOMgateway itself (satisfied by S1.8) | fastDICOMgateway calls `policy.apply()` instead of hand-rolling the equivalent primitive sequence; its own tests stay green | `docs/architecture/S1_8_GATEWAY_INTEGRATION_CLOSURE.md` -- `fastDICOMgateway` commit `26caca86090a69eaa981236a1b716b7aac36e802` replaces its four imperative `Structure` calls with a declarative `policy.Policy` applied through `policy.apply()`; byte-identical output for the deterministic accepted fixture (SHA-256 `3bf45c...dc761`), unchanged Q2/Q3 rejection behavior, an instrumented delegation proof (not merely independently-agreeing outputs), 77/1-skip gateway tests passing (74 pre-existing unmodified + 3 new), 299/299 Structure tests passing, zero changes to `fastdicomstructure`/`fastdicomattrs` production code. **Advanced from DEFERRED/BLOCKED to CURRENT by S1.8.** Scoped narrowly: this evidences composability for this one consumer/policy/integration pattern, not universal composability -- see the closure document's own "What was NOT demonstrated" section. |

## P6 -- Operational Characteristics

| ID | Capability | Status | Owning layer | Dependency/prerequisite | Intended validation | Current evidence |
|---|---|---|---|---|---|---|
| P6.1 | Performance | PARTIAL | structure (`resolve_locator`) + attrs (underlying primitives) | a real-corpus-scale measurement, and eventually the RSNA CTP comparison (see Hypotheses below) | Locator resolution timing across root/concrete/wildcard/large-item-count shapes | S1.1 report, "Performance": root-tag ~0.03ms, deep concrete (2000-item sequence) ~1.3ms, one-level wildcard over 2000 items ~27ms, multi-level wildcard (400x5) ~44ms; scaling check 500-8000 items shows near-constant per-item cost (~11-22 microseconds/item, not worsening) -- narrow, single-machine, single-file evidence only, no corpus-scale or cross-file claim |
| P6.2 | Bounded resource consumption | PARTIAL | structure (`resolve_locator`) + attrs (Pixel Data by-reference handling) | corpus-scale memory profiling for a real product claim | Locator resolution never touches/materializes Pixel Data | `tests/python/test_locator.py::test_pixel_data_target_never_resolves_and_never_materializes` proves a real, tested **non-interference** guarantee: no locator can touch or materialize Pixel Data, because Pixel Data is structurally outside the element graph `resolve_locator` walks (see `docs/architecture/S1_1_PIXEL_DATA_DISCOVERABILITY_REVIEW.md`). **This does not demonstrate bounded resource behavior for a policy that actually needs to reason about Pixel Data** -- Pixel Data's extent (byte length) is not currently exposed through the C ABI/Python surface at all (only presence/kind is), so no size-aware bounding claim, positive or negative, can be made yet. Non-interference and efficient reasoning are distinct claims; only the former is evidenced here. |
| P6.3 | Scalability | CANDIDATE | structure + attrs | multi-file/batch/corpus-scale measurement | Throughput/latency across a real corpus, not just synthetic single-file timing | None beyond P6.1's single-file synthetic timing |
| P6.4 | Deployment portability | CANDIDATE | structure (core already qualifies; adapters don't exist) | P5.2-P5.4 | Same policy executes unchanged across local/CLI/container/serverless invocation | Structural argument only (core has zero fs/network imports, per the inventory's own section 11 analysis, still true after S1.1). **Two of three prerequisites (P5.2, P5.3) are now demonstrated** -- see `docs/architecture/S1_6_THIN_CLI_IMPLEMENTATION_REPORT.md` and `docs/architecture/S1_7_CONTAINER_PORTABILITY_IMPLEMENTATION_REPORT.md`; P5.4 (cloud/serverless) remains undemonstrated, so this row stays `CANDIDATE`, not promoted -- S1.7 does not prove cloud portability. |

## P7 -- Observability / Integration

| ID | Capability | Status | Owning layer | Dependency/prerequisite | Intended validation | Current evidence |
|---|---|---|---|---|---|---|
| P7.1 | Structured exception reporting | **CURRENT** | structure (`policy.MalformedLocatorError` for construction-time errors; `policy.Diagnostic`/`DIAGNOSTIC_CODES`/`_classify_exception` for the execution-time mapping the inventory originally flagged MISSING) | none further for the V1 definition | attrs' typed mutation exceptions (`VRRequiredError`, `UnrepresentableCharacterError`, `InvalidUnicodeInputError`, `AlreadyExistsError`, generic `FdsError`) each map to a distinct, stable diagnostic code, one dedicated trigger test per reachable code | `tests/python/test_result_diagnostic.py::DiagnosticCodeCoverageTest` (9 tests); `tests/python/test_locator.py::test_malformed_locator_rejected` (unchanged, construction-time coverage). **Advanced from PARTIAL to CURRENT by S1.3** -- the broader exception-to-Diagnostic mapping the inventory flagged as MISSING (section 12 of `POST_A1_RUTHLESS_INVENTORY.md`) is now built |
| P7.2 | Audit/event output | PARTIAL | structure (`PolicyResult`) | S1.3 | `PolicyResult` reports decision/operations/diagnostics per `apply()` call | Pre-existing, unchanged in shape by S1.1. **Not promoted by S1.5**: `execution.ExecutionResult` is a distinct, compatible operational-result concept one layer above `PolicyResult` (see `docs/architecture/S1_5_EXECUTION_ARCHITECTURE_IMPLEMENTATION_REPORT.md`), but this row's own claim is specifically about `PolicyResult`'s shape, which S1.5 does not change or extend evidence for -- its mere existence is not treated as advancing this row, per the S1.5 authorization's own explicit caution. |
| P7.3 | Evidence Packet integration | CANDIDATE | structure (future, unspecified) | undefined -- no design work has started | N/A | None. Explicitly out of scope for S1.1; listed here only as a named future integration point |

## S1.1 traceability

**Primary capability advanced:** P1.3 (Nested/pattern targeting) -- moved from
non-existent to `CURRENT`, with a dedicated engine-level test suite
(`tests/python/test_locator.py`, 27 tests covering the 20 required scenarios plus
locator equality/hash and ergonomics), full migration of the five existing policy
operations onto it, an encoding-independence integration test, and non-interference
proofs.

**Enables but does not implement (still their own prior status, unchanged by
this increment):** P2 (declarative configuration -- design-proof only, no
parser), P1.4 (de-identification -- infrastructure ingredient only), P5
(deployment-neutral execution -- already true of `policy.apply()` before S1.1
and unaffected by it).

No other capability's status changed as a result of S1.1. In particular, P1.1,
P1.2, P1.5, P6.1, P6.2, and P7.1 show incidental evidence updates (new tests
exercise them through the widened operations) but remain at their pre-S1.1
`PARTIAL` status -- none crossed into `CURRENT` this increment.

**Newly tracked, not advanced:** P1.6 (Bulk-data-aware policy) is added to this
map for the first time as part of S1.1's own Pixel Data finding
(`docs/architecture/S1_1_PIXEL_DATA_DISCOVERABILITY_REVIEW.md`) -- it starts at
`CANDIDATE`, the same status any newly-recorded, not-yet-built capability
starts at, not an advancement. P6.2's evidence text was also corrected (not
broadened) during this same pass: locator resolution's inability to touch
Pixel Data is a real non-interference guarantee, not evidence of bounded
resource reasoning about Pixel Data -- see P6.2's row above and the
discoverability review's section 8.

## S1.2 traceability

**Primary capability advanced:** P1.2 (Mutation policy) -- moved from `PARTIAL`
(raw-bytes only) to `CURRENT`: `ReplaceText`, `Ensure`, `EnsureText` add
charset-aware replacement and set-or-insert semantics across bare/concrete/
wildcard locators, fully delegating VR inference and charset context
resolution to frozen attrs, with operation atomicity (including exact
raw-byte restoration on rollback) and 57 new tests
(`tests/python/test_ensure_and_text.py`) covering insertion-site resolution,
the VR-inference matrix, charset inheritance/override/sibling-isolation on
both the update and insert branch, duplicate-tag inheritance, non-interference
(successful and failed operations), Explicit/Implicit equivalence,
performance, and independent pydicom/DCMTK validation.

**Enables but does not implement (still their own prior status, unchanged by
this increment):** P1.4 (de-identification -- every ingredient is now
available and demonstrated in isolation, but no named, reusable
de-identification policy/profile was built), P2.5 (mutation-policy
configuration -- design-proof only, no parser).

No other capability's status changed as a result of S1.2. P1.5 shows an
incidental evidence update (S1.2 adds `RollbackError` and names a second
result-model gap alongside S1.1's existing one) but remains `PARTIAL` -- richer
result modeling is still S1.3's job, not attempted here. P1.1, P1.3, P6.1,
P6.2, P7.1 are unaffected by S1.2 and unchanged from their S1.1 values.

## S1.3 traceability

**Primary capabilities advanced:** P1.5 (Audit/results/errors) and P7.1
(Structured exception reporting) -- both moved from `PARTIAL` to `CURRENT`.
`ExecutionStatus`/`PolicyExecutionStatus` separate "did this execute" from
`satisfied`'s narrower "did this operation's own condition/guarantee hold"
(`Optional[bool]`, `None` where no condition exists or an operation never
ran); a stable, ten-code `Diagnostic` vocabulary (`DIAGNOSTIC_CODES`) maps
attrs' typed mutation exceptions -- the exact gap
`POST_A1_RUTHLESS_INVENTORY.md` section 12 originally flagged MISSING -- onto
structured, privacy-safe outcomes; `Policy.apply()` gains a narrow, closed
exception boundary (never `except Exception`) that converts known failures
into a `PARTIAL` `PolicyResult` with later operations marked `NOT_EXECUTED`,
while `RollbackError` and any unrecognized exception continue to propagate
raw. As part of the same increment, a real pre-S1.3 defect discovered during
the design checkpoint's own evidence-gathering -- a raw `Replace` callback
failing partway through a wildcard left earlier sites mutated, while
`ReplaceText` already rolled its own back -- was resolved by bringing
`Replace` onto the same atomic engine, closing the asymmetry rather than
carrying it forward. 37 new tests (`tests/python/test_result_diagnostic.py`)
cover both capabilities' full V1 definitions, including a differential test
proving the new model distinguishes three cases the S1.2-era model
conflated, a three-operation policy test demonstrating operation atomicity
plus whole-policy non-atomicity plus complete result visibility together,
and a mechanical privacy sweep against a known sensitive fixture literal.

**Enables but does not implement (still their own prior status, unchanged by
this increment):** P1.4 (de-identification -- unaffected by this increment,
which touched results/diagnostics, not mutation semantics), P2 (JSON
configuration), P5 (execution/deployment adapters), P1.6 (bulk-data policy),
P7.3 (Evidence Packet integration) -- S1.3 makes results representable in a
way that would later serve all of these but builds none of them, per
explicit instruction.

No other capability's status changed as a result of S1.3. P1.1, P1.2, P1.3,
P6.1, P6.2 are unaffected and unchanged from their S1.1/S1.2 values.

## Hypotheses (not capabilities -- no status, not yet measured)

**Performance relative to RSNA CTP.** Not currently a claim. Recorded as a future
falsifiable hypothesis, no numerical threshold selected:

> For equivalent supported metadata transformation workloads,
> fastDICOMstructure + fastDICOMattrs can achieve materially greater throughput
> and/or lower resource consumption than an equivalent RSNA CTP pipeline.

RSNA CTP was not benchmarked during S1.1, per this increment's explicit exclusion.
See P6.1/P6.3 above for the (unrelated, much narrower) locator-resolution timing
evidence this increment did produce.

---

**Provenance footer updated for the S1.8 gateway integration closure.** This document's body
already cites S1.4–S1.8 rows above; this footer previously lagged behind at an S1.3 reference and
is corrected here rather than left inconsistent with the body. Evaluated against fastDICOMstructure
at `2efc8ae8a20963f1d18980c00591a0d2217d50ae` (S1.8 gateway integration closure, descended from
S1.7 `ffa117f1a63c7e269bfad24bfc0f5e1938430f35`) and fastDICOMattrs frozen at `46bf7d3` (A1.7,
unchanged by any Structure/gateway increment). Earlier per-increment freeze commits remain: S1.1
`bdc324cfe5b71c7080d7efee8d745186d7020366`, S1.2 `53ecb832bd76345eb62bbf533167663b9f9546d9`, S1.3
(see `S1_3_RESULT_DIAGNOSTIC_IMPLEMENTATION_REPORT.md`), S1.6 `9b84a2a` (see that report's own
erratum note on its cited freeze hash), S1.7 `ffa117f`, gateway S1.8 `26caca86090a69eaa981236a1b716b7aac36e802`.
