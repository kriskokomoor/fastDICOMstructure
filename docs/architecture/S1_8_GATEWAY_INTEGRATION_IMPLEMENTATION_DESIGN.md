# S1.8 Gateway Integration — Implementation Design

**Status: IMPLEMENTATION-DESIGN CHECKPOINT ONLY.** No production code in any of the three
repositories was modified; nothing was committed. Every claim below was verified against the
actual current working-tree content of `fastDICOMgateway` (including its pre-existing, uncommitted
changes — read directly, not assumed from the prior S1.8 checkpoint's own summary).

---

> **Historical-role notice (added after implementation).** This design **was** implemented, in
> `fastDICOMgateway` commit `26caca86090a69eaa981236a1b716b7aac36e802`, essentially exactly as
> proposed below (the one disclosed deviation — the `PolicyExecutionStatus` completeness check
> placed inside `_apply_demo_policy()` rather than in `process()` — made the actual change smaller
> than this document's own estimate, not larger or different in kind). See
> `docs/architecture/S1_8_GATEWAY_INTEGRATION_CLOSURE.md` for the frozen evidence and final result
> statement; this document is preserved unmodified below as the design record that governed that
> implementation.

---

## 1. Scope correction

The prior document, `docs/architecture/S1_8_EXTERNAL_DICOM_GATEWAY_DESIGN_CHECKPOINT.md`, is
preserved unchanged. It is **not** authorization for a commercial gateway product, a clinical-trial
platform, or a new cloud architecture — none of that is pursued here. The objective is narrowed to
one engineering question: can `fastDICOMgateway`'s existing, working HTTP service delegate its
DICOM metadata policy evaluation to the frozen `fastdicomstructure.policy` engine, in place of its
own hand-implemented equivalent, while its externally observable behavior stays the same?

## 2. Frozen baselines

| Repository | HEAD | Working tree |
|---|---|---|
| fastDICOMstructure | `ffa117f1a63c7e269bfad24bfc0f5e1938430f35` | clean except the untracked S1.8 industry-research checkpoint |
| fastDICOMattrs | `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6` | clean |
| fastDICOMgateway | `c8863c28c222bba3193ca1b77ea4d24e66912893` | pre-existing, uncommitted changes to `README.md`, `docs/PUBLICATION_BRIEF.md`, `src/fastdicom_gateway/transform.py`, `src/fastdicom_gateway/validation/{m2,m3}.py`, `tests/test_{m2,m3}_validation.py`, plus several untracked validation/adversarial-evidence files — present and unchanged since before this session began; not touched by this checkpoint |

`python3 -m pytest tests/python/` — **299/299 passing**. No discrepancy from the expected state.

## 3. Existing gateway architecture

Directly re-read (not assumed) from the current working tree:

- **`app.py`**: FastAPI, `POST /dicom` and `POST /dicom/store`. Reads the raw request body as
  bytes (no multipart/disk staging), calls `transform.process(body)`, and maps the result: a
  `transform.RejectedInput` → HTTP 400 with `{"status": "rejected", "reason": ...}`; **any other
  exception** → HTTP 500 with `{"status": "error"}`, logged via `logger.exception` (type/location/
  traceback only, never local variable contents — confirmed by direct inspection of the log call
  site). Success → the transformed bytes returned as the response body (`/dicom`) or additionally
  submitted via `sink.store()` (`/dicom/store`).
- **`sink.py`**: an authenticated STOW-RS submission (multipart/related, PS3.18 §6.6.1) to a
  configured Cloud Healthcare API DICOM store. Unmodified by the working-tree diff; not proposed for
  any change here.
- **`transform.py`**: the actual policy path — detailed in section 4.

## 4. Existing duplicated policy path

**Re-verified against the live working tree, not the last commit** (the file differs from
`git show HEAD:...` — see section 2). `_apply_demo_policy(structure) -> tuple[int, int]`:

```python
touched = 0
touched += structure.erase_recursive(_TAG_PATIENT_NAME)
touched += structure.set_value_recursive(_TAG_PATIENT_ID, _DEMO_PATIENT_ID)
touched += structure.erase_recursive(_TAG_PATIENT_BIRTH_DATE)
private_removed = structure.erase_private()
return touched, private_removed
```

`_TAG_PATIENT_NAME=(0x0010,0x0010)`, `_TAG_PATIENT_ID=(0x0010,0x0020)`,
`_TAG_PATIENT_BIRTH_DATE=(0x0010,0x0030)`, `_DEMO_PATIENT_ID=b"DEMO"`. These four calls
(`erase_recursive`/`set_value_recursive`/`erase_private`) are called **directly on
`fastdicomattrs.Structure`** — `fastdicomstructure.policy` is not imported anywhere in
`transform.py` (verified: no such import exists in the file). `_parse_or_reject` additionally
rejects non-`FdsError`-raising-but-still-unacceptable input: a raised `FdsError` → `RejectedInput`;
non-Explicit-VR input → `RejectedInput` (a gateway-specific acceptance-scope decision, documented
in the file's own comment as tied to this fixed policy's own demonstrated structural-visibility
limits, not a general claim); any blocking (non-`"info"`) parse diagnostic → `RejectedInput`.

**A materially important, previously-unremarked fact**: this exact recursive-mutation shape (in
gateway's own *currently uncommitted* working tree) is **already the precise scenario an existing
Structure test targets** — see section 5. Whoever wrote that test already anticipated gateway's
own in-progress fix for nested-occurrence coverage.

## 5. Existing Structure equivalent

`tests/python/test_policy.py::PolicyReproducesGatewayDemoTest::test_apply_reproduces_gateway_demo_policy`
(re-read directly, current frozen content, line 367 onward) already constructs:

```python
pol = policy.Policy(
    name="gateway-demo-equivalent", version="1.0.0",
    operations=(
        policy.Remove(_TAG_PATIENT_NAME),
        policy.Replace(_TAG_PATIENT_ID, b"DEMO"),
        policy.Remove(_TAG_PATIENT_BIRTH_DATE),
        policy.PrivateTagPolicy(remove=True),
    ),
)
```

and proves, on a fixture **with nested occurrences**
(`_build_dataset_with_nested_occurrences`), that `policy.apply(structure, pol)` produces
**byte-identical output** (`self.assertEqual(policy_bytes, gateway_bytes)`) to a locally-reproduced
copy of gateway's own `erase_recursive`/`set_value_recursive`/`erase_private` sequence, and an equal
element count once the private-tag count is added back in. `Remove`/`Replace` default to
`recursive=True` (S1.1's own established default for these two kinds specifically) — exactly
matching `erase_recursive`/`set_value_recursive`'s own semantics, with no `recursive=` argument
needed in the `Policy` construction above. This test does **not** call into gateway's own code (its
own docstring says so explicitly) — it is an independent reproduction, which is precisely why
Q7 (section 14) is required before this can be called proof of an actual dependency.

## 6. Proposed dependency direction

Confirmed already correct today for the *packaging* direction (gateway → structure → attrs), but
currently **hollow** for the *functional* direction: `transform.py` imports `fastdicomstructure as
fds` and uses only `fds.Structure`/`fds.read_buffer`/`fds.FdsError` — all of which are themselves
just `fastdicomstructure/__init__.py`'s own re-export of `fastdicomattrs`. **Gateway's actual
functional dependency today is on `fastdicomattrs`, not on anything `fastdicomstructure` itself
adds.** The proposed substitution is the *first* time this dependency becomes genuine — a materially
stronger form of the same architectural evidence the prior checkpoint was looking for.

## 7. Exact minimum substitution

**Use `policy.apply(structure, pol)` directly — not `execution.execute_one()`, not
`execution.run()`/`run_configured()`, not Configuration V1.** Reasoning, derived from the actual
code shape, not assumed: `execute_one` bundles parsing, policy application, and conditional
serialization into one call — but gateway already owns its *own* parsing/rejection step
(`_parse_or_reject`, including its Explicit-VR-only acceptance-scope check, which `execute_one` has
no equivalent for) and its *own* post-processing step (`_verify_output`'s self-reparse **and** UID
extraction for the M5 receipt — `execute_one`/`ExecutionResult` deliberately carries no identity
field at all, per S1.5's own Correction 2). Adopting `execute_one` would force gateway to either
duplicate its Explicit-VR check *again* elsewhere or restructure `_parse_or_reject`/`_verify_output`
around a boundary that does not fit them — a larger, less surgical change than necessary.
`policy.apply()` fits **exactly** at `_apply_demo_policy`'s existing call site and nowhere else needs
to move.

Configuration V1 is correctly not used: gateway's policy is fixed, not user-configurable at
request time, and constructing a `Policy` object directly (as the existing equivalence test already
does) needs no JSON, no loader, no envelope — exactly matching the authorization's own preference
for the programmatic API.

**Proposed change, confined entirely to `transform.py`:**

```python
from fastdicomstructure import policy as fds_policy   # new import

_GATEWAY_DEMO_POLICY = fds_policy.Policy(               # new module-level constant
    name="gateway-demo-policy", version="1.0.0",
    operations=(
        fds_policy.Remove(_TAG_PATIENT_NAME),
        fds_policy.Replace(_TAG_PATIENT_ID, _DEMO_PATIENT_ID),
        fds_policy.Remove(_TAG_PATIENT_BIRTH_DATE),
        fds_policy.PrivateTagPolicy(remove=True),
    ),
)

def _apply_demo_policy(structure: fds.Structure) -> tuple[int, int]:
    result = fds_policy.apply(structure, _GATEWAY_DEMO_POLICY)
    private_removed = next(op.count for op in result.operations
                            if op.kind == "private_tag_policy")
    touched = sum(op.count for op in result.operations if op.kind != "private_tag_policy")
    return touched, private_removed
```

The function's name, signature, and return contract (`(elements_touched, private_elements_removed)`)
are preserved exactly — `process()` and every caller of `_apply_demo_policy` need no change at all.

**One genuinely new behavior this surfaces, named precisely, not hidden**: `policy.apply()` can, in
principle (never observed, but architecturally real — S1.3's frozen contract), return
`PolicyExecutionStatus.PARTIAL` for this exact policy if `Replace`'s atomic engine ever fails a
`set_value` on a recursively-matched `PatientID` site (gateway's *old* `set_value_recursive` call
had no equivalent failure signal at all — a bool-return primitive that could only silently
under-count, never surface a real failure). `policy.apply()` can also, separately, raise
`RollbackError` if such a failure's own rollback cannot fully restore a site. **Neither requires a
new `except` clause in `app.py`**: both are already covered by its existing, unmodified bare
`except Exception` → 500 path (verified directly, section 3) — but the *decision* that `PARTIAL`
should be treated as an internal failure (not silently returned as if it were a clean transform) is
new and belongs in `transform.py`'s own `process()`, roughly:

```python
if result.execution is not fds_policy.PolicyExecutionStatus.COMPLETED:
    raise RuntimeError("gateway demo policy did not complete")  # -> app.py's existing 500 path
```

placed immediately after the `_apply_demo_policy` call inside `process()`. This is the only other
line proposed anywhere in the substitution.

## 8. Repository ownership of each change

**All proposed changes are confined to `fastDICOMgateway`.** `fastDICOMstructure`: **zero**
production changes — `policy.apply()` is used exactly as already frozen. `fastDICOMattrs`: **zero**
changes. This is the preferred result named in the authorization, and the evidence supports it
without qualification.

## 9. Files/functions proposed for modification

| File | Function | Change |
|---|---|---|
| `src/fastdicom_gateway/transform.py` | module level | one new import (`from fastdicomstructure import policy as fds_policy`); one new constant (`_GATEWAY_DEMO_POLICY`) |
| `src/fastdicom_gateway/transform.py` | `_apply_demo_policy` | body replaced, signature/name unchanged |
| `src/fastdicom_gateway/transform.py` | `process` | two lines added (the `PARTIAL` check, section 7) |

No other file (`app.py`, `sink.py`, `validation/*`, `Dockerfile`, `pyproject.toml`) is proposed for
any change.

## 10. Approximate additions/deletions

~15–18 lines added (1 import, ~7-line `Policy` constant, ~5-line rewritten function body, 2-line
`PARTIAL` check), ~5 lines removed (the old four-line hand-rolled body). **Net roughly +10 to +13
lines, one file, three touch points within it.** This eliminates the gateway's own duplicated
recursive-mutation reasoning (and the comment block explaining it, itself evidence of nontrivial
independent re-derivation — section 4) in favor of a single already-tested declarative
`Policy` object.

## 11. Dependency/packaging implications

**No new wiring required.** `fastdicomstructure/__init__.py` already re-exports `policy` in its own
`__all__`; gateway's existing `_add_fastdicomstructure_to_path()` sibling-discovery mechanism already
puts the whole package (including the `policy` submodule) on `sys.path` for local tests. For the
**container build**: gateway's own Dockerfile already executes
`COPY --from=structure python/fastdicomstructure /usr/local/lib/python3.12/site-packages/fastdicomstructure`
— copying `policy.py`, `configuration.py`, `execution.py`, and `adapters/` into the runtime image
**today, already, entirely unused**. No Dockerfile change is required for this substitution. This
is a clean, zero-packaging-friction finding, not a hoped-for one.

## 12. Behavior that must remain invariant

- Accepted input still produces transformed bytes with the same four operations' combined effect.
- Rejected input (parse failure, non-Explicit-VR, blocking diagnostic) still raises
  `RejectedInput` with the same `reason` values, via the same, untouched `_parse_or_reject`.
- Malformed DICOM: unchanged (parse-time rejection is not touched by this substitution).
- Transformed output bytes: **must remain identical** for the same input (section 5's existing
  test already establishes this at the object level; Q1 re-establishes it through the actual
  `transform.process()` call path — section 14).
- Destination (STOW-RS) invocation: unchanged, `sink.py` untouched, still called exactly once for
  accepted output on `/dicom/store`.
- Destination failure semantics: unchanged, `sink.py` untouched.
- HTTP status codes and response bodies: unchanged — `app.py`'s existing 400/500/200 mapping
  requires no new branch (section 7).
- Diagnostics/logs: unchanged privacy posture — `logger.exception`'s existing type/location/
  traceback-only discipline already covers any new exception shape this substitution can produce.
- Existing tests: `tests/test_m2_validation.py`, `tests/test_m3_validation.py`, and any other
  existing gateway test must continue to pass unmodified.

## 13. Explicit exclusions

This experiment does **not** claim: full DICOM de-identification, PS3.15 conformance, study-level
anonymization, complete PHI removal, or burned-in-pixel-PHI handling — carried forward unchanged
from the prior checkpoint's own findings (its section 8/14). The gateway's fixed policy is, and
remains, accurately described only as **policy-driven metadata transformation** of three named
attributes plus private-tag removal — exactly what it already was before this substitution, now
expressed declaratively instead of imperatively. No UID remapping is introduced or implied by this
policy (it never targets a UID-shaped tag).

## 14. Qualification probes Q1–Q8

| Probe | Design |
|---|---|
| **Q1 — baseline equivalence** | Capture `sha256(transform.process(fixture).output_bytes)` from the *current* (pre-substitution) code against gateway's own existing fixtures (reusing `validation/fixtures.py` if suitable); after substitution, assert the identical hash for the identical fixture. Byte identity is achievable here (not merely semantic equivalence) because the operation sequence and its ordering are unchanged, only its expression is. |
| **Q2 — rejection equivalence** | For each existing `RejectedInput` fixture/reason, confirm `transform.process()` still raises with the same `reason` string, unchanged (this path is untouched by the substitution, so this is a regression check, not a new proof). |
| **Q3 — malformed input** | Same as Q2 for parse-failure fixtures specifically — untouched code path, regression check only. |
| **Q4 — sink behavior** | `sink.store()` called exactly once for an accepted `/dicom/store` request, with `sink.py` itself unmodified — a call-count assertion (mock/spy), not a new sink implementation. |
| **Q5 — sink failure** | Existing `PersistenceFailed`/`StoreFailure` fixtures continue to produce the same `/dicom/store` failure response — regression check, `sink.py` untouched. |
| **Q6 — privacy** | Inject a known sensitive literal (matching this project's own established technique) into a fixture's `PatientName`/private-tag value; confirm it does not appear in any HTTP response body, log line, or exception message across both `/dicom` and `/dicom/store`, for both accept and reject paths. |
| **Q7 — dependency proof** | **Required, and deliberately not satisfied by Q1 alone.** Monkey-patch `fastdicomstructure.policy.apply` with a counting wrapper (the identical technique already established in `tests/python/test_cli.py`'s `DifferentialTest.test_run_delegates_to_execute_one_exactly_once`) around a real `transform.process()` call, and assert it is invoked exactly once with the expected `Policy` object — direct, executable proof gateway's production path reaches Structure's engine, not two independently-computed answers that happen to agree. |
| **Q8 — regression** | All existing gateway tests green; all 299 frozen Structure tests remain passing; attrs remains at its exact frozen commit, clean. |

None of these has been executed — this section is a design, not a report of results.

## 15. Proposed S1.8 claim

> The existing `fastDICOMgateway` application can delegate its fixed DICOM metadata policy
> evaluation and transformation (removal of `PatientName`, replacement of `PatientID`, removal of
> `PatientBirthDate`, and private-tag removal) to the frozen `fastdicomstructure.policy.apply()`
> engine, via a change confined entirely to one function and one new module-level constant in
> `transform.py`, while preserving byte-identical transformed output, its existing HTTP status/
> response-body contract, its existing STOW-RS destination behavior, and its existing privacy
> discipline — without any change to `fastDICOMstructure`, `fastDICOMattrs`, Configuration V1, or
> `app.py`/`sink.py`.

No claim is made about commercial usefulness, market differentiation, production readiness,
general clinical-trial workflow support, full de-identification, arbitrary gateway compatibility,
other DICOMweb systems, or any deployment/cloud property beyond what Q1–Q8 actually test.

## 16. STOP conditions

Evaluated against the evidence gathered directly above, item by item:

1. Structure production code must change — **not triggered**.
2. attrs must change — **not triggered**.
3. Configuration V1 must change — **not triggered** (not used at all).
4. Gateway must be substantially redesigned — **not triggered** (one function, one constant, two
   extra lines in `process()`).
5. New HTTP abstraction required in Structure — **not triggered**.
6. Generalized network destination abstraction required — **not triggered** (`sink.py` untouched).
7. UID/study-level coordination becomes necessary — **not triggered** (this policy never targets a
   UID).
8. Durable staging/retry infrastructure required — **not triggered**.
9. Large compatibility layer required to preserve behavior — **not triggered**; the one new
   behavioral case (`PARTIAL`/`RollbackError`) is already covered by `app.py`'s existing exception
   handling, requiring only a 2-line explicit decision inside `transform.py` itself.
10. Dependency wiring becomes a substantial packaging project — **not triggered**; zero new wiring
    needed anywhere, including the container build (section 11).
11. Resulting implementation larger/more complex than what it replaces — **not triggered**; comparable
    or smaller, and removes duplicated reasoning (section 4/10).
12. Integration makes the dependency direction less clear — **not triggered**; it makes gateway's
    dependency on Structure *real* for the first time (section 6), strictly clearer than today's
    pass-through-only relationship.

**No STOP condition is triggered.**

## 17. Risks/open questions

- The `PolicyExecutionStatus.PARTIAL` case (section 7) has never been observed in practice for this
  fixed policy — the proposed handling is a reasonable, small, explicit decision, not something Q1–Q8
  can prove is *correct* absent a fixture that actually triggers it (none is known to exist; this is
  disclosed, not hidden).
- Gateway's own uncommitted working-tree changes (section 2) are outside this checkpoint's control —
  the proposed diff is written against that current state; if gateway's own maintainers commit,
  revert, or further change `transform.py` before this integration is implemented, the exact diff
  in section 7 would need to be re-derived against whatever state exists at that time.
- This checkpoint did not execute Q1–Q8; a future implementation turn would need to actually capture
  the "before" baseline (Q1) before touching `transform.py`, since the substitution itself would
  overwrite the code needed to produce that baseline.

## 18. Implementation recommendation

**AUTHORIZED FOR MINIMAL INTEGRATION IMPLEMENTATION**

The evidence supports a genuinely small, surgical, single-file substitution: zero changes to
`fastDICOMstructure` or `fastDICOMattrs`, zero new packaging/dependency wiring (including for the
existing container build), zero changes to gateway's HTTP layer or STOW-RS sink, and a net addition
of roughly ten lines confined to one function and one new constant in `transform.py`. An
already-existing, already-passing Structure test independently establishes byte-identical output
for exactly this substitution's target policy on a fixture with nested occurrences — strong prior
evidence, though Q7's dependency-proof instrumentation is still required before this can be called
more than a coincidence of two independently-correct implementations. No STOP condition is
triggered. Implementation itself is not performed by this checkpoint, per its own authorization.

```text
attrs: FROZEN @ 46bf7d3
S1.1: FROZEN @ bdc324c
S1.2: FROZEN @ 53ecb83
S1.3: FROZEN @ 25615dd
S1.4: FROZEN @ 8879ca7
S1.5: FROZEN @ 350f88c
S1.6: FROZEN @ 9b84a2a
S1.7: FROZEN @ ffa117f
S1.8: IMPLEMENTATION-DESIGN CHECKPOINT ONLY — AUTHORIZED FOR MINIMAL INTEGRATION IMPLEMENTATION
```

No production code in any of the three repositories was modified; nothing was committed.
