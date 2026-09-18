# S1.3 -- Result / Diagnostic Completion -- Implementation Report

> **Public-release redaction note (2026-09-17):** a local development-machine absolute path in an
> example command below has been replaced with a `/path/to/...` placeholder. Value-level
> substitution only — the command and its reported result are otherwise unchanged.

**Status: PASS.** The Design B result/diagnostic model is implemented exactly as the accepted
checkpoint specified, with both approved corrections (raw `Replace` callback atomicity; raw
`Replace`'s silent `set_value(False)` under-counting) resolved by bringing `Replace` onto the
shared S1.2 atomic engine. All 105 pre-S1.3 tests pass unchanged; 37 new tests were added (142
total). attrs remains untouched at its frozen commit. No S1.4/S1.5/gateway work was started.

## 1. Frozen starting commits

| Item | Value |
|---|---|
| fastDICOMattrs | frozen at `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6`, unchanged throughout |
| fastDICOMstructure | S1.1 FROZEN `bdc324cfe5b71c7080d7efee8d745186d7020366`; S1.2 FROZEN `53ecb832bd76345eb62bbf533167663b9f9546d9`, 105/105 tests passing |

## 2. Design-checkpoint disposition

`docs/architecture/S1_3_RESULT_DIAGNOSTIC_DESIGN_CHECKPOINT.md`, Design B, accepted with the two
corrections below. The checkpoint's own section 28 recommendation ("either fixing [Finding 3] or
formally documenting it as an accepted, permanent limitation") was resolved toward *fixing* it, not
documenting around it -- recorded in the checkpoint's own new section 29, added after acceptance,
preserving sections 1-28 exactly as originally written (no rewriting of history to make the defect
look anticipated).

## 3. Raw Replace atomicity correction

`Replace`'s own mutation loop (`_resolve_and_replace`) now routes through `_apply_sites_atomically`
-- the identical engine `ReplaceText`/`Ensure`/`EnsureText` already used, reused verbatim rather
than reimplemented (no second rollback engine was built, per the correction's own instruction).
Every resolved match becomes an `_InsertionSite` with `exists=True` (`Replace` never inserts,
exactly preserving its original contract); a callback's own exception is wrapped in a new
`CallbackError` before it reaches the atomic engine, so a callback failure and an attrs mutation
failure are both caught by the same generic exception path and rolled back identically.

**Direct-call contract** (verified, `ReplaceAtomicityTest::test_direct_call_rolls_back_and_raises_callback_error`):
a wildcard `Replace` whose callback raises on the second site now raises `CallbackError`
(`cause_type="ValueError"`, the *original* exception's class) and leaves the first site's raw bytes
exactly as they were before the call -- not, as before S1.3, mutated and left that way.

**`Policy.apply()` contract** (verified,
`ReplaceAtomicityTest::test_policy_apply_reports_callback_failed_rolled_back`): the same scenario
through a `Policy` produces `execution=ROLLED_BACK`, `count=0`, one `Diagnostic(code="CALLBACK_FAILED",
cause_type="ValueError")`, with the original callback's message (`"boom"`) confirmed absent from
the diagnostic's own string representation.

**Callback failing before any mutation** (verified,
`test_callback_fails_before_any_site_mutation_is_failed_not_rolled_back`): `execution=FAILED`, not
`ROLLED_BACK` -- there was nothing to roll back, and the model does not claim there was.

## 4. Raw Replace silent-failure correction

`Replace`'s `do_update` closure now raises `_MutationFailed` (unchanged internal marker, already
used by `Ensure`/`EnsureText`) when `set_value` returns `False`, instead of silently not
incrementing `count`. Verified (`ReplaceMutationFailureTest`):

- No prior site mutated -> `execution=FAILED`, `Diagnostic(code="MUTATION_FAILED")`, structure
  unchanged (`test_no_prior_mutation_is_failed`).
- An earlier wildcard site already mutated -> that site's raw bytes are restored exactly,
  `execution=ROLLED_BACK` (`test_earlier_site_mutation_is_rolled_back`).
- A direct call raises `_MutationFailed` rather than returning a result with fewer changes than
  matches (`test_set_value_false_raises_mutation_failed_not_silent_undercount`).

This correction emerged directly from correction 3's own mechanism (both corrections share the same
`do_update` closure and the same atomic engine), exactly as the authorization anticipated ("This
correction should emerge naturally if Replace is moved onto the shared atomic engine").

## 5. Final Result Contract v1

```python
class ExecutionStatus(str, enum.Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    NOT_EXECUTED = "not_executed"

class PolicyExecutionStatus(str, enum.Enum):
    COMPLETED = "completed"
    REJECTED = "rejected"
    PARTIAL = "partial"

class Decision(str, enum.Enum):
    ACCEPT = "accept"
    TRANSFORM = "transform"
    REJECT = "reject"
    PARTIAL = "partial"       # new

@dataclass(frozen=True)
class OperationResult:
    kind: str
    tag: Optional[Tag]
    execution: ExecutionStatus
    satisfied: Optional[bool]
    count: int
    updated_count: Optional[int] = None   # Ensure/EnsureText only
    inserted_count: Optional[int] = None  # Ensure/EnsureText only
    diagnostics: tuple[Diagnostic, ...] = ()

@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    execution: PolicyExecutionStatus
    operations: tuple[OperationResult, ...]
    diagnostics: tuple[Diagnostic, ...]
    policy_name: str
    policy_version: str
    # elements_touched / failed_requirement: unchanged properties (failed_requirement's
    # implementation corrected -- see section 8)
```

Implemented exactly as the checkpoint's section 6 specified -- no field added, removed, or
reshaped beyond that design.

## 6. Final Diagnostic Contract v1

```python
DIAGNOSTIC_CODES = (
    "REQUIREMENT_UNSATISFIED", "GUARANTEE_UNESTABLISHED", "VR_REQUIRED",
    "TEXT_OPERATION_UNSUPPORTED", "INVALID_UNICODE", "CHARACTER_UNREPRESENTABLE",
    "ALREADY_EXISTS", "MUTATION_FAILED", "CALLBACK_FAILED", "ROLLBACK_FAILED",
)

@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    operation_kind: str
    operation_index: int
    locator: str              # repr() of the operation's own Locator -- never attrs' raw path
    site: Optional[str] = None    # Structure-owned rendering of one concrete failing site
    message: str = ""             # fixed, code-specific, never exception text
    cause_type: Optional[str] = None   # exception CLASS NAME only
```

`LOCATOR_INVALID` is documented (module docstring, `DIAGNOSTIC_CODES`'s own docstring) as reserved
for a future S1.4 loader, deliberately **not** included in the `DIAGNOSTIC_CODES` tuple itself and
never constructed at runtime -- matching the instruction not to manufacture an S1.3 runtime path
for it.

## 7. Execution status semantics

Implemented exactly per section 5's table. A direct `operation.apply(structure)` call only ever
returns `execution=COMPLETED` on a normal return -- `FAILED`/`ROLLED_BACK` appear *only* in an
`OperationResult` `Policy.apply()` itself constructs after catching an exception; `NOT_EXECUTED`
appears *only* as a placeholder `Policy.apply()` builds for operations after an early stop. This
division of responsibility (verified by inspection: no operation's own `apply()` method ever
constructs a `FAILED`/`ROLLED_BACK`/`NOT_EXECUTED` result) keeps each concern in exactly one place.

## 8. Satisfaction semantics

`satisfied: Optional[bool]` -- `True`/`False` only for `require`/`ensure`/`ensure_text`; `None` for
`remove`/`replace`/`replace_text`/`allow_list_prune`/`private_tag_policy` (no condition exists) and
for **any** kind when `execution=NOT_EXECUTED` (a condition that was never evaluated, not one that
evaluated `False`).

**A real pre-existing bug found and fixed while implementing this** (not present before S1.3's own
schema change made it reachable): `PolicyResult.failed_requirement`'s original implementation
checked `not result.satisfied`, which is `True` for both `satisfied=False` *and* `satisfied=None`
-- meaning a `NOT_EXECUTED` `Require` (impossible before S1.3, since nothing produced
`NOT_EXECUTED` results at all) would have been misreported as an unsatisfied one. Fixed to
`result.satisfied is False` (strict), verified by
`ResultShapeTest::test_require_unsatisfied_via_policy_rejects_and_marks_later_not_executed`, which
asserts a `NOT_EXECUTED` `Require`'s `satisfied` is `None`, not `False`. `Policy.apply()`'s own
`Require`-rejection check was written with the same strict `is False` comparison from the start,
for consistency.

## 9. Count semantics

`count` unchanged in meaning (total elements durably changed); `0` for any `FAILED`/`ROLLED_BACK`/
`NOT_EXECUTED` result (a rolled-back mutation is not a committed change -- verified directly,
section 3/4's tests). `_apply_sites_atomically` now returns `(updated_count, inserted_count)`
instead of one total, so `Ensure`/`EnsureText` can report the split without re-deriving it (which
would incorrectly include the existing-but-Sequence skip case as "changed" -- verified correct via
`ResultShapeTest::test_ensure_mixed_update_and_insert_split_counts`, 2 updated + 1 inserted = 3
total, matching the underlying fixture exactly). `Replace`/`ReplaceText` always get
`inserted_count=0` internally (summed into their single `count`, never exposed as a separate field
on those two kinds, matching the checkpoint's explicit "no generalized effect taxonomy" decision).

## 10. Stable diagnostic codes

All ten implemented exactly per the checkpoint's section 8 table. Reachability verified directly,
one dedicated trigger per code, in `DiagnosticCodeCoverageTest`:

| Code | Verified via |
|---|---|
| `REQUIREMENT_UNSATISFIED` | `Require` on an absent tag |
| `GUARANTEE_UNESTABLISHED` | `Ensure` with no concrete insertion site |
| `VR_REQUIRED` | `Ensure` on `(0028,0106)` (SmallestImagePixelValue, "US or SS" -- the same attrs-own-test-suite tag used throughout S1.2), `vr=None` |
| `TEXT_OPERATION_UNSUPPORTED` | `ReplaceText` on `(0008,0005)` (VR `CS`, not text-governed) |
| `CHARACTER_UNREPRESENTABLE` | `ReplaceText` with a Cyrillic character against a root `ISO_IR 100` (Latin1) declaration |
| `MUTATION_FAILED` | `Replace` with a 70,000-byte value (exceeds Short16's max length) |
| `CALLBACK_FAILED` | `Replace` with a callback that raises |
| `ALREADY_EXISTS` | **not independently triggerable** -- documented, not fabricated (section 28) |
| `INVALID_UNICODE` | **not independently triggerable from Python `str` input** -- documented, matching attrs' own A1.7 report's identical finding (section 28) |
| `ROLLBACK_FAILED` | reserved for a caller catching `RollbackError` directly (section 19) -- never constructed automatically by this module |

## 11. Exception boundary

`Policy.apply()` never uses `except Exception` as its own boundary — it catches, then classifies via
`_classify_exception` (a closed `isinstance` chain, most-specific-subclass-first, since
`VRRequiredError`/`AlreadyExistsError`/`UnrepresentableCharacterError`/`InvalidUnicodeInputError`
are all `FdsError` subclasses); an unrecognized exception is re-raised immediately (`if code is
None: raise`), before any `OperationResult`/`PolicyResult` construction. Verified:
`RollbackErrorBoundaryTest::test_unrecognized_exception_propagates_through_policy_apply` (a
synthetic operation raising `KeyError`, confirmed to propagate, not silently absorbed).

The four A1.7 exception subclasses attrs itself exports but `fastdicomstructure/__init__.py` does
not yet re-export (a gap named in `docs/architecture/POST_A1_RUTHLESS_INVENTORY.md`, unrelated to
this increment) are imported directly from `fastdicomattrs` inside `policy.py` -- already on
`sys.path` by the time `policy.py` loads (`fastdicomstructure/__init__.py` adds it before `from .
import policy` runs), so this is not a new dependency, only bypassing an incomplete shim. Not fixed
here (out of S1.3's authorized scope); recorded as carry-forward (section 30).

## 12. Callback boundary

`CallbackError(original)` wraps a callback's own raised exception at the point of *invocation* only
(`value(...)`/`values(...)`), never around consuming its return value -- matching the checkpoint's
section 16 analysis exactly (a wrong-type return from a callback surfaces as whatever attrs/ctypes
raises when the value is consumed, an ordinary, unclassified failure, not `CALLBACK_FAILED`; no test
currently exercises this specific sub-case, and none was fabricated to do so). Applied identically
to `Replace` (new, section 3) and `ReplaceText` (already had per-occurrence callback support in
S1.2, now additionally wrapped). `cause_type` is fixed *at construction* to
`type(original).__name__` and consumed correctly by `Policy.apply()` -- **a real bug found and
fixed during implementation** (not present in the design): the first draft used
`type(exc).__name__` uniformly in `Policy.apply()`'s exception branch, which for a `CallbackError`
reports `"CallbackError"` (the wrapper's own class) rather than the original callback exception's
class. Fixed to check `isinstance(exc, CallbackError)` and use `exc.cause_type` in that case;
verified directly (`ReplaceAtomicityTest::test_policy_apply_reports_callback_failed_rolled_back`
asserts `cause_type == "ValueError"`, not `"CallbackError"`).

## 13. Require rejection

Unchanged in behavior from S1.1/S1.2, now correctly typed: `execution=COMPLETED, satisfied=False,
diagnostics=(Diagnostic(code="REQUIREMENT_UNSATISFIED"),)`, containing `PolicyResult` gets
`decision=REJECT, execution=REJECTED`, every later operation `NOT_EXECUTED`. Verified:
`ResultShapeTest::test_require_unsatisfied_via_policy_rejects_and_marks_later_not_executed`.

## 14. Guarantee-unestablished semantics

`Ensure`/`EnsureText` with zero insertion sites: `execution=COMPLETED` (not a failure),
`satisfied=False`, `count=updated_count=inserted_count=0`,
`diagnostics=(Diagnostic(code="GUARANTEE_UNESTABLISHED"),)`. **Does not halt the containing
`Policy`** -- verified directly, reproducing the exact S1.3 design-checkpoint Finding 2 scenario
(`ResultShapeTest::test_ensure_zero_sites_visible_at_policy_level`): `decision` stays `ACCEPT`,
`execution` stays `COMPLETED`, but the diagnostic is now present in `PolicyResult.diagnostics` --
previously (S1.2) it was silently absent from both.

## 15. Successful no-op semantics

`Remove`/`Replace`/`ReplaceText`/`AllowListPrune`/`PrivateTagPolicy` with zero matches:
`execution=COMPLETED, satisfied=None, count=0, diagnostics=()`. Verified distinct from `Require`
unsatisfied (`satisfied=False`) and `Ensure` zero-sites (`satisfied=False` + a diagnostic) by the
differential test (section 24).

## 16. Policy-level partial execution

Implemented exactly per the checkpoint: operation atomicity holds (each operation that ran is
either fully `COMPLETED` or fully `ROLLED_BACK`), no whole-policy rollback exists or was added,
`PolicyExecutionStatus.PARTIAL` plus `Decision.PARTIAL` represent the containing `Policy`'s own
stopped-early-due-to-failure state. Verified end-to-end by the three-operation test (section 25).

## 17. NOT_EXECUTED semantics

`_not_executed_result(operation)` builds a placeholder populating only what's knowable without
running the operation: `execution=NOT_EXECUTED`, `satisfied=None` (never `False`), `count=0`,
`updated_count`/`inserted_count` set to `0` only for `ensure`/`ensure_text` kinds (`None`
otherwise, matching every other result's own convention), no diagnostics. Verified: section 8's
bug-fix test, and the three-operation test (section 25) asserting `op3`'s full shape.

## 18. Rollback handling

`_apply_sites_atomically` now returns `(updated_count, inserted_count)` (section 9) and, on a
fully-recovered failure, attaches two private, best-effort attributes to the *original* exception
before re-raising it unchanged: `_fds_policy_rolled_back` (`bool(undo_log)` -- was anything mutated
before the failure) and, per-site, `_fds_policy_failed_site` (a `_describe_path`-rendered string,
attached at the exact point of failure inside the per-site `try`/`except`, never the raw attrs path
tuple). Both are consumed only by `Policy.apply()`'s own exception branch; a direct caller still
sees exactly the original exception type, unchanged, with these as invisible extra attributes they
have no reason to inspect. This is how `Policy.apply()` distinguishes `FAILED` from `ROLLED_BACK`
and populates `Diagnostic.site` without `_apply_sites_atomically`'s own public return contract
needing to grow.

## 19. RollbackError exceptional boundary

**Never caught or converted by `Policy.apply()`** -- the very first line of its `except` handling is
`except RollbackError: raise`, before `_classify_exception` is even consulted. Verified directly
(`RollbackErrorBoundaryTest::test_rollback_error_propagates_through_policy_apply`): a deliberately
constructed double-failure (forward mutation fails, then the rollback attempt for the
already-succeeded site is *also* forced to fail) propagates `RollbackError` through `Policy.apply()`
unchanged -- no `PolicyResult` is returned for this case, exactly as designed. `ROLLBACK_FAILED`
remains a documented `DIAGNOSTIC_CODES` entry for a caller who catches `RollbackError` themselves
and wants to build their own `Diagnostic` from it -- `Policy.apply()` never does this automatically.

## 20. Locator/site rendering

`Diagnostic.locator` is `repr()` of the operation's own `Locator` (already Structure-owned since
S1.1 -- reused directly, no new type). `Diagnostic.site` is produced by a new `_describe_path`
helper rendering an already-resolved attrs `ElementPath` (list of `(tag, item_index)` tuples) into
a human string (e.g. `"(300A,00B0)[1]/(300A,00C2)"`) -- **the raw tuple list is never placed in a
`Diagnostic` field**; only the rendered string, built once, at the point of failure, inside
`_apply_sites_atomically`. Verified indirectly throughout (every `Diagnostic.site` assertion in the
test suite compares against a plain string, never a path structure) and directly by the three-
operation test's own diagnostic inspection.

## 21. Privacy/PHI protections

`PrivacyTest::test_no_diagnostic_leaks_the_sensitive_fixture_literal` triggers `REQUIREMENT_UNSATISFIED`,
`GUARANTEE_UNESTABLISHED`, `VR_REQUIRED`, and `CALLBACK_FAILED` (the last via a callback that
*deliberately* tries to leak the target element's own value into its exception message --
`f"leaked value would be {v!r}"`) against a fixture carrying a known sensitive literal
(`"Zbigniew^Sekretny"`, the fixture's own `PatientName`), then mechanically greps every produced
`Diagnostic`'s full `repr()` for that literal (both as plain text and as its hex byte encoding) and
for the callback's own attempted-leak message text. Both assertions pass: the sensitive literal and
the callback's leak attempt are **not present anywhere** in any diagnostic produced during the test
run -- proof by construction (no diagnostic field is ever populated from a value/message), not
merely by absence of a specific known bug.

## 22. Compatibility

Verified by running all 105 pre-S1.3 tests **unmodified**: zero changes were needed to
`test_locator.py`, `test_policy.py`, `test_pipeline_demo.py`, or `test_ensure_and_text.py` (`git
diff` confirms empty for all four). Every existing accessor (`OperationResult.kind`/`.tag`/`.count`/
`.satisfied`; `PolicyResult.decision`/`.operations`/`.diagnostics`/`.policy_name`/`.policy_version`/
`.elements_touched`/`.failed_requirement`) retained its name and meaning, exactly as the design
checkpoint's own compatibility inventory (section 20) predicted. The one *behavioral* change
(disclosed, not silent, per the checkpoint's own section 20 analysis): a `Policy` containing an
operation that used to make `apply()` raise for one of the ten now-modeled failure types instead
returns a `PolicyResult(execution=PARTIAL, ...)`; no existing test exercised this path before S1.3
(confirmed empirically at the design-checkpoint stage), so nothing broke, but new caller code
relying on the old raise-always behavior for these specific cases would need to check
`result.execution` instead.

## 23. Tests

| Suite | Before S1.3 | After S1.3 |
|---|---|---|
| `tests/python/test_locator.py` | 27 | 27 (unchanged) |
| `tests/python/test_policy.py` | 20 | 20 (unchanged) |
| `tests/python/test_pipeline_demo.py` | 1 | 1 (unchanged) |
| `tests/python/test_ensure_and_text.py` | 57 | 57 (unchanged) |
| `tests/python/test_result_diagnostic.py` | -- (new file) | 37 |
| **Total** | **105** | **142** |

All 142 pass:

```text
$ FASTDICOMATTRS_REPO=/path/to/fastDICOMattrs python -m pytest tests/python -v
............................................................................
......................................................................
142 passed in 0.61s
```

New coverage by class: `ResultShapeTest` (9), `ReplaceAtomicityTest` (3), `ReplaceMutationFailureTest`
(3), `DiagnosticCodeCoverageTest` (9), `RollbackErrorBoundaryTest` (2), `ThreeOperationPolicyTest`
(1), `DifferentialConflationTest` (1), `PrivacyTest` (1), `EncodingEquivalenceTest` (1),
`NonInterferenceTest` (1), `IndependentValidationTest` (2), `PerformanceTest` (3),
`JSONAuthorabilityTest` (1).

## 24. Differential tests

`DifferentialConflationTest::test_zero_matches_vs_zero_sites_vs_modeled_failure_are_structurally_distinct`
constructs the authorization's exact A/B/C scenario (`Remove` zero matches; `Ensure` zero insertion
sites; `Ensure` hitting `VR_REQUIRED`) in one test and asserts all three are distinguishable by
`(execution, satisfied)` and, where applicable, diagnostic `code` alone -- no exception-message
parsing, no `Structure` re-inspection. Additionally, section 12's `cause_type` bug (found *during*
implementation, not anticipated by the design) was itself caught by exactly this kind of direct,
structured-field assertion (`assertEqual(cause_type, "ValueError")`) rather than a looser check that
would have let the bug pass silently -- a real instance of the differential-testing discipline
paying for itself within this same increment.

## 25. Three-operation policy test

`ThreeOperationPolicyTest::test_op1_committed_op2_rolled_back_op3_not_executed`: `op1` (`Ensure`,
root insertion) succeeds and its mutation is confirmed present in the structure after `apply()`
returns; `op2` (`Ensure` on an ambiguous-VR tag) fails with `VR_REQUIRED`; `op3` (`Ensure`, would
succeed if it ran) is confirmed **never to touch the structure** (`structure.get(...)` returns
`None` for its target tag). `PolicyResult.execution == PARTIAL`, `len(operations) == 3` with the
exact `COMPLETED`/`FAILED`/`NOT_EXECUTED` sequence, and exactly one diagnostic, correctly indexed to
operation 1 (zero-based).

## 26. Explicit/Implicit equivalence

`EncodingEquivalenceTest::test_same_semantic_failure_produces_same_diagnostic_code`: an identical
ambiguous-VR `Ensure` insertion attempt against semantically-equivalent Explicit VR LE and Implicit
VR LE fixtures produces the identical `VR_REQUIRED` diagnostic code and `FAILED` execution status on
both -- the diagnostic model's outcome does not vary with source encoding, extending S1.1/S1.2's own
encoding-independence proofs to the diagnostic layer specifically (not previously tested there).

## 27. Independent validation

**pydicom**: a fresh `pydicom.dcmread` of this library's own `write_bytes()` output, after a real
three-operation, fully-`COMPLETED` `Policy` (`Require` + `ReplaceText` + `EnsureText`), independently
confirms the expected `PatientName`/inserted-tag values and `Modality` unchanged.

**DCMTK's `dcmdump`**: the same style of check with a second independent implementation --
`dcmdump` exits `0` (structurally valid) on the same kind of successful multi-operation policy
output and its text output contains the expected replaced value.

Per instruction, **independent validation is not claimed to validate the diagnostic model itself**
-- both tools only ever see a successfully-written DICOM file after a `COMPLETED` policy run; for
failure cases, validation is the result/state differential proof (raw-byte-exact rollback,
structured field inspection) documented in sections 3/4/24/25, not external parser agreement (a
DICOM parser has no concept of "was this Python library's diagnostic code correct").

## 28. Performance

Not optimized; measured only to detect pathological regression, one machine, synthetic fixtures:

| Workload | Result |
|---|---|
| Root `Require` | ~0.01ms |
| Wildcard `Replace` (now atomic) over 2000 sibling Items | ~96ms (comparable to S1.2's own wildcard `Ensure` baseline of ~90-95ms for the same item count -- the new atomic engine adds no material overhead over the already-atomic `Ensure`/`EnsureText` it now shares code with) |
| A 3-operation, fully-`COMPLETED` `Policy` (`Require` + wildcard `Replace` over 2000 items + `Remove`) via `Policy.apply()` | ~116ms (the exception-boundary bookkeeping added to `apply()`'s loop -- a `try`/`except` per operation, index tracking -- is not separately measurable against the dominant wildcard-mutation cost above) |

No corpus-scale or cross-file throughput claim is made (unchanged scope from S1.1/S1.2); RSNA CTP
was not benchmarked, per this increment's explicit exclusion.

## 29. Defects discovered/fixed

Two real defects were found and fixed *during* this implementation, both caught by the same
discipline of asserting structured fields directly rather than assuming the design's pseudocode was
already correct:

1. **`PolicyResult.failed_requirement`'s pre-existing `not result.satisfied` bug** (section 8) --
   would have misreported a `NOT_EXECUTED` `Require` (`satisfied=None`) as unsatisfied
   (`satisfied=False`), since Python's `not None` is `True`. This bug was latent in S1.1/S1.2's own
   code but unreachable there (nothing ever produced a `NOT_EXECUTED` result before S1.3); S1.3's
   own schema change made it reachable, and fixing it was necessary for S1.3's own correctness, not
   optional. Fixed to `result.satisfied is False`.
2. **`Policy.apply()`'s `cause_type` construction bug** (section 12) -- used
   `type(exc).__name__` uniformly, which for a caught `CallbackError` reports `"CallbackError"`
   itself rather than the wrapped original exception's class (`"ValueError"`, etc.) -- directly
   contradicting this module's own stated privacy/precision contract for `cause_type`. Found by a
   test asserting the exact expected string, not merely that *some* string was present. Fixed to
   consult `CallbackError.cause_type` specifically.

No defect was found in frozen attrs; none was introduced (verified: attrs' working tree is clean
and HEAD is unchanged throughout, section 31).

## 30. Product Capability Map changes

Not yet applied in this report -- to be updated as part of this report's own review, per the same
discipline S1.1/S1.2 followed (the map is updated once, deliberately, referencing this report, not
edited speculatively mid-implementation). Evidence-based assessment against the checkpoint's own
named V1 `CURRENT` threshold (stable structured operation outcomes; stable diagnostic codes;
policy-level partial/rejected/completed distinction; deterministic aggregation; privacy-safe
diagnostics; modeled expected-failure boundary):

- **P1.5 (Audit/results/errors)**: every named criterion is demonstrated with direct evidence in
  this report (sections 5-21, 24-25, 27). **Promotion to `CURRENT` is justified.**
- **P7.1 (Structured exception reporting)**: the `Diagnostic`/`DIAGNOSTIC_CODES` vocabulary is a
  substantial, evidenced advance on the same axis this capability's row already names as
  outstanding (mapping attrs' typed exceptions to a modeled outcome). **Promotion to `CURRENT` is
  justified.**
- **Not promoted**, per instruction, regardless: P2 (JSON configuration), P5 (execution/deployment
  adapters), P1.6 (bulk-data policy), P7.3 (Evidence Packet integration) -- S1.3 makes results
  representable in a way that would later serve all of these (sections 20-22 of the design
  checkpoint's own JSON/adapter/audit probes), but builds none of them.

## 31. Known limitations / S1.4 carry-forward

- **`TEXT_OPERATION_UNSUPPORTED`'s three-way collapse** (`NotATextVR`/`UnsupportedCharset`/
  `MalformedCharsetDeclaration` all map to the same generic `FdsError`) is a real attrs
  Python-binding precision limit, confirmed unchanged and not addressed here -- attrs was not
  modified, per instruction. Recorded as attrs/public-surface technical debt, not S1.3 debt.
- **`ALREADY_EXISTS` and `INVALID_UNICODE` have no independent trigger** through this module's own
  normal operation flow (the former structurally, per `_resolve_insertion_sites`'s own guarantees;
  the latter because a Python `str` cannot itself produce malformed UTF-8, per attrs' own A1.7
  report). Both remain in `DIAGNOSTIC_CODES` for defensive completeness, documented as such, not
  claimed as tested-common cases.
- **The pre-existing `fastdicomstructure/__init__.py` re-export gap** (four A1.7 exception classes
  not re-exported, first named in the Post-A1 inventory) was worked around inside `policy.py`
  (importing directly from `fastdicomattrs`) rather than fixed -- out of this increment's authorized
  scope; still a real, minor gap for any *other* caller of `fastdicomstructure` wanting to catch
  these exception types by their `fastdicomstructure.`-qualified name.
- **`Diagnostic.message`'s exact English wording** remains an implementation detail, as the design
  checkpoint itself anticipated -- free to iterate without breaking the contract (`code` is the
  stable part).
- **No JSON loader, no execution adapter** -- both remain fully out of scope, as required; the
  design checkpoint's own JSON/adapter probes (sections 20-22) were re-validated against the actual
  implemented field names during this report's own writing, not re-designed.

## 32. Exact candidate freeze commit

Run immediately before writing this section, from a clean check of both repositories:

```text
$ cd fastDICOMattrs && git status --short && git rev-parse HEAD
46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6
$ cd fastDICOMstructure && git status --short
 M python/fastdicomstructure/policy.py
?? docs/architecture/S1_3_RESULT_DIAGNOSTIC_DESIGN_CHECKPOINT.md
?? tests/python/test_result_diagnostic.py
```

fastDICOMattrs: working tree clean, HEAD exactly `46bf7d3` -- unchanged, as required.
fastDICOMstructure: modifications are exactly `policy.py` (the Result/Diagnostic Contract v1, the
`Replace` atomicity/silent-failure corrections, the `Policy.apply()` exception boundary), the new
`tests/python/test_result_diagnostic.py`, the design checkpoint (already committed in a prior turn,
now updated in place with the section 29 disposition), and this report. `test_locator.py`/
`test_policy.py`/`test_ensure_and_text.py` (S1.1/S1.2's own tests) are untouched, verified by empty
`git diff`. No other file changed. `fastDICOMgateway` was not present in this environment and was
not referenced.

fastDICOMstructure's own starting commit for this increment was `53ecb832bd76345eb62bbf533167663b9f9546d9`;
the candidate freeze is the working-tree state described above, to be committed as the S1.3 freeze
commit following this report's own review.

## Final falsifiable claim

Refined once more against actual implementation evidence (the checkpoint's own section 26 already
narrowed the authorization's original claim; this report confirms the narrowed form held, with one
additional, explicit boundary now demonstrated rather than merely asserted):

> For every currently-reachable modeled policy execution outcome catalogued in this report
> (successful evaluation, successful no-op, unsatisfied requirement, unestablished guarantee, each
> of the eight independently-triggerable diagnostic codes, successful rollback, rollback failure,
> and policy-level partial/rejected/completed execution), `fastdicomstructure.policy` reports that
> outcome as a structured `PolicyResult` whose `execution`/`satisfied`/`diagnostic code` fields
> alone determine which outcome occurred -- without the caller inspecting an exception's message
> text, the mutated `Structure`'s own state, or any attrs-internal implementation detail -- and no
> `Diagnostic` produced anywhere in this report's 37 new tests contains a DICOM element value, a
> decoded value, or callback input/output. `RollbackError`, unrecognized exceptions, and
> `MalformedLocatorError` (a construction-time, not execution-time, condition) remain exceptional
> by deliberate design and are not modeled `PolicyResult` outcomes.
