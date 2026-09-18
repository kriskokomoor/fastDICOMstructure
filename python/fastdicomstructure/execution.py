"""S1.5 -- Execution Core + Filesystem Adapter Proof.

The deployment-neutral execution core over `policy.py`, plus the small,
S1.5-owned operational-result model (`ExecutionResult`/`ExecutionOutcome`/
`ExecutionDiagnostic`) that reports what happened *around* a Policy run --
acquiring bytes, parsing, serializing, and persisting -- without policy.py
ever needing to know any of that exists. See
docs/architecture/S1_5_EXECUTION_ARCHITECTURE_DESIGN_CHECKPOINT.md for the
full design rationale (including the three accepted corrections) and
docs/architecture/S1_5_EXECUTION_ARCHITECTURE_IMPLEMENTATION_REPORT.md for
qualification evidence; this module's own docstrings cover only what a
caller needs to know.

Ownership boundary, stated up front:

* **This module is the sole caller of attrs' parse/write primitives** in the
  production execution path (`read_buffer`/`write_bytes`). Adapters (see
  `adapters/`) never parse or serialize DICOM, never see a `Structure`, a
  `Policy`, or a `PolicyResult` -- they exchange raw `bytes` only.
* **`policy.py` is completely unmodified and unaware this module exists.**
  `execute_one` calls `policy.apply()` exactly as any other caller would;
  nothing here reinterprets or duplicates `PolicyResult`'s own diagnostics.
* **No Configuration awareness.** `execute_one(data: bytes, policy: Policy)`
  never mentions `configuration.Configuration` -- a caller who already has
  bytes and a `Policy` needs neither a Configuration document nor an
  adapter to use it (see `docs/architecture/
  S1_5_EXECUTION_ARCHITECTURE_DESIGN_CHECKPOINT.md`, Probe H).
* **No execution identity.** Per the accepted design checkpoint's
  Correction 2, `ExecutionResult` carries no path/filename/UID/source-URI
  field of any kind -- deferred until a real consumer establishes the
  required semantics and privacy boundary.
* **Two different scopes, not one symmetrical vocabulary.** `execute_one`
  owns parse -> policy -> conditional serialization and can produce
  `{SUCCEEDED, PARSE_FAILED, POLICY_REJECTED, POLICY_PARTIAL,
  SERIALIZATION_FAILED}`; `run` additionally owns source acquisition and
  conditional destination persistence, and can additionally produce
  `{SOURCE_FAILED, DESTINATION_FAILED}` -- stages `execute_one` does not
  own and is never forced to model (accepted design checkpoint Correction
  3). `run` always calls `execute_one` itself for the shared core, never a
  parallel reimplementation.
* **Unexpected-exception boundary: there isn't one.** This module adds no
  `except Exception` anywhere. `RollbackError` (an uncertain post-mutation
  state -- see `policy.RollbackError`) and any exception `policy.apply()`
  itself does not recognize propagate raw out of `execute_one`/`run`,
  exactly mirroring `policy.apply()`'s own frozen exception boundary one
  layer down. Neither is ever converted into an `ExecutionResult`, and no
  serialization or destination write can occur afterward -- there is no
  code path from `policy.apply()` raising back to those later steps.
* **Persistence gate.** A destination is written only when
  `PolicyResult.execution == PolicyExecutionStatus.COMPLETED` **and**
  `PolicyResult.decision` is one of the accepted/transformed success
  values (`Decision.ACCEPT`/`Decision.TRANSFORM`) -- both dimensions are
  checked explicitly (accepted design checkpoint Correction 1), not just
  one, even though today's frozen `policy.py` only ever produces them in
  lockstep.
"""

from __future__ import annotations

import dataclasses
import enum
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from fastdicomattrs import FdsError, read_buffer

from .policy import Decision, Policy, PolicyExecutionStatus, PolicyResult
from . import policy as _policy

if TYPE_CHECKING:
    from . import Structure

