# S1.2 Design Checkpoint — Charset-Aware Replace + Ensure

**Status: ANALYSIS AND DESIGN ONLY.** No production code in this repository, and no file in
`fastDICOMattrs`, was modified to produce this checkpoint. Every attrs capability cited below was
verified directly against frozen `46bf7d3` source (headers, `.cpp` files, ABI mapping tables) or the
A1.5/A1.6/A1.7 freeze reports — nothing here is designed from memory. S1.2 is **not implemented** by
this document; it settles the semantic contract implementation must satisfy.

## 1. Executive verdict

**READY**, with one genuine, load-bearing, and cleanly-scoped attrs gap (no Sequence/Item creation
primitive exists — section 25) that determines the "no structural synthesis" rule rather than
merely supporting it as a preference. Every other design question below resolves cleanly against
already-frozen attrs primitives, with no attrs change needed and no Locator V1 change needed. The
recommended public vocabulary (`ReplaceText`, `Ensure`, `EnsureText`, alongside unmodified `Replace`)
mirrors attrs' own already-frozen `set_value`/`set_text`/`insert`/`insert_text` split exactly —
naming symmetry one layer up, not an invented pattern. Operation atomicity for the newly-fallible
operations is achievable today, without any attrs change, via a mutate-with-guaranteed-rollback
strategy proven safe by attrs' own documented all-or-nothing single-call contract (section 16/17).

## 2. Frozen starting state

| Item | Value |
|---|---|
| fastDICOMstructure | S1.1 FROZEN at `bdc324cfe5b71c7080d7efee8d745186d7020366`, 48/48 tests passing |
| fastDICOMattrs | A1 progression COMPLETE, frozen at `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6` |
| Primary capability established | P1.3 (Nested/pattern targeting): `CURRENT` |
| Relevant frozen attrs reports read in full for this checkpoint | `A1_5_CHARACTER_SET_CONTEXT_AND_DECODING_REPORT.md`, `A1_6_CHARACTER_SET_REENCODING_REPORT.md`, `A1_7_MUTATION_ERGONOMICS_AND_PUBLIC_API_REPORT.md` |
| Verified directly against source (not the reports' prose alone) | `dicom_structure.hpp`/`.cpp`, `element.hpp`, `mutation.cpp`, ABI status-mapping table (`abi/src/*.cpp`), Python `__init__.py`'s `insert`/`insert_text`/`set_text`/`decode_text` signatures |

## 3. Existing attrs primitives actually available (verified, not assumed)

**Structural insertion** — `DICOMStructure::insert(parent, tag, vr, value)` / Python
`Structure.insert(tag, value, vr=None, parent=None)`: `parent` is a **container locator** — every
step (no exception for the last) must resolve to an existing Sequence Item; empty/`None` names the
root. Rejects `vr in {SQ, Unknown}` (`dicom_structure.cpp:243`, confirmed by direct read) — **there
is no way to insert a new Sequence element or a new Item via this or any other primitive** (see
section 25). Duplicate-tag check scans the *entire* target container, not just the first match
(`for (const auto& e : *loc.container) if (e.tag() == tag) return false;`) — this differs from
lookup's first-match convention (below). Raises (`AlreadyExistsError`, `VRRequiredError`,
`FdsError`) rather than returning `bool` — confirmed both in `dicom_structure.hpp`'s doc comment and
by reading `__init__.py`'s exception model directly.

**Structural lookup/update** — `find`/`set_value`/`erase` (path-capable since A1.7, root-capable
since before): return `None`/`False` on absence, never raise. Container/element resolution
(`locate()` in `dicom_structure.cpp`) takes the **first** tag match at each level of a path and
stops (`for (j...) if (tag matches) { found; break; }`) — verified directly; a non-canonical
duplicate tag within one container is structurally invisible beyond its first occurrence to *every*
path-based primitive, not a new S1.2 concern.

**VR inference** (`fds::internal::infer_vr`, reached via `insert(vr=None)`/`insert_text(vr=None)`):
unambiguous dictionary VR → inferred; PS3.6 `VRAmbiguity != None` → `VRRequiredError`; tag absent
from dictionary → `VRRequiredError`; private (odd-group) data element → `VRRequiredError` always;
Private Creator declaration (odd group, element `0x10`–`0xFF`) → inferred `VR::LO` (a normative
PS3.5 fact, not a dictionary guess). Verified against A1.7 section 8 and the frozen Python
signature.

**Charset-aware text** — `resolve_character_set_context`/`decode_text` (A1.5, read-only,
element-locator-shaped), `encode_text`/`set_text`/`insert_text` (A1.6/A1.7, write direction).
**Freeze-critical, independently verified fact**: `insert_text`'s charset context is resolved *at
the target's intended parent container*, via a dedicated `resolve_character_set_context_for_container`
internal path (A1.7 section 10) — proven by a differential test that reverted to the naive
element-locator walker and confirmed 3 of 6 scenario tests then failed exactly as predicted. This is
not something S1.2 needs to build, work around, or re-verify; `structure.insert_text(...)` already
does it correctly. `(0008,0005)`'s own VR is `CS`, not one of the seven text-governed VRs — `set_text`
on it returns `NotATextVR` (mapped to a plain `FdsError`, see below) automatically, with zero
special-casing anywhere; **no dataset-wide transcode operation exists at any layer** (A1.6 section
19, explicit, deliberate, permanent boundary).

**Atomicity, verified directly**: every one of `insert`, `insert_text`, `set_text` "validates
everything... before touching `structure` at all; a single mutation call happens only on total
success" (A1.7 section 12) — and a *failed* (exception-raising) call does **not** bump the Python
generation counter (A1.7 section 16), meaning a failed call is a true, zero-side-effect no-op, not
merely "probably harmless." This single fact is what makes S1.2's atomicity design possible without
any attrs change (section 16).

**ABI status mapping, verified by direct read of `abi/src/*.cpp`**: `SetTextStatus::NotATextVR` →
`FDS_STATUS_UNSUPPORTED` → (no Python subclass registered) → plain `FdsError`.
`PathNotFound`/`ContainerNotFound`/`NotASequence`/`ItemIndexOutOfRange` → `FDS_STATUS_NOT_FOUND` →
plain `FdsError` (Python's `set_text`/`insert_text` have **no** bool-return "not found" convention
at all — they raise for *every* non-`Success` status, including simple absence). `set_value`, by
contrast, still returns `False` for not-found. This asymmetry is real, verified, and shapes section
21's failure model directly.

