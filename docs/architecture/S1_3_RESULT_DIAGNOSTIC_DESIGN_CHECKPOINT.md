# S1.3 Design Checkpoint — Result / Diagnostic Completion

**Status: ANALYSIS AND DESIGN ONLY.** No production code in this repository, and no file in
`fastDICOMattrs`, was modified to produce this checkpoint. Every claim about current behavior below
was verified by direct inspection of frozen `policy.py` and by running real code against the frozen
S1.2 commit (not assumed from memory of prior reports) — see section 2 for the evidence and its
provenance.

## 1. Frozen starting state

| Item | Value |
|---|---|
| fastDICOMattrs | frozen at `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6`, A1 COMPLETE |
| fastDICOMstructure | S1.1 FROZEN `bdc324cfe5b71c7080d7efee8d745186d7020366`; S1.2 FROZEN `53ecb832bd76345eb62bbf533167663b9f9546d9`, 105/105 tests passing |
| Inspected directly for this checkpoint | `python/fastdicomstructure/policy.py` in full (1042 lines); `tests/python/test_policy.py`, `test_locator.py`, `test_ensure_and_text.py` for existing coverage gaps; three ad hoc verification scripts run against the frozen commit (not committed) confirming `Policy.apply()`'s actual exception-propagation behavior, the `Ensure`-`satisfied=False`-invisible-at-policy-level gap, and a real `Replace`-vs-`ReplaceText` callback-atomicity asymmetry (all reported as new findings below, not assumed from the S1.1/S1.2 reports' own prose) |

## 2. Current outcome/failure inventory (evidence, not assumption)

Three findings below were **not** anticipated by the S1.1/S1.2 reports and were discovered only by
running code against the frozen commit — flagged explicitly as new evidence.

**Finding 1 (new): `Policy.apply()` has no exception boundary at all.** `apply()`'s loop
(`policy.py` lines 1017-1031) calls `operation.apply(structure)` with no `try`/`except` anywhere.
Verified directly: a three-operation `Policy` where operation 1 (`Ensure`) succeeds and mutates,
operation 2 (`Ensure` on an ambiguous-VR tag) raises `VRRequiredError`, and operation 3 would
otherwise succeed —

```text
apply() raised: VRRequiredError fds_structure_insert_path: VR required (inference was ambiguous or unavailable)
op1's mutation persisted? b'OP1-APPLIED '
op3 ran? None
```

`policy.apply()` raises the **raw attrs exception**, with **no `PolicyResult` returned at all** —
the caller loses every already-computed `OperationResult`, including operation 1's, and must
inspect the (already-partially-mutated) `Structure` themselves to reconstruct what happened.
Operation 3 correctly never runs, but that fact is only visible by its absence from a result the
caller never receives.

**Finding 2 (new): an `Ensure`/`EnsureText` that reports `satisfied=False` is invisible at the
`PolicyResult` level.** Verified: an `Ensure` targeting a locator with zero insertion sites
(`satisfied=False`), followed by an unrelated no-op `Remove`, produces:

```text
decision: Decision.ACCEPT
diagnostics: ()
failed_requirement: None
```