__all__ = [
    "ExecutionOutcome",
    "EXECUTION_DIAGNOSTIC_CODES",
    "ExecutionDiagnostic",
    "ExecutionResult",
    "SourceAcquisitionError",
    "DestinationWriteError",
    "execute_one",
    "run",
    "run_configured",
]


class ExecutionOutcome(str, enum.Enum):
    """The closed, S1.5-owned outcome vocabulary. A `str` subclass,
    matching `policy.Decision`/`policy.ExecutionStatus`'s own established
    convention. Deliberately **not** a single generic `FAILED` -- see the
    design checkpoint section 9/"Failure taxonomy" for why each value below
    is independently actionable by a future caller (CLI/container/service)
    without needing to inspect a message string.

    `execute_one` can produce `SUCCEEDED`/`PARSE_FAILED`/`POLICY_REJECTED`/
    `POLICY_PARTIAL`/`SERIALIZATION_FAILED`. `run` can additionally produce
    `SOURCE_FAILED`/`DESTINATION_FAILED` -- stages `execute_one` does not
    own (accepted design checkpoint Correction 3)."""

    SUCCEEDED = "succeeded"
    SOURCE_FAILED = "source_failed"
    PARSE_FAILED = "parse_failed"
    POLICY_REJECTED = "policy_rejected"
    POLICY_PARTIAL = "policy_partial"
    SERIALIZATION_FAILED = "serialization_failed"
    DESTINATION_FAILED = "destination_failed"


EXECUTION_DIAGNOSTIC_CODES = (
    "SOURCE_ACQUISITION_FAILED",
    "DICOM_PARSE_FAILED",
    "SERIALIZATION_FAILED",
    "DESTINATION_ALREADY_EXISTS",
    "DESTINATION_WRITE_FAILED",
    "DESTINATION_COMMIT_FAILED",
)
"""The stable, closed vocabulary of `ExecutionDiagnostic.code` values. A
deliberately separate vocabulary from `policy.DIAGNOSTIC_CODES` and from
`configuration.CONFIGURATION_ERROR_CODES` -- an execution diagnostic means
"something went wrong acquiring, parsing, serializing, or persisting this
one object," never "the Policy itself rejected or partially executed"
(that stays entirely in `PolicyResult.diagnostics`, never duplicated here)
and never "this document could not become a Policy at all" (that is
`ConfigurationError`, a different failure entirely)."""

_EXECUTION_DIAGNOSTIC_MESSAGES = {
    "SOURCE_ACQUISITION_FAILED": "the configured source could not be acquired",
    "DICOM_PARSE_FAILED": "the acquired bytes could not be parsed as DICOM",
    "SERIALIZATION_FAILED": "the transformed structure could not be serialized",
    "DESTINATION_ALREADY_EXISTS": "the destination target already exists and overwrite is not enabled",
    "DESTINATION_WRITE_FAILED": "the destination write could not be completed",
    "DESTINATION_COMMIT_FAILED": "the destination write completed but could not be published atomically",
}


@dataclass(frozen=True)
class ExecutionDiagnostic:
    """A small, PHI-safe operational diagnostic -- distinct from
    `policy.Diagnostic` (a policy-evaluation-time finding) and from
    `configuration.ConfigurationError` (a document-shape problem discovered
    before any Policy could exist). `code` is one of
    `EXECUTION_DIAGNOSTIC_CODES`; `message` is one of a small, fixed set of
    curated strings keyed by `code` -- never `str(exception)`, never an
    adapter's own exception text, never a filesystem path, filename, DICOM
    UID, DICOM value, raw DICOM bytes, or downstream response body.
    `cause_type` is the underlying exception's class name only (mirroring
    `policy.CallbackError.cause_type`'s established precedent) -- present
    only when a low-level detail is genuinely useful for debugging, never
    as the primary message."""

    code: str
    message: str
    cause_type: Optional[str] = None


def _diagnostic(code: str, cause_type: Optional[str] = None) -> ExecutionDiagnostic:
    return ExecutionDiagnostic(code=code, message=_EXECUTION_DIAGNOSTIC_MESSAGES[code],
                                cause_type=cause_type)


