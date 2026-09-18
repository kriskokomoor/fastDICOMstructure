# S1.4 Implementation Report — Single Declarative JSON Configuration

## 1. Frozen starting state

| Item | Commit |
|---|---|
| fastDICOMattrs | `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6` (unchanged throughout S1.4) |
| fastDICOMstructure | `25615dd0824b1940abd7b012f69c612f61cd74c0` (S1.3 freeze) |

Both verified via `git rev-parse HEAD` immediately before any S1.4 implementation work began;
matched the authorized starting state exactly, working trees clean apart from the already-accepted
checkpoint document.

## 2. Checkpoint disposition / corrections

`docs/architecture/S1_4_JSON_CONFIGURATION_DESIGN_CHECKPOINT.md` was accepted for implementation
with three bounded corrections, recorded in that document's own "Accepted disposition and
corrections" section (appended, original analysis preserved unchanged):

1. **No extension escape hatch in V1** — the checkpoint's proposed `"x-"` extension namespace is
   removed. Configuration V1 is fully closed: every field must be understood or the document is
   rejected.
2. **Schema identifier is frozen** — `"fastdicomstructure-configuration"` is permanent, never
   replaced by a URI; a future JSON Schema document, if any, would use a separate field.
3. **No result serialization in S1.4** — `PolicyResult`/`OperationResult`/`Diagnostic` → JSON is
   out of scope; S1.4's executable boundary ends at `Policy.apply()` → `PolicyResult`, inspected
   directly by qualification code.

All three corrections are implemented exactly as specified; no further deviation from the corrected
authorization was required.

## 3. Final Configuration Contract v1

```text
Configuration
    schema            required, must equal "fastdicomstructure-configuration"
    schema_version     required, must equal 1
    policy             required
        name           required string
        version        required string
        acceptance     optional array, default [] -- "require" only
        mutation       optional array, default [] -- remove/replace_text/ensure_text/
                                                        allow_list_prune/private_tag_policy only
    source             optional envelope: {type: str (non-empty), options: object, default {}}
    destination        optional envelope: same shape
```

Every object level is fully closed: no field outside the sets above is accepted at any level,
including a `"x-"`-prefixed one (Correction 1, verified by test —
`test_x_prefixed_top_level_field_rejected`, `test_x_prefixed_operation_field_rejected`).

## 4. Public API

`python/fastdicomstructure/configuration.py`, re-exported as `fastdicomstructure.configuration`:

```python
SCHEMA_IDENTIFIER: str = "fastdicomstructure-configuration"
SCHEMA_VERSION: int = 1
CONFIGURATION_ERROR_CODES: tuple[str, ...]

class ConfigurationError(ValueError):
    code: str; path: str; message: str

class Envelope:            # frozen dataclass -- type: str, options: Mapping[str, Any]
class Configuration:       # frozen dataclass -- schema, schema_version, policy, source, destination

def load_configuration(data: Any) -> Configuration: ...
def load_configuration_json(text: str) -> Configuration: ...
def to_canonical_data(config: Configuration) -> dict: ...
def to_canonical_json(config: Configuration) -> str: ...
```

`Configuration.policy` is the actual constructed, frozen `policy.Policy` object — ready for
`policy.apply(structure, config.policy)` unchanged. No Policy semantics are duplicated.

## 5. ConfigurationError model / codes

