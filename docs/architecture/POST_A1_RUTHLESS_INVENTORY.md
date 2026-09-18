# Post-A1 Ruthless Inventory of fastDICOMstructure

> **Public-release redaction note (2026-09-17):** local development-machine absolute paths below
> have been replaced with `/path/to/...` placeholders. Value-level substitution only — reported
> commands and results are otherwise unchanged.

**Status: ANALYSIS ONLY.** No production code in this repository, or in `fastDICOMattrs`, was
implemented, refactored, deleted, renamed, or modified to produce this report. See section 20 for
an explicit accounting.

Performed against `fastDICOMstructure` at `63970e5` ("Rebuild as a thin consumer of
fastDICOMattrs (A0 semantic-engine extraction)"), evaluated against `fastDICOMattrs` frozen at
`46bf7d3` (A1.7, A1 capability progression COMPLETE).

## 1. Executive verdict

The A0 extraction already did its job correctly: **no DICOM semantic leakage was found** anywhere
in this repository. Every byte of DICOM parsing, VR/charset interpretation, mutation mechanics,
and serialization already lives in `fastDICOMattrs`; nothing here reimplements it. This is a
smaller, cleaner repository than the authorization's framing anticipated (~1,000 lines of
production+test+example Python, no C++, no build system of its own).

The finding is therefore not "delete most of it" — it is **"most of it is architecturally sound
but stale and narrow relative to what attrs A1.7 now provides."** `policy.py`'s shape (a closed
operation vocabulary, composed into a named/versioned `Policy`, executed by one `apply()`
function returning a `PolicyResult`) is the right nucleus for the product and should be kept. Its
five operations, however, were written against pre-A1.7 attrs and only ever address a bare
top-level-or-everywhere `(group, element)` tag — none of them can target a specific nested
location, none of them use attrs' charset-aware text mutation, and none of them can insert a
missing attribute. Widening every operation to use attrs' current path/VR/charset surface is
**substantial, necessary rework**, but it is a rewrite of five classes against a now-richer
dependency, not a rescue from a bad design.

The single most consequential finding, independent of code quality: **`policy.py` currently has
zero production callers.** The repository's own flagship example (`pipeline_demo.py`) bypasses it
in favor of hand-rolled `Structure` calls, and the one real external consumer this analysis could
inspect — `fastDICOMgateway`'s `transform.py` — also bypasses it, hand-rolling the identical
`erase_recursive`/`set_value_recursive`/`erase_private` sequence `policy.py` exists to replace.
The policy abstraction is tested, self-consistent, and provably equivalent to that imperative
sequence (`test_apply_reproduces_gateway_demo_policy`) — but nothing in production actually uses
it yet. That is the real gap this analysis surfaces, more than any semantic-boundary violation.

## 2. Repository/baseline state

| Item | Value |
|---|---|
| Repository | `/path/to/fastDICOMstructure` |
| HEAD | `63970e5` — "Rebuild as a thin consumer of fastDICOMattrs (A0 semantic-engine extraction)" |
| Branch | `main` |
| Working tree | clean (no local modifications) |
| Dependency | `fastDICOMattrs`, located via `FASTDICOMATTRS_REPO` (sibling-checkout convention), frozen at `46bf7d3` for this analysis |
| Build system | none — pure Python, no C++, no CMake, no compiled artifact of its own |
| Test runner | `pytest` (also plain `unittest discover`) |
| Test baseline | **12/12 passing** against attrs `46bf7d3` (see section 2a) |
| Package layout | `python/fastdicomstructure/{__init__.py, policy.py}`, `python/examples/pipeline_demo.py`, `tests/python/{test_policy.py, test_pipeline_demo.py}` |
| CI | `.github/workflows/ci.yml` — checks out both repos, builds attrs' library only (`FDS_BUILD_TESTS=OFF FDS_BUILD_BENCH=OFF FDS_BUILD_ABI=ON`), runs `pytest`. Correct and current — the one piece of infrastructure already fully reflects the post-A0 shape. |
| Packaging | none (`pyproject.toml`/`setup.py` absent — imported via `PYTHONPATH`/`sys.path` manipulation only) |
| CLI surface | none |

### 2a. Test run evidence

```text
$ FASTDICOMATTRS_REPO=/path/to/fastDICOMattrs python3 -m pytest tests/python -v
collected 12 items
tests/python/test_pipeline_demo.py::PipelineAcceptanceTest::test_diagnostic_bearing_input_is_rejected_before_policy_or_persistence PASSED
tests/python/test_policy.py::PolicyResultSemanticsTest::test_accept_when_no_operation_changes_anything PASSED
tests/python/test_policy.py::PolicyResultSemanticsTest::test_reject_when_required_tag_is_absent PASSED
tests/python/test_policy.py::PolicyResultSemanticsTest::test_replace_recursive_with_callback_is_rejected_at_construction PASSED
tests/python/test_policy.py::PolicyResultSemanticsTest::test_replace_with_callback_non_recursive PASSED
tests/python/test_policy.py::PolicyResultSemanticsTest::test_transform_when_an_operation_changes_something PASSED
tests/python/test_policy.py::PolicyNestedStructureTest::test_allow_list_prune_keeps_only_listed_tags_at_every_depth PASSED
tests/python/test_policy.py::PolicyNestedStructureTest::test_private_tag_policy_reaches_nested_private_element PASSED
tests/python/test_policy.py::PolicyNestedStructureTest::test_recursive_remove_reaches_nested_occurrence PASSED
tests/python/test_policy.py::PolicyNestedStructureTest::test_replace_recursive_reaches_every_occurrence_with_one_value PASSED
tests/python/test_policy.py::PolicyDeterminismTest::test_repeated_independent_execution_is_identical PASSED
tests/python/test_policy.py::PolicyReproducesGatewayDemoTest::test_apply_reproduces_gateway_demo_policy PASSED
============================== 12 passed in 0.08s ==============================
```

Nothing failed. attrs A1.7's additions (path-aware mutation, `insert`/`insert_text`, `iter_elements`)
are purely additive to the surface `policy.py` already used (`get`/`erase`/`erase_recursive`/
`set_value`/`set_value_recursive`/`erase_private`/iteration) — none of it was removed or changed
shape, so nothing here broke.

## 3. Current dependency map

```text
fastDICOMgateway (sibling repo, execution shell: HTTP/Cloud Run/container ingestion service)
        |  imports `fastdicomstructure as fds`, but calls attrs primitives
        |  (erase_recursive/set_value_recursive/erase_private) directly --
        |  NOT policy.py's Policy/apply (see section 4a)
        v
fastDICOMstructure  (THIS repository -- 63970e5)
        |  python/fastdicomstructure/__init__.py re-exports fastdicomattrs'
        |  public surface + adds `policy` submodule
        v
fastDICOMattrs (46bf7d3, frozen) -- DICOM semantic engine: parse, dictionary,
        |                          charset, mutation, ABI, Python bindings
        v
   raw DICOM bytes
```

