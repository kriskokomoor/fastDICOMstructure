# S1.6 Design Checkpoint — Thin CLI Consumer

**Status: ANALYSIS AND DESIGN ONLY.** No production code was written, no test was modified, no
frozen file was touched, and nothing was committed during this checkpoint. Every claim below was
verified against the actual frozen source (read directly for this checkpoint), not recalled from
memory.

## 1. Verified frozen starting state

| Item | Commit | Verified |
|---|---|---|
| fastDICOMattrs | `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6` | matches, clean |
| fastDICOMstructure S1.5 | `350f88c98acf39d197787bdb69848f8c325b4f94` | matches, HEAD, clean |

No discrepancy found; no commit was changed during this checkpoint.

## 2. Current test baseline

`python3 -m pytest tests/python/` — **252/252 passing** (216 pre-S1.5 + 36 from
`test_execution.py`), both working trees clean.

## 3. Problem statement

S1.5 proved a deployment-neutral execution core (`execute_one`/`run`) and one concrete adapter
pair (filesystem), but every existing caller is either a Python test or a direct library call.
`PRODUCT_CAPABILITY_MAP.md`'s P5.2 row has stood as `PLANNED` since S1.1, with the success
criterion **"a CLI invocation produces the same `PolicyResult` as a library call."** S1.6's job is
to prove exactly that, through a real, subprocess-invokable command, composing only what S1.1–S1.5
already built — never reimplementing DICOM parsing, policy application, serialization, or I/O, and
never inventing a second configuration surface.

## 4. Proposed CLI contract

The CLI owns exactly: argument parsing, composing the existing `load_configuration_json` →
`resolve_source`/`resolve_destination` → `check_source_destination_collision` → `run()` sequence,
rendering the resulting `ExecutionResult` (human-readable or a small curated JSON form), and
choosing a process exit code from a closed vocabulary. It owns nothing about DICOM, policy, I/O
mechanics, or Configuration semantics — every one of those stays exactly where S1.1–S1.5 already
put it.

Verified guard-rail findings (each investigated directly against the frozen source, not assumed):

- **DICOM parsing/serialization**: `execute_one` is already the sole caller of `read_buffer`/
  `write_bytes` (verified, `execution.py`). The CLI has no reason to import `fastdicomattrs` at
  all, and this design does not.
- **Policy application**: `policy.apply()` is called exactly once, inside `execute_one`. The CLI
  never constructs a `Policy` by hand (see section 7 — none is needed).
- **Filesystem I/O**: `FilesystemSource.acquire()`/`FilesystemDestination.write()` already own all
  file I/O, including the race-safe atomic-publish logic (S1.5). The CLI never calls `open()`
  against a *configured* source/destination path — the one place the CLI legitimately does its own
  file I/O is reading the `--config` document itself (a CLI-owned input, not a DICOM object).
- **`execution.run()` duplication**: not duplicated — see section 9's `run_configured` proposal,
  which composes existing functions rather than reimplementing their internals.
- **Retry/batch/concurrency**: none proposed (section 23).
- **A second configuration schema**: not introduced — the CLI's only new "schema" is its own
  argument list (`--config`, `--json`), which describes *how to invoke the tool*, not *what to
  execute*. The Configuration V1 document remains the sole authoritative execution description.
- **Deployment/container/cloud semantics**: none proposed.

## 5. Exact invocation syntax

```bash
python -m fastdicomstructure run --config configuration.json [--json]
```

