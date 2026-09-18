# S1.2 -- Charset-Aware Replace + Ensure -- Implementation Report

> **Public-release redaction note (2026-09-17):** a local development-machine absolute path in an
> example command below has been replaced with a `/path/to/...` placeholder. Value-level
> substitution only — the command and its reported result are otherwise unchanged.

**Status: PASS.** `ReplaceText`, `Ensure`, `EnsureText` are implemented, qualified against the
accepted design checkpoint (with its one required correction applied), and integrated alongside
S1.1's unmodified operations. All 48 S1.1 tests pass unchanged; 57 new tests were added (105
total). attrs remains untouched at its frozen commit. No S1.3 work was started.

## 1. Starting commits

| Item | Value |
|---|---|
| fastDICOMstructure | S1.1 FROZEN at `bdc324cfe5b71c7080d7efee8d745186d7020366`, 48/48 tests passing |
| fastDICOMattrs | frozen at `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6`, unchanged throughout S1.2 |

## 2. Accepted design contract

`docs/architecture/S1_2_REPLACE_ENSURE_DESIGN_CHECKPOINT.md`, accepted with one required
correction (section 3). Governing decisions implemented exactly as designed: four-operation
vocabulary (`Replace`/`ReplaceText`/`Ensure`/`EnsureText`) mirroring attrs' own
`set_value`/`set_text`/`insert`/`insert_text` split; an internal-only `_InsertionSite`/
`_resolve_insertion_sites` concept sharing `resolve_locator`'s step-expansion core, not a new
public `Locator` type; `Ensure`/`EnsureText`'s bare-tag default of `recursive=False` (root-only),
deliberately different from `Remove`/`Replace`'s `recursive=True`; no structural ancestor
synthesis; operation atomicity via mutate-with-guaranteed-rollback; literal-value-only
`Ensure`/`EnsureText` (no callback); `ReplaceText`'s callback preserved and extended to text.

## 3. Design-checkpoint correction (accepted before implementation)

