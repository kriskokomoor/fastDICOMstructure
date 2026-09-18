"""S1.4 -- Single Declarative JSON Configuration.

A small, versioned, human-authorable JSON representation of a subset of the
`policy` module's frozen operation vocabulary: `Require`, `Remove`,
`ReplaceText`, `EnsureText`, `AllowListPrune`, `PrivateTagPolicy`. Raw-byte
`Replace`/`Ensure` and callback-based `Replace`/`ReplaceText` are
deliberately **not** representable here -- they remain Python/programmatic-
only. See docs/architecture/S1_4_JSON_CONFIGURATION_DESIGN_CHECKPOINT.md for
the full design rationale and docs/architecture/
S1_4_JSON_CONFIGURATION_IMPLEMENTATION_REPORT.md for qualification evidence;
this module's own docstrings cover only what a caller needs to know.

Design choices, stated up front:

* **Fully closed, fail-closed.** Every field in a Configuration V1 document
  must be understood by this module or the document is rejected. There is no
  extension namespace (a proposed `"x-"` escape hatch was considered and
  explicitly rejected -- see the design checkpoint's corrections).
* **The `schema` field is a stable identifier, not a URI.** It never
  changes; a future formal JSON Schema document, if published, would be
  referenced through a separate field under separate review.
* **No executable content, anywhere.** No field shape in this contract can
  hold a callback reference, an expression, a template, or a code string.
  Every accepted document is pure data.
* **Configuration construction is not policy execution.** A document that
  fails validation raises `ConfigurationError` before a `Policy` object ever
  exists; it is never converted into a `PolicyResult`/`Diagnostic` (the
  runtime model `apply()` produces once a `Policy` actually executes).
* **Curated, fixed error messages.** `ConfigurationError.message` is one of
  a small closed set of static strings, keyed by `code` -- never
  interpolated from the offending value. `path` records *where* the problem
  is structurally, never *what* the value was. This mirrors `Diagnostic`'s
  own privacy discipline in `policy.py`.
* **No result serialization here.** This module's only executable surface
  is: JSON -> validated `Configuration` -> frozen `Policy`/`Locator` objects,
  ready for the existing, unchanged `policy.apply()`. It does not serialize
  `PolicyResult`/`OperationResult`/`Diagnostic` -- that remains out of scope
  until a real consumer exists (S1.4 design checkpoint, Correction 3).
"""

from __future__ import annotations

import json
import re
import types
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .policy import (
    AllowListPrune,
    EnsureText,
    ITEM_WILDCARD,
    Locator,
    LocatorStep,
    PathLocator,
    Policy,
    PolicyOperation,
    PrivateTagPolicy,
    Remove,
    ReplaceText,
    Require,
    Tag,
    TagLocator,
)

__all__ = [
    "SCHEMA_IDENTIFIER",
    "SCHEMA_VERSION",
    "CONFIGURATION_ERROR_CODES",
    "ConfigurationError",
    "Envelope",
    "Configuration",
    "load_configuration",
    "load_configuration_json",
    "to_canonical_data",
    "to_canonical_json",
]

SCHEMA_IDENTIFIER = "fastdicomstructure-configuration"
"""The stable, permanent Configuration V1 schema identifier. Never replaced
by a URI or any other spelling -- see the design checkpoint's Correction 2."""

SCHEMA_VERSION = 1
"""The only `schema_version` this implementation accepts. Major-version-only
by design (see the design checkpoint section 10)."""


# ---------------------------------------------------------------------------
# ConfigurationError -- distinct from policy.py's runtime Diagnostic model
# ---------------------------------------------------------------------------