`fastDICOMscan` (an unrelated, independent DCMTK-backed shallow probe, per `fastDICOMattrs`'
README) is not a dependency in either direction and is out of scope here.

**Import-level dependency**: `fastdicomstructure/__init__.py` locates a sibling `fastDICOMattrs`
checkout via `FASTDICOMATTRS_REPO` (default: sibling directory), inserts its `python/` directory
onto `sys.path`, and imports `read, read_buffer, Structure, Element, Item, Diagnostic, FdsError,
StaleElementError, WriteStats` from it verbatim (re-exported, not wrapped or subclassed).

**A concrete staleness gap already visible from this list**: attrs' A1.7 `__all__` also exports
`VRRequiredError`, `AlreadyExistsError`, `UnrepresentableCharacterError`, `InvalidUnicodeInputError`
(new in A1.7) — none of these four names are re-exported here. A consumer that only
`import fastdicomstructure as fds` (not `fastdicomattrs` directly) cannot catch these new
exception types by their `fds.`-qualified name today. This is narrow (four names) and mechanical,
not architectural, but it is a real, present gap — the re-export list has not been updated since
A1.7 landed. New instance *methods* on `Structure` (`find`, `insert`, `insert_text`, `set_text`,
`decode_text`, `iter_elements`) require no re-export change and are already available on any
`Structure` obtained through this package, since the class itself is re-exported unmodified.

## 4. Capability inventory

| Capability | Implemented where | Public API | Tests | Attrs now provides the same primitive? | Legitimate structure-layer value added | Currently used by anything? |
|---|---|---|---|---|---|---|
| Re-export attrs' read/inspect/mutate/write surface | `__init__.py` | `fastdicomstructure.{read,read_buffer,Structure,...}` | indirectly (via policy/pipeline tests) | N/A — this *is* attrs' API | Import-path compatibility for existing consumers | Yes — `test_policy.py`, `test_pipeline_demo.py`, `fastDICOMgateway` |
| Declarative policy composition (`Policy`, `PolicyOperation`) | `policy.py` | `policy.Policy`, `policy.apply` | `test_policy.py` (10 tests) | No — attrs has no policy concept, by design | Yes — this is the actual product nucleus | **No production caller** (see 4a) |
| `Require` (presence gate) | `policy.py` | `policy.Require` | yes | `tag in structure` (attrs `__contains__`) | Yes — reject-on-absence is a policy decision | Test-only |
| `Remove` (by tag, root or recursive) | `policy.py` | `policy.Remove` | yes | `erase`/`erase_recursive` | Yes, but tag-only (see 6) | Test-only |
| `Replace` (by tag, literal or non-recursive callback) | `policy.py` | `policy.Replace` | yes | `set_value`/`set_value_recursive` | Yes, but raw-bytes-only and tag-only (see 6) | Test-only |
| `AllowListPrune` | `policy.py` | `policy.AllowListPrune` | yes | No direct attrs primitive for "prune by set" | Yes — genuine policy composition | Test-only |
| `PrivateTagPolicy` | `policy.py` | `policy.PrivateTagPolicy` | yes | `erase_private` | Marginal — thin wrapper, but the *name* is a policy decision | Test-only |
| Recursive tag discovery (`_collect_tags`) | `policy.py` (private) | none (internal helper) | indirectly, via `AllowListPrune`'s tests | **Yes** — `Structure.iter_elements(recursive=True)` (A1.7) | No remaining value — pure duplication of a now-native capability | `AllowListPrune` only |
| Ingestion-pipeline demonstration | `pipeline_demo.py` | script, not a library API | `test_pipeline_demo.py` | N/A (calls attrs directly, not via policy.py) | Demonstrates a hand-rolled, non-declarative pipeline | Runnable example only |
| Fixed hard-coded transformation policy (remove PatientName, hash PatientID, strip private) | `pipeline_demo.py::apply_transformation_policy` | none — inline function | yes | attrs primitives directly | This *is* policy content, expressed imperatively rather than via `policy.py` | Example only |
| Audit record of a pipeline run | `pipeline_demo.py` (a plain `dict`) | none | indirectly | N/A | Ad hoc, not a reusable type | Example only |
| Round-trip self-verification | `pipeline_demo.py::verify_round_trip` | none | yes | Reparse is an attrs primitive; the *assertions* are policy-specific | Legitimate — "did the policy actually do what it claimed" | Example only |
| JSON/declarative configuration | **absent** | — | — | N/A | — | — |
| CLI / stdin-stdout orchestration | **absent** | — | — | N/A | — | — |
| Audit/result object distinct from the mutated `Structure` | Partially — `PolicyResult` | `policy.PolicyResult` | yes | N/A | Yes, already a reasonable shape (see 10) | Test-only |
| Input/output adapters (file, memory, stream) | **absent here** — inherited unchanged from attrs' `read`/`read_buffer`/`write`/`write_bytes` | re-exported | N/A | Yes, fully | None added at this layer yet | via re-export |

### 4a. The zero-production-caller finding, in detail

`fastDICOMgateway/src/fastdicom_gateway/transform.py` imports `fastdicomstructure as fds` and
calls, directly, in `_apply_demo_policy`:

```python
touched += structure.erase_recursive(_TAG_PATIENT_NAME)
touched += structure.set_value_recursive(_TAG_PATIENT_ID, _DEMO_PATIENT_ID)
touched += structure.erase_recursive(_TAG_PATIENT_BIRTH_DATE)
private_removed = structure.erase_private()
```

This is exactly the sequence `test_policy.py::PolicyReproducesGatewayDemoTest` reproduces
independently to prove `policy.apply()` computes an equivalent result — but the gateway's own
production code was never switched over to call `policy.apply()` itself. Nothing is broken by
this (both paths are attrs-primitive-correct), but it means the declarative abstraction this
repository exists to provide is, today, an island: built, tested, proven equivalent to the
imperative alternative, and used by nobody outside its own test suite.

## 5. Component-by-component classification