**No exposed encode-without-mutating primitive.** `encode_text()` (pure, C++-only, takes no
`DICOMStructure`) is never bound to Python or the ABI (confirmed: A1.6 section 31, and absent from
the A1.7 section 20 Python API inventory). This is the one place a caller cannot "try before
touching" via a dedicated primitive — addressed in sections 16–17 without needing one.

## 4. S1.2 scope

**In scope**: charset-aware text replacement (`ReplaceText`) and set-or-insert semantics (`Ensure`,
`EnsureText`) for `TagLocator`/`PathLocator` (concrete and wildcard), built entirely on the
primitives in section 3. **Primary capability advanced**: P1.2 (Mutation policy). **Materially
enables, does not complete**: P1.4 (de-identification — section 22 is a design probe, not new
scope), P2 (declarative configuration — section 23 is a JSON-authorability proof, not a loader).
**Explicitly excluded** (per the authorization's own list): JSON loader/schema/CLI/adapters/
streaming/C-STORE/DICOMweb/database/cloud/container/Evidence Packet/creator-aware
`PrivateTagPolicy`/bulk-data policy/Pixel Data mutation/generalized conditions/a DICOM
de-identification profile/attrs changes/new charset repertoire/transcode/the S1.3 diagnostic
redesign.

## 5. Replace semantic contract

**Unchanged from S1.1.** `Replace` keeps its exact raw-bytes contract (zero matches → no-op; N
matches → N replaced; bare-tag `recursive=True` + callback still forbidden). S1.2 adds a sibling
operation, `ReplaceText`, rather than extending `Replace` — see section 13 for why.

## 6. Ensure semantic contract

`Ensure(locator, value)` / `EnsureText(locator, values)`: for every **insertion site** the locator's
structural shape resolves to (section 7) —

- site's target already exists → **update** it (`set_value`/`set_text`), exactly like `Replace`.
- site's target absent, but its immediate parent container concretely exists → **insert** it
  (`insert`/`insert_text`).
- no concrete parent container can be established (missing Sequence, wrong Item index, non-SQ
  intermediate) → that site does not exist at all; **nothing is synthesized**.

This is the accepted default rule from the authorization, confirmed rather than merely adopted: it
follows directly from attrs itself having no primitive to create a Sequence or Item (section 25) —
Structure could not synthesize structural ancestors even if it wanted to, without duplicating
DICOM-structural-construction logic attrs deliberately does not expose. The rule is therefore not
just a policy preference but the only rule consistent with "no DICOM semantic reimplementation in
Structure."

**`Ensure` is genuinely distinct from `Replace`**, not `Replace` with a flag: `Replace` answers "if
this is already there, change it" (absence is always a legitimate, silent no-op); `Ensure` answers
"guarantee this value is present here" (absence is only a no-op when no concrete site could be
established at all — section 21). This mirrors attrs' own explicit rejection of a combined
upsert primitive (A1.7 section 5: `upsert()` was designed, then deleted, specifically because
"insert-or-replace" ambiguously conflates two decisions) — `Ensure` does not repeat that mistake:
it is the same explicit two-call composition attrs' own documentation recommends
(`if (structure.find(path)) structure.set_value(path, value); else structure.insert(...)`),
generalized across `TagLocator`/`PathLocator`/wildcard by one operation, not a new fused primitive.

## 7. Locator vs. insertion-parent resolution

**No change to the public `Locator` vocabulary.** `TagLocator`/`PathLocator`/`LocatorStep` are
unchanged. What is needed is a second, **internal-only** resolution mode alongside
`resolve_locator`, answering a different question:

```python
@dataclass(frozen=True)
class InsertionSite:
    parent: ElementPath   # attrs container-locator shape; [] means root
    tag: Tag
    exists: bool          # whether the leaf is already present at this site
    target_path: ElementPath  # parent + [(tag, None)] -- valid whether or not `exists`

def resolve_insertion_sites(structure, locator) -> list[InsertionSite]: ...
```

This is not a second locator language and not a second traversal engine: `PathLocator`'s wildcard
expansion in `resolve_locator` already computes, as an intermediate value, the full set of
surviving `prefixes` (candidate parent containers) *before* filtering to just the ones where the
leaf exists. `resolve_insertion_sites` is that same step-expansion, with the existence check turned
into a tag on each surviving prefix instead of a filter. `resolve_locator`'s implementation can be
refactored to share this core with `resolve_insertion_sites` (a private helper both call) without
changing either function's public behavior or `resolve_locator`'s signature — an internal-only
change, not a Locator V1 redesign. `TagLocator` gets its own small, direct handling (section 8),
not routed through the same step-expansion (it has no steps to expand).

`Locator V1` still answers *where is the target*; `resolve_insertion_sites` answers *where may a
missing final element be created*, using exactly the same non-DICOM-semantic primitives
(`find`/`is_sequence`/`items()`) `resolve_locator` already uses — no new attrs surface, no VR/
charset inspection at resolution time.

## 8. TagLocator semantics

- **Root-only (`recursive=False`), including the bare-tag default for `Ensure`/`EnsureText`
  specifically (see below)**: exactly one insertion site, `parent=[]` (root, always "exists" as a
  container), `exists = tag in structure`. Unambiguous, matching the authorization's own expectation.

- **Recursive (`recursive=True`)**: **update every existing occurrence; never insert.** If zero
  occurrences exist, the result is a genuine no-op (zero matches, zero inserted) — not an error, not
  a silent root-insertion. Reasoning, addressing the authorization's explicit instruction not to
  decide this from backward compatibility (there is none to preserve): "this tag, at any depth, in
  any container shape" does not name a single container the way `recursive=False` (root) or a
  `PathLocator` (an explicit step chain) does — there is no well-defined answer to *which* container
  a new occurrence would belong to. The authorization's own alternative ("insert at root only if
  none exist") was evaluated and rejected: it would insert into a location (root) the caller never
  named, purely because a search elsewhere came up empty — exactly the kind of implicit, surprising
  default the authorization warned against, and inconsistent with every other locator kind's
  insertion rule, which only ever inserts into a container the locator's own shape concretely names.

- **Consequence for `Ensure`'s bare-tag default**: unlike `Remove`/`Replace` (whose bare-tag default
  is `recursive=True`, preserving `erase_recursive`/`set_value_recursive`'s pre-S1.1 legacy scope),
  **`Ensure`/`EnsureText`'s bare-tag default is `recursive=False`** — deliberately different, and
  deliberately *not* chosen for compatibility (there is none for a new operation): root-only is the
  only scope with a single, unambiguous, always-establishable insertion site, and it is exactly the
  right default for the de-identification stress case's own examples (`PatientIdentityRemoved`,
  `DeidentificationMethod` — both PS3.6 top-level-only attributes; section 22). A caller wanting
  update-only behavior across every existing nested occurrence, with no insertion risk, passes an
  explicit `TagLocator(tag, recursive=True)`.

