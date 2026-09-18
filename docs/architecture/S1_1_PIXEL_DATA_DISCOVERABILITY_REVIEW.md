# S1.1 Pixel Data Discoverability Review

**Status: ANALYSIS ONLY.** No file in this repository or in `fastDICOMattrs` was modified,
refactored, or renamed to produce this review. Both repositories remain exactly as they were at
S1.1's candidate freeze (`fastDICOMattrs` at `46bf7d3`, working tree clean; `fastDICOMstructure`
carrying only S1.1's own already-reported changes). This review answers the central question the
S1.1 Pixel Data finding raised, and stops at a recommendation -- nothing here is authorization to
implement it.

## Central question

> Should Pixel Data be discoverable through fastDICOMattrs' semantic attribute surface, without
> materializing or decoding the Pixel Data payload -- so a caller can identify that (7FE0,0010)
> exists, locate it semantically, inspect safe metadata about it, and target it through Structure
> policy, while retaining attrs' zero-copy/by-reference bulk-data behavior?

**Short answer: partially yes, but not by changing where Pixel Data lives, and not by touching
Locator V1.** attrs already built almost everything this question asks for -- a dedicated,
zero-copy, non-decoding metadata object (`PixelDataReference`) -- and did so as a documented,
deliberate design choice, not an oversight. The real gap is narrower and sits one layer up: the C
ABI and Python binding collapse that already-rich C++ object down to a 3-state enum
(none/native/encapsulated), discarding length, VR, and position information the C++ layer already
computes safely. That narrowing -- not the C++ separation itself -- is the part worth reconsidering,
and it does not require or suggest folding Pixel Data into `find`/`iter_elements`.

## 1. How Pixel Data is represented (traced from frozen `46bf7d3`)

**Parser.** Both dataset parsers (`src/parser/explicit_vr_le_parser.cpp`,
`parse_pixel_data()` at line 298; `implicit_vr_le_parser.cpp`, the equivalent Implicit VR loop) peek
the next tag; when it equals `kPixelDataTag` `(0x7FE0,0x0010)`, they branch into a dedicated
`parse_pixel_data()` function instead of the ordinary element-parsing path. That function:

- reads the tag/VR/reserved/length header itself (not through the generic element header reader);
- for a defined length (`length != kUndefinedMarker`), records one `SourceSpan` over the raw pixel
  bytes **in place** and returns `PixelDataReference::native(...)` -- the bytes are never copied,
  never touched, only their offset/length recorded;
- for an undefined length, walks the Basic Offset Table Item and each fragment Item's header
  (tag + length only) to build a `SourceSpan` per fragment, **without interpreting fragment
  contents** (the code comment is explicit about this), and returns
  `PixelDataReference::encapsulated(...)`.

**Native representation** (`include/fastdicomattrs/pixel_data_reference.hpp`): VR, the 2 reserved
header bytes (kept for lossless fidelity), the resolved `TransferSyntax`, and one `SourceSpan`
(`native_span()`) covering the raw bytes.

**Encapsulated representation**: the same VR/reserved/transfer-syntax fields, plus an optional
`SourceSpan` for the Basic Offset Table and a `std::vector<PixelDataFragment>` (each fragment
itself just a `SourceSpan`). No fragment's bytes are ever decoded or reassembled.

**Where it lives in `DICOMStructure`**: a sibling field, not a member of the element list --

```cpp
std::vector<Element> elements_;
std::optional<PixelDataReference> pixel_data_;
std::optional<std::size_t> pixel_data_position_;
```

(`include/fastdicomattrs/dicom_structure.hpp`, private section). `pixel_data_position_` (added in
A1.3) separately records how many *ordinary* top-level elements preceded Pixel Data in the source,
specifically so the writer can reproduce Pixel Data's true relative position -- including an
element that followed it, e.g. Data Set Trailing Padding `(FFFC,FFFC)` -- instead of always
emitting it last. This is real, deliberate engineering investment spent *because* Pixel Data lives
outside `elements_`; a team that considered the separation an oversight would not have built a
second field and a writer algorithm to compensate for its ordering cost.

