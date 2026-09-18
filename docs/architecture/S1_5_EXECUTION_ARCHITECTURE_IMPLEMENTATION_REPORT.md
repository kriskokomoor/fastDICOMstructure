# S1.5 Implementation Report — Execution Core + Filesystem Adapter Proof

## 1. Frozen starting state

| Item | Commit |
|---|---|
| fastDICOMattrs | `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6` (unchanged throughout S1.5) |
| fastDICOMstructure | `8879ca7a9395bafe0764910dfa6f3278b95c4a48` (S1.4 freeze) |

Both verified via `git rev-parse HEAD` immediately before any S1.5 implementation work began, and
again immediately after: attrs unchanged; structure's only pre-existing addition was the accepted,
unimplemented `S1_5_EXECUTION_ARCHITECTURE_DESIGN_CHECKPOINT.md`. Baseline: `python3 -m pytest
tests/python/` — **216/216 passing**, both trees clean.

## 2. Checkpoint disposition and three corrections

`docs/architecture/S1_5_EXECUTION_ARCHITECTURE_DESIGN_CHECKPOINT.md` was accepted for
implementation as `S1.5 — Execution Core + Filesystem Adapter Proof`, with three corrections
recorded in that document's own "Accepted disposition and corrections" section (appended, original
analysis preserved unchanged):

1. **Persistence gate** — eligibility for the normal destination requires **both**
   `PolicyResult.execution == PolicyExecutionStatus.COMPLETED` **and** `PolicyResult.decision` in
   `{Decision.ACCEPT, Decision.TRANSFORM}`, checked explicitly against both dimensions rather than
   relying on the fact that today's frozen `policy.py` only ever produces them in lockstep.
2. **No execution identity** — `execute_one(data: bytes, policy: Policy) -> ExecutionResult`, no
   `identity` parameter; `ExecutionResult` carries no path/filename/UID/source-URI field of any
   kind.
3. **Execution equivalence claim, narrowed** — `execute_one` and `run` are not forced into a
   superficially symmetric outcome vocabulary; `run` literally calls `execute_one` for the shared
   core (proven by instrumentation, section 24) rather than reimplementing it.

All three are implemented exactly as specified; no further deviation was required.

## 3. Final module architecture

```text
python/fastdicomstructure/
    policy.py                  UNCHANGED (byte-for-byte, verified: git diff --stat is empty)
    configuration.py            UNCHANGED (byte-for-byte, verified: git diff --stat is empty)
    execution.py                NEW -- ExecutionOutcome, ExecutionDiagnostic, ExecutionResult,
                                  SourceAcquisitionError, DestinationWriteError,
                                  execute_one(), run()
    adapters/
        __init__.py              NEW -- AdapterResolutionError, SOURCE_ADAPTERS/
                                  DESTINATION_ADAPTERS, resolve_source(), resolve_destination(),
                                  check_source_destination_collision()
        filesystem.py            NEW -- FilesystemSource, FilesystemDestination
```

`__init__.py` re-exports `execution` and `adapters` alongside the existing `policy`/`configuration`
(two lines added: `from . import execution`/`from . import adapters`, and their names added to
`__all__` — the only change to any pre-existing file). No `plugin.py`/`retry.py`/`batch.py`/
`queue.py`/`cloud.py`/`docker.py`/`telemetry.py` was created; no async machinery was added.

## 4. `execute_one` contract

```python
def execute_one(data: bytes, policy: Policy) -> ExecutionResult
```

