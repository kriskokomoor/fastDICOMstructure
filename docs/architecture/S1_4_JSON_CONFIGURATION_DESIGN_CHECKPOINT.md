# S1.4 Design Checkpoint — Single Declarative JSON Configuration

**Status: ANALYSIS AND DESIGN ONLY.** No production code in this repository, and no file in
`fastDICOMattrs`, was modified to produce this checkpoint. No JSON parser, schema validator,
loader, CLI, adapter, or gateway integration was built. Every claim about current behavior below
was verified by direct inspection of frozen `policy.py` (re-read in full for this checkpoint, not
recalled from memory) and, where noted, by a disposable, uncommitted Python probe.

## 1. Exact frozen repository state

| Item | Value | Verified |
|---|---|---|
| fastDICOMattrs | `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6` | `git log -1` — matches, working tree clean |
| fastDICOMstructure | `25615dd0824b1940abd7b012f69c612f61cd74c0` (S1.3 freeze) | `git log -1` — matches the stated `25615dd` exactly, working tree clean |

**No discrepancy found.** Both repositories are exactly at the stated frozen commits; analysis
proceeds from this state.

## 2. Factual inventory of the current S1.1-S1.3 public model

Read in full from `python/fastdicomstructure/policy.py` (1,555 lines) for this checkpoint, not
assumed from prior reports.

**`Policy`**: `name: str`, `version: str` (both required, no defaults), `operations:
tuple[PolicyOperation, ...]`. One flat, ordered tuple — there is no acceptance/mutation split at
the Python level today; `apply()` iterates it in list order with no operation-kind-based
reordering.

