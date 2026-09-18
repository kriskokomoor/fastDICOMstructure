# S1.1 -- Structure Locator Model v1 -- Freeze Report

> **Public-release redaction note (2026-09-17):** a local development-machine absolute path in an
> example command below has been replaced with a `/path/to/...` placeholder. Value-level
> substitution only — the command and its reported result are otherwise unchanged.

**Status: PASS.** Locator V1 (`TagLocator`, `PathLocator`, `LocatorStep`,
`resolve_locator`) is implemented, qualified independently of policy operations,
and the five existing policy operations are migrated onto it. All existing tests
pass unchanged; 36 new tests were added. attrs remains untouched at its frozen
commit. No later increment (S1.2+) was started.

## 1. Starting state

| Item | Value |
|---|---|
| fastDICOMstructure starting commit | `63970e5` ("Rebuild as a thin consumer of fastDICOMattrs (A0 semantic-engine extraction)") |
| fastDICOMattrs, frozen | `46bf7d3` (A1.7, A1 capability progression COMPLETE) |
| Authorizing document | `docs/architecture/POST_A1_RUTHLESS_INVENTORY.md`, accepted, section 17's S1.1 proposal |
| Baseline tests | 12/12 passing (`tests/python/test_policy.py` 11, `tests/python/test_pipeline_demo.py` 1) |
| Baseline `policy.py` | 356 lines; five operations (`Require`, `Remove`, `Replace`, `AllowListPrune`, `PrivateTagPolicy`) addressing only a bare, top-level-or-everywhere `(group, element)` tag; `_collect_tags` hand-rolled recursive tag discovery |

## 2. Locator V1 contract

Three locator kinds, one resolution engine:

1. **`TagLocator(tag, recursive=True)`** -- the bare-tag compatibility form.
   `recursive=True` (default) means "this tag, at any nesting depth, anywhere in
   the document" (pre-S1.1 `erase_recursive`/`set_value_recursive` scope);
   `recursive=False` means "this tag, root level only" (pre-S1.1
   `erase`/`set_value`/`__contains__` scope, and `Require`'s only historical
   scope).
2. **`PathLocator(steps, tag)`** -- zero or more `LocatorStep` container-descent
   steps followed by a leaf `tag`. All-concrete steps make it a CONCRETE
   LOCATOR (exactly one possible location); any step with a wildcard Item
   selector makes it a PATTERN LOCATOR (zero-to-many).
3. **`LocatorStep(tag, item)`** -- one Sequence-descent step: enter Sequence
   `tag`'s Item `item`, a non-negative concrete index or `ITEM_WILDCARD` (`"*"`).

One free function, `resolve_locator(structure, locator) -> list[ElementPath]`, is
the entire resolution engine -- every operation (`Require`/`Remove`/`Replace`/
`AllowListPrune`) calls it, or a small helper built directly on it
(`_remove_matches`, `_resolve_and_replace`); none implements its own traversal.

## 3. Type/API design

```python
Tag = tuple[int, int]
ITEM_WILDCARD = "*"

class MalformedLocatorError(ValueError): ...

@dataclass(frozen=True)
class LocatorStep:
    tag: Tag
    item: Union[int, str]          # non-negative index, or ITEM_WILDCARD

@dataclass(frozen=True)
class TagLocator:
    tag: Tag
    recursive: bool = True

@dataclass(frozen=True)
class PathLocator:
    steps: tuple[LocatorStep, ...]  # plain (tag, item) tuples accepted too
    tag: Tag
    @property
    def is_pattern(self) -> bool: ...

Locator = Union[TagLocator, PathLocator]   # documentation-only alias

def resolve_locator(structure, locator) -> list[ElementPath]: ...
```

No `Locator` base class/ABC -- deliberately, to keep the vocabulary to exactly
the three kinds required and avoid a query-language generality the brief
explicitly rejected (no value/VR/private-creator predicates; "where is it" stays
separate from "should policy apply").

`Require`, `Remove`, and `Replace` each gained one field (`locator`, replacing
the old `tag` field) accepting a bare tag, a `TagLocator`, or a `PathLocator`;
normalization happens once, in `__post_init__`, via `_normalize_locator`. No
existing call site used the `tag=` keyword (verified by inspection of every call
site in this repository), so the rename is source-compatible with every existing
positional-argument caller.