**Why it is excluded from the ordinary element vector -- a structural reason, not a preference.**
`Element`'s payload is `std::variant<Value, std::unique_ptr<Sequence>>`
(`include/fastdicomattrs/element.hpp`) -- exactly two shapes, scalar or sequence. `Value` itself
already supports zero-copy, source-backed bytes (`Value::from_source(source, span)`,
`include/fastdicomattrs/value.hpp`) -- so **native** Pixel Data alone could, in principle, be
represented as an ordinary `Element` holding a source-backed `Value` over one span, without
materializing anything. But `Value` can hold exactly one contiguous span (or one owned buffer) --
it has no shape for "a Basic Offset Table span plus N fragment spans." **Encapsulated** Pixel Data
therefore cannot be represented as a `Value` at all, regardless of the materialization question.
Since a `DICOMStructure` must have one representation for tag `(7FE0,0010)` that works whether the
source happened to be native or encapsulated -- not two different runtime shapes for the same tag
depending on content -- keeping *all* Pixel Data as a uniform `PixelDataReference`, for both forms,
is the one-concept choice consistent with this codebase's stated preference elsewhere (e.g.
`docs/architecture.md` section 5 on File Meta: "keeps the object model to one concept... instead of
two").

**Ordering.** Preserved exactly, via `pixel_data_position()` for the unmodified write path
(verbatim source position, including anything that followed it) and via fresh ascending-tag-order
recomputation for the modified path (`(7FE0,0010)` participates in exactly the same
`std::lower_bound`-based ordering rule every other top-level element already follows -- not a
special case). See `docs/architecture/A1_3_PIXEL_DATA_ORDERING_REPORT.md` for the full, tested
account.