@dataclass(frozen=True)
class ExecutionResult:
    """The result of one `execute_one`/`run` call. Deliberately the
    smallest model that the qualified execution probes require -- no
    identity field (accepted design checkpoint Correction 2), no
    timestamps, no run ID, no path, no UID, no retry count, no cloud/host
    metadata. `policy_result` is populated whenever a `Policy` actually ran
    (i.e. for every outcome except `SOURCE_FAILED`/`PARSE_FAILED`, which
    occur strictly before a `Policy` could run at all) -- never re-derived
    or duplicated, the exact object `policy.apply()` returned.
    `output_bytes` is populated only for `SUCCEEDED` (the one outcome that
    reached serialization). `diagnostic` is populated for every outcome
    that has no `PolicyResult`-level diagnostic already covering it:
    `SOURCE_FAILED`, `PARSE_FAILED`, `SERIALIZATION_FAILED`,
    `DESTINATION_FAILED` -- never for `POLICY_REJECTED`/`POLICY_PARTIAL`,
    whose cause is already fully described by `policy_result.diagnostics`
    (S1.3, unchanged) and must not be duplicated here."""

    outcome: ExecutionOutcome
    policy_result: Optional[PolicyResult] = None
    output_bytes: Optional[bytes] = None
    diagnostic: Optional[ExecutionDiagnostic] = None


class SourceAcquisitionError(RuntimeError):
    """Raised by a source adapter's `acquire()` when it cannot obtain
    bytes (missing/unreadable file, and the equivalent for any future
    source kind). `run()` catches exactly this type to produce
    `ExecutionOutcome.SOURCE_FAILED` -- any other exception a source
    raises is a genuine, unmodeled bug and propagates raw, uncaught,
    exactly like every other unexpected exception in this module.
    `cause_type` is the original exception's class name only."""

    def __init__(self, cause: BaseException):
        self.cause_type = type(cause).__name__
        super().__init__(f"source acquisition failed ({self.cause_type})")


class DestinationWriteError(RuntimeError):
    """Raised by a destination adapter's `write()` when it cannot durably
    publish the given bytes. `category` is one of `EXECUTION_DIAGNOSTIC_CODES`'
    three destination-shaped codes (`DESTINATION_ALREADY_EXISTS`/
    `DESTINATION_WRITE_FAILED`/`DESTINATION_COMMIT_FAILED`), letting the
    adapter distinguish "could not write the content at all" from "wrote
    the content but could not publish it atomically" from "a target
    already exists and overwrite was not requested" without `run()` needing
    to inspect the underlying OS exception itself. `cause_type` is the
    original exception's class name only. Any exception a destination
    raises that is *not* this type is an unmodeled bug and propagates raw,
    uncaught."""

    def __init__(self, cause: BaseException, category: str = "DESTINATION_WRITE_FAILED"):
        assert category in EXECUTION_DIAGNOSTIC_CODES
        self.category = category
        self.cause_type = type(cause).__name__
        super().__init__(f"destination write failed ({category}: {self.cause_type})")


_PERSISTENCE_ELIGIBLE_DECISIONS = (Decision.ACCEPT, Decision.TRANSFORM)


def _is_persistence_eligible(policy_result: PolicyResult) -> bool:
    """The accepted design checkpoint's Correction 1: the positive
    persistence-eligibility condition is checked against **both** frozen
    dimensions explicitly -- `execution == COMPLETED` and `decision` is an
    accepted/transformed success value -- never relying on the fact that
    today's frozen `policy.py` only ever produces them in lockstep (a
    `COMPLETED`+`REJECT` pairing cannot occur in the current implementation,
    verified: `Decision.REJECT`/`Decision.PARTIAL` are only ever
    constructed together with `PolicyExecutionStatus.REJECTED`/`PARTIAL`
    respectively in `policy._build_policy_result`'s call sites -- but this
    function does not assume that invariant holds, by design)."""
    return (policy_result.execution == PolicyExecutionStatus.COMPLETED
            and policy_result.decision in _PERSISTENCE_ELIGIBLE_DECISIONS)