Only `Require`'s dissatisfaction reaches `Decision`/`diagnostics`/`failed_requirement`
(`apply()`'s only check is `isinstance(operation, Require) and not result.satisfied`). A caller
who checks the "headline" fields (`decision`, `diagnostics`) — exactly the fields the current API
markets as the summary — sees `ACCEPT`, no diagnostics, and would conclude nothing is wrong, while
a guarantee the policy was supposed to establish silently was not. This generalizes and is more
serious than the single conflation named in the authorization ("zero insertion sites vs. sites
existed but rolled back") — it is a structural gap in how *any* non-`Require` dissatisfaction
surfaces.

**Finding 3 (new): `Replace`'s own callback is not atomic across a wildcard's multiple matches;
`ReplaceText`'s is.** Verified with an identical two-Item wildcard scenario, callback failing on
the second match:

```text
raw Replace: item0 after (was AAAA): b'ZZZZ'   item1 after (was BBBB): b'BBBB'   # item0 STAYS mutated
ReplaceText: item0 after (was AAAA): b'AAAA'   item1 after (was BBBB): b'BBBB'   # item0 rolled back
```

`Replace` (S1.1, never retrofitted with S1.2's atomic engine — a deliberate choice recorded in the
S1.2 report, correct on its own terms since `Replace` "only ever wraps attrs calls that cannot
meaningfully fail once `resolve_locator` has confirmed a path exists") did not anticipate that a
**caller-supplied callback** is itself a source of mid-batch failure independent of attrs' own
mutation reliability. `ReplaceText` (S1.2) is atomic here purely as a side effect of routing
through `_apply_sites_atomically`, which treats a callback's own exception identically to an attrs
mutation failure. This is a real, user-visible inconsistency between two operations with otherwise
parallel contracts, not previously named in either the S1.1 or S1.2 reports. **Not fixed by this
checkpoint** (no implementation authorized) — recorded as a risk/open question (section 28) with a
recommendation.

**Full per-operation outcome matrix**, each row verified against frozen code (source line or direct
test, not inferred):

| Operation | Zero-match/site | N matches | Malformed locator | Unsupported target | Other failure |
|---|---|---|---|---|---|
| `Require` | `count=0, satisfied=False`; `Policy` -> `REJECT` + one `Diagnostic` | `count=N, satisfied=True` | raises `MalformedLocatorError` at *construction*, before any `Policy`/`apply()` involvement | n/a (read-only) | none possible -- `resolve_locator` never raises |
| `Remove` | `count=0, satisfied=True` (successful no-op) | `count=N` removed | same as above | n/a (delegates to `erase`, bool-return, never raises) | none |
| `Replace` | `count=0, satisfied=True` | `count=N`, but **silently under-counts** if `set_value` returns `False` (value too long) -- no exception, no diagnostic, just a smaller `count` than matches (a pre-existing, undocumented-until-now S1.1 gap) | same | existing-but-Sequence target silently skipped, not counted | **callback exception propagates raw, immediately, with whatever partial mutation already happened left in place (Finding 3)**; callback returning a wrong type surfaces a raw `TypeError` from ctypes marshaling, not a Structure-level error |
| `ReplaceText` | `count=0, satisfied=True` | `count=N`, atomic | same | existing-but-Sequence target silently skipped | `NotATextVR`/`UnsupportedCharset`/`MalformedCharsetDeclaration` all collapse to one generic `FdsError` (verified: all three map to the same ABI status, `FDS_STATUS_UNSUPPORTED` -- see section 5's precision limit); `UnrepresentableCharacterError`/`InvalidUnicodeInputError` are distinctly typed; callback exception is caught by the atomic engine and **does** trigger rollback (Finding 3's other half) |
| `Ensure` | zero insertion sites: `count=0, satisfied=False`, **invisible at `PolicyResult` level (Finding 2)** | `count=N` sites updated-or-inserted, `satisfied=True` | same | existing-but-Sequence target silently skipped (mid-implementation discovery, S1.2 report section 21) | `VRRequiredError` (ambiguous/unknown/private-data VR), `AlreadyExistsError` (theoretically reachable, not exercised by any current test), raw `set_value` returning `False` wrapped in the internal `_MutationFailed` marker -- both propagate raw after atomic rollback; `RollbackError` if rollback itself fails |
| `EnsureText` | same as `Ensure`, `kind="ensure_text"` | same as `Ensure` | same | existing-but-Sequence skip; text-VR failures as `ReplaceText`'s row | `VRRequiredError`, `UnrepresentableCharacterError`, `InvalidUnicodeInputError`, generic `FdsError` (text-VR/charset), `RollbackError` |
| `AllowListPrune` | `count=0` (nothing to prune) is possible but `satisfied` is always `True` (no condition) | `count=N` | n/a -- takes a bare tag tuple set, not a `Locator` | n/a | none -- delegates entirely to `_remove_matches`, which never raises |
| `PrivateTagPolicy` | `count=0` if `remove=False` or nothing private present | `count=N` | n/a | n/a | none |

**`PolicyResult.diagnostics` is, in practice, always empty or exactly one element** -- `apply()`'s
only `Diagnostic`-producing code path is the single `Require`-rejection branch; no other operation
outcome, including every failure row above, ever reaches a `Diagnostic` today (they either don't
produce one by design, as with a `Remove`/`Replace` no-op, or they raise an uncaught exception that
prevents `PolicyResult` construction entirely, per Finding 1).

## 3. Current semantic conflations

Beyond the one named in the authorization (which the evidence confirms and generalizes -- Finding
2), four additional conflations, all evidence-backed:

1. **Exception vs. result, globally (Finding 1).** There is currently no boundary at all between
   "a policy execution outcome worth reporting structurally" and "an uncaught exception." Every
   non-`Require` failure of every kind -- VR required, charset failure, raw mutation failure,
   callback bug, rollback failure -- currently destroys the entire `PolicyResult`, including
   already-computed operation outcomes for operations that ran and succeeded earlier in the same
   `Policy`.
2. **`satisfied`'s dual meaning.** For `Require`, `satisfied` answers "does the dataset meet this
   condition." For `Ensure`/`EnsureText`, `satisfied` answers a structurally identical question
   ("was the guarantee established"), but for `Remove`/`Replace`/`ReplaceText`/`AllowListPrune`/
   `PrivateTagPolicy`, `satisfied` is hardcoded `True` and means nothing -- it is not a condition
   those operations have. Three different semantics sharing one field name and one Python type.
3. **`count`'s dual meaning for `Ensure`/`EnsureText`.** A single integer cannot currently tell a
   caller "guaranteed 3 things were already correct" from "guaranteed 3 things by creating them"
   from a mix of both -- information the operation itself computes (`_apply_sites_atomically`
   already distinguishes update vs. insert internally) and then discards before returning `count`.
4. **Silent under-counting as a fourth failure shape (`Replace` row above).** `Replace`'s
   `set_value`-returns-`False` case is neither "matched and changed" nor "matched and failed
   loudly" -- it is matched, silently not changed, not counted, not diagnosed. This is a real,
   already-existing (pre-S1.3) gap this checkpoint did not introduce but must account for when
   defining what "changed" means.

Finding 3 (the `Replace`/`ReplaceText` atomicity asymmetry) is a **behavioral** inconsistency, not
strictly a *result-model* conflation -- it is recorded in section 2 and carried to section 28 as a
risk, not folded into the dimensional analysis below, since fixing it (if S1.3 chooses to) is an
implementation question about `Replace`'s own mutation loop, not about how results are reported.

## 4. Required semantic dimensions

The authorization's five proposed dimensions (A-E) are evaluated against the evidence above, not
adopted by default.

- **A (Policy satisfaction) -- confirmed, real, and independent.** Evidence: `Require` and
  `Ensure`/`EnsureText` both have a genuine condition/guarantee; the other five operations do not.
  This is exactly the axis that should replace `satisfied`'s current dual meaning (section 3.2).
- **B (Execution status) -- confirmed, and the single most under-modeled dimension today.**
  Evidence: Finding 1 shows there is currently *no* execution-status field at all; success and
  every failure mode are distinguished only by "did `apply()` return or raise," which loses
  everything about *where* in a multi-operation `Policy` a failure occurred (Finding 1's op1/op3
  visibility loss).
- **C (Match/target cardinality) -- confirmed, largely already present (`count`), but needs
  splitting for exactly one family.** Evidence: section 3.3 -- only `Ensure`/`EnsureText` mix two
  cardinalities (matched-and-updated vs. newly-inserted) in one count; every other operation's
  single `count` is already unambiguous given its `kind`.
- **D (Mutation effect) -- partially real, mostly subsumed by C once C is split correctly.** The
  authorization's own examples ("examined, removed, replaced, inserted, unchanged, skipped") mostly
  reduce to: `matched_count` (C) plus, only for `Ensure`/`EnsureText`, an `updated`/`inserted` split,
  plus one boolean-shaped fact ("was an existing-but-Sequence site skipped") that is currently
  silent and arguably belongs in a diagnostic (E) the first time it happens, not a new count field
  nobody has asked to see. **Recommendation: do not add a fifth "effect" enum distinct from a
  refined C -- this would be over-modeling for what the evidence actually shows is needed.**
- **E (Diagnostic information) -- confirmed, and currently the most starkly absent.** Evidence:
  section 2's matrix -- of roughly a dozen distinct failure shapes identified, exactly one
  (`Require` rejection) currently produces a `Diagnostic` at all.

**Verdict: four dimensions, not five** -- A (satisfaction), B (execution status), C (cardinality,
refined per-operation-family rather than a fixed universal set of named counts), E (diagnostics).
D is folded into C plus E rather than kept separate, since the evidence does not show a case where
a distinct "effect" taxonomy is needed beyond "how many, of which kind" (C) and "why, if unusual"
(E).

## 5. Candidate result models

**Design A -- minimal additive patch.** Add one field to `OperationResult` (`execution:
ExecutionStatus`, default `COMPLETED`) and one to `PolicyResult` (`execution:
PolicyExecutionStatus`). Wrap `Policy.apply()`'s loop in a blanket `try/except Exception`,
converting *any* operation exception into a `FAILED` outcome + a generic `Diagnostic` carrying
`str(exception)`. Leave `satisfied`/`count` exactly as they are.

- *Semantic precision*: poor -- `satisfied`'s conflation (section 3.2) and `count`'s conflation
  (section 3.3) both persist untouched; a blanket `except Exception` also catches `RollbackError`
  and unclassified bugs identically to ordinary attrs failures, exactly what section 6/10 argues
  against.
- *API simplicity*: highest of the three.
- *Compatibility*: perfect (pure addition).
- *JSON authorability*: adequate for the new field, unchanged for the rest.
- *Future adapter/audit usefulness*: low -- `str(exception)` as diagnostic content directly
  violates the privacy rule (section 15) whenever an exception message happens to embed a value,
  and gives S1.5 no stable code to route on.
- *Privacy*: **fails** -- storing `str(exception)` is exactly the "raw exception string as
  contractual data" the authorization warned against.
- *Implementation complexity*: lowest.
- *Over-modeling risk*: none, but at the cost of solving almost nothing this checkpoint's own
  evidence shows is broken. **Rejected** -- cheapest, but does not address findings 1-3 adequately
  and fails the privacy rule outright.

**Design B -- explicit execution-state + satisfaction + diagnostics, additive.** Add
`execution: ExecutionStatus` and `satisfied: Optional[bool]` (re-scoped, not removed) to
`OperationResult`; add `updated_count`/`inserted_count` (`Optional[int]`, populated only for
`Ensure`/`EnsureText`) alongside the existing `count` (kept, meaning "total changed," backward
compatible); add a **stable diagnostic code vocabulary** (section 8) to a redesigned `Diagnostic`
carried per-operation, not only at the `Policy` level; add `execution: PolicyExecutionStatus` to
`PolicyResult` (`COMPLETED`/`REJECTED`/`PARTIAL`); `Policy.apply()` catches a **narrow, explicit set**
of known "expected policy execution failure" exception types (never a blanket `except Exception`),
converts them to a `FAILED` `OperationResult` + `Diagnostic`, marks remaining operations
`NOT_EXECUTED`, and **always returns a `PolicyResult`** for this class of failure; `RollbackError`
and any unrecognized exception type are deliberately left uncaught, propagating raw (section 6/10).

- *Semantic precision*: high -- every conflation in section 3 is resolved by a dimension with real
  evidence behind it (section 4); nothing is added that section 4 didn't justify.
- *API simplicity*: moderate -- more fields than Design A, but every one maps to a named, real gap.
- *Compatibility*: fully additive (section 20) -- no existing field is removed, renamed, or
  repurposed incompatibly.
- *JSON authorability*: high -- every new field is a plain string/enum-as-string/int/optional,
  already the shape S1.1/S1.2's own JSON probes used.
- *Future adapter/audit usefulness*: high -- `execution` + `satisfied` + diagnostic `code` together
  answer exactly the routing questions section 13 poses, without exception-text parsing.
- *Privacy*: satisfies the rule by construction -- diagnostics carry `code`/`locator` repr/`tag`/
  `cause_type` (exception class name only) and never raw values (section 15).
- *Implementation complexity*: moderate -- the new exception-catching boundary and the
  `CallbackError` wrapper (section 6) are real, bounded new code, not a rewrite.
- *Over-modeling risk*: low -- every field traces to a specific verified gap; the temptation to add
  a fifth "effect" dimension was explicitly rejected (section 4).

**Design C -- unified single outcome enum, no separate execution/satisfaction fields.** Collapse
`execution` and `satisfied` into one closed enum per operation
(`SATISFIED`/`UNSATISFIED`/`APPLIED`/`NO_OP`/`FAILED`/`ROLLED_BACK`/`ROLLBACK_FAILED`/
`NOT_EXECUTED`).

- *Semantic precision*: **worse than Design B**, on inspection -- it re-conflates exactly the two
  axes the authorization asked to keep independent. Concretely: "a `Require` satisfied, in a
  `Policy` where a *later* operation still failed" needs both "this operation's condition held"
  and "the containing policy did not complete" expressed simultaneously; one enum per operation
  cannot express the *policy*-level fact at all, forcing a second, ad hoc field back in anyway --
  at which point Design C has reinvented Design B's two fields under a worse name.
- *API simplicity*: appears simpler (one field) but is not, once the missing policy-level
  information is added back.
- Every other criterion is dominated by Design B once the above is accounted for. **Rejected** --
  presented to show it was considered, not adopted as a compromise.

**Recommendation: Design B.**

## 6. Recommended Result Contract v1

```python
class ExecutionStatus(str, enum.Enum):
    COMPLETED = "completed"            # the operation ran to completion (regardless of `satisfied`)
    FAILED = "failed"                  # raised an expected policy-execution failure, no rollback applicable (e.g. VR required on the first site)
    ROLLED_BACK = "rolled_back"        # raised mid-batch; every already-applied site in THIS operation was restored exactly
    NOT_EXECUTED = "not_executed"      # never ran, because an earlier operation in the same Policy rejected or failed

@dataclass(frozen=True)
class OperationResult:
    kind: str
    tag: Optional[Tag]
    execution: ExecutionStatus
    satisfied: Optional[bool]          # None when the operation kind has no condition/guarantee
    count: int                         # unchanged meaning: total elements changed (updated+inserted, or removed/pruned)
    updated_count: Optional[int] = None    # Ensure/EnsureText only; None for every other kind
    inserted_count: Optional[int] = None   # Ensure/EnsureText only; None for every other kind
    diagnostics: tuple["Diagnostic", ...] = ()   # 0..1 in practice today; never assumed to stay at most 1

class PolicyExecutionStatus(str, enum.Enum):
    COMPLETED = "completed"    # every operation ran; decision reflects the outcome
    REJECTED = "rejected"      # stopped early: an unsatisfied Require
    PARTIAL = "partial"        # stopped early: a caught operation failure (section 10)

@dataclass(frozen=True)
class PolicyResult:
    decision: Decision                     # unchanged (ACCEPT/TRANSFORM/REJECT) -- kept for the existing simple callers
    execution: PolicyExecutionStatus       # new, authoritative status
    operations: tuple[OperationResult, ...]
    diagnostics: tuple["Diagnostic", ...]  # unchanged shape; now an aggregate view, per-operation is primary (see section 7)
    policy_name: str
    policy_version: str
    # elements_touched / failed_requirement: unchanged properties, still computable from `operations`
```

**`satisfied`'s meaning, precisely defined**: `Optional[bool]`, populated *only* for operations
that have a condition or guarantee to evaluate (`Require`: does the dataset already meet the
condition; `Ensure`/`EnsureText`: could the guarantee be established anywhere the locator names).
`None` for `Remove`/`Replace`/`ReplaceText`/`AllowListPrune`/`PrivateTagPolicy` -- they have no
condition, so the field is absent (not `True`-by-convention, which is what invites the current
conflation). **`satisfied` never means "the operation executed without error"** -- that is
`execution`'s job, exclusively.

**`count`'s meaning, precisely defined**: total elements changed (updated + inserted for `Ensure`/
`EnsureText`; removed for `Remove`/`AllowListPrune`/`PrivateTagPolicy`; replaced for `Replace`/
`ReplaceText`), preserving `elements_touched`'s existing sum-of-`count` computation unchanged.
`updated_count`/`inserted_count` are `Ensure`/`EnsureText`-only refinements, `None` elsewhere --
not a generalized five-count model (section 4's over-modeling rejection).

## 7. Recommended Diagnostic Contract v1

```python
@dataclass(frozen=True)
class Diagnostic:
    code: str                  # stable, closed vocabulary -- section 8
    severity: str               # "error" | "warning" -- kept as str, matching S1.1's own stated
                                 # reason (room to grow without a breaking change), not newly invented
    operation_kind: str          # e.g. "ensure_text" -- mirrors OperationResult.kind
    operation_index: int         # zero-based position in Policy.operations -- section 18
    locator: str                 # repr(the operation's own Locator) -- Structure-owned, e.g.
                                  # "PathLocator((300A,00B0)[*]/(0008,0090))" -- never attrs' raw
                                  # ElementPath tuples
    site: Optional[str] = None   # for a wildcard operation, a Structure-owned rendering of the one
                                  # concrete site that failed (e.g. "(300A,00B0)[2]/(0008,0090)"),
                                  # built the same way -- None when the failure isn't site-specific
                                  # (e.g. a Require evaluated as a whole)
    message: str = ""            # a short, curated, code-specific human sentence -- never
                                  # str(exception) or exception.args verbatim (section 15)
    cause_type: Optional[str] = None   # the underlying exception's CLASS NAME only (e.g.
                                        # "VRRequiredError") -- never the exception object or its
                                        # message
```

Every field is justified against section 2/3's evidence, none added for completeness alone:
`code`/`severity`/`message` answer "why" (dimension E); `operation_kind`/`operation_index` answer
"which operation" (section 18, needed the moment a `Policy` has more than one operation of the
same kind -- already true of every multi-operation example in section 2); `locator`/`site` answer
"where," Structure-owned (section 11); `cause_type` gives a programmatic caller a stable
discriminator without exposing exception text.

## 8. Stable diagnostic-code vocabulary

Derived strictly from section 2's matrix -- no code invented without a traced frozen-behavior
trigger, no two materially different conditions collapsed merely to shrink the list:

| Code | Meaning | Triggering behavior | Fatal to operation? | Fatal to Policy? | Structure may have changed? | Rollback applies? |
|---|---|---|---|---|---|---|
| `REQUIREMENT_UNSATISFIED` | A `Require`'s condition does not hold | `Require`, zero matches | No (this *is* the completed, correct outcome) | Yes -- `Policy` -> `REJECTED` | No (`Require` never mutates) | n/a |
| `GUARANTEE_UNESTABLISHED` | An `Ensure`/`EnsureText` found no concrete insertion site anywhere the locator names | `_resolve_insertion_sites` returns `[]` | No (completed; nothing to guarantee against) | No (does not stop the `Policy` -- see section 9's rationale) | No | n/a |
| `VR_REQUIRED` | An insertion site's VR could not be inferred and none was given | attrs `VRRequiredError` | Yes | Yes -- `Policy` -> `PARTIAL` | No (rolled back if any earlier site in the same operation succeeded) | Yes |
| `TEXT_OPERATION_UNSUPPORTED` | The target/site's actual VR is not text-governed, or the effective charset declaration is unsupported/malformed | attrs generic `FdsError` mapped from `NotATextVR`/`UnsupportedCharset`/`MalformedCharsetDeclaration` -- **collapsed deliberately; see the precision limit below** | Yes | Yes | No (rolled back) | Yes |
| `INVALID_UNICODE` | The Python `str` supplied was not well-formed Unicode at the point attrs validates it | `InvalidUnicodeInputError` | Yes | Yes | No (rolled back) | Yes |
| `CHARACTER_UNREPRESENTABLE` | The requested text contains a character the effective charset context cannot encode | `UnrepresentableCharacterError` | Yes | Yes | No (rolled back) | Yes |
| `ALREADY_EXISTS` | An insertion site's tag already existed in that container at mutation time | attrs `AlreadyExistsError` -- not reachable via any current test (`_resolve_insertion_sites`'s own `exists` check should always agree), kept for defensive completeness, not a claimed-common case | Yes | Yes | No (rolled back) | Yes |
| `MUTATION_FAILED` | A raw structural mutation attrs itself reports failed (e.g. `set_value` returning `False` for a too-long value) | the internal `_MutationFailed` marker | Yes | Yes | No (rolled back) | Yes |
| `CALLBACK_FAILED` | A caller-supplied `Replace`/`ReplaceText` callback raised | any exception from `value(...)`/`values(...)`, wrapped (section 6) | Yes | Yes | **Currently differs by operation -- `Replace`: yes, partially, per Finding 3; `ReplaceText`: no, rolled back.** Recorded honestly, not smoothed over; see section 28. | `ReplaceText`: yes. `Replace`: not currently, a named risk. |
| `ROLLBACK_FAILED` | An atomic operation's own rollback could not fully restore every already-applied site | `RollbackError` -- **not caught by `Policy.apply()`, propagates raw** (section 6/10) | Yes | Yes (by propagating, not by conversion) | **Yes, possibly, for the specific paths named in `RollbackError.failed_undo_actions`** | Attempted; this code exists for when it did not fully succeed |

**A precision limit, stated plainly rather than hidden**: `TEXT_OPERATION_UNSUPPORTED` collapses
three distinct C++-level conditions (`NotATextVR`, `UnsupportedCharset`, `MalformedCharsetDeclaration`)
because all three map to the identical ABI status (`FDS_STATUS_UNSUPPORTED`, verified directly from
`abi/src/*.cpp`'s status table) and therefore the identical Python exception (`FdsError`, no
subclass) -- there is no reliable, non-message-parsing way to distinguish them from Python today.
This is a genuine attrs Python-binding precision limit, not an S1.3 design shortcut; recorded as a
candidate attrs improvement (section 25/28), not attempted here.

**`LOCATOR_INVALID`, deliberately absent from this table.** A malformed locator raises
`MalformedLocatorError` at *operation construction*, before a `Policy` exists at all (section 2) --
it can never reach `Policy.apply()`'s exception boundary and therefore never becomes a `Diagnostic`
in practice. A stable code name is still worth reserving (`LOCATOR_INVALID`) purely so a future
JSON loader (S1.4) can report *its own* construction-time rejection using the same vocabulary --
but S1.3 itself never constructs a `Diagnostic` with this code, and implementing that reservation
is nothing more than writing the string down here.

## 9. Exception boundary

Evaluated against the authorization's four options plus the evidence in section 2:

**Option A** (all expected failures become results, exceptions reserved for programmer errors) is
closest to correct but too absolute -- `RollbackError` (section 10) is not a "programmer error" in
the usual sense, yet treating it as an ordinary convertible result would hide that the atomicity
guarantee itself broke.

**Option B** (operations keep raising; `Policy.apply()` converts) is the mechanism, but naive
"catch everything" is wrong (Design A's rejection, section 5).

**Option C** (both levels return structured results) is not adopted at the *operation* level:
`Ensure.apply()`/`ReplaceText.apply()`/etc. keep raising exactly as S1.2 built them (unchanged
public behavior for a caller using operations directly, outside a `Policy`) -- only
`Policy.apply()` gains the conversion boundary. Changing every operation's own direct-call contract
would be a real, avoidable break (section 20) for no evidence-backed gain.

**Recommendation -- a refined Option B**: `Policy.apply()` catches a **named, closed, explicit** set
of exception types -- `VRRequiredError`, `AlreadyExistsError`, `UnrepresentableCharacterError`,
`InvalidUnicodeInputError`, the plain `FdsError` base (covering `NotATextVR`/`UnsupportedCharset`/
`MalformedCharsetDeclaration`), the internal `_MutationFailed` marker, and a **new**, narrow
`CallbackError` wrapper (below) -- converting each into a `FAILED`/`ROLLED_BACK` `OperationResult` +
`Diagnostic` with the matching code from section 8, then marking every remaining operation
`NOT_EXECUTED` and returning a `PolicyResult` with `execution=PARTIAL`. **Never** a blanket
`except Exception`. Two types are deliberately left **uncaught**, propagating raw:

- **`RollbackError`**: analyzed explicitly per instruction. Rollback failure means the one
  guarantee this whole design leans on (attrs' per-call atomicity making rollback provably safe) did
  not hold, for reasons outside this module's control. A caller receiving a routine-looking
  `PolicyResult(execution=PARTIAL, ...)` here would be actively misled into thinking the dataset is
  in a known, safe state when it may not be. `RollbackError` should interrupt the caller, not be
  smoothed into the same bucket as an ordinary, fully-recovered mutation failure.
- **Any exception not in the named set** (a genuine bug in `policy.py` itself, or a future attrs
  exception type this checkpoint didn't anticipate): propagates raw, deliberately, so it is never
  silently absorbed into a diagnostic that makes an unanticipated failure look like a modeled,
  understood one.

**Malformed locator, analyzed explicitly per instruction**: correctly a construction-time/
configuration error (an operation object could not even be built), not a `Policy.apply()`-time
outcome at all -- already fully handled by S1.1/S1.2's existing design (raises immediately at
`Require(...)`/`Ensure(...)`/etc. construction, before any `Policy` exists to catch it). No change
needed or possible here; a caller authoring a `Policy` programmatically already gets an immediate,
un-smoothed `MalformedLocatorError` at the point they made the mistake, which is the right place
for a configuration error to surface.

**Callback exceptions, analyzed explicitly per instruction**: a caller's own code failing is a
different kind of fact than a DICOM semantic failure, and today's raw propagation (section 2) gives
`Policy.apply()` no reliable way to recognize "this specific exception came from a callback" versus
an unanticipated bug, since a callback can raise *anything*. **New, minimal, S1.3-scoped addition**:
`_apply_sites_atomically`'s `do_update` closures (for `ReplaceText`) wrap a callback's own raised
exception in `CallbackError(original)` before letting it propagate to the atomic engine's
`except Exception` -- `original.__class__.__name__` becomes the `Diagnostic`'s `cause_type`; the
original exception's *message* is never copied into `message` (section 15). This is new code, not
merely new documentation -- it is the one piece of section 8's `CALLBACK_FAILED` row that does not
already exist in frozen S1.2, and is small and bounded (one wrapper class, one `try/except` in one
already-existing closure).

## 10. Require semantics

Confirmed: `Require`'s unsatisfied state is **already correctly modeled as a completed evaluation,
not a failure** in frozen code -- `apply()`'s `Require`-rejection branch does not raise, does not
skip building a `PolicyResult`, and does produce (the one existing) `Diagnostic`. The Result
Contract v1 preserves this shape exactly, generalizing its *name* rather than its behavior:
`Require` unsatisfied -> `OperationResult(execution=ExecutionStatus.COMPLETED, satisfied=False, ...)`
+ a `Diagnostic(code="REQUIREMENT_UNSATISFIED", ...)`; the containing `PolicyResult` gets
`execution=PolicyExecutionStatus.REJECTED` (a renamed, more precise version of what `Decision.REJECT`
already meant) and every later operation is recorded `NOT_EXECUTED`. **An unsatisfied `Require` must
never be classified `FAILED`** -- it is the policy engine working exactly as designed, and section
8's table records this explicitly (`REQUIREMENT_UNSATISFIED`: "Fatal to operation? No").

## 11. Zero-match/zero-site semantics

The three-way distinction the authorization names is fully expressible via the (`execution`,
`satisfied`, `count`) triple with **zero special-case interpretation required by callers** --
exactly the goal:

| Operation | `execution` | `satisfied` | `count` |
|---|---|---|---|
| `Remove`/`Replace`/`ReplaceText`/`AllowListPrune`/`PrivateTagPolicy`, zero matches | `COMPLETED` | `None` (no condition) | `0` |
| `Require`, zero matches | `COMPLETED` | `False` | `0` |
| `Ensure`/`EnsureText`, zero insertion sites | `COMPLETED` | `False` | `0` |

A caller distinguishes all three by reading `kind` (already present) plus `satisfied`'s new,
precisely-scoped meaning -- no per-caller special-case logic, no new field needed beyond what
section 6 already proposes. `Require` and `Ensure`/`EnsureText` share an identical *shape* here
deliberately (both are "condition-bearing" operations, section 4's dimension A) while differing in
`kind` and, when a `Diagnostic` is produced, `code`.

## 12. Policy-level execution semantics

Verified (section 2, Finding 1) that frozen code has **no** policy-level partial-execution
semantics today -- an operation exception simply destroys the whole `PolicyResult`. The authorized
default expectation ("operation atomicity: YES; whole-policy atomicity: NO") is **confirmed** as the
right target, but is **not yet actually implemented as a visible, structured semantic** -- today it
is implemented only as an accidental *consequence* of exceptions propagating raw (the caller can, in
principle, inspect the mutated `Structure` after catching the exception themselves, but gets no
`PolicyResult` telling them so).

**Recommendation**: implement the three-way distinction explicitly via
`PolicyExecutionStatus`: `REJECTED` (stopped due to `Require`), `PARTIAL` (stopped due to a caught
operation failure, section 9), `COMPLETED` (every operation ran, whether or not any individual one
reported `satisfied=False` -- `Ensure`'s dissatisfaction alone does not halt the `Policy`, per
section 8's `GUARANTEE_UNESTABLISHED` row, "Fatal to Policy? No" -- unlike `Require`). Every
operation *after* the one that triggered `REJECTED`/`PARTIAL` gets an `OperationResult` with
`execution=NOT_EXECUTED` (a lightweight placeholder result, not simply absent from the list) so
`len(PolicyResult.operations) == len(Policy.operations)` always holds, regardless of where execution
stopped -- directly enabling Part 22's example 11 (`op1` committed, `op2` failed+rolled back, `op3`
`NOT_EXECUTED`, all three visible in one `PolicyResult`).

## 13. Operation-level rollback semantics

Both the normal and exceptional cases (section 10's own Part 10 numbering) are addressed:

1. **A successfully-rolled-back operation returns a structured `FAILED`/`ROLLED_BACK` result within
   the containing `Policy`'s `PolicyResult`** (via section 9's boundary) -- it does not continue
   raising *out of* `Policy.apply()`. (Calling the operation directly, outside a `Policy`, is
   unchanged -- it still raises, exactly as S1.2 built it; only `Policy.apply()` gains the
   conversion.)
2. **`execution=ROLLED_BACK` is sufficient**; a separate `rollback_attempted`/`rollback_succeeded`
   boolean pair is not needed in addition -- `ROLLED_BACK` already means "rollback was attempted and
   fully succeeded" by construction (if rollback had *not* fully succeeded, the outcome is
   `RollbackError`, section below, not a `ROLLED_BACK` result at all). Adding both an enum value and
   redundant booleans would be over-modeling the same fact twice.
3. **`RollbackError` should remain an exception**, confirmed (section 9) -- dataset state is
   genuinely uncertain when it fires, and an uncertain-state signal belongs in the "stop everything"
   category, not the "here is a clean, understood outcome" category a `PolicyResult` represents.
4. **How a future execution adapter (S1.5) knows what to do, without parsing exception text**:
   - `PolicyResult` returned normally, `execution=COMPLETED` or `REJECTED` -> dataset is in a fully
     known, intentional state; safe to route on `decision` as today.
   - `PolicyResult` returned, `execution=PARTIAL` -> some earlier operations' effects are
     genuinely committed (operation atomicity held for each), but the *policy's* own intended
     end-state was not reached -- an adapter should treat this as "needs review/quarantine," not
     "safe to emit," per section 13/17's own later analysis.
   - `RollbackError` raised (no `PolicyResult` at all) -> the *specific paths* named in
     `failed_undo_actions` may be in an inconsistent state; an adapter must stop and cannot safely
     infer anything further from `policy.py` alone -- this is intentionally the one case this module
     does not attempt to characterize further, since attrs' own atomicity contract is what broke.

## 14. Locator/path representation

Every `Locator` subtype (`TagLocator`, `PathLocator`, `LocatorStep`) already has a Structure-owned,
attrs-independent `__repr__` (verified: `_format_tag`-based hex tag rendering, e.g.
`"PathLocator((300A,00B0)[*]/(0008,0090))"`) -- **this is reused directly**, as a plain `str`, for
`Diagnostic.locator`; no new type is introduced. For a wildcard operation's *one specific failing
site* (`Diagnostic.site`), a small new helper renders an already-resolved `ElementPath` (attrs'
internal list-of-`(tag, item_index)` tuples) into the same human string shape -- e.g.
`"(300A,00B0)[2]/(0008,0090)"` -- **the raw tuple list itself is never placed in `Diagnostic`**, only
this rendered string. JSON-authorability is immediate: both fields are already plain strings.

## 15. Privacy/PHI rules

**Confirmed, not merely accepted**: `Diagnostic` as designed (section 7) never carries an element's
raw or decoded value, a callback's input or output, or an exception's full message/repr by default
-- only `tag` (via `locator`/`site`), `operation_kind`, `code`, a curated `message` template, and
`cause_type` (a class name, never exception content). This was verified against every failure row in
section 2's matrix: none of the proposed fields require copying a value to be useful (a caller
already knows the *policy* they authored; the diagnostic only needs to say which part of it
produced which named condition, at which named location). **Rule, stated explicitly for the
contract**: diagnostics describe structure/action/failure category, never patient data content --
confirmed correct, not challenged, by this analysis.

## 16. Callback failure semantics

Three distinguishable cases, evaluated against actual verified behavior (section 2):

1. **Callback raises an exception** -- verified: propagates with the exception's own real type/
   message today, for both `Replace` and `ReplaceText`, with the atomicity difference noted in
   Finding 3. Classified `CALLBACK_FAILED` (section 8), wrapped in the new `CallbackError` (section
   9) so `Policy.apply()` can recognize it reliably; `cause_type` records the *original* exception's
   class name, not `CallbackError`'s own.
2. **Callback returns a value of the wrong type** (e.g. `str` where `bytes` is required) --
   verified: currently surfaces as a raw ctypes `TypeError` ("a bytes-like object is required, not
   'str'") with no Structure-level involvement at all. This is functionally a sub-case of (1) from
   `Policy.apply()`'s perspective (it is still an exception raised while attempting to apply the
   callback's result) but arguably deserves its own code
   (`CALLBACK_INVALID_RETURN` -- not separately tabled in section 8, since S1.3 does not mandate
   distinguishing it from `CALLBACK_FAILED`, but the option is recorded here since the underlying
   `TypeError` is currently an uncontrolled leak of a ctypes-layer message that a stricter
   implementation could catch and re-message before it ever reaches a caller).
3. **attrs rejects the callback's (correctly-typed) returned value** (e.g. representable-but-
   too-long bytes, or unrepresentable text) -- this is **not** a callback failure at all; it is an
   ordinary attrs mutation/charset failure (sections 8's `MUTATION_FAILED`/
   `CHARACTER_UNREPRESENTABLE` rows) that happens to have been reached via a callback's output. No
   separate code needed -- the *cause* here is the value, not the callback.

**Recommendation**: the result model needs to distinguish (1)/(2) from (3), which it already does
via `CALLBACK_FAILED` vs. the ordinary attrs-failure codes -- no further splitting is required by
current evidence.

## 17. Configuration-vs-dataset failure classification

Assessed against section 8's full code list, not invented as decoration:

| Code | Classification |
|---|---|
| `REQUIREMENT_UNSATISFIED` | dataset-specific execution condition (the *data* doesn't meet the policy, not a config error) |
| `GUARANTEE_UNESTABLISHED` | dataset-specific execution condition |
| `VR_REQUIRED` | **ambiguous by nature, and this matters**: it is a dataset condition (this tag really is ambiguous/unknown) *and* a configuration gap (the policy author should have supplied an explicit VR) simultaneously -- classified here as dataset-specific, since it is the *data's* tag that triggered it, but documented as the clearest example of why a rigid two-bucket taxonomy would mislead; a caller authoring policy should read this as "fix your policy for this tag," even though the underlying trigger is inspected per-dataset |
| `TEXT_OPERATION_UNSUPPORTED` | dataset-specific execution condition |
| `INVALID_UNICODE` | configuration/policy error (the literal string the policy author supplied is malformed) |
| `CHARACTER_UNREPRESENTABLE` | dataset-specific execution condition (the *target's* charset context can't represent the requested text) |
| `ALREADY_EXISTS` | dataset-specific (a genuinely surprising state of the input) |
| `MUTATION_FAILED` | dataset-specific (a real value-shape limit hit against real data) |
| `CALLBACK_FAILED` | configuration/policy error -- the caller's own code, not the dataset |
| `ROLLBACK_FAILED` | internal/system failure -- neither the data nor the policy caused this; the execution environment or an unanticipated interaction did |
| `LOCATOR_INVALID` (reserved, section 8) | configuration/policy error |

**Does this materially help future execution decisions? Yes, but only loosely, not as a rigid
gate**: `VR_REQUIRED`'s genuine ambiguity (above) shows the taxonomy is a *hint* for humans/adapters
triaging results, not a strict routing switch a machine should branch on blindly. **Recommendation**:
record the classification as documentation/guidance attached to each code (as the table above does),
not as a fourth structured field on `Diagnostic` itself -- adding a `category` enum field would
imply a precision the `VR_REQUIRED` case shows doesn't really exist, and no evidence from section 2
shows a caller currently needs to branch on it programmatically rather than read it.

## 18. Operation identity

**Recommendation: `operation_index` only, now; an optional user-facing name/id deferred to S1.4.**
`operation_index` (zero-based position in `Policy.operations`) is: already fully known without any
user input (the `Policy` object already has this as list position); cheap (an `int`, computed at
`apply()` time, not stored on the operation); immediately disambiguates "which of four
`ReplaceText`s failed" (the authorization's own motivating example) without inventing user-facing
naming conventions this checkpoint has no evidence anyone needs yet. An optional `name: Optional[str]
= None` field is **not** added to `PolicyOperation` now -- S1.4's JSON authors will most likely want
to name operations in their own configuration language directly, and adding an unused Python-only
`name` field now risks guessing wrong about its shape (a bare string? a dotted path? unique within
a `Policy`?) before there's a real consumer. `operation_index` alone is forward-compatible: S1.4 can
add `name` as a fully independent, additive `Optional[str]` field to both `PolicyOperation` and
`Diagnostic` later without touching `operation_index` at all.

## 19. Policy identity

`Policy.name`/`Policy.version` (already frozen, S1.1) are sufficient and are carried unchanged into
`PolicyResult.policy_name`/`policy_version` -- no new identifier is introduced. Deployment/run
identifiers (a specific *execution* of a policy against a specific dataset, as opposed to the policy
definition itself) are correctly out of scope, per instruction, and belong to a future execution
adapter (S1.5), which already has the raw material (`policy_name`+`policy_version`+a timestamp/run
ID it generates itself) to construct its own broader identity without any `policy.py` change.

## 20. Compatibility impact

Every existing accessor, inventoried directly from `tests/python/test_policy.py`,
`test_locator.py`, `test_ensure_and_text.py`, and `policy.py` itself:

- `OperationResult.kind`, `.tag`, `.count`, `.satisfied` -- all four **retained unchanged in name and
  type** (`satisfied` becomes `Optional[bool]` rather than `bool`, but every existing call site reads
  it only where it was already meaningful -- `Require`'s own tests -- so `True`/`False` comparisons
  in existing tests keep working; no existing test reads `satisfied` on an operation kind where the
  new model would return `None`).
- `PolicyResult.decision`, `.operations`, `.diagnostics`, `.policy_name`, `.policy_version`,
  `.elements_touched`, `.failed_requirement` -- all **retained unchanged**; `elements_touched`'s
  `sum(r.count for r in operations if r.kind != "require")` computation is unaffected by adding new
  fields alongside `count`.

**Verdict: the recommended model is introducible additively, with zero compatibility breakage**,
confirmed by inventory, not merely asserted. The one *behavioral* (not structural) change existing
callers could observe is Design B's exception-boundary change itself (section 9): a `Policy`
containing an operation that used to make `apply()` raise will now, for the named exception set,
return a `PolicyResult(execution=PARTIAL, ...)` instead. No existing test currently exercises this
path (verified, section 2's Finding 1 -- this scenario was previously untested), so no existing test
breaks, but any *future* caller-written code relying on `apply()` raising for these specific
cases would need to switch to checking `result.execution` -- a real, disclosed, one-directional
behavior change, not a silent one.

## 21. Result-model design options

See section 5 (three candidate designs, assessed and Design B recommended) -- presented there rather
than duplicated here, per the natural ordering of evidence -> conflations -> dimensions -> designs.

## 22. Representative examples (recommended model)

```python
# 1. Require satisfied
OperationResult(kind="require", tag=(0x0010,0x0020), execution=ExecutionStatus.COMPLETED,
                satisfied=True, count=1)

# 2. Require unsatisfied
OperationResult(kind="require", tag=(0x0010,0x0020), execution=ExecutionStatus.COMPLETED,
                satisfied=False, count=0,
                diagnostics=(Diagnostic(code="REQUIREMENT_UNSATISFIED", severity="error",
                                        operation_kind="require", operation_index=0,
                                        locator="TagLocator((0010,0020), scope=root)",
                                        message="required tag (0010,0020) is absent"),))
# containing PolicyResult: decision=REJECT, execution=REJECTED

# 3. Remove, zero matches
OperationResult(kind="remove", tag=(0x0009,0x0099), execution=ExecutionStatus.COMPLETED,
                satisfied=None, count=0)

# 4. Replace, three matches changed
OperationResult(kind="replace", tag=(0x0010,0x0010), execution=ExecutionStatus.COMPLETED,
                satisfied=None, count=3)

# 5. Ensure, root insertion
OperationResult(kind="ensure", tag=(0x0012,0x0062), execution=ExecutionStatus.COMPLETED,
                satisfied=True, count=1, updated_count=0, inserted_count=1)

# 6. Ensure, nested locator with no valid parent
OperationResult(kind="ensure", tag=(0x0001,0x0001), execution=ExecutionStatus.COMPLETED,
                satisfied=False, count=0, updated_count=0, inserted_count=0,
                diagnostics=(Diagnostic(code="GUARANTEE_UNESTABLISHED", severity="error",
                                        operation_kind="ensure", operation_index=1,
                                        locator="PathLocator((0099,0099)[0]/(0001,0001))",
                                        message="no concrete insertion site could be "
                                                "established for this locator"),))

# 7. ReplaceText fails on second wildcard site, rolls back
OperationResult(kind="replace_text", tag=(0x300A,0x00C2), execution=ExecutionStatus.ROLLED_BACK,
                satisfied=None, count=0,
                diagnostics=(Diagnostic(code="CHARACTER_UNREPRESENTABLE", severity="error",
                                        operation_kind="replace_text", operation_index=2,
                                        locator="PathLocator((300A,00B0)[*]/(300A,00C2))",
                                        site="(300A,00B0)[1]/(300A,00C2)",
                                        message="requested text is not representable under "
                                                "this site's effective character set",
                                        cause_type="UnrepresentableCharacterError"),))

# 8. Ensure fails because VR is required
OperationResult(kind="ensure", tag=(0x0028,0x0106), execution=ExecutionStatus.FAILED,
                satisfied=None, count=0,
                diagnostics=(Diagnostic(code="VR_REQUIRED", severity="error",
                                        operation_kind="ensure", operation_index=0,
                                        locator="TagLocator((0028,0106), scope=root)",
                                        message="VR could not be inferred for this tag; an "
                                                "explicit vr= is required",
                                        cause_type="VRRequiredError"),))

# 9. Callback raises
OperationResult(kind="replace_text", tag=(0x0010,0x0010), execution=ExecutionStatus.ROLLED_BACK,
                satisfied=None, count=0,
                diagnostics=(Diagnostic(code="CALLBACK_FAILED", severity="error",
                                        operation_kind="replace_text", operation_index=0,
                                        locator="TagLocator((0010,0010), scope=root)",
                                        message="the caller-supplied callback raised an "
                                                "exception",
                                        cause_type="ValueError"),))

# 10. Rollback itself fails -- NOT a PolicyResult; RollbackError propagates raw:
# RollbackError(forward_error=UnrepresentableCharacterError(...),
#               failed_undo_actions=(("restore_raw", [((0x300A,0x00B0), 0), ((0x300A,0x00C2), None)]),))

# 11. Three-operation Policy: op1 succeeds, op2 fails+rolls back, op3 not executed
PolicyResult(
    decision=Decision.TRANSFORM,           # reflects op1's real, committed effect
    execution=PolicyExecutionStatus.PARTIAL,
    operations=(
        OperationResult(kind="ensure", tag=..., execution=ExecutionStatus.COMPLETED,
                         satisfied=True, count=1, updated_count=0, inserted_count=1),
        OperationResult(kind="ensure", tag=..., execution=ExecutionStatus.FAILED,
                         satisfied=None, count=0,
                         diagnostics=(Diagnostic(code="VR_REQUIRED", operation_index=1, ...),)),
        OperationResult(kind="remove", tag=..., execution=ExecutionStatus.NOT_EXECUTED,
                         satisfied=None, count=0),
    ),
    diagnostics=(Diagnostic(code="VR_REQUIRED", operation_index=1, ...),),  # aggregate view
    policy_name="...", policy_version="...",
)
```

Example 11 makes the model's core claim concrete: op1's real committed effect, op2's specific
failure and rollback, and op3's non-execution are all simultaneously visible in one returned value,
with no exception to catch and no `Structure` re-inspection needed.

## 23. Implementation boundary (not executed here)

| Item | Classification |
|---|---|
| `OperationResult` | **extend** (additive fields, section 6) |
| `PolicyResult` | **extend** (additive field, section 6) |
| `Diagnostic` | **replace** (S1.1's two-field shape is insufficient for section 7's requirements; the *name* and its role are retained, its shape is not) |
| `Policy`, `PolicyOperation` | **retain** unchanged |
| `apply()` | **extend** (the exception-catching boundary, section 9, is new logic inside the existing function -- not a rewrite of its operation-iteration structure) |
| `Require`/`Remove`/`Replace`/`AllowListPrune`/`PrivateTagPolicy` | **retain** unchanged (they already produce correctly-shaped outcomes; only the *container* they're read through changes) |
| `Ensure`/`EnsureText`'s own `apply()` | **extend** minimally (populate `updated_count`/`inserted_count`, which `_apply_sites_atomically` can already compute internally but currently discards) |
| `ReplaceText`'s `do_update` closure | **extend** (wrap callback exceptions in `CallbackError`, section 9) |
| `_apply_sites_atomically` | **extend** (surface which specific site failed, for `Diagnostic.site`, section 14) -- not a redesign of its rollback logic (sections 12/13's mechanism is unchanged) |
| `RollbackError` | **retain** unchanged (still raised, still uncaught by `Policy.apply()`) |
| Tests | **extend** (new coverage per section 24); zero existing tests require modification (section 20) |
| Documentation | **extend** (module docstring, this checkpoint's own eventual freeze report) |
| **attrs** | **no change required or recommended** -- confirmed against every design decision above; the one place attrs' own precision limits this checkpoint (`TEXT_OPERATION_UNSUPPORTED`'s three-way collapse, section 8) is absorbed by a coarser code, not by requesting an attrs change |

## 24. Test / qualification plan

Freeze criteria for the eventual S1.3 implementation, derived from this checkpoint's own findings
(not generic best practice filler):

- All 105 S1.2 tests remain green, unmodified (compatibility, section 20).
- Every operation's zero-match/zero-site behavior matches section 11's table exactly, one test per
  row.
- `Require` unsatisfied produces `execution=COMPLETED, satisfied=False` -- explicitly asserted
  *not* `FAILED` (section 10).
- A successful no-op (`count=0, satisfied=None`) is asserted distinguishable, by field inspection
  alone, from a `FAILED` outcome for the same operation kind under a forced failure.
- A `VR_REQUIRED`/`CHARACTER_UNREPRESENTABLE`/`INVALID_UNICODE`/`MUTATION_FAILED` failure is asserted
  distinguishable from `Require`'s `REQUIREMENT_UNSATISFIED` by both `code` and by `execution`
  (`FAILED`/`ROLLED_BACK` vs. `COMPLETED`).
- A `ROLLED_BACK` outcome is asserted distinguishable from a `RollbackError`-propagating case by
  triggering both deliberately (mirroring S1.2's own two rollback tests) and confirming one produces
  a `PolicyResult` while the other raises.
- A three-operation `Policy` (op1 succeeds, op2 fails+rolls back, op3 never runs) asserts all three
  operations' `OperationResult`s are present in `PolicyResult.operations`, with `execution` values
  `COMPLETED`/`ROLLED_BACK`/`NOT_EXECUTED` respectively (directly qualifying example 11).
- Every code in section 8's table has at least one dedicated test triggering it via real frozen
  behavior (not a mock), mirroring S1.2's own precedent of using real dictionary/charset tags.
- A test asserts `Diagnostic.message` is a fixed, code-specific string that does **not** vary with
  (and does not embed) the underlying exception's own message text -- proving diagnostics don't
  depend on exception message content, per the authorization's explicit requirement.
- A test asserts no `Diagnostic` produced by any test in the suite contains a decoded/raw element
  value or callback input/output -- a direct, mechanical privacy-rule check (e.g. asserting a known
  sensitive literal used in the test fixture never appears in any `Diagnostic` field's string
  representation).
- Malformed-locator/configuration-failure behavior is proven unchanged (still raises at
  construction, never produces a `Diagnostic`).
- A callback failure test proves both `Replace` and `ReplaceText`'s *current* (possibly still
  asymmetric, per Finding 3 -- see section 28) behavior explicitly, rather than assuming symmetry.
- `VRRequired`/`TEXT_OPERATION_UNSUPPORTED`/`INVALID_UNICODE`/`CHARACTER_UNREPRESENTABLE`/
  `MUTATION_FAILED`/`ROLLBACK_FAILED` are each proven via at least one real triggering test (not all
  novel -- several already exist in `test_ensure_and_text.py` and only need their assertions
  extended to check the new `Diagnostic`/`execution` fields, not rewritten).
- JSON-authorability is re-demonstrated (design-proof only) for the final `Diagnostic`/
  `OperationResult`/`PolicyResult` shapes, mirroring S1.1/S1.2's own probes.
- Deterministic result ordering: `PolicyResult.operations` always has exactly
  `len(Policy.operations)` entries, in the same order, regardless of where execution stopped.
- Explicit/Implicit source encoding does not alter which diagnostic *code* an equivalent semantic
  failure produces (mirroring S1.1/S1.2's own encoding-independence tests, extended to the failure
  path specifically -- not previously tested at the diagnostic level).
- **The specific differential test the authorization requires**: construct one scenario the current
  (S1.2) model conflates -- recommended: Finding 2's own scenario (an `Ensure` with zero insertion
  sites, in a `Policy` that also does something else) -- and prove the new model reports it via a
  populated `Diagnostic`/`execution` combination that the old model's `decision`/`diagnostics` pair
  could not distinguish from "nothing happened, everything fine" (reproducing section 2's Finding 2
  measurement, then showing the new model resolves it).

## 25. Product Capability Map implications (assessed, not promoted preemptively)

**P1.5 (Audit/results/errors)**: the V1 definition this checkpoint infers from the Product
Capability Map's own existing row (a broader diagnostic model mapping attrs' typed exceptions and
locator-shape detail into results) is **substantively met by the recommended design**, assuming it
is actually implemented and qualified per section 24 -- at that point, `PARTIAL -> CURRENT` would be
evidence-based, not premature. **This checkpoint does not promote it now** (no implementation has
happened); the promotion is conditional on section 24's criteria being met, exactly as S1.1/S1.2's
own capability-map updates were.

**P7.1 (Structured exception reporting)**, present in the map (`PARTIAL`, evidence:
`MalformedLocatorError` distinguishing malformed-vs-zero-match): the recommended design's
`Diagnostic`/`code` vocabulary is a real, substantial advance on this same axis (attrs' typed
mutation exceptions now map to a modeled outcome, exactly the gap P7.1's own row names as
outstanding) -- **also conditionally promotable to `CURRENT` once implemented**, not now.

**Not promoted, per instruction, regardless of S1.3's outcome**: P2 (JSON configuration), P5
(deployment/execution adapters), P1.6 (bulk-data policy), P7.3 (Evidence Packet integration) --
S1.3 makes results *representable* in a way that would later serve all of these, per sections 12-14,
but building none of them is this checkpoint's explicit boundary.

## 26. Falsifiable S1.3 claim

The authorization's candidate claim is refined, not rejected outright -- it is directionally right
but too broad to test as written ("deterministically distinguish... without exposing... details or
sensitive values" bundles several independently-falsifiable sub-claims into one sentence).
**Recommended, narrower, testable form**:

> For every currently-reachable policy execution outcome catalogued in this checkpoint's section 2
> (successful evaluation, successful no-op, unsatisfied condition, unestablished guarantee, each
> named mutation/charset/VR failure, successful rollback, and policy-level partial execution),
> `fastdicomstructure.policy` can report that outcome as a structured `PolicyResult` whose
> `execution`/`satisfied`/`diagnostic code` fields alone determine which of section 2's rows
> occurred -- without the caller inspecting an exception's message text, the mutated `Structure`'s
> own state, or any attrs-internal type -- and no `Diagnostic` produced while qualifying this claim
> contains a decoded element value, a raw element value, or callback input/output.

This is directly testable by section 24's plan: for each row, construct the triggering condition,
inspect only the structured fields, and confirm the row is identifiable; separately, grep every
`Diagnostic` produced during the test run for known sensitive literals used in fixtures, expecting
zero matches.

## 27. Risks / open questions

- **Finding 3 (`Replace`/`ReplaceText` callback-atomicity asymmetry) is not resolved by this
  checkpoint.** It was discovered during evidence-gathering, not invented as a hypothetical. Left
  as-is, section 8's `CALLBACK_FAILED` row and section 24's test plan **document the asymmetry
  rather than paper over it** (a test proves each operation's *actual* current behavior, not an
  assumed-symmetric one). **Recommendation for the next authorization**: either (a) explicitly scope
  a small, separate fix bringing `Replace`'s callback loop onto the same atomic engine
  `ReplaceText` already uses (a bounded, well-understood change, not a redesign -- `Replace` would
  simply gain the same `_apply_sites_atomically` wrapping `ReplaceText` already has), decided
  *before* S1.3's freeze report claims a coherent "operation atomicity" story, or (b) explicitly
  accept and document the asymmetry as a known, permanent S1.1-era limitation. Silently leaving it
  ambiguous is the one outcome this checkpoint recommends against.
- **`TEXT_OPERATION_UNSUPPORTED`'s three-way collapse** (section 8) is a real attrs Python-binding
  precision limit, not fixable within S1.3's own "no attrs change" constraint. If finer
  distinction is ever wanted, it requires attrs exposing a richer status for `set_text`/
  `insert_text`'s `NotATextVR`/`UnsupportedCharset`/`MalformedCharsetDeclaration` trio past the ABI
  -- flagged for future review, not silently expanded into this checkpoint's own scope.
  `AlreadyExistsError`'s row is similarly speculative (no test currently reaches it) and should be
  treated as defensive, not load-bearing, until real evidence says otherwise.
- **`Diagnostic.message`'s exact wording** is illustrative in section 22 -- the checkpoint commits
  to the *shape* (a fixed, code-specific template, never exception text) but not the final English
  strings, which are an implementation detail free to iterate on without breaking the contract.
- **Whether `CallbackError` should also wrap `Ensure`/`EnsureText`'s hypothetical future callback
  support** is moot today (section 18 of the S1.2 checkpoint already rejected callbacks for
  `Ensure`/`EnsureText` in V1) but worth remembering if that decision is ever revisited.

## 28. Recommendation

**READY FOR IMPLEMENTATION**, with one explicit condition (not a blocker to *starting*, but to
*freezing*): the next increment must explicitly resolve, not silently carry forward, the
`Replace`/`ReplaceText` callback-atomicity asymmetry (Finding 3) -- either by fixing it (bringing
`Replace` onto the shared atomic engine) or by formally documenting it as an accepted, permanent
limitation before S1.3's own freeze report claims a coherent atomicity story. Every other piece of
the recommended design (sections 6-19) is additive, evidence-backed, requires no attrs change, and
has a concrete, boundable implementation surface (section 23).

## 29. Implementation disposition (recorded after review and acceptance)

**This section records what was decided and built after this checkpoint was reviewed; sections
1-28 above are preserved exactly as originally written, as a record of the analysis and findings
at design time -- not rewritten to make Finding 3 look anticipated or already resolved.**

The recommended Design B was accepted for implementation, with two corrections to the boundary of
what S1.3 would resolve rather than merely document:

1. **Finding 3 (the `Replace`/`ReplaceText` callback-atomicity asymmetry) was resolved, not left as
   a condition on some later increment.** Section 28's recommendation offered two paths ("either
   fixing it... or formally documenting it as an accepted, permanent limitation"); the accepted
   correction chose the first: `Replace` was brought onto the same `_apply_sites_atomically` engine
   `ReplaceText`/`Ensure`/`EnsureText` already used, closing the asymmetry directly rather than
   documenting around it.
2. **The related, closely-adjacent `Replace`'s `set_value`-returns-`False` silent-undercounting gap
   (section 3.4/8's `MUTATION_FAILED` row) was resolved in the same pass**, for the same reason: it
   shares the exact mechanism (the same `do_update` closure, the same atomic engine) as correction
   1, and leaving it as a separate, still-silent gap after fixing the callback asymmetry would have
   been an inconsistent, half-finished result.

Both corrections were implemented by moving `Replace`'s own mutation loop onto
`_apply_sites_atomically` -- exactly the mechanism this checkpoint's sections 6/12/13 already
designed for `ReplaceText`/`Ensure`/`EnsureText`, reused, not reinvented, per this checkpoint's own
"do not create a second rollback implementation" instruction (a `Replace`-specific rollback engine
was never built or considered). See `docs/architecture/S1_3_RESULT_DIAGNOSTIC_IMPLEMENTATION_REPORT.md`
for the full implementation account, qualification evidence, and exact freeze commit.

Every other recommendation in sections 6-19 was implemented as designed, with no material
deviation identified during implementation beyond the ordinary specificity a Python implementation
requires over a design document's own pseudocode (e.g. `Diagnostic.operation_index` is corrected
after the fact by `Policy.apply()`'s own `_with_operation_index` helper, since an operation's own
`apply()` has no view of its containing `Policy` -- an implementation detail the design anticipated
in spirit, section 18, but had not worked out mechanically).

---

No production code in either repository was changed to produce the *original* checkpoint (sections
1-28). No attrs file was modified, then or during implementation. `fastdicomstructure/policy.py`
and all committed test files were unchanged from the S1.2 freeze commit at the time this checkpoint
was first written; section 29 above records what changed afterward, once implementation was
authorized. S1.4/S1.5/gateway convergence were not started.
