"""S1.6 -- Thin CLI Consumer.

A real, subprocess-invokable command that composes only what S1.1-S1.5
already built: `configuration.load_configuration_json` ->
`execution.run_configured` (adapter resolution, the source/destination
collision check, and `execution.run`) -> a curated rendering of the
resulting `ExecutionResult` -> a process exit code. See
docs/architecture/S1_6_THIN_CLI_DESIGN_CHECKPOINT.md for the full design
rationale and docs/architecture/S1_6_THIN_CLI_IMPLEMENTATION_REPORT.md for
qualification evidence; this module's own docstrings cover only what an
invoker needs to know.

Ownership boundary, stated up front:

* **This module owns exactly**: argument parsing, composing the existing
  `load_configuration_json`/`run_configured` calls, rendering, and process
  exit status. It never imports `fastdicomattrs`, never constructs a
  `Policy`, never calls an adapter's `acquire()`/`write()` itself, and
  never reimplements any part of `execution.run()`/`run_configured()`.
* **Configuration V1 remains the sole execution-configuration surface.**
  This module accepts exactly two flags (`--config`, `--json`); neither
  ever encodes execution semantics (no source/destination/mutation/
  overwrite/batch/retry/network flag exists here or is planned).
* **No new exception boundary.** `ConfigurationError`/`AdapterResolutionError`
  are the only exceptions this module catches -- both are pre-execution,
  document-shape/environment problems, not per-object outcomes.
  `RollbackError` and any exception `execute_one`/`run` do not already
  recognize are **not** caught here either -- they propagate out of
  `main()` uncaught, exactly mirroring `policy.apply()`'s and
  `execution.run()`'s own established "no blanket catch" discipline one
  layer up. Converting an unmodeled/uncertain-state failure into an
  apparently ordinary exit code would misrepresent it -- Python's own
  default unhandled-exception behavior (traceback to stderr, exit 1) is
  the correct, honest signal for this category, not a special case to
  paper over.
* **Rendering never exposes `ExecutionResult.output_bytes`.** No rendering
  path in this module ever references it, truncated or otherwise -- binary
  DICOM bytes are never written to a terminal.
* **Rendering never falls back to `str()`/`repr()` of an exception, a
  `Configuration`, or an `ExecutionResult`.** Every field placed in either
  rendering is a specific, already-privacy-qualified attribute (a `code`,
  an `.value` of a closed enum, a curated `message`) -- never a bare
  object dump.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from . import adapters, configuration
from . import execution
from .policy import PolicyResult

__all__ = ["build_parser", "main"]

_EXIT_SUCCESS = 0
_EXIT_USAGE = 2
_EXIT_CONFIGURATION_ERROR = 10
_EXIT_ADAPTER_RESOLUTION_ERROR = 11
_EXECUTION_OUTCOME_EXIT_CODES = {
    execution.ExecutionOutcome.SUCCEEDED: _EXIT_SUCCESS,
    execution.ExecutionOutcome.SOURCE_FAILED: 12,
    execution.ExecutionOutcome.PARSE_FAILED: 13,
    execution.ExecutionOutcome.POLICY_REJECTED: 14,
    execution.ExecutionOutcome.POLICY_PARTIAL: 15,
    execution.ExecutionOutcome.SERIALIZATION_FAILED: 16,
    execution.ExecutionOutcome.DESTINATION_FAILED: 17,
}
"""The one-to-one mapping from the closed `ExecutionOutcome` vocabulary to
process exit codes -- see docs/architecture/
S1_6_THIN_CLI_DESIGN_CHECKPOINT.md section 12 for why each is kept
distinct (no generic collapsed "failure" code) and why 1 is reserved,
never assigned by this module."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fastdicomstructure")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="Execute one DICOM object's configured Policy via Configuration V1")
    run_parser.add_argument("--config", required=True,
                             help="Path to a Configuration V1 JSON document")
    run_parser.add_argument("--json", action="store_true", dest="as_json",
                             help="Render the result as a single curated JSON object on stdout")
    return parser


def _tag_token(tag) -> str:
    group, element = tag
    return f"({group:04X},{element:04X})"


def _enum_value(value) -> Optional[str]:
    return value.value if value is not None else None


def _render_operation(op) -> dict:
    return {
        "kind": op.kind,
        "tag": _tag_token(op.tag) if op.tag is not None else None,
        "execution": _enum_value(op.execution),
        "satisfied": op.satisfied,
        "count": op.count,
        "updated_count": op.updated_count,
        "inserted_count": op.inserted_count,
        "diagnostics": [_render_policy_diagnostic(d) for d in op.diagnostics],
    }


def _render_policy_diagnostic(d) -> dict:
    return {
        "code": d.code,
        "severity": d.severity,
        "operation_kind": d.operation_kind,
        "operation_index": d.operation_index,
        "locator": d.locator,
        "site": d.site,
        "message": d.message,
        "cause_type": d.cause_type,
    }