| Component | Current responsibility | Classification | Why | Replacement/target |
|---|---|---|---|---|
| `__init__.py` re-export list (8 names) | Compatibility shim onto attrs' public surface | **A. RETAIN** (mechanism) / needs a 4-name update | The shim pattern is exactly right; it is simply one increment stale | Add `VRRequiredError`, `AlreadyExistsError`, `UnrepresentableCharacterError`, `InvalidUnicodeInputError` to the import/`__all__` list |
| `_add_fastdicomattrs_to_path` | Sibling-checkout resolution | **A. RETAIN** | Correct, minimal, mirrors the established family convention one level up | none |
| `Tag`, `_format_tag`, `Decision`, `OperationResult`, `Diagnostic`, `PolicyResult` (policy.py architecture, ~90 lines) | Result/vocabulary types for policy evaluation | **A. RETAIN** | Clean, minimal, no DICOM semantics, genuinely policy-layer concepts | none structurally; `Tag` should grow into a path-capable locator type (see section 6) without discarding the shape |
| `PolicyOperation` base + `Policy` dataclass + `apply()` | Composition and execution model | **A. RETAIN** | The right shape: closed operation list, explicit order, one entry point | none structurally; `apply()`'s no-transactionality limitation is honest and acceptable for V1 (see section 7) |
| `Require` | Presence gate | **B. SIMPLIFY** | Correct today; needs to accept a path (or wildcard path), not just a root-scoped bare tag, to be useful against nested content | Extend to accept `ElementPath`-shaped targets |
| `Remove` | Tag-based removal, root or fully recursive | **B. SIMPLIFY** | Same limitation — cannot target "this tag, but only inside Sequence X" | Extend to accept a path/path-pattern; keep the fully-recursive default as the common case |
| `Replace` | Tag-based raw-bytes replacement | **B. SIMPLIFY** | Raw-bytes-only, tag-only, and its callback restriction (no recursive callback) was a genuine attrs-side limitation *pre-A1.7* that A1.7's `iter_elements`+per-path `set_value` now resolves | Add a path-capable raw variant and a Unicode-aware variant built on attrs' `set_text`; lift the recursive-callback restriction by iterating paths explicitly instead of calling `set_value_recursive` |
| `AllowListPrune` | Prune-by-tag-set, whole tree | **B. SIMPLIFY** (logic) / **C. REPLACE WITH ATTRS** (its traversal helper) | The *policy* ("keep only these tags") is legitimate structure-layer content; its internal traversal is not | Keep the operation; replace `_collect_tags` with `Structure.iter_elements(recursive=True)` |
| `PrivateTagPolicy` | Wraps `erase_private()` | **A. RETAIN** (thin, correct) | It's a one-line wrapper today because `erase_private` is already exactly what a blanket private-tag policy needs; giving it a name in the policy vocabulary is legitimate even though the implementation is trivial | Leave as-is; a creator-allowlist variant is a **F. MISSING** item, not a defect in what exists |
| `_collect_tags` | Recursive tag-set discovery via hand-rolled `Element.items()`/`Item.__iter__` walk | **C. REPLACE WITH ATTRS** | attrs A1.7's `Structure.iter_elements(recursive=True)` is the native, C++-backed equivalent; this Python-level reimplementation predates it and is not needed once `AllowListPrune` calls the native traversal | `Structure.iter_elements(recursive=True)` |
| `pipeline_demo.py` (structural parse/inspect, persist, verify) | End-to-end example calling attrs directly | **A. RETAIN** | A legitimate, working, already-tested example of building a pipeline directly on attrs without the policy DSL — the repository's own `docs/architecture.md` explicitly calls this a deliberate, valid alternative | none required; see 4a for the product-alignment observation |
| `pipeline_demo.py::apply_transformation_policy` | Hard-coded imperative policy content | **E. MOVE (conceptually) / F. MISSING (a declarative sibling)** | Not wrong, but it is exactly the shape `policy.py` was built to replace, and it is the repository's only "here is what a real transformation looks like" artifact — it currently teaches the imperative style, not the declarative one this product is meant to differentiate on | Add a second example driving the same outcome through `policy.Policy`/`apply` (and, once it exists, JSON config) alongside this one — do not delete the imperative version, since "both are legitimate" per the existing architecture doc |
| `test_policy.py` | Policy-layer qualification (10 tests) | **B. SIMPLIFY** (follows policy.py) | Genuine policy-behavior tests, not attrs-semantic tests; they will need extending (not replacing) alongside the operations they test | Add path-targeting/charset-aware test cases as those operations grow |
| `test_pipeline_demo.py` | One acceptance test for the demo | **A. RETAIN** | Small, correct, tests real behavior (rejection on diagnostic-bearing input) | none |
| `initial_requirements.txt` | Pre-split historical charter | **A. RETAIN as labeled history** (optional **E. MOVE** to `docs/history/`) | README already correctly frames it as historical, not current scope; deleting it destroys provenance for no benefit | Optionally relocate under `docs/` for tidiness; not urgent |
| `CONTRIBUTING.md` | Contributor build/test instructions | **D. DELETE (content) / rewrite** | Describes a `cmake`/`ctest`/`corpus.py`/`docs/corpus-results.md`/`tests/fixtures/README.md`/`requirements-dev.txt` workflow — **none of which exist in this repository post-A0**. This is actively misleading to a new contributor today. | Rewrite to match the actual `pytest tests/python` / `FASTDICOMATTRS_REPO` workflow already correctly documented in `README.md` and `.github/workflows/ci.yml` |
| `SECURITY.md` | Vulnerability disclosure policy | **A. RETAIN** | Generic, accurate, needs nothing | none |
| `README.md`, `docs/architecture.md` | Project description / architecture | **A. RETAIN** | Both already correctly reflect the post-A0 state; both are honest about `pipeline_demo.py` bypassing `policy.py` | Update only incidentally (the `__init__.py` re-export list they describe) when that shim is refreshed |
| `.github/workflows/ci.yml` | CI | **A. RETAIN** | Already fully correct for the post-A0 shape | none |
| C++ code | — | **N/A** | None remains; fully and correctly extracted to attrs at A0 | — |

## 6. Semantic duplication / leakage findings

**Finding: none of substance.** This is the headline result of Step 4's search. Every operation in
`policy.py` is built exclusively from `Structure`'s existing public primitives
(`get`/`erase`/`erase_recursive`/`set_value`/`set_value_recursive`/`erase_private`/iteration) —
there is no raw byte interpretation, no VR interpretation, no Implicit-VR logic, no dictionary
lookup, no charset interpretation, no sequence-parsing logic, no private-creator resolution
reimplementation, no Pixel Data handling, no padding logic, and no serialization logic anywhere in
this repository. `pipeline_demo.py` is the same story: it calls `structure.get`/`erase`/
`set_value`/`erase_private`/`write_with_stats` and nothing else DICOM-shaped.