**`TagLocator(tag, recursive=True)`**: bare-tag scope form. `recursive=True` = "this tag, any
depth, any container" (via `iter_elements` + tag filter); `recursive=False` = root-only (via
`__contains__`). Two genuinely different resolution algorithms, not a special case of `PathLocator`
(verified: `resolve_locator`'s `TagLocator` branch never touches `_expand_path_locator_prefixes`).

**`PathLocator(steps, tag)`** / **`LocatorStep(tag, item)`**: `item` is a non-negative int (concrete)
or the literal string `"*"` (`ITEM_WILDCARD`, wildcard). Zero steps names a root element. Multiple
wildcard steps compose depth-first, deterministic Item-index order (0..N-1).

**Wildcard semantics** (unchanged since S1.1, re-verified by reading `_expand_path_locator_prefixes`
directly): a missing/wrong-index/non-SQ-intermediate step contributes zero prefixes past that point
(a valid empty match, not an error); a malformed locator (bad tag shape, bad Item selector) raises
`MalformedLocatorError` at **construction**, before any `Structure`/`Policy` exists.

**`Require(locator)`**: read-only (verified: `apply()` body calls only `resolve_locator`, no
mutation call anywhere). `satisfied = len(matches) > 0`. Unsatisfied → `REQUIREMENT_UNSATISFIED`
diagnostic, `Policy.apply()` stops with `execution=REJECTED`.

**`Remove(locator, recursive=True)`**: mutates via `erase`, never fails in a way that produces a
`Diagnostic` (bool-return primitive, wrapped by `_remove_matches`, which never raises). `satisfied
=None` always (no condition).

**`Replace(locator, value, recursive=True)`**: `value` is `bytes` or a `bytes -> bytes` callback.
**As of S1.3, operation-atomic** (moved onto `_apply_sites_atomically`) — a callback exception is
wrapped in `CallbackError`; `set_value` returning `False` raises `_MutationFailed`. Both propagate
as real, classified failures (`CALLBACK_FAILED`/`MUTATION_FAILED`) through `Policy.apply()`,
rolling back any already-mutated site in the same call first.

**`ReplaceText(locator, values, recursive=True)`**: `values` is `str`/`Sequence[str]` or a
`List[str] -> str|Sequence[str]` callback. Same atomicity, same callback-wrapping, plus attrs'
charset failures (`CHARACTER_UNREPRESENTABLE`, `INVALID_UNICODE`, `TEXT_OPERATION_UNSUPPORTED` for
`NotATextVR`/`UnsupportedCharset`/`MalformedCharsetDeclaration`, verified all three collapse to one
generic `FdsError`).

**`Ensure(locator, value, vr=None, recursive=False)`**: `value` is `bytes` only, **never a
callback** (`__post_init__` raises `ValueError` if `callable(value)`). Bare-tag default scope is
`recursive=False` — **different from `Remove`/`Replace`'s `True`** (verified, S1.2's own deliberate,
non-backward-compatible choice). Zero insertion sites → `satisfied=False`,
`GUARANTEE_UNESTABLISHED` diagnostic, but **does not halt the containing `Policy`** (verified by
reading `apply()`'s only halt condition: `isinstance(operation, Require) and result.satisfied is
False` — `Ensure`'s own dissatisfaction is invisible to that check).

**`EnsureText(locator, values, vr=None, recursive=False)`**: same shape, text-valued, `values` never
a callback either.

**`AllowListPrune(tags)`**: `tags: tuple[Tag, ...]` — a flat tag *set*, not a `Locator` at all (no
`.locator` attribute — verified `_operation_tag`'s `getattr(operation, "locator", None)` returns
`None` for this kind).

**`PrivateTagPolicy(remove=True)`**: a bare boolean flag, no locator, no tag.

**Callbacks**: exist on `Replace`/`ReplaceText` only, always optional (a literal is always also
valid), never on `Remove`/`Ensure`/`EnsureText`/`AllowListPrune`/`PrivateTagPolicy` (those have no
callback concept at all in frozen code).

**`OperationResult`**: `kind` (one of exactly 8 strings, matching `_OPERATION_KIND`'s values
verbatim — `"require"`, `"remove"`, `"replace"`, `"replace_text"`, `"ensure"`, `"ensure_text"`,
`"allow_list_prune"`, `"private_tag_policy"`), `tag`, `execution: ExecutionStatus`, `satisfied:
Optional[bool]`, `count`, `updated_count`/`inserted_count` (Ensure/EnsureText only),
`diagnostics: tuple[Diagnostic, ...]`.

**`PolicyResult`**: `decision: Decision` (`accept`/`transform`/`reject`/`partial`),
`execution: PolicyExecutionStatus` (`completed`/`rejected`/`partial`), `operations`, `diagnostics`,
`policy_name`, `policy_version`.

**`Diagnostic`**: `code` (one of exactly 10 `DIAGNOSTIC_CODES` strings), `severity`,
`operation_kind`, `operation_index`, `locator` (a `repr()` string, Structure-owned), `site`
(optional, Structure-owned rendering), `message` (fixed per code), `cause_type` (exception class
name only).

**attrs VR representation exposed to Structure** (verified directly from
`fastdicomattrs/__init__.py`): `_VR_NAMES` is a fixed list of 34 standard 2-letter VR codes plus the
literal string `"UNKNOWN"` (attrs' own internal sentinel meaning "infer" — `insert`/`insert_text`
map Python `vr=None` to this sentinel internally; `"UNKNOWN"` is never a valid *explicit* VR a
caller should author). `insert(tag, value, vr=None, parent=None)` / `insert_text(tag, values,
vr=None, parent=None)`: an explicit `vr` is used **verbatim, never checked against the dictionary**
(verified from the method's own doc comment: "the caller's own authoritative VR (never consulted
against the dictionary)").

**Raw byte / text-value interfaces**: `bytes` for `Replace`/`Ensure`; `str`/`Sequence[str]` for
`ReplaceText`/`EnsureText`. JSON has no native `bytes` type — this is the one representational gap
JSON must resolve or explicitly decline to resolve (section 6).

### Classification

| Behavior | Classification |
|---|---|
| `Require`, `Remove`, `ReplaceText` (literal), `EnsureText` (literal), `AllowListPrune`, `PrivateTagPolicy`, `TagLocator`, `PathLocator`, VR string | exists, suitable for JSON as-is |
| `Replace`/`Ensure` (raw `bytes`) | exists, but a real representational gap (no native JSON byte type) requiring a deliberate choice, not automatic inclusion (section 6) |
| `Replace`/`ReplaceText` callbacks | exists, **inherently non-declarative** — a Python function has no JSON form; excluded from V1 by design, not oversight (section 7) |
| Acceptance-before-mutation ordering as a *structural guarantee* | does not exist today (Python allows any order) — JSON needs to decide whether to add this as an authoring-time constraint without changing frozen `Policy` semantics (section 3) |
| Keyword tag addressing (`"PatientName"`) | does not exist at any layer (attrs has no reverse dictionary lookup exposed; Locator V1 is numeric-only) — JSON cannot offer it without a prerequisite increment neither repository has built (section 4) |
| Source/destination adapters | do not exist at all — JSON needs an extension point, not an implementation (section 9) |

## 3. Configuration Contract v1

```text
Configuration
    schema            (string, stable identifier, never changes)
    schema_version     (integer, major-only for V1 -- see section 10)
    policy             (required object)
        name           (required string -- maps to Policy.name, no Python default to mirror)
        version        (required string -- maps to Policy.version)
        acceptance     (optional array, default []  -- Require operations only)
        mutation       (optional array, default []  -- the other seven operation kinds)
    source             (optional object -- envelope only, section 9)
    destination        (optional object -- envelope only, section 9)
```

**Decisions, each argued below**: `schema`/`schema_version` required; `policy` required (a document
naming no policy at all is very likely an authoring mistake, rejected rather than defaulted to a
no-op); `policy.name`/`policy.version` required (mirrors `Policy`'s own frozen dataclass, which has
no default for either); `policy.acceptance`/`policy.mutation` each optional, defaulting to an empty
list (an explicitly empty policy section is a legitimate, unsurprising choice, unlike omitting
`policy` entirely); `source`/`destination` optional (a policy-only configuration remains valid,
matching `policy.apply()`'s own deployment-neutral design, unaffected by this checkpoint).
**Unknown top-level fields**: rejected, except a reserved `"x-"`-prefixed extension namespace
(section 10). **Unknown-field/unknown-kind behavior generally**: fail-closed (section 10/20).

This is suitable for eventual JSON Schema expression (a `oneOf`-discriminated operation array, a
`required` list matching the above) — not implemented here.

## 4. Recommended top-level JSON shape

```json
{
  "schema": "fastdicomstructure-configuration",
  "schema_version": 1,
  "policy": {
    "name": "example-policy",
    "version": "1.0.0",
    "acceptance": [ ... ],
    "mutation": [ ... ]
  },
  "source": { "type": "filesystem", "...": "..." },
  "destination": { "type": "filesystem", "...": "..." }
}
```

`"schema"` is a plain stable string identifier, not a resolvable URI (no schema document is
published yet; using a URI-shaped string now would falsely imply one exists) — see section 10 for
why this is still forward-compatible with later publishing a real JSON Schema URI as an *additional*
field, not a breaking rename.

## 5. Locator representation

**Central finding, argued from evidence, not assumed**: the JSON representation must express **two**
genuinely different shapes, not one, because `TagLocator` and `PathLocator` are two different
*resolution algorithms* in frozen code (section 2) — `TagLocator(recursive=True)`'s "anywhere, any
depth" search cannot be expressed as any `PathLocator` step sequence (fixed-depth wildcards only).
Collapsing them into one JSON shape would either silently lose the "anywhere" capability or require
inventing a new unbounded-depth locator semantic — explicitly out of scope ("no new Locator
semantics"). The two-shape design is therefore not a stylistic choice; it is required by frozen
Locator V1's own structure.

**Tag token**: a single string, `"(GGGG,EEEE)"`, exactly four uppercase hex digits per group,
parenthesized, comma-separated — matching PS3.6/`dcmdump`'s own printed convention exactly (the
form a DICOM practitioner already recognizes on sight), not attrs' `(group, element)` tuple, not a
decimal array. Lowercase/unpadded/bare forms are **rejected**, not normalized — one canonical
spelling, chosen for round-trip determinism (canonical serialization always produces the identical
string) and trivial regex validation (`^\([0-9A-F]{4},[0-9A-F]{4}\)$`), evaluated against and
preferred over `[16, 16]` (accurate but unrecognizable to the target DICOM-literate audience without
a lookup) and unparenthesized `"0010,0010"` (marginally less standard-looking, no real advantage).

**Bare-tag target (`TagLocator`)**:

```json
{"tag": "(0010,0010)", "scope": "root"}
{"tag": "(0010,0010)", "scope": "recursive"}
```

`scope` is **required**, no default, exactly two values (`"root"`|`"recursive"`) — a deliberate
divergence from the Python API's convenience defaults (which differ *per operation*: `Remove`/
`Replace`/`ReplaceText` default `recursive=True`; `Ensure`/`EnsureText` default `False`). Requiring
`scope` explicitly in JSON means a reviewer never has to remember which operation defaults which
way to understand a document — more explicit than the Python API, deliberately, for reviewability.

**Path target (`PathLocator`, concrete or wildcard)**:

```json
{
  "path": [
    {"tag": "(300A,00B0)", "item": "*"},
    {"tag": "(300A,0111)", "item": 0}
  ],
  "tag": "(0010,0010)"
}
```

`item` is a non-negative integer or the literal string `"*"` — identical to `ITEM_WILDCARD`, chosen
in S1.1 specifically to already be the natural JSON token (verified: `LocatorStep`'s own docstring
states this was the reason `"*"`, not a Python-only sentinel object, was chosen). Zero steps (a bare
`{"path": [], "tag": "..."}`) is accepted and is meaning-equivalent to `{"tag": "...", "scope":
"root"}` — both forms exist because one is idiomatic for "I know this is root" and the other for
"generated/templated path construction where zero steps is just a degenerate case," not because two
independent concepts exist.

**Discrimination**: structural (presence of `"path"` vs `"scope"`), not a redundant `"kind"` field
on the locator object itself — adding one would create two ways to say the same thing with a risk of
contradiction (`"kind": "tag"` alongside a `"path"` array). Operations themselves *do* get an
explicit discriminator (section 6) because their shapes do not already imply their own kind the way
a locator's shape does.

**Malformed representation rejectable before execution**: yes, at the loader/schema layer (section
11) — a bad tag string, a bad `item` token, or a `scope` value outside the two allowed strings are
all pure syntax checks, resolvable without ever touching a `Structure`.

### Keyword addressing

**Deferred, not excluded, not V1** — distinguished deliberately: attrs has no reverse
dictionary lookup exposed at any layer (confirmed across every prior A1 freeze report), and
Locator V1 itself is numeric-tag-only by its own frozen design. JSON cannot offer `"PatientName"`
addressing without a prerequisite capability neither repository has built — this is a blocked
dependency, not a product decision against the idea (section 20's decision table records this
distinction explicitly).

## 6. Operation representation

**Discriminator**: `"op"`, a string, one of exactly the operation kinds included in V1 (below) —
chosen to match `OperationResult.kind`'s own vocabulary **verbatim**, so a human reading a
`PolicyResult` can match a diagnostic straight back to the JSON operation that produced it without a
translation table. This is a real, evidence-based design property, not a coincidence: `"op":
"replace_text"` and `OperationResult.kind == "replace_text"` are the same string by construction.

**V1 operation set, decided**: `require`, `remove`, `replace_text`, `ensure_text`,
`allow_list_prune`, `private_tag_policy`. **Raw `replace`/`ensure` (bytes-valued) are excluded from
V1**, argued in full in section 6a below.

```json
{"op": "require", "target": {"tag": "(0010,0020)", "scope": "root"}}

{"op": "remove", "target": {"tag": "(0010,0010)", "scope": "recursive"}}

{"op": "replace_text", "target": {...}, "value": "ANONYMIZED"}
{"op": "replace_text", "target": {...}, "value": ["ONE", "TWO"]}

{"op": "ensure_text", "target": {"tag": "(0012,0062)", "scope": "root"}, "value": "YES", "vr": "CS"}

{"op": "allow_list_prune", "tags": ["(0008,0060)", "(0010,0020)"]}

{"op": "private_tag_policy", "remove": true}
```

Per operation:

| Operation | Required | Optional (default) | Notes |
|---|---|---|---|
| `require` | `target` | -- | never mutates; zero matches inherited unchanged (`REQUIREMENT_UNSATISFIED`, rejects Policy) |
| `remove` | `target` | -- | zero matches → silent no-op, inherited unchanged |
| `replace_text` | `target`, `value` | -- | `value`: `str` or array of `str`; zero matches → silent no-op |
| `ensure_text` | `target`, `value` | `vr` (infer) | zero insertion sites → `GUARANTEE_UNESTABLISHED`, does not reject Policy |
| `allow_list_prune` | `tags` (array of tag tokens) | -- | not locator-shaped -- a flat set, matching `AllowListPrune.tags` exactly |
| `private_tag_policy` | -- | `remove` (`true`) | matches Python's own default; documented explicitly given its privacy-relevant effect |

No callback field exists anywhere in this shape (section 7). `target` uses the single shared
locator grammar from section 5, uniformly, across every operation that has one.

### 6a. Raw values vs. text values — the decision

**Decision: exclude raw `bytes`-valued `Replace`/`Ensure` from Configuration V1; keep both
available only through the Python API.**

JSON has no native byte type; every option considered (base64 object, hex object, a restricted
string encoding) requires the JSON author to reason about an encoding they cannot visually verify
(`"data": "V0VTAA=="` is not reviewable the way `"value": "YES"` is) — directly opposed to "human
comprehensible," "visual auditability." Evaluated against "should ordinary product users need raw
mutation at all": every worked de-identification/tagging example across S1.2/S1.3's own probes
(`PatientName`, `PatientID`, `PatientIdentityRemoved`, `DeidentificationMethod`) is text-shaped;
raw-byte mutation exists in the Python API specifically for expert-level cases (writing a
non-UTF-8-representable value, bypassing charset validation deliberately) that a declarative,
reviewable configuration format is a poor fit for regardless of encoding choice.

**Capability lost, stated explicitly**: a JSON-authored policy cannot write an exact raw byte
sequence or target a genuinely binary/non-text element's raw value. **Not lost**: the Python API
(`Replace`/`Ensure`, unchanged) remains fully available for this need — nothing is removed from the
programmatic surface; V1 JSON is a *declarative subset*, not a replacement. This is recorded as a
deliberate, revisitable exclusion (a `replace`/`ensure` raw-byte JSON shape could be added in a
later minor version, additively, without touching this decision for `replace_text`/`ensure_text`),
not a permanent architectural wall.

**Multi-valued text**: `"value": ["ONE", "TWO"]` maps directly to `Sequence[str]`, matching
`ReplaceText`/`EnsureText`'s existing Python parameter shape with no reinterpretation.

## 7. Callback disposition

**Classification: programmatic-only, permanently for V1.** Confirmed against the instruction's own
three candidate classifications: not "declarative transform vocabulary introduced later" and not
"templating/expression language later" — **no expression language, templating engine, or dynamic
evaluation of any kind is designed or implied here**. The JSON schema for `replace_text`/
`ensure_text` accepts only a literal string or array of strings for `"value"`; there is no field
shape, anywhere in this checkpoint's design, that could hold a callback reference, a code string, or
an expression. This is a genuine security boundary, not merely a convenience gap: a loader built
against this contract has no code path that could `eval`/`exec`/deserialize executable content, by
construction, because no such field exists to feed it.

If a future increment wants declarative *conditional* value computation (e.g. "replace with the
first 3 characters of the original value"), that is a **new, separately-authorized capability**
(a constrained transform vocabulary, explicitly *not* general expressions) — not designed here, and
not assumed to be needed; recorded as a possible, unscoped future direction only.

## 8. VR representation

```json
"vr": "CS"
```

Standard 2-letter uppercase VR spelling, from attrs' own frozen `_VR_NAMES` list **excluding**
`"UNKNOWN"` (attrs' internal inference sentinel, never a valid thing to *author* — omitting `"vr"`
entirely is how a JSON author requests inference, mirroring Python's `vr=None`).

**Validation boundary, precisely drawn**: the loader (not attrs, not duplicating attrs) may check
that a supplied VR token is one of the ~30 standard PS3.5 letter-pairs — a fixed, standards-frozen
enum, pure string syntax, unrelated to *which* VR is correct for *which* tag (that question is
attrs' dictionary, never touched here). This is a syntax check (analogous to checking a tag string
matches `\([0-9A-F]{4},[0-9A-F]{4}\)`), not a semantic one.

| Case | Behavior |
|---|---|
| `vr` omitted, inference succeeds | identical to Python `vr=None` — attrs infers, no JSON-layer difference |
| `vr` omitted, attrs requires one | `VR_REQUIRED` diagnostic, identical to Python — the loader passes `None` through unchanged |
| invalid VR token (not in the known ~30) | **configuration error**, rejected before execution (section 12) — a pure syntax problem |
| explicit VR conflicts with the standard dictionary VR for that tag | **used exactly as given, never checked** — mirrors attrs' own documented behavior verbatim ("the caller's own authoritative VR, never consulted against the dictionary"); the loader must not second-guess this, since doing so would both duplicate the dictionary and remove a legitimate expert override capability that already exists in the Python API |

## 9. Acceptance vs. mutation

**Decision: separate `acceptance`/`mutation` arrays, with `acceptance` restricted to `require`
operations only in V1.**

Argued from the evidence in section 2, item by item, per the instruction's own question list:

- **Is `Require` fundamentally acceptance?** Yes — it is the only operation kind whose
  dissatisfaction halts the containing `Policy` (`execution=REJECTED`), verified directly from
  `apply()`'s single halt condition.
- **Can mutation occur before an acceptance condition?** In the raw Python API, yes — nothing
  prevents a caller from ordering `Remove` before `Require` in `Policy.operations` (the module's own
  docstring already warns about this: "A caller that needs 'no partial mutation on reject' must put
  every `Require` first"). **The two-array JSON design removes this footgun by construction**: the
  loader always concatenates `acceptance` operations before `mutation` operations when building the
  underlying `Policy.operations` tuple, so a JSON author cannot accidentally author a
  mutate-then-reject document. **This is a self-imposed restriction of the JSON authoring layer,
  not a change to frozen `Policy` semantics** — a direct Python caller retains full freedom; nothing
  in `policy.py` is modified to enforce this.
- **Should acceptance always execute before mutation?** Yes, by the loader's own construction, for
  exactly the safety reason above.
- **Can acceptance policy mutate anything?** No, by construction — `acceptance` accepts only
  `require`-kind entries, and `Require` never mutates (verified).
- **Can mutation policy reject?** In V1, no — `require` is deliberately **not** an allowed kind
  inside `mutation` (a closed restriction, not a technical impossibility: nothing in `Policy` itself
  would prevent a `Require` from appearing after mutations, but the JSON schema chooses not to offer
  that ordering, to avoid authoring the exact `Policy.apply()` known limitation about
  no-transactionality-across-operations into a declarative document by accident). This can be
  relaxed additively later if real demand for mid-pipeline requirements appears.
- **Where does `Ensure`/`EnsureText` belong?** **`mutation`, not `acceptance`** — despite having its
  own `satisfied` condition, `Ensure`'s dissatisfaction (`GUARANTEE_UNESTABLISHED`) does **not**
  halt the `Policy` (verified directly, section 2) — placing it under `acceptance` would visually
  imply a rejection capability it does not have under frozen semantics. This is the single most
  important finding of this section: **`Ensure`'s condition and `Require`'s condition are not the
  same kind of "acceptance" despite both having `satisfied: Optional[bool]`** — the JSON model must
  not conflate them, and does not.
- **Does `GUARANTEE_UNESTABLISHED` affect acceptance?** No — confirmed by the same evidence; it is
  visible in `PolicyResult.diagnostics` (an S1.3 improvement) but does not change
  `PolicyExecutionStatus`/`Decision` the way an unsatisfied `Require` does.
- **Does operation ordering cross the acceptance/mutation boundary?** No, by construction of the
  loader — acceptance operations are always assembled first, as a fixed rule, not an author choice.
- **Does separating them improve safety/authorability, or incorrectly constrain the existing Policy
  model?** Improves both, without constraining anything: it does not change what `Policy`/`apply()`
  can do (a `Policy` object built from a valid Configuration document is indistinguishable from one
  built by hand with the same operations in the same order) — it only narrows what a JSON *author*
  can accidentally construct. **No conflict with frozen semantics was found**; nothing here required
  changing S1.1-S1.3 behavior.

## 10. Versioning and forward compatibility

| Decision | Value | Rationale |
|---|---|---|
| Schema identifier | `"schema": "fastdicomstructure-configuration"` (plain string, not a URI) | stable identity without implying a published, resolvable schema document that does not yet exist; can later be *replaced* by a real URI as a compatible, additive change (the field's role is unchanged) |
| Schema version | `"schema_version": 1` (bare integer, major-only) | simplest honest choice for a young interface; avoids inventing semver-style minor-compatibility rules whose complexity the instructions themselves caution against; every future *behavior-affecting* addition requires the loader to explicitly recognize the new field anyway (fail-closed, below), so a minor-version number would not by itself grant safe forward-compatibility -- it would just be decoration |
| Unknown top-level field | **rejected** | affects interpretation risk; see extension exception below |
| Unknown operation kind (`"op"`) | **rejected** | could silently skip or misrepresent an entire operation -- highest-severity fail-closed case |
| Unknown operation field | **rejected** | an unrecognized field could represent author intent the loader silently ignores -- dangerous for a de-identification tool specifically |
| Unknown locator field | **rejected** | same reasoning |
| Unknown VR token | **rejected** | syntax-level, unrelated to dictionary semantics (section 8) |
| Unknown source/destination adapter `"type"` | **not rejected by the Configuration model** -- deferred to the (not-yet-built) execution layer, section 9's envelope is opaque by design | S1.4 builds no adapters and has no registry to check against; rejecting here would be either always-true (nothing is "known" yet) or require inventing a fake registry |
| Newer configuration presented to an older implementation | **rejected on major-version mismatch**; unknown fields inside it are already covered by the rules above | fail-closed is the correct default until real backward-compatibility need is demonstrated |
| Extension namespace | any field name prefixed `"x-"`, at the top level or inside an operation object, is reserved and **must be safely ignorable** -- contractually never policy-semantic | mirrors the established OpenAPI/JSON:API `x-` convention rather than inventing a new one; the one deliberate carve-out from "reject unknown fields," scoped narrowly enough not to weaken the fail-closed default |

## 11. Validation boundary

| Layer | Owns |
|---|---|
| JSON/schema layer (future loader) | syntactic JSON validity; required/optional top-level and per-operation fields and their types; the `"op"` discriminator; locator shape (`tag`/`path`/`item`/`scope` syntax); tag-token regex; wildcard-token syntax (`"*"` or non-negative int); **VR token syntax** (closed list membership, not dictionary correctness); unknown-field rejection; schema version check |
| Structure (`policy.py`, unchanged) | constructing `TagLocator`/`PathLocator`/`LocatorStep` from already-syntax-valid loader output (`MalformedLocatorError` remains the structural-validity backstop it already is); operation semantic validity (e.g. `Replace` refusing a callback on a bare recursive-scope `TagLocator` -- already frozen, unaffected); `Policy`-level ordering/execution (unchanged) |
| attrs (frozen, untouched) | dictionary-backed VR *inference* (not token syntax); charset semantics/representability; actual DICOM mutation correctness/encoding constraints |

**No duplication found or proposed**: the one place this boundary could blur (VR token checking) is
resolved in section 8 by drawing the line at syntax-vs-semantics precisely, not by the loader
consulting the dictionary.

## 12. Configuration errors vs. execution diagnostics

**Decision: a distinct, separate `ConfigurationError` model — not a reuse of `Diagnostic`/
`DIAGNOSTIC_CODES`.** Illustrative only, not implemented:

```text
ConfigurationError
    code        (SCHEMA_VERSION_UNSUPPORTED | UNKNOWN_OPERATION | LOCATOR_INVALID |
                 VR_TOKEN_INVALID | MISSING_REQUIRED_FIELD | UNKNOWN_FIELD | MALFORMED_JSON)
    path        (a JSON-pointer-shaped location within the document, e.g. "/policy/mutation/2/target")
    message
```

**`LOCATOR_INVALID` belongs here, not in runtime `DIAGNOSTIC_CODES`** — this is the direct S1.4
resolution of the question S1.3 deliberately left open. It is **not** simply carried forward into
the existing vocabulary merely because the name was reserved; it is placed in a **new, parallel**
model precisely because it answers a different question ("could this document even be turned into a
`Policy`") than every existing code answers ("what happened when a *valid* `Policy` ran"). This
mirrors `MalformedLocatorError`'s own existing Python-level distinction exactly (construction-time,
never reaching `Policy.apply()`) — the JSON loader's `LOCATOR_INVALID` is the declarative-layer twin
of that same, already-frozen line.

The two models are used sequentially, never mixed: a document that fails `ConfigurationError`
validation never reaches `Policy.apply()` at all; a document that passes produces an ordinary
`PolicyResult` using the unchanged S1.3 model. No document can produce both kinds of error for the
same failure.

## 13. S1.3 result-serialization compatibility analysis

**Finding: already cleanly compatible, effectively self-proven by S1.3's own qualification.**
`tests/python/test_result_diagnostic.py::JSONAuthorabilityTest` already round-trips a real
`PolicyResult` (including a `Diagnostic`) through `json.dumps`/`json.loads` and asserts the reloaded
structure matches. Re-verified against every checklist item in this checkpoint's own instruction:

- No attrs raw path leaks: confirmed — `Diagnostic.locator`/`.site` are already plain,
  Structure-owned strings (section 2).
- No DICOM value leaks: confirmed by S1.3's own dedicated privacy test.
- No exception message leaks: confirmed by S1.3's own dedicated test (`cause_type` is a class name
  only).
- No Python-specific enum representation: `ExecutionStatus`/`PolicyExecutionStatus`/`Decision` are
  all `str` subclasses — `.value` (or, since they subclass `str`, direct use) yields a plain JSON
  string. **One real, minor implementation wrinkle, not a design flaw**: `dataclasses.asdict()`
  does not automatically stringify `Enum` members (confirmed directly in S1.3's own test, which had
  to convert `execution`/`decision` fields explicitly before calling `json.dumps`) — a future
  serializer needs one small, explicit conversion step; this does not require any change to the
  `Diagnostic`/`OperationResult`/`PolicyResult` dataclasses themselves.
- Deterministic ordering: confirmed — `operations` always matches `Policy.operations` order;
  `diagnostics` is aggregated in that same order (verified directly from `_build_policy_result`).
- Stable diagnostic codes: confirmed, `DIAGNOSTIC_CODES` unchanged by this checkpoint.

**No contradiction was found requiring any change to the frozen S1.3 result model.**

## 14. Security analysis

| Concern | Finding |
|---|---|
| Arbitrary code execution | not possible by construction — no field shape anywhere in this design can hold executable content; a loader would use `json.loads` only |
| Callback injection | not possible — no callback-shaped field exists in V1 (section 7) |
| Path traversal (future filesystem adapter) | out of S1.4 scope to solve; flagged as a real S1.5 concern once a filesystem adapter's `"path"`-shaped fields are actually designed |
| Oversized configuration | a future loader should impose a sane size/depth limit; not designed in detail here, recorded as an implementation-time concern |
| Pathological wildcard policies | inherited, not new — S1.1/S1.2 already disclose "linear traversal, not optimized" as the accepted performance envelope; JSON does not introduce a new risk class here, only a new way to *author* an already-possible-in-Python pattern |
| Unknown-field ambiguity | resolved, fail-closed (section 10) |
| Dangerous implicit defaults | reviewed field-by-field: `scope` has **no** default (required, precisely to avoid this); `vr` omission means "infer," identical to Python, not a new default; `private_tag_policy.remove` defaults to `true`, inherited unchanged from Python and consistent with the operation's own name/purpose -- flagged for explicit documentation, not changed |
| Accidental PHI inclusion in configuration | a **real, JSON-specific** risk worth naming explicitly: a literal `"value"` in `replace_text`/`ensure_text` could accidentally contain a real patient's data if a template file is copy-pasted from a real case rather than written generically -- JSON documents, being data, are more likely to be checked into version control or logged verbatim than Python source. Not technically preventable (a literal replacement value is a legitimate, intended feature); recorded as an operational guideline: configuration files should be handled with the same care as any file that might contain sensitive literals |
| Accidental PHI in result diagnostics | already resolved by S1.3 (section 13) — unaffected by this checkpoint |
| Secrets/credentials in adapter configuration | **not solved here, boundary only**: when `source`/`destination` adapters are eventually designed (S1.5+), they should support *referencing* external secrets (an environment variable name, a secret-manager URI) rather than embedding raw credentials in the JSON document — a principle recorded for that future design, not a mechanism built now |

**Configuration V1, as designed, is declarative data — no field shape can carry executable
content.**

## 15. Authorability examples/probes

Design examples, not executable artifacts.

**Probe A — minimal de-identification policy**

```json
{
  "schema": "fastdicomstructure-configuration",
  "schema_version": 1,
  "policy": {
    "name": "basic-deidentification",
    "version": "1.0.0",
    "acceptance": [
      {"op": "require", "target": {"tag": "(0010,0020)", "scope": "root"}}
    ],
    "mutation": [
      {"op": "replace_text", "target": {"tag": "(0010,0010)", "scope": "root"}, "value": "ANONYMIZED"},
      {"op": "remove", "target": {"tag": "(0010,0030)", "scope": "root"}},
      {"op": "ensure_text", "target": {"tag": "(0012,0062)", "scope": "root"}, "value": "YES", "vr": "CS"}
    ]
  }
}
```

**Probe B — nested wildcard mutation**

```json
{"op": "replace_text",
 "target": {"path": [{"tag": "(300A,00B0)", "item": "*"}], "tag": "(300A,00C3)"},
 "value": "REDACTED"}
```

(every Item of BeamSequence, its BeamDescription replaced — a real `PathLocator` pattern, exactly
the shape S1.1/S1.2's own probes used.)

**Probe C — charset-sensitive text**

```json
{"op": "ensure_text", "target": {"tag": "(0010,0010)", "scope": "root"}, "value": "Müller^Anna"}
```

(relies entirely on attrs' existing, frozen charset resolution at the target's effective
`(0008,0005)` context — the JSON loader does nothing charset-aware itself, per section 11's
boundary.)

**Probe D — private tag behavior**

```json
{"op": "private_tag_policy", "remove": true}
```

(the existing declarative operation, unchanged; no new private-creator-aware JSON shape is
introduced, matching the explicit exclusion.)

**Probe E — acceptance failure**

```json
"acceptance": [
  {"op": "require", "target": {"tag": "(0008,0060)", "scope": "root"}}
]
```

(a document with no `Modality` present produces `execution=REJECTED`, `decision=REJECT`, and every
`mutation` entry `NOT_EXECUTED` — directly exercising S1.3's own model, unchanged.)

**Probe F — source/destination envelope (illustrative only, no execution semantics)**

```json
{
  "schema": "fastdicomstructure-configuration",
  "schema_version": 1,
  "policy": { "name": "same-as-probe-a", "version": "1.0.0", "mutation": [ ] },
  "source": {"type": "filesystem", "path": "/incoming"},
  "destination": {"type": "filesystem", "path": "/processed"}
}
```

(the envelope shape only — `"path"` here is illustrative of what a *future* filesystem adapter
*might* need, not a designed, validated field; S1.4 does not interpret `source`/`destination`
beyond checking they are objects with a `"type"` string.)

## 16. Round-trip analysis

For every construct in sections 5-9 **except** callbacks (section 7, permanently excluded from V1)
and raw-byte `Replace`/`Ensure` (section 6a, deliberately excluded from V1, not merely
unrepresentable), the round trip holds conceptually:

```text
JSON  ->  Locator/Operation/Policy objects  ->  frozen Structure operations  ->
    identical semantics to direct programmatic construction (no JSON-specific
    reinterpretation anywhere in sections 5-9)

Policy object  ->  canonical JSON (deterministic field order, canonical tag-token
    spelling)  ->  parse  ->  semantically equivalent object (same operations,
    same order, same locators -- not necessarily byte-identical JSON text, matching
    S1.1's own "semantic round-trip, not byte-identical" precedent)
```

**Nothing else in the current Policy API resists this round-trip** beyond the two already-named
exclusions — every locator shape, every included operation, VR handling, and the acceptance/
mutation split were each individually checked against frozen semantics in sections 5-9 with no
further contradiction found.

## 17. Usability / product-hypothesis implications

Not measured (no user study run, per instruction) — Probe A evaluated qualitatively against the
required criteria:

- **Line count**: ~15 lines of JSON for a 4-operation policy (1 acceptance + 3 mutation).
- **Conceptual vocabulary required**: `op`, `target`, `tag`/`path`/`item`/`scope`, `value`, `vr` --
  6 concepts, all DICOM- or policy-domain words, none Python- or attrs-specific.
- **DICOM knowledge required**: tag numbers (or a future keyword layer, deferred) and, for
  `ensure_text` on a non-text-VR-inferable tag, a VR letter pair — the same knowledge a DICOM
  practitioner already has from reading the standard or `dcmdump` output.
- **fastDICOM-specific knowledge required**: the `scope`/wildcard vocabulary (small, ~4 concepts:
  root, recursive, concrete item, wildcard item) and the acceptance/mutation split's own rule
  (acceptance = `require` only) -- both explained in one short document, neither requiring Python
  familiarity.
- **Visual auditability**: high for Probe A/C/D/E (flat, short); Probe B's nested `path` array is
  the most visually complex construct in this design, proportional to genuinely complex targeting,
  not to accidental verbosity.
- **Likely error modes**: forgetting `scope` (loader rejects, fail-closed, not silently wrong);
  wrong VR token (rejected at load, section 8); typo'd tag string (rejected, section 5).
- **Defaults**: `vr` (infer) and `private_tag_policy.remove` are the only two real defaults in V1,
  both inherited unchanged from Python and both documented explicitly (section 14).
- **Nesting/noise**: the deepest realistic V1 document is 4 levels (`policy.mutation[].target.path[]`)
  — proportional to the underlying `PathLocator` shape itself, not inflated by the JSON encoding.

**Proposed future metrics** (not run here): JSON lines/bytes for a canonical set of probes; number
of distinct required concepts (vocabulary size); equivalent Python LOC for the same policy;
number of explicit VR declarations required across a representative policy set; number of
configuration-validation errors produced when a technically competent but fastDICOM-unfamiliar
reviewer is asked to author a probe from a plain-English description; a structured reviewability
score (e.g. "can a second engineer, without running it, correctly predict the outcome against a
described dataset").

## 18. Product Capability Map implications

Reviewed `docs/architecture/PRODUCT_CAPABILITY_MAP.md` — **no status changed by this checkpoint**
(design-only, no implementation).

Assessment of what a *successful S1.4 implementation* (not this checkpoint) would be sufficient to
promote, separating **configuration representability** from **adapter/execution capability**:

| Capability | What this checkpoint establishes | What it does NOT establish |
|---|---|---|
| P2.1 (Single declarative JSON) | a durable, evidence-based Configuration Contract v1 design, proven against frozen semantics with no contradiction | no parser/schema/loader exists yet -- still not promotable past `PLANNED` until one is built and qualified |
| P2.2 (Source config) | a minimal, deliberately-opaque envelope shape (`{"type": ..., ...}`) | no adapter exists or is designed in any depth -- representability of the *envelope* is not the same as the capability, and this checkpoint is explicit that it is not designing P2.2's real content |
| P2.3 (Destination config) | same envelope shape | same caveat |
| P2.4 (Acceptance-policy config) | a concrete, argued JSON shape for `require` (section 9) | no loader exists; JSON mapping proven on paper only, same as P2.1 |
| P2.5 (Mutation-policy config) | a concrete, argued JSON shape for six of eight operation kinds (raw `replace`/`ensure` deliberately excluded) | no loader; also, this checkpoint discovers that P2.5's *eventual* CURRENT bar should explicitly note raw-byte operations remain programmatic-only, not silently implied to be covered |

**None of P2.1-P2.5 is promoted by this checkpoint.** A future S1.4 *implementation* report would be
the right place to promote them, following exactly the S1.1-S1.3 precedent (design checkpoint,
then implementation + qualification, then capability-map update referencing evidence).

## 19. Explicit deferred/out-of-scope items

Per instruction, not designed in detail here (recorded for continuity only): S1.5 execution
adapters, gateway convergence, CLI, filesystem walking, streaming, C-STORE, DICOMweb, database
output, cloud functions, containers, Kubernetes, Evidence Packet integration, P1.6 bulk-data policy,
creator-aware private policy, attrs changes, keyword/tag dictionary implementation, expression
languages, arbitrary scripting, plugin execution systems, secrets-management implementation,
RSNA CTP benchmarking.

## 20. Discovered blockers or contradictions

**None that require changing a frozen S1.1-S1.3 contract.** Two genuine *dependencies* (not
contradictions) were surfaced:

1. Keyword tag addressing cannot be offered because neither attrs nor Structure exposes the
   prerequisite reverse-dictionary capability (section 5) — a blocked dependency on a future,
   separately-authorized increment, not a design flaw in this checkpoint.
2. `LOCATOR_INVALID`'s S1.3-era reservation needed a real decision, not a default reuse (section
   12) — resolved by placing it in a new, parallel `ConfigurationError` model rather than the
   runtime `Diagnostic` vocabulary, with no change to the frozen S1.3 `DIAGNOSTIC_CODES` tuple.

### Required decision tables

**Locator representation**

| Case | Classification | JSON shape |
|---|---|---|
| `TagLocator` recursive | V1 declarative | `{"tag": "...", "scope": "recursive"}` |
| `TagLocator` root-only | V1 declarative | `{"tag": "...", "scope": "root"}` |
| `PathLocator` concrete | V1 declarative | `{"path": [{"tag": "...", "item": 0}, ...], "tag": "..."}` |
| `PathLocator` one wildcard | V1 declarative | `{"path": [{"tag": "...", "item": "*"}], "tag": "..."}` |
| `PathLocator` multiple wildcards | V1 declarative | same shape, multiple `"item": "*"` steps |
| malformed locator | rejected at load (`ConfigurationError`, `LOCATOR_INVALID`), never reaches `Policy` | n/a |

**Operation representation**

| Operation | Classification | Rationale |
|---|---|---|
| `Require` | V1 declarative | acceptance, no value, no callback concept |
| `Remove` | V1 declarative | no value, no callback concept |
| `Replace` (raw) | **programmatic-only** | section 6a — raw bytes excluded from V1 for usability/reviewability, not impossibility |
| `ReplaceText` (literal) | V1 declarative | — |
| `Ensure` (raw) | **programmatic-only** | same as raw `Replace` |
| `EnsureText` (literal) | V1 declarative | — |
| `AllowListPrune` | V1 declarative | flat tag-set shape, no locator needed |
| `PrivateTagPolicy` | V1 declarative | single boolean flag |
| callback-based `Replace` | **unsupported in JSON, permanently** (programmatic-only) | section 7 — security boundary, not a gap to close later without a separately-designed constrained vocabulary |
| callback-based `ReplaceText` | **unsupported in JSON, permanently** | same |

**Value representation**

| Case | JSON shape |
|---|---|
| single text | `"value": "ANONYMIZED"` |
| multi-valued text | `"value": ["ONE", "TWO"]` |
| raw bytes | **not represented in V1** (section 6a) |
| explicit VR | `"vr": "CS"` (section 8) |
| inferred VR | `"vr"` omitted |
| callback value | **not representable, by design** (section 7) |

**Unknown input behavior**

| Case | Behavior |
|---|---|
| unknown schema version (major mismatch) | reject |
| unknown top-level field | reject, unless `"x-"`-prefixed |
| unknown operation | reject |
| unknown operation field | reject, unless `"x-"`-prefixed |
| unknown locator field | reject |
| unknown VR token | reject |
| unknown source adapter type | not rejected by the Configuration model itself -- deferred to the execution layer (section 9's opaque envelope) |
| unknown destination adapter type | same |

## 21. Proposed S1.4 implementation progression

The suggested progression is assessed as **appropriate with one refinement**: result serialization
(originally proposed as `S1.4.5`) is *already effectively designed and proven* by this checkpoint
(section 13) and by S1.3's own `JSONAuthorabilityTest` — it does not need its own implementation
stage, only the one small enum-to-string conversion helper noted in section 13, which is small
enough to fold into whichever stage first needs to emit a `PolicyResult` as JSON (most naturally
`S1.4.6`'s own qualification work, or deferred entirely to whichever future increment first needs
runtime result serialization for real, since S1.4 itself does not execute anything).

```text
S1.4.1  Configuration data model + version contract       (dataclasses/types only, no parsing)
S1.4.2  Locator + operation decoding/validation            (JSON -> Locator/PolicyOperation objects)
S1.4.3  Policy construction                                (assembling acceptance+mutation -> Policy)
S1.4.4  Source/destination declarative envelopes           (opaque type+options parsing only)
S1.4.5  Canonical examples + qualification                 (the six probes, differential/round-trip tests)
S1.4 freeze
```

(Five stages, not six — result serialization folded out per the refinement above.) Kept small, per
instruction; no stage here builds an adapter, a CLI, or executes anything against a real DICOM
pipeline beyond calling the already-frozen `policy.apply()`.

## 22. Falsifiable S1.4 implementation claim

Refined from the authorization's own candidate, narrowed to match the exclusions this checkpoint
actually settled on (raw operations, callbacks):

> Every V1-declarative Structure policy operation (`Require`, `Remove`, `ReplaceText`, `EnsureText`,
> `AllowListPrune`, `PrivateTagPolicy` — explicitly excluding raw-byte `Replace`/`Ensure` and
> callback-based `Replace`/`ReplaceText`, which remain programmatic-only by design) can be
> represented in a small, versioned, human-authorable JSON configuration, parsed deterministically
> into the existing frozen `Policy`/`Locator` model, and executed with semantics equivalent to
> direct programmatic construction, without exposing attrs path mechanics and without any field
> shape capable of holding executable configuration.

**Separate, explicitly-not-yet-demonstrated product hypothesis**:

> Common DICOM acceptance and metadata-transformation policies can be expressed more compactly and
> with less application-specific code using Configuration v1 than through direct Python
> construction.

Not claimed as demonstrated by this checkpoint — section 17 proposes future metrics; none were
measured.

## GO / NO-GO recommendation

**GO**, with the scope exactly as narrowed in sections 5-9: a JSON Configuration Contract v1
covering `Require`/`Remove`/`ReplaceText`/`EnsureText`/`AllowListPrune`/`PrivateTagPolicy`, the
acceptance/mutation split restricted to `require`-only acceptance, VR-token syntax validation only,
an opaque source/destination envelope, and a separate `ConfigurationError` model distinct from
runtime `Diagnostic`. No frozen S1.1-S1.3 contract requires modification. No attrs change is
required. The only real blocker found (keyword addressing) is correctly deferred, not designed
around. Raw-byte operations and callbacks are deliberately, permanently excluded from the
declarative surface, not silently unaddressed.

---

No production code in either repository was modified to produce this checkpoint. No attrs file was
touched. `fastdicomstructure/policy.py` and all committed test files are unchanged from the S1.3
freeze commit. No JSON parser, schema, loader, CLI, adapter, or gateway integration was built.
S1.4 implementation, S1.5, and gateway convergence were not started.

---

## Accepted disposition and corrections (recorded post-acceptance)

This checkpoint was **accepted for implementation**, with three bounded corrections. This section
records the disposition; the analysis above is preserved unchanged as the original evidence and
reasoning trail — it is not rewritten to make the corrections appear anticipated.

**Correction 1 — no extension escape hatch in V1.** Section 10's `"x-"`-prefixed extension
namespace is **removed**. Configuration V1 is fully closed and fail-closed with no exception:
unknown top-level fields, unknown `policy` fields, unknown operation fields, unknown locator
fields, and unknown fields on the core `source`/`destination` envelope are all rejected
unconditionally. The invariant implemented is: *every field in a Configuration V1 document is
understood by the Configuration V1 implementation reading it.* No extension mechanism is invented
until a demonstrated use case requires one — section 10's own `"x-"` row is superseded by this
correction, not deleted from the historical record above.

**Correction 2 — schema identifier is frozen.** Section 4/10's suggestion that `"schema":
"fastdicomstructure-configuration"` might later be *replaced* by a URI is **withdrawn**. The
string `"fastdicomstructure-configuration"` is the stable Configuration V1 schema identifier,
permanently, and retains its original identity semantics. A future formal JSON Schema document, if
ever published, would be referenced through a *separate* field (e.g. `$schema`), introduced under
its own design/versioning review — not by repurposing or replacing this field.

**Correction 3 — no result serialization in S1.4.** Section 13's finding that S1.3's result model
is already cleanly JSON-compatible **stands as evidence**, but the small enum-to-string conversion
helper it mentioned is **not implemented in S1.4**. `PolicyResult`/`OperationResult`/`Diagnostic` →
JSON serialization is explicitly out of S1.4's implementation scope; S1.4's executable boundary
ends at `Policy.apply()` → `PolicyResult` (inspected directly by qualification code, never
serialized). Actual result serialization is deferred to whichever future increment first has a real
consumer for it (most naturally S1.5).

**Configuration Contract v1, as actually implemented**, matches this checkpoint's sections 3-9
except for Correction 1 (no `"x-"` exception) and Correction 2 (schema identifier permanently
frozen, no "may later be replaced" language). See
`docs/architecture/S1_4_JSON_CONFIGURATION_IMPLEMENTATION_REPORT.md` for the frozen implementation
record, qualification evidence, and final freeze disposition.