CONFIGURATION_ERROR_CODES = (
    "MALFORMED_JSON",
    "SCHEMA_MISMATCH",
    "SCHEMA_VERSION_UNSUPPORTED",
    "MISSING_REQUIRED_FIELD",
    "UNKNOWN_FIELD",
    "UNKNOWN_OPERATION",
    "INVALID_OPERATION_PLACEMENT",
    "LOCATOR_INVALID",
    "TAG_INVALID",
    "VR_TOKEN_INVALID",
    "VALUE_INVALID",
    "ENVELOPE_INVALID",
)
"""The stable, closed vocabulary of `ConfigurationError.code` values. This is
a deliberately separate vocabulary from `policy.DIAGNOSTIC_CODES` -- a
Configuration error means "this document could not be turned into a Policy
at all," never "a Policy ran and something happened." `LOCATOR_INVALID` is
the declarative-layer counterpart of `policy.MalformedLocatorError`, and is
the resolution of the code `policy.DIAGNOSTIC_CODES` reserved but never
produces (see policy.py's own docstring on that reservation)."""

_CONFIGURATION_ERROR_MESSAGES: Mapping[str, str] = {
    "MALFORMED_JSON": "the configuration text is not well-formed JSON",
    "SCHEMA_MISMATCH": "the \"schema\" field does not match the Configuration V1 schema identifier",
    "SCHEMA_VERSION_UNSUPPORTED": "the \"schema_version\" field is not a version this implementation supports",
    "MISSING_REQUIRED_FIELD": "a required field is missing at this location",
    "UNKNOWN_FIELD": "an unrecognized field is present at this location -- Configuration V1 is fully closed",
    "UNKNOWN_OPERATION": "this operation kind is not part of the Configuration V1 declarative vocabulary",
    "INVALID_OPERATION_PLACEMENT": "this operation kind is not permitted in this section of the policy",
    "LOCATOR_INVALID": "the locator at this location has an invalid shape",
    "TAG_INVALID": "the tag token at this location is not a valid canonical \"(GGGG,EEEE)\" spelling",
    "VR_TOKEN_INVALID": "the VR token at this location is not a recognized, authorable standard VR",
    "VALUE_INVALID": "the value at this location is not of the expected type or shape",
    "ENVELOPE_INVALID": "the source/destination envelope at this location is invalid",
}


class ConfigurationError(ValueError):
    """Raised when a JSON document cannot be turned into a `Configuration`.
    Distinct from `policy.py`'s runtime `Diagnostic`/`PolicyResult` model:
    a `ConfigurationError` always occurs strictly *before* any `Policy`
    object exists, never as a result of executing one.

    `code` is one of `CONFIGURATION_ERROR_CODES`. `path` is a curated,
    dotted/indexed structural location within the document (e.g.
    `"policy.mutation[2].target.scope"`, `""` for the document root) --
    never the offending value itself. `message` is one of a small, fixed
    set of strings keyed by `code`, exactly like `policy.Diagnostic`'s own
    `message` field -- never interpolated from user-supplied content, so no
    configuration value (sensitive or otherwise) can ever reach it.

    Only the *first* problem encountered is reported (fail-fast, not an
    aggregate of every defect in the document) -- deterministic and simple,
    matching `MalformedLocatorError`'s own precedent of raising immediately
    at the first invalid construction it detects.
    """

    def __init__(self, code: str, path: str):
        assert code in CONFIGURATION_ERROR_CODES, f"unknown ConfigurationError code: {code!r}"
        self.code = code
        self.path = path
        self.message = _CONFIGURATION_ERROR_MESSAGES[code]
        super().__init__(f"{code} at {path!r}: {self.message}")


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _index(path: str, i: int) -> str:
    return f"{path}[{i}]"


def _check_fields(obj: Any, required: set, optional: set, path: str) -> None:
    """The one field-closure check every object-shaped level of a
    Configuration V1 document goes through: unknown fields are rejected
    unconditionally (no extension namespace -- design checkpoint Correction
    1), then required fields are confirmed present. Deterministic: the
    lexicographically-first offending field name is reported when more than
    one problem exists."""
    if not isinstance(obj, dict):
        raise ConfigurationError("VALUE_INVALID", path)
    present = set(obj.keys())
    unknown = sorted(present - (required | optional))
    if unknown:
        raise ConfigurationError("UNKNOWN_FIELD", _join(path, unknown[0]))
    missing = sorted(required - present)
    if missing:
        raise ConfigurationError("MISSING_REQUIRED_FIELD", _join(path, missing[0]))