def _render_policy_result(result: PolicyResult) -> dict:
    return {
        "name": result.policy_name,
        "version": result.policy_version,
        "decision": _enum_value(result.decision),
        "execution": _enum_value(result.execution),
        "operations": [_render_operation(op) for op in result.operations],
        "diagnostics": [_render_policy_diagnostic(d) for d in result.diagnostics],
    }


def _render_execution_diagnostic(d) -> dict:
    return {"code": d.code, "message": d.message, "cause_type": d.cause_type}


def render_json(status: str, result: Optional[execution.ExecutionResult]) -> dict:
    """Builds the single curated JSON object this CLI ever emits on
    stdout. `status` is deliberately drawn from the same closed vocabulary
    as the process exit code (see `_EXECUTION_OUTCOME_EXIT_CODES` and the
    two pre-execution string constants below) -- one designed property,
    not two independently-invented vocabularies. `result` is `None` for a
    pre-execution failure (`ConfigurationError`/`AdapterResolutionError`),
    in which case `"policy"`/`"diagnostic"` are simply absent.
    `output_bytes` never appears here."""
    doc: dict[str, Any] = {"status": status}
    if result is not None:
        doc["policy"] = _render_policy_result(result.policy_result) if result.policy_result else None
        doc["diagnostic"] = _render_execution_diagnostic(result.diagnostic) if result.diagnostic else None
    return doc


def render_text(status: str, result: Optional[execution.ExecutionResult]) -> str:
    """The human-readable default rendering -- a short, information-dense
    summary in the same plain register the rest of this codebase already
    uses. Never includes a source/destination path (an operator who wants
    path confirmation already knows it -- they wrote it into the
    Configuration document) and never references `output_bytes`."""
    lines = [f"fastdicomstructure: {status.upper()}"]
    if result is not None and result.policy_result is not None:
        pr = result.policy_result
        lines.append(f"policy: {pr.policy_name} v{pr.policy_version} -- "
                      f"decision={_enum_value(pr.decision)}, execution={_enum_value(pr.execution)}")
        for op in pr.operations:
            satisfied = "" if op.satisfied is None else f"satisfied={op.satisfied}   "
            lines.append(f"  {op.kind:<14} {_enum_value(op.execution):<12} {satisfied}count={op.count}")
        for d in pr.diagnostics:
            lines.append(f"  diagnostic: {d.code} -- {d.message}")
    if result is not None and result.diagnostic is not None:
        d = result.diagnostic
        cause = f" ({d.cause_type})" if d.cause_type else ""
        lines.append(f"diagnostic: {d.code}{cause} -- {d.message}")
    return "\n".join(lines)


def _print(text_or_doc, as_json: bool) -> None:
    if as_json:
        print(json.dumps(text_or_doc, indent=2))
    else:
        print(text_or_doc)


def _run_command(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    try:
        text = config_path.read_text()
    except OSError:
        # Correction 2 (S1.6 review): the CLI's own --config argument is
        # the one, narrow, deliberate exception to "never echo a path" --
        # this is an operator-supplied CLI argument, not a configured
        # source/destination path, a DICOM-derived value, or an exception
        # string. See docs/architecture/S1_6_THIN_CLI_DESIGN_CHECKPOINT.md
        # section 14.
        print(f"fastdicomstructure: cannot read configuration file: {args.config}", file=sys.stderr)
        return _EXIT_USAGE

    try:
        config = configuration.load_configuration_json(text)
    except configuration.ConfigurationError as exc:
        doc_or_text = (render_json("configuration_error", None) if args.as_json
                       else f"fastdicomstructure: CONFIGURATION_ERROR -- {exc.code}: {exc.message}")
        if args.as_json:
            doc_or_text["code"] = exc.code
            doc_or_text["message"] = exc.message
        _print(doc_or_text, args.as_json)
        return _EXIT_CONFIGURATION_ERROR

    if config.source is None:
        # A CLI-level precondition, not a modeled Configuration/execution
        # failure: a Configuration document valid under S1.4 may still
        # lack a source, but `run`/`run_configured` require one.
        print("fastdicomstructure: the configuration has no \"source\" -- "
              "\"run\" requires one", file=sys.stderr)
        return _EXIT_USAGE

    try:
        result = execution.run_configured(config)
    except adapters.AdapterResolutionError as exc:
        doc_or_text = (render_json("adapter_resolution_error", None) if args.as_json
                       else f"fastdicomstructure: ADAPTER_RESOLUTION_ERROR -- {exc.code}: {exc.message}")
        if args.as_json:
            doc_or_text["code"] = exc.code
            doc_or_text["message"] = exc.message
        _print(doc_or_text, args.as_json)
        return _EXIT_ADAPTER_RESOLUTION_ERROR

    status = result.outcome.value
    _print(render_json(status, result) if args.as_json else render_text(status, result), args.as_json)
    return _EXECUTION_OUTCOME_EXIT_CODES[result.outcome]


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return _run_command(args)
    parser.error(f"unknown command: {args.command}")  # unreachable -- argparse itself rejects this
    return _EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
