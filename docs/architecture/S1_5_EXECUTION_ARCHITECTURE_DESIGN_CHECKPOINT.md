# S1.5 Design Checkpoint — Execution Architecture

**Status: ANALYSIS AND DESIGN ONLY.** No production code was written, no test was modified, no
file in `fastDICOMattrs` or `fastDICOMgateway` was touched, and no container or cloud resource was
created. Every claim below was verified against the actual frozen source of all three repositories
(read directly for this checkpoint), not recalled from memory.

## 1. Verified starting state

| Item | Commit | Verified |
|---|---|---|
| fastDICOMattrs | `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6` | matches, clean |
| fastDICOMstructure S1.1 | `bdc324cfe5b71c7080d7efee8d745186d7020366` | matches (in history) |
| fastDICOMstructure S1.2 | `53ecb832bd76345eb62bbf533167663b9f9546d9` | matches (in history) |
| fastDICOMstructure S1.3 | `25615dd0824b1940abd7b012f69c612f61cd74c0` | matches (in history) |
| fastDICOMstructure S1.4 | `8879ca7a9395bafe0764910dfa6f3278b95c4a48` | matches, HEAD, clean |

`python3 -m pytest tests/python/` re-run: **216/216 passing.** No discrepancy found; no commit was
changed during this checkpoint.

## 2. Current execution-capability inventory (what exists vs. what is planned)

Read directly: `python/fastdicomstructure/{__init__,policy,configuration}.py`,
`python/examples/pipeline_demo.py`, `docs/architecture/PRODUCT_CAPABILITY_MAP.md`, and the frozen
`fastdicomattrs/__init__.py` (`Structure.read`/`read_buffer`/`write`/`write_with_stats`/
`write_bytes`/`write_bytes_with_stats`/`close`, `FdsError`).

**Exists:**
- `policy.apply(structure, policy) -> PolicyResult` — pure in-memory, zero I/O coupling (verified:
  `policy.py` imports nothing filesystem- or network-shaped).
- `configuration.load_configuration(_json)(...) -> Configuration` — a fully closed JSON loader
  producing a real `Policy` object plus **opaque, uninterpreted** `source`/`destination`
  `Envelope`s (`{type: str, options: dict}`).
- attrs' `read(path)`/`read_buffer(bytes)` (raise `FdsError` on I/O or parse failure, distinguishable
  via `FdsError.status` — `_FDS_STATUS_IO_ERROR=3` vs. `_FDS_STATUS_PARSE_FAILED=4`/
  `_FDS_STATUS_UNSUPPORTED=5`; a partially-successful parse does **not** raise, it populates
  `.diagnostics`).
- attrs' `write(path)`/`write_with_stats(path)`/`write_bytes()`/`write_bytes_with_stats()` — both
  path-based and buffer-based serialization already exist; `write(path)` writes **directly** to the
  final path with no atomic-rename or overwrite-protection behavior visible at the Python level.
- `Structure` has **no context-manager protocol** (no `__enter__`/`__exit__`) — every existing test
  and the example demo call `close()` explicitly in a `try/finally`.
- `python/examples/pipeline_demo.py` — a runnable, filesystem-writing demo (`write_with_stats`),
  but it hand-rolls mutation (`erase`, `set_value`, `erase_private`) directly against `Structure`,
  **not** through `policy.py` at all.

**Does not exist:**
- No adapter registry, no adapter resolution, no source/destination execution of any kind.
- No filesystem adapter defined by or known to `configuration.py` (deliberately opaque, per S1.4).
- No execution engine, no `ExecutionResult`-shaped concept anywhere in `fastdicomstructure`.
- No CLI, no container artifact, no Cloud Run contract, in this repository.
- No streaming parse primitive in attrs (`fds_parse_stream` is an acknowledged stub — confirmed
  still true per `PRODUCT_CAPABILITY_MAP.md` P3.3, unchanged since S1.1).

**Gateway (`fastDICOMgateway`, inspected, not modified) — this is the single most important piece
of evidence for this checkpoint**, because it is a real, production-validated pipeline that has
already independently solved a narrower version of exactly the problem S1.5 is being asked to
solve generically:

- `transform.py` parses via `fds.read_buffer`, hand-rolls a **fixed three-tag policy** directly
  against `Structure` primitives (`erase_recursive`/`set_value_recursive`/`erase_private`) — it
  imports `fastdicomstructure` but **never calls `policy.py`'s `Policy`/`apply` at all**. This
  reconfirms `POST_A1_RUTHLESS_INVENTORY.md` section 4a's "zero-production-caller" finding,
  **unchanged** as of this checkpoint: a test (`test_apply_reproduces_gateway_demo_policy`) already
  proves `policy.apply()` computes an equivalent result to gateway's hand-rolled sequence, but
  nothing in production actually exercises that path.
- Gateway's pipeline is **entirely in-memory, end to end** — no filesystem read or write anywhere
  in `transform.py`; its actual *destination* is `sink.py`, an authenticated HTTPS **DICOMweb
  STOW-RS** submission to a Cloud Healthcare API store (real network I/O, real cloud credentials
  via `google.auth.default()`, real production deployment).
- Gateway already independently invented a structurally similar three-way result taxonomy:
  `RejectedInput`/`Rejection` (bad input — curated `reason` string, never raw diagnostic content),
  `TransformResult` (success — curated, safe-to-log fields, **UID strings only**, no PHI values),
  and `sink.PersistenceFailed`/`StoreFailure` (destination failure — curated `reason` from a small
  fixed set, deliberately **never** logs the downstream response body). This is strong,
  independent, already-shipped convergent evidence for the shape this checkpoint recommends below
  (a closed, curated, PHI-safe operational-diagnostic vocabulary distinct from policy diagnostics).
- Gateway is **already deployed on Cloud Run** (`app.py`'s `_lifespan` references Cloud Run's own
  `K_SERVICE`/`K_REVISION`/`K_CONFIGURATION` env vars; the docstrings cite its own `M3`/`M4`
  container/Cloud-Run validation reports) via a plain **request-driven HTTP** model (`POST /dicom`,
  FastAPI/Starlette reading the body directly into memory — no multipart staging to disk, no
  filesystem use of any kind, confirmed by its own M4 "runtime filesystem posture" characterization
  logged at startup).

This is direct, already-shipped, empirical evidence that: (a) the general shape "in-memory
parse → fixed transform → in-memory serialize → network destination" survives containerized,
Cloud-Run, HTTP-request-driven deployment for this exact library family, without requiring any
container- or Cloud-Run-specific logic inside the transform pipeline itself; and (b) gateway's own
result/rejection/failure modeling already converges, independently, on the same curated,
PHI-conscious diagnostic discipline S1.3/S1.4 established for `policy.py`/`configuration.py`. Both
facts directly inform sections 15, 19, 20, and 24 below.

## 3. Execution lifecycle

The prompt's own sketch is broadly right but conflates two different concerns: *acquiring an
object* and *running policy against one already acquired*. Separating them is the central design
decision of this checkpoint (justified fully in section 7). Refined lifecycle:

```text
resolve adapters (once per Configuration)      -- adapters/ (new)
        |
        v
acquire bytes from source                       -- adapter (new)
        |
        v
parse bytes -> Structure                         -- attrs, invoked by execution.py
        |
        v
apply Policy -> PolicyResult                     -- policy.py, UNCHANGED
        |
        +--- REJECTED / PARTIAL --> stop here, no serialize, no destination
        |
        v  (COMPLETED only)
serialize Structure -> bytes                     -- attrs, invoked by execution.py
        |
        v
write bytes to destination                       -- adapter (new)
        |
        v
ExecutionResult                                  -- execution.py (new)
```

**Ownership per transition** (the answer section 5 asks for explicitly):

| Transition | Owner |
|---|---|
| Configuration → resolved adapters | `adapters/` (new), once per Configuration |
| adapter → raw bytes | the adapter (new) |
| bytes → `Structure` | attrs, called by `execution.py` (new) — **never** by an adapter |
| `Structure` + `Policy` → `PolicyResult` | `policy.py`, **completely unchanged** |
| `Structure` → output bytes | attrs, called by `execution.py` (new) — **never** by an adapter, and only on `PolicyResult.execution == COMPLETED` |
| output bytes → destination | the adapter (new) |
| the whole call → `ExecutionResult` | `execution.py` (new) |

This preserves the established principle verbatim: **Structure owns policy/orchestration and is
the sole caller of attrs' parse/write primitives; attrs owns DICOM semantics/serialization;
adapters own I/O only and never see DICOM semantics.**

## 4. Ownership boundaries (summary)

- `policy.py` — unchanged, zero new responsibilities.
- `configuration.py` — unchanged, zero new responsibilities (envelopes stay opaque).
- `execution.py` (new) — the only module that calls both attrs' parse **and** write primitives in
  the production path; the only module that knows about `Policy`/`PolicyResult` *and* raw bytes at
  the same time; owns `ExecutionResult`.
- `adapters/` (new) — I/O only. Never parses DICOM, never serializes DICOM, never inspects a
  `Structure` or a `PolicyResult`. A source hands back `bytes`; a destination accepts `bytes`.

## 5. PolicyResult vs. operational-result boundary

**`PolicyResult` stops exactly where it already stops today: at "what happened when this Policy
ran against an already-parsed Structure."** It says nothing about how the Structure was obtained
or where its output goes, and section 2/3's evidence gives no reason to change that — every
`PolicyResult` field (`decision`, `execution`, `operations`, `diagnostics`, `policy_name`,
`policy_version`) is already meaningful without any concept of a source or destination.

A new, deliberately smaller concept is warranted: **`ExecutionResult`**, wrapping (not replacing)
`PolicyResult` and adding exactly the operational states `PolicyResult` cannot represent by
construction — because they occur *before* a `Policy` could ever run (no bytes acquired, parse
failed) or *after* it already succeeded (serialization, destination write). Derived, not assumed,
from the concrete failure cases in section 11 and the probes in section 31 — see section 34 for the
resulting field list, arrived at by asking "what does each probe A–H need to observe" rather than
guessing a shape up front.

## 6. Source adapter alternatives

Evaluated shapes for what `source.acquire()` returns:

| Shape | Verdict |
|---|---|
| Raw `bytes` | **Recommended.** Uniform across every future source (filesystem, C-STORE, DICOMweb, database — none of which can return a "path"); parsing stays centralized in `execution.py`, so failure classification (section 11) never depends on which adapter produced the bytes. |
| A file-like object | Rejected — adds a streaming illusion attrs cannot honor (section 22); no actual benefit over bytes for a single-object primitive. |
| A path | Rejected as the *general* contract (only filesystem could ever offer one — see section 23 for the specific filesystem-vs-buffer tradeoff this creates, addressed there rather than smuggled into the adapter contract). |
| A `fastdicomattrs.Structure` | Rejected — would make **every** adapter a DICOM parser, duplicating attrs-calling logic per adapter and defeating centralized failure classification; directly contradicts "who parses DICOM" staying singular. |
| An iterator of objects | Rejected for S1.5 — conflates single-object acquisition with enumeration/batch (explicitly out of scope, section 28); the single-object primitive should not be designed around a hypothetical multi-object future. |
| A neutral `InputObject` wrapper | Rejected as unnecessary indirection — `bytes` already *is* neutral; wrapping it in a class adds a type with no behavior for S1.5's scope. |

**"No object available" vs. failure:** for S1.5's filesystem source — which names exactly one
concrete file (section 14) — a missing file is a **failure** (`SOURCE_FAILED`), not a legitimate
"nothing to do" case, because the Configuration named a specific object expected to exist. The
distinction between "enumerated source, empty is normal" and "named source, absence is an error"
only becomes real once an enumerable source exists (S1.6+); the contract should not pre-invent a
"no object" return value S1.5 itself never produces.

**Who owns input identity/provenance / who closes resources:** the adapter owns acquisition-time
identity (it may know a path, a URL, a message ID); `execution.py` owns `Structure`'s lifecycle
(`close()` in a `finally`, matching every existing test's own convention, since `Structure` is not
a context manager — section 2). A source adapter never receives or closes a `Structure`.

**Streaming relevance:** none, for the interface itself — see section 22. The contract is
consciously **not** shaped like a stream reader.

## 7. Destination adapter alternatives

| Question | Answer, with reasoning |
|---|---|
| Bytes, Structure, or both? | **Bytes only.** Giving a destination a `Structure` would let it call attrs' write primitives itself — the one thing section 3/4 explicitly forbids adapters from doing. `execution.py` remains the sole caller of `write_bytes()`. |
| Who serializes? | `execution.py`, always, and **only** after `PolicyResult.execution == COMPLETED` — never speculatively, never for a rejected/partial result. |
| Does the adapter receive `PolicyResult`? | No. By the time a destination is invoked, the policy has already unconditionally succeeded (see the gating rule below); the adapter needs nothing from `PolicyResult` to do its job (write these bytes, to this place). Keeping `PolicyResult` out of the adapter contract is what keeps adapters ignorant of policy semantics, matching section 4. |
| Invoked on rejection or failure? | **No — never**, in S1.5. See section 10, Model A. |
| Destination failure representation | A dedicated `ExecutionOutcome.DESTINATION_FAILED` plus a curated `ExecutionDiagnostic` (section 11) — never a bare re-raised adapter exception surfacing through `ExecutionResult`. |
| Transaction/commit semantics? | For the one adapter S1.5 builds (filesystem): yes, narrowly — atomic rename is the commit (section 15). No general two-phase-commit API is warranted for one adapter. |
| Who names the final output? | The Configuration's `destination.options` (adapter-owned, opaque to `configuration.py`) — for S1.5's single-object proof, a literal target path; no templating/naming logic (that is a batch-era concern, explicitly deferred). |

## 8. Adapter resolution alternatives