The checkpoint originally proposed capturing an update site's pre-mutation state via
`decode_text(path)` and rolling back via `set_text(path, saved_text)` -- semantic restoration, not
byte-exact restoration. This was rejected on review: a decode-then-re-encode cycle can legitimately
choose a different (still-valid) byte representation for the same text (different ISO 2022 escape
placement -- A1.6 section 21's own documented non-guarantee -- or different padding), so "restores
the same text" is not "restores the same bytes."

**Implemented correction**: every update-site undo action captures and restores **raw bytes**,
never semantic text, regardless of whether the forward mutation was `set_value` (raw) or `set_text`
(charset-aware): `Element.value` is read *before* the forward mutation runs; rollback replays those
exact bytes through `set_value`, never `set_text`. Insert-site rollback is unchanged (`erase`). This
establishes the invariant a failed S1.2 operation restores every previously-modified existing
element to its **exact** pre-operation raw value bytes -- proven directly, not merely argued (section
16).

**Rollback-failure handling, also corrected as required**: every undo action's own outcome is now
checked (not assumed to succeed); on an unexpected failure, every *remaining* undo action is still
attempted (maximizing restoration), and a narrow, S1.2-local `RollbackError` is raised -- wrapping
the original forward failure as `__cause__` and recording which undo actions did not complete --
rather than either silently reporting success or attempting the broader S1.3 diagnostic redesign.
The design checkpoint document itself was updated (section 16a) to record this correction, per
instruction, preserving the original proposal's text as history rather than rewriting it away.

## 4. Final public API

```python
Replace(locator, value: bytes | Callable, recursive: bool = True)        # unchanged from S1.1
ReplaceText(locator, values: str | Sequence[str] | Callable, recursive: bool = True)   # new
Ensure(locator, value: bytes, vr: str | None = None, recursive: bool = False)          # new
EnsureText(locator, values: str | Sequence[str], vr: str | None = None,
           recursive: bool = False)                                                    # new
```

Raw vs. text is the class name, never a runtime type guess -- mirroring attrs' own
`set_value`/`insert` vs. `set_text`/`insert_text` split exactly (verified from the frozen Python
API, not assumed). `Ensure`/`EnsureText` reject a callable `value`/`values` at construction
(`ValueError`) -- literal-value-only, by design. `RollbackError` is exported (`policy.RollbackError`)
so callers can catch it distinctly from an ordinary forward-mutation exception.

## 5. Insertion-site resolution

```python
@dataclass(frozen=True)
class _InsertionSite:
    parent: ElementPath   # attrs container-locator shape; [] = root
    tag: Tag
    exists: bool
    target_path: ElementPath

def _resolve_insertion_sites(structure, locator) -> list[_InsertionSite]: ...
```

Internal only -- not exported, not part of the public `Locator` vocabulary. `resolve_locator`'s
`PathLocator` branch was refactored to extract `_expand_path_locator_prefixes` (the shared
step-expansion core); `resolve_locator` filters its result to leaf-exists paths (unchanged
behavior -- see section 16's regression evidence), `_resolve_insertion_sites` does not filter,
tagging each surviving prefix with whether the leaf exists there instead. `TagLocator` is handled
directly (no steps to expand): `recursive=False` always produces exactly one site (root, always a
valid container); `recursive=True` produces one site per **existing** occurrence only, never an
insertion site (see section 6 for why).

## 6. Ensure semantics

Implemented exactly per the checkpoint:

- Existing target -> update (`set_value`).
- Missing target, concretely-resolvable parent -> insert (`insert`).
- No concretely-resolvable parent (missing Sequence, wrong Item index, non-SQ intermediate) ->
  no site at all -- **no structural ancestor is ever synthesized**. Verified as a hard blocker, not
  merely a preference: `DICOMStructure::insert`/`set` and `fds::mutation::insert` all explicitly
  reject `VR::SQ` (confirmed by direct source read); no `add_item`/`create_sequence`-equivalent
  function exists anywhere in `include/`/`src/` (confirmed by exhaustive `grep`) -- Structure could
  not synthesize an ancestor even if authorized to.
- Bare-tag default `recursive=False` (root-only) -- deliberately different from
  `Remove`/`Replace`'s `True`, because insertion has no "everywhere" analogue.
- `TagLocator(recursive=True)`, passed explicitly: updates every existing occurrence, never
  inserts; zero occurrences is a genuine no-op (`count=0, satisfied=False`), not a root insertion.
- Zero insertion sites overall -> `satisfied=False` (the guarantee could not be established
  anywhere) -- meaningfully different from `Remove`/`Replace`'s "zero matches is a no-op"
  (`satisfied=True` there).
- An existing target that is itself a Sequence element is silently skipped (no mutation, not
  counted, no undo entry) -- discovered during implementation (section 21) as a necessary guard,
  mirroring `Replace`'s own long-established skip-sequence convention exactly, and avoiding
  `Element.value`'s `ValueError` for a sequence.

Tested: `EnsureRawTest` (13 tests) -- root update/insert, concrete update/insert, missing-parent
no-synthesis, wildcard mixed existing/missing, callback rejection, the full VR matrix (section 9),
atomicity/rollback (section 16), one duplicate-tag regression (section 14).

## 7. ReplaceText semantics

Unchanged targeting behavior from `Replace` (bare tag/`TagLocator`/`PathLocator`, same
`recursive=True` default, same bare-recursive-tag-locator-plus-callback restriction) with semantic
text input instead of raw bytes: forwards to attrs' `set_text`, which performs all charset
resolution/encoding/validation (section 10). Zero matches remains a successful no-op
(`satisfied=True`), exactly like `Replace` -- `ReplaceText` never has an insertion site (absence is
always a no-op, matching `Replace`'s own contract, not `Ensure`'s). Operation-atomic across every
resolved match (section 16).

## 8. EnsureText semantics

Same insertion-site semantics as `Ensure` (same root-only bare-tag default, same no-synthesis rule,
same atomicity), text instead of raw: update branch calls `set_text`; insert branch calls
`insert_text`, whose charset context is resolved at the **parent container** -- the A1.7
freeze-critical distinction this module relies on directly (section 10) rather than re-solving.

## 9. VR delegation

Verified against A1.7 section 8 and exercised directly, one test per row, all against real
dictionary tags (not invented ones):

| Case | Tag used | Result |
|---|---|---|
| Explicit VR supplied | `(0x0041,0x0010)`, `vr="LO"` | used verbatim |
| Unambiguous dictionary VR | `(0x0010,0x0020)` PatientID | inferred `LO` |
| Ambiguous dictionary VR | `(0x0028,0x0106)` SmallestImagePixelValue ("US or SS") -- same tag attrs' own C++ suite uses | `VRRequiredError` |
| Tag absent from dictionary | `(0x0000,0x0002)` (PS3.7 Command-group element -- attrs' own documented "genuine dictionary miss" example) | `VRRequiredError` |
| Private data element | `(0x0009,0x1010)` | `VRRequiredError`, always |
| Private Creator declaration | `(0x0009,0x0011)` (odd group, element in `0x10`-`0xFF`) | inferred `LO` |

Structure performs no VR inference of its own anywhere in this code -- every row above is `insert`/
`insert_text`'s own frozen behavior, observed, not reimplemented.

## 10. Charset delegation

Verified on **both** branches, per the checkpoint's own emphasis on this being the A1.7
freeze-critical property:

- **Update branch** (`ReplaceText`/`EnsureText` on an existing target): root-declared repertoire
  (`ISO_IR 100`/Latin1) inherited by a nested element with no local override; a local `(0008,0005)`
  override (`ISO_IR 144`/Cyrillic) on one Item takes effect for that Item specifically (a
  Latin1-only character is rejected there, proving the override is live, not merely present);
  sibling isolation (a neighboring Item with no override correctly falls back to *root's*
  declaration, never its sibling's -- a Cyrillic-only character is rejected there too).
- **Insert branch** (`EnsureText` on a missing target): the identical three properties -- root
  inheritance, local override, sibling isolation -- proven again, this time through
  `insert_text`'s parent-container-scoped resolution rather than the update branch's
  element-locator-scoped one. This is the specific distinction A1.7 section 10 built
  `resolve_character_set_context_for_container` to get right (a naive element-locator walker would
  silently miss a target container's own local override) -- S1.2 relies on it directly and adds no
  charset logic of its own; `grep -n "charset\|repertoire\|ISO.2022" python/fastdicomstructure/policy.py`
  confirms zero matches outside comments/docstrings quoting attrs' own terminology.

Six dedicated tests (three properties x two branches) plus their "rejects the wrong repertoire"
counterparts (four more), all in `ReplaceTextEnsureTextTest`.

## 11. Atomicity implementation

`_apply_sites_atomically(structure, sites, do_update, do_insert)` -- one shared engine behind
`ReplaceText`, `Ensure`, `EnsureText`:

1. Sites already fully resolved (a pure read) before this function runs.
2. Applies mutations one site at a time, in resolved order; on each success, records an undo
   action (`("restore_raw", path, original_bytes)` for an update, `("erase", path)` for an insert).
3. On any forward failure (an attrs exception, or -- for raw `set_value`, which returns `False`
   rather than raising -- a `False` return wrapped as the internal `_MutationFailed` marker so every
   forward-failure shape is caught uniformly), rolls back every already-applied site in reverse
   order and re-raises the original failure.
4. Returns the count of actionable sites successfully mutated (excluding any existing-but-Sequence
   site, silently skipped -- section 6).

No attrs change was needed: every individual `set_text`/`insert_text`/`insert` call is already
atomic and side-effect-free on failure (verified directly -- a failed call does not bump the Python
generation counter), so "attempt the real mutation" and "preflight-probe it" are the same safe
action; true preflight-without-any-mutation (a standalone, non-mutating `encode_text`/VR-ambiguity
query) remains unexposed past the ABI, exactly as the checkpoint found (section 25).

**Retroactive scope, honored exactly as designed**: S1.1's `Remove`/`Replace`/`AllowListPrune`/
`PrivateTagPolicy` were not given rollback machinery -- confirmed by `git diff`, their code is
byte-for-byte unchanged from the S1.1 freeze commit.

## 12. Raw-byte rollback mechanism -- proof

Two layers of proof, per the checkpoint's own "do not qualify merely by decode equality" mandate:

**Direct mechanism proof** (`EnsureRawTest::test_atomic_rollback_restores_raw_bytes_on_later_site_failure`):
a wildcard `Ensure` over two sibling Items, the second's forward `set_value` forced to fail (via
`unittest.mock.patch.object`, with every *other* call -- including the first site's forward
mutation and its own rollback -- left as the real, unmocked attrs call) after the first site's
forward mutation has genuinely already succeeded; asserts both sites' raw bytes are exactly their
pre-operation values afterward.

**Freeze-critical text proof, differentially verified**
(`ReplaceTextEnsureTextTest::test_text_rollback_restores_exact_raw_bytes_not_merely_same_decoded_text`):
a fixture whose first-touched element's original raw bytes use a deliberately non-canonical NUL pad
byte (`b"AAAAA\x00"` -- PS3.5/A1.6 mandate SPACE padding for text VRs; the fixture is built by hand
to bypass this repository's own auto-space-pad test helper, simulating a real-world non-conformant
file). A wildcard `ReplaceText` succeeds on this element (a Cyrillic replacement, representable
under its local override) before failing on a sibling (the same Cyrillic text is not representable
under the sibling's inherited Latin1 context), forcing rollback. Asserts the first element's raw
bytes end up **exactly** `b"AAAAA\x00"` again -- not `b"AAAAA "` (space-padded), which is what a
decode-then-re-encode rollback (the rejected design) would have produced.

**This test was differentially verified against the rejected design**, exactly matching A1.7's own
precedent for proving a test actually catches the bug class it names, not merely passing
vacuously: `_apply_sites_atomically` was temporarily monkey-patched (in an ad hoc verification
script, not committed) to capture `decode_text` and roll back via `set_text` -- the test then
**failed** exactly as predicted (`b'AAAAA ' != b'AAAAA\x00'`), confirming raw-byte-equality is what
actually distinguishes the accepted design from the rejected one; the real, committed implementation
was then re-confirmed passing.

## 13. Rollback-failure handling

`RollbackError(forward_error, failed_undo_actions)` -- a `RuntimeError` subclass, exported.
`forward_error` (also `__cause__`, via ordinary exception chaining) is the original failure that
triggered rollback; `failed_undo_actions` is a tuple of `(kind, path)` pairs naming exactly which
undo actions did not complete (every *other* undo action in the same rollback still ran to
completion -- rollback does not abort early on its own first failure).

Tested (`EnsureRawTest::test_rollback_failure_surfaces_as_rollback_error_not_silent_success`): a
deliberately constructed scenario (unreachable under attrs' own documented contracts, per the
design checkpoint's safety argument -- constructed here only to prove the failure-handling code
path is real, not vestigial) where site 0's forward mutation succeeds, site 1's forward mutation
fails (triggering rollback), and site 0's own rollback attempt is *also* forced to fail. Asserts
`RollbackError` is raised (not silently reported as an ordinary clean failure), with the correct
`forward_error`/`__cause__`/`failed_undo_actions` populated. The **expected normal case** -- rollback
succeeds completely -- is proven by every *other* atomicity test in the suite, none of which raises
`RollbackError`; `test_atomic_rollback_restores_raw_bytes_on_later_site_failure` specifically proves
it under an otherwise-real (non-doubly-mocked) rollback path.

## 14. Duplicate-tag behavior

Verified directly from attrs source (not assumed): `locate()` in `dicom_structure.cpp` takes the
**first** tag match within a container and stops, at every level, for every path-based primitive
(`find`/`set_value`/`erase`/`set_text` all delegate to it); `insert`/`insert_text` check the *entire*
container and correctly refuse if *any* matching tag already exists. Structure builds no
duplicate-enumeration/rejection machinery of its own -- it inherits "first occurrence" semantics
automatically through `_resolve_insertion_sites`'/`resolve_locator`'s calls to `find`. One
regression test (`EnsureRawTest::test_duplicate_tag_in_one_container_updates_first_occurrence_only`)
proves this against a genuinely non-canonical fixture (two identical `PatientID` tags inside one
Item): `Ensure` updates the first occurrence only, leaving the second untouched.

## 15. SpecificCharacterSet boundary

`(0008,0005)`'s VR is `CS`, not one of the seven text-governed VRs -- `ReplaceText`/`EnsureText`
targeting it reach attrs' `NotATextVR` (a plain `FdsError`, verified via the ABI status-mapping
table), with **zero special-casing anywhere in `policy.py`** (confirmed: no code path inspects the
tag value `(0x0008, 0x0005)`). Two dedicated tests confirm this for both operations. A third test
confirms the converse and states the boundary explicitly: raw `Replace` on `(0008,0005)` *does*
succeed (it is a raw operation, no text-VR check) but **does not transcode any other element** --
`PatientName`'s raw bytes are asserted byte-identical before and after changing the declaration.
This documents, rather than merely implies, that no dataset-wide transcode capability exists at any
layer of this family -- matching A1.6 section 19's own explicit, permanent boundary.

## 16. Tests

| Suite | Before S1.2 | After S1.2 |
|---|---|---|
| `tests/python/test_locator.py` | 27 | 27 (unchanged) |
| `tests/python/test_policy.py` | 20 | 20 (unchanged) |
| `tests/python/test_pipeline_demo.py` | 1 | 1 (unchanged) |
| `tests/python/test_ensure_and_text.py` | -- (new file) | 57 |
| **Total** | **48** | **105** |

All 105 pass:

```text
$ FASTDICOMATTRS_REPO=/path/to/fastDICOMattrs python -m pytest tests/python -v
............................................................................
.........................
105 passed in 0.71s
```

Every S1.1 test passes byte-for-byte unmodified -- confirmed by `git diff` showing
`test_locator.py`/`test_policy.py` untouched. New coverage by class: `InsertionSiteResolutionTest`
(12), `EnsureRawTest` (15), `ReplaceTextEnsureTextTest` (17), `NonInterferenceTest` (3),
`EncodingIndependenceTest` (2), `PerformanceTest` (5), `IndependentValidationTest` (2), plus one
regression test each for duplicate-tag behavior and text rollback counted within the classes above.

## 17. Independent validation

**pydicom (a separate Python implementation)**: a fresh `pydicom.dcmread` of this library's own
`write_bytes()` output, after a real `ReplaceText`+`EnsureText` policy run, independently confirms
`PatientName == "Müller^Anna"`, the inserted `(0012,0063)` value `== "café"`, `Modality == "CT"`
unchanged, and `SpecificCharacterSet == "ISO_IR 100"` unchanged -- a second, independent decoder
agrees with this library's own claims about its output.

**DCMTK's `dcmdump`**: the same style of check with a different independent implementation --
after `Ensure((0012,0062), b"YES")` (raw, correct VR `CS`) and `EnsureText((0012,0063),
"POLICY-X")` (text, correct VR `LO`), `dcmdump` exits `0` (structurally valid Part 10 output) and
its text output contains both `PatientIdentityRemoved`/`YES` and `DeidentificationMethod`/
`POLICY-X` at the expected tags. Both tests self-skip (not fail) if the corresponding tool is
unavailable in a given environment; both tools were confirmed present and both tests ran and
passed in this environment (pydicom 3.0.2, DCMTK 3.6.6).

**Serialization + reparse**: every fixture that reaches a policy call in `test_ensure_and_text.py`
is built via `fds.read_buffer(..., fidelity="lossless")` (attrs' own parser, not a hand-rolled
model) and, in the independent-validation and encoding-independence tests specifically,
`write_bytes()` output is reparsed (`_reparse_cleanly`, mirroring S1.1's own convention) before any
external tool inspects it.

## 18. Explicit/Implicit equivalence

Two tests, mirroring S1.1's own `PolicyEncodingIndependenceTest`: the same `Ensure` (update +
insert) and the same `EnsureText` (insert, charset-aware) policy applied to semantically-equivalent
Explicit VR LE and Implicit VR LE fixtures (both declaring `SpecificCharacterSet = ISO_IR 100`,
confirmed via `structure.is_explicit_vr`) produce equal `OperationResult.count` and byte-identical
(raw) / text-identical (`decode_text`) outcomes.

## 19. Non-interference

`NonInterferenceTest` (3 tests): a successful wildcard `Ensure` and a successful wildcard
`EnsureText` each leave `Modality`/`PatientName` byte-unchanged and Pixel Data's trailing encoded
bytes unchanged (Pixel Data is not reachable via `get`/`find`/`iter_elements` at all -- an S1.1
finding, unaffected by S1.2 -- so preservation is checked via `write_bytes()`'s trailing bytes,
exactly as S1.1's own non-interference tests do). A **failed, rolled-back** `ReplaceText` (forced
via the same Cyrillic-vs-Latin1 mismatch used in section 12) additionally proves unrelated
elements and Pixel Data are preserved specifically on the failure path -- a case S1.1 never needed
to prove, since none of its operations could fail mid-batch.

## 20. Performance

Not optimized; measured only to detect obviously pathological behavior, on one machine,
single-file, synthetic fixtures:

| Shape | Result |
|---|---|
| Root `Ensure` | ~0.05ms |
| Deep concrete `Ensure` (insert, last of 2000 sibling Items) | ~0.56ms |
| One-level wildcard `Ensure` (update) over 2000 Items | ~92ms (~46us/item) |
| One-level wildcard `Ensure` (insert) over 2000 Items | ~69ms (~35us/item) |
| One-level wildcard `EnsureText` (insert) over 2000 Items | ~44ms (~22us/item) |
| Two-level wildcard `Ensure` (update), 400x5=2000 sites | ~99ms (~50us/item) |

`_resolve_insertion_sites` scaling (isolated from mutation/undo-log cost), one-level wildcard,
minimum of 3 runs each:

| Item count | Total time | Per-item cost |
|---|---|---|
| 500 | 5.25ms | 10.50us |
| 1000 | 10.66ms | 10.66us |
| 2000 | 23.46ms | 11.73us |
| 4000 | 47.41ms | 11.85us |

Per-item resolution cost is flat as item count grows -- consistent with S1.1's own linear-traversal
finding for `resolve_locator`, not worsened by insertion-site resolution or undo logging. Full
`Ensure`/`EnsureText` `apply()` costs more per item than resolution alone (an extra `find()` +
mutation call + undo-log append per site), still linear, still well within "not obviously
pathological." No corpus-scale or cross-file throughput claim is made (unchanged from S1.1's own
disclosed scope); RSNA CTP was not benchmarked, per this increment's explicit exclusion.

## 21. Defects discovered/fixed

- **A real crash risk, found and fixed during implementation, before any test was written against
  it**: `_apply_sites_atomically`'s original draft called `Element.value` unconditionally on every
  existing-target site to capture the rollback baseline -- which raises `ValueError` for a target
  that happens to already be a Sequence element (no scalar value to capture). Fixed by mirroring
  `Replace`'s own long-established convention exactly: an existing-but-Sequence target is silently
  skipped (no mutation, not counted, no undo entry), never crashes. Not separately regression-tested
  with a dedicated fixture (no S1.2 acceptance criterion named this case, and it describes an
  unusual policy-authoring mistake -- targeting a container tag with `Ensure` -- rather than a
  normal use case); recorded here for transparency rather than silently absorbed.
- **Multiple odd-length raw-literal test-authoring mistakes**, caught immediately by attrs' own
  `set_value` correctly rejecting odd-length values (`False`, not a crash) during initial test
  writing -- not a `policy.py` defect, a reminder that (like `Replace` in S1.1) `Ensure`'s update
  branch never auto-pads (only its insert branch does, via attrs' `insert`'s own auto-padding
  layer) -- documented in section 29 of the design checkpoint as a foreseen, not discovered,
  asymmetry; this section records that the foreseen asymmetry was in fact encountered exactly as
  predicted, not that it was a surprise.
- No defect was found in frozen attrs; none was introduced (verified: attrs' working tree is clean
  and HEAD is unchanged throughout, see section 24).

## 22. Product Capability Map changes

`docs/architecture/PRODUCT_CAPABILITY_MAP.md` updated:

- **P1.2 (Mutation policy): `PARTIAL` -> `CURRENT`.** Evidence-based, not infrastructure-based:
  raw and charset-aware mutation, and set-or-insert semantics, now exist across every locator
  shape, fully VR-/charset-delegated, atomic, with 57 passing tests including independent
  cross-implementation validation.
- **P1.4 (De-identification/anonymization): unchanged, `DEFERRED`.** Every ingredient is now
  `CURRENT`/available, and the design checkpoint's own probe plus this increment's tests exercise
  de-identification-shaped tags directly -- but no named, reusable de-identification policy/profile
  was built or qualified as its own artifact. Not promoted, per instruction, merely because enabling
  infrastructure now exists.
- **P1.5 (Audit/results/errors): unchanged, `PARTIAL`.** `RollbackError` is new evidence of the same
  kind of gap S1.1 already named (richer result modeling deferred to S1.3), not a new capability.
- **P2.5 (Mutation-policy configuration): unchanged, `PLANNED`.** JSON-authorability re-demonstrated
  for the new operations (design-proof only); still no loader.
- New "S1.2 traceability" section added, mirroring S1.1's own.

## 23. Known limitations / S1.3 carry-forward

- **Result-model conflation, now in two places.** `OperationResult.tag` still reports only a
  locator's leaf tag (S1.1 debt, unchanged). `Ensure`/`EnsureText`'s `satisfied=False, count=0`
  cannot yet distinguish "zero insertion sites existed" from "sites existed but the atomic
  operation aborted and rolled back" -- both were explicitly named as acceptable S1.2 minimums in
  the design checkpoint (section 21) and are carried forward, not silently dropped.
- **`RollbackError` is a plain, narrow exception, not a modeled `Diagnostic`.** Mapping it (and
  attrs' own typed mutation exceptions -- `VRRequiredError`, `UnrepresentableCharacterError`,
  `InvalidUnicodeInputError`, the generic `NotATextVR` `FdsError`) onto a richer `PolicyResult`
  outcome remains S1.3's explicitly-assigned job, per the original Post-A1 inventory's own
  progression plan, not attempted here.
- **The existing-but-Sequence skip case** (section 21) has no dedicated regression test; a future
  increment touching `_apply_sites_atomically` should add one rather than rely on this report as
  the only evidence.
- **Single-machine, single-file, synthetic performance evidence only** (section 20) -- unchanged in
  kind from S1.1's own disclosed scope.
- **Duplicate-tag "first occurrence" semantics** (section 14) remain inherited, not designed --
  correct and now regression-tested, but still a property of attrs' own frozen resolution, not a
  Structure-level guarantee that could be strengthened without new attrs work.

## 24. Exact candidate freeze commit

Run immediately before writing this section, from a clean check of both repositories:

```text
$ cd fastDICOMattrs && git status --short && git rev-parse HEAD
46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6
$ cd fastDICOMstructure && git status --short
 M python/fastdicomstructure/policy.py
?? docs/architecture/S1_2_REPLACE_ENSURE_DESIGN_CHECKPOINT.md
?? tests/python/test_ensure_and_text.py
```

fastDICOMattrs: working tree clean, HEAD exactly `46bf7d3` -- unchanged, as required.
fastDICOMstructure: modifications are exactly `policy.py` (the three new operations, the
insertion-site/atomic-mutation engine, `resolve_locator`'s internal refactor -- behavior
unchanged, proven by all 27 `test_locator.py` tests passing byte-for-byte unmodified), the new
`tests/python/test_ensure_and_text.py`, the design checkpoint (already committed in a prior turn,
now updated in place with the section 16a correction), the Product Capability Map update, and this
report. `test_locator.py`/`test_policy.py` (S1.1's own tests) are untouched. No other file changed.
`fastDICOMgateway` was not present in this environment and was not referenced.

fastDICOMstructure's own starting commit for this increment was `bdc324cfe5b71c7080d7efee8d745186d7020366`;
the candidate freeze is the working-tree state described above, to be committed as the S1.2 freeze
commit following this report's own review.