Justification, derived rather than assumed (section 15 has the full packaging analysis): neither
`fastDICOMstructure` nor `fastDICOMattrs` has ever had *any* packaging metadata (`pyproject.toml`,
`setup.py`, `setup.cfg`) — both are consumed exclusively via `PYTHONPATH`/sibling-directory
discovery, documented as such in `fastdicomstructure/__init__.py`'s own docstring. `python -m
fastdicomstructure` requires zero new packaging metadata (only a `__main__.py`) and slots directly
into the existing consumption model. A `run` subcommand is included even though it is the only one
today, specifically so a future second verb (e.g. a `validate` command around
`configuration.to_canonical_json`) does not force a breaking invocation change later — this costs
nothing functionally (one `argparse` subparser) and is not scope creep.

`--config` is a required, explicit flag (not a bare positional) — self-documenting or one-argument
CLIs in the wild go both ways, but an explicit flag reads unambiguously at the call site and leaves
room for a second required-input mode later (e.g. stdin) without positional-argument ambiguity.

## 6. Argument ownership

| Argument | Owner | Rationale |
|---|---|---|
| `--config <path>` | CLI | The one required input: which Configuration V1 document to execute. |
| `--json` | CLI | Presentation mode only (section 10) — never changes execution semantics. |

**Deliberately absent**: `--source`, `--destination`, `--mutation-rule`, `--overwrite`, or any
other flag that would let the CLI describe *what* to execute independently of the Configuration
document. `Configuration.source`/`.destination` are `Envelope`s the CLI resolves through the
existing closed registry (`adapters.SOURCE_ADAPTERS`/`DESTINATION_ADAPTERS`) exactly as any other
caller would — accepting CLI flags that shadow or override envelope fields would create a second,
parallel configuration surface the checkpoint was explicitly told to guard against, and no evidence
gathered here justifies one.

## 7. Policy construction path

**Investigated directly, not hand-waved: there is no gap.** `configuration.Configuration.policy`
(verified, `configuration.py` line 498) is already a fully-constructed `policy.Policy` object —
`load_configuration`/`load_configuration_json` build it eagerly at load time
(`configuration._parse_policy`), not lazily or as a separate description. **Item 1 of the
checkpoint's own candidate list is the answer**: Configuration already contains sufficient policy
specification, and the existing composition mechanism (`load_configuration_json(text) ->
Configuration`, whose `.policy` field is directly usable) is already exactly what
`execution.run(source, policy, destination)` requires. No new function, no CLI-side policy
construction, and no gap of any kind exists here. The CLI's own responsibility is reduced to:
`config = load_configuration_json(text); result = run(source, config.policy, destination)` (or,
per section 9, `run_configured(config)`).

## 8. Configuration → adapter → execution composition path

```python
text = Path(args.config).read_text()
config = configuration.load_configuration_json(text)          # ConfigurationError -> exit 10
if config.source is None:
    # CLI-level precondition, not a modeled Configuration/execution failure -- `run`
    # requires a source; a Configuration valid under S1.4 may still lack one.
    ...usage error, exit 2...
source = adapters.resolve_source(config.source)                # AdapterResolutionError -> exit 11
destination = (adapters.resolve_destination(config.destination)
               if config.destination is not None else None)    # AdapterResolutionError -> exit 11
if destination is not None:
    adapters.check_source_destination_collision(source, destination)  # -> exit 11
result = execution.run(source, config.policy, destination)     # ExecutionOutcome -> exit 12-17
```

This is the exact sequence the S1.5 design checkpoint's own "preferred use" example specified — the
CLI does not bypass, reorder, or shortcut any step, and in particular never skips the collision
check even though doing so would "work" for the common case.

`config.destination is None` is treated as a legitimate mode, not an error: it falls directly out
of `execution.run`'s own frozen `destination=None` semantics ("no normal destination configured") —
a Configuration document with only `policy`/`source` populated becomes a free "evaluate this
Policy against this object without persisting anywhere" invocation, at zero CLI-specific logic.
This is documented as an intentional, minor, low-risk capability, not a new CLI concept.

## 9. Is `run_configured()` (or equivalent) justified?

**Yes, recommended — with one genuine architectural wrinkle that implementation must resolve
carefully, flagged explicitly below rather than papered over.**

The composition in section 8 is not "merely four already-clear lines": getting it right requires
(a) conditionally resolving the destination only when present, (b) performing the collision check
only when both resolve to filesystem adapters, and (c) doing so in the correct order (collision
check strictly before `source.acquire()` is ever reachable). This is exactly the kind of "easy to
subtly get wrong or drift on a second implementation" logic the S1.5 design checkpoint's own
dependency diagram already anticipated when it wrote `configuration.py --> execution.py (only via
an optional convenience wrapper, e.g. run_configured())` — i.e., `execution.py` was always the
anticipated eventual owner, once a second real consumer existed. S1.6 is that consumer.

```python
# execution.py (proposed addition)
def run_configured(config: "configuration.Configuration") -> ExecutionResult:
    """Composes resolve_source/resolve_destination/check_source_destination_collision/run
    for a caller that already has a loaded Configuration. Requires config.source is not
    None (a caller precondition, exactly like run() itself requiring a non-None source
    argument) -- raising is the caller's problem to avoid, not something this function
    defensively re-validates. Deferred (local) import of `adapters` -- see the circular-
    import note below."""
    from . import adapters as _adapters  # deferred: adapters -> adapters.filesystem -> execution
    source = _adapters.resolve_source(config.source)
    destination = (_adapters.resolve_destination(config.destination)
                   if config.destination is not None else None)
    if destination is not None:
        _adapters.check_source_destination_collision(source, destination)
    return run(source, config.policy, destination)