| Approach | Evaluation |
|---|---|
| **A. Closed internal registry** (`{"filesystem": FilesystemSource}`) | **Recommended.** Deterministic, trivially testable, zero dynamic code execution, matches Configuration V1's own closed/fail-closed philosophy exactly (S1.4's `_ALL_KNOWN_OPS` is the identical pattern one layer up). Extending it later means adding a dict entry, not a framework change. |
| B. Explicit dependency injection (`execute(config, source_registry=..., destination_registry=...)`) | Adopted **as the mechanism**, not a distinct alternative — the closed registry from A is itself passed by ordinary Python argument, so a test or an unusual deployment can substitute a different registry without any global state. A and B are complementary, not competing. |
| C. Plugin/discovery model (entry points, dynamic import, scanning) | **Rejected.** Directly contradicts "no field capable of containing executable configuration" and "no arbitrary code execution" carried forward from S1.4's own security posture (section 27) — a `"type"` string driving a dynamic import is exactly the shape a malicious or malformed Configuration document could abuse. Given Configuration V1's own explicit skepticism toward extensibility-for-its-own-sake (S1.4 Correction 1), a closed registry is the only choice consistent with prior decisions. |

**Where adapter-specific option validation happens:** the model given in the prompt is correct and
is adopted verbatim — `configuration.py` validates only the common envelope shape (unchanged, no
new code there); a small `adapters/` resolver maps `envelope.type` to a constructor; the concrete
adapter class (`FilesystemSource`, e.g.) validates its own `options` (a `"path"` string present,
non-empty) at construction time. `Unknown adapter type` and `known type, invalid options` are both
raised as one new, S1.5-owned `AdapterResolutionError` (two curated codes:
`ADAPTER_TYPE_UNKNOWN`/`ADAPTER_OPTIONS_INVALID`) — occurring **once per Configuration, before any
object is acquired**, never inside `ExecutionResult` (see Probe G, section 31).

## 9. Failure taxonomy