**Writer access**: `write_pixel_data()` (`src/writer/lossless_writer.cpp:163`) writes the tag/VR/
reserved bytes itself, then `source.data(span)` directly into the output stream for native data (or
per-fragment for encapsulated) -- no intermediate buffer, confirmed by the A1.3 report's own
`grep`-based check ("no new `std::vector<std::byte>` copy or allocation was introduced on the Pixel
Data write path").

**Public C++ API**: `DICOMStructure::pixel_data() -> const PixelDataReference*` (nullptr if absent),
`pixel_data_position()`. `PixelDataReference` itself exposes `tag()` (always `(7FE0,0010)`, present
for API uniformity), `vr()`, `reserved_bytes()`, `transfer_syntax()`, `is_encapsulated()`,
`native_span()` (whose `.length()` is the byte count -- extent, without reading a single byte),
`basic_offset_table()`, `fragments()`.

**C ABI**: exactly one function, `fds_structure_pixel_data_kind` (`abi/include/fastdicomattrs_c/
fds.h:188`), implemented as (`abi/src/*.cpp:380-384`):

```cpp
int fds_structure_pixel_data_kind(const fds_structure_t* structure) {
  const auto* pixel_data = from_c(structure)->structure->pixel_data();
  if (pixel_data == nullptr) return 0;
  return pixel_data->is_encapsulated() ? 2 : 1;
}
```

Every other field on `PixelDataReference` -- VR, reserved bytes, native span length, position,
fragment count -- is read by this function and then **discarded**; nothing else crosses the ABI.
Confirmed by exhaustive `grep` across `abi/include/fastdicomattrs_c/fds.h` and `abi/src/*.cpp`: no
`pixel_data_position`, `pixel_data_length`, `pixel_data_span`, or `pixel_data_vr` symbol exists
anywhere in the ABI.

**Python API**: `Structure.pixel_data_kind` (`python/fastdicomattrs/__init__.py`), a property
mapping the ABI's `{0: None, 1: "native", 2: "encapsulated"}` -- the same narrowing, one layer
further out. There is no Python-level `pixel_data()` accessor at all (unlike the illustrative API
in the Attrs Contract V1 document -- see section 3).

## 2. Was the exclusion intentional?

**Yes, unambiguously, for the C++-layer separation.** Three independent pieces of primary evidence,
none written in response to this review:

1. `pixel_data_reference.hpp`'s own doc comment: "Location/extent/encoding of the dataset's Pixel
   Data element, without decoding it... Pixel bytes are never materialized into an owned buffer by
   this library."
2. `docs/architecture.md` section 8, "Pixel data": "Pixel Data (`(7FE0,0010)`) is never turned into
   an allocated `Value` inside `DICOMStructure`... Decoding pixel bytes is explicitly out of scope,
   **permanently, not just for this increment**." (emphasis in the original)
3. A1.3's entire scope (`A1_3_PIXEL_DATA_ORDERING_REPORT.md`) is dedicated to compensating for the
   ordering consequence of this separation -- new field, new writer logic, 11 new tests, a real
   pre-fix defect reproduced and fixed. This is not the shape of an accidental gap; it is the shape
   of a team protecting a decision they consider load-bearing.

The rationale, per the evidence, is **prevent accidental materialization** (the dominant, explicitly
stated reason) plus, as a structural consequence rather than a separately-argued goal, **handle
encapsulated fragments** (no other object in this codebase can represent a multi-span payload) and
**preserve source spans / writer fidelity** (both downstream of the same non-materialization
commitment). It is not framed anywhere as being about "distinguishing bulk data from normal Value"
as a philosophical category for its own sake -- see section 3: the Attrs Contract V1 gap analysis
explicitly flags that *general* bulk-data recognition (beyond Pixel Data specifically) does **not**
yet exist as a named concept, which cuts against reading the current design as a deliberate general
theory of "bulk data" rather than a Pixel-Data-specific accommodation.

**Whether the ABI/Python narrowing (kind-only) was equally intentional is less clear.** No document
inspected states "the C ABI should expose only kind, discarding length/position." It is consistent
with, but not compelled by, the C++-layer decision -- see section 3.

## 3. Classification against Attrs Contract V1

The relevant document is `docs/architecture/ATTRS_CONTRACT_V1_AND_GAP_ANALYSIS.md`. Two passages
matter, and they point in different directions depending on which layer is being judged:

- Section I, "Bulk data behavior": "**MUST**: recognize Pixel Data specifically and expose
  location/extent/encapsulation metadata without decoding (**already implemented and well-designed
  in `fastDICOMstructure`**)." The MUST is explicitly marked satisfied.
- Section 6's illustrative API model shows `pixel_ref = ds.pixel_data()` -- **a separate call**,
  distinct from `ds.find(...)` and `ds.iter_elements(...)` in the same code block -- annotated
  "metadata only, never materializes bytes."

Reading both together: the contract's own illustrative model *already anticipated* Pixel Data being
reached through a dedicated accessor, not through ordinary attribute discovery. Nothing in the
contract states or implies Pixel Data must also be reachable via `find`/`iter_elements`. On that
basis, **the current separation from the element graph is (A) fully consistent with the frozen
contract** at the design-intent/C++ layer.

**However**, the contract's own MUST is "expose location/extent/encapsulation metadata" -- and the
illustrative `ds.pixel_data()` is shown returning something a caller inspects for that metadata.
The frozen Python binding's actual `pixel_data_kind` delivers only *encapsulation* (kind); *extent*
(length) and *location* (a discoverable path/position) are computed in C++
(`native_span().length()`, `pixel_data_position()`) but never exposed past the ABI. This is **(C) an
accidental/incomplete gap against the contract** at the ABI/Python layer specifically -- not because
anyone documented "we decided not to expose length," but because A1.7's Python binding work
(building `pixel_data_kind` to answer the narrower "native vs. encapsulated vs. absent" question
that was actually needed at the time) never revisited the fuller "location/extent" MUST the contract
had already written down. No document argues the narrower `kind`-only surface is the intended final
state; it reads as an implementation that satisfied an immediate need and stopped, not a considered
exception.

**Verdict: split by layer.** C++ design (the separation itself): **A**. ABI/Python exposed surface
(kind-only, discarding length/position the C++ layer already has safely): **C**. Neither verdict
implies Locator V1 or `resolve_locator` should change -- see sections 5-6.

## 4. Discovery versus value access

The object model already supports exactly this distinction for Pixel Data -- it is the entire
reason `PixelDataReference` exists as a type separate from `Value`. Concretely, already
available **without decoding or copying anything**:

| Fact | Available today | Where |
|---|---|---|
| Tag identity | yes (trivially `(7FE0,0010)` by construction) | `PixelDataReference::tag()` |
| Presence | yes | `pixel_data() != nullptr` (C++); `pixel_data_kind` (Python, `None` vs. not) |
| VR | yes, in C++ | `PixelDataReference::vr()` -- **not exposed past the ABI** |
| Path/location among top-level elements | yes, in C++ | `pixel_data_position()` -- **not exposed past the ABI** |
| Native vs. encapsulated kind | yes, everywhere | `is_encapsulated()` (C++); `pixel_data_kind` (Python) |
| Encoded length (extent), native | yes, in C++ | `native_span().length()` -- **not exposed past the ABI** |
| Fragment count/lengths, encapsulated | yes, in C++ | `fragments()[i].span.length()` -- **not exposed past the ABI** |
| Source/reference metadata | yes, in C++ (it *is* the representation) | the `SourceSpan`s themselves -- meaningless outside the process, correctly not exposed |

Explicitly and permanently unavailable, by design, at every layer: decoded pixels, copied Pixel
Data bytes, automatic materialization. Nothing inspected suggests weakening that; nothing in this
review recommends it.

**The object model cleanly supports the discovery/value-access split already** -- `PixelDataReference`
*is* that split, correctly built. The only real question is which of its already-safe fields are
worth threading through the ABI and Python binding (a narrow, additive, non-materializing change --
see Option B) versus which should stay C++-internal (the raw `SourceSpan`s, which are meaningless
without the C++ `Source` they resolve against).

## 5. Product-level policy cases

| Policy | Classification | Why |
|---|---|---|
| Require Pixel Data (presence) | Already possible cleanly, **not via a Locator** | `structure.pixel_data_kind is not None` today, in Python, with zero attrs changes -- but only as a bespoke check outside `policy.py`, since no `Locator`/`resolve_locator` path can see it (by design, section 1) |
| Reject if Pixel Data exists | Same as above | Same -- `pixel_data_kind is not None` answers it directly |
| Accept metadata-only DICOM only | Already possible cleanly, not via a Locator | `pixel_data_kind is None` -- same primitive, inverted |
| Remove Pixel Data | **Requires attrs support that does not exist at any layer** | No C++/ABI/Python primitive removes, nulls, or replaces Pixel Data -- confirmed by exhaustive `grep` for `erase.*pixel`/`remove.*pixel` across the whole attrs tree, no match. This is a real, unbuilt capability, not a discoverability gap -- and it raises its own questions this review does not attempt to settle (does "remove" mean drop the element declaring zero length, or omit it entirely, and how does that interact with `pixel_data_position()`/group-length recomputation?). |
| Route based on native vs. encapsulated | Already possible cleanly, not via a Locator | `pixel_data_kind`'s two non-`None` values already distinguish this |
| Report presence/size without reading payload | **Split**: presence -- already possible; size -- **requires a narrow attrs/ABI/Python addition** | `native_span().length()` (native) / per-fragment lengths (encapsulated) exist in C++ today and would need one new ABI accessor each (or one combined struct) plus a matching Python property; no parser/decoder change needed |

**None of these six cases is "inappropriate for Structure."** All six are reasonable things a real
de-identification/routing policy would want to express (the README's own worked example already
treats Pixel Data as a first-class policy line item -- "passthru (7FE0,0010)" -- distinct from the
ordinary remove/hash/preserve actions applied to metadata, which independently confirms the product
has always conceived of Pixel Data as its own policy category rather than an ordinary locator
target). What varies is *how much new plumbing* each needs: three need none (presence/routing, via
a structure-side check against the already-frozen `pixel_data_kind`), one needs a small additive
attrs change (size), and one needs real, unscoped attrs design work (removal).

## 6. Would Structure need an undesirable special case?

**Only if the special case is built inside `resolve_locator` itself -- which it should not be.**
Evaluating the tempting shape directly:

```python
if locator.tag == (0x7FE0, 0x0010):
    use structure.pixel_data_kind / special Pixel Data API
else:
    use resolve_locator()
```

This would **damage** Locator V1's abstraction, for reasons this investigation can now state
precisely rather than by preference alone:

1. **It would embed DICOM semantic knowledge Structure was built specifically not to own.** S1.1's
   own invariant (`S1_1_LOCATOR_MODEL_REPORT.md`, section 4) is "no DICOM semantic reimplementation
   ... never infers VR ... never resolves a private creator." Hard-coding the one tag attrs happens
   to store specially is exactly that category of knowledge -- it requires Structure to know
   something about DICOM's tag space (which coordinate is magic) that today it correctly does not
   need to know at all.
2. **It would not generalize.** The Contract gap analysis (section I, "SHOULD") already flags that
   attrs' *general* zero-copy treatment is currently Pixel-Data-specific with "no API to ask 'is
   this bulk data' for an arbitrary tag" -- meaning if attrs ever extends the same by-reference
   treatment to another large-value tag (a waveform, an overlay, a large private blob), a
   tag-equality special case in `resolve_locator` would need a second hard-coded branch, then a
   third, forever trailing attrs' own bulk-data surface one tag at a time.
3. **It would break "one locator resolution engine."** S1.1's central architectural claim is that
   every locator kind resolves through exactly one function. A tag-keyed branch reintroduces
   per-tag special-casing at the one place S1.1 was authorized specifically to eliminate it (recall
   `AllowListPrune`'s retired `_collect_tags` was rejected for the same reason: a second traversal
   path competing with the one canonical one).

**Your default preference holds, and inspection strengthens rather than weakens it**: Structure
locators should not need to know which tags attrs stores specially, and nothing about attrs' actual
design argues otherwise -- attrs itself keeps Pixel Data behind a *named*, separate accessor
(`pixel_data()`) precisely so that ordinary consumers (`find`, `visit`/`iter_elements`) never need a
special case for it either. Structure mirroring that same separation with its own distinct concept
(not a Locator, not a branch inside `resolve_locator`) is following attrs' own pattern, not fighting
it.

## 7. Options

**Option A -- leave attrs unchanged; document the limitation.**
Pixel Data stays outside attribute discovery entirely; `policy.py` documents (as
`S1_1_LOCATOR_MODEL_REPORT.md` already does) that no locator can target it. *Conceptual
cleanliness*: high -- zero new surface anywhere. *Compatibility risk*: none. *Implementation scope*:
zero (already the current state). *A1 frozen guarantees*: untouched. *ABI/Python implications*:
none. *Writer fidelity*: untouched. *Materialization risk*: none (nothing changes). *Locator V1
impact*: none. *Future policy usefulness*: **low** -- "Remove Pixel Data," "reject if present," and
"report size" all stay unimplementable or require the caller to bypass `policy.py` and hand-roll a
`pixel_data_kind` check outside the declarative model this repository exists to provide.

**Option B -- add a narrow attrs presence/reference API for bulk data; Structure gets a distinct
future bulk-data policy concept, not a Locator.**
Concretely: (a) no attrs change needed at all for presence/routing (`pixel_data_kind` already
answers "Require presence," "reject if present," "route by kind"); (b) a small, additive ABI/Python
extension exposing `native_span().length()` and fragment lengths (new fields alongside `kind`, or a
new small struct) would additionally answer "report size without reading payload"; (c) Structure
would introduce a new, explicitly-named policy concept -- e.g. a future `PixelDataPolicy`/bulk-data
predicate, deliberately **not** a `Locator` subtype -- for `Require`/`Reject`-shaped presence and
kind checks, keeping `resolve_locator` exactly as narrow as it is today. *Conceptual cleanliness*:
high -- each layer keeps owning exactly what it already owns; no tag-keyed branching anywhere.
*Compatibility risk*: low -- purely additive ABI functions/struct fields, no existing signature
changes. *Implementation scope*: small for (a)/(new policy concept), small-to-moderate for (b) (new
ABI function(s), new ctypes declarations, new Python property/dataclass, new tests) -- but this
review does not scope it precisely; that is design work for whenever it is authorized. *A1 frozen
guarantees*: unaffected -- A1 froze the *existing* surface; adding new, additive functions doesn't
reopen it, though it would need its own authorization and freeze discipline, mirroring A1's own
increments. *ABI/Python implications*: new symbols only, nothing existing changes shape. *Writer
fidelity*: unaffected (read-only additions). *Materialization risk*: none -- every new field
proposed here is already computed without touching pixel bytes. *Locator V1 impact*: **zero** --
this is the point. *Future policy usefulness*: **high** -- closes all six cases in section 5 except
"Remove Pixel Data," which is a materially bigger, separate question this option does not resolve.

**Option C -- make Pixel Data semantically discoverable through attrs' ordinary find/iteration
model, retaining payload-by-reference semantics.**
This would require extending `Element`'s content variant to a third alternative (today exactly two:
`Value` or `Sequence`) carrying something `PixelDataReference`-shaped, then teaching `find`,
`visit`/`iter_elements`, `erase_if` (and everything that pattern-matches `is_sequence()`/`value()`/
`sequence()`, including the Python binding's `Element.is_sequence`/`.value`) to handle a third case
that has neither a scalar value nor sequence items in the ordinary sense. *Conceptual cleanliness*:
**low** -- it reopens exactly the "one concept, not two" tension the current design deliberately
avoided (section 1), now as "one concept, not three," for a single tag that behaves unlike every
other element in the structure (it can never be `set_value`d, `insert`-adjacent, or read via
`.value()`, so callers would still need a runtime check before treating it like a normal element --
the special case would move, not disappear). *Compatibility risk*: **high** -- `Element` is a
frozen, central type; every consumer of `is_sequence()` and `.value()` across both repositories
(and the ABI's own generation-counter/staleness model) would need to account for a state that is
neither. *Implementation scope*: large -- C++ `Element`, `visit`/`find`/`erase_if`, the writer's
interleaving logic (currently keyed off `pixel_data_position()`, would need rethinking), the ABI,
and the Python binding all touched. *A1 frozen guarantees*: **would require reopening A1's frozen
`Element`/`DICOMStructure` contract** -- a materially bigger decision than this review's scope.
*Writer fidelity*: at risk of regression during the transition (A1.3's ordering fix is entangled
with the current separation). *Materialization risk*: **real** -- any code path that currently
assumes "not a sequence implies has a `Value`" (e.g. Python's `Element.value` property, which always
calls `ctypes.string_at` to copy bytes into a Python `bytes` object) would need an explicit new guard
everywhere, and a missed one would silently materialize Pixel Data through an existing call site.
*Locator V1 impact*: would make Pixel Data locator-targetable "for free" once `iter_elements`
surfaced it -- but at a cost this review assesses as disproportionate to that one benefit. *Future
policy usefulness*: high in principle, but achievable more cheaply and more safely via Option B.

**Option D -- none better identified.** Sections 1-6 did not surface an architecture superior to B
for the near term. A hybrid is worth naming explicitly since it is not quite A, B, or C: **do
nothing now, revisit only if/when a second bulk-data-shaped tag (e.g. a large private OB blob a
caller wants routed without reading) makes a *general* "is this bulk data" concept (the Contract's
own flagged SHOULD) worth building before a Pixel-Data-specific one** -- i.e., prefer designing
Option B's future policy concept generically ("bulk data reference metadata," not
"PixelDataPolicy" narrowly) if and when it is actually built, so it does not need a second
redesign the day a second such tag matters. This is a sequencing note, not a fourth architecture.

## 8. Product Capability Map P6.2 -- critical review

Current wording (as written) treats `resolve_locator` never surfacing Pixel Data as evidence for
**P6.2 Bounded resource consumption**. This conflates two different claims:

- **What is actually proven**: locator resolution cannot touch Pixel Data, because Pixel Data is
  outside the graph `resolve_locator` walks. True, tested
  (`test_pixel_data_target_never_resolves_and_never_materializes`), and worth keeping as evidence.
- **What P6.2 as a capability implies**: that the system can *reason about* Pixel Data's resource
  footprint efficiently when a policy actually needs to (size-based routing, conditional handling
  based on how large the payload is, bounding memory for a metadata-plus-selective-Pixel-Data
  operation). **None of that is demonstrated.** The system cannot currently even report Pixel Data's
  byte length (section 4) -- it isn't that resource reasoning about Pixel Data is *proven bounded*,
  it's that Pixel Data is currently *invisible*, which trivially (and vacuously) prevents Locator V1
  specifically from mismanaging it. A program that never opens a file cannot leak its file handle
  either; that is not evidence the program manages file handles well.

**Recommended corrected wording for P6.2's evidence column** (not applied -- for whoever edits the
map next):