Owns: parsing `data` (attrs `read_buffer(fidelity="lossless")`), running `policy` against the
result (`policy.apply()`, completely unmodified), and — only when persistence-eligible (section
13) — serializing (attrs `write_bytes()`). Never touches a filesystem path, an adapter, a
`Configuration`, logging, retry, or rendering. The `Structure` it creates is always closed in a
`finally` (verified: attrs' `Structure` has no `__enter__`/`__exit__`, confirmed by direct
inspection of `fastdicomattrs/__init__.py` — this checkpoint did not add context-manager behavior
to attrs, matching the authorization's explicit instruction).

## 5. `run` contract

```python
def run(source, policy: Policy, destination=None) -> ExecutionResult
```

Owns exactly two responsibilities `execute_one` does not: `source.acquire()` (before) and
conditional `destination.write(...)` (after). Implemented as a literal call to `execute_one` for
the shared core — never a parallel reimplementation of parsing, policy application, or
serialization (section 24 proves this by instrumentation, not merely by code inspection).

## 6. Adapter contracts

`SourceAdapter` (informal `Protocol`, not a base class — nothing requires one for a single
concrete implementation): `acquire() -> bytes`, raising `execution.SourceAcquisitionError` on
failure. `DestinationAdapter`: `write(data: bytes) -> None`, raising
`execution.DestinationWriteError` on failure. Neither receives or returns a `Structure`, `Policy`,
or `PolicyResult` — verified directly: `adapters/filesystem.py` imports neither `policy` nor
`fastdicomattrs`.

## 7. Adapter registry/resolution

```python
SOURCE_ADAPTERS = {"filesystem": FilesystemSource}
DESTINATION_ADAPTERS = {"filesystem": FilesystemDestination}

def resolve_source(envelope, registry=SOURCE_ADAPTERS): ...
def resolve_destination(envelope, registry=DESTINATION_ADAPTERS): ...
def check_source_destination_collision(source, destination): ...
```

Closed, deterministic `dict`s — no entry-point discovery, no dynamic import, no class name taken
from JSON, no `eval`, no filesystem scanning for plugins (verified: `adapters/__init__.py` contains
no such construct). `registry` is an explicit, overridable parameter for test substitution (small,
direct dependency injection, per the authorization's own allowance). `configuration.py` remains
unchanged — it validates only the common `Envelope` shape; adapter-specific option validation
happens entirely inside `FilesystemSource.__init__`/`FilesystemDestination.__init__`.

## 8. `AdapterResolutionError` contract

Three closed codes: `ADAPTER_TYPE_UNKNOWN`, `ADAPTER_OPTIONS_INVALID`,
`SOURCE_DESTINATION_COLLISION` (one beyond the authorization's stated minimum, added for the
required source/destination collision check — section 15). Curated, fixed messages per code,
mirroring `configuration.ConfigurationError`'s own established pattern; never echoes the envelope's
`type` string or any `options` value (`SecurityQualificationTest.test_adapter_resolution_error_does_not_echo_options`).
Raised once per Configuration, strictly before any object is acquired — never converted into an
`ExecutionResult`.

## 9. `ExecutionResult` contract

```python
@dataclass(frozen=True)
class ExecutionResult:
    outcome: ExecutionOutcome
    policy_result: Optional[PolicyResult] = None
    output_bytes: Optional[bytes] = None
    diagnostic: Optional[ExecutionDiagnostic] = None
```

No `identity`, no timestamps, no run ID, no source/destination path, no UID, no retry count, no
cloud/host metadata — nothing beyond what the eight probes (section 23) actually required to be
observable was added. No expansion was discovered to be freeze-critical during implementation.

## 10. `ExecutionOutcome` vocabulary

Seven closed values: `SUCCEEDED`, `SOURCE_FAILED`, `PARSE_FAILED`, `POLICY_REJECTED`,
`POLICY_PARTIAL`, `SERIALIZATION_FAILED`, `DESTINATION_FAILED`. `execute_one` can produce
`{SUCCEEDED, PARSE_FAILED, POLICY_REJECTED, POLICY_PARTIAL, SERIALIZATION_FAILED}`; `run` can
additionally produce `{SOURCE_FAILED, DESTINATION_FAILED}` — verified directly from the source: no
code path inside `execute_one` ever constructs the latter two.

## 11. `ExecutionDiagnostic` contract

```python
@dataclass(frozen=True)
class ExecutionDiagnostic:
    code: str
    message: str
    cause_type: Optional[str] = None
```

Six closed codes (`EXECUTION_DIAGNOSTIC_CODES`): `SOURCE_ACQUISITION_FAILED`,
`DICOM_PARSE_FAILED`, `SERIALIZATION_FAILED`, `DESTINATION_ALREADY_EXISTS`,
`DESTINATION_WRITE_FAILED`, `DESTINATION_COMMIT_FAILED` — one fixed, curated message per code,
never `str(exception)`. Distinct from both `policy.Diagnostic` and `configuration.ConfigurationError`
(different vocabularies, different failure classes — section 14). `cause_type` is the underlying
exception's class name only, present only where genuinely useful (parse/source/destination
failures caused by a raised exception) — never for `POLICY_REJECTED`/`POLICY_PARTIAL`, whose cause
is already fully described by `policy_result.diagnostics` and is never duplicated here (verified:
`ExecutionResult.diagnostic is None` for both of those outcomes throughout `test_execution.py`).

## 12. `PolicyResult`/`ExecutionResult` boundary

`PolicyResult` is attached, unmodified, to `ExecutionResult.policy_result` for every outcome where a
`Policy` actually ran (`SUCCEEDED`, `POLICY_REJECTED`, `POLICY_PARTIAL`, `DESTINATION_FAILED`) —
`None` for `SOURCE_FAILED`/`PARSE_FAILED`, which occur strictly before a `Policy` could run.
`ExecutionDiagnostic` never duplicates anything `PolicyResult.diagnostics` already carries.

## 13. Persistence gate

```python
_PERSISTENCE_ELIGIBLE_DECISIONS = (Decision.ACCEPT, Decision.TRANSFORM)

def _is_persistence_eligible(policy_result: PolicyResult) -> bool:
    return (policy_result.execution == PolicyExecutionStatus.COMPLETED
            and policy_result.decision in _PERSISTENCE_ELIGIBLE_DECISIONS)
```

Both dimensions checked explicitly (Correction 1). Confirmed by direct inspection of frozen
`policy.py`: `Decision.ACCEPT`/`TRANSFORM` are constructed only inside `apply()`'s final `return`
statement, reached only when `execution=PolicyExecutionStatus.COMPLETED` was already decided —
today's frozen code cannot actually produce a `COMPLETED`+`REJECT` pairing — but `_is_persistence_eligible`
does not rely on that fact; it checks both fields unconditionally, so it would correctly refuse
persistence even if a future, currently-unreachable state combination existed. `run()` gates
destination invocation on `execute_one`'s returned `outcome is ExecutionOutcome.SUCCEEDED` alone,
since that value already fully encodes the gate.

## 14. Failure taxonomy (as implemented)

| Failure | Representation |
|---|---|
| Configuration invalid | `configuration.ConfigurationError` (unchanged, outside execution) |
| Unsupported adapter / invalid options | `adapters.AdapterResolutionError` (new, outside per-object execution) |
| Source acquisition failure | `ExecutionOutcome.SOURCE_FAILED` |
| DICOM parse failure | `ExecutionOutcome.PARSE_FAILED` (see section 27 for a genuine implementation-time finding here) |
| Policy `Require` rejection | `ExecutionOutcome.POLICY_REJECTED`, `PolicyResult` attached, no new diagnostic |
| Modeled policy operation failure | `ExecutionOutcome.POLICY_PARTIAL`, `PolicyResult` attached, no new diagnostic |
| `RollbackError` | propagates raw, uncaught, out of both `execute_one` and `run` |
| Serialization failure | `ExecutionOutcome.SERIALIZATION_FAILED` |
| Destination write/commit failure | `ExecutionOutcome.DESTINATION_FAILED` |
| Unexpected exception | propagates raw, uncaught |

## 15. `RollbackError` boundary

Preserved exactly. `execution.py` adds no `except RollbackError`/`except Exception` anywhere around
`policy.apply()`. Proven directly (`ProbeETest`, reusing `test_result_diagnostic.py`'s own proven
`mock.patch.object(fastdicomattrs.Structure, "set_value", flaky)` technique): `RollbackError`
propagates out of `execute_one` and out of `run`; in the `run` case, the destination test double's
`.calls` list remains empty, proving no `ExecutionResult` was ever constructed and no destination
write was ever attempted.

## 16. Unexpected-exception boundary

Proven directly: a synthetic `PolicyOperation` raising a plain `KeyError` (mirroring
`test_result_diagnostic.py`'s own proven technique) propagates unmodified through both
`execute_one` and `run` — never converted into any `ExecutionResult`
(`DifferentialTest.test_unexpected_exception_propagates_not_converted_to_execution_result`).

## 17. Filesystem source semantics

Exactly one configured file (`options = {"path": str}`, closed field set — any other key is
`AdapterResolutionError("ADAPTER_OPTIONS_INVALID")`). `acquire()` reads the whole file via
`Path.read_bytes()`; any `OSError` (missing file, permission denied, etc.) is wrapped in
`SourceAcquisitionError`. No directory enumeration, globbing, recursion, or watching exists. No
"no object available" state — a missing/unreadable configured file is unconditionally
`SOURCE_FAILED`.

## 18. Filesystem destination semantics

`options = {"path": str, "overwrite": bool = False}`, same closed-field-set discipline. `write(data)`
never receives or produces a `Structure`/`Policy`/`PolicyResult` — bytes in, nothing out (or a
`DestinationWriteError`).

## 19. Filesystem safety/atomicity behavior

Precisely, the POSIX primitives used:

1. `tempfile.mkstemp(dir=<target's own directory>)` — guarantees the later publish step is
   same-filesystem.
2. Bytes are written, then `f.flush()` + `os.fsync(f.fileno())` before the file is closed —
   durability before any publish attempt.
3. **`overwrite=True`**: `os.replace(temp, target)` — POSIX `rename(2)`, atomic, unconditionally
   replaces an existing target.
4. **`overwrite=False` (default)**: **not** a check-then-rename sequence. `os.link(temp, target)` —
   POSIX `link(2)` creates the new directory entry `target` atomically and fails with
   `FileExistsError` if `target` already exists, without ever touching or truncating it. This is
   the same technique Maildir delivery and content-addressed object stores rely on for
   publish-if-absent semantics, and is what makes the no-overwrite path race-free — there is no
   separate "check" step whose result could go stale before the actual publish. The redundant
   temporary directory entry is removed afterward (`_best_effort_unlink`) once `target` has its own
   independent entry to the same inode.
5. Every failure path removes the temporary file on a best-effort basis
   (`path.unlink(missing_ok=True)`, swallowing only its own `OSError`) — the original failure being
   reported is never masked by a cleanup failure.

**Race-safety qualification, specifically** (`FilesystemSafetyTest`):
- `test_race_safe_no_overwrite_no_check_then_act_window` — creates the target file *after* the
  destination object already exists (simulating a concurrent creator that appeared after any
  hypothetical earlier check) and confirms `write()` still correctly refuses to overwrite it.
- `test_race_safe_no_overwrite_under_real_concurrency` — a genuine two-thread stress test (20
  repeated trials, both threads racing `FilesystemDestination.write()` against the same
  non-existent target with `overwrite=False`): every trial produces exactly one winner and exactly
  one `DESTINATION_ALREADY_EXISTS` loser, and the final file content is always one of the two
  payloads in full, never mixed or corrupted. Re-run five additional times during this
  implementation with no failures (100 total trials, 0 races observed).

**Source/destination collision**: `adapters.check_source_destination_collision(source,
destination)` compares `Path.resolve()` on both adapters when both are concretely
`FilesystemSource`/`FilesystemDestination`, raising `AdapterResolutionError("SOURCE_DESTINATION_COLLISION")`
before any acquisition is attempted; a no-op for every other adapter combination.

## 20. Known whole-object memory-copy tradeoff

Retained exactly as the design checkpoint named it, not hidden: `FilesystemSource.acquire()` reads
the complete file into a Python `bytes` object; `execute_one` parses it via `read_buffer` (a second,
attrs-internal copy into the C++ engine); a successful policy result is serialized back via
`write_bytes()` (producing a third Python-level `bytes` object). This is one additional whole-object
Python-level representation relative to attrs' own `read(path)`/`write(path)`, which would let the
C++ layer perform file I/O directly. Not hidden, not called streaming, no bounded-memory claim made.
Not optimized around in S1.5 — qualification revealed no functional blocker requiring it. No Pixel
Data decoding is introduced anywhere in this design; the fixtures used for qualification contain no
Pixel Data element at all (out of scope for what S1.5 needed to prove), consistent with S1.1's own
finding that Pixel Data is entirely outside the element graph this family of operations ever
inspects.

## 21. Configuration relationship

Kept fully separate, as designed. `execute_one(data: bytes, policy: Policy)` never mentions
`configuration.Configuration`. No `run_configured(config)` convenience was added — qualification did
not reveal a case where composing `resolve_source`/`resolve_destination`/`run` explicitly (four
lines) was materially harder than a bundled call would have been; per the authorization's own
guidance ("Only add it if it materially simplifies the real S1.5 qualification. Otherwise defer it
to the CLI consumer"), it is deferred to S1.6.

## 22. Security/privacy qualification

`SecurityQualificationTest` (5 tests): a known sensitive literal
(`"Zbigniew^Sekretny^SSN-123-45-6789"`) was injected into (a) DICOM-shaped bytes passed to a source
double, (b) a source-adapter exception's own `__str__`, (c) a destination-adapter exception's own
`__str__`, and (d) adapter `options` (a path-shaped string). In every case, the literal is confirmed
absent from `ExecutionDiagnostic.message`, `repr(ExecutionDiagnostic)`, `repr(ExecutionResult)`, and
`AdapterResolutionError`'s message/`str()` — only `cause_type` (the exception's class name) survives
into the diagnostic, never its text. `EXECUTION_DIAGNOSTIC_CODES` confirmed closed (no duplicates).
Operating-system exception messages are explicitly **not** claimed PHI-safe anywhere — they are
never placed in any public field at all (only `type(exc).__name__` is), which is a stronger property
than "safe to include," matching the authorization's own caution against that specific claim.

## 23. Probes A–H

All eight implemented as direct tests in `tests/python/test_execution.py`; all pass. Summary (full
detail in the test file itself):

| Probe | Outcome | Key assertions |
|---|---|---|
| A — successful filesystem transformation | `SUCCEEDED` | destination file exists, reparses cleanly, `PatientName == "ANONYMIZED"` |
| B — acceptance rejection | `POLICY_REJECTED` | destination never invoked, source file byte-identical to before, no `output_bytes` |
| C — malformed DICOM | `PARSE_FAILED` | no `PolicyResult`, PHI-safe diagnostic, destination never invoked; a second, distinct sub-case proves the raised-`FdsError` path is also reachable (not merely the lenient-diagnostic path) |
| D — modeled policy failure | `POLICY_PARTIAL` | no serialization, no destination, `PolicyResult.operations[1].diagnostics[0].code == "VR_REQUIRED"` remains sole authority |
| E — rollback failure | propagates raw | proven both through `execute_one` directly and through `run` (destination test double never called) |
| F — destination failure | `DESTINATION_FAILED` | `PolicyResult`/`output_bytes` from the successful `execute_one` call are preserved via `dataclasses.replace`; source unaffected; two sub-cases (`DESTINATION_WRITE_FAILED`, `DESTINATION_COMMIT_FAILED`) both leave no partial target file |
| G — unsupported adapter type | `AdapterResolutionError("ADAPTER_TYPE_UNKNOWN")` | raised at resolution time, before any acquisition; Configuration V1 itself accepts the opaque envelope unchanged |
| H — direct bytes caller | `SUCCEEDED` | identical `output_bytes`/`decision`/`execution` to the filesystem-adapter path for the same underlying bytes and Policy, with no Configuration and no adapter involved at all |

## 24. Differential qualification

`DifferentialTest` (5 tests), all passing:

1. **`policy.apply` vs `execute_one`** — the same fixture bytes and `Policy`, applied once directly
   and once through `execute_one`, produce an equal `PolicyResult` (`assertEqual`, full dataclass
   equality).
2. **`execute_one` vs `run`** — `execution.execute_one` instrumented via `mock.patch.object` with a
   counting spy; `run()` is proven to call it **exactly once**, with the exact acquired bytes and
   `Policy` — the literal, executable proof of Correction 3's delegation claim, not merely a
   structural assertion.
3. **Destination invocation counts** — exactly one call for a successful policy, zero for
   `REJECTED`, zero for `PARTIAL`, zero for a `RollbackError`-raising policy.
4. **Serialization gate** — `Structure.write_bytes` instrumented with a counting wrapper; confirmed
   never called for rejected/partial/rollback-failure cases, called exactly once for a genuine
   success.
5. **Unexpected exception** — see section 16.

## 25. Real-DICOM validation

`RealDicomQualificationTest` (2 tests), both executed (not skipped) in this environment: Probe A's
full filesystem source → `run()` → filesystem destination path, verified by:
- Structure's own lossless self-reparse (no blocking diagnostics).
- **pydicom** (`pydicom.dcmread`): `PatientName == "ANONYMIZED"`, `Modality == "CT"`.
- **DCMTK `dcmdump`** (subprocess): return code 0, output contains `"ANONYMIZED"`.

Both independent tools confirm the *resulting DICOM semantics*, not the execution architecture
itself, per the authorization's own framing.

## 26. Explicit/Implicit smoke regression

`EncodingRegressionTest` (1 test): the same policy applied via `execute_one` to fixtures built under
Explicit VR Little Endian and Implicit VR Little Endian produces identical `(outcome, decision,
execution)` — a smoke-level confirmation only, not a re-run of the full A1/S1.2 qualification (per
the authorization's own explicit instruction not to).

## 27. Regression totals

| Point | Total | Result |
|---|---|---|
| Baseline (S1.4 freeze, before S1.5 work) | 216 | all passing |
| After S1.5 implementation | 252 | all passing (216 pre-existing + 36 new, all in `test_execution.py`) |

`policy.py` and `configuration.py` are confirmed byte-for-byte unchanged (`git diff --stat` against
both is empty). No existing test file was modified.

## 28. Performance characterization

`PerformanceSmokeTest` (2 tests): a pathological-overhead guard only (the wrapped
parse→apply→serialize path is not orders of magnitude slower than a bare no-op `policy.apply()`
call against an already-parsed `Structure`); a second test confirms source-read, `execute_one`, and
destination-write are independently timeable stages, recorded as characterization only. No
throughput, scalability, or bounded-resource claim is made anywhere.

## 29. Defects discovered/fixed

**One genuine, evidence-driven implementation-time finding**, discovered during qualification, not
anticipated in the design checkpoint: **attrs' `read_buffer` is lenient by design** — it raises
`FdsError` only for catastrophic conditions (I/O failure, a wholly unsupported/unrecognized transfer
syntax); ordinary malformed or truncated content instead produces a `Structure` whose own
`.diagnostics` carry the finding (e.g. `severity="recoverable_error"`), without raising at all. This
is not a defect in attrs — it is attrs' own established, documented behavior, and is exactly the
convention `python/examples/pipeline_demo.py` (`structural_parse_and_inspect`) and
`fastDICOMgateway`'s `transform.py` (`_parse_or_reject`) already both independently rely on. The
initial `execute_one` implementation caught only `FdsError`, which would have let a garbage/near-empty
`Structure` reach `policy.apply()` (observed directly: a malformed-input probe produced
`POLICY_REJECTED` instead of the intended `PARSE_FAILED`, because a `Require` on an essentially empty
structure legitimately fails, masking the real problem). Fixed by additionally checking
`structure.diagnostics` for any non-`"info"` severity immediately after a successful parse and
classifying that as `PARSE_FAILED` too — reusing an existing, proven convention rather than
inventing a new one. No change to `policy.py`, `configuration.py`, or attrs was needed or made;
`execution.py`'s own docstring documents this finding directly (see `execute_one`'s docstring).

## 30. Product Capability Map changes

Updated `docs/architecture/PRODUCT_CAPABILITY_MAP.md`:

- **P2.2** (Source configuration): `PLANNED` → **`CURRENT`** — `FilesystemSource` resolves and
  executes end-to-end (Probes A/B/C/G).
- **P2.3** (Destination configuration): `PLANNED` → **`CURRENT`** — `FilesystemDestination`
  resolves and executes end-to-end (Probes A/F), including atomic-publish/no-overwrite safety.
- **P4.x** (Extensible output adapters): `PLANNED (S1.5 first instance)` → **`CURRENT`** (filesystem
  only) — the closed adapter boundary (I/O-only, never DICOM/policy semantics) is proven with
  exactly one concrete pair.
- **P7.2** (Audit/event output): **left `PARTIAL`**, not promoted — `ExecutionResult` is a distinct,
  compatible concept one layer above `PolicyResult`, but this row's own claim is about
  `PolicyResult`'s shape specifically, which S1.5 provides no new evidence for, per the
  authorization's own explicit caution against automatic promotion here.
- **Left unchanged, as required**: P5.2 (CLI), P5.3 (Container), P5.4 (Cloud/serverless), P5.5
  (Gateway convergence), P6.3 (Scalability), P6.4 (Deployment portability), P3.3 (Streaming), P4.3
  (C-STORE), P4.4 (DICOMweb), P4.5 (Database), P7.3 (Evidence Packet integration) — none of these
  is touched or promotable by S1.5's own scope.

## 31. Known limitations/carry-forward

- The whole-object memory-copy tradeoff (section 20) is unoptimized, by deliberate choice.
- No streaming, no bounded-memory claim, no scalability/throughput claim, no batch/concurrency/retry
  behavior — all explicitly out of S1.5's scope, per the authorization.
- Only one concrete adapter pair (filesystem) exists; C-STORE/DICOMweb/database remain future,
  separately-authorized increments.
- No result serialization (`ExecutionResult`/`PolicyResult`/`Diagnostic` → JSON) exists yet — S1.6's
  CLI is the first expected concrete consumer.
- No `identity`/provenance field exists anywhere in the public contract (Correction 2) — deferred
  until a real consumer establishes the required semantics and privacy boundary.
- Gateway is untouched; its own Cloud Run/DICOMweb pipeline remains independent evidence supporting
  this architecture, not code migrated during S1.5.

## 32. Provisional S1.6–S1.9 progression

Unchanged from the accepted checkpoint, still provisional and evidence-driven, not an immutable
roadmap:

```text
S1.6  Thin CLI consumer
S1.7  Containerized execution proof
S1.8  Cloud Run/serverless execution proof
S1.9  Gateway convergence
```

The architectural expectation carried forward: containerization should be a thin deployment wrapper
around the same execution core (`execute_one`/`run`, both entirely free of filesystem/network
coupling themselves); if a future S1.7 requires substantial container-specific execution logic,
that is evidence of a boundary problem in this core, not normal implementation cost.

## 33. Exact candidate freeze commit

Recorded after the freeze commit is created — see the FINAL RESPONSE returned alongside this
report. Starting commit (verified before any implementation work): `8879ca7a9395bafe0764910dfa6f3278b95c4a48`.

## 34. Final falsifiable S1.5 claim

> Given a valid Configuration V1 document naming the filesystem source and filesystem destination
> adapters, fastDICOMstructure can execute exactly one DICOM object's configured Policy through a
> deployment-neutral execution core (`execute_one`) and thin I/O adapters (`FilesystemSource`/
> `FilesystemDestination`), while preserving the frozen separation among DICOM semantics (attrs),
> policy semantics (`policy.py`, unmodified), configuration semantics (`configuration.py`,
> unmodified), and I/O (`adapters/`, DICOM- and policy-ignorant).
>
> Additionally: for identical acquired bytes and the same `Policy`, `run()` delegates the
> parse/policy/serialization lifecycle to the exact `execute_one()` semantics available directly to
> a caller supplying bytes — proven by instrumentation (section 24, item 2), not merely asserted.

**Supported** by: 36 new tests (probes A–H, 5 differential tests, 11 filesystem safety tests
including a 20-trial real-concurrency race-safety stress test, 5 security tests, 2 real-DICOM
validation tests, 1 Explicit/Implicit smoke regression, 2 performance-characterization tests),
alongside 216 pre-existing tests unaffected, 252/252 passing total.

**Not claimed**: container portability, cloud portability, scalability, streaming, bounded memory,
protocol interoperability, batch execution, concurrency, retry behavior, performance superiority —
none of these was tested, and none is asserted.