## 9. Concrete PathLocator semantics

For `SequenceA[2]/SequenceB[0]/Target`, the five scenarios collapse to two outcomes, mirroring
S1.1's own zero-match reasoning exactly:

| Case | Outcome |
|---|---|
| A. target exists | one `InsertionSite(exists=True)` → **update** |
| B. target absent, complete parent resolves | one `InsertionSite(exists=False)` → **insert** |
| C. intermediate Sequence missing | **no site at all** (empty result) |
| D. requested Item missing | **no site at all** |
| E. intermediate element exists but is not SQ | **no site at all** |

C/D/E deliberately collapse into one outcome (no insertion parent could be established) for the
same reason S1.1 collapsed the analogous zero-match causes: distinguishing *why* no site exists is
a diagnostic-richness question (S1.3), not a resolution-correctness question this function needs to
answer differently case-by-case.

## 10. Wildcard PathLocator semantics

`BeamSequence[*]/PatientIdentityRemoved` against 5 Items: `resolve_insertion_sites` enumerates all 5
Items (deterministic index order, exactly as `resolve_locator`'s wildcard expansion already does),
producing 5 `InsertionSite` records — one per Item, each independently `exists=True` or `False`
depending on whether that specific Item currently carries the tag. **A missing leaf never
eliminates an otherwise-valid site; a missing/wrong-shaped intermediate ancestor does** (that
branch never reaches the point of producing a candidate prefix at all — same step-expansion logic
as `resolve_locator`, section 7). No DICOM parsing/VR/charset semantics are consulted at this
stage — only `find`/`is_sequence`/`items()`, exactly as `resolve_locator` already restricts itself
to.

## 11. Mixed existing/missing targets

`Sequence[*]/Target` with Item 0 present, Item 1 absent, Item 2 present, Item 3 absent produces,
in order: update(0), insert(1), update(2), insert(3) — exactly the authorization's proposed model,
confirmed rather than merely adopted, against each named criterion:

- **De-identification**: this is precisely "ensure a marker exists in every Item of an existing
  Sequence" (section 22) — one operation, no separate Require/Insert-shaped composition needed.
- **Configuration simplicity**: one JSON `ensure`/`ensure_text` action with a wildcard path
  expresses the full mixed sweep (section 23) — no branching JSON needed for "if present" vs. "if
  absent."
- **Callback/value generation**: literal-value-only for V1 (section 18) sidesteps the question of
  what a callback would receive for an insert-site with no prior value — deliberately not solved
  here.
- **Failure handling**: since a literal value applies identically everywhere, the only per-site
  failure mode is an attrs-level one (VR/charset/length), handled uniformly by the atomicity design
  (section 16) regardless of whether that site was an update or an insert.
- **Future audit reporting**: a literal value trivially reports "value applied at N sites" without
  needing per-site value tracking yet; S1.3 can add per-site detail later without changing this
  contract.

No alternative was found preferable to the authorization's own proposed model.

## 12. VR semantics

Directly delegated to `fds::internal::infer_vr` via `insert`/`insert_text`'s `vr=None` (verified,
section 3) — **Structure infers nothing itself**. Mapping, confirmed against A1.7 section 8 and the
frozen Python exception model:

| Case | Behavior |
|---|---|
| Explicit VR supplied | used exactly, subject to attrs' own validity rules (`InvalidVR` on a bad choice) |
| VR omitted, unambiguous dictionary entry | inferred |
| VR omitted, ambiguous dictionary VR | `VRRequiredError` |
| VR omitted, tag absent from dictionary | `VRRequiredError` |
| VR omitted, private (odd-group) data element | `VRRequiredError`, always |
| VR omitted, Private Creator declaration (odd group, `0x10`–`0xFF`) | inferred `VR::LO` |

`Ensure`/`EnsureText` accept an optional `vr` parameter (default `None` = infer), passed straight
through to `insert`/`insert_text` on the insert branch; **on the update branch `vr` is irrelevant
and ignored** — `set_value`/`set_text` always preserve the existing element's own VR (attrs'
documented behavior, unchanged), exactly like `Replace` already does.

## 13. Raw vs. text operations — the API decision

**Recommendation: separate, explicitly-named operation classes — `Replace` (raw, unchanged),
`ReplaceText` (new), `Ensure` (raw, new), `EnsureText` (new) — not a single polymorphic operation
dispatching on Python's `bytes` vs. `str` type.**

This is not an arbitrary stylistic choice: it is attrs' own already-frozen, already-battle-tested
convention, verified directly from the Python API (`insert(tag, value: bytes, ...)` and
`insert_text(tag, values: Union[str, Sequence[str]], ...)` are two separately-named functions, not
one dispatching on argument type), and stated as a deliberate principle in A1.7's own audit (section
28: "**Raw/text ambiguity** — none; `bytes` vs. `str`/`Sequence[str]` is the only signal, never
content-sniffed" — describing *why two names*, not why one name with type-sniffing). The
authorization's own instruction ("Do NOT create an API that guesses whether Python bytes/str means
raw or semantic behavior in surprising ways") is fully satisfied by mirroring this precedent one
layer up: Structure's operation *class name* is the discriminator (matching attrs' *function name*
being the discriminator), never a runtime type inspection inside one class. Four operation classes,
symmetric with attrs' own four entry points (`set_value`/`set_text`/`insert`/`insert_text`), is the
smallest vocabulary that avoids guessing — collapsing to fewer would reintroduce exactly the
ambiguity attrs itself rejected; more would be unjustified surface for no additional distinction.