## 4. Invariants

- **Malformed vs. zero-match, separated by *when*.** A locator whose own shape
  is invalid (bad tag arity/type, bad Item selector) raises
  `MalformedLocatorError` in `__post_init__`, before any `Structure` is ever
  consulted. `resolve_locator` therefore never needs to represent "malformed" as
  a return value -- by the time it runs, the locator is guaranteed well-formed,
  and `[]` is always a legitimate answer, never an error signal.
- **Purity and determinism.** `resolve_locator` is a pure function of
  `(structure, locator)`: no mutation, and match order never depends on `dict`/
  `set` iteration (the one place a set appears, `AllowListPrune`'s tag
  difference, is `sorted()` before use). Two calls against the same unmutated
  `Structure` return identical, identically-ordered lists (tested:
  `test_deterministic_ordering`); two independent parses of the same bytes
  resolve identically too (tested:
  `test_repeated_resolution_identical_across_independent_parses`).
- **Equality/hash.** All three types are `frozen=True` dataclasses with
  hashable fields, so structural `__eq__`/`__hash__` are free -- two locators
  naming the same target compare and hash equal (tested:
  `test_locator_equality_and_hash`).
- **No new C ABI surface, no DICOM semantic reimplementation.** `resolve_locator`
  calls only `Structure.find`, `Element.is_sequence`, and `Element.items()` --
  never `.value`. It never parses bytes, infers VR, resolves a private creator,
  or interprets charset/sequence/item encoding; it only asks attrs' own public
  object model "is this a sequence" and "how many Items does it have."

## 5. Concrete locator semantics

`PathLocator(steps=(), tag=T)` (zero steps) names a root element -- meaning-
equivalent to `TagLocator(T, recursive=False)`, though a distinct type/identity
(tested: `test_root_pathlocator_equivalent_to_root_scope_tag_locator`, asserting
`resolve_locator` produces the same result for both). An all-concrete
`PathLocator` (every step a fixed Item index) names exactly one possible element
location -- it may still resolve to zero matches at runtime if the data doesn't
have it (see section 7), but the *locator* itself is unambiguous.

## 6. Wildcard semantics

Expansion is breadth-first over the step list: starting from `[[]]` (root, no
steps taken), for each `LocatorStep` in order, every surviving prefix is
extended by `find`-ing the named container and enumerating either every Item
(wildcard) or one concrete index. All ten required scenarios are directly
tested in `tests/python/test_locator.py`:

| # | Scenario | Test |
|---|---|---|
| 1 | wildcard matches every Item of the named Sequence | `test_wildcard_one_level` |
| 2 | multiple wildcard levels | `test_wildcard_multiple_levels` |
| 3 | exact Item then wildcard | `test_exact_then_wildcard` |
| 4 | wildcard then exact Item | `test_wildcard_then_exact` |
| 5 | missing Sequence | `test_missing_sequence` |
| 6 | empty Sequence | `test_empty_sequence` |
| 7 | Sequence exists, Item index doesn't | `test_invalid_item_index` |
| 8 | intermediate element exists but isn't SQ | `test_intermediate_non_sq_element` |
| 9 | target absent from one matched Item | `test_target_absent_from_one_matched_item` |
| 10 | target absent from all matched Items | `test_target_absent_everywhere` |

Multiple sibling Items are proven matched independently and in Item-index order
(`test_multiple_sibling_items_matched_independently`,
`test_wildcard_one_level`).

## 7. Zero-match semantics

