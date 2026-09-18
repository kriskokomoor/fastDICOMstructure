"""S1.5 -- Adapter resolution: a closed, deterministic registry from a
Configuration V1 envelope's `type` string to a concrete adapter class, plus
the small, curated error raised when resolution itself cannot proceed.

I/O only, by design (see the package's own module boundary in
docs/architecture/S1_5_EXECUTION_ARCHITECTURE_DESIGN_CHECKPOINT.md,
"Ownership boundaries"): nothing under this package parses or serializes
DICOM, inspects a `Structure`/`Policy`/`PolicyResult`, or implements a
policy decision.

Deliberately **not** a plugin/discovery system: no entry points, no dynamic
import, no class name taken from JSON, no `eval`, no filesystem scanning.
`SOURCE_ADAPTERS`/`DESTINATION_ADAPTERS` are plain, closed `dict`s -- adding
a future adapter (C-STORE, DICOMweb, database) means adding a dict entry in
this file, never accepting one from a Configuration document itself. This
mirrors Configuration V1's own closed/fail-closed philosophy (S1.4) one
layer up, deliberately.
"""

from __future__ import annotations

from typing import Mapping

__all__ = [
    "ADAPTER_RESOLUTION_ERROR_CODES",
    "AdapterResolutionError",
    "SOURCE_ADAPTERS",
    "DESTINATION_ADAPTERS",
    "resolve_source",
    "resolve_destination",
    "check_source_destination_collision",
]

ADAPTER_RESOLUTION_ERROR_CODES = (
    "ADAPTER_TYPE_UNKNOWN",
    "ADAPTER_OPTIONS_INVALID",
    "SOURCE_DESTINATION_COLLISION",
)
"""The stable, closed vocabulary of `AdapterResolutionError.code` values.
Occurs once per Configuration, strictly before any object is acquired --
never an `execution.ExecutionResult` (a per-object outcome). Distinct from
both `configuration.ConfigurationError` (a document-shape problem
`configuration.py` itself can detect, with no notion of which adapters
this deployment actually supports) and `execution.ExecutionOutcome` (a
per-object operational outcome)."""

_ADAPTER_RESOLUTION_ERROR_MESSAGES = {
    "ADAPTER_TYPE_UNKNOWN": "this deployment has no adapter registered for the given envelope type",
    "ADAPTER_OPTIONS_INVALID": "the adapter-specific options for this envelope are invalid",
    "SOURCE_DESTINATION_COLLISION": "the source and destination envelopes resolve to the same location",
}


class AdapterResolutionError(ValueError):
    """Raised when a Configuration V1 envelope cannot be turned into a
    usable adapter -- an unknown `type`, invalid adapter-specific
    `options`, or (for two filesystem-shaped adapters specifically) a
    source/destination collision detected before any object is acquired.
    `code` is one of `ADAPTER_RESOLUTION_ERROR_CODES`; `message` is one of
    a small, fixed, curated set keyed by `code` -- never echoes the
    envelope's own `type` string or any `options` value, matching
    `configuration.ConfigurationError`'s own established discipline."""

    def __init__(self, code: str):
        assert code in ADAPTER_RESOLUTION_ERROR_CODES, f"unknown AdapterResolutionError code: {code!r}"
        self.code = code
        self.message = _ADAPTER_RESOLUTION_ERROR_MESSAGES[code]
        super().__init__(f"{code}: {self.message}")


from .filesystem import FilesystemDestination, FilesystemSource  # noqa: E402

SOURCE_ADAPTERS: Mapping[str, type] = {
    "filesystem": FilesystemSource,
}
DESTINATION_ADAPTERS: Mapping[str, type] = {
    "filesystem": FilesystemDestination,
}


def resolve_source(envelope, registry: Mapping[str, type] = SOURCE_ADAPTERS):
    """Resolves a Configuration V1 `source` envelope (`configuration.Envelope`)
    into a constructed source adapter, using the closed `registry`.
    Raises `AdapterResolutionError("ADAPTER_TYPE_UNKNOWN")` for an
    unregistered `envelope.type`; the constructed adapter's own
    `__init__` is responsible for raising
    `AdapterResolutionError("ADAPTER_OPTIONS_INVALID")` for invalid
    `envelope.options`. `registry` is an explicit, overridable parameter
    (small, direct dependency injection) so tests can substitute a
    different registry without global state."""
    factory = registry.get(envelope.type)
    if factory is None:
        raise AdapterResolutionError("ADAPTER_TYPE_UNKNOWN")
    return factory(envelope.options)


def resolve_destination(envelope, registry: Mapping[str, type] = DESTINATION_ADAPTERS):
    """Destination-side counterpart to `resolve_source` -- identical
    contract."""
    factory = registry.get(envelope.type)
    if factory is None:
        raise AdapterResolutionError("ADAPTER_TYPE_UNKNOWN")
    return factory(envelope.options)


def check_source_destination_collision(source, destination) -> None:
    """Raises `AdapterResolutionError("SOURCE_DESTINATION_COLLISION")` if
    both `source` and `destination` are filesystem adapters resolved to
    the same real filesystem path -- checked once, before any object is
    acquired, since it is a Configuration-shape problem discoverable
    independently of any particular object (design checkpoint section 12).
    A no-op for every other adapter combination: collision detection is
    only attempted when it can be determined safely (both concrete
    filesystem types known), never guessed at for adapters this module
    cannot introspect. A caller that resolves both a source and a
    destination is expected to call this once, after both are resolved and
    before calling `execution.run()`."""
    if isinstance(source, FilesystemSource) and isinstance(destination, FilesystemDestination):
        if source._resolved_path == destination._resolved_path:
            raise AdapterResolutionError("SOURCE_DESTINATION_COLLISION")
