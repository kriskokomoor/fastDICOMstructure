# S1.6 Implementation Report — Thin CLI Consumer

## 1. Starting commits

| Item | Commit |
|---|---|
| fastDICOMattrs | `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6` (unchanged throughout S1.6) |
| fastDICOMstructure | `350f88c98acf39d197787bdb69848f8c325b4f94` (S1.5 freeze) |

Both verified via `git rev-parse HEAD` immediately before implementation began, matching the
authorized starting state exactly, working trees clean apart from the already-accepted
`S1_6_THIN_CLI_DESIGN_CHECKPOINT.md`. Baseline: `python3 -m pytest tests/python/` — **252/252
passing**.

## 2. Exact files changed

```text
python/fastdicomstructure/cli.py             NEW
python/fastdicomstructure/__main__.py        NEW
python/fastdicomstructure/execution.py       ADDITIVE ONLY -- one new function, run_configured();
                                              zero changes to any existing line (verified: git diff
                                              shows a pure insertion, no deletions/modifications
                                              beyond the __all__ list gaining one entry)
tests/python/test_cli.py                     NEW (26 tests)
docs/architecture/PRODUCT_CAPABILITY_MAP.md  MODIFIED -- P5.2 promoted, P6.4 annotated
docs/architecture/S1_6_THIN_CLI_IMPLEMENTATION_REPORT.md  NEW (this report)
```

**Untouched, verified by `git diff <S1.5 freeze commit> -- <path>` returning empty**: `policy.py`,
`configuration.py`, `adapters/__init__.py`, `adapters/filesystem.py`, `fastdicomstructure/__init__.py`.
No file in `fastDICOMattrs` or `fastDICOMgateway`.

## 3. Implementation architecture

```text
python -m fastdicomstructure run --config <path> [--json]
        |
        v
__main__.py  (thin shim: from .cli import main; sys.exit(main()))
        |
        v
cli.py: main(argv) -> build_parser/parse_args -> _run_command(args)
        |
        v
Path(args.config).read_text()            -- CLI's own I/O, for the config document only
        |
        v
configuration.load_configuration_json(text)     -- unchanged, S1.4
        |
        v
execution.run_configured(config)                -- S1.6 addition to execution.py:
        |                                            resolve_source / resolve_destination /
        |                                            check_source_destination_collision / run()
        v
ExecutionResult
        |
        v
render_json() / render_text()  -- cli.py-local presentation, never touches output_bytes
        |
        v
stdout (the one requested artifact) + process exit code (closed vocabulary)
```

`cli.py` imports `configuration`, `adapters`, `execution`, and `policy.PolicyResult` (for a type
hint only) — never `fastdicomattrs`. It never constructs a `Policy`, never calls an adapter's
`acquire()`/`write()` directly, and never calls `execution.run()` directly (always through
`run_configured`).

## 4. `run_configured()` (execution.py addition)

```python
def run_configured(config) -> ExecutionResult:
    from . import adapters as _adapters
    source = _adapters.resolve_source(config.source)
    destination = (_adapters.resolve_destination(config.destination)
                   if config.destination is not None else None)
    if destination is not None:
        _adapters.check_source_destination_collision(source, destination)
    return run(source, config.policy, destination)
```

Implemented exactly as approved: a deferred (local, in-function) import of `adapters`, avoiding the
real load-time circular dependency (`execution → adapters → adapters.filesystem → execution`) that
a module-level import would have created. Pure composition — no new execution semantics, no
duplicated adapter/DICOM/policy/serialization/filesystem-I/O logic. `config.source is not None` is
a caller precondition, not defensively re-validated inside the function (per the approved design).

## 5. CLI contract

```bash
python -m fastdicomstructure run --config configuration.json [--json]
```

Exactly two flags, both CLI-local: `--config` (required) and `--json` (a presentation switch only —
verified it never changes which branch of `_run_command` executes, only how the same result is
rendered). No source/destination/mutation/overwrite/batch/retry/network flag exists. Configuration
V1 remains the sole execution-configuration surface.

## 6. Rendering

Two renderers in `cli.py`, both operating only on already-privacy-qualified fields
(`PolicyResult`/`OperationResult`/`Diagnostic`/`ExecutionDiagnostic`'s own `code`/`message`/
`cause_type`/enum `.value`s) — neither ever references `ExecutionResult.output_bytes`, neither ever
falls back to `str(exc)`/`repr(exc)`/`repr(config)`/`repr(result)` (mechanically confirmed, section
11). `render_json`'s top-level `"status"` field is drawn from the identical closed vocabulary as the
process exit code (`"configuration_error"`, `"adapter_resolution_error"`, or one of the seven
`ExecutionOutcome.value` strings) — one designed property expressed two ways, not two independently
invented vocabularies.

## 7. Exit-code contract