## 14. Character-set context

For every text operation, context resolution is **entirely attrs' responsibility, already proven**:
`ReplaceText`/`EnsureText`'s update branch calls `structure.set_text(path, values)`, which resolves
context via A1.5's element-locator walker (root inheritance, nested override, sibling isolation all
already proven — A1.5 section 6-7, A1.6 section 18). `EnsureText`'s insert branch calls
`structure.insert_text(tag, values, vr=vr, parent=parent_path)`, which resolves context at the
**parent container** via the dedicated, differentially-tested `resolve_character_set_context_for_container`
path (A1.7 section 10) — the freeze-critical distinction the authorization named, verified already
solved, not re-solved here. **Structure duplicates none of this logic** — it only ever calls
`set_text`/`insert_text` and interprets their status/exception, exactly as `resolve_locator`
duplicates none of attrs' traversal logic.

## 15. SpecificCharacterSet handling

`(0008,0005)`'s VR is `CS`, outside the seven text-governed VRs (A1.5 section 8, A1.6 section 19,
both verified). `ReplaceText`/`EnsureText` targeting it will reach attrs' `set_text`/`insert_text`
and receive `NotATextVR` → a plain `FdsError` (section 3's ABI mapping) — **with zero special-casing
in Structure**, and this must remain true: no code path in S1.2 may special-case `(0008,0005)`, and
none needs to. **Explicitly, repeatedly documented**: changing this element via `ReplaceText`
(should a caller do it via `Replace`, raw bytes, which *would* succeed since `Replace` never
consults text-VR-ness) **does not transcode any other element in the dataset** — no such operation
exists at any layer (A1.6 section 19, a deliberate, permanent boundary), and S1.2 introduces
nothing that could be mistaken for one. This must be stated plainly in the eventual public
docstring for `Replace`/`Ensure` (not just this checkpoint) to prevent a caller from assuming
"replacing the charset declaration re-encodes existing text" — it does not, and never will, without
a materially different, unauthorized capability.

## 16. Atomicity — decision and mechanism

**Decision: operation-atomic**, matching the authorization's stated default preference, achieved
without any attrs change.

**Why true preflight-without-any-mutation is not available via frozen Python/ABI** (stated plainly,
per the instruction not to answer "TBD" where a real fact settles it): `encode_text()` — the one
genuinely pure, non-mutating validation primitive C++ has — is never exposed past the ABI (section
3). VR-ambiguity is resolved only inside `insert`/`insert_text`'s own internal call to `infer_vr`;
there is no standalone, Python-reachable "would this VR be ambiguous" query either. So a classic
"validate every target first, touching nothing, then commit all" pipeline cannot be built purely
from read-only attrs calls for the *text-encoding* or *VR-inference* dimensions specifically.

**Why operation-atomicity is achievable anyway, and provably safe**: every individual `set_text`/
`insert_text`/`insert` call is *itself* already atomic and side-effect-free on failure (section 3 —
verified, not assumed: a failed call does not bump the generation counter, and A1.7 section 12/17
confirm nothing is touched before total success). This means "attempt the real mutation" and
"preflight-probe it" are the *same safe action* — a failed attempt costs nothing to have tried.
Structure therefore achieves operation atomicity via **mutate-with-guaranteed-rollback**, not
validate-then-commit:

1. Resolve every target/insertion site up front (`resolve_locator`/`resolve_insertion_sites`), a
   pure read — no mutation yet.
2. Apply mutations one site at a time, in the same deterministic order sites were resolved,
   recording an **undo action** for each site *immediately after it succeeds*:
   - update site: capture the pre-mutation value (`element.value` for raw, `decode_text(path)` for
     text) **before** calling `set_value`/`set_text`; on success, record `("restore", path,
     original_value)`.
   - insert site: on success, record `("erase", target_path)`.
3. If any site's mutation fails (an attrs exception, or — for raw `set_value` specifically, which
   returns `False` rather than raising — a `False` return treated as failure), **roll back every
   already-applied site in reverse order** using the recorded undo actions, then propagate the
   original failure.
4. If every site succeeds, the undo log is simply discarded.

**Why the rollback itself cannot fail**: a `("restore", path, original_value)` entry replays
`set_value`/`set_text` against a path that, moments earlier, held exactly that value with exactly
that VR/length-form — nothing about the element's shape changed in between (only the operation's own
single prior mutation touched it), so restoring is guaranteed to succeed by the same contract that
let the forward mutation succeed. A `("erase", path)` entry removes a path that was, moments
earlier, freshly and successfully inserted by this same operation and touched by nothing else since
(single-threaded, synchronous execution, no concurrent mutation) — `erase` on a path just proven to
exist cannot spuriously fail. This is a provable safety argument from attrs' own documented
contracts, not an assumption.

**Scope of this mechanism**: applies to the newly-fallible operations this increment introduces
(`ReplaceText`, `Ensure`, `EnsureText`). **S1.1's existing raw `Remove`/`Replace` are not
retroactively given rollback machinery** — they only ever wrap attrs calls that cannot meaningfully
fail once `resolve_locator` has already confirmed a path exists (erase/set_value on a
already-confirmed, non-sequence path), so there is nothing new to make atomic, and retrofitting
frozen S1.1 operations is out of this checkpoint's scope regardless (no production code changes).

## 16a. Review correction — raw-byte rollback (accepted)