```

**Genuine architectural finding — a real circular import, not hypothetical.** `execution.py`
currently has zero dependency on `adapters` (verified). `adapters/filesystem.py` already imports
`execution` (for `SourceAcquisitionError`/`DestinationWriteError`). Adding `from . import adapters`
at module level to `execution.py` would create `execution → adapters → adapters.filesystem →
execution`, a real cycle. It is resolvable — and this codebase already uses the identical technique
once, in `adapters/__init__.py` itself, which defines `AdapterResolutionError` *before* importing
`.filesystem` (which imports it back) specifically so the partially-initialized module already has
what the cycle needs by the time it closes — but the safest, least fragile fix for a *second*
occurrence of this pattern is a **local (deferred) import inside `run_configured`'s own function
body**, not a module-level one, exactly as sketched above. This sidesteps any load-order fragility
entirely, since by the time anyone actually *calls* `run_configured`, the whole package has already
finished importing.

This is presented as a recommendation requiring explicit sign-off before implementation, since it
is an **additive** change to a frozen S1.5 file (`execution.py`) — no existing line changes, only a
new function is added, but "frozen" files still warrant deliberate, not silent, extension. The
fallback if this dependency edge is judged unwelcome: implement the identical composition directly
in `cli.py` instead (zero new dependency edges, but not reusable by a future non-CLI consumer, e.g.
a later container entrypoint or gateway convergence work, without duplicating it). This checkpoint
recommends the `execution.py` placement, but flags the fallback as equally viable if reviewed and
preferred.

## 10. Result rendering/serialization design

**Two independent questions, answered separately, as instructed.**

**Is this a reusable domain contract or CLI presentation?** CLI presentation, for now. The *shape*
of what is safe to expose (a curated `PolicyResult`/`ExecutionResult` subset, never `output_bytes`)
could become a reusable concern if a second consumer (a future container's structured logs, a
future service response body) needed the identical rendering — matching exactly how S1.4/S1.5 each
deferred generalizing something until a second real need existed. No second consumer exists yet, so
the rendering code is proposed to live in `cli.py`, not in `execution.py` or a new shared module.

**Minimum stable machine-readable representation.** A single flat JSON object per invocation,
mirroring `ExecutionResult`'s own shape plus a rendering of the attached `PolicyResult` (already a
privacy-qualified model, S1.3) — never re-deriving new fields, never exposing `output_bytes`:

```json
{
  "status": "succeeded",
  "policy": {
    "name": "basic-deidentification", "version": "1.0.0",
    "decision": "transform", "execution": "completed",
    "operations": [
      {"kind": "require", "execution": "completed", "satisfied": true, "count": 1},
      {"kind": "replace_text", "execution": "completed", "satisfied": null, "count": 1}
    ],
    "diagnostics": []
  },
  "diagnostic": null
}
```

`"status"` is deliberately the *same* closed vocabulary as the process exit code (section 12) —
`"configuration_error"`, `"adapter_resolution_error"`, or one of the seven `ExecutionOutcome`
values (lowercase, `.value`) — so the JSON field and the exit code are two views of one designed
property, not two independently-invented vocabularies that could drift apart. `"policy"` is `null`
when no `PolicyResult` exists (`SOURCE_FAILED`/`PARSE_FAILED`); `"diagnostic"` is `null` except for
`SOURCE_FAILED`/`PARSE_FAILED`/`SERIALIZATION_FAILED`/`DESTINATION_FAILED` — mirroring
`ExecutionResult`'s own established invariant exactly, never duplicating what `PolicyResult`
already carries. `output_bytes` never appears in any rendering, human or JSON — see section 11.
`OperationResult.tag` (a raw `(group, element)` int tuple) is rendered as the same canonical
`"(GGGG,EEEE)"` string Configuration V1 already uses, implemented locally in `cli.py` (a one-line
helper) rather than reaching into another module's private formatting function.

**Human-readable default** (no `--json`): a short, information-dense summary in the same plain
register as this whole codebase's own style —

```text
fastdicomstructure: SUCCEEDED
policy: basic-deidentification v1.0.0 -- decision=transform, execution=completed
  require        completed  satisfied=True   count=1
  replace_text   completed                   count=1