> `tests/python/test_locator.py::test_pixel_data_target_never_resolves_and_never_materializes`
> proves Locator V1 cannot touch Pixel Data, because Pixel Data is structurally outside the element
> graph it walks -- a real non-interference guarantee for locator-driven policy, but not evidence
> that this system can efficiently *reason about* Pixel Data's resource footprint. Pixel Data's
> extent (byte length) is not currently exposed past the C ABI/Python layer at all (see
> `docs/architecture/S1_1_PIXEL_DATA_DISCOVERABILITY_REVIEW.md`), so no size-aware bounding claim
> can be made yet, positively or negatively.

This does not change P6.2's status (`PARTIAL` remains appropriate), only tightens what the existing
evidence is allowed to imply.

## 9. S1.1 freeze impact

**Disposition: B -- S1.1 can freeze unchanged, but the Product Capability Map and S1.1 report
wording should be corrected first.**

Reasoning against the higher-friction options:

- **Not C** (wait for an attrs correction). Nothing about S1.1's actual, authorized scope --
  targeting *ordinary* elements via bare/concrete/wildcard locators -- depends on Pixel Data being
  reachable. `resolve_locator`'s inability to see Pixel Data is correctly documented, tested
  behavior, not a defect masquerading as a feature. Waiting on attrs work that was never in S1.1's
  scope would block an already-complete, already-correct increment on a capability nobody
  authorized S1.1 to deliver.