**Decision: a syntactically valid locator that matches nothing is a valid empty
match set, not an error** -- the brief's stated default preference, adopted
after evaluation rather than mechanically. Rationale: every one of missing
Sequence, empty Sequence, out-of-range Item index, non-SQ intermediate element,
and target-absent-from-a-matched-Item is a *data* property, not a *locator*
property -- the same `PathLocator` object is well-formed regardless of which of
these the data happens to exhibit, and re-running it against different (or
later-mutated) data can legitimately produce a different match count. Collapsing
these five causes into one "empty branch" outcome inside `resolve_locator` is
deliberate: distinguishing *why* a branch is empty is a diagnostic-richness
question for `OperationResult`/`Diagnostic` (S1.3's concern), not a
locator-correctness question this engine needs to answer. Consequences, as
implemented:

- `Require`: zero matches -> unsatisfied (reject). One or more -> satisfied.
- `Remove`: zero matches -> successful no-op (`count=0`).
- `Replace`: zero matches -> successful no-op (`count=0`).

## 8. Malformed-locator semantics

Distinguished from zero-match by construction time, not by a result field:
`LocatorStep`/`TagLocator`/`PathLocator.__post_init__` validate tag shape (must
be a 2-tuple of non-`bool` ints) and Item selector shape (must be a non-negative
`int`, excluding `bool`, or exactly `"*"`) and raise `MalformedLocatorError`
(a `ValueError` subclass) immediately if not. `test_malformed_locator_rejected`
exercises six distinct malformed shapes: wrong tag arity, non-int tag component,
negative Item index, a non-`"*"` string Item selector, `True` as an Item index
(guarding against `bool` being an `int` subclass), and a 3-tuple leaf tag on a
`PathLocator`.

## 9. Deterministic ordering

PathLocator wildcard expansion enumerates Items via `Element.items()`, which is
itself index-ordered (0..N-1); nested wildcards compose depth-first in the same
order document traversal would produce (outer step's Item 0 fully explored
before Item 1). `TagLocator(recursive=True)` uses `Structure.iter_elements`'s
own already-deterministic document order, filtered by tag. Proven twice, at two
different granularities: `test_deterministic_ordering` (same live `Structure`,
resolved twice) and
`test_repeated_resolution_identical_across_independent_parses` (two
independently-parsed copies of identical bytes).

## 10. attrs ElementPath translation

`resolve_locator`'s return value *is* the attrs path shape already -- a `list`
of `(Tag, item_index)` steps, last step's index `None` -- directly usable with
`find`/`set_value`/`erase`/`set_text`/`decode_text`. No separate translation
function exists or is needed; this is exactly what "attrs ElementPath stays an
execution detail" means in practice: `TagLocator`/`PathLocator`/`LocatorStep`
are the only shapes a policy author or this module's own operations ever
construct by hand, and the list-of-steps shape appears only transiently, between
`resolve_locator` and the attrs call consuming its output.

## 11. JSON-authorability proof

Illustrative only -- no JSON code was written; JSON parsing is out of scope for
S1.1.

| Python | JSON |
|---|---|
| `TagLocator((0x0010,0x0010), recursive=True)` | `{"tag": [16, 16]}` (default scope) |
| `TagLocator((0x0010,0x0010), recursive=False)` | `{"tag": [16, 16], "scope": "root"}` |
| `PathLocator(steps=(LocatorStep((0x0010,0x1002), 0),), tag=(0x0010,0x0020))` | `{"path": [{"tag": [16, 4098], "item": 0}, {"tag": [16, 32]}]}` |
| `PathLocator(steps=(LocatorStep((0x300A,0x00B0), "*"),), tag=(0x0008,0x0090))` | `{"path": [{"tag": [12298, 176], "item": "*"}, {"tag": [8, 144]}]}` (the brief's own worked example, reproduced exactly) |

The mapping is lossless and mechanical in both directions: every `LocatorStep`
is one `path` array entry carrying `item`; the final entry carries `tag` only
(no `item`), which is exactly `PathLocator.tag`. `ITEM_WILDCARD` was chosen to
be the literal string `"*"` specifically so it is already the natural JSON
token, not a Python-only sentinel needing a translation rule. This confirms the
brief's own design constraint: S1.4 will not need a different Python locator
shape to build a declarative loader on top of this one.

## 12. Policy migration

All five operations now route through `resolve_locator` (directly, or via the
shared `_remove_matches`/`_resolve_and_replace` helpers) -- one locator
resolution engine, no per-operation traversal:

| Operation | Locator-capable | Bare-tag default scope | Notes |
|---|---|---|---|
| `Require` | yes | `recursive=False` (root-only, preserving `__contains__`'s exact historical scope) | Never mutates |
| `Remove` | yes | `recursive=True` (preserving `erase_recursive`'s exact historical scope) | Deletes deepest-path-first (section 13) |
| `Replace` | yes | `recursive=True` (preserving `set_value_recursive`'s exact historical scope) | Raw bytes only in S1.1 (section 16) |
| `AllowListPrune` | yes, internally (tag discovery via `iter_elements`, removal via `_remove_matches`) | N/A (takes a tag set, not a single locator) | `_collect_tags` deleted |
| `PrivateTagPolicy` | not migrated, by design | N/A (blanket flag) | Unchanged -- see section 18 |

## 13. Recursive-flag compatibility

**Determination: yes, `recursive=True`/`False` normalizes cleanly into
`TagLocator`, preserving exact legacy behavior, without a second traversal
implementation.** `Remove`/`Replace`'s `recursive: bool = True` field is
retained on the public dataclass (not removed) and, in `__post_init__`, feeds
`_normalize_locator(locator, recursive)`: a bare tag becomes
`TagLocator(tag, recursive)`, which `resolve_locator` expands via
`Structure.iter_elements(recursive=True)` filtered by tag equality (matching
`erase_recursive`/`set_value_recursive`'s matched-element set exactly) or via
root-only containment (matching `erase`/`set_value` exactly) when `False`.
Verified: `test_bare_tag_normalizes_to_expected_tag_locator_scope` asserts the
exact `TagLocator` each bare-tag call produces; every pre-existing nested/
recursive test (`PolicyNestedStructureTest`, `PolicyReproducesGatewayDemoTest`,
`PolicyDeterminismTest`) continues to pass unchanged, including byte-identical
comparison against an independently-reproduced imperative
`erase_recursive`/`set_value_recursive`/`erase_private` sequence.

Because deletion now goes through generic per-path `erase()` calls rather than
one native `erase_recursive` call, `_remove_matches` orders deletions by
descending path length (a stable sort) before deleting: equal-length matches
from one locator template can never be ancestor/descendant of each other (same
step count implies disjoint siblings), so their order never matters; the one
case where it can matter is `TagLocator(recursive=True)`, where the same tag
could in principle recur nested inside its own occurrence -- deepest-first
guarantees a descendant is removed (or found already gone, harmlessly, since
`erase()` returns `False` rather than raising) before an ancestor's `erase()`
could otherwise sweep it away as a side effect. `count` reports elements
actually removed, which can be one fewer than the number of resolved paths in
that specific self-nesting edge case -- an honest count, not a request echo.
Proven directly with sibling and nested deletion:
`test_remove_concrete_locator_touches_only_requested_occurrence`,
`test_remove_wildcard_touches_all_three_and_only_those`,
`test_concrete_remove_leaves_sibling_items_and_pixel_data_untouched`.

## 14. Require results

`Require.apply` resolves the (normalized) locator and reports `count=len(matches)`,
`satisfied=count>0`. Bare-tag behavior is unchanged (root-only, exactly
`__contains__`). New: a `PathLocator` (concrete or wildcard) can be required
directly -- "at least one Item of this Sequence has this tag" is now
expressible. Tested: `test_require_zero_one_many_matches` (concrete-satisfied,
wildcard-satisfied-with-count-3, wildcard-with-absent-leaf-unsatisfied).

## 15. Remove results

Zero matches -> no-op (`count=0`). N matches -> exactly those N removed (barring
the documented self-nesting edge case in section 13). Concrete locator removal
proven to touch only the requested occurrence, leaving a root-level occurrence
of the *same tag* and untouched sibling Items alone
(`test_remove_concrete_locator_touches_only_requested_occurrence`). Wildcard
removal proven to touch exactly all three matching occurrences and nothing else
(`test_remove_wildcard_touches_all_three_and_only_those`).

## 16. Replace results

Raw bytes only, as scoped -- no charset/Unicode semantics were added (S1.2's
concern). Zero/exact/wildcard match counts behave as for Remove. The callback
restriction from before S1.1 (`Replace(recursive=True)` + a callback raises at
construction) is **kept, but narrowed**: it now applies only to the bare-tag
`TagLocator(recursive=True)` scope specifically (preserving the exact existing
regression test,
`test_replace_recursive_with_callback_is_rejected_at_construction`), because that
scope's "anywhere, any depth, any container shape" semantics have no
per-occurrence discovery contract independent of an explicit step chain. A
`PathLocator` -- concrete or wildcarded -- **does** support a callback in S1.1:
`_resolve_and_replace` re-`find()`s each match's live element immediately before
computing `value(element.value)`, so each occurrence's callback sees that
occurrence's own original bytes, independent of how many other occurrences the
same locator matched. Proven with three sibling occurrences carrying three
distinct original values, transformed to three distinct results:
`test_replace_wildcard_callback_receives_per_occurrence_original_value`
(`b"NESTED-A"/"NESTED-B"/"NESTED-C"` -> `b"nested-a"/"nested-b"/"nested-c"`, root
occurrence of the same tag left untouched).

## 17. AllowListPrune migration

`_collect_tags` is deleted; tag discovery is now
`{element.tag for element, _ in structure.iter_elements(recursive=True)}` --
the frozen attrs A1.7 native traversal. Removal for each disallowed tag reuses
`_remove_matches` with a `TagLocator(tag, recursive=True)`, in the same
`sorted()` order as before. Existing semantics unchanged and unchanged tests
pass (`PolicyNestedStructureTest::test_allow_list_prune_keeps_only_listed_tags_at_every_depth`);
`_collect_tags`'s removal is directly asserted:
`PolicyLocatorMigrationTest::test_collect_tags_removed`
(`not hasattr(policy, "_collect_tags")`).

## 18. PrivateTagPolicy regression

Not migrated onto Locator V1, by design -- it is a blanket boolean flag over
`erase_private()`, not a tag-targeted operation, and the brief explicitly
excludes expanding creator-aware behavior in S1.1. Code is byte-for-byte
unchanged from before S1.1. Existing regression test continues to pass
unmodified:
`PolicyNestedStructureTest::test_private_tag_policy_reaches_nested_private_element`.

## 19. Encoding-independence integration

One locator-based policy (`Remove` targeting a concrete nested `PathLocator`)
applied to two independently-built fixtures carrying the same semantic content
(`Modality` root element, a nested `PatientID` under `OtherPatientIDsSequence`
Item 0) -- one Explicit VR Little Endian, one Implicit VR Little Endian (File
Meta stays Explicit VR LE per the standard; only the main dataset's encoding
switches; both use standard PS3.6 dictionary tags so attrs' own
already-qualified Implicit VR VR-inference resolves them, per its A1.4/A1.7
reports -- this test does not re-prove attrs' own parser). Both structures
start with the target present at the same logical location, both end with it
absent, both report `Decision.TRANSFORM` with equal `elements_touched`. Test:
`PolicyEncodingIndependenceTest::test_same_locator_policy_same_semantic_outcome_explicit_and_implicit`.

## 20. Non-interference

For a wildcard `Replace` (case-folding three sibling nested `PatientID`
occurrences): unrelated top-level elements (`Modality`, the private tag, a
root-level `PatientID` occurrence of the *same tag* outside the targeted
Sequence) are asserted byte-unchanged; each of the three sibling occurrences
changes to its own correct value.
(`PolicyNonInterferenceTest::test_wildcard_replace_touches_only_targeted_occurrences`)

For a concrete `Remove` (one of three sibling Items): the other two sibling
Items' `PatientID` elements are asserted untouched, and the targeted Item
itself survives (only its one element is removed, not the Item).
(`PolicyNonInterferenceTest::test_concrete_remove_leaves_sibling_items_and_pixel_data_untouched`)

**Pixel Data:** both non-interference tests additionally assert Pixel Data
byte-identical before/after. This surfaced a finding worth stating precisely
(see section 23): Pixel Data (`(7FE0,0010)`) is not reachable through
`Structure.get`/`find`/`iter_elements` **at all** -- confirmed by direct
inspection (`Structure.pixel_data_kind` reports `"native"` while `get`/`find`/
`iter_elements` all fail to surface it) and by reading fastDICOMattrs'
`DicomStructure` source, which holds Pixel Data in a dedicated `pixel_data_`
member never passed to `element_count`/`element_at`. Because of this, the
non-interference tests here compare the trailing bytes of `write_bytes()`
output (Pixel Data is placed last in the fixture and its own 16-byte encoding
never changes shape regardless of upstream edits) rather than reading through
`.get(...).value`, which cannot reach it. At the locator-engine level,
`tests/python/test_locator.py::test_pixel_data_target_never_resolves_and_never_materializes`
proves the stronger claim directly: a locator naming Pixel Data always resolves
to zero matches, and `.value` is never even attempted (checked with
`unittest.mock.patch` raising if it were).

**This exclusion is deliberate and consistent with frozen attrs' own C++
design, not an S1.1 defect.** A dedicated follow-up investigation
(`docs/architecture/S1_1_PIXEL_DATA_DISCOVERABILITY_REVIEW.md`, accepted)
traced this to its root: `Element`'s payload is strictly `Value | Sequence`,
and Pixel Data is represented instead by a separate, zero-copy
`PixelDataReference` -- a real, three-times-independently-documented design
decision (the type's own doc comment, `docs/architecture.md` section 8's
"permanently, not just for this increment," and A1.3's dedicated
`pixel_data_position()` machinery, built specifically to preserve Pixel Data's
ordering despite this separation). attrs' own Contract V1 illustrative API
already shows Pixel Data reached through a distinct accessor
(`ds.pixel_data()`), separate from `find`/`iter_elements` -- the current
behavior matches that model. **Locator V1 must not, and does not,
special-case `(7FE0,0010)` inside `resolve_locator`**: the review found that
doing so would embed DICOM-specific tag knowledge Structure was built
specifically not to own, would not generalize to any future bulk-data-shaped
tag, and would reintroduce the per-tag traversal special-casing S1.1 was
authorized to eliminate (the same reasoning `AllowListPrune`'s retired
`_collect_tags` failed on). The one real, narrower gap the review did
identify sits one layer up, not in Locator V1: the C ABI and Python binding
expose only Pixel Data's presence/kind (`fds_structure_pixel_data_kind`/
`Structure.pixel_data_kind`), discarding length/position/fragment metadata
`PixelDataReference` already computes safely in C++. That is a narrower attrs
public-surface gap, tracked separately (Product Capability Map, P1.6,
`CANDIDATE`) -- not an S1.1 defect, and not something S1.1's own scope
required or attempted to close. See the review for the full analysis,
options considered, and disposition.

## 21. Performance

Not optimized; measured only to detect obviously pathological behavior, on one
machine, single-file, synthetic fixtures (`tests/python/test_locator.py::LocatorPerformanceTest`
plus additional ad hoc measurements below):

| Locator shape | Matches | Timing |
|---|---|---|
| Root tag | 1 | ~0.03ms average |
| Deep concrete (last of 2000 sibling Items) | 1 | ~1.3ms average |
| One-level wildcard over 2000 sibling Items | 2000 | ~27ms average |
| Two-level wildcard, 400 outer x 5 inner = 2000 | 2000 | ~44ms average |

Scaling check (one-level wildcard, per-match cost, minimum of 3 runs each):

| Item count | Total time | Per-item cost |
|---|---|---|
| 500 | 11.0ms | 22.1us |
| 1000 | 22.5ms | 22.5us |
| 2000 | 27.8ms | 13.9us |
| 4000 | 49.4ms | 12.4us |
| 8000 | 89.0ms | 11.1us |

Per-item cost is flat to slightly improving as item count grows -- consistent
with a linear traversal, not a quadratic regression (which would show per-item
cost growing with `n`). This is single-file, single-machine, synthetic-fixture
evidence only; no corpus-scale or cross-file throughput claim is made (see
`PRODUCT_CAPABILITY_MAP.md`, P6.1/P6.3). RSNA CTP was not benchmarked, per this
increment's explicit exclusion.

## 22. Tests

| Suite | Before S1.1 | After S1.1 |
|---|---|---|
| `tests/python/test_policy.py` | 11 | 20 (11 unchanged + 9 new: `PolicyLocatorMigrationTest` x6, `PolicyEncodingIndependenceTest` x1, `PolicyNonInterferenceTest` x2) |
| `tests/python/test_pipeline_demo.py` | 1 | 1 (unchanged) |
| `tests/python/test_locator.py` | -- (new file) | 27 (`LocatorEngineTest` x24, `LocatorPerformanceTest` x3) |
| **Total** | **12** | **48** |

All 48 pass:

```text
$ FASTDICOMATTRS_REPO=/path/to/fastDICOMattrs python -m pytest tests/python -v
============================== 48 passed in 0.63s ==============================
```

Every pre-S1.1 test passes byte-for-byte unmodified (no test assertion in
`test_policy.py`'s original 11, or `test_pipeline_demo.py`'s 1, was changed).

## 23. Defects/limitations discovered

- **Pixel Data is outside attrs' element graph entirely.** Not a Locator V1
  defect (see section 20) -- but a real, previously-undocumented-at-this-layer
  finding: `Structure.get`/`find`/`iter_elements` cannot surface `(7FE0,0010)`
  even when `pixel_data_kind` confirms it is present. A `Require` naming Pixel
  Data will therefore always report unsatisfied, and a `Remove`/`Replace`
  naming it will always be a no-op, regardless of whether Pixel Data is
  actually present. This is a *strong, structurally-guaranteed*
  non-interference property (no locator can ever touch Pixel Data), but it is
  a surprising one if a caller ever expected `Require((0x7FE0,0x0010))` to mean
  "this object must carry Pixel Data" -- it cannot express that today. Not
  fixed in S1.1 (would require attrs exposing Pixel Data through the ordinary
  element surface, an attrs-side, cross-repo decision, and out of scope
  regardless). Recorded here so it isn't rediscovered as a "bug" later.
  Investigated in full, and accepted, as
  `docs/architecture/S1_1_PIXEL_DATA_DISCOVERABILITY_REVIEW.md`: the exclusion
  is deliberate and consistent with frozen attrs' C++ design (`Element` is
  strictly `Value | Sequence`; Pixel Data is a separate, zero-copy
  `PixelDataReference` instead); Locator V1 correctly must not special-case
  `(7FE0,0010)`; the one real gap is the C ABI/Python layer's narrower
  presence/kind-only exposure of that same C++ metadata, tracked separately
  (Product Capability Map, P1.6, `CANDIDATE`), not an S1.1 defect.
- **Fragile pre-existing test-import ordering, worked around locally.**
  `tests/python/test_policy.py` (pre-existing, unmodified by S1.1) imports
  `fastdicomstructure` with no explicit `sys.path` setup; it only succeeds
  because `tests/python/test_pipeline_demo.py`'s own import of `pipeline_demo`
  has the side effect of inserting `python/` onto `sys.path`, and pytest
  happens to collect that file before `test_policy.py` alphabetically. This
  pre-dates S1.1 and was not touched (out of scope), but the new
  `tests/python/test_locator.py` sorts alphabetically *before*
  `test_pipeline_demo.py`, so it could not rely on that same accident -- it
  bootstraps its own `sys.path` insertion instead (mirroring
  `test_pipeline_demo.py`'s own pattern) so it passes standalone and in any
  collection order, not just the one the existing suite happens to depend on.
- **Benign stderr noise, correctly attributed to a pre-existing test, not
  S1.1's own fixtures.** Running the suite under `unittest discover` (not
  `pytest`, which captures stdout/stderr on passing tests) prints one line
  during interpreter shutdown: `[recoverable_error] truncated native Pixel
  Data value`. Traced (via `pytest -s`, isolating which test emits it) to
  the pre-existing, unmodified-by-S1.1
  `test_pipeline_demo.py::PipelineAcceptanceTest::test_diagnostic_bearing_input_is_rejected_before_policy_or_persistence`,
  which deliberately truncates `pipeline_demo.build_untrusted_input()` by one
  byte to test input rejection -- that byte lands inside the fixture's own
  Pixel Data value (the last element in the file), so attrs' parser
  correctly and expectedly reports it as truncated. This is attrs behaving
  exactly as designed against a deliberately-malformed fixture, printed
  directly (not surfaced through `Structure.diagnostics`, since that test
  never successfully constructs a `Structure` at all). It does not affect
  test outcomes and has nothing to do with S1.1's own Pixel Data fixtures in
  `test_locator.py`/`test_policy.py`, whose `.diagnostics` were separately
  confirmed empty. An earlier draft of this report misattributed this
  message to S1.1's own synthetic fixtures; corrected here after tracing it
  to its actual source.
- No defects were found in frozen attrs; none were introduced into attrs
  (verified: attrs' working tree is clean and HEAD is unchanged, see section
  25).

## 24. Known limitations / carry-forward items

- **Result-model granularity (S1.3 carry-forward, explicitly not solved here).**
  `OperationResult.tag` still reports only a locator's leaf tag, not its full
  shape (steps, wildcard positions). A caller inspecting a `PolicyResult`
  cannot currently tell *which* nested location or pattern produced a given
  count from the result object alone (only from having written the `Policy`).
  Acceptable for V1 per this increment's explicit scope (no
  `PolicyResult`/`OperationResult` schema change authorized); recorded as a
  real, deliberate gap for S1.3.
- **No charset-aware `Replace`, no `Ensure`.** Exactly as scoped -- S1.2's
  concern, not attempted here.
- **`AllowListPrune` recomputes `iter_elements(recursive=True)` once per
  `apply()` call**, not once per disallowed tag -- this was already true before
  S1.1 (the old `_collect_tags` walk was also a single full traversal) and is
  unchanged in complexity shape; noted only because a reader diffing this
  operation's cost model should know it didn't get more expensive, but also
  didn't get cheaper.
- **Pixel Data unreachability** (section 23) is a real limitation on what
  `Require` can express, carried forward as a documented gap rather than
  worked around -- investigated and accepted as deliberate, consistent attrs
  design (`S1_1_PIXEL_DATA_DISCOVERABILITY_REVIEW.md`); the narrower
  actionable gap it identified (C ABI/Python exposing only Pixel Data
  presence/kind, not extent/position) is tracked as Product Capability Map
  P1.6 (`CANDIDATE`), not carried here as S1.1 debt.
- **Single-machine, single-file, synthetic performance evidence only**
  (section 21) -- no corpus-scale measurement, no RSNA CTP comparison; both
  explicitly out of scope for S1.1 (see `PRODUCT_CAPABILITY_MAP.md`, P6.1/P6.3
  and the Hypotheses section).

## 25. Exact freeze commit

Run immediately before writing this section, from a clean check of both
repositories:

```text
$ cd fastDICOMattrs && git status --short && git rev-parse HEAD
46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6
$ cd fastDICOMstructure && git status --short
 M python/fastdicomstructure/policy.py
 M tests/python/test_policy.py
?? docs/architecture/
?? tests/python/test_locator.py
```

fastDICOMattrs: working tree clean, HEAD exactly `46bf7d3` -- unchanged, as
required. fastDICOMstructure: modifications are exactly `policy.py` (the
Locator V1 engine + migrated operations) and `test_policy.py` (new migration/
integration test classes appended, all 11 original tests byte-for-byte
unmodified), plus the new `test_locator.py` and this increment's
`docs/architecture/` additions (this report; `PRODUCT_CAPABILITY_MAP.md`; and
`S1_1_PIXEL_DATA_DISCOVERABILITY_REVIEW.md`, the accepted follow-up
investigation into this report's own Pixel Data finding -- analysis and
recommendation evidence only, not an implementation authorization, per its own
stated scope -- alongside the pre-existing, already-committed
`POST_A1_RUTHLESS_INVENTORY.md`). No other file changed. `fastDICOMgateway` was
not present in this environment to inspect or modify, and was not referenced
by any code change (only read, historically, by the inventory this report
builds on).

fastDICOMstructure's own starting commit for this increment was `63970e5`; the
candidate freeze is the working-tree state described above, committed as the
S1.1 freeze commit following the discoverability review's acceptance and the
documentation corrections described above (see the top-level repository
history for the exact freeze commit hash).