| Failure | Represented as |
|---|---|
| Configuration invalid | `configuration.ConfigurationError` (S1.4, unchanged) |
| Adapter type unavailable | `AdapterResolutionError` (new; resolution-time, once per Configuration) |
| Source/destination configuration invalid | `AdapterResolutionError` (same, adapter-owned options validation) |
| Source open/acquisition failure | `ExecutionResult.outcome = SOURCE_FAILED` |
| Source object missing | `ExecutionResult.outcome = SOURCE_FAILED` (S1.5's single-named-file source has no separate "missing" category — see section 6) |
| DICOM parse failure | `ExecutionResult.outcome = PARSE_FAILED` |
| Policy rejection | `ExecutionResult.outcome = POLICY_REJECTED`, full `PolicyResult` attached (its own `diagnostics` are sufficient — not duplicated) |
| Policy execution failure | `ExecutionResult.outcome = POLICY_PARTIAL`, full `PolicyResult` attached |
| Policy rollback failure / uncertain state | **`RollbackError` propagates raw**, uncaught by `execution.py` — never converted into any `ExecutionResult` value (see section 32) |
| DICOM serialization failure | `ExecutionResult.outcome = SERIALIZATION_FAILED` (a new category this checkpoint identifies — see section 23/31) |
| Destination open/write/commit failure | `ExecutionResult.outcome = DESTINATION_FAILED` |
| Unexpected internal/system failure | propagates raw, uncaught — `execution.py` adds **no** blanket `except Exception`, mirroring `policy.apply()`'s own boundary exactly |

This gives seven closed `ExecutionOutcome` values plus two exception types (`RollbackError`,
reused unmodified from `policy.py`; `AdapterResolutionError`, new) — enough distinction for a
future CLI/container/service to make correct decisions (e.g. "retry-eligible" vs. "never retry" vs.
"operator must intervene") without ever needing to pattern-match a message string.

## 10. Acceptance/rejection behavior

**Recommended: Model A, with a single unifying rule.** A destination is invoked **if and only if**
`PolicyResult.execution == PolicyExecutionStatus.COMPLETED`. This one rule handles both an
unsatisfied `Require` (`REJECTED`) and an operation failure (`PARTIAL`) identically and correctly,
with no special-casing — both mean "the Policy's intended end state was not reached," and neither
should be able to reach the destination.

Model B (destination receives rejected objects with metadata) is rejected: it would force every
destination adapter to understand policy semantics (what does a filesystem destination *do* with a
rejection flag?), directly violating the ownership boundary in section 4.

Model C (a future quarantine/rejection sink) is **not built in S1.5**, but nothing in this design
makes it architecturally impossible later: an `ExecutionResult` with `outcome != SUCCEEDED` is
already a complete, addressable value a future caller could route to a different destination
adapter of their own choosing — the gating rule lives in the *orchestration* helper (`run()`,
section 34), not baked into `execute_one()` or the adapter contract itself, so a future quarantine
sink is simply "call a second destination adapter when `outcome != SUCCEEDED`," not a redesign.

## 11. Filesystem-adapter analysis

**Minimal proof only** (per section 14's own framing): exactly one configured input file → one
policy execution → one configured output file. No directory enumeration, no globbing, no
recursion, no watching. `source.options = {"path": "<file>"}`, `destination.options = {"path":
"<file>", "overwrite": false (default)}`.

**Read side:** the adapter reads the named file's bytes and returns them (`open(path,
"rb").read()`); it does not call any attrs primitive (section 6). A missing/unreadable file raises
a plain, curated adapter exception, caught by `execution.py` and turned into `SOURCE_FAILED`.

**Write side:** see section 12 for the safety analysis; the destination adapter never calls an
attrs primitive either — `execution.py` hands it finished bytes.

## 12. Output safety / atomicity analysis

Decisions, each argued:

- **Temporary file + atomic rename**, not a direct write to the final path. `structure.write(path)`
  itself (section 2) writes straight to the target with no atomicity guarantee — building the S1.5
  filesystem destination directly on top of that primitive would establish unsafe semantics on day
  one that a later increment would have to break compatibility to fix. The adapter therefore writes
  to a temp file in the **same directory** as the target (so the final `os.rename` is same-filesystem
  and atomic on POSIX) and renames only after the write completes and is flushed.
- **Reject an existing target by default**, with an explicit `"overwrite": true` opt-in inside the
  adapter's own opaque `options` (never validated by `configuration.py` — section 8). Silent
  overwrite is a bad default for a tool that may run repeatedly against the same directory; an
  explicit, adapter-owned flag matches the "closed vocabulary, explicit opt-in" discipline carried
  forward from S1.3/S1.4.
- **Source/destination path collision**: checked once, at adapter-resolution time (section 8) when
  both adapters happen to be filesystem-typed and their resolved paths are equal — raised as
  `AdapterResolutionError`, the same category as an unsupported adapter type, since it is a
  Configuration-shape problem discoverable before touching any object, not a per-object outcome.
- **Serialization succeeds, final write fails**: this is exactly `DESTINATION_FAILED` (section 9);
  the temp file is removed on any adapter-side failure (best-effort cleanup, mirroring
  `_apply_sites_atomically`'s own "best-effort, never masks the real failure" precedent) so a
  failed run never leaves a stray partial file next to the target.
- **No transactional filesystem layer** beyond temp-write + atomic rename is built — anything more
  (journaling, multi-file transactions) is unjustified for a single-object, single-file proof.

## 13. Result-serialization decision

**Not implemented in S1.5**, for the identical reasoning S1.4's Correction 3 already established:
no real consumer exists yet. S1.5's own qualification inspects `ExecutionResult` directly, in
Python, exactly as `test_configuration.py` inspects `PolicyResult` directly. A CLI (S1.6, section
18) is the first genuine consumer that would need rendered (JSON or text) output; building
serialization now, before that consumer exists, risks guessing its shape wrong. `ExecutionResult`
stays a plain, immutable Python dataclass.

## 14. CLI decision

**Deferred to a separate increment (S1.6), not part of S1.5.** S1.5's architectural claim (section
37) is fully provable as a library-level Python API — `execute_one`/`run` called directly from
tests — with no CLI required. Bundling a CLI into S1.5 risks exactly the coupling the prompt itself
names: argument parsing, exit codes, result rendering, logging configuration, and (if not
disciplined) batch behavior are all orthogonal to proving the execution boundary, and each is its
own small design surface better given its own checkpoint. This matches every prior increment's own
discipline (S1.1 Locator, S1.2 Replace/Ensure, S1.3 Result model, S1.4 Configuration — each proved
exactly one bounded claim).

## 15. Containerization decision

**A separate, later increment — not S1.5, and not necessarily immediately after.** Two independent
lines of evidence support this:

1. **Gateway's own M3/M4 validation already empirically demonstrates** that a structurally similar,
   in-memory, sibling-repo-consuming pipeline built on this same library family survives
   containerized/Cloud-Run execution without requiring container-specific pipeline logic (section
   2). This does not *prove* S1.5's own execution core behaves identically, but it substantially
   reduces the a priori risk that containerization would surface a surprising architectural problem.
2. **`execute_one` itself has zero filesystem/network coupling by construction** (only the adapters
   do) — so containerization is *expected* to be exactly the "thin invocation layer around the same
   engine" shape the prompt prefers. But expected-to-be-boring is not proven-to-be-boring, and there
   is nothing meaningful to containerize yet: no CLI, only a library API and one filesystem adapter
   pair whose entire point is proving the boundary *locally*. Containerizing before a CLI (or at
   least a settled invocation surface) exists would be proving a deployment shape with nothing real
   to deploy.

If a container built on top of S1.5+S1.6 later required **substantial** container-specific
execution logic, that would itself be a signal of an architectural problem in the execution core
(a filesystem assumption leaking somewhere) — not an expected, normal cost. This checkpoint records
that expectation now so it can be checked against later, but recommends against building the
container prematurely.

## 16. Cloud Run / serverless decision

**Preferred answer is "no, the S1.5 core requires nothing Cloud-Run-specific" — and the evidence
supports it, not just asserts it.** `execute_one(data: bytes, policy: Policy) -> ExecutionResult` is
already a plain value-in/value-out Python call with no I/O of its own; it is directly callable
identically from a request handler (request-driven shape), an event handler (event-driven shape,
e.g. a Cloud Storage trigger acquiring bytes then calling the identical primitive), or a batch job
driver (looping `execute_one` calls) — the three shapes named in the prompt differ **only** in how
bytes are acquired and how `ExecutionResult` is disposed of, exactly matching gateway's own request-
driven precedent (`app.py`'s handler is already this exact shape, one layer down, for its own
hand-rolled transform).

No Cloud Run deployment shape is assumed to be the "right" one by this checkpoint — that decision
belongs to whichever future increment actually builds one, informed by real product need. S1.5
itself creates no HTTP server, no event subscription, no GCP SDK dependency, and (per the
instructions) deploys nothing.

## 17. Streaming assessment

**Unchanged, still `BLOCKED` at attrs** (`PRODUCT_CAPABILITY_MAP.md` P3.3, reconfirmed: attrs has
no streaming parse primitive). S1.5's source adapter contract (`acquire() -> bytes`, section 6) does
**not** claim streaming support in any form — a filesystem adapter reading a whole file into memory
before returning it is ordinary buffered I/O, not streaming, and this checkpoint is explicit that a
future bounded-buffer read pattern would still not constitute "streaming parse" unless attrs itself
gains a streaming primitive. Nothing in the S1.5 contract shape needs to change if/when that
happens — a future streaming source would still ultimately have to hand attrs *something* it can
parse; how that "something" differs from `bytes` is attrs' own future design question, out of this
checkpoint's scope.

## 18. Pixel Data / materialization assessment

Genuine, non-hypothetical hazard identified (not just asserted): **routing a filesystem source
through the bytes-uniform contract (section 6) means a whole-file `bytes` copy exists in Python
memory before `fds.read_buffer` even runs — including Pixel Data — where attrs' own `read(path)`
would let its C++ layer do the file I/O with no equivalent Python-level copy.** This is a real
architectural fork, not glossed over:

- **Option 1 (bytes-uniform, recommended for S1.5):** adapters always return/accept `bytes`;
  `execution.py` always calls `read_buffer`/`write_bytes`. Costs one extra whole-object Python-level
  copy for the filesystem case specifically.
- **Option 2 (path-optimized):** let filesystem-typed adapters signal a path instead, and have
  `execution.py` call attrs' `read(path)`/`write(path)` directly, avoiding the extra copy — at the
  cost of a second code path in `execution.py` and a contract that stops being uniform the moment a
  second filesystem-like adapter (e.g. a mounted network share) also wants the optimization.

**Recommendation: Option 1, with the hazard explicitly named and accepted as a bounded, revisitable
cost — not silently absorbed.** Reasoning: (a) every *other* planned adapter (C-STORE, DICOMweb,
database — P4.3/P4.4/P4.5) can only ever produce/consume bytes, so optimizing the one adapter that
happens to have a path-shaped alternative over-fits the general contract to filesystem specifically;
(b) gateway's own production pipeline (section 2) already uses exactly this bytes-uniform pattern
(`read_buffer`/`write_bytes`) successfully; (c) S1.1–S1.4 never claimed bounded memory either
(`PRODUCT_CAPABILITY_MAP.md` P6.2: "no size-aware bounding claim... can be made yet") — S1.5 does
not regress an existing guarantee, it inherits an already-documented, already-accepted gap; (d) the
path-optimized alternative remains available to add later, adapter-by-adapter, once actually
measured to matter — consistent with "do not claim bounded memory unless measured... but identify
obvious hazards now."

Beyond that one hazard: Pixel Data itself is never decoded by anything in this design — `read_buffer`
and `write_bytes` are the same, unmodified attrs primitives every prior increment already relies on,
and `resolve_locator`/`policy.py` still never touch it (S1.1 finding, unchanged).

## 19. Gateway-convergence assessment

Confirmed, not merely assumed, from direct inspection (section 2): gateway hand-rolls its fixed
policy and has **never** called `policy.py`; it has its own separate, already-shipped,
production-validated (M2–M5), Cloud-Run-deployed pipeline whose real destination is DICOMweb
STOW-RS, not a filesystem. `PRODUCT_CAPABILITY_MAP.md`'s P5.5 row already recorded the correct
disposition before this checkpoint began (`DEFERRED/BLOCKED`, prerequisite "S1.5's local adapter,
then a coordinated, separately-authorized change to fastDICOMgateway itself") — this checkpoint's
own evidence fully corroborates that pre-existing judgment rather than overturning it.

**What could eventually be replaced:** `transform.py`'s `_apply_demo_policy` (currently four direct
`Structure` calls) could become a single `policy.Policy` executed via `policy.apply()` — already
shown equivalent by `test_apply_reproduces_gateway_demo_policy`.

**What must remain gateway-specific:** its FastAPI/Starlette HTTP layer, `sink.py`'s STOW-RS
submission and credential handling, and its own M2–M5 validation apparatus — none of that is
S1.5's concern, and gateway's STOW-RS destination is valuable **future** prior art for an eventual
`DicomwebDestination` adapter, not something S1.5 attempts to build now (S1.5 proves exactly one
adapter pair: filesystem).

**Should gateway convergence be part of S1.5? No** — confirmed, not just asserted, by (a) gateway's
own working, deployed, separately-validated state (a live production-shaped pipeline is not a safe
thing to casually re-point at a brand-new, unproven execution engine within the same increment that
built the engine), and (b) the explicit instruction not to modify gateway in this checkpoint or its
implementation. Recorded as its own later increment (S1.9, section 35).

## 20. Evidence Packet forward-compatibility assessment

`PRODUCT_CAPABILITY_MAP.md` P7.3 remains `CANDIDATE`, no design work started, and none is done
here. `ExecutionResult`'s shape (section 5/34) — configuration identity, per-stage outcome,
`PolicyResult`, an operational diagnostic — is deliberately sufficient raw material for a future
Evidence Packet consumer to build a fan-out on top of, without `execution.py` importing or knowing
about Evidence Packets at all:

```text
ExecutionResult
        |
        +---- future CLI renderer   (S1.6)
        +---- future logger
        +---- future Evidence Packet adapter
        +---- future service telemetry
```

This shape is recommended only because it falls out naturally from keeping `ExecutionResult` a
plain, dependency-free value type — not built or justified specifically for Evidence Packets. No
Evidence Packet dependency exists anywhere in the S1.5 design.

## 21. Security/privacy analysis

Carried forward, not reinvented: `ExecutionDiagnostic` mirrors `policy.Diagnostic` and
`configuration.ConfigurationError` exactly — a closed `category` code plus one fixed, curated
message per code (never `str(exception)`, never adapter exception text, never a filename asserted
to be PHI-safe). Gateway's own independently-built `Rejection`/`StoreFailure` dataclasses (section
2) already establish real-world precedent for exactly this discipline at the I/O boundary
specifically (a `reason` from a small fixed set, never a downstream response body). `cause_type`
(exception class name only, matching `CallbackError.cause_type`'s precedent) is the only place a
low-level detail survives into the diagnostic, for debugging, without becoming the default public
surface. `ExecutionResult.identity` (section 34) is never a raw filesystem path or DICOM UID by
default — see that section for the reasoning.

## 22. Concurrency/batch/retry disposition

**Both explicitly out of S1.5**, per the prompt's own default and this checkpoint's own evidence:
filesystem I/O needs no retry framework; concurrency/batching are not required to prove the
one-object execution contract (section 33's central claim). `execute_one`/`run` are synchronous,
single-object, single-threaded. They are designed to be *composable* into a future batch driver
(call the same function once per object) without needing any concurrency-aware machinery baked in
now — adding it later is additive, not a redesign.

## 23. Candidate architectures

### Candidate 1 — Minimal core + one adapter pair, closed registry (recommended)

```python
def execute_one(data: bytes, policy: Policy, *, identity: Optional[str] = None) -> ExecutionResult:
    ...  # parse -> apply -> (serialize on COMPLETED) -- no I/O, no adapters, no Configuration

def run(source: SourceAdapter, policy: Policy, destination: Optional[DestinationAdapter]) -> ExecutionResult:
    data = source.acquire()               # may raise -> SOURCE_FAILED
    result = execute_one(data, policy, identity=source.identity())
    if destination is not None and result.outcome is ExecutionOutcome.SUCCEEDED:
        destination.write(result.output_bytes)   # may raise -> DESTINATION_FAILED
    return result

SOURCE_ADAPTERS = {"filesystem": FilesystemSource}
DESTINATION_ADAPTERS = {"filesystem": FilesystemDestination}
```

| Criterion | Assessment |
|---|---|
| Conceptual simplicity | High — two small functions, one closed dict per direction |
| Policy-core isolation | Complete — `execute_one` never imports an adapter |
| Adapter isolation | Complete — adapters never import `policy`/attrs |
| Filesystem suitability | Direct |
| Future network suitability | Direct — bytes-in/bytes-out is what any network adapter already produces |
| Future container suitability | Direct — no coupling to remove |
| Cloud Run suitability | Direct — same value-in/value-out shape |
| Testability | High — `execute_one` testable with zero adapters at all (Probe H) |
| Deterministic behavior | Yes |
| Failure semantics | Seven closed outcomes (section 9), no blanket catch |
| Memory/copy behavior | One documented, accepted extra copy for filesystem (section 18) |
| Security/privacy | Closed registry, no dynamic code, curated diagnostics |
| Implementation complexity | Low |
| Over-abstraction risk | Low — nothing built that lacks a current use |

### Candidate 2 — Single `execute(config)` entry point, adapters resolved internally

```python
def execute(config: Configuration) -> ExecutionResult:
    source = resolve_source(config.source)          # internal
    destination = resolve_destination(config.destination)
    data = source.acquire()
    ...
```

**Rejected as the sole/primary primitive.** It fails Probe H directly: a Python caller who already
has bytes or a `Structure` would have to fabricate a fake `Configuration`/source envelope just to
run policy they could already run with `policy.apply()` — precisely the deployment-neutrality
failure section 33 warns against, and precisely why `configuration.py` and `policy.py` were kept
separate in S1.4. Retained only as optional convenience *sugar* built on top of Candidate 1's
primitives for a caller who genuinely starts from a `Configuration` and wants the full path in one
call — never as the only way to invoke execution.

### Candidate 3 — Rich adapter framework (ABCs with open/stage/commit/rollback hooks, async support, plugin discovery)

```python
class Adapter(Protocol):
    async def open(self) -> None: ...
    async def stage(self, data: bytes) -> StagingHandle: ...
    async def commit(self, handle: StagingHandle) -> None: ...
    async def rollback(self, handle: StagingHandle) -> None: ...
    def retry_policy(self) -> RetryPolicy: ...
```

**Rejected for S1.5.** Every hook beyond "acquire"/"write" is unused by the one concrete adapter
this increment builds; `async` buys nothing when nothing in the current stack (attrs' ctypes calls,
plain file I/O) is actually async; a generic `retry_policy()` bakes cloud-service assumptions into
the core the prompt itself warns against (section 29). High implementation complexity, large
surface for a future security review, and the textbook over-abstraction risk this checkpoint was
told to watch for. Some individual ideas are salvaged narrowly (an explicit commit step, section 12)
without adopting the framework.

### (Reference) Candidate 4 — Event/queue-driven engine from the start

Briefly considered and rejected: designing the core around a generic event bus/queue consumer to
"future-proof" for Cloud Run event-driven and batch use cases simultaneously conflates
execution-primitive design with deployment-shape design, adds complexity with no current test to
justify it, and is trivially unnecessary — Candidate 1's `execute_one` is already composable into a
queue consumer later (call it once per dequeued message) without anything queue-shaped in the core
today.

**Recommendation: Candidate 1.**

## 24. Recommended architecture

`execute_one(data: bytes, policy: Policy, *, identity: Optional[str] = None) -> ExecutionResult` is
the deployment-neutral core. `run(source, policy, destination) -> ExecutionResult` is a thin
orchestration wrapper adding exactly acquisition and (conditional) persistence. `resolve_source`/
`resolve_destination` (a closed registry, section 8) sit outside both, invoked once per
Configuration by whichever caller owns a `Configuration` — never by `execute_one` itself.

## 25. Required execution probes

**A — successful filesystem transformation.** `source.acquire()` returns the input file's bytes →
`execute_one` parses, `Require` passes, `ReplaceText` runs → `PolicyResult.execution == COMPLETED`
→ `execution.py` serializes → `run()` invokes `destination.write(...)`, which atomically renames
into place → `ExecutionResult(outcome=SUCCEEDED, policy_result=<COMPLETED, TRANSFORM>,
output_bytes=<...>, diagnostic=None)`.

**B — acceptance rejection.** Input parses; `Require` fails → `PolicyResult.execution == REJECTED`.
Per the section 10 gating rule, `run()` never calls `destination.write(...)` — **destination is not
invoked**. `ExecutionResult(outcome=POLICY_REJECTED, policy_result=<REJECTED>, output_bytes=None,
diagnostic=None)` — no new diagnostic is invented; `PolicyResult.diagnostics` (S1.3, unchanged)
already carries `REQUIREMENT_UNSATISFIED`. The input file on disk is untouched (filesystem source
never mutates or deletes it); no output file is created or altered.

**C — malformed DICOM.** `source.acquire()` succeeds (bytes obtained); `fds.read_buffer` raises
`FdsError`. Owned entirely by `execution.py` (never the adapter, since the adapter's job — getting
bytes — already succeeded). `ExecutionResult(outcome=PARSE_FAILED, policy_result=None,
output_bytes=None, diagnostic=ExecutionDiagnostic(category="DICOM_PARSE_FAILED",
cause_type="FdsError", ...))`. No `Structure` ever existed to close.

**D — policy execution failure with successful rollback.** `policy.apply()` catches a known
failure, rolls the failing operation's own sites back exactly (S1.3, unchanged), returns
`PolicyResult.execution == PolicyExecutionStatus.PARTIAL`. `execution.py` does nothing special —
the same section 10 gating rule applies (`PARTIAL != COMPLETED`) — destination is skipped.
`ExecutionResult(outcome=POLICY_PARTIAL, policy_result=<PARTIAL>, output_bytes=None,
diagnostic=None)`. **`ExecutionResult` never re-derives or duplicates what `PolicyResult` already
says about which operation failed or why** — that stays exactly where S1.3 put it.

**E — policy rollback failure / uncertain state.** `policy.apply()` itself never catches
`RollbackError` (S1.3's own frozen contract) — it propagates raw out of `policy.apply()`.
`execution.py` adds **no** new boundary around that call, so `RollbackError` propagates raw out of
`execute_one`/`run` too. **No `ExecutionResult` is ever constructed for this case, and no
destination write can ever occur afterward** — there is no code path in `run()` that reaches the
destination-write step without first receiving a normal return from `execute_one`. This is the
direct, deliberate consequence of choosing not to add a second exception boundary (section 9): the
uncertain-state signal already exists one layer down and is reused, not duplicated or softened.

**F — destination write failure.** Policy `COMPLETED`, serialization succeeds (`output_bytes` is
populated), `destination.write(...)` raises. `run()` catches it and returns
`ExecutionResult(outcome=DESTINATION_FAILED, policy_result=<COMPLETED>, output_bytes=<...>,
diagnostic=ExecutionDiagnostic(category="DESTINATION_WRITE_FAILED", ...))`. The source is
unaffected — the filesystem source is read-only by construction (never deletes/renames/truncates
its own input); a partially-written temp file at the destination is removed by the adapter's own
cleanup (section 12), so no stray file appears at or near the target path.

**G — unsupported adapter type.** `{"source": {"type": "future-adapter", ...}}` is a **valid**
Configuration V1 document (S1.4, unchanged — no adapter registry exists at that layer). S1.5
rejects it at **adapter-resolution time**, before any object is touched: `resolve_source(...)`
raises `AdapterResolutionError(code="ADAPTER_TYPE_UNKNOWN", ...)`. This is deliberately **not** an
`ExecutionResult` value — it happens once per Configuration, identically for every object that
Configuration would ever process, so it belongs to the "can we even attempt this" phase (section 8),
not the per-object outcome vocabulary.

**H — same execution API from a non-filesystem caller.** A Python caller that already has DICOM
bytes (or first calls `structure.write_bytes()` on a `Structure` it already holds) calls
`execute_one(data, my_policy)` directly — no `Configuration`, no adapter, no `source`/`destination`
envelope of any kind. It gets back the identical `ExecutionResult` shape Probe A's `run()` path
produces (minus `identity`, which is optional and caller-supplied). This is the direct, executable
proof of deployment neutrality claim #2 in section 33: **the core requires no adapter concept to be
useful.**

## 26. Atomicity boundaries

| Level | Guarantee |
|---|---|
| One S1.2-era multi-site operation (`Replace`/`ReplaceText`/`Ensure`/`EnsureText`) | Atomic — unchanged, S1.2/S1.3 |
| A whole `Policy` (multiple operations) | **Not** transactional — unchanged, S1.1 docstring's own long-standing statement |
| Filesystem destination write | Atomic at the filesystem-rename level only (temp file + `os.rename`) — the final path either shows the complete new file or is untouched; nothing in between is ever externally visible |
| A whole `execute_one`/`run` call | **Not** atomic across stages — a successful parse followed by a policy failure leaves no destination write (by the gating rule, section 10), but nothing "rolls back" the *source* (there is nothing to roll back — the source was only ever read) or reaches back into `Structure`'s own already-established per-operation guarantees. "Atomic" is never used to describe the whole pipeline; only the two narrower guarantees above are actual atomicity claims. |

## 27. Configuration relationship

**Recommended: kept separate**, exactly per the prompt's own strong preference, and directly
enabled by `execute_one`'s signature (`data: bytes, policy: Policy`, section 24) never mentioning
`Configuration` at all. `configuration.load_configuration_json(text) -> Configuration` remains
untouched; a `Configuration`'s `.policy` field is already a plain `Policy` object (S1.4), so calling
`execute_one(data, config.policy)` requires no glue code. This matters exactly for the reason given:
future deployments may obtain configuration from a file, an environment variable, a database row, a
request payload, or a hand-built Python object — none of that should ever need to pass through JSON
parsing to reach execution.

## 28. Proposed module boundaries

```text
fastdicomstructure/
    policy.py                (unchanged)
    configuration.py         (unchanged)
    execution.py             (new -- ExecutionResult, ExecutionOutcome, ExecutionDiagnostic,
                               execute_one(), run())
    adapters/
        __init__.py           (new -- AdapterResolutionError, resolve_source/resolve_destination,
                                the two closed registry dicts)
        filesystem.py          (new -- FilesystemSource, FilesystemDestination)
```

`source.py`/`destination.py`/`registry.py` as separate top-level files are **not** warranted for one
concrete adapter — that is framework-sized scaffolding for a single pair; `adapters/filesystem.py`
holding both classes, with the small shared resolution logic in `adapters/__init__.py`, is
proportionate. The package (not a flat module) signals the intended extension point for the
already-named future adapters (C-STORE/DICOMweb/database, P4.3–P4.5) without building anything
unused today.

Dependency direction:

```text
attrs ──────────┐
                ├──> execution.py ──> adapters/*
policy.py ──────┘         ^
                           |
configuration.py ─────────┘   (only via an optional convenience wrapper, e.g. run_configured())
```

`adapters/*` depends on nothing but the standard library and `execution.py`'s own small exception/
outcome vocabulary — never on attrs, never on `policy.py`, confirming adapters cannot become
alternate owners of DICOM or policy semantics (the invariant the prompt names explicitly).

## 29. Proposed progression after S1.4

| Increment | Capability added | Claim proved | Explicitly out of scope | Prerequisite | Freeze evidence |
|---|---|---|---|---|---|
| **S1.5** | `execution.py` core (`execute_one`, `ExecutionResult`) + `adapters/filesystem.py` pair + `run()` orchestration | Section 37's falsifiable claim | CLI, container, cloud, gateway convergence, concurrency/batch/retry, result serialization, streaming, keyword/network adapters | S1.4 (frozen) | New `test_execution.py`: probes A–H, atomicity boundaries, security/privacy sweep, regression (all prior tests green) |
| **S1.6** | Thin CLI (`load_configuration_json` → `resolve_*` → `run()` → render/exit code) | The same `ExecutionResult` is producible identically from a command-line invocation | Batch/directory processing, container, cloud | S1.5 | CLI-level tests + reused S1.5 probes via subprocess or in-process invocation |
| **S1.7** | Containerized execution proof | The same core, invoked through a thin container entrypoint, produces byte-identical `ExecutionResult`s to a local invocation | Cloud-specific behavior, orchestration (Kubernetes, etc.) | S1.5 (and likely S1.6, for something meaningful to invoke) | A measured container run compared against the same local run |
| **S1.8** | Cloud Run / serverless execution proof | The same core, invoked via one concrete deployment shape (request- or event-driven, chosen based on real product need at that time), produces the same `ExecutionResult` | Any other deployment shape not chosen, scalability/throughput claims | S1.7 | A real (but still narrowly scoped) deployed invocation, or an explicit decision to defer further |
| **S1.9** | Gateway convergence (separately authorized) | `transform.py`'s hand-rolled policy replaced by `policy.apply()`; evaluate whether `sink.py` becomes a `DicomwebDestination` adapter | Any change to gateway not explicitly authorized in that increment's own checkpoint | S1.5 (at minimum); a `DicomwebDestination` adapter design if `sink.py` convergence is attempted | Gateway's own existing test suite stays green; `test_apply_reproduces_gateway_demo_policy`-style equivalence proof extended to the real migration |

This avoids both named failure modes: it does not fragment "execution" into meaningless
sub-micro-increments (S1.5 is one coherent, freezable unit — core plus exactly one adapter pair),
and it does not let "execution" balloon into filesystem+CLI+Docker+GCP+gateway+batch in a single
step (each of those is its own row above, gated on the previous one actually existing and being
frozen).

## 30. Product Capability Map implications

**Nothing is promoted by this checkpoint** (design-only). Evidence that *would* justify promotion
if S1.5 is implemented as recommended and qualified:

| Capability | Current | Evidence needed to promote | Stays as-is if not met |
|---|---|---|---|
| P4.x Extensible output adapters | `PLANNED (S1.5)` | A qualified `FilesystemDestination` behind the closed registry, exercised by Probe A/F | `PLANNED` |
| P2.2 Source configuration | `PLANNED` | A qualified `FilesystemSource` resolving and executing a `source` envelope end-to-end | `PLANNED` |
| P2.3 Destination configuration | `PLANNED` | Same, destination side | `PLANNED` |
| P7.2 Audit/event output | `PARTIAL` | `ExecutionResult` qualified across all seven outcomes (section 9), shown sufficient for the section 20 fan-out without new coupling | `PARTIAL` (most likely secondary candidate besides P2.2/P2.3/P4.x) |

**Must remain `PLANNED`/`CANDIDATE`/`BLOCKED` after S1.5, regardless of implementation quality**,
because S1.5 as scoped cannot produce evidence for them:

- P5.2 CLI — `PLANNED` (S1.6).
- P5.3 Container, P5.4 Cloud function/serverless — `CANDIDATE` (S1.7/S1.8).
- P5.5 Gateway convergence — `DEFERRED/BLOCKED` (S1.9, unchanged from its current disposition).
- P6.3 Scalability, P6.4 Deployment portability — `CANDIDATE` (S1.5 tests execution portability
  only, not deployment portability — see section 33's explicit 4-way split).
- P3.3 Streaming input — `BLOCKED` (attrs prerequisite unchanged).
- P4.3/P4.4/P4.5 (C-STORE/DICOMweb/database) — `CANDIDATE` (no adapter for any of these exists or is
  built by S1.5).
- P7.3 Evidence Packet integration — `CANDIDATE` (section 20, no design work).

## 31. Falsifiable S1.5 claim

Refined from the prompt's own starting point, tightened to name the exact adapter pair and exclude
every claim S1.5 does not actually test:

> Given a valid Configuration V1 document naming the filesystem source and filesystem destination
> adapters, and a Policy composed only of the V1 declarative operations, fastDICOMstructure can
> execute one DICOM object's configured acceptance and mutation policy through the `execute_one`/
> `run` execution boundary, producing results (including rejection, operation failure, parse
> failure, and destination failure) that are observably identical whether that boundary is invoked
> through the filesystem adapter pair or by a caller supplying DICOM bytes directly — while
> `policy.py`, `configuration.py`, and `fastdicomattrs` remain completely unmodified.

This is **execution portability** specifically (see the 4-way split below), not deployment,
container, or cloud portability, and makes no scalability, streaming, or protocol-interoperability
claim.

**Separated portability claims** (the prompt's own instruction to not collapse them into one):

1. **Policy portability** — already proven, S1.1–S1.4, unaffected by S1.5.
2. **Execution portability** — the claim above; this is what S1.5 actually tests (Probe H vs. Probe
   A producing the same `ExecutionResult` shape for the same underlying bytes/policy).
3. **Adapter portability** — only partially testable in S1.5, since only one concrete adapter pair
   exists; Probe H (no adapter at all) is the strongest partial evidence available now that the
   boundary holds even in the degenerate zero-adapter case.
4. **Deployment portability** (container/cloud) — **not tested by S1.5 at all**; deferred to
   S1.7/S1.8.

## 32. Implementation freeze criteria (recommended, for the future S1.5 implementation turn)

- All existing 216 tests remain green; `policy.py` and `configuration.py` are byte-for-byte
  unchanged unless a genuine, separately-justified defect is discovered (and if so, STOP and report
  it rather than silently fixing it in this increment, per established discipline).
- `attrs` remains at `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6`, unmodified.
- Adapter-specific option validation lives in `adapters/filesystem.py`, never in `configuration.py`.
- `execute_one` proven directly (no adapter) and via `run()` (with the filesystem pair) to produce
  identical `PolicyResult`s for identical inputs — a direct semantic-equivalence test mirroring
  S1.4's own `SemanticEquivalenceTest` pattern.
- Probes A–H (section 25) each have a corresponding passing test.
- The section 10 gating rule (`destination` invoked iff `PolicyResult.execution == COMPLETED`) is
  proven both for `REJECTED` and for `PARTIAL`.
- `RollbackError` propagates raw through `execute_one`/`run` (Probe E) — proven via the same kind of
  differential test S1.3 used to prove its own rollback-catching boundary is real, not vacuous.
- Malformed DICOM (Probe C) and destination failure (Probe F) each produce their own distinct
  `ExecutionOutcome`, never collapsed into a generic `FAILED`.
- `AdapterResolutionError` is raised for an unsupported adapter type (Probe G), never surfaced as an
  `ExecutionResult`.
- No PHI-bearing value appears in any `ExecutionDiagnostic` — a mechanical sweep test, mirroring
  S1.4's `SecurityQualificationTest`, using a known sensitive literal.
- Filesystem destination output safety (temp file + atomic rename, reject-existing-by-default,
  cleanup on failure) is directly tested, including a simulated late-stage failure.
- `ExecutionResult` construction is deterministic (repeated runs against unmodified input produce
  identical results, mirroring `resolve_locator`'s own determinism proof from S1.1).
- The same `Policy` produces the same `PolicyResult` through `execute_one` as through direct
  `policy.apply()` — no behavior change introduced by the execution wrapper.
- Explicit/Implicit VR LE equivalence, already established at the policy layer (S1.4), is confirmed
  by at least one smoke-level regression test through the new execution path — not re-proven from
  scratch.
- No new Pixel Data decoding/materialization is introduced beyond the one documented,
  accepted whole-object copy named in section 18.
- No file in `fastDICOMgateway` is touched.
- No dependency on any cloud SDK, container tooling, or Dockerfile is introduced.
- No concurrency, batching, or retry framework is introduced unless a future authorization
  explicitly asks for it.
- Any performance measurement is smoke/regression evidence only (ruling out pathological behavior),
  never a throughput or scalability product claim.

## 33. Blockers/gaps

None found that require changing any frozen contract in `policy.py`, `configuration.py`, or attrs.
Two genuine, pre-existing, unrelated-to-S1.5 gaps are reconfirmed (not new):

1. attrs has no streaming parse primitive (P3.3, `BLOCKED`, unchanged).
2. attrs' Pixel Data extent (byte length) does not cross the C ABI (P6.2, `PARTIAL`, unchanged) —
   irrelevant to S1.5's own scope (S1.5 never inspects Pixel Data specifically) but relevant to any
   future size-aware adapter behavior, noted for completeness.

One new, genuinely S1.5-introduced consideration (not a blocker, a design decision already resolved
above): `execute_one` is the first place in this repository's production-shaped code that would call
`structure.write_bytes()` as part of an ordinary execution path (previously only tests and the
example demo called any write primitive) — meaning `SERIALIZATION_FAILED` (section 9) is a genuinely
new failure category this checkpoint had to identify, not one inherited unchanged from S1.1–S1.4.

## 34. Final recommendation

The evidence — both the direct inspection of `policy.py`/`configuration.py`/attrs and, most
significantly, `fastDICOMgateway`'s independent, already-shipped convergence on a structurally
similar (curated, PHI-safe, three-way rejection/success/destination-failure) result model —
supports the architecture recommended above with no discovered contradiction to any frozen
contract. The scope (execution core + exactly one adapter pair, no CLI/container/cloud/gateway/
batch) matches the smallest coherent unit that can actually prove the central S1.5 question.

**READY FOR S1.5 IMPLEMENTATION**

```text
attrs A1     FROZEN @ 46bf7d3

S1.1        FROZEN @ bdc324c
S1.2        FROZEN @ 53ecb83
S1.3        FROZEN @ 25615dd
S1.4        FROZEN @ 8879ca7

S1.5        DESIGN CHECKPOINT ONLY — READY FOR S1.5 IMPLEMENTATION
S1.6        NOT STARTED
```

No production code was written, no test was modified, no file in `fastDICOMattrs` or
`fastDICOMgateway` was touched, and no container or cloud resource was created or deployed during
this checkpoint.

---

## Accepted disposition and corrections (recorded post-acceptance)

This checkpoint was **accepted for implementation** as `S1.5 — Execution Core + Filesystem Adapter
Proof`, with three bounded corrections. The analysis above is preserved unchanged as the original
evidence and reasoning trail; this section records the disposition only.

**Correction 1 — persistence gate.** Section 10's gating rule ("destination invoked iff
`PolicyResult.execution == COMPLETED`") is **insufficient** and is corrected: the positive
persistence-eligibility condition must check **both** `PolicyResult.execution ==
PolicyExecutionStatus.COMPLETED` **and** `PolicyResult.decision` is an accepted/transformed success
state (`Decision.ACCEPT`/`Decision.TRANSFORM`), using the frozen `Decision` vocabulary directly —
never relying on the fact that, in today's frozen `policy.py`, these two dimensions happen to move
in lockstep. `PolicyResult`/`Decision` themselves are not modified.

**Correction 2 — no execution identity in S1.5.** The proposed `identity: Optional[str]` field is
**removed** from `execute_one`'s contract (section 34's original field list) and from
`ExecutionResult` entirely. `execute_one(data: bytes, policy: Policy) -> ExecutionResult` — no
identity parameter, no identity field. `FilesystemSource` may know its own configured path
internally (it must, to read the file) but that path never becomes part of `ExecutionResult` or any
diagnostic surface. Identity/provenance is deferred until a real consumer establishes the required
semantics and privacy boundary.

**Correction 3 — execution equivalence claim, narrowed.** Section 25/33's claim that `run()` and
`execute_one()` can produce "identical" results is corrected: they operate at different scopes and
must not be forced into a superficially symmetric outcome vocabulary. `execute_one` owns exactly
parse → policy → conditional serialization, and can produce `{SUCCEEDED, PARSE_FAILED,
POLICY_REJECTED, POLICY_PARTIAL, SERIALIZATION_FAILED}`; `run` additionally owns source acquisition
and conditional destination persistence around that same core, and can additionally produce
`{SOURCE_FAILED, DESTINATION_FAILED}` — stages `execute_one` does not own and must not be forced to
model. The falsifiable claim is narrowed accordingly: for identical acquired bytes and the same
`Policy`, `run()`'s use of the parse/policy/serialization lifecycle is exactly `execute_one()`'s own
semantics (implemented by `run()` literally calling `execute_one()`, not a parallel reimplementation).

See `docs/architecture/S1_5_EXECUTION_ARCHITECTURE_IMPLEMENTATION_REPORT.md` for the frozen
implementation record, qualification evidence, and final freeze disposition.