def execute_one(data: bytes, policy: Policy) -> ExecutionResult:
    """The deployment-neutral execution core. Owns exactly: parsing `data`
    into a `Structure` (attrs' `read_buffer`, `fidelity="lossless"`,
    matching every prior increment's own qualification convention) --
    treating both a raised `FdsError` and a successful parse that carries a
    blocking (non-"info") diagnostic as `ExecutionOutcome.PARSE_FAILED`,
    since attrs' `read_buffer` is lenient by design and reserves raising
    for catastrophic conditions only (see the implementation report,
    "known defects/fixed" for the evidence this was discovered against) --
    running `policy` against it (`policy.apply()`, completely unmodified),
    and -- only when the result is persistence-eligible (see
    `_is_persistence_eligible`) -- serializing the mutated `Structure`
    back to bytes (attrs' `write_bytes()`). Never touches a filesystem
    path, an adapter, a `Configuration`, or any logging/retry/rendering
    concern -- those belong to `run()` and to callers of this module.

    `RollbackError` and any exception `policy.apply()` itself does not
    recognize (see `policy.apply()`'s own docstring, "Exception boundary")
    propagate raw, uncaught, out of this function -- never converted into
    an `ExecutionResult`. No serialization can occur after such a failure,
    since there is no code path from a raised exception back to the
    serialization step below it.

    The `Structure` this function creates is always closed
    (`try`/`finally`) before returning or propagating, since `Structure`
    itself is not a context manager (verified: no `__enter__`/`__exit__` on
    the frozen attrs class) -- matching every existing test's own
    convention throughout S1.1-S1.4.
    """
    try:
        structure = read_buffer(data, fidelity="lossless")
    except FdsError as exc:
        return ExecutionResult(outcome=ExecutionOutcome.PARSE_FAILED,
                                diagnostic=_diagnostic("DICOM_PARSE_FAILED", cause_type=type(exc).__name__))

    try:
        # attrs' read_buffer is lenient by design -- FdsError is reserved
        # for catastrophic conditions (I/O, a wholly unsupported transfer
        # syntax); ordinary malformed/truncated content instead produces a
        # Structure whose own .diagnostics carry the finding, exactly the
        # convention python/examples/pipeline_demo.py and fastDICOMgateway's
        # transform.py already both rely on (never re-implemented here,
        # only reused). A blocking (non-"info") diagnostic at this point
        # means the input was not sound enough to run a Policy against, and
        # is reported identically to an outright raised FdsError.
        blocking = [d for d in structure.diagnostics if d.severity != "info"]
        if blocking:
            return ExecutionResult(outcome=ExecutionOutcome.PARSE_FAILED,
                                    diagnostic=_diagnostic("DICOM_PARSE_FAILED"))

        policy_result = _policy.apply(structure, policy)

        if not _is_persistence_eligible(policy_result):
            outcome = (ExecutionOutcome.POLICY_REJECTED
                       if policy_result.execution == PolicyExecutionStatus.REJECTED
                       else ExecutionOutcome.POLICY_PARTIAL)
            return ExecutionResult(outcome=outcome, policy_result=policy_result)

        try:
            output_bytes = structure.write_bytes()
        except FdsError as exc:
            return ExecutionResult(outcome=ExecutionOutcome.SERIALIZATION_FAILED,
                                    policy_result=policy_result,
                                    diagnostic=_diagnostic("SERIALIZATION_FAILED", cause_type=type(exc).__name__))

        return ExecutionResult(outcome=ExecutionOutcome.SUCCEEDED, policy_result=policy_result,
                                output_bytes=output_bytes)
    finally:
        structure.close()