Implemented exactly as specified: 0 (`SUCCEEDED`), 1 (reserved, unassigned — Python's own default
for any uncaught exception), 2 (CLI usage/precondition/config-read failure), 10
(`ConfigurationError`), 11 (`AdapterResolutionError`), 12–17 (one per remaining `ExecutionOutcome`
value). No blanket `except Exception` exists anywhere in `cli.py` — verified by direct inspection:
the only `except` clauses are `except OSError` (config file read), `except
configuration.ConfigurationError`, and `except adapters.AdapterResolutionError`.

## 8. Qualification evidence — Probes A–L

All implemented in `tests/python/test_cli.py`, all passing:

| Probe | Result |
|---|---|
| A | Subprocess exit 0; destination file created, reparses cleanly; `PatientName == "ANONYMIZED"`; both JSON and human-readable renderings verified; `"output_bytes"` confirmed absent from stdout |
| B | Exit 14; destination never created; `REQUIREMENT_UNSATISFIED` present in `PolicyResult.diagnostics`; `ExecutionResult.diagnostic` absent (not duplicated); no sensitive-literal leakage |
| C | Exit 13 for both the lenient-diagnostic malformed-input path and the raised-`FdsError` (unsupported transfer syntax) path — `cause_type == "FdsError"` confirmed present only in the latter |
| D | Exit 10; a source path that would raise loudly if opened (a directory) confirms acquisition was never attempted, since the failure is `MISSING_REQUIRED_FIELD` at the Configuration-load stage, before any adapter resolution |
| E | Exit 11 for both an unknown adapter `type` (`ADAPTER_TYPE_UNKNOWN`) and invalid filesystem options (`ADAPTER_OPTIONS_INVALID`) |
| F | Exit 11 (`SOURCE_DESTINATION_COLLISION`); shared file content proven byte-identical to its original bytes afterward — never touched |
| G | Exit 17 (`DESTINATION_ALREADY_EXISTS`); pre-existing destination content proven unchanged |
| H | Exit 15 (`POLICY_PARTIAL`, via an `Ensure` on an ambiguous VR tag); destination never created; `ExecutionResult.diagnostic` absent |
| I | `cli.main(argv)` called in-process (subprocess cannot be monkeypatched) with `Structure.set_text`/`Structure.set_value` patched to force a rollback-then-restore-failure — `policy.RollbackError` propagates **uncaught** out of `main()`, verified via `assertRaises`, never returning an exit code |
| J | Two independent techniques, both passing (section 9) |
| K | A Configuration with `policy`/`source` but no `destination`: exit 0, destination never referenced anywhere, directory contents proven to contain only the source and config files afterward |
| L | Missing `--config` (argparse itself, exit 2, no stdout); unreadable `--config` path (exit 2, path echoed to stderr per the approved exception); Configuration with no `source` (exit 2, no stdout) |

## 9. Differential/delegation qualification (Probe J)

**Technique 1 — black-box equivalence.** The identical fixture bytes and Policy executed once via a
real CLI subprocess (`--json`) and once via a direct, in-process
`configuration.load_configuration_json` → `execution.run_configured` call: the two destination
files are proven **byte-identical**, and the CLI's JSON `decision`/`execution` fields match the
directly-obtained `PolicyResult`'s own `.value`s exactly.

**Technique 2 — instrumentation.** `policy.apply` and `fastdicomattrs.Structure.write_bytes` were
each wrapped with a counting spy (`mock.patch.object`, the identical technique
`test_execution.py`'s own `DifferentialTest` already uses) around an in-process `cli.main(argv)`
call: both are confirmed called **exactly once**. Together, both techniques prove the CLI reaches
the frozen `execute_one`/`run` call graph rather than an independent reimplementation.

## 10. Real-DICOM validation

`RealDicomQualificationTest` (2 tests), both executed (not skipped) in this environment: Probe A's
scenario invoked as a real subprocess, output verified by Structure's own lossless self-reparse,
**pydicom** (`PatientName == "ANONYMIZED"`, `Modality == "CT"`), and **DCMTK `dcmdump`** (return
code 0, output contains `"ANONYMIZED"`). Neither tool is claimed to validate the CLI architecture
itself, only the resulting DICOM semantics.

## 11. Security/privacy qualification

Six tests, all passing:

- A sensitive literal embedded in a **source/destination path component** (a directory name) is
  confirmed absent from stdout and stderr, in both JSON and human-readable rendering, across an
  existing-destination failure scenario — proving the general "never echo a configured path"
  discipline holds under the CLI, unchanged from S1.5.
- The **approved narrow exception** is confirmed working precisely as scoped: an unreadable
  `--config` argument's own path *is* echoed to stderr — and confirmed this occurs *only* for that
  one argument, not for any configured source/destination path (the two tests above and this one
  are deliberately paired to prove the boundary is exactly where the review approved it, not
  broader).
- A sensitive literal placed in a **DICOM value** (`PatientName`) on a rejected object is confirmed
  absent from all output.
- A static source-level check confirms `cli.py` contains no `str(exc)`, `repr(exc)`, `repr(config)`,
  or `repr(result)` construct anywhere.
- The JSON rendering is confirmed to never contain an `"output_bytes"` key under any circumstance
  tested.

## 12. Performance characterization

One smoke test: a full subprocess invocation of Probe A's scenario, timed, asserted to complete
well under a generous 10-second bound. This rules out pathological startup/orchestration overhead
only — no throughput, scalability, or DICOM-parsing-speed claim is made.

## 13. Regression totals

| Point | Total | Result |
|---|---|---|
| Baseline (S1.5 freeze, before S1.6 work) | 252 | all passing |
| After S1.6 implementation | 278 | all passing (252 pre-existing + 26 new, all in `test_cli.py`) |

No existing test file was modified. `policy.py` and `configuration.py` are confirmed byte-for-byte
unchanged; `adapters/__init__.py` and `adapters/filesystem.py` are confirmed byte-for-byte
unchanged; `execution.py`'s diff is confirmed purely additive (one new function, one `__all__`
entry, zero deletions or modifications to existing lines).