```

Neither rendering ever includes a source/destination path by default (see section 14) — an
operator who wants path confirmation already knows it, since they wrote it into the Configuration
document.

## 11. stdout/stderr contract

Derived from the actual invocation shapes above, not assumed:

- **stdout**: exactly one artifact per invocation — the JSON object (`--json`) or the
  human-readable summary (default) — for *every* modeled outcome, including
  `ConfigurationError`/`AdapterResolutionError` and all seven `ExecutionOutcome` values. A modeled
  "failure" (e.g. `POLICY_REJECTED`) is still a well-formed *result* the tool was asked to produce,
  not a usage error — it belongs on stdout exactly like a success does.
- **stderr**: reserved for two things only — `argparse`'s own usage errors (bad flags, missing
  `--config`), and Python's own default unhandled-exception traceback for anything this design
  deliberately does not catch (section 13).
- **exit status**: the coarse, closed machine outcome (section 12).

**Binary DICOM bytes are never written to a terminal**: `ExecutionResult.output_bytes` is excluded
from both renderers entirely — not truncated, not summarized by length, simply never referenced by
any rendering code path. This is a design-level exclusion, verified by the fact that neither
rendering function sketched above ever names `output_bytes`.

## 12. Process exit-code contract

A one-to-one mapping from the already-closed vocabularies this project has already built —
no new granularity invented, no invented collapsing either:

| Code | Meaning |
|---|---|
| 0 | `ExecutionOutcome.SUCCEEDED` |
| 1 | *(reserved, not assigned by this design — see section 13)* |
| 2 | CLI usage error (`argparse` failure; unreadable `--config`; Configuration has no `source`) |
| 10 | `configuration.ConfigurationError` |
| 11 | `adapters.AdapterResolutionError` |
| 12 | `ExecutionOutcome.SOURCE_FAILED` |
| 13 | `ExecutionOutcome.PARSE_FAILED` |
| 14 | `ExecutionOutcome.POLICY_REJECTED` |
| 15 | `ExecutionOutcome.POLICY_PARTIAL` |
| 16 | `ExecutionOutcome.SERIALIZATION_FAILED` |
| 17 | `ExecutionOutcome.DESTINATION_FAILED` |

`POLICY_REJECTED`/`POLICY_PARTIAL` are kept distinct (14 vs. 15) rather than collapsed, matching
this project's own consistent preference for distinguishable, closed vocabularies over conflation
(a caller may legitimately want to treat "a `Require` cleanly failed" very differently from
"something broke mid-mutation, safely rolled back, but is still an operational anomaly"). Eleven
total distinct codes (0, 1, 2, 10–17) is judged the smallest vocabulary that does not lose
information any real caller (a script, a future container health check) would plausibly need to act
on differently — not one code per `ExecutionDiagnostic`/`AdapterResolutionError` sub-code, which
would be over-granular for a process-exit-status vocabulary.

## 13. Exception boundary

**Recommendation: the CLI adds no handling whatsoever for `RollbackError` or any exception
`execute_one`/`run` do not already recognize.** Code 1 is not assigned by any explicit `except`
clause — it is simply Python's own default behavior for an uncaught exception reaching the top of
`__main__`, which the CLI does not intercept.

This was a genuine design choice, not the default by omission: an alternative considered was a
narrow `except policy.RollbackError` at the very top of `main()`, printing a deliberately
alarming, distinctly-formatted message before exiting with a *reserved* code. It is **rejected**:
building a bespoke "safe" formatter around content whose full safety has not been separately,
exhaustively qualified (`RollbackError`'s default message chain traces back to Structure-owned
strings only, verified by construction in S1.3 — but *any* genuinely unmodeled exception is, by
definition, unbounded and could contain anything) would itself risk creating a false sense of
safety around precisely the one category that is supposed to look abnormal. Letting Python's own
default traceback-to-stderr-then-exit-1 behavior apply is the most literal way to avoid "converting
[an] internal failure into an apparently ordinary policy outcome" — it is not made to look like any
of the eleven modeled codes above, and a caller (script or human) already knows code 1 conventionally
means "the process crashed," which is the accurate description. This mirrors the whole project's
own established discipline exactly: `policy.apply()` never catches `RollbackError`, `execute_one`/
`run` never catch it either — the CLI is the third, consistent layer to make the same choice, not a
new invention.

## 14. Security/privacy analysis

Every field the CLI's two renderers touch is already privacy-qualified by S1.3/S1.4/S1.5
(`Diagnostic`, `ConfigurationError`, `AdapterResolutionError`, `ExecutionDiagnostic` all use fixed,
curated messages, never `str(exception)`). The CLI introduces exactly two new surfaces requiring
their own qualification, not inherited "for free":

1. **`--config` file-read errors.** Read manually (`Path(args.config).read_text()`, not
   `argparse.FileType`, precisely so the CLI controls the resulting message rather than trusting
   `argparse`'s own default formatting) and wrapped in a short, curated usage-error message. The
   path itself *may* appear in this one message (an operator-supplied CLI argument, not a DICOM
   value) — this is a deliberate, narrow, and only place any path appears in default output,
   distinct from the established stance that `ExecutionResult`/`ExecutionDiagnostic` never carry
   one.
2. **The renderers themselves.** Must be proven, not assumed, never to fall back to a bare
   `repr(config)`/`repr(result)`/`str(exc)` on any code path, including partially-implemented or
   error-handling branches — see the required security probes (section 19).

`str(exc)`/`repr(exc)` on adapter/attrs exceptions are never placed in CLI output — only
`ExecutionDiagnostic.cause_type`/`ConfigurationError.code`/`AdapterResolutionError.code` (all
closed, class-name-or-enum-shaped strings) ever reach a renderer.

## 15. Packaging/entry-point design

Investigated directly: `fastDICOMstructure` and `fastDICOMattrs` have **no packaging metadata of
any kind** (`find . -iname "setup.py" -o -iname "pyproject.toml" -o -iname "setup.cfg"` returns
nothing in either repository) — both are consumed exclusively via `PYTHONPATH`/sibling-directory
discovery (documented in `fastdicomstructure/__init__.py`'s own docstring). Only `fastDICOMgateway`
has a `pyproject.toml` (hatchling-based), and it defines **no** `[project.scripts]` console-script
entry point either. A further search across all three repositories for existing CLI-like code found
only offline dev-tools in `fastDICOMattrs/tools/` (`argparse`, invoked directly as `python3
tools/script.py --flag value` — no packaging, no entry point) and `if __name__ == "__main__":`
demo scripts (`pipeline_demo.py`, `nested_mutation.py`, `smoke_test.py`) — **zero precedent for a
console-script entry point anywhere in this family.**

**Recommendation: `python -m fastdicomstructure` only, via a new `__main__.py`.** This requires
introducing no packaging metadata for the first time in this repository's history — a console-script
entry point (`[project.scripts]`) would require exactly that, which is explicitly out of scope
("avoid packaging churn unrelated to S1.6"). If a real packaging need arises later (e.g., actual
`pip install`ability for a future container image), a console-script entry point becomes a natural,
low-risk addition at that time — not before.

## 16. Proposed module/file changes

```text
python/fastdicomstructure/
    __main__.py     NEW -- thin shim: `from .cli import main; sys.exit(main())`
    cli.py           NEW -- build_parser(), main(argv=None) -> int, human/JSON renderers
    execution.py     ADDITIVE ONLY -- one new function, run_configured() (section 9);
                     zero changes to any existing line