# ---------------------------------------------------------------------------
# Tag / locator decoding
# ---------------------------------------------------------------------------

_TAG_TOKEN_RE = re.compile(r"^\(([0-9A-F]{4}),([0-9A-F]{4})\)$")
"""Canonical tag spelling only -- exactly four uppercase hex digits per
group, parenthesized, comma-separated. Lowercase, unpadded, and alternative
spellings are rejected, never normalized (design checkpoint section 5)."""


def _parse_tag(token: Any, path: str) -> Tag:
    if not isinstance(token, str) or not _TAG_TOKEN_RE.match(token):
        raise ConfigurationError("TAG_INVALID", path)
    m = _TAG_TOKEN_RE.match(token)
    return (int(m.group(1), 16), int(m.group(2), 16))


_TAG_LOCATOR_FIELDS = {"tag", "scope"}
_PATH_LOCATOR_FIELDS = {"tag", "path"}
_PATH_STEP_FIELDS = {"tag", "item"}


def _parse_path_steps(value: Any, path: str) -> list:
    if not isinstance(value, list):
        raise ConfigurationError("LOCATOR_INVALID", path)
    steps = []
    for i, step_obj in enumerate(value):
        step_path = _index(path, i)
        if not isinstance(step_obj, dict):
            raise ConfigurationError("LOCATOR_INVALID", step_path)
        unknown = sorted(set(step_obj.keys()) - _PATH_STEP_FIELDS)
        if unknown:
            raise ConfigurationError("UNKNOWN_FIELD", _join(step_path, unknown[0]))
        if "tag" not in step_obj:
            raise ConfigurationError("MISSING_REQUIRED_FIELD", _join(step_path, "tag"))
        if "item" not in step_obj:
            raise ConfigurationError("MISSING_REQUIRED_FIELD", _join(step_path, "item"))
        tag = _parse_tag(step_obj["tag"], _join(step_path, "tag"))
        item = step_obj["item"]
        is_valid_index = isinstance(item, int) and not isinstance(item, bool) and item >= 0
        if item != ITEM_WILDCARD and not is_valid_index:
            raise ConfigurationError("LOCATOR_INVALID", _join(step_path, "item"))
        steps.append(LocatorStep(tag=tag, item=item))
    return steps


def _parse_locator(obj: Any, path: str) -> Locator:
    """Decodes one locator (a `target` field, or an `AllowListPrune` tag
    entry's own containing shape) into a `TagLocator`/`PathLocator`.
    Discrimination is structural: a `"path"` key means `PathLocator`; its
    absence means `TagLocator`, which then requires `"scope"` explicitly --
    no per-operation Python default is ever silently applied to
    JSON-authored locators (design checkpoint Correction 1's sibling
    concern, addressed here directly)."""
    if not isinstance(obj, dict):
        raise ConfigurationError("LOCATOR_INVALID", path)
    has_path = "path" in obj
    has_scope = "scope" in obj
    if has_path and has_scope:
        raise ConfigurationError("LOCATOR_INVALID", path)

    if has_path:
        unknown = sorted(set(obj.keys()) - _PATH_LOCATOR_FIELDS)
        if unknown:
            raise ConfigurationError("UNKNOWN_FIELD", _join(path, unknown[0]))
        if "tag" not in obj:
            raise ConfigurationError("MISSING_REQUIRED_FIELD", _join(path, "tag"))
        leaf_tag = _parse_tag(obj["tag"], _join(path, "tag"))
        steps = _parse_path_steps(obj["path"], _join(path, "path"))
        return PathLocator(steps=tuple(steps), tag=leaf_tag)

    unknown = sorted(set(obj.keys()) - _TAG_LOCATOR_FIELDS)
    if unknown:
        raise ConfigurationError("UNKNOWN_FIELD", _join(path, unknown[0]))
    if "tag" not in obj:
        raise ConfigurationError("MISSING_REQUIRED_FIELD", _join(path, "tag"))
    if "scope" not in obj:
        raise ConfigurationError("MISSING_REQUIRED_FIELD", _join(path, "scope"))
    tag = _parse_tag(obj["tag"], _join(path, "tag"))
    scope = obj["scope"]
    if scope not in ("root", "recursive"):
        raise ConfigurationError("LOCATOR_INVALID", _join(path, "scope"))
    return TagLocator(tag=tag, recursive=(scope == "recursive"))