**This section records a correction accepted after this checkpoint's own review, before
implementation began. The original text above (section 16, bullet 2's "update site" line) is left
unedited as a record of what was first proposed; this section states what was actually implemented
and why the original proposal was insufficient. Read section 16 as superseded on this one point by
this section, not as a design that was ever actually built.**

**The finding**: the original proposal captured an update site's pre-mutation state by calling
`decode_text(path)` (semantic text) and, on rollback, replaying `set_text(path, saved_text)` — i.e.,
restoring through the same charset-encode path the forward mutation used. This proves *semantic*
restoration (the decoded string comes back the same) but does **not** prove *exact* restoration of
the original DICOM value representation: a decode-then-re-encode cycle may legitimately choose a
different (still valid) byte representation for the same text — a different ISO 2022 escape
placement (A1.6 section 10's own "prefer the active repertoire" policy can choose a different escape
point than the original source did — A1.6 section 21 states this explicitly as an *intentional,
documented* non-guarantee, not a bug), different padding, or simply a canonicalized form of an
otherwise-valid but non-canonical source encoding. Restoring "the same text" is not restoring "the
same bytes," and a caller who mutated a wildcard sweep and then had it fail and roll back is
entitled to expect the object is returned to *exactly* what it was, at the byte level, not merely to
something that decodes the same way.

**The correction, accepted and implemented as follows**: every update-site undo action is captured
and replayed at the **raw byte** layer, never the text layer, regardless of which forward mutation
performed the update:

- **Before** any forward mutation of an existing element (whether the operation is `Ensure`
  (`set_value`) or `EnsureText`/`ReplaceText` (`set_text`)): read `Element.value` (raw bytes) at that
  path and record `("restore_raw", path, original_raw_bytes)`.
- **Forward execution** is unchanged from section 16 — `set_text` still performs charset-aware
  semantic mutation for the text operations; only the *undo* representation changes.
- **Rollback** replays the captured raw bytes through `set_value(path, original_raw_bytes)` — the
  raw structural primitive, never `set_text` — for every kind of update site, text or raw alike.

This establishes the stronger, now-actually-implemented invariant: **a failed S1.2 operation
restores every previously-modified existing element to its exact pre-operation raw value bytes**,
independent of whatever semantic transform the forward mutation applied. Insert-site rollback is
unchanged from section 16 (`erase(target_path)`) — an inserted element has no "original bytes" to
restore; removing it entirely is already the exact correct undo.

**Rollback-failure handling, also corrected**: section 16's "why the rollback itself cannot fail"
argument is retained as the reason rollback is expected to succeed, but is no longer treated as a
license to skip checking. The implemented contract: every undo action's own return/outcome is
checked; if one unexpectedly fails, the implementation continues attempting every *remaining* undo
action (maximizing how much of the structure is actually restored) rather than aborting the
rollback pass early, and raises a narrow, S1.2-local exception (`RollbackError`, wrapping the
original forward-mutation failure as its cause, plus recording which specific undo actions did not
complete) rather than either (a) silently reporting the operation as if it had succeeded, or (b)
attempting the broader S1.3 diagnostic/result-model redesign to represent it. See the S1.2
implementation report, section 13, for the exact exception shape and the test proving the expected
normal case (rollback succeeds completely) as well as the narrower one proving a forced rollback
failure is surfaced rather than swallowed.

No other part of this checkpoint's design changed as a result of this correction — sections 6-15
and 17-30 are implemented exactly as originally proposed.

## 17. Preflight design

Per section 16: **no separate preflight *phase* is designed** — "attempt with rollback" *is* the
preflight, because a failed attrs call is definitionally a no-op. This is simpler, cheaper (no
second pass over every target), and requires no new attrs surface, unlike a genuine
validate-then-commit pipeline (which would need `encode_text` and a VR-ambiguity query exposed to
Python — a real, identified attrs gap, not pursued here per the "do not modify attrs" instruction —
see section 25 for the honest accounting). Memory cost of the undo log is `O(number of targets in
this one operation)`, holding only each site's *previous* raw/decoded value or its path — independent
of file or Pixel Data size, and discarded immediately on success.

## 18. Callback/value-factory decision

**Recommendation: `Ensure`/`EnsureText` do not support a per-site callback/value-factory in S1.2 —
literal values only.** `Replace`'s existing callback (`bytes -> bytes`, per-occurrence, receiving
that occurrence's own original value) is **preserved unchanged**; `ReplaceText` gains the direct
text-layer analogue (`Callable[[List[str]], Union[str, Sequence[str]]]`, receiving that occurrence's
own `decode_text()` output, applied per-match exactly like `Replace`'s existing pattern) — a small,
symmetric, justified extension, not new complexity. `ReplaceText` inherits the identical bare-tag
`recursive=True` + callback restriction `Replace` already has, for the identical reason (S1.1's own
rationale: that scope has no per-occurrence discovery contract independent of an explicit step
chain).

`Ensure`/`EnsureText` are different: a callback would need a *richer* signature than `Replace`'s
(something like `Optional[bytes] -> bytes`, receiving `None` for an insert-site with no prior
value) — genuinely new surface, not symmetry-for-its-own-sake. Rejected for V1 because: (1) both of
the authorization's own worked de-identification examples (`Ensure PatientIdentityRemoved="YES"`,
`Ensure DeidentificationMethod="..."`) need only a fixed literal, never a per-occurrence
computation; (2) a caller with a genuine per-occurrence upsert need can already compose it today
from existing primitives (`Require`+`Replace(callback)`+a literal `Remove`/insert sequence) without
new machinery; (3) it materially complicates the atomicity design in section 16 (a callback could
itself raise, and its failure semantics inside a rollback would need separate specification) for a
capability neither worked example needs. Matches the authorization's own instruction not to add
"callback complexity merely for symmetry."

## 19. Duplicate-target semantics

Verified directly (section 3): every attrs path-based lookup (`find`, and therefore `set_value`/
`erase`/`set_text`) resolves the **first** tag match within a container and stops; `insert`/
`insert_text` check the *entire* container and refuse if *any* matching tag exists, so a
non-canonical duplicate is correctly detected as "already there," never silently duplicated
further. Because `resolve_locator`/`resolve_insertion_sites` only ever call `find` to test
existence, **Structure inherits "first occurrence" semantics automatically, uniformly, at every
locator kind and every nesting level** — no new logic. **Recommendation: document this plainly
rather than build new duplicate-detection machinery.** Building a "reject as ambiguous" or
"update all duplicates" behavior would require Structure to enumerate and count same-tag siblings
within one container itself — a traversal capability beyond what `find`/`is_sequence`/`items()`
already give cleanly, for an edge case describing already-non-canonical input (PS3.5 prohibits
duplicate tags within one container) that neither the authorization's own worked examples nor any
S1.1 test fixture exercises. Deterministic (first-occurrence, always) beats a new mechanism built
for a case this increment has no evidence is a real product need.

## 20. Mutation ordering / path stability

Extends S1.1's own established, tested pattern (`_remove_matches`/`_resolve_and_replace`: resolve
every target to a plain path *value* first, never retain a Python `Element`/`Item` handle across a
mutation call, re-`find()` fresh each time) — proven safe there, and it generalizes directly:

- **Sibling insertion sites are independent by construction.** A Sequence's Items are each their own
  `std::vector<Element>`; inserting a new element into Item *i*'s vector cannot reallocate or shift
  Item *j*'s vector, and — critically for `Ensure` specifically — **inserting an element never adds
  or removes an Item**, so a wildcard's Item-index enumeration, computed once up front, remains
  valid for the entire operation. This is a strictly simpler ordering problem than S1.1's `Remove`
  (which had to guard against one match's deletion cascading into another's, via deepest-path-first
  ordering) — `Ensure`/`EnsureText` never delete anything, so no such cascade risk exists, and no
  ordering rule beyond "process resolved sites in their own deterministic discovery order" is
  required for correctness (kept anyway, for reproducibility/audit, matching S1.1's own
  determinism standard).
- **Never hold an `Element`/`Item` reference across a mutation call.** Each site is applied by
  re-`find()`ing (for updates, to capture the pre-mutation value) or directly calling `insert`/
  `insert_text` (which needs no prior handle at all) against a plain path value computed once during
  resolution — exactly S1.1's already-tested discipline, carried forward unchanged.

## 21. Failure/result model — S1.2 minimum, S1.3 carry-forward

**No `PolicyResult`/`OperationResult` schema change.** `Ensure`/`EnsureText`/`ReplaceText` reuse the
existing four-field `OperationResult` (`kind`, `tag`, `count`, `satisfied`) exactly as S1.1 left it:

- `count` = number of sites successfully updated-or-inserted (always `0` or the *total* site count,
  by construction of atomicity — a partially-succeeded, non-rolled-back state is unreachable).
- `satisfied` = `True` iff at least one insertion site was resolved *and* the operation committed
  (guarantee holds somewhere); `False` if zero sites could be resolved at all, **or** if the
  operation aborted mid-batch and rolled back (both surface identically — see below).

**Minimum failures S1.2 must distinguish, classified**:

| Failure | Classification | Surfaces as |
|---|---|---|
| Malformed locator (bad tag/item shape) | configuration/policy error | `MalformedLocatorError`, at construction — unchanged from S1.1 |
| Zero insertion sites resolved (no parent establishable anywhere) | valid no-op | `OperationResult(count=0, satisfied=False)` — not an exception |
| VR required, no explicit VR given | target-specific semantic failure | uncaught `VRRequiredError`, propagated from `apply()` after rollback |
| Unrepresentable text / invalid Unicode | target-specific semantic failure | uncaught `UnrepresentableCharacterError`/`InvalidUnicodeInputError`, propagated after rollback |
| Non-text VR targeted by `ReplaceText`/`EnsureText` | target-specific semantic failure | uncaught plain `FdsError` (`NotATextVR`), propagated after rollback |
| Raw `set_value` returns `False` on an update site (value too long) | attrs mutation failure | wrapped as a plain exception (no new type introduced), propagated after rollback |
| Duplicate-target ambiguity | not modeled — see section 19 | first-occurrence semantics, no error raised |