Twelve closed codes (`CONFIGURATION_ERROR_CODES`): `MALFORMED_JSON`, `SCHEMA_MISMATCH`,
`SCHEMA_VERSION_UNSUPPORTED`, `MISSING_REQUIRED_FIELD`, `UNKNOWN_FIELD`, `UNKNOWN_OPERATION`,
`INVALID_OPERATION_PLACEMENT`, `LOCATOR_INVALID`, `TAG_INVALID`, `VR_TOKEN_INVALID`,
`VALUE_INVALID`, `ENVELOPE_INVALID`. Each has one fixed, curated message (mirroring
`policy._DIAGNOSTIC_MESSAGES`'s own pattern) — never interpolated from the offending value.
`path` is a dotted/indexed structural location (e.g. `"policy.mutation[2].target.scope"`); it
never carries a value, only a location. This is a distinct model from `policy.DIAGNOSTIC_CODES` —
`LOCATOR_INVALID` here is the resolution of the code `DIAGNOSTIC_CODES` reserved but never
produces at runtime (S1.3's own documented reservation). Fail-fast: the first problem found is
raised; no aggregation of multiple defects in one document.

## 6. Schema / version behavior

`schema` must equal `"fastdicomstructure-configuration"` exactly (`SCHEMA_MISMATCH` otherwise,
including wrong type). `schema_version` must equal the integer `1` exactly (`bool` explicitly
excluded from passing as an int, per Python's `bool <: int`) — any other value or type produces
`SCHEMA_VERSION_UNSUPPORTED`. No `"x-"` or other version-compatibility mechanism exists.

## 7. Unknown-field behavior (fail-closed, verified)

Every object level (top level, `policy`, each locator shape, each operation, each envelope) is
checked via one shared `_check_fields` helper: any field outside the exact allowed set is
`UNKNOWN_FIELD`, unconditionally — including `"x-"`-prefixed fields (Correction 1). Verified by
`test_unknown_top_level_field`, `test_x_prefixed_top_level_field_rejected`,
`test_unknown_policy_field`, `test_unknown_operation_field`, `test_x_prefixed_operation_field_rejected`,
`test_unknown_locator_field`, `test_source_unknown_core_field`, `test_destination_unknown_core_field`.

## 8. Locator JSON representation

```json
{"tag": "(0010,0010)", "scope": "root" | "recursive"}
{"path": [{"tag": "(300A,00B0)", "item": 0 | "*"}], "tag": "(0010,0010)"}
```

Canonical tag spelling only: exactly four uppercase hex digits per group, parenthesized,
comma-separated (`^\([0-9A-F]{4},[0-9A-F]{4}\)$`) — lowercase/unpadded/alternative spellings
rejected as `TAG_INVALID`, never normalized. `scope` is required on a bare-tag locator (no
Python-level per-operation default is ever silently applied — verified by construction: every
decoded locator is passed to its operation as an already-built `TagLocator`/`PathLocator`
instance, which `_normalize_locator` always uses as-is, bypassing that operation's own
`recursive=` field entirely). A locator with both `"path"` and `"scope"` is `LOCATOR_INVALID`.
Zero-step `PathLocator` is accepted.

## 9. Declarative operation vocabulary

Exactly six kinds implemented: `require`, `remove`, `replace_text`, `ensure_text`,
`allow_list_prune`, `private_tag_policy`. Each maps to the identically-named `policy.py`
dataclass, matching `OperationResult.kind`'s own vocabulary verbatim (chosen originally at the
design checkpoint, confirmed unchanged here).

## 10. Raw / callback exclusion — proof

`_ALL_KNOWN_OPS` contains exactly the six declarative kinds; `"replace"` and `"ensure"` (the raw
bytes-valued Python operations) are not members, so authoring either fails closed as
`UNKNOWN_OPERATION` with no special-casing (`test_raw_replace_op_rejected`,
`test_raw_ensure_op_rejected`). No field shape anywhere accepts a callback reference, expression,
or code string; an attempt to attach one (`"callback"`, `"expr"`) to a supported operation is
rejected as `UNKNOWN_FIELD` (`test_callback_shaped_field_rejected_as_unknown_field`,
`test_expression_shaped_field_rejected_as_unknown_field`) — not silently ignored. A mechanical
source scan (`SecurityQualificationTest.test_module_source_contains_no_dynamic_execution`)
confirms `configuration.py` contains no `eval(`, `exec(`, `__import__(`, or `importlib.` call.

## 11. Acceptance/mutation construction rule

`Policy.operations` is always assembled as every `acceptance` operation (in that section's document
order) followed by every `mutation` operation (in that section's document order) —
`_parse_policy`'s own fixed rule, not an author choice. `acceptance` accepts only `"require"`;
`mutation` accepts only the other five kinds. Placing `require` in `mutation`, or any mutation kind
in `acceptance`, is `INVALID_OPERATION_PLACEMENT` (verified:
`test_require_inside_mutation`, `test_mutation_operation_inside_acceptance`,
`AcceptanceSafetyDifferentialTest.test_configuration_v1_cannot_encode_mutation_before_require`).
`policy.apply()` itself is unmodified — zero lines of `policy.py` changed.

## 12. Value / VR semantics

`replace_text`/`ensure_text` accept a plain string or an array of strings only; mixed-type arrays,
nested arrays, `null`, numbers, and objects are all `VALUE_INVALID` (`_parse_text_value` rejects
any non-`str` item structurally, covering every listed negative case with one check). `vr` on
`ensure_text` is optional; when given it must be one of the 34 standard PS3.5 VR letter-pairs
(`_KNOWN_VR_TOKENS`, a local closed list — **not** imported from attrs' private `_VR_NAMES`, to
avoid coupling to an unexported symbol); `"UNKNOWN"` is explicitly excluded and rejected as
`VR_TOKEN_INVALID` (never a valid thing to author — omitting `vr` is the correct way to request
inference). No VR-vs-tag dictionary correctness check is performed — matches frozen attrs' own
"caller's own authoritative VR, never consulted against the dictionary."

## 13. Source/destination envelope

```json
{"type": "filesystem", "options": {"path": "/incoming"}}
```

Core fields are exactly `type` (required, non-empty string) and `options` (optional object,
default `{}`); any other sibling field is `UNKNOWN_FIELD` (Correction 1's consequence: `options` is
the one defined containment point for adapter-specific data, not an escape hatch — verified by
`test_source_unknown_core_field`/`test_destination_unknown_core_field`). `options`' contents are
never validated beyond "is it a JSON object" — preserved exactly, opaque to S1.4
(`Envelope.options` stored as a read-only `MappingProxyType`). `type` is not checked against any
adapter registry — none exists; an unregistered value like `"future-adapter"` is a valid
Configuration V1 envelope (`UnknownAdapterTypeTest`), execution-availability is explicitly S1.5's
concern, not this module's.

## 14. Validation ownership boundary

Unchanged from the design checkpoint's own boundary (section 11 there): `configuration.py` owns
JSON/schema-level syntax (field shapes, tag/VR token syntax, operation placement); `policy.py`
(untouched) owns semantic construction (`TagLocator`/`PathLocator`/`LocatorStep`'s own
`__post_init__` validation, never reached with invalid input since `configuration.py`
pre-validates exhaustively); attrs (untouched) owns dictionary/charset semantics at execution time.

## 15. Unknown-field fail-closed behavior

See section 7 — implemented uniformly via one shared helper (`_check_fields`), applied at every
object-shaped level: top level, `policy`, every locator shape, every path step, every operation,
every envelope. No exceptions, no `"x-"` namespace.

## 16. Canonical serialization / round-trip

`to_canonical_data`/`to_canonical_json` render a `Configuration` back to the canonical shape:
canonical tag spelling, acceptance operations recovered by `isinstance(op, Require)` filtering
over `Policy.operations` (exact, since acceptance is `Require`-only and always precedes mutation
by construction — no separate stored split needed, avoiding duplicating `Policy`'s own state).
Semantic (not byte-identical) round-trip verified for: Probe A, Probe F (including both
envelopes), explicit-vs-omitted VR, and a wildcard `PathLocator` (`RoundTripTest`, 5 tests, all
passing) — operation reprs compare equal after `JSON → Configuration → canonical JSON →
Configuration`. This function does **not** serialize `PolicyResult`/`OperationResult`/`Diagnostic`
(Correction 3) — confirmed by inspection: `to_canonical_data` only ever reads `Configuration`
fields, never a `PolicyResult`.

## 17. Semantic-equivalence qualification

`SemanticEquivalenceTest` (7 tests): for `require` (root), `remove` (recursive), `replace_text`
(concrete `PathLocator`), `ensure_text` (one wildcard, both `count`/`updated_count`/`inserted_count`
compared), `ensure_text` (repeated-run determinism proxy for multiple wildcards — see limitation
note below), `allow_list_prune`, `private_tag_policy` — each compares the JSON-configured path
against direct Python construction on separately-parsed identical fixtures, asserting equal
`PolicyResult` fields **and** byte-identical `structure.write_bytes()` output. All pass.

**Limitation noted honestly**: the fixture used (a single-level `BeamSequence`) does not contain a
genuinely two-level nested Sequence, so "multiple wildcard steps" is qualified only by an
equivalent-locator determinism proof (two independent applications of the same wildcard-path
operation against separately-parsed fixtures produce identical output), not by a distinct
multi-level-wildcard fixture. `resolve_locator`'s own multi-wildcard composition is already
qualified at the Locator V1 layer (S1.1); this test's purpose — JSON decoding producing an
identical `LocatorStep` sequence — does not depend on wildcard depth, so this is judged sufficient
without adding a new fixture shape solely for this increment.

## 18. Acceptance-safety differential (freeze-critical)

`AcceptanceSafetyDifferentialTest` (2 tests):

1. `test_direct_python_mutation_before_failing_require_leaves_mutation` — reproduces the documented
   Python-level footgun directly: a `Policy` with `Remove` before a failing `Require` leaves the
   `Remove` committed (`PatientName` absent) after `execution=REJECTED`. **Confirms the footgun is
   real** in the unmodified, frozen `policy.apply()`.
2. `test_configuration_v1_cannot_encode_mutation_before_require` — proves no valid Configuration V1
   document can encode that ordering: a mutation kind in `acceptance` and `require` in `mutation`
   are both rejected (`INVALID_OPERATION_PLACEMENT`), and a valid document's constructed
   `Policy.operations` always places `Require` before `Remove` regardless of which section-relative
   position was intended. **This is the direct, executable proof that the JSON restriction removes
   the exact footgun test 1 just demonstrated.**

Both tests pass.

## 19. Negative controls

`RawCallbackNegativeControlTest` (4 tests) — see section 10. All pass.

## 20. Real-DICOM validation

`RealDicomQualificationTest` (2 tests), both executed (not skipped) in this environment:
Probe A applied via `load_configuration` → `policy.apply()` against a constructed fixture;
output verified by:
- Structure's own lossless self-reparse (`_reparse_cleanly`) — no blocking diagnostics.
- **pydicom** (`pydicom.dcmread`): confirms `PatientName == "ANONYMIZED"`, `Modality == "CT"`,
  private tag `(0009,1010)` absent.
- **DCMTK `dcmdump`** (subprocess, `dcmdump` resolved via `shutil.which`): return code 0, output
  contains `"ANONYMIZED"`.

Both independent tools confirm the *resulting DICOM semantics*, not the JSON loader itself, per
the authorization's own framing.

## 21. Explicit/Implicit VR LE equivalence

`EncodingQualificationTest` (1 test): the same JSON-configured Probe A policy applied against
fixtures built under Explicit VR Little Endian (`1.2.840.10008.1.2.1`) and Implicit VR Little
Endian (`1.2.840.10008.1.2`) transfer syntaxes produces identical `execution`, `decision`, and
resulting `PatientName` text. Passes.

## 22. Charset validation

Probe C (`ensure_text` targeting `PatientName` with `"Müller^Anna"` under `SpecificCharacterSet
= ISO_IR 100`) is exercised directly in `AuthorabilityProbeTest.test_probe_c_charset_sensitive_text`
and passes — charset resolution, encoding, and representability validation are entirely attrs' own
(unmodified); `configuration.py` performs no charset-aware processing of any kind, only JSON→`str`
decoding (Python's `json` module already handles UTF-8/Unicode text correctly).

## 23. Security qualification

`SecurityQualificationTest` (4 tests):
- Mechanical source scan: no `eval(`, `exec(`, `__import__(`, `importlib.` in `configuration.py`.
- A sensitive literal (`"Zbigniew^Sekretny^SSN-123-45-6789"`) placed in both a legitimate `"value"`
  field and an intentionally-invalid extra field of an otherwise-invalid document: confirmed absent
  from `ConfigurationError.message`, `ConfigurationError.path`, and `str(exception)` — the fixed,
  curated-message design (section 5) makes this true by construction, not by a runtime filter.
- A "sensitive-looking" malformed tag string is confirmed absent from the raised error's string
  form.
- `CONFIGURATION_ERROR_CODES` is confirmed closed (no duplicates) and entirely `str`.

All pass. This is consistent with, and does not weaken, S1.3's own separately-verified runtime
`Diagnostic` privacy guarantees (untouched).

## 24. Regression totals

| Point | Total | Result |
|---|---|---|
| Baseline (S1.3 freeze, before S1.4 work) | 142 | all passing |
| After S1.4 implementation | 216 | all passing (142 pre-existing + 74 new, all in `test_configuration.py`) |

No existing test file (`test_locator.py`, `test_policy.py`, `test_pipeline_demo.py`,
`test_ensure_and_text.py`, `test_result_diagnostic.py`) was modified. No contradiction with frozen
S1.1-S1.3 behavior was discovered that required changing any of them.

## 25. Performance

`PerformanceSmokeTest`: loader timing measured at 10, 100, and 1000 `remove` operations (5 runs
averaged each). Only a pathological-blowup guard is asserted (1000-op timing well under
1000× the 10-op timing, ruling out quadratic-or-worse behavior); no throughput claim, no RSNA CTP
comparison, consistent with the authorization's explicit scope limit.

## 26. Authorability measurements

For Probe A (`AuthorabilityMeasurementTest.test_probe_a_baseline_metrics`):

| Metric | Value |
|---|---|
| JSON line count (indent=2) | 43 |
| JSON byte count (UTF-8) | 836 |
| Operation count | 4 (1 acceptance + 3 mutation) |
| Explicit VR declarations | 1 |
| Equivalent direct Python construction | 6 lines (`Policy(` + name/version + 4 operation lines) |

These are recorded as a baseline measurement only, exactly as instructed — **not** converted into a
usability or "easier" conclusion. The separate product hypothesis from the design checkpoint
(section 22 there) remains explicitly unproven.

## 27. Defects discovered/fixed

One implementation-time finding, corrected before freeze (not a change to any frozen contract):

**Probe A's original illustrative `ensure_text` target was CS-typed and not text-governed.** The
design checkpoint's own Probe A sketch (section 15 there) targeted `PatientIdentityRemoved`
`(0012,0062)` — VR `CS` — with `ensure_text`. Running it revealed `TEXT_OPERATION_UNSUPPORTED`:
attrs' Specific-Character-Set-governed VR set does not include `CS` (matching a fact already
recorded during S1.2/S1.3 fixture work — `PatientIdentityRemoved` is CS, not text-governed, unlike
`DeidentificationMethod`, which is `LO`). This is **pre-existing, frozen, correct attrs/Structure
behavior**, not a defect in `policy.py` or `configuration.py` — it is a defect in the illustrative
example only, which was never executed before this implementation turn (the design checkpoint was
analysis-only). Fixed by retargeting Probe A's third mutation to `DeidentificationMethod`
`(0012,0063)` (`vr: "LO"`) — semantically equivalent for the probe's illustrative purpose (declaring
that de-identification occurred), and now genuinely exercisable through `ensure_text`. No change to
`policy.py`, `configuration.py`, or any frozen contract was needed or made.

**Known limitation carried forward, not a defect**: a Configuration V1 author cannot use
`ensure_text`/`replace_text` to set a CS-typed marker field (e.g. `PatientIdentityRemoved`) — this
was already true of `EnsureText`/`ReplaceText` in frozen S1.2/S1.3 Python code (CS is simply not
one of the seven charset-governed VRs); Configuration V1 inherits this exactly, unchanged. A caller
needing to set such a field must use raw `Ensure`/`Replace` (bytes) programmatically — outside
Configuration V1's declarative scope by design (section 6a of the design checkpoint).

## 28. Product Capability Map changes

Updated `docs/architecture/PRODUCT_CAPABILITY_MAP.md`:

- **P2.1** (Single declarative JSON configuration): `PLANNED` → **`CURRENT`** — a working loader
  exists, qualified against semantic equivalence, round-trip, real-DICOM, and security evidence
  above.
- **P2.4** (Acceptance-policy configuration): `PLANNED` → **`CURRENT`** — `require` fully
  representable and qualified (`AcceptanceSafetyDifferentialTest`, `AuthorabilityProbeTest`).
- **P2.5** (Mutation-policy configuration): `PLANNED` → **`CURRENT`**, with an explicit note that
  Configuration V1 covers the declarative text-mutation subset (`remove`, `replace_text`,
  `ensure_text`, `allow_list_prune`, `private_tag_policy`) and excludes raw-byte (`replace`/
  `ensure`) and callback-based operations by design — those remain Python-only.
- **P2.2** (Source configuration) / **P2.3** (Destination configuration): **left `PLANNED`**, not
  promoted — only the common opaque envelope representation exists; no adapter-specific
  configuration or execution capability was built (per the authorization's explicit instruction not
  to overclaim these).

## 29. Known limitations / S1.5 carry-forward

- Raw-byte `Replace`/`Ensure` and callback-based `Replace`/`ReplaceText` remain Python-only,
  permanently by design (not a gap to close later without a separate, explicitly-authorized
  capability).
- CS-typed (and other non-charset-governed-VR) elements cannot be set via `ensure_text`/
  `replace_text` — inherited from frozen S1.2/S1.3 behavior, unchanged (section 27).
- No keyword/tag-name addressing — blocked on a capability neither attrs nor Structure exposes
  (unchanged finding from the design checkpoint).
- `source`/`destination` envelopes are syntactically validated only; no adapter registry, no
  execution semantics, no filesystem/networking/database/cloud behavior — entirely S1.5's scope.
- Result serialization (`PolicyResult`/`OperationResult`/`Diagnostic` → JSON) is not implemented —
  deferred per Correction 3 to whichever future increment has a real consumer.
- No formal JSON Schema artifact was produced — assessed and declined (section, "JSON Schema
  decision" below) in favor of the single-source-of-truth Python loader alone.

**JSON Schema decision**: a machine-readable JSON Schema was assessed against the authorization's
own criterion — "if a single-source-of-truth implementation is not clean and small, do not
implement." Configuration V1's validation logic includes several rules a declarative JSON Schema
document cannot express directly without a second, independently-maintained implementation risking
drift (e.g. the mutual-exclusion of `path`/`scope` on a locator, the closed VR-token set, the
require-only/mutation-only op-placement split, and the requirement that both wildcard tokens and
non-negative integers are valid `item` values). Producing a schema mechanically generated from the
same Python source was judged to add real implementation weight disproportionate to any benefit
over the loader's own comprehensive `ConfigurationError` reporting for this increment's scope.
**No JSON Schema artifact was implemented in S1.4** — the Python loader (`configuration.py`) is
the sole source of truth for Configuration V1 validity, as permitted by the authorization.

## 30. Exact candidate freeze commit

Recorded after the freeze commit is created — see the FINAL RESPONSE returned alongside this
report for the exact commit hash. Starting commit (verified before any implementation work):
`25615dd0824b1940abd7b012f61cd74c0`.

## 31. Final falsifiable claim

> Every V1-declarative Structure policy operation (`Require`, `Remove`, `ReplaceText`,
> `EnsureText`, `AllowListPrune`, `PrivateTagPolicy` — explicitly excluding raw-byte `Replace`/
> `Ensure` and callback-based operations, which remain programmatic-only) can be represented in a
> small, versioned, human-authorable JSON configuration, parsed deterministically into the frozen
> `Policy`/`Locator` model, and executed with semantics equivalent to direct programmatic
> construction, without exposing attrs path mechanics and without any field capable of containing
> executable configuration.

**Supported** by: 7 semantic-equivalence tests (byte-identical output vs. direct Python
construction, across root/recursive/concrete/wildcard locators, for all six declarative kinds), 2
acceptance-safety differential tests, 4 raw/callback negative-control tests, 40 validation-negative
tests, 5 round-trip tests, 2 real-DICOM tests (pydicom + DCMTK), 1 Explicit/Implicit VR LE
equivalence test, 4 security tests — 74 new tests total, all passing, alongside 142 pre-existing
tests unaffected.

The separate product hypothesis ("Common DICOM acceptance and metadata-transformation policies can
be expressed more compactly and with less application-specific code using Configuration V1 than
through direct Python construction") remains **unproven** — only baseline measurements were
recorded (section 26), not converted into a usability conclusion, exactly as instructed.