The one item that came close is `_collect_tags` — not because it *misunderstands* DICOM structure
(it walks `Sequence`/`Item` correctly, using only attrs' own public accessors), but because it is a
**traversal reimplementation that attrs itself now performs natively** (`iter_elements`). This is
not "structure implementing HOW DICOM works" in the sense the audit was watching for (no VR/charset/
padding knowledge is embedded in it) — it is closer to "structure solving a problem attrs has since
solved better," which is why it is classified `C. REPLACE WITH ATTRS` rather than flagged as a
boundary violation.

**Conclusion for Step 4**: the A0 extraction was executed cleanly and has held. The work remaining
is not a boundary correction — it is catching the *policy vocabulary's* expressiveness up to what
the now-complete attrs substrate makes possible (nested targeting, VR-optional insertion,
charset-aware text mutation), which is ordinary product development, not architecture repair.

## 7. `policy.py` detailed audit

Function/class-by-function breakdown of what kind of logic each piece contains:

| Element | Genuine policy logic | DICOM semantic logic | Traversal logic | Mutation mechanics | Configuration logic | Error handling | Orchestration |
|---|---|---|---|---|---|---|---|
| `Tag` / `_format_tag` | — | trivial formatting only | — | — | — | — | — |
| `Decision` | policy outcome vocabulary | — | — | — | — | — | — |
| `OperationResult` / `Diagnostic` / `PolicyResult` | result modeling | — | — | — | — | — | — |
| `PolicyOperation` (base) | interface | — | — | — | — | — | — |
| `Require.apply` | yes (presence gate) | — | — | — (read-only) | — | none (never fails; produces a result the caller interprets) | — |
| `Remove.apply` | yes (which tag, how broadly) | — | delegates to attrs | delegates to attrs | — | none | — |
| `Replace.apply` | yes (which tag, literal-or-callback) | — | delegates to attrs | delegates to attrs | — | `__post_init__` validates the callback/recursive combination — genuine, useful, minimal | — |
| `AllowListPrune.apply` | yes (which tags survive) | — | **owns its own** (`_collect_tags`) | delegates to attrs (`erase_recursive`) | — | none | — |
| `PrivateTagPolicy.apply` | yes (whether to strip) | — | delegates to attrs | delegates to attrs | — | none | — |
| `Policy` (dataclass) | ordering/naming/versioning | — | — | — | none (Python objects, not a config format) | — | mild (`operations` tuple materialization) |
| `apply()` | yes (short-circuit-on-reject) | — | iterates the operation list | — | — | builds the one modeled `Diagnostic` | yes — this *is* the orchestration entry point |

**What the module would look like rewritten against frozen attrs** (description only, not
implemented, per instruction):

- `Tag = tuple[int, int]` widens into something that can also carry a nested locator — either a
  thin structure-owned wrapper type that can represent "a bare tag" (today's shape, still the
  common case) *or* "a container-locator + tag" *or* "a wildcard path pattern" (see section 9),
  translated into one or more concrete `fastdicomattrs.ElementPath`/`(parent, tag)` calls at
  execution time. Attrs' own `ElementPath` need not appear as the policy-authoring surface —
  structure should own the friendlier shape (section 9).
- `Require`, `Remove` stay conceptually identical but accept that widened locator; their `apply()`
  bodies grow a small "does this locator name one tag, or does it expand to N via a wildcard"
  branch, still delegating every actual DICOM operation to attrs.
- `Replace` splits into (at minimum) a raw-bytes variant (today's, generalized to a locator) and a
  Unicode-text variant built on `Structure.set_text`/`decode_text` — because attrs A1.6/A1.7 now
  make the charset-correct path trivial to call, and a de-identification policy overwhelmingly
  wants to write human text ("ANONYMOUS"), not pre-encoded, pre-padded bytes. The `recursive=True`
  + callback restriction disappears: with `iter_elements(recursive=True)` available, a "recursive
  callback replace" can be implemented correctly (call the callback once per discovered path, with
  that occurrence's own original value) instead of being refused outright.
- `AllowListPrune` keeps its exact policy semantics; `_collect_tags` is deleted and replaced by a
  call to `Structure.iter_elements(recursive=True)`.
- `PrivateTagPolicy` gains an optional creator-allowlist mode now that it's cheap to build (attrs'
  A1.7 nested `find`/`resolve_private_creator` — noting `resolve_private_creator` itself has no
  Python binding yet, see section 8's ownership table and the "genuinely missing" caveat) — or
  stays exactly as-is if that refinement is judged not worth it for V1; either is defensible.
- A new operation kind is very likely warranted: an upsert-shaped **Ensure**/**Insert** action
  ("set this tag to this value whether or not it currently exists, inferring VR when safe") — the
  de-identification stress case in Step 7 below needs this (e.g., inserting
  `(0012,0062) PatientIdentityRemoved = YES`), and it did not exist before because attrs itself had
  no nested insert primitive before A1.7.
- `apply()`'s orchestration shape (iterate, short-circuit on failed `Require`, aggregate results)
  is unchanged — it was already correct and attrs-agnostic.

**Direct answer to the question asked**: `policy.py` **contains the nucleus of the desired
product** — the `Policy`/`PolicyOperation`/`apply`/`PolicyResult` shape is exactly right and
should not be discarded or redesigned. It does **not**, however, contain a policy architecture rich
enough to be the *destination* — its concrete operations are narrower than what attrs now supports,
narrower than the stated product goals (path-targeting "regardless of nesting," de-identification),
and it has no configuration-loading, execution, or audit layer around it yet. Retaining it does not
constrain a cleaner architecture; it is the correct foundation for one, provided its five operations
are treated as "V1's starting vocabulary, due for extension," not as a frozen contract.

## 8. Proposed attrs/structure ownership boundary

| Concern | Owner | Notes |
|---|---|---|
| Tag identification | **attrs** | `Tag`, dictionary lookup |
| Keyword resolution | **neither, today** | attrs deliberately deferred keyword-string addressing to a later increment (A1.7 report, section "APIs that should not be added"); structure has no keyword layer either. Genuinely absent, not a boundary question yet. |
| VR semantics | **attrs** | dictionary VR, ambiguity, inference policy |
| Charset semantics | **attrs** | resolution, decode, encode |
| Recursive element discovery | **attrs** | `iter_elements`/`visit` — structure should stop hand-rolling this (section 6) |
| Private creator identity | **attrs** | `resolve_private_creator` (C++/native only — no Python binding exists yet; see the caveat below) |
| Value decoding | **attrs** | `decode_text`, raw `.value` |
| Value encoding | **attrs** | `encode_text` (internal), `set_text`/`insert_text` |
| Raw mutation | **attrs** | `set_value`, `insert` |
| Semantic text mutation | **attrs** | `set_text`, `insert_text`, `decode_text` |
| Nested insertion/removal | **attrs** | `insert`/`insert_text` (absent-only), `erase` (any depth) |
| Serialization | **attrs** | `write`/`write_bytes`(`_with_stats`) |
| Pixel Data preservation | **attrs** | by reference, never decoded — structure inherits this for free by never touching Pixel Data |
| Policy matching | **structure** | condition evaluation over attrs-supplied facts |
| Policy conditions | **structure** | tag/path/VR/private-creator-identity/charset-mode predicates |
| Policy actions | **structure** | `Require`/`Remove`/`Replace`/`AllowListPrune`/`PrivateTagPolicy`/(missing) `Ensure` |
| Recursive policy application | **structure** | orchestrates attrs' recursive primitives; owns no traversal algorithm of its own once `_collect_tags` is retired |
| De-identification rules | **structure** (policy *content* is the caller's, per `policy.py`'s own stated design — see section 9) | attrs supplies every mechanic needed |
| Configuration parsing | **structure** (does not exist yet) | JSON/DSL is presentation, belongs here, never in attrs |
| Input adapters | **structure**, thin wrappers over attrs' `read`/`read_buffer` | none exist yet beyond direct re-export |
| Output adapters | **structure**, thin wrappers over attrs' `write`/`write_bytes` | same |
| Audit/event reporting | **structure** | `PolicyResult` already a reasonable start |
| Error aggregation | **structure** | `PolicyResult.diagnostics`, currently one modeled reason (`Require` failure) |
| Execution orchestration | **structure** (core) / **fastDICOMgateway and future adapters** (shell) | see section 11 |

**Caveat on Private Creator**: `resolve_private_creator` is a frozen, tested attrs capability
(A1.2) with **no C ABI or Python binding** — confirmed by inspecting `abi/include/fastdicomattrs_c/
fds.h` and `python/fastdicomattrs/__init__.py` in the attrs repository; this is a pre-existing gap
(already noted in attrs' own A1.7 freeze report, section 28, as "not new A1.7 debt," a Path A
candidate for attrs itself). It is **not** a structure-side leakage or omission — structure simply
cannot reach a capability attrs has not yet exposed to Python. If a creator-aware `PrivateTagPolicy`
variant becomes a real product requirement, that is a **genuine missing attrs capability that
blocks structure** (flagged honestly here, not manufactured for convenience — see the final
response's item 7).

The dependency direction is clean throughout: nothing above requires attrs to know about `Policy`,
`Decision`, JSON, or any policy concept — every attrs-owned row is expressed purely in terms of
tags, paths, VRs, and bytes/Unicode text.

## 9. Candidate policy model

The existing five-operation vocabulary (`Require`, `Remove`, `Replace`, `AllowListPrune`,
`PrivateTagPolicy`) is evaluated, not discarded. Recommended minimal V1 vocabulary, building on it:

- **`Require(locator)`** — unchanged in spirit; `locator` widens from bare `Tag` to "tag, optionally
  under a container path or wildcard pattern."
- **`Remove(locator)`** — same widening. The existing `recursive: bool` flag becomes redundant once
  locators can already express "everywhere" (today's default) vs. "this exact nested spot" vs. "any
  Item of this Sequence" (a wildcard) — one locator concept subsumes the current boolean.
- **`Replace(locator, value)`** — split into raw-bytes and Unicode-text forms (or one operation with
  a `text: bool` discriminant), both locator-capable, the text form always calling attrs' `set_text`.
- **`Ensure(locator, value, vr=None)`** *(new — MISSING today)* — set-or-insert: replace if present,
  insert (explicit or attrs-inferred VR) if absent. The direct policy-layer analogue of attrs'
  documented "compose `find` + `set_value`/`insert`" idiom (attrs deliberately has no upsert
  primitive of its own — see its A1.7 report, section 5 — so this composition is exactly the kind
  of orchestration structure, not attrs, should own).
- **`AllowListPrune(tags)`** — unchanged semantics; internals retarget to `iter_elements`.
- **`PrivateTagPolicy(remove, creator_allowlist=None)`** — unchanged for V1; the optional allowlist
  is explicitly a **MISSING**, not a defect, and is blocked on attrs Python-exposing
  `resolve_private_creator` (section 8).

This is deliberately **not** a bigger vocabulary than this. A generic "run arbitrary user code"
action (beyond `Replace`'s existing bytes-callback hook) is explicitly not recommended — `policy.py`'s
own stated design principle ("if a use case needs a sixth kind, revisit this module, not subclass
around it") remains sound advice.

### De-identification stress case, walked through

> recursively inspect all attributes → determine whether policy applies → remove / replace /
> preserve / insert → preserve unrelated data → serialize correctly

Every step maps onto an attrs-supplied mechanic plus a structure-owned decision:

1. **Recursively inspect** — `Structure.iter_elements(recursive=True)` (attrs, native).
2. **Determine whether policy applies** — structure-owned condition evaluation over the
   `(tag, path, vr, is_private, resolved_creator?)` facts attrs' iteration/inspection already
   exposes per element.
3. **Remove/replace/preserve** — `Remove`/`Replace` locators, as above; "preserve" requires no code
   (not touching an element already preserves it, exactly as `pipeline_demo.py`'s own comment
   already states).
4. **Insert** — the new `Ensure` action, or the current `Remove`+manual `Structure.insert` if
   `Ensure` is deferred.
5. **Preserve unrelated data** — a property of attrs' mutation primitives already proven in A1.7's
   own qualification (non-interference tests); structure inherits this for free by construction —
   it never touches anything its policy didn't name.
6. **Serialize correctly** — `Structure.write`/`write_bytes` (attrs, unchanged).

**Nothing genuinely missing from attrs blocks this stress case.** The one deliberately-not-invented
requirement is Private-Creator-aware allowlisting (section 8's caveat) — real, but narrow, and not
required for a basic, correct de-identification policy (a blanket `PrivateTagPolicy(remove=True)`
already handles the common "strip all private data" case attrs' own A1.7 corpus regression already
validated against 23,000+ real files).

## 10. Declarative JSON configuration analysis

**Nothing exists today** — no JSON/YAML loader, no schema, no CLI that consumes one. This is a pure
**F. MISSING** category, evaluated here as a design probe only, per the explicit instruction not to
implement it.

Minimum concepts needed: policy `name`/`version`; an ordered `operations` list; each operation an
`action` discriminant plus action-specific fields (`tag`, `path`/`pattern`, `vr`, `value`,
`recursive`/wildcard shape, `creator` for a future private-creator-aware action); a top-level
`on_error`/`failure` field describing what an unsatisfied `Require` should do (today: always reject
— the JSON layer could make this explicit rather than implicit).

**attrs' `ElementPath` should not appear directly in JSON.** attrs' path shape (a list of
`{tag, item_index}` steps, with two incompatible meanings depending on whether the last step's
index is present — see attrs' own `element_path.hpp`/A1.7 report section 4) is a precise, C++-
shaped contract that is unnecessarily awkward to hand-author and provides no wildcard concept at
all (a real path names one concrete Item, never "every Item"). Structure should own a
JSON-friendlier path DSL — a list of `{tag: [g, e], item: <int> | "*"}` steps — and translate it
into one or more concrete attrs `ElementPath`/`(parent, tag)` calls at execution time (expanding
`"*"` by first discovering how many Items actually exist, via `Structure.find`+`Element.items()` or
`iter_elements`). This keeps attrs' path contract exactly as frozen and gives structure exactly the
presentation flexibility a configuration format needs.

### Design probes (illustrative only — not a committed schema)

**1. Simple top-level policy** (tests the minimal shape):

```json
{
  "name": "strip-patient-name",
  "version": "1.0.0",
  "operations": [
    {"action": "remove", "tag": [4112, 16]}
  ]
}
```

**2. Nested transformation** (tests the wildcard path DSL from section 10's ownership discussion):

```json
{
  "name": "redact-referring-physician-in-every-beam",
  "version": "1.0.0",
  "operations": [
    {
      "action": "remove",
      "path": [
        {"tag": [12298, 176], "item": "*"},
        {"tag": [8, 144]}
      ]
    }
  ]
}
```

(`[12298, 176]` = `(300A,00B0)` BeamSequence, `[8, 144]` = `(0008,0090)` ReferringPhysicianName —
"remove this tag from every Item of this Sequence, wherever it appears," expanding `"*"` at
execution time into one concrete `Remove` per discovered Item.)

**3. Privacy / de-identification** (tests `Ensure`, private-tag policy, and text-aware replace
together):

```json
{
  "name": "basic-deidentification",
  "version": "1.0.0",
  "operations": [
    {"action": "remove", "tag": [16, 16]},
    {"action": "replace_text", "tag": [16, 32], "vr": "LO", "value": "ANONYMOUS"},
    {"action": "private_tag_policy", "remove": true},
    {"action": "ensure", "tag": [18, 98], "vr": "CS", "value": "YES"}
  ]
}
```

(`[16,16]` = PatientName removed; `[16,32]` = PatientID replaced with literal text, charset-correct
via attrs' `set_text`; all private data stripped; `[18,98]` = `(0012,0062)` PatientIdentityRemoved
inserted-or-set to `"YES"` — a real, standards-appropriate attribute for exactly this use case.)

These three probes are sufficient to validate that the proposed vocabulary (section 9) and path DSL
cover a simple case, a nested case, and the de-identification stress case without inventing a large
configuration language.

## 11. Input/output/execution boundary

**Today**: structure has no execution layer of its own. `pipeline_demo.py` is a script, not a
reusable adapter; `fastDICOMgateway` is the one real execution shell in the family, and it already
sits exactly one level above structure in the intended dependency diagram, currently calling attrs
primitives directly rather than through `policy.py`.

**Core engine vs. execution adapters** — the split this analysis recommends:

- **Core** (`fastdicomstructure.policy` and whatever configuration loader is eventually added):
  takes an already-open `fastdicomattrs.Structure` and a `Policy`, returns a `PolicyResult`, and
  otherwise knows nothing about files, sockets, containers, or clouds. This already describes
  `policy.apply()` exactly as it exists today — it is deployment-neutral by construction, with zero
  changes needed to keep it that way.
- **Adapters** (new, not yet built): thin functions/CLIs that turn "a file path in, a policy
  reference in" into "a file path out, a `PolicyResult` out" — one for local file I/O
  (`fastdicomattrs.read`/`write` directly), one that `fastDICOMgateway` could eventually call
  instead of hand-rolling policy content, and, later, one for streaming/serverless invocation. None
  of these need to exist for V1; the point is only that `policy.apply()`'s existing shape already
  supports building them without any change to the core.

**Streaming**: explicitly not recommended for V1 (per instruction, and because attrs itself has no
streaming input yet — `fds_parse_stream` is an acknowledged stub in attrs' own ABI design doc).
Deployment neutrality for V1 is achieved simply by the core engine never importing anything
file-system- or network-shaped — true today, and cheap to keep true.

**The design goal stated in the prompt — "the same policy operates unchanged whether invoked
locally, from CLI, from a container, from a cloud function, from a service" — is already
structurally achievable with zero core-engine change**, precisely because `policy.apply(structure,
policy)` takes an in-memory object and returns an in-memory result; every one of those invocation
contexts differs only in how the `Structure` got constructed and where the result goes afterward,
both of which are already attrs' concern (`read`/`read_buffer`/`write`/`write_bytes`), not
structure's.

## 12. Error and audit model

**Today**: `PolicyResult` (decision, per-operation `OperationResult` tuple, `diagnostics` tuple,
policy name/version) is already a reasonable, proportionate audit object, separate from the mutated
`Structure` — exactly the separation the prompt asks about. Its one modeled failure reason is
"a required tag is absent."

**Minimum useful distinctions for V1**, most of which already exist or map directly onto an
existing attrs status:

| Outcome | Exists today? | Source |
|---|---|---|
| Policy matched / operation fired | yes | `OperationResult.count > 0` |
| Policy not matched (no-op) | yes | `OperationResult.count == 0`, `satisfied=True` |
| Required attribute missing | yes | `Require` → `Decision.REJECT` |
| Action applied | yes | `OperationResult` |
| Unsupported operation (e.g., a locator that doesn't resolve, or a VR-required insert with none given) | **partially** — today's operations mostly can't fail this way because they only wrap always-succeeding attrs primitives (`erase`, `set_value_recursive`); a new `Ensure`/path-aware operation calling attrs' `insert`/`insert_text` *can* fail (`AlreadyExistsError`, `VRRequiredError`, etc.) and needs a modeled `OperationResult`/`Diagnostic` outcome for that | **F. MISSING** |
| Malformed DICOM (parse-time) | yes, but deliberately kept separate | `Structure.diagnostics` (attrs), by the module's own explicit design choice not to merge the two diagnostic streams |
| Attrs semantic failure (e.g. `UnrepresentableCharacterError` from a text-aware `Replace`) | **no** | **F. MISSING** — needs a mapping from attrs' typed exceptions to a `Diagnostic` |
| Configuration error (malformed JSON policy) | N/A — no config loader exists yet | **F. MISSING**, deferred with the loader itself |
| Output failure | not modeled — `write`/`write_bytes` already raise `FdsError` on failure, uncaught | acceptable for V1 (the caller sees the exception) |

No enterprise logging framework is warranted or recommended — `PolicyResult`'s existing shape,
extended with a couple of new outcome kinds as new operations are added, is proportionate.

## 13. Test ownership analysis

| Test file/case | What it actually tests | Classification |
|---|---|---|
| `test_policy.py::PolicyResultSemanticsTest` (5 tests) | `Decision`/`OperationResult`/`Require`/`Replace` construction-time validation — genuine policy behavior | **Genuine structure-policy test — retain, extend as operations grow** |
| `test_policy.py::PolicyNestedStructureTest` (3 tests) | That `Remove`/`PrivateTagPolicy`/`AllowListPrune` correctly reach nested occurrences — genuine policy behavior, exercised *through* attrs' recursive primitives | **Genuine structure-policy test** — note these are simultaneously a light integration check that attrs' `erase_recursive`/`erase_private` behave as structure expects; that overlap is fine, not duplication, since the assertions are about *policy outcomes* (which tags survive), not about attrs' internal correctness |
| `test_policy.py::PolicyDeterminismTest` | Two independent applications of the same policy to two independently-parsed copies produce byte-identical output | **Genuine, valuable structure-level property test** — this is exactly the kind of "prove policy is deterministic" claim a de-identification tool needs and attrs' own test suite has no reason to cover |
| `test_policy.py::PolicyReproducesGatewayDemoTest` | Declarative policy vs. hand-rolled imperative sequence produce identical output | **Genuine, valuable — should be kept even after `fastDICOMgateway` (if ever) switches to calling `policy.apply()` directly**, as a permanent regression guard on that equivalence claim |
| `test_pipeline_demo.py` | One rejection-path test for the demo script | **Retain** — small, real, not attrs-duplicative |
| *(none currently)* | Exhaustive proof that Implicit VR parsing, charset decoding, or dictionary VR resolution work | **Correctly absent** — this repository does not and should not rebuild attrs' own qualification suite; attrs' A1.1–A1.7 freeze reports already own that evidence |
| *(missing)* | A policy applied to genuinely Implicit-VR-origin input, end to end, proving the *policy* behaves correctly regardless of source encoding | **F. MISSING** — this is the correct shape of integration test structure needs (attrs proved Implicit-VR mutation itself works in its own A1.7 report; structure has not yet proven a *policy* is encoding-agnostic) |
| *(missing)* | Path-targeted `Remove`/`Replace`/`Ensure` operations, once they exist | **F. MISSING**, follows directly from section 9 |
| *(missing)* | JSON config round-trip (parse → `Policy` → `apply` → expected result), once a loader exists | **F. MISSING**, deferred with the loader |

**No test in this repository duplicates attrs' own semantic qualification.** The existing suite
already draws the line correctly: unit-qualify policy *decisions*, integration-qualify that those
decisions, once executed through attrs, produce the expected DICOM bytes — never re-prove that
attrs' parser/charset/dictionary logic itself is correct.

## 14. LOC / deletion / simplification estimates

Meaningful production + test + example Python (excludes docs, CI/config, license, pytest cache):

| Bucket | Approx. LOC | % of ~1,013 total |
|---|---|---|
| `__init__.py` | 61 | 6% |
| `policy.py` — architecture (types, `Policy`, `apply`) | ~150 | 15% |
| `policy.py` — five operation classes + `_collect_tags` | ~206 | 20% |
| `pipeline_demo.py` | 243 | 24% |
| `test_pipeline_demo.py` | 18 | 2% |
| `test_policy.py` | 335 | 33% |
| **Total** | **~1,013** | **100%** |

Classification rollup:

| Classification | Approx. LOC | % |
|---|---|---|
| **A. RETAIN** (as-is or with a trivial mechanical update) | ~224 (`__init__.py` + policy architecture minus the small re-export fix + `test_pipeline_demo.py`) | ~22% |
| **B. SIMPLIFY** (correct shape, needs rework for path/VR/charset-awareness) | ~721 (five operation classes, `pipeline_demo.py`'s policy content as a design reference, `test_policy.py`) | ~71% |
| **C. REPLACE WITH ATTRS** | ~18 (`_collect_tags`) | ~2% |
| **D. DELETE** | 0 lines of production/test Python. (`CONTRIBUTING.md`'s stale build instructions are documentation, not counted here.) | 0% |
| **E. MOVE/REHOME** | 0 lines forced to move (`initial_requirements.txt`, 28 lines, is documentation and optional to relocate) | 0% |

**This does not match a "70% should disappear" pattern, and the honest finding is that it
shouldn't be forced to.** ~71% of the codebase needs substantial, real rework (every concrete
policy operation, and the tests that pin them) — but rework because the target (attrs' now-complete
capability) moved forward, not because the existing code is wrong, duplicative, or leaking DICOM
semantics. Only ~2% (`_collect_tags`) is outright superseded. Zero production code is dead or
duplicative enough to delete outright.

**Estimated size of the converged V1 core** (architecture retained + operations widened +
`Ensure` added + JSON loader + a handful of new tests, still no C++, no new attrs dependency
surface beyond what A1.7 already exposes): roughly **900–1,300 LOC** — similar in order of magnitude
to today's ~1,000, not a large expansion, because the growth (locator handling, `Ensure`, JSON
parsing) is offset by deleting `_collect_tags` and by every concrete operation getting *simpler*
per-operation once it can lean on `iter_elements`/`set_text`/`insert` instead of composing lower-
level primitives by hand.

## 15. Candidate Structure Contract v1

**fastDICOMstructure Contract v1 — CANDIDATE** (not authoritative; for review)

**Guarantees**:
- A `Policy` is an ordered, named, versioned, immutable list of operations from a closed
  vocabulary (section 9); evaluating the same policy against the same input twice produces
  identical output (already proven for the current vocabulary — `PolicyDeterminismTest`).
- `apply()` never mutates a `Structure` past the first unsatisfied `Require`; every operation
  before that point has already run (no rollback — an explicit, documented limitation, not a
  guarantee violation).
- Every operation's `PolicyResult` entry reports how many elements it touched, or whether a
  `Require` was satisfied; nothing about *what changed* is left for the caller to infer by diffing
  the structure.
- Policy authoring never requires knowledge of attrs' `ElementPath` step-shape rules; structure
  owns the presentation-level path/pattern syntax.

**Delegates entirely to attrs**: tag/VR/keyword identification (partial — keyword deferred, see
section 8), charset resolution/decoding/encoding, recursive traversal, private-creator identity,
raw and semantic mutation, nested insertion/removal, serialization, Pixel Data preservation.
Structure never re-implements any of these, and never will absent a demonstrated attrs gap.

**Supported policy concepts (V1)**: `Require`, `Remove`, `Replace` (raw and text), `Ensure`
(new), `AllowListPrune`, `PrivateTagPolicy`; locators are a bare tag, a concrete nested path, or a
wildcard-Item path pattern (section 10).

**Configuration responsibility**: structure owns any JSON/DSL surface end to end; attrs' public
API is never extended to understand policy concepts, ever.

**Execution responsibility**: structure's core (`policy.apply`) is deployment-neutral by
construction (in-memory `Structure` in, `PolicyResult` out); file/stream/container/cloud adapters
are separate, optional, built outside the core, and not required for V1.

**Result/audit behavior**: `PolicyResult` (decision, per-operation results, diagnostics,
policy identity) is the single, proportionate audit object; no external logging/reporting
framework.

**Explicit non-goals for V1**: pseudonymization/HMAC/UID-remapping/date-shifting content (`Replace`'s
callback hook is the caller's escape valve, exactly as documented today); a plugin/subclass
mechanism for new operation kinds; streaming input; multi-document/batch orchestration; a
CLI; keyword-string tag addressing (matches attrs' own V1 non-goal); creator-aware private-tag
allowlisting (blocked on an attrs Python binding gap, section 8).

## 16. Falsifiable product hypotheses

| Claim | Hypothesis | Measurable outcome | Likely experiment | What would falsify it |
|---|---|---|---|---|
| **Usability** | A meaningful transformation can be fully described by a small JSON policy with no application-specific code | Lines of application code required to express the three design probes in section 10, beyond loading and calling `apply()` | Implement the JSON loader (a later increment) and count | If any of the three probes require a bespoke Python callback beyond `Replace`'s existing hook to express correctly |
| **Portability** | The same `Policy` object executes unchanged through different execution adapters | Byte-identical `PolicyResult`/output across a local-CLI invocation and a simulated container/cloud invocation of the same policy and input | Build one local adapter and one containerized adapter (out of scope for this analysis), run both, diff results | Any adapter needing to special-case policy content, not just I/O plumbing |
| **Semantic completeness** | Policy can target an attribute regardless of nesting depth, Explicit/Implicit VR, supported charset, or private-element placement | A single locator/policy definition matches the same logical attribute across an Explicit-VR fixture, an Implicit-VR fixture, and a nested-Sequence fixture, unmodified | Reuse attrs' own A1.4/A1.7 fixture-building patterns, run one policy against all three | The policy needing per-encoding variants to hit the same attribute |
| **Preservation** | Policy can modify selected metadata while leaving unrelated attributes and Pixel Data untouched | Byte-for-byte comparison of every non-targeted element and the Pixel Data span, before and after | Extend `pipeline_demo.py`'s existing non-interference checks into a systematic test | Any unrelated element or Pixel Data byte changing |
| **Resource behavior** | The engine avoids Pixel Data decoding/materialization during metadata-only transformations | Peak memory / wall time on a large-Pixel-Data file for a metadata-only policy, compared to a naive decode-and-re-encode baseline | Reuse attrs' own `docs/benchmarks.md` methodology with a policy-driven metadata-only edit | Memory or time scaling with Pixel Data size for a policy that never names `(7FE0,0010)` |

None of these have been measured yet — they are stated here as the falsifiable claims a V1
implementation should be built to satisfy and later tested against, not as results already
obtained.

## 17. Proposed implementation progression

Derived from this inventory, not from a template. Each increment is independently freezable, small,
and falsifiable — mirroring the shape (not the specific content) of attrs' own A1 progression.
**None of these are authorized by this analysis; all require separate sign-off.**

- **S1.1 — Locator widening.** Extend `Require`/`Remove`/`Replace` to accept a nested path or
  wildcard-Item pattern, not just a bare top-level-or-everywhere tag. Retire `_collect_tags` in
  favor of `Structure.iter_elements`. Exclusions: no JSON, no new operation kinds, no execution
  layer. Acceptance: every existing test still passes; new tests prove path-targeted and
  wildcard-targeted operations against nested fixtures (mirroring attrs' own nested-insertion test
  style). Freeze point: the widened five-operation vocabulary, path-capable throughout.

- **S1.2 — Charset-aware `Replace` and the `Ensure` action.** Add a text-mode `Replace` built on
  attrs' `set_text`, and the new `Ensure` (set-or-insert, explicit-or-inferred VR) built on attrs'
  `find`+`set_value`/`insert`(`_text`). Exclusions: no JSON. Acceptance: the de-identification
  stress case (section 9) fully expressible and tested end-to-end, including a genuinely
  non-ASCII replacement value. Freeze point: V1's complete policy-action vocabulary.

- **S1.3 — Result/diagnostic model completion.** Map attrs' typed mutation exceptions
  (`VRRequiredError`, `AlreadyExistsError`, `UnrepresentableCharacterError`,
  `InvalidUnicodeInputError`) onto new `OperationResult`/`Diagnostic` outcomes for the new
  path/`Ensure` operations from S1.1/S1.2, since those can now fail in ways the current five
  always-succeeding-on-valid-input operations never could. Exclusions: no logging framework.
  Acceptance: every new failure mode from S1.1/S1.2 has a modeled, tested `PolicyResult` outcome,
  never an uncaught exception escaping `apply()`.

- **S1.4 — Declarative JSON configuration.** Implement the loader for the vocabulary S1.1–S1.3
  established, validated against the three design probes in section 10 (now committed, not
  illustrative). Exclusions: no CLI yet, no schema versioning beyond the `version` string already
  in `Policy`. Acceptance: round-trip (JSON → `Policy` → `apply` → expected `PolicyResult`) for
  each probe, plus a malformed-JSON rejection path with a modeled configuration-error diagnostic.

- **S1.5 — First execution adapter + `fastDICOMgateway` convergence.** Build one thin local
  file-in/file-out adapter around `policy.apply()`, then (a cross-repo, coordinated change, out of
  this analysis's scope to authorize) switch `fastDICOMgateway`'s `_apply_demo_policy` to call it
  instead of hand-rolling the equivalent sequence — closing the "zero production callers" gap
  identified in section 4a. Exclusions: no streaming, no cloud-specific adapter yet. Acceptance:
  `fastDICOMgateway`'s own existing tests (out of this repo, unaffected here) continue to pass
  with byte-identical output before/after the switch — the exact property
  `PolicyReproducesGatewayDemoTest` already proves is possible.

- **S1.6 — Private-creator-aware policy (conditional).** Only if attrs exposes
  `resolve_private_creator` to Python/ABI first (an attrs-side decision, not this repository's to
  make) — add a creator-allowlist mode to `PrivateTagPolicy`. Explicitly blocked, not scheduled,
  until that dependency is resolved.

Each increment above should get its own freeze report in this repository's `docs/architecture/`,
mirroring attrs' own per-increment discipline, once (and if) this progression is authorized.

## 18. Risks and unresolved questions

- **Cross-repo coordination risk**: S1.5's `fastDICOMgateway` convergence step touches a second
  repository this analysis was not authorized to inspect deeply or modify. It should be scoped and
  authorized as its own decision, involving whoever owns that repository, not folded silently into
  a structure-only increment.
- **Wildcard path semantics are a new design surface**: `"item": "*"` (section 10) has no existing
  precedent in either repository; its exact expansion rules (what happens if the named Sequence
  doesn't exist at all — is that zero operations, or a diagnostic?) need explicit design before
  S1.1, not left implicit.
- **`Ensure`'s interaction with `Require`**: an `Ensure` that inserts a missing attribute could
  make a *later* `Require` for that same attribute trivially always-satisfied — worth deciding
  whether that's desired (idempotent policies) or worth a diagnostic warning.
- **Whether `resolve_private_creator`'s Python-binding gap is worth closing at all**: this analysis
  flags it as a real gap but takes no position on whether creator-aware private-tag policy is
  product-important enough to justify the attrs-side work — that's a product decision, not an
  architecture one.
- **Packaging is entirely unaddressed** by this analysis (no `pyproject.toml` exists); if any S1
  increment is expected to ship as an installable package rather than a `sys.path`-relative
  sibling checkout, that is additional, currently-unscoped work.

## 19. Recommended next decision

Review this inventory and the candidate Structure Contract v1 (section 15). If accepted, authorize
**S1.1 only** first (locator widening) — it is the single change every later increment depends on,
it touches no configuration format or execution surface yet, and its acceptance criteria are
independently verifiable against the existing test suite's own patterns. Do not authorize S1.2
onward until S1.1's freeze report demonstrates the widened locator model actually holds up against
real nested/wildcard fixtures.

## 20. Explicit statement of what was NOT implemented

No file in `fastDICOMstructure` was modified except the creation of this report and the (previously
absent) `docs/architecture/` directory to hold it. No file in `fastDICOMattrs` was read for any
purpose other than confirming its current public API and A1.7 freeze-report claims, and none was
modified. Specifically, none of the following were done, per the stop condition: `policy.py` was
not refactored; no JSON schema or loader was implemented; no duplicated code was deleted; no
`__init__.py` re-export list was updated; no test was added, changed, or removed; `S1.1` was not
started; `fastDICOMgateway` was inspected read-only (to establish the dependency map in sections 3
and 4a) and not modified.