# ---------------------------------------------------------------------------
# Value / VR decoding
# ---------------------------------------------------------------------------

def _parse_text_value(value: Any, path: str):
    """`replace_text`/`ensure_text` values: a plain string, or an array of
    plain strings. Rejects mixed arrays, nested arrays, null, objects, and
    numbers -- deliberately: Configuration V1 is text-oriented for mutation,
    and never infers that a JSON number should become a numeric DICOM VR
    (design checkpoint section 6a)."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, str):
                raise ConfigurationError("VALUE_INVALID", path)
        return value
    raise ConfigurationError("VALUE_INVALID", path)


_KNOWN_VR_TOKENS = frozenset({
    "AE", "AS", "AT", "CS", "DA", "DS", "DT", "FL", "FD", "IS", "LO", "LT", "OB", "OD", "OF",
    "OL", "OV", "OW", "PN", "SH", "SL", "SQ", "SS", "ST", "SV", "TM", "UC", "UI", "UL", "UN",
    "UR", "US", "UT", "UV",
})
"""The closed set of standard two-letter VR spellings a Configuration V1
document may *author* explicitly -- attrs' internal `"UNKNOWN"` inference
sentinel is deliberately excluded (never a valid thing to author; omitting
`"vr"` is how a document requests inference, exactly like Python `vr=None`).
This is a syntax check only (closed PS3.5 enum), never the tag dictionary --
see the design checkpoint section 8 for why the line is drawn here."""


def _parse_vr(obj: Mapping[str, Any], path: str) -> Optional[str]:
    if "vr" not in obj:
        return None
    vr = obj["vr"]
    if not isinstance(vr, str) or vr not in _KNOWN_VR_TOKENS:
        raise ConfigurationError("VR_TOKEN_INVALID", _join(path, "vr"))
    return vr


# ---------------------------------------------------------------------------
# Operation decoding -- the closed V1 declarative vocabulary
# ---------------------------------------------------------------------------

_ACCEPTANCE_OPS = frozenset({"require"})
_MUTATION_OPS = frozenset({"remove", "replace_text", "ensure_text", "allow_list_prune", "private_tag_policy"})
_ALL_KNOWN_OPS = _ACCEPTANCE_OPS | _MUTATION_OPS
"""Configuration V1's entire declarative operation vocabulary -- exactly six
kinds. Raw `"replace"`/`"ensure"` (bytes-valued) and any callback-shaped
operation are not members of this set at all, so an attempt to author them
fails closed as `UNKNOWN_OPERATION` with no special-casing required (design
checkpoint section 6a/7)."""


def _parse_require(obj: Mapping[str, Any], path: str) -> Require:
    _check_fields(obj, {"op", "target"}, set(), path)
    target = _parse_locator(obj["target"], _join(path, "target"))
    return Require(target)


def _parse_remove(obj: Mapping[str, Any], path: str) -> Remove:
    _check_fields(obj, {"op", "target"}, set(), path)
    target = _parse_locator(obj["target"], _join(path, "target"))
    return Remove(target)


def _parse_replace_text(obj: Mapping[str, Any], path: str) -> ReplaceText:
    _check_fields(obj, {"op", "target", "value"}, set(), path)
    target = _parse_locator(obj["target"], _join(path, "target"))
    value = _parse_text_value(obj["value"], _join(path, "value"))
    return ReplaceText(target, value)


def _parse_ensure_text(obj: Mapping[str, Any], path: str) -> EnsureText:
    _check_fields(obj, {"op", "target", "value"}, {"vr"}, path)
    target = _parse_locator(obj["target"], _join(path, "target"))
    value = _parse_text_value(obj["value"], _join(path, "value"))
    vr = _parse_vr(obj, path)
    return EnsureText(target, value, vr=vr)


def _parse_allow_list_prune(obj: Mapping[str, Any], path: str) -> AllowListPrune:
    _check_fields(obj, {"op", "tags"}, set(), path)
    tags_value = obj["tags"]
    tags_path = _join(path, "tags")
    if not isinstance(tags_value, list):
        raise ConfigurationError("VALUE_INVALID", tags_path)
    tags = tuple(_parse_tag(t, _index(tags_path, i)) for i, t in enumerate(tags_value))
    return AllowListPrune(tags)


def _parse_private_tag_policy(obj: Mapping[str, Any], path: str) -> PrivateTagPolicy:
    _check_fields(obj, {"op"}, {"remove"}, path)
    remove = obj.get("remove", True)
    if not isinstance(remove, bool):
        raise ConfigurationError("VALUE_INVALID", _join(path, "remove"))
    return PrivateTagPolicy(remove=remove)


_MUTATION_PARSERS = {
    "remove": _parse_remove,
    "replace_text": _parse_replace_text,
    "ensure_text": _parse_ensure_text,
    "allow_list_prune": _parse_allow_list_prune,
    "private_tag_policy": _parse_private_tag_policy,
}
_ACCEPTANCE_PARSERS = {"require": _parse_require}


def _parse_operation(obj: Any, path: str, allowed_ops: frozenset, parsers: dict) -> PolicyOperation:
    if not isinstance(obj, dict):
        raise ConfigurationError("VALUE_INVALID", path)
    if "op" not in obj:
        raise ConfigurationError("MISSING_REQUIRED_FIELD", _join(path, "op"))
    op = obj["op"]
    if not isinstance(op, str) or op not in _ALL_KNOWN_OPS:
        raise ConfigurationError("UNKNOWN_OPERATION", _join(path, "op"))
    if op not in allowed_ops:
        raise ConfigurationError("INVALID_OPERATION_PLACEMENT", _join(path, "op"))
    return parsers[op](obj, path)


def _parse_acceptance_list(value: Any, path: str) -> list:
    if not isinstance(value, list):
        raise ConfigurationError("VALUE_INVALID", path)
    return [_parse_operation(entry, _index(path, i), _ACCEPTANCE_OPS, _ACCEPTANCE_PARSERS)
            for i, entry in enumerate(value)]


def _parse_mutation_list(value: Any, path: str) -> list:
    if not isinstance(value, list):
        raise ConfigurationError("VALUE_INVALID", path)
    return [_parse_operation(entry, _index(path, i), _MUTATION_OPS, _MUTATION_PARSERS)
            for i, entry in enumerate(value)]


# ---------------------------------------------------------------------------
# Policy decoding
# ---------------------------------------------------------------------------

_POLICY_REQUIRED = {"name", "version"}
_POLICY_OPTIONAL = {"acceptance", "mutation"}


def _parse_policy(obj: Any, path: str) -> Policy:
    """Assembles `Policy.operations` as `acceptance` operations followed by
    `mutation` operations, in each section's own document order -- a JSON
    document can never author mutation-before-Require, by construction
    (design checkpoint section 9 -- the acceptance/mutation split is a
    safety property of the declarative surface, not a change to
    `Policy.apply()`, which is untouched)."""
    _check_fields(obj, _POLICY_REQUIRED, _POLICY_OPTIONAL, path)
    name = obj["name"]
    if not isinstance(name, str):
        raise ConfigurationError("VALUE_INVALID", _join(path, "name"))
    version = obj["version"]
    if not isinstance(version, str):
        raise ConfigurationError("VALUE_INVALID", _join(path, "version"))
    acceptance = _parse_acceptance_list(obj.get("acceptance", []), _join(path, "acceptance"))
    mutation = _parse_mutation_list(obj.get("mutation", []), _join(path, "mutation"))
    return Policy(name=name, version=version, operations=tuple(acceptance) + tuple(mutation))


# ---------------------------------------------------------------------------
# Source / destination envelope decoding
# ---------------------------------------------------------------------------

_ENVELOPE_REQUIRED = {"type"}
_ENVELOPE_OPTIONAL = {"options"}


@dataclass(frozen=True)
class Envelope:
    """A minimal, deliberately opaque source/destination declaration. Only
    `type` (a non-empty string, not checked against any adapter registry --
    S1.4 builds no adapters) and `options` (an opaque, adapter-owned object,
    preserved exactly and never interpreted here) exist at the core level.
    `options`' *contents* are not validated beyond requiring the value
    itself to be a JSON object -- see the design checkpoint's "Unknown
    adapter type" section for why this is not an unknown-field escape hatch:
    `options` is itself a defined, closed field of the envelope; only its
    interior is intentionally opaque."""

    type: str
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", types.MappingProxyType(dict(self.options)))


def _parse_envelope(obj: Any, path: str) -> Envelope:
    if not isinstance(obj, dict):
        raise ConfigurationError("ENVELOPE_INVALID", path)
    unknown = sorted(set(obj.keys()) - (_ENVELOPE_REQUIRED | _ENVELOPE_OPTIONAL))
    if unknown:
        raise ConfigurationError("UNKNOWN_FIELD", _join(path, unknown[0]))
    if "type" not in obj:
        raise ConfigurationError("MISSING_REQUIRED_FIELD", _join(path, "type"))
    type_value = obj["type"]
    if not isinstance(type_value, str) or type_value == "":
        raise ConfigurationError("ENVELOPE_INVALID", _join(path, "type"))
    options = obj.get("options", {})
    if not isinstance(options, dict):
        raise ConfigurationError("ENVELOPE_INVALID", _join(path, "options"))
    return Envelope(type=type_value, options=options)


# ---------------------------------------------------------------------------
# Configuration -- the top-level decoded object
# ---------------------------------------------------------------------------

_TOP_LEVEL_REQUIRED = {"schema", "schema_version", "policy"}
_TOP_LEVEL_OPTIONAL = {"source", "destination"}


@dataclass(frozen=True)
class Configuration:
    """The fully-decoded, validated result of loading a Configuration V1
    document. `policy` is the actual, constructed, frozen `policy.Policy`
    object -- ready to pass directly to `policy.apply(structure, config.policy)`
    -- not a re-description of it; this module never duplicates `Policy`'s
    own semantics. Immutable: every field is itself immutable
    (`Policy`/`PolicyOperation`/`Locator` are already frozen dataclasses;
    `Envelope.options` is a read-only mapping)."""

    schema: str
    schema_version: int
    policy: Policy
    source: Optional[Envelope] = None
    destination: Optional[Envelope] = None


def load_configuration(data: Any) -> Configuration:
    """Validates and decodes an already-parsed JSON value (e.g. the output
    of `json.loads`) into a `Configuration`. Raises `ConfigurationError` on
    the first structural or semantic problem found -- see
    `ConfigurationError` for the fail-fast, single-cause contract."""
    _check_fields(data, _TOP_LEVEL_REQUIRED, _TOP_LEVEL_OPTIONAL, "")

    schema = data["schema"]
    if schema != SCHEMA_IDENTIFIER:
        raise ConfigurationError("SCHEMA_MISMATCH", "schema")

    schema_version = data["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) \
            or schema_version != SCHEMA_VERSION:
        raise ConfigurationError("SCHEMA_VERSION_UNSUPPORTED", "schema_version")

    policy_obj = data["policy"]
    if not isinstance(policy_obj, dict):
        raise ConfigurationError("VALUE_INVALID", "policy")
    decoded_policy = _parse_policy(policy_obj, "policy")

    source = _parse_envelope(data["source"], "source") if "source" in data else None
    destination = _parse_envelope(data["destination"], "destination") if "destination" in data else None

    return Configuration(schema=schema, schema_version=schema_version, policy=decoded_policy,
                          source=source, destination=destination)


def load_configuration_json(text: str) -> Configuration:
    """Parses `text` as JSON and validates/decodes it into a
    `Configuration`. Raises `ConfigurationError("MALFORMED_JSON", "")` for
    text that is not well-formed JSON at all; otherwise delegates to
    `load_configuration`."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("MALFORMED_JSON", "") from exc
    return load_configuration(data)