## 14. Product Capability Map changes

- **P5.2 (CLI)**: `PLANNED` → **`CURRENT`** — the row's own stated success criterion ("a CLI
  invocation produces the same `PolicyResult` as a library call") is directly evidenced by Probe J.
- **P6.4 (Deployment portability)**: left `CANDIDATE` — annotated to note one of its three
  prerequisites (P5.2) is now demonstrated, but P5.3 (container) and P5.4 (cloud/serverless) remain
  undemonstrated, so the row itself is not promoted.
- **Left unchanged, as required**: P5.3, P5.4, P5.5, P6.3, P3.3, P4.3/P4.4/P4.5, P7.2, P7.3 — none
  of these is touched or promotable by S1.6's own scope.

## 15. Explicit non-claims

Container portability, cloud portability, scalability, streaming, batch/concurrency/retry behavior,
non-filesystem adapter support, gateway convergence, a console-script packaging entry point, and any
performance characteristic beyond the pathological-overhead smoke check — none of these was tested,
and none is asserted.

## 16. Final S1.6 verdict

**PASS.** All twelve required probes (A–L) pass; both delegation-proof techniques for Probe J pass;
real-DICOM validation (pydicom + DCMTK) confirms resulting semantics; security qualification
confirms no sensitive-literal leakage anywhere except the one approved, narrowly-scoped
`--config`-argument exception; the performance smoke check shows no pathological overhead; 278/278
tests passing; every protected file confirmed byte-for-byte unchanged; `execution.py`'s only change
is the approved additive `run_configured()` function.

**Independent review verdict**: PASS — FREEZE AUTHORIZED, no implementation changes requested.

## 17. Freeze commit and post-commit verification

**Exact S1.6 freeze commit**: `7564cf71557eab37fcdc66d3c5ff19a3a7284ca9`

Post-commit verification, performed after this commit was created:

- `python3 -m pytest tests/python/` — **278/278 passing**.
- `git status --porcelain` (fastDICOMstructure) — clean.
- `git status --porcelain` (fastDICOMattrs) — clean; `git rev-parse HEAD` —
  `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6`, unchanged.
- `policy.py`, `configuration.py`, `adapters/__init__.py`, `adapters/filesystem.py`,
  `fastdicomstructure/__init__.py` — confirmed byte-for-byte unchanged against the S1.5 freeze
  commit (`git diff 350f88c98acf39d197787bdb69848f8c325b4f94 -- <path>` empty for each).
- fastDICOMgateway — not modified by S1.6; its pre-existing dirty working tree (16 changed/untracked
  entries, present before this increment began) is unrelated to this increment and was left as-is.

```text
attrs: FROZEN @ 46bf7d3
S1.1: FROZEN @ bdc324c
S1.2: FROZEN @ 53ecb83
S1.3: FROZEN @ 25615dd
S1.4: FROZEN @ 8879ca7
S1.5: FROZEN @ 350f88c
S1.6: FROZEN @ 7564cf7
S1.7: NOT STARTED
```

---

**Erratum (added during public-release preparation, dated separately from the original freeze
above; the original claim above is preserved unchanged):** `7564cf71557eab37fcdc66d3c5ff19a3a7284ca9`
is not reachable from this repository's `main` history. The commit actually reachable on `main`
with parent `350f88c` (the same S1.5 freeze this report diffs against) is
`9b84a2a6...` (`git log --oneline` on `main` shows `9b84a2a "S1.6: freeze thin CLI consumer"`
immediately after `350f88c`). `git diff 7564cf7 9b84a2a` shows the only difference between the two
is this report's own section 17 (30 insertions, 2 deletions) — a documentation-only amendment made
after the commit this report originally cited, never a change to `policy.py`, `configuration.py`,
`adapters/`, or `fastdicomstructure/__init__.py`. **Cite `9b84a2a` as the S1.6 freeze commit** in
any release manifest or downstream reference; the original hash above is left as originally
written, not corrected in place, per this project's evidence-preservation policy.
