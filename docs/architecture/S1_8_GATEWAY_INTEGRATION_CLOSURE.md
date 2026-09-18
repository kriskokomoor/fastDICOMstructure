# S1.8 Gateway Integration — Closure

Concise, evidence-oriented record of what S1.8 actually established. Every figure below was
independently reproduced (not merely read from the prior implementation report) as part of closing
this increment.

## Question

Can an existing, independently-developed application (`fastDICOMgateway`) replace its own
hand-coded DICOM mutation policy with the frozen `fastdicomstructure.policy` engine, without
changing its surrounding architecture or externally observable behavior?

## Frozen inputs

| Repository | Commit | Role |
|---|---|---|
| fastDICOMattrs | `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6` | unchanged throughout |
| fastDICOMstructure | `ffa117f1a63c7e269bfad24bfc0f5e1938430f35` | frozen S1.7 baseline, production code unchanged since |
| fastDICOMgateway | `e4cba92902750798088344995bc99d99569f73ac` | pre-integration baseline (parent commit) |
| fastDICOMgateway | `26caca86090a69eaa981236a1b716b7aac36e802` | post-integration (S1.8) |

## Intervention

Exactly **one** gateway production file changed: `src/fastdicom_gateway/transform.py`
(+52/-19 lines). `app.py` and `sink.py` are byte-for-byte unchanged. No file in
`fastDICOMstructure` or `fastDICOMattrs` was modified.

`_apply_demo_policy()`'s four imperative calls —

```python
touched += structure.erase_recursive(_TAG_PATIENT_NAME)
touched += structure.set_value_recursive(_TAG_PATIENT_ID, _DEMO_PATIENT_ID)
touched += structure.erase_recursive(_TAG_PATIENT_BIRTH_DATE)
private_removed = structure.erase_private()
```

— were replaced by a declarative `fastdicomstructure.policy.Policy` applied through
`fastdicomstructure.policy.apply()`:

```python
_GATEWAY_DEMO_POLICY = fds_policy.Policy(
    name="gateway-demo-policy", version="1.0.0",
    operations=(
        fds_policy.Remove(_TAG_PATIENT_NAME),
        fds_policy.Replace(_TAG_PATIENT_ID, _DEMO_PATIENT_ID),
        fds_policy.Remove(_TAG_PATIENT_BIRTH_DATE),
        fds_policy.PrivateTagPolicy(remove=True),
    ),
)
...
result = fds_policy.apply(structure, _GATEWAY_DEMO_POLICY)
```

`_apply_demo_policy()`'s own name, signature, and `(elements_touched, private_elements_removed)`
return contract are unchanged; `process()` required no change at all.

## Evidence (independently reproduced during closure, not merely read from the prior report)

| Check | Baseline (pre-integration) | Reproduced (post-integration) | Result |
|---|---|---|---|
| Q1 output SHA-256 | `3bf45c727c1703b7e2f99ff0c5de1f32138eeff8a86caf60770ba9a8dfcdc761` | `3bf45c727c1703b7e2f99ff0c5de1f32138eeff8a86caf60770ba9a8dfcdc761` | **exact match** |
| Q1 input/output byte count | 2414 / 2324 | 2414 / 2324 | exact match |
| Q1 `elements_touched` / `private_elements_removed` | 3 / 1 | 3 / 1 | exact match |
| Q2 (non-Explicit-VR) | `reason=unsupported_transfer_syntax`, 0 diagnostics | identical | exact match |
| Q3 (malformed input) | `reason=blocking_diagnostic`, 3 diagnostics, `(warning, warning, recoverable_error)` | identical | exact match |
| Delegation proof | — | `mock.patch.object(fastdicomstructure.policy, "apply", ...)` around a real `transform.process()` call: called exactly once, with the actual `_GATEWAY_DEMO_POLICY` object | genuine instrumentation, not two independently-computed answers |
| Old imperative calls | present | absent from production code (only referenced in comments describing what was replaced) | confirmed by direct search |
| Gateway test suite | 74 passed, 1 skipped | 77 passed, 1 skipped (74 pre-existing unmodified + 3 new) | all pass |
| Structure test suite | 299 passed | 299 passed | unchanged |
| Structure production code (`python/fastdicomstructure/`) | — | byte-for-byte unchanged vs. the S1.7 freeze | confirmed via `git diff --stat` |
| attrs | `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6`, clean | unchanged | confirmed |

## Result

The experiment demonstrated that the existing `fastDICOMgateway` application could replace its
hand-coded fixed DICOM mutation sequence with the frozen `fastdicomstructure` policy engine while
preserving the tested observable behavior, including byte-identical output for the deterministic
accepted fixture and unchanged tested rejection behavior, using an instrumented proof that the
production path genuinely invokes the shared engine rather than two independently-correct
implementations that happen to agree.

## What was NOT demonstrated

- General gateway superiority over any other tool or approach.
- Commercial need or market validation of any kind.
- Complete DICOM de-identification.
- PS3.15 (or any other) de-identification-profile conformance.
- UID remapping.
- Study- or series-level coordination across multiple objects.
- Burned-in pixel PHI handling (Pixel Data is untouched by this policy and by this architecture,
  by design — unchanged since S1.1).
- Integration into any application other than this one, specific, already-existing gateway.
- Support for arbitrary or configurable policies (the substituted policy is the same fixed,
  four-operation demonstration policy the gateway already had).
- Cloud portability beyond what S1.7 separately, independently established.
- Any performance advantage from the substitution — none was measured, and none is claimed.

## Architectural implication

This is fair evidence that the `fastdicomstructure.policy` boundary is usable, unmodified, by an
independently existing consumer application without requiring any change to `fastdicomstructure`
or `fastdicomattrs` themselves. This is evidence of **composability/reuse in one concrete,
verified instance** — not proof of universal composability, and not evidence that any other
consumer, policy shape, or integration pattern would succeed without its own separate
verification.