**Explicitly, deliberately deferred to S1.3** (named, not silently dropped): mapping each of these
attrs-level exceptions onto a modeled `Diagnostic`/richer `OperationResult` outcome, so a caller can
distinguish "zero sites existed" from "sites existed but the batch aborted" from a `PolicyResult`
alone, without needing a try/except around `apply()`. This is exactly the work the original
Post-A1 inventory already assigned to S1.3, not S1.2 (its own words: "Map attrs' typed mutation
exceptions... onto new `OperationResult`/`Diagnostic` outcomes for the new path/`Ensure` operations
from S1.1/S1.2, since those can now fail in ways the current five always-succeeding-on-valid-input
operations never could") — S1.2 introduces the fallible operations; S1.3 was always slated to model
their failures richly. Raising for now, exactly mirroring attrs' own A1.7 rationale for why
`insert`/`insert_text`/`set_text` raise rather than return a collapsed boolean (too many
distinguishable reasons for one bit to carry), is the honest minimum, not a shortcut.

## 22. De-identification design probe (not new scope)

Using the proposed vocabulary directly, as a probe for semantic holes — nothing here is implemented
or claimed as a standards-complete profile:

- `ReplaceText(TagLocator((0x0010,0x0010), recursive=True), "ANON")` — replaces `PatientName`
  wherever it already occurs (root or nested); never inserts one where absent (matching `Replace`'s
  existing "absence is a no-op" contract, now text-aware).
- `Ensure((0x0012,0x0062), "YES")` — bare tag, `Ensure`'s own root-only default (section 8):
  inserts `PatientIdentityRemoved` at root if absent, updates it if present. No ambiguity: this is
  exactly the PS3.6 top-level-only attribute the default was designed for.
- `EnsureText((0x0012,0x0063), "fastDICOMstructure policy X")` — same shape,
  `DeidentificationMethod`, a text VR (LO) this time, exercising the insert-branch charset
  resolution (section 14).
- `ReplaceText(PathLocator(steps=(LocatorStep(seq_tag, "*"),), tag=nested_pn_tag), lambda names:
  [n.split("^")[0] + "^ANON" for n in names])` — recursively replaces a nested `PN` field with a
  per-occurrence callback, receiving each occurrence's own decoded name components (section 18).
- `EnsureText(PathLocator(steps=(LocatorStep(beam_seq_tag, "*"),), tag=marker_tag), "REVIEWED")` —
  the mixed-existing/missing wildcard case (section 11): ensures a marker exists in every Item of an
  existing Sequence, updating where present, inserting where absent, in one operation.

No semantic hole was exposed that the design above doesn't already resolve; the probe's purpose —
finding a case the vocabulary can't express cleanly — did not surface one within this scope.

## 23. JSON-authorability proof (illustrative only, no loader)

| Python | Illustrative JSON |
|---|---|
| `Replace((0x0010,0x0020), b"DEMO")` | `{"action": "replace", "tag": [16, 32], "value_hex": "44454d4f"}` |
| `ReplaceText((0x0010,0x0010), "ANON")` | `{"action": "replace_text", "tag": [16, 16], "value": "ANON"}` |
| `Ensure((0x0012,0x0062), b"YES")` | `{"action": "ensure", "tag": [18, 98], "value_hex": "796573"}` |
| `EnsureText((0x0012,0x0062), "YES")` | `{"action": "ensure_text", "target": {"tag": [18, 98]}, "value": "YES", "vr": "CS"}` |
| `EnsureText(PathLocator(steps=(LocatorStep((0x300A,0x00B0), "*"),), tag=(0x0008,0x0090)), "YES")` | `{"action": "ensure_text", "target": {"path": [{"tag": [12298, 176], "item": "*"}, {"tag": [8, 144]}]}, "value": "YES"}` |

The `path`/`item`/`tag` shape is unchanged from S1.1's own proven mapping; only the `action`
discriminant grows by two values (`replace_text`, `ensure`/`ensure_text`) and an optional `vr`
field appears for insertion-capable actions — no new shape category, confirming S1.1's own claim
that the locator JSON mapping would not need to change for later increments. `value_hex` for raw
actions is this checkpoint's own illustrative choice (bytes have no native JSON representation);
not a committed schema decision.

## 24. Product Capability Map impact

**Primary**: P1.2 (Mutation policy) — from `PARTIAL` (raw-bytes only) toward a fuller `PARTIAL`/
`CURRENT` once implemented and tested (status change itself deferred to the actual S1.2 freeze
report, not this checkpoint, per the map's own "not an implementation backlog" rule).
**Enables, does not complete**: P1.4 (De-identification/anonymization) — remains `DEFERRED`; this
checkpoint's own design probe (section 22) is evidence the *ingredients* now compose cleanly, not
evidence a de-identification capability exists. P2.5 (Mutation-policy configuration) — remains
`PLANNED`; section 23 is design-proof only, exactly like S1.1's own JSON-authorability section, no
status change implied. P2.4 (Acceptance-policy configuration) — **no effect**; `Ensure`/`ReplaceText`
are mutation, not acceptance, operations (confirmed: the authorization's own expectation was
"possibly none"). P1.5 (Audit/results/errors) — exposes a real requirement (section 21's named
carry-forward) but does not complete it; still `PARTIAL`. **No new capability row is warranted** —
`Ensure`/`ReplaceText`/`EnsureText` are new *operations* inside the already-tracked P1.2, not a new
product capability category; manufacturing a new row for them would duplicate P1.2 without adding
information.

## 25. Genuine attrs gaps/blockers

Two, both real, both correctly out of scope for attrs modification here:

1. **No primitive to create a new Sequence element or append a new Item to an existing Sequence, at
   any layer.** Verified directly: `DICOMStructure::insert`/`set`, and `fds::mutation::insert`,
   explicitly reject `VR::SQ`; no `add_item`/`create_sequence`/equivalent function exists anywhere
   in `include/`/`src/` (confirmed by exhaustive `grep`). This is *why* "no structural ancestor
   synthesis" (section 6) is not merely this checkpoint's policy preference but the only rule
   consistent with what attrs can actually do — Structure could not honor a "synthesize missing
   Sequences/Items" rule even if authorized to try, without duplicating Sequence/Item construction
   logic attrs deliberately does not expose. Not a blocker to S1.2 (which adopts the "no synthesis"
   rule anyway); a genuine, real limit on any *future* increment that might want richer upsert
   semantics.
2. **No non-mutating preflight primitive exposed past the C++ layer** (`encode_text()`'s pure form,
   and VR-ambiguity resolution, are both C++-internal only — section 3/16). Not a blocker to S1.2
   either, since the mutate-with-rollback mechanism (section 16) achieves the same external
   atomicity guarantee without it — named here so a future increment doesn't rediscover this as a
   surprise, and so "why doesn't Structure just preflight-validate" has a documented, verified answer
   rather than an assumed one.

Neither gap is proposed for closure in S1.2; both are recorded for visibility, per the checkpoint's
own instruction not to change attrs.

## 26. Proposed S1.2 public API (illustrative, not committed until implementation)

```python
@dataclass(frozen=True)
class ReplaceText(PolicyOperation):
    locator: Union[Tag, TagLocator, PathLocator]
    values: Union[str, Sequence[str], Callable[[List[str]], Union[str, Sequence[str]]]]
    recursive: bool = True   # same meaning/default as Replace; same callback restriction

@dataclass(frozen=True)
class Ensure(PolicyOperation):
    locator: Union[Tag, TagLocator, PathLocator]
    value: bytes
    vr: Optional[str] = None
    recursive: bool = False  # Ensure's OWN default -- root-only, not Remove/Replace's True

@dataclass(frozen=True)
class EnsureText(PolicyOperation):
    locator: Union[Tag, TagLocator, PathLocator]
    values: Union[str, Sequence[str]]
    vr: Optional[str] = None
    recursive: bool = False
```

`_normalize_locator` gains a `default_recursive` parameter already (S1.1); `Ensure`/`EnsureText`
simply pass `False` where `Remove`/`Replace` pass `True` — no change to the normalization function's
own shape. No new `Locator` types; `resolve_insertion_sites` and the rollback helper are private
module functions, not exported.

## 27. Proposed implementation decomposition

The authorization's own suggested split is sound and is adopted, with one refinement: fold the
"qualification" half of each raw/text pair into its own construction step rather than treating
qualification as a trailing phase, since S1.1's own precedent (design note → implement → qualify in
the same movement per operation) worked well and this checkpoint found no reason to depart from it.

- **S1.2a — Insertion-site resolution.** `resolve_insertion_sites`, `InsertionSite`, refactored
  shared step-expansion core with `resolve_locator` (section 7). Qualified independently of any
  policy operation, mirroring `test_locator.py`'s own precedent — the 20-scenario-style matrix from
  section 9/10/11 above, directly.
- **S1.2b — Raw `Ensure` + rollback mechanism.** `Ensure`, the mutate-with-rollback helper (shared,
  parametrized for raw vs. text — built once, used by both raw and text in 2c), VR inference
  wiring, atomicity qualification for raw insert/update mixes.
- **S1.2c — `ReplaceText` + `EnsureText` + charset qualification.** Both text operations, reusing
  2b's rollback helper unchanged; charset inheritance/override/sibling-isolation qualification at
  both the update and insert branch (proving Structure correctly inherits A1.7's already-solved
  parent-scope resolution, not re-solving it); `(0008,0005)` non-special-casing proof (section 15).
- **S1.2d — Encoding-independence, non-interference, and full-suite integration.** Explicit/
  Implicit equivalence for the new operations (mirroring S1.1's own encoding-independence test),
  Pixel Data/unrelated-element preservation, mixed-locator-kind policies combining old and new
  operations in one `Policy`, full regression against all 48 S1.1 tests.

This is the same shape the authorization proposed (S1.2a–d), confirmed rather than replaced,
because nothing in this checkpoint's analysis suggested a smaller or cleaner split — each phase
above depends on the one before it and produces independently-testable, freezable evidence, exactly
as S1.1's single-increment freeze did. **The final S1.2 implementation still freezes as one S1.2
capability increment** (a–d are an internal work-tracking convenience, not separate authorizations
or separate freeze reports), per the authorization's own instruction.

## 28. Acceptance criteria for implementation

- All 48 S1.1 tests remain green, byte-for-byte unmodified.
- Existing raw `Replace` behavior is unchanged (regression, not re-qualification).
- Root `Ensure`: update when present, insert when absent, at root only by default.
- Concrete nested `Ensure`: update/insert per section 9's A/B, no-op (not synthesized) per C/D/E.
- Wildcard `Ensure`/`EnsureText` over a mix of existing/missing leaves: update-where-present,
  insert-where-absent, in one deterministic pass (section 11), proven with a fixture carrying both
  outcomes among true siblings.
- No structural ancestor synthesis under any locator shape: proven with a missing-Sequence and a
  wrong-Item-index case, both asserting zero insertion sites and zero mutation.
- Deterministic operation order: two independent resolutions of the same wildcard `Ensure` against
  the same unmutated structure produce identical site lists, mirroring
  `test_locator.py::test_deterministic_ordering`'s own proof style.
- VR inference and VR-required cases: unambiguous standard tag, ambiguous tag, unknown tag, private
  data, and Private Creator declaration, each asserted against the exact attrs-documented outcome
  (section 12), not a Structure-invented one.
- Raw vs. semantic-text distinction: `Ensure` never charset-interprets; `EnsureText` never accepts
  raw `bytes` (a `TypeError` or equivalent at construction for a type mismatch, matching attrs' own
  "never content-sniffed" principle).
- Charset inheritance (root → nested, no local override), nested override, and sibling isolation,
  each proven for **both** the update and the insert branch of `EnsureText` — the insert branch
  specifically exercising A1.7's freeze-critical parent-scope resolution (section 14).
- Unrepresentable text and invalid Unicode: proven to leave the structure completely unchanged
  (rollback verified via a multi-site wildcard where an early site would succeed and a later one
  would fail — asserting the early site's mutation was reverted, not merely that the operation
  "failed").
- Operation atomicity: the rollback scenario above is the direct proof; additionally, a raw `Ensure`
  update-site value-too-long case proves the same rollback path for the non-text failure mode.
- Failed-operation non-interference: unrelated elements and Pixel Data unchanged after a rolled-back
  operation (mirroring S1.1's own non-interference test style, extended to the failure path
  specifically — a case S1.1 never needed since its operations couldn't fail mid-batch).
- Explicit/Implicit input equivalence: the same `Ensure`/`EnsureText` policy against equivalent
  Explicit- and Implicit-VR-origin fixtures produces the same semantic outcome, mirroring S1.1's own
  integration test.
- Unrelated element and Pixel Data preservation under `Ensure`/`EnsureText`'s successful path too
  (not just the failure path above) — mirroring S1.1's non-interference proofs exactly.
- JSON-authorability: the mapping in section 23 is re-demonstrated (not re-designed) against the
  actual implemented classes' real field names once built.

## 29. Risks / carry-forward

- **Result-model conflation** (section 21): "zero sites" and "aborted mid-batch" both surface as
  `satisfied=False, count=0`. Explicit S1.3 carry-forward, not a defect.
- **Raw `Ensure`'s update-branch `set_value`-returns-`False` case** needs *some* exception wrapping
  to fit the rollback design (section 16) since attrs itself doesn't raise there; the exact
  exception type/message is an implementation decision for S1.2 proper, not settled by this
  checkpoint (a genuine, narrow open question, distinct from the "no TBD" instruction's target,
  which was about *design facts*, not a naming choice deferred to implementation).
- **The pre-existing S1.1 `Replace` silent-swallow gap** (a raw `set_value` returning `False` for
  value-too-long is silently not counted, no exception) is *not* fixed by this checkpoint and is not
  proposed to be — noted only so the asymmetry between `Replace`'s silent tolerance and `Ensure`'s
  new exception-raising-and-rolling-back behavior for the *same* underlying attrs condition is a
  documented, deliberate difference (Ensure is new, with no legacy silent-tolerance behavior to
  preserve), not an inconsistency worth resolving by changing frozen S1.1 code.
- **Duplicate-target "first occurrence" semantics** (section 19) is inherited, not designed, and
  remains untested against a real duplicate-tag fixture in S1.1's suite — the future S1.2
  implementation should add exactly one such regression test rather than leave the claim
  unverified in code.

## 30. Recommendation

**Proceed to implementation** using the decomposition in section 27, the public API sketched in
section 26, and the acceptance criteria in section 28. No attrs change is required or recommended.
No revision to Locator V1 is required. The one genuine attrs gap (no Sequence/Item creation
primitive, section 25) is correctly absorbed by design (the "no synthesis" rule) rather than
requiring resolution before S1.2 can proceed.