# ---------------------------------------------------------------------------
# Canonical serialization -- Configuration -> JSON, for round-trip proof only
# ---------------------------------------------------------------------------
#
# This is NOT a general PolicyResult/OperationResult/Diagnostic serializer
# (explicitly out of S1.4 scope -- design checkpoint Correction 3). It only
# ever serializes a *Configuration* -- i.e. round-trips the input side of
# this module, never the execution result.

def _tag_token(tag: Tag) -> str:
    group, element = tag
    return f"({group:04X},{element:04X})"


def _locator_to_json(locator: Locator) -> dict:
    if isinstance(locator, TagLocator):
        return {"tag": _tag_token(locator.tag), "scope": "recursive" if locator.recursive else "root"}
    if isinstance(locator, PathLocator):
        return {
            "path": [{"tag": _tag_token(step.tag), "item": step.item} for step in locator.steps],
            "tag": _tag_token(locator.tag),
        }
    raise TypeError(f"not a Locator V1 value: {locator!r}")


def _operation_to_json(op: PolicyOperation) -> dict:
    if isinstance(op, Require):
        return {"op": "require", "target": _locator_to_json(op.locator)}
    if isinstance(op, Remove):
        return {"op": "remove", "target": _locator_to_json(op.locator)}
    if isinstance(op, ReplaceText):
        return {"op": "replace_text", "target": _locator_to_json(op.locator), "value": op.values}
    if isinstance(op, EnsureText):
        result = {"op": "ensure_text", "target": _locator_to_json(op.locator), "value": op.values}
        if op.vr is not None:
            result["vr"] = op.vr
        return result
    if isinstance(op, AllowListPrune):
        return {"op": "allow_list_prune", "tags": [_tag_token(t) for t in op.tags]}
    if isinstance(op, PrivateTagPolicy):
        return {"op": "private_tag_policy", "remove": op.remove}
    raise TypeError(
        f"operation kind not representable in Configuration V1 (programmatic-only): {op!r}"
    )


def to_canonical_data(config: Configuration) -> dict:
    """Renders `config` back to the canonical Configuration V1 data shape
    (a plain JSON-serializable dict, deterministic field content and
    ordering, canonical tag spelling). The contract is *semantic*
    round-trip, not byte-identical text: re-parsing this output via
    `load_configuration` always reconstructs a `Configuration` equivalent to
    the original, but this function does not attempt to preserve the
    original author's whitespace or key order."""
    acceptance = [op for op in config.policy.operations if isinstance(op, Require)]
    mutation = [op for op in config.policy.operations if not isinstance(op, Require)]
    data = {
        "schema": config.schema,
        "schema_version": config.schema_version,
        "policy": {
            "name": config.policy.name,
            "version": config.policy.version,
            "acceptance": [_operation_to_json(op) for op in acceptance],
            "mutation": [_operation_to_json(op) for op in mutation],
        },
    }
    if config.source is not None:
        data["source"] = {"type": config.source.type, "options": dict(config.source.options)}
    if config.destination is not None:
        data["destination"] = {"type": config.destination.type, "options": dict(config.destination.options)}
    return data


def to_canonical_json(config: Configuration) -> str:
    return json.dumps(to_canonical_data(config), indent=2)