- **Not D** (Locator V1 itself needs revision). The threshold for this is high by design, and
  nothing found here meets it: `resolve_locator`'s refusal to special-case a tag is exactly the
  correct behavior once you know attrs itself deliberately keeps Pixel Data out of `find`/
  `iter_elements` (section 1) and its own illustrative contract shows a *separate* accessor for it
  (section 3). Section 6 shows concretely that the "obvious fix" (a tag-equality branch) would
  actively damage the abstraction, not repair it. Locator V1's boundary is correctly drawn.
- **B, not a bare A**, because this review surfaced concrete wording that is currently misleading
  (P6.2's evidence, section 8) and a report claim worth sharpening (the S1.1 report's own "Known
  limitations" section already names the Pixel Data finding correctly as a limitation, not a defect
  -- consistent with this review -- but P6.2 in the capability map overstates what that finding
  proves, and should be corrected as part of finalizing the freeze, not carried forward as-is).

**Recommended pre-freeze correction (wording only, not yet applied, per this review's own
no-implementation instruction)**: update `PRODUCT_CAPABILITY_MAP.md` P6.2's evidence text per
section 8, and consider adding one new `CANDIDATE`-status capability row (a natural home would be
under P1 or a new P1.6, "Bulk-data-aware policy: presence/kind/size targeting for Pixel Data and
similar large values") so this review's Option B has a place to be tracked once/if authorized --
that row itself is a documentation addition, not a code change, and is left to the next editing
pass of the capability map rather than performed here.

## Summary of answers to the ten requested points

1. **Why outside the element graph**: `Element`'s content is strictly `Value | Sequence`; `Value`
   cannot represent encapsulated Pixel Data's multi-span shape, so a uniform `PixelDataReference`
   outside the ordinary vector is the one-concept choice for both native and encapsulated forms.
2. **Deliberate?** Yes, for the C++ separation (three independent primary-source confirmations,
   section 2). The ABI/Python narrowing to kind-only is not documented as deliberate anywhere found.
3. **Contract classification**: **A** at the C++ design layer (the contract's own illustrative model
   already shows a separate `pixel_data()` accessor); **C** at the ABI/Python layer (the contract's
   "expose location/extent" MUST is only partly delivered -- kind only, not length or position).
4. **What's exposable without materializing**: tag, presence, VR, encapsulation kind, and extent
   (length, native or per-fragment) are all already computed safely in C++; only kind currently
   crosses the ABI/Python boundary.
5. **Does future policy reasonably need to target it?** Yes -- presence/reject/route/report-size are
   all reasonable, three of five already possible today with zero attrs change (via a structure-side
   check, not a Locator), one needs a small additive attrs change (size), one (removal) needs real,
   unscoped attrs design work.
6. **Would Structure need an undesirable special case?** Only if built inside `resolve_locator`
   (section 6) -- which would violate S1.1's own no-DICOM-semantics and one-engine invariants and
   would not generalize to future bulk-data tags. A separate, explicitly-named bulk-data policy
   concept avoids this entirely.
7. **Options**: A (status quo, low future usefulness) / B (narrow additive attrs API + a distinct
   Structure bulk-data policy concept, recommended) / C (fold into the element graph, high risk and
   cost for one tag) / D (no better alternative found; sequencing note toward a general "bulk data"
   concept if a second such tag ever matters).
8. **Recommended architecture**: Option B, deferred (not authorized here) -- keep `resolve_locator`
   exactly as narrow as S1.1 built it; if/when authorized, add narrow, additive, non-materializing
   ABI/Python accessors for Pixel Data's already-computed metadata, and give Structure a distinct,
   non-Locator policy concept for it.
9. **Corrected P6.2 wording**: proposed in section 8 -- separates "locator resolution cannot
   interfere with Pixel Data" (proven) from "the system can efficiently reason about Pixel Data's
   resource footprint" (not demonstrated; extent isn't even exposed yet).
10. **S1.1 freeze disposition**: **B** -- freeze unchanged after a wording-only correction to
    `PRODUCT_CAPABILITY_MAP.md` (P6.2, and optionally a new tracked `CANDIDATE` capability row for
    future bulk-data policy). No attrs change, no Locator V1 change, no S1.2 work implied or begun.

---

No production code in either repository was changed to produce this review. No attrs file was
modified. `fastdicomstructure/policy.py`, `tests/python/test_locator.py`, and
`tests/python/test_policy.py` are unchanged from S1.1's already-reported state.
S1.2 was not started.