def run(source, policy: Policy, destination=None) -> ExecutionResult:
    """The thin orchestration wrapper: `source.acquire()` -> the identical
    `execute_one()` core -> conditional `destination.write(...)`. Adds
    exactly two responsibilities `execute_one` does not own -- source
    acquisition and destination persistence -- and duplicates neither
    parsing, policy application, nor serialization (those remain
    `execute_one`'s alone; this function always calls `execute_one`
    itself for that step, never a parallel reimplementation -- the direct,
    executable form of the accepted design checkpoint's Correction 3).

    `destination` is invoked if and only if `execute_one` returned
    `ExecutionOutcome.SUCCEEDED` (which already encodes the full
    persistence gate via `_is_persistence_eligible`) -- never for
    `POLICY_REJECTED`/`POLICY_PARTIAL`/`PARSE_FAILED`. A `destination` of
    `None` means "no normal destination configured" (matching `execute_one`'s
    own bare-Python-caller use case, section "Probe H" of the design
    checkpoint) and is not itself a failure.

    A source that raises `SourceAcquisitionError` produces
    `ExecutionOutcome.SOURCE_FAILED` (no `Structure` was ever created, so
    `policy_result` is `None`). A destination that raises
    `DestinationWriteError` after a successful `execute_one()` call
    produces `ExecutionOutcome.DESTINATION_FAILED` -- the *original*
    successful `policy_result`/`output_bytes` are preserved unchanged (via
    `dataclasses.replace`, reusing exactly what `execute_one` already
    produced rather than reconstructing it), only `outcome`/`diagnostic`
    change. Any other exception from either adapter call is an unmodeled
    bug and propagates raw, uncaught -- this function adds no
    `except Exception` anywhere.
    """
    try:
        data = source.acquire()
    except SourceAcquisitionError as exc:
        return ExecutionResult(outcome=ExecutionOutcome.SOURCE_FAILED,
                                diagnostic=_diagnostic("SOURCE_ACQUISITION_FAILED", cause_type=exc.cause_type))

    result = execute_one(data, policy)

    if destination is None or result.outcome is not ExecutionOutcome.SUCCEEDED:
        return result

    try:
        destination.write(result.output_bytes)
    except DestinationWriteError as exc:
        return dataclasses.replace(result, outcome=ExecutionOutcome.DESTINATION_FAILED,
                                    diagnostic=_diagnostic(exc.category, cause_type=exc.cause_type))

    return result


def run_configured(config) -> ExecutionResult:
    """S1.6 addition -- pure composition, no new execution semantics. Given
    a loaded `configuration.Configuration`, resolves the source adapter,
    conditionally resolves the destination adapter, performs the existing
    source/destination collision check whenever a destination is present
    (strictly before any acquisition can occur), and delegates to `run()`
    unchanged. This is exactly the sequence the S1.5 design checkpoint's
    own "preferred use" example already specified
    (`resolve_source`/`resolve_destination`/`check_source_destination_collision`/
    `run`) -- getting the conditional-destination and collision-check-
    ordering right is easy to subtly drift on a second, independent
    implementation, so it is centralized here once a second real consumer
    (S1.6's CLI) exists to justify it, per the design checkpoint's own
    anticipation of this exact function.

    Requires `config.source is not None` -- a caller precondition, exactly
    like `run()` itself requiring a non-`None` `source` argument; this
    function does not defensively re-validate it (an `AttributeError` from
    `resolve_source` on a `None` envelope is the caller's problem to avoid,
    not this function's to catch and re-wrap).

    Uses a deferred (local, in-function) import of `adapters` rather than
    a module-level one: `adapters/filesystem.py` already imports this
    module (`execution.py`) for `SourceAcquisitionError`/
    `DestinationWriteError`, so a module-level `import adapters` here would
    create a real load-time cycle (`execution -> adapters ->
    adapters.filesystem -> execution`). Deferring the import to call time
    sidesteps any load-order fragility entirely, since by the time anyone
    actually calls this function the whole package has already finished
    importing -- see docs/architecture/
    S1_6_THIN_CLI_DESIGN_CHECKPOINT.md section 9 for the full analysis.
    """
    from . import adapters as _adapters

    source = _adapters.resolve_source(config.source)
    destination = (_adapters.resolve_destination(config.destination)
                   if config.destination is not None else None)
    if destination is not None:
        _adapters.check_source_destination_collision(source, destination)
    return run(source, config.policy, destination)