```

`__main__.py` and `cli.py` are kept separate (rather than one file) specifically so `cli.py`
remains freely importable by tests (for in-process `main()` calls, section 19's Probe J) without
triggering any `__main__`-only side effect — a standard, well-established Python idiom (e.g.
`http.server`, `json.tool`).

## 17. Explicit files that must remain unchanged

`policy.py`, `configuration.py`, `adapters/__init__.py`, `adapters/filesystem.py` — byte-for-byte,
verified by `git diff --stat` against the S1.5 freeze commit at freeze time, exactly as every prior
increment has done. `fastdicomstructure/__init__.py` requires no change (submodules are importable
by dotted path without a re-export; `cli`/`__main__` are not added to `__all__` since they are not
meant to be imported as library surface, only invoked). No file in `fastDICOMattrs` or
`fastDICOMgateway`.

## 18. Qualification probes

All ten (A–J) designed as concrete, executable tests; each states its verification technique.

| Probe | Technique | What it proves |
|---|---|---|
| A — successful configured CLI execution | Real Configuration V1 file, real filesystem source/destination, **subprocess** invocation (`subprocess.run([sys.executable, "-m", "fastdicomstructure", "run", "--config", ...])`) | exit 0; destination file created; reparses cleanly; pydicom/DCMTK confirm the mutation; stdout contains the expected human summary (or, with `--json`, a well-formed JSON object matching the closed shape) |
| B — policy rejection | Subprocess, a `Require` guaranteed to fail | exit 14; destination file **not** created; `policy_result.diagnostics` (via `--json`) carries `REQUIREMENT_UNSATISFIED`; no sensitive literal in stdout/stderr |
| C — malformed DICOM | Subprocess, garbage bytes as the source file (reusing S1.5's own finding: both the lenient-diagnostic and the raised-`FdsError` sub-cases) | exit 13; `"status": "parse_failed"` |
| D — invalid Configuration V1 | Subprocess, a syntactically-invalid Configuration document | exit 10, **before** any source/adapter is ever touched (proven by a source path that would raise loudly if ever opened, e.g. a directory instead of a file, confirming acquisition never happened) |
| E — unknown adapter / invalid options | Subprocess, `{"type": "future-adapter", ...}` and separately a filesystem envelope missing `path` | exit 11 in both cases, distinguishable from any `ExecutionOutcome` exit code |
| F — source/destination collision | Subprocess, source and destination envelopes naming the identical resolved path | exit 11, proven that `source.acquire()` was never reached (e.g. the source file's mtime/content unchanged, or a source path that would error loudly if opened) |
| G — destination already exists | Subprocess, pre-existing destination file, default `overwrite=false` | exit 17 (`DESTINATION_FAILED`/`DESTINATION_ALREADY_EXISTS`), pre-existing destination content **unchanged** — the exact S1.5 race-safe semantics (section 19 of the S1.5 report) surfacing correctly through the CLI, not re-implemented by it |
| H — modeled partial policy execution | Subprocess, the same `Ensure(_TAG_AMBIGUOUS, ..., vr=None)` technique `test_execution.py` already uses | exit 15; destination not created; deterministic `"status": "policy_partial"` |
| I — raw rollback/internal exception | **In-process** call to `cli.main(argv)` (not subprocess — monkeypatching a subprocess is not possible), reusing `test_result_diagnostic.py`'s/`test_execution.py`'s own proven `mock.patch.object(fastdicomattrs.Structure, "set_value", flaky)` technique | `cli.main(...)` itself raises `policy.RollbackError` uncaught — asserted via `assertRaises`, never returns an exit code, never produces stdout/stderr output claiming a modeled result |
| J — direct architecture delegation | Two independent techniques: (1) black-box value comparison — the CLI's `--json` rendering of a successful run compared field-for-field against a direct, in-process `execution.execute_one(data, policy)` call on the identical bytes/policy; (2) in-process `cli.main(argv)` call with `fastdicomattrs.Structure.write_bytes`/`policy.apply` instrumented via the same counting-wrapper technique `test_execution.py`'s `DifferentialTest` already uses, confirming each is called **exactly once** | the CLI does not independently parse, apply, or serialize — it reaches the frozen `execute_one`/`run` call graph, not a parallel reimplementation |

Two additions beyond the letter list, each falsifying a distinct, significant claim:

- **K — destination-less "policy check" invocation** (section 8's free capability): a Configuration
  with `policy`/`source` but no `destination`; subprocess exit 0 (`SUCCEEDED`), no destination
  ever referenced, `output_bytes` never appears in any rendering.
- **L — CLI usage errors** (exit code 2): missing `--config`, unreadable `--config` path,
  Configuration with no `source` — each subprocess-invoked, each producing exit 2 and a stderr
  message (never stdout).

## 19. Differential/delegation qualification

Covered by Probe J above (both techniques). A third, cheap addition: run the *exact same*
Configuration document and fixture through (a) the CLI subprocess and (b) a direct in-process
`load_configuration_json` → `resolve_source`/`resolve_destination` → `run()` call, asserting the
resulting destination files are byte-identical — the strongest possible black-box proof that the
CLI is not a parallel execution path.

## 20. Real-DICOM qualification

Reuses `test_execution.py`'s own established fixture-building convention (duplicated locally, per
that file's own stated precedent) and both independent tools already integrated into this
codebase's qualification discipline: **pydicom** (`pydicom.dcmread`) and **DCMTK** (`dcmdump`,
resolved via `shutil.which`, skipped if unavailable) — applied to Probe A's destination file.
Neither tool is claimed to validate the CLI architecture itself, only the resulting DICOM
semantics, exactly matching every prior increment's own stated framing.

## 21. Performance characterization

Not a claim, a smoke check only: one subprocess invocation of Probe A's scenario, timed, asserting
completion well within a generous bound (e.g. a few seconds) — catching pathological startup
overhead (an accidental heavy import, a hang) without benchmarking DICOM parsing or making any
throughput/scalability claim. This mirrors S1.4/S1.5's own `PerformanceSmokeTest` pattern exactly.

## 22. Product Capability Map implications

**P5.2 (CLI)** is the sole primary target. Its own row already states the exact success bar this
checkpoint has designed toward: *"A CLI invocation produces the same `PolicyResult` as a library
call."* Evidence needed to promote it to `CURRENT`: Probe J (both techniques) passing, plus Probes
A–L collectively demonstrating a working, subprocess-invokable, exit-code-and-rendering-complete
CLI. **Not promoted by this checkpoint** — design only.

**Must remain unchanged after S1.6, and this design produces no evidence for any of them**: P5.3
(Container), P5.4 (Cloud/serverless), P5.5 (Gateway convergence), P3.3 (Streaming), P6.3
(Scalability), P4.3/P4.4/P4.5 (C-STORE/DICOMweb/database — the CLI exercises only the existing,
already-qualified filesystem adapter, per the explicit scope exclusion), P7.3 (Evidence Packet
integration). **P6.4 (Deployment portability)** lists `P5.2-P5.4` as its prerequisite chain — S1.6
alone satisfies only one of three; it should **not** be promoted, though its own evidence column
may note one prerequisite is now met. **P7.2 (Audit/event output)** should **not** be promoted
merely because the CLI can render results — this repeats the exact caution the S1.5 implementation
report already applied to itself for the identical reason (presentation is not a new domain-layer
audit capability).

## 23. Explicit non-goals

Directory traversal, globbing, multiple-object execution, batch processing, queues, concurrency,
retries, network fetching, HTTP, DICOMweb, C-STORE, Orthanc integration, streaming, bounded-memory
redesign, containerization, Cloud Run/serverless, gateway convergence, plugin discovery, dynamic
adapter loading, telemetry frameworks, generalized logging infrastructure, a console-script
packaging entry point, result serialization as a reusable domain contract (kept CLI-local, section
10), and CLI-level source/destination/mutation flags that would shadow the Configuration document.

## 24. Known risks/open questions

1. **The `execution.py` circular-import wrinkle (section 9)** is real and requires a deferred
   (local, in-function) import, not a module-level one — flagged for explicit review before
   implementation, with a documented fallback (inline the composition in `cli.py` instead) if the
   dependency edge is judged unwelcome.
2. **Path echoing in CLI usage errors** (`--config` read failures, section 14, item 1) is a
   deliberate, narrow exception to the "never echo a path" discipline established for
   `ExecutionResult`/diagnostics — worth explicit confirmation that this narrower, CLI-argument-only
   exception is acceptable, since it is the one place this design's privacy posture is not
   perfectly uniform with the rest of the project.
3. **`run_configured`'s precondition** (`config.source is not None`) is enforced by the *caller*
   (the CLI), not defensively re-validated inside `run_configured` itself — consistent with this
   codebase's general style of trusting preconditions rather than defensive re-validation at every
   layer, but worth confirming this is the preferred style here too rather than a defensive check
   inside `run_configured`.
4. No open question was found regarding whether Configuration V1 can supply what `execution.run()`
   needs — section 7 found a clean, complete answer, not a gap.

## 25. Falsifiable S1.6 claim

> Given a valid Configuration V1 document naming the filesystem source and destination adapters, a
> real subprocess invocation of `python -m fastdicomstructure run --config <path>` produces process
> exit status, stdout/stderr content, and destination-file side effects that are fully determined by
> — and never diverge from — the same `execute_one`/`run` execution boundary a direct, in-process
> Python caller would reach for identical acquired bytes and Policy, across every one of the seven
> `ExecutionOutcome` values plus `ConfigurationError`/`AdapterResolutionError`, while introducing no
> new DICOM-parsing, policy-application, serialization, or filesystem-I/O logic of its own.

Not claimed: container portability, cloud portability, scalability, streaming, batch/concurrency/
retry behavior, non-filesystem adapter support, or performance characteristics beyond a pathological-
overhead smoke check.

## 26. Implementation recommendation

**PROCEED WITH CORRECTIONS.**

Not an unconditional `PROCEED` because two decisions in this design materially affect a frozen file
and a privacy-posture boundary and deserve explicit confirmation before implementation begins, not
silent assumption:

1. Confirm whether `run_configured()` should be added to `execution.py` (recommended, with the
   deferred-import technique specified in section 9) or instead kept entirely inside `cli.py` (the
   documented fallback) — this is the one place this checkpoint proposes touching a frozen S1.5
   file, even though additively.
2. Confirm the narrow, CLI-argument-only exception to the "never echo a path" discipline (section
   14, item 1; risk 2 in section 24) is acceptable as scoped.

No other blocker, gap, or contradiction with any frozen contract was discovered. Configuration V1
was found to already fully supply what `execution.run()` requires (section 7) — a clean result, not
a hedge. The proposed CLI surface (one subcommand, one required flag, one presentation flag, eleven
exit codes) is judged the smallest surface that genuinely exercises S1.5 end-to-end as a real
consumer, consistent with every prior increment's own "one bounded claim per increment" discipline.

No production code was written, no test was modified, no frozen file was touched, and nothing was
committed during this checkpoint.
