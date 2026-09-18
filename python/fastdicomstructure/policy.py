"""A minimal, deterministic policy layer over Structure's existing mutation
and inspection primitives.

As of S1.1 ("Structure Locator Model v1"), `Require`, `Remove`, `Replace`,
`AllowListPrune`, `PrivateTagPolicy` are locator-capable: each can target a
bare tag (root-or-anywhere, matching the pre-S1.1 API exactly), one concrete
nested occurrence, or a zero-to-many wildcard pattern, through one shared
resolution engine (`resolve_locator`). See
docs/architecture/S1_1_LOCATOR_MODEL_REPORT.md for the full design rationale,
invariants, and evidence.

As of S1.2, three more operations extend the same locator vocabulary onto
charset-aware text and set-or-insert ("ensure") semantics: `ReplaceText`,
`Ensure`, `EnsureText`. See
docs/architecture/S1_2_REPLACE_ENSURE_DESIGN_CHECKPOINT.md (design) and
docs/architecture/S1_2_REPLACE_ENSURE_IMPLEMENTATION_REPORT.md (freeze
evidence) for the full rationale.

As of S1.3, `OperationResult`/`PolicyResult`/`Diagnostic` carry a complete,
structured account of what happened: `ExecutionStatus`
(`COMPLETED`/`FAILED`/`ROLLED_BACK`/`NOT_EXECUTED`) and
`PolicyExecutionStatus` (`COMPLETED`/`REJECTED`/`PARTIAL`) separate "did this
execute successfully" from `satisfied`'s narrower "did this operation's own
condition/guarantee hold" (`Require`/`Ensure`/`EnsureText` only -- `None`
elsewhere); a stable `Diagnostic` code vocabulary (`DIAGNOSTIC_CODES`)
replaces ad hoc messages; `Policy.apply()` gains a narrow, closed exception
boundary (never a blanket `except Exception`) converting known policy-
execution failures into a `PARTIAL` `PolicyResult` with later operations
marked `NOT_EXECUTED`, while `RollbackError` and any unrecognized exception
continue to propagate raw. `Replace` is also brought onto the same
operation-atomic engine `ReplaceText`/`Ensure`/`EnsureText` already used
(closing a real asymmetry the S1.3 design checkpoint's own evidence-gathering
found: a raw `Replace` callback failing partway through a wildcard used to
leave earlier sites mutated; it no longer does). See
docs/architecture/S1_3_RESULT_DIAGNOSTIC_DESIGN_CHECKPOINT.md (design,
including that correction's history) and
docs/architecture/S1_3_RESULT_DIAGNOSTIC_IMPLEMENTATION_REPORT.md (freeze
evidence) for the full rationale; this docstring covers only what a caller
of this module needs to know.

Design choices, stated up front so the shape below isn't mistaken for an
oversight:

* **Eight operation kinds, closed.** This is not a plugin system and
  `PolicyOperation` is not meant to be subclassed by callers -- extending
  behavior happens through `Replace`/`ReplaceText`'s callback hook, not by
  adding operation kinds. If a use case needs a ninth kind, that is a signal
  to revisit this module, not to subclass around it.
* **Locator V1, not a query language.** `TagLocator` / `PathLocator` /
  `LocatorStep` answer exactly one question -- "which concrete element(s)
  does this name" -- with no value/VR/private-creator predicates. "Should
  policy apply" conditions are a separate, future concern. `Ensure`/
  `EnsureText` introduce a second, internal-only, non-public question --
  "where may a missing final element be created" -- answered by
  `_resolve_insertion_sites`/`_InsertionSite`, never by a new public locator
  type; see docs/architecture/S1_2_REPLACE_ENSURE_DESIGN_CHECKPOINT.md
  section 7.
* **No business logic.** No HMAC pseudonymization, no UID remapping, no
  date shifting, no data dictionary, no confidentiality profiles. `Replace`/
  `ReplaceText` accept a plain literal or a caller-supplied per-occurrence
  callback so that policy *content* like the above can be composed by a
  caller without this module knowing what it is. `Ensure`/`EnsureText` are
  literal-value-only by design -- see their own docstrings.
* **Raw vs. text is a class name, never a runtime type guess.** `Replace`/
  `Ensure` take raw `bytes`; `ReplaceText`/`EnsureText` take `str`/
  `Sequence[str]`. This mirrors frozen attrs' own `set_value`/`insert` vs.
  `set_text`/`insert_text` split exactly -- Structure never inspects a
  value's Python type to decide which behavior to apply.
* **No new C ABI surface.** Every operation is built from primitives
  `Structure` already exposes: `get`, `find`, `set_value`, `set_text`,
  `insert`, `insert_text`, `decode_text`, `erase`, `erase_private`, and
  `iter_elements`. `resolve_locator`/`_resolve_insertion_sites` are
  pure-Python composition of existing read-only primitives, not a new
  mutation primitive; charset/VR semantics are never reimplemented here --
  see docs/architecture/S1_2_REPLACE_ENSURE_DESIGN_CHECKPOINT.md sections
  12-15.
* **`Replace`/`ReplaceText`/`Ensure`/`EnsureText` are operation-atomic.**
  Each either fully applies to every site it resolves, or leaves the
  structure exactly as it was before the operation ran (raw-byte-exact for
  every previously-existing element it touched) -- see
  `_apply_sites_atomically` and `RollbackError`. `Remove`/`AllowListPrune`/
  `PrivateTagPolicy` are not given this machinery: they only ever wrap attrs
  calls that cannot meaningfully fail once `resolve_locator` has already
  confirmed a path exists (`erase`, bool-return, never raises).
* **No transactionality across operations.** `apply()` executes a policy's
  operations in order. If a `Require` fails, evaluation stops immediately
  and the decision is `reject` -- but any operation that already ran earlier
  in the same `apply()` call has already mutated the structure, and nothing
  here undoes it. A caller that needs "no partial mutation on reject" must
  put every `Require` first in the operation list. This is a real
  limitation of this module, not hidden by it. (Atomicity *within* one
  `ReplaceText`/`Ensure`/`EnsureText` call, across its own possibly-many
  resolved sites, is a separate, narrower guarantee -- see above.)
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Callable, List, Optional, Sequence, Union

# Four A1.7 exception subclasses attrs' own __all__ exports but
# fastdicomstructure/__init__.py does not yet re-export (a pre-existing gap
# named in docs/architecture/POST_A1_RUTHLESS_INVENTORY.md, not fixed here --
# out of S1.3's authorized scope). Imported directly from the frozen attrs
# package itself -- already on sys.path by the time this module loads, since
# fastdicomstructure/__init__.py adds it before `from . import policy` runs
# -- not a new dependency, just bypassing an incomplete shim.
from fastdicomattrs import (
    AlreadyExistsError,
    FdsError,
    InvalidUnicodeInputError,
    UnrepresentableCharacterError,
    VRRequiredError,
)

if TYPE_CHECKING:
    from . import Element, Structure

__all__ = [
    "Tag",
    "ITEM_WILDCARD",
    "MalformedLocatorError",
    "LocatorStep",
    "TagLocator",
    "PathLocator",
    "Locator",
    "resolve_locator",
    "RollbackError",
    "CallbackError",
    "ExecutionStatus",
    "PolicyExecutionStatus",
    "DIAGNOSTIC_CODES",
    "Decision",
    "OperationResult",
    "Diagnostic",
    "PolicyResult",
    "PolicyOperation",
    "Require",
    "Remove",
    "Replace",
    "ReplaceText",
    "Ensure",
    "EnsureText",
    "AllowListPrune",
    "PrivateTagPolicy",
    "Policy",
    "apply",
]

Tag = tuple[int, int]

# An attrs-consumable concrete element path: a list of (Tag, item_index)
# steps, every step but the last carrying a concrete Item index, the last
# always None (names the element itself). This is the exact shape accepted
# by Structure.find/set_value/erase/set_text/decode_text -- resolve_locator
# below produces this shape directly; nothing else in this module needs to
# know it exists.
ElementPath = list[tuple[Tag, Optional[int]]]


def _format_tag(tag: Tag) -> str:
    group, element = tag
    return f"({group:04X},{element:04X})"


def _describe_path(path: "ElementPath") -> str:
    """Structure-owned, human-readable rendering of a concrete, already-
    resolved attrs element path -- e.g. `"(300A,00B0)[2]/(0008,0090)"`. Used
    only for `Diagnostic.site`; the raw list-of-`(tag, item_index)` tuples
    themselves are never placed in a `Diagnostic` (see docs/architecture/
    S1_3_RESULT_DIAGNOSTIC_DESIGN_CHECKPOINT.md section 14 -- attrs'
    ElementPath shape stays an execution detail, not a public result field,
    exactly as S1.1 already kept it out of the locator-authoring surface)."""
    parts = []
    for tag, item_index in path:
        rendered = _format_tag(tag)
        if item_index is not None:
            rendered += f"[{item_index}]"
        parts.append(rendered)
    return "/".join(parts)


def _is_bare_tag(value) -> bool:
    return (isinstance(value, tuple) and len(value) == 2
            and all(isinstance(x, int) and not isinstance(x, bool) for x in value))


class MalformedLocatorError(ValueError):
    """Raised at Locator V1 construction time when a locator's own shape is
    invalid (bad tag arity/type, bad Item selector) -- independent of any
    Structure. Deliberately distinct from "valid locator, zero matches":
    see docs/architecture/S1_1_LOCATOR_MODEL_REPORT.md, "Zero-match vs
    malformed"."""


def _validate_tag(tag) -> None:
    if not _is_bare_tag(tag):
        raise MalformedLocatorError(
            f"invalid tag {tag!r}: expected a (group, element) tuple of ints"
        )


# ---------------------------------------------------------------------------
# Structure Locator Model v1
# ---------------------------------------------------------------------------

ITEM_WILDCARD = "*"  # sentinel Item selector: "every Item of this Sequence"


@dataclass(frozen=True)
class LocatorStep:
    """One Sequence-descent step of a PathLocator: enter Sequence `tag`'s
    Item `item` -- a concrete non-negative Item index, or ITEM_WILDCARD
    ("*") for every Item. `item` is chosen to be the literal JSON token a
    future declarative loader would use (see the S1.1 report,
    "JSON-authorability")."""

    tag: Tag
    item: Union[int, str]

    def __post_init__(self) -> None:
        _validate_tag(self.tag)
        valid_index = isinstance(self.item, int) and not isinstance(self.item, bool) and self.item >= 0
        if self.item != ITEM_WILDCARD and not valid_index:
            raise MalformedLocatorError(
                f"invalid Item selector {self.item!r} for step {_format_tag(self.tag)}: "
                f"expected a non-negative int or {ITEM_WILDCARD!r}"
            )

    def __repr__(self) -> str:
        return f"{_format_tag(self.tag)}[{self.item}]"


@dataclass(frozen=True)
class TagLocator:
    """The bare-tag compatibility form: target `tag` according to the
    operation's defined scope. `recursive=True` (default) means "this tag,
    at any nesting depth, anywhere in the document" -- the pre-S1.1
    `erase_recursive`/`set_value_recursive` scope. `recursive=False` means
    "this tag, root level only" -- the pre-S1.1 `erase`/`set_value`/
    `__contains__` scope (also Require's only historical scope).

    Kept as its own Locator kind rather than a special case of PathLocator:
    "anywhere, any depth, any container shape" is not expressible as a
    fixed-depth step chain -- see the S1.1 report for the full rationale.
    """

    tag: Tag
    recursive: bool = True

    def __post_init__(self) -> None:
        _validate_tag(self.tag)

    def __repr__(self) -> str:
        return f"TagLocator({_format_tag(self.tag)}, scope={'recursive' if self.recursive else 'root'})"


@dataclass(frozen=True)
class PathLocator:
    """A concrete or wildcard nested locator: zero or more `LocatorStep`
    container descents, followed by a leaf `tag`. Zero steps names a root
    element (meaning-equivalent, though not identical in type, to
    `TagLocator(tag, recursive=False)`). Any step with `item ==
    ITEM_WILDCARD` makes `is_pattern` True (zero-to-many matches);
    all-concrete steps make this a CONCRETE LOCATOR naming exactly one
    possible element location (it may still resolve to zero matches at
    runtime -- see resolve_locator's zero-match semantics).

    `steps` entries may be given as plain `(tag, item)` tuples for
    authoring convenience; they are normalized to `LocatorStep` in
    `__post_init__`.
    """

    steps: tuple[LocatorStep, ...]
    tag: Tag

    def __post_init__(self) -> None:
        normalized = tuple(
            step if isinstance(step, LocatorStep) else LocatorStep(*step)
            for step in self.steps
        )
        object.__setattr__(self, "steps", normalized)
        _validate_tag(self.tag)

    @property
    def is_pattern(self) -> bool:
        return any(step.item == ITEM_WILDCARD for step in self.steps)

    def __repr__(self) -> str:
        parts = [repr(step) for step in self.steps] + [_format_tag(self.tag)]
        return "PathLocator(" + "/".join(parts) + ")"


Locator = Union[TagLocator, PathLocator]


def _normalize_locator(value, recursive: bool) -> "Locator":
    """Structure's one locator-normalization point: a bare (group, element)
    tuple becomes `TagLocator(tag, recursive)`; a `TagLocator`/`PathLocator`
    passed directly is used as-is (the caller's own `recursive=` field, if
    any, is then irrelevant for that operation)."""
    if isinstance(value, (TagLocator, PathLocator)):
        return value
    if _is_bare_tag(value):
        return TagLocator(tag=value, recursive=recursive)
    raise MalformedLocatorError(
        f"invalid locator {value!r}: expected a (group, element) tag, a TagLocator, "
        "or a PathLocator"
    )


def _leaf_tag(locator: "Locator") -> Tag:
    return locator.tag


def resolve_locator(structure: "Structure", locator: "Locator") -> list[ElementPath]:
    """The single Locator V1 resolution engine. Expands `locator` against
    `structure` into zero or more concrete attrs element paths, each
    directly usable with Structure.find/set_value/erase/set_text/
    decode_text -- no further translation step exists or is needed.

    Every locator kind goes through this one function; no operation below
    implements its own traversal. A syntactically valid locator that
    matches nothing returns `[]` -- not an error (see the S1.1 report,
    "Zero-match vs malformed"); a malformed locator was already rejected at
    construction time and can never reach this function.

    Deterministic: PathLocator wildcard expansion follows Sequence Item
    index order (0..N-1), depth-first over the step list; TagLocator's
    `recursive=True` scope is exactly `Structure.iter_elements`'s own
    document order, filtered by tag. Calling this twice against the same
    unmutated `structure` returns identical, identically-ordered lists.
    Only `find`/`is_sequence`/`items()` are used -- never `.value` -- so
    resolving a locator never materializes an element's value (relevant
    for Pixel Data: discovery only, never decoded here).
    """
    if isinstance(locator, TagLocator):
        if not locator.recursive:
            return [[(locator.tag, None)]] if locator.tag in structure else []
        return [
            path for element, path in structure.iter_elements(recursive=True)
            if element.tag == locator.tag
        ]

    if isinstance(locator, PathLocator):
        matches: list[ElementPath] = []
        for prefix in _expand_path_locator_prefixes(structure, locator):
            leaf_path = prefix + [(locator.tag, None)]
            if structure.find(leaf_path) is not None:
                matches.append(leaf_path)
        return matches

    raise TypeError(f"not a Locator V1 value: {locator!r}")


def _expand_path_locator_prefixes(structure: "Structure", locator: "PathLocator") -> list[ElementPath]:
    """The shared step-expansion core behind both `resolve_locator` (which
    filters the result to leaf-exists paths) and `_resolve_insertion_sites`
    (which does not filter, and tags each surviving prefix with whether the
    leaf exists there). Returns every concrete container-locator prefix
    `locator.steps` resolves to, in deterministic Item-index order -- a
    missing/wrong-index/non-SQ intermediate step simply contributes no
    prefixes past that point (see `resolve_locator`'s "Zero-match vs
    malformed" and the S1.2 checkpoint's identical treatment for insertion
    sites); a missing *leaf* is not this function's concern at all, since it
    only ever inspects containers, never the leaf tag itself.
    """
    prefixes: list[ElementPath] = [[]]
    for step in locator.steps:
        next_prefixes: list[ElementPath] = []
        for prefix in prefixes:
            container = structure.find(prefix + [(step.tag, None)])
            if container is None or not container.is_sequence:
                continue  # missing Sequence / non-SQ intermediate -> empty branch
            items = list(container.items())
            if step.item == ITEM_WILDCARD:
                indices = range(len(items))
            elif step.item < len(items):
                indices = (step.item,)
            else:
                indices = ()  # Item index out of range -> empty branch
            for index in indices:
                next_prefixes.append(prefix + [(step.tag, index)])
        prefixes = next_prefixes
    return prefixes


@dataclass(frozen=True)
class _InsertionSite:
    """Internal only -- not part of the public Locator V1 vocabulary, never
    exported. Answers a different question than `resolve_locator`: not
    "does this exist" but "where may a missing final element be created, and
    does it already exist there." `parent` is an attrs container-locator
    path (every step concrete, `[]` for root); `target_path` is
    `parent + [(tag, None)]`, the element-locator form, valid whether or not
    `exists`. See docs/architecture/S1_2_REPLACE_ENSURE_DESIGN_CHECKPOINT.md
    section 7."""

    parent: ElementPath
    tag: Tag
    exists: bool
    target_path: ElementPath


def _resolve_insertion_sites(structure: "Structure", locator: "Locator") -> list["_InsertionSite"]:
    """The single insertion-site resolution engine behind `Ensure`/
    `EnsureText`. Shares `_expand_path_locator_prefixes` with
    `resolve_locator` for `PathLocator` -- no second traversal
    implementation. Never synthesizes a missing structural ancestor: a
    prefix that `_expand_path_locator_prefixes` could not reach (missing
    Sequence, wrong Item index, non-SQ intermediate) simply produces no
    site, exactly like `resolve_locator`'s equivalent zero-match case.

    `TagLocator(recursive=False)` (including `Ensure`/`EnsureText`'s own
    bare-tag default): exactly one site, the root -- always a valid
    container, so root insertion is always well-defined regardless of
    whether the tag currently exists there.

    `TagLocator(recursive=True)`: existing occurrences only, one site per
    match, all with `exists=True` -- **never an insertion site**. "Anywhere,
    any depth, any container shape" does not name a single container an
    insertion could target; zero existing occurrences correctly produces
    zero sites (a no-op for `Ensure`/`EnsureText`, not an insertion
    anywhere). See the S1.2 checkpoint section 8 for the full reasoning
    behind this deliberately-not-backward-compatible choice.

    `PathLocator` (concrete or wildcard): one site per surviving prefix from
    `_expand_path_locator_prefixes`, each independently tagged `exists`
    depending on whether that specific prefix's leaf is currently present --
    a missing leaf never eliminates an otherwise-valid site; a
    missing/wrong-shaped ancestor never produces one to begin with.
    """
    if isinstance(locator, TagLocator):
        if not locator.recursive:
            target_path: ElementPath = [(locator.tag, None)]
            return [_InsertionSite(parent=[], tag=locator.tag,
                                    exists=locator.tag in structure, target_path=target_path)]
        return [
            _InsertionSite(parent=path[:-1], tag=locator.tag, exists=True, target_path=path)
            for element, path in structure.iter_elements(recursive=True)
            if element.tag == locator.tag
        ]

    if isinstance(locator, PathLocator):
        sites: list[_InsertionSite] = []
        for prefix in _expand_path_locator_prefixes(structure, locator):
            leaf_path = prefix + [(locator.tag, None)]
            exists = structure.find(leaf_path) is not None
            sites.append(_InsertionSite(parent=prefix, tag=locator.tag, exists=exists,
                                         target_path=leaf_path))
        return sites

    raise TypeError(f"not a Locator V1 value: {locator!r}")


def _remove_matches(structure: "Structure", locator: "Locator") -> int:
    """Shared by Remove and AllowListPrune. Deletes every element
    `locator` resolves to, ordered by descending path length so that if one
    match's subtree happens to contain another (only possible for
    `TagLocator(recursive=True)`, where the same tag could recur nested
    inside its own occurrence), the descendant is removed -- or found
    already gone, harmlessly, since `erase()` returns False rather than
    raising -- before the ancestor's `erase()` could otherwise sweep it
    away as a side effect. Equal-length matches from one PathLocator
    template are always disjoint siblings, so their relative order never
    matters. Returns the number of elements actually removed, which may be
    fewer than the number of resolved paths if an ancestor/descendant pair
    collapsed into one removal.
    """
    ordered = sorted(resolve_locator(structure, locator), key=len, reverse=True)
    removed = 0
    for path in ordered:
        if structure.erase(path):
            removed += 1
    return removed


def _resolve_and_replace(structure: "Structure", locator: "Locator",
                          value: Union[bytes, Callable[[bytes], bytes]]) -> int:
    """Shared by Replace. As of S1.3, routed through `_apply_sites_atomically`
    -- the same engine `ReplaceText`/`Ensure`/`EnsureText` already used,
    closing a real asymmetry the S1.3 design checkpoint's own evidence-
    gathering found: previously, a wildcard `Replace` whose callback raised
    partway through left every already-succeeded site mutated, while
    `ReplaceText` (already atomic) rolled its own back. `Replace` never
    produces an insertion site (absence is always a no-op, matching its
    original contract exactly) -- every resolved match is `exists=True`.

    A callback receives that occurrence's own original bytes, read
    immediately before that occurrence's own `set_value` -- the same
    per-occurrence-correctness property the pre-S1.3 implementation already
    had, unchanged. A callback's own exception is wrapped in `CallbackError`
    (never left as whatever arbitrary type the callback raised) so
    `Policy.apply()`'s exception boundary can recognize it reliably.

    A `set_value` that returns `False` (e.g. a too-long value) is, as of
    S1.3, a real failure -- `_MutationFailed` is raised, not silently
    absorbed into a smaller count (the S1.2-era gap this correction closes).
    """
    sites = [
        _InsertionSite(parent=path[:-1], tag=_leaf_tag(locator), exists=True, target_path=path)
        for path in resolve_locator(structure, locator)
    ]
    if not sites:
        return 0

    def do_update(structure: "Structure", path: ElementPath) -> None:
        element = structure.find(path)
        if callable(value):
            try:
                new_value = value(element.value)
            except Exception as exc:
                raise CallbackError(exc) from exc
        else:
            new_value = value
        if not structure.set_value(path, new_value):
            raise _MutationFailed(
                f"set_value returned False for {path!r} -- value likely too long for the "
                "element's existing length form"
            )

    updated, inserted = _apply_sites_atomically(structure, sites, do_update, do_insert=None)
    return updated + inserted


class RollbackError(RuntimeError):
    """Raised when an S1.2 atomic operation (`ReplaceText`/`Ensure`/
    `EnsureText`) fails *and* its own rollback could not fully restore every
    previously-applied site in this operation. This is not the expected
    outcome -- attrs' own documented per-call atomicity (S1.2 checkpoint
    section 16/16a) makes rollback provably safe in the ordinary case, and
    every S1.2 test proves it succeeds -- but "provably safe" is qualified
    here, not merely assumed: every undo action's own outcome is checked,
    and this exception exists for the case one unexpectedly does not
    succeed, so that outcome is never silently reported as if the operation
    had merely failed cleanly.

    `forward_error` is the original exception that triggered rollback
    (available as `__cause__` too, via ordinary exception chaining).
    `failed_undo_actions` is a tuple of `(kind, path)` pairs -- `kind` is
    `"restore_raw"` or `"erase"` -- describing exactly which undo actions did
    not complete; every *other* undo action in the same rollback still ran
    (rollback continues attempting every remaining action rather than
    aborting on the first failure, to restore as much as possible)."""

    def __init__(self, forward_error: BaseException, failed_undo_actions: tuple):
        self.forward_error = forward_error
        self.failed_undo_actions = failed_undo_actions
        super().__init__(
            f"operation failed ({forward_error!r}) and {len(failed_undo_actions)} rollback "
            f"action(s) did not complete: {failed_undo_actions!r} -- the structure may be left "
            "in a partially-mutated state for those specific paths"
        )


class _MutationFailed(RuntimeError):
    """Internal marker: a boolean-return attrs primitive (`set_value`)
    reported failure. Raised only so `_apply_sites_atomically` can treat
    every forward-mutation failure uniformly (attrs exceptions and
    boolean-return failures alike) without needing to know which primitive
    a given `do_update`/`do_insert` callback used. Maps to the
    `MUTATION_FAILED` diagnostic code at the `Policy.apply()` boundary (see
    `_classify_exception`). As of S1.3, this is no longer silently
    swallowed into an under-counted result (the S1.2-era `Replace` gap) --
    raising it is what makes the failure real and reportable."""


class CallbackError(RuntimeError):
    """Wraps an exception raised by a caller-supplied `Replace`/
    `ReplaceText` callback, so `Policy.apply()`'s exception boundary can
    recognize a callback failure specifically (`CALLBACK_FAILED`) without
    pattern-matching on arbitrary user exception types -- a callback may
    raise anything. `cause_type` is the *original* exception's class name
    only; `original` is kept for `from`-chaining (developer-facing
    tracebacks) but neither it nor its message is ever copied into a
    `Diagnostic` field (see `_classify_exception`/`_diagnostic` -- privacy
    rule, docs/architecture/S1_3_RESULT_DIAGNOSTIC_DESIGN_CHECKPOINT.md
    section 15). Raised at the point a callback is *invoked*, never for a
    failure attrs itself reports about the callback's (correctly-typed)
    returned value -- that remains an ordinary attrs failure (`MUTATION_FAILED`/
    `CHARACTER_UNREPRESENTABLE`/etc.), not a callback failure."""

    def __init__(self, original: BaseException):
        self.original = original
        self.cause_type = type(original).__name__
        super().__init__(f"callback raised {self.cause_type}")


def _attach_failed_site(exc: BaseException, path: "ElementPath") -> None:
    """Records which concrete site a forward-mutation failure occurred at,
    as a Structure-owned rendered string (`_describe_path`) -- never the
    raw attrs path tuples -- on the exception object itself, so
    `Policy.apply()` can populate `Diagnostic.site` without
    `_apply_sites_atomically` needing to return anything richer than it
    already does on success. Best-effort: some exception types restrict
    attribute assignment, so failure to attach is silently ignored (the
    diagnostic is simply built without a `site`, not less correct)."""
    try:
        exc._fds_policy_failed_site = _describe_path(path)
    except Exception:
        pass


def _apply_sites_atomically(
    structure: "Structure",
    sites: list["_InsertionSite"],
    do_update: Callable[["Structure", ElementPath], None],
    do_insert: Optional[Callable[["Structure", ElementPath, Tag], None]],
) -> tuple[int, int]:
    """The shared atomic mutation/rollback engine behind `Replace`,
    `ReplaceText`, `Ensure`, and `EnsureText` (as of S1.3, `Replace` is on
    this engine too -- see the module docstring and docs/architecture/
    S1_3_RESULT_DIAGNOSTIC_DESIGN_CHECKPOINT.md's "Correction 1"). `sites`
    must already be fully resolved (a pure read, no mutation) before this is
    called. `do_update(structure, target_path)` performs the forward
    mutation for an existing-target site (raising on failure); `do_insert
    (structure, parent, tag)` performs it for a missing-target site (`None`
    if the caller never produces `exists=False` sites, e.g. `Replace`/
    `ReplaceText`).

    An existing target that is itself a sequence element is silently
    skipped (no mutation, not counted, no undo entry) -- mirroring the
    original `Replace`'s own long-established convention, and avoiding
    `Element.value`'s `ValueError` for a sequence, which has no scalar
    value to capture or restore.

    Returns `(updated_count, inserted_count)` -- split, not a single total,
    so `Ensure`/`EnsureText` can report both without re-deriving them from
    `sites` (which would wrongly include the sequence-skip case above as
    "changed"). `Replace`/`ReplaceText` always get `inserted_count == 0`
    (`do_insert=None`, never called) and simply sum the two.

    Operation-atomic: either every *actionable* site (excluding the
    sequence-skip case above) is successfully mutated, or the structure is
    restored to exactly its pre-call state for every site this call
    touched, and the original failure is re-raised (see docs/architecture/
    S1_2_REPLACE_ENSURE_DESIGN_CHECKPOINT.md section 16a for why this is
    achieved via mutate-with-guaranteed-rollback rather than
    validate-then-commit, and why rollback is expected to always succeed).
    Before re-raising a fully-recovered failure, this function records
    (best-effort, via `_attach_failed_site`) which site failed and (via a
    private `_fds_policy_rolled_back` attribute) whether *any* site had
    already been mutated when the failure occurred -- both consumed only by
    `Policy.apply()`'s exception boundary (`_classify_exception`), never
    part of this function's own public contract to a direct caller, who
    still just sees the original exception type re-raised unchanged.

    Rollback restores raw bytes for update sites -- **never** semantic text
    -- captured from `Element.value` *before* `do_update` runs, regardless of
    whether `do_update` itself performed a raw or charset-aware mutation.
    This is the S1.2 design-checkpoint correction: decode/re-encode is not
    used for restoration, only for forward text mutation, because a
    decode-then-re-encode round-trip is not guaranteed to reproduce the
    exact original bytes (different but equally valid padding/ISO 2022
    escape placement) even when it reproduces the same decoded text.
    """
    undo_log: list[tuple] = []  # ("restore_raw", path, original_bytes) | ("erase", path)
    updated = 0
    inserted = 0
    try:
        for site in sites:
            if site.exists:
                element = structure.find(site.target_path)
                if element is None or element.is_sequence:
                    continue  # mirrors Replace's own skip-sequence convention; nothing to undo
                original = element.value
                try:
                    do_update(structure, site.target_path)
                except Exception as exc:
                    _attach_failed_site(exc, site.target_path)
                    raise
                undo_log.append(("restore_raw", site.target_path, original))
                updated += 1
            else:
                if do_insert is None:
                    raise AssertionError(
                        f"resolved an insertion site with exists=False but this operation "
                        f"supports update-only sites: {site!r}"
                    )
                try:
                    do_insert(structure, site.parent, site.tag)
                except Exception as exc:
                    _attach_failed_site(exc, site.target_path)
                    raise
                undo_log.append(("erase", site.target_path))
                inserted += 1
        return updated, inserted
    except Exception as forward_error:
        failed: list[tuple] = []
        for action in reversed(undo_log):
            kind = action[0]
            try:
                if kind == "restore_raw":
                    _, path, original_bytes = action
                    if not structure.set_value(path, original_bytes):
                        failed.append((kind, path))
                else:  # "erase"
                    _, path = action
                    if not structure.erase(path):
                        failed.append((kind, path))
            except Exception:
                failed.append((kind, action[1]))
        if failed:
            raise RollbackError(forward_error, tuple(failed)) from forward_error
        try:
            forward_error._fds_policy_rolled_back = bool(undo_log)
        except Exception:
            pass
        raise


class ExecutionStatus(str, enum.Enum):
    """Did this *operation* execute successfully -- independent of whether
    its condition/guarantee (`OperationResult.satisfied`) held. A str
    subclass, matching `Decision`'s own established convention.

    `COMPLETED`: ran to completion. This is the *only* status a direct
    `operation.apply(structure)` call ever returns on a normal return --
    `FAILED`/`ROLLED_BACK` never appear from a direct call, because a
    direct call raises instead (see the module docstring, "operations
    called directly retain their existing raise-oriented failure
    contract"); they appear only in an `OperationResult` `Policy.apply()`
    itself constructs after catching a known failure.
    `FAILED`: `Policy.apply()` caught a known policy-execution failure
    (section: "Exception boundary") and no site of this operation had been
    mutated yet when it occurred.
    `ROLLED_BACK`: same, but at least one site *had* been mutated and was
    then exactly restored (raw bytes) before the failure was converted to
    this result -- the operation's net committed effect is zero.
    `NOT_EXECUTED`: never ran, because an earlier operation in the same
    `Policy` rejected (`Require`) or failed. Never appears outside a
    `PolicyResult`."""

    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    NOT_EXECUTED = "not_executed"


class PolicyExecutionStatus(str, enum.Enum):
    """Did the *containing Policy* run every one of its operations.
    `COMPLETED`: every operation ran (individual operations may still
    report `satisfied=False`, e.g. `Ensure`'s `GUARANTEE_UNESTABLISHED` --
    that does not halt the Policy, see `Ensure`'s own docstring).
    `REJECTED`: stopped early because a `Require` was unsatisfied.
    `PARTIAL`: stopped early because `Policy.apply()` caught a known
    operation failure (see "Exception boundary" below) -- operation
    atomicity held for every operation that ran (each is either fully
    `COMPLETED` or fully `ROLLED_BACK`), but the Policy's own intended
    end-state was not reached. There is deliberately no whole-policy
    rollback: operations before the failure remain exactly as they were
    left, per the module docstring's "No transactionality across
    operations"."""

    COMPLETED = "completed"
    REJECTED = "rejected"
    PARTIAL = "partial"


class Decision(str, enum.Enum):
    """The simple, coarse-grained outcome of `apply()` -- kept for callers
    who only need a ternary-ish summary; `PolicyResult.execution` is the
    authoritative field for anything more precise. A str subclass so it
    compares equal to and logs as its own value without callers needing to
    know it's an Enum.

    `ACCEPT`/`TRANSFORM`/`REJECT` mean exactly what they always have,
    unchanged, and only ever appear together with `execution=COMPLETED` (the
    first two) or `execution=REJECTED` (the third). `PARTIAL` is new in
    S1.3: it appears only together with `execution=PolicyExecutionStatus.PARTIAL`,
    and exists specifically so a caller reading `decision` alone is never
    told a partially-executed, failed Policy was accepted or transformed
    successfully -- there was no valid three-value answer for that case in
    the pre-S1.3 enum, and inventing one by reusing ACCEPT/TRANSFORM/REJECT
    would have been actively misleading (see docs/architecture/
    S1_3_RESULT_DIAGNOSTIC_IMPLEMENTATION_REPORT.md, "Policy decision", for
    the full analysis of why a fourth value, not a reinterpretation of the
    existing three, is the smallest correct fix)."""

    ACCEPT = "accept"
    TRANSFORM = "transform"
    REJECT = "reject"
    PARTIAL = "partial"


DIAGNOSTIC_CODES = (
    "REQUIREMENT_UNSATISFIED",
    "GUARANTEE_UNESTABLISHED",
    "VR_REQUIRED",
    "TEXT_OPERATION_UNSUPPORTED",
    "INVALID_UNICODE",
    "CHARACTER_UNREPRESENTABLE",
    "ALREADY_EXISTS",
    "MUTATION_FAILED",
    "CALLBACK_FAILED",
    "ROLLBACK_FAILED",
)
"""The stable, closed vocabulary of `Diagnostic.code` values this module can
produce. `ROLLBACK_FAILED` is reserved for a caller who catches
`RollbackError` themselves and wants to build their own `Diagnostic` from it
-- `Policy.apply()` never constructs one automatically, since `RollbackError`
is never converted into an ordinary `PolicyResult` (see "Exception boundary"
below). `LOCATOR_INVALID` is deliberately *not* in this tuple: a malformed
locator raises `MalformedLocatorError` at operation *construction*, before a
`Policy`/`Diagnostic` could ever exist to report it -- the name is reserved
in documentation only, for a future S1.4 JSON loader's own construction-time
reporting, with no S1.3 runtime path producing it."""

_DIAGNOSTIC_MESSAGES = {
    "REQUIREMENT_UNSATISFIED": "required locator has zero matches",
    "GUARANTEE_UNESTABLISHED": "no concrete insertion site could be established for this locator",
    "VR_REQUIRED": "VR could not be inferred for this tag; an explicit vr= is required",
    "TEXT_OPERATION_UNSUPPORTED": (
        "the target's VR is not text-governed, or its effective character set declaration is "
        "unsupported or malformed"
    ),
    "INVALID_UNICODE": "the supplied text is not well-formed Unicode",
    "CHARACTER_UNREPRESENTABLE": (
        "the requested text is not representable under this site's effective character set"
    ),
    "ALREADY_EXISTS": "an element already exists at this insertion site",
    "MUTATION_FAILED": "the requested mutation could not be applied to this element",
    "CALLBACK_FAILED": "the caller-supplied callback raised an exception",
    "ROLLBACK_FAILED": "operation rollback could not fully restore every previously-applied site",
}


@dataclass(frozen=True)
class Diagnostic:
    """A policy-evaluation-time diagnostic. Distinct from Structure's own
    `diagnostics` property, which reports *parse*-time findings -- the two
    are not merged here, since they answer different questions ("was the
    input well-formed" vs. "did the policy accept it") and a caller that
    wants both already has `structure.diagnostics` available separately.

    `code` is one of `DIAGNOSTIC_CODES` -- stable, closed, meant for
    programmatic branching. `operation_kind`/`operation_index` identify
    *which* operation in a multi-operation `Policy` this belongs to (the
    latter is `0` for a `Diagnostic` built by an operation called directly,
    outside a `Policy`, and is overwritten with the real list position when
    aggregated by `Policy.apply()`). `locator` is `repr()` of the
    operation's own `Locator` -- Structure-owned, never attrs' raw
    `ElementPath` tuples. `site`, when set, is a Structure-owned rendering
    (`_describe_path`) of the one concrete resolved site a wildcard
    operation's failure occurred at -- `None` when the failure isn't
    site-specific (e.g. `Require`, evaluated as a whole).

    Privacy, by construction (docs/architecture/
    S1_3_RESULT_DIAGNOSTIC_DESIGN_CHECKPOINT.md section 15): `message` is a
    short, curated, *code-specific* sentence, never `str(exception)` or an
    exception's own `args`; `cause_type`, when set, is the underlying
    exception's class name only, never the exception object, its message,
    or a callback's input/output. No field here ever carries a raw or
    decoded DICOM element value."""

    code: str
    severity: str  # "error" | "warning" -- kept as a str, not an enum, matching S1.1's own stated reason (room to grow without a breaking change)
    operation_kind: str
    operation_index: int
    locator: str
    site: Optional[str] = None
    message: str = ""
    cause_type: Optional[str] = None


def _diagnostic(code: str, operation_kind: str, locator_repr: str,
                 site: Optional[str] = None, cause_type: Optional[str] = None) -> Diagnostic:
    return Diagnostic(code=code, severity="error", operation_kind=operation_kind, operation_index=0,
                       locator=locator_repr, site=site, message=_DIAGNOSTIC_MESSAGES[code],
                       cause_type=cause_type)


@dataclass(frozen=True)
class OperationResult:
    """The outcome of one operation within one `apply()` call (or of a
    direct `operation.apply(structure)` call -- always `execution=COMPLETED`
    in that case, since a direct call raises rather than returning a
    `FAILED`/`ROLLED_BACK` result; see `ExecutionStatus`).

    `satisfied` is `Optional[bool]` and means *only* "did this operation's
    own condition/guarantee hold" -- `True`/`False` for `require`/`ensure`/
    `ensure_text` (the three operation kinds that have a condition or
    guarantee at all), `None` for every other kind (they have none) *and*
    for any kind when `execution=NOT_EXECUTED` (an unexecuted condition was
    never evaluated -- `execution` is what distinguishes "no condition
    exists" from "a condition exists but wasn't evaluated"; no second field
    is added merely to carry that distinction, per docs/architecture/
    S1_3_RESULT_DIAGNOSTIC_DESIGN_CHECKPOINT.md's own analysis).
    `satisfied` **never** means "executed without error" -- `execution`
    alone answers that.

    `count` is the total number of elements this operation actually,
    durably changed (`0` for a `FAILED`/`ROLLED_BACK`/`NOT_EXECUTED`
    operation -- a rolled-back mutation is not a committed change).
    `updated_count`/`inserted_count` are populated only for `ensure`/
    `ensure_text` (the only kinds that can do both in one call); `None`
    for every other kind, `0`/`0` for a `FAILED`/`ROLLED_BACK`/
    `NOT_EXECUTED` `ensure`/`ensure_text` result specifically. This is a
    deliberately narrow split -- see docs/architecture/
    S1_3_RESULT_DIAGNOSTIC_DESIGN_CHECKPOINT.md section 4/6 for why a
    generalized per-kind effect taxonomy (`removed_count`, `replaced_count`,
    ...) was considered and rejected as over-modeling; `kind` already
    disambiguates what a single `count` means for every other operation.

    `tag` is the locator's leaf tag for every kind that has one (`None` for
    `allow_list_prune`/`private_tag_policy`, which don't target a single
    tag). A malformed locator never produces an `OperationResult` -- it
    raises `MalformedLocatorError` at operation-construction time instead.
    """

    kind: str  # "require" | "remove" | "replace" | "replace_text" | "ensure" | "ensure_text" | "allow_list_prune" | "private_tag_policy"
    tag: Optional[Tag]
    execution: ExecutionStatus
    satisfied: Optional[bool]
    count: int
    updated_count: Optional[int] = None
    inserted_count: Optional[int] = None
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class PolicyResult:
    """The result of `apply(structure, policy)`. Always has exactly
    `len(policy.operations)` entries in `operations`, in the same order,
    regardless of where execution stopped -- an operation that never ran is
    still represented, with `execution=NOT_EXECUTED`, never simply omitted.

    `execution` is the authoritative status (`PolicyExecutionStatus`);
    `decision` is the simpler, pre-existing three/four-value summary (see
    `Decision`'s own docstring for the `PARTIAL` addition and how the two
    fields relate)."""

    decision: Decision
    execution: PolicyExecutionStatus
    operations: tuple[OperationResult, ...]
    diagnostics: tuple[Diagnostic, ...]
    policy_name: str
    policy_version: str

    @property
    def elements_touched(self) -> int:
        """Total elements changed across every non-`require` operation.
        Does not include `require` outcomes, which don't touch the
        structure. A `FAILED`/`ROLLED_BACK`/`NOT_EXECUTED` operation
        contributes `0`, since none of those represent a committed
        change."""
        return sum(r.count for r in self.operations if r.kind != "require")

    @property
    def failed_requirement(self) -> Optional[Tag]:
        """The tag of the first unsatisfied `require`, or None if no
        `require` was unsatisfied (including: the policy contains no
        `require`, every `require` was satisfied, or a `require` never ran
        at all -- `NOT_EXECUTED`'s `satisfied=None` is deliberately not
        treated as "unsatisfied" here, unlike a naive `not result.satisfied`
        check would; see `OperationResult.satisfied`'s own docstring)."""
        for result in self.operations:
            if result.kind == "require" and result.satisfied is False:
                return result.tag
        return None


class PolicyOperation:
    """Base for the five closed operation kinds below. Not meant to be
    subclassed by callers -- see module docstring."""

    def apply(self, structure: "Structure") -> OperationResult:
        raise NotImplementedError


@dataclass(frozen=True)
class Require(PolicyOperation):
    """Rejects the object if `locator` does not resolve to at least one
    match. `locator` accepts a bare tag (normalized to root-level-only
    scope, exactly `__contains__`'s historical behavior), a `TagLocator`
    (e.g. an explicit `recursive=True` to require the tag *anywhere*), or a
    `PathLocator` (a concrete nested occurrence, or a wildcard pattern --
    "at least one Item of this Sequence has this tag").

    Never mutates. Conventionally placed first in a policy's operation
    list, since a `require` later in the list does not undo mutations
    already applied by operations before it (see module docstring, "No
    transactionality")."""

    locator: Union[Tag, TagLocator, PathLocator]

    def __post_init__(self) -> None:
        object.__setattr__(self, "locator", _normalize_locator(self.locator, recursive=False))

    def apply(self, structure: "Structure") -> OperationResult:
        matches = resolve_locator(structure, self.locator)
        satisfied = len(matches) > 0
        diagnostics = ()
        if not satisfied:
            diagnostics = (_diagnostic("REQUIREMENT_UNSATISFIED", "require", repr(self.locator)),)
        return OperationResult(kind="require", tag=_leaf_tag(self.locator),
                                execution=ExecutionStatus.COMPLETED, satisfied=satisfied,
                                count=len(matches), diagnostics=diagnostics)


@dataclass(frozen=True)
class Remove(PolicyOperation):
    """Removes every element `locator` resolves to. `locator` accepts a
    bare tag (normalized via `recursive`, default True -- "anywhere",
    matching pre-S1.1 `erase_recursive`; False -- "root level only",
    matching pre-S1.1 `erase`), a `TagLocator`, or a `PathLocator` (a
    concrete nested occurrence, or a wildcard pattern reaching every
    matching Item). `recursive` is ignored when `locator` is already a
    `TagLocator`/`PathLocator` instance."""

    locator: Union[Tag, TagLocator, PathLocator]
    recursive: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "locator", _normalize_locator(self.locator, self.recursive))

    def apply(self, structure: "Structure") -> OperationResult:
        count = _remove_matches(structure, self.locator)
        return OperationResult(kind="remove", tag=_leaf_tag(self.locator),
                                execution=ExecutionStatus.COMPLETED, satisfied=None, count=count)


@dataclass(frozen=True)
class Replace(PolicyOperation):
    """Replaces the value of every non-sequence element `locator` resolves
    to. `locator` accepts a bare tag (normalized via `recursive`, same
    default/meaning as `Remove`), a `TagLocator`, or a `PathLocator`.

    `value` is either a bytes literal, applied identically to every matched
    occurrence, or a `bytes -> bytes` callback applied to each occurrence's
    own original value independently.

    The callback is refused only for the bare-tag `recursive=True` scope
    (`TagLocator` with `recursive=True`) -- kept exactly as before S1.1: that
    scope's "anywhere, any depth, any shape" semantics have no per-occurrence
    discovery contract independent of a concrete step chain, and changing it
    would break the existing regression test asserting this combination is
    rejected. A `PathLocator` -- concrete or wildcarded -- built from
    explicit steps *does* support a callback in S1.1: pattern expansion
    (S1.1's actual new capability) makes correct callback-per-occurrence
    replacement possible, each callback receiving that occurrence's own
    original bytes (see `_resolve_and_replace`).

    **Operation-atomic as of S1.3** (previously not -- see the module
    docstring and docs/architecture/S1_3_RESULT_DIAGNOSTIC_DESIGN_CHECKPOINT.md
    "Correction 1"): if a callback raises, or a matched value cannot be
    written (`set_value` returning `False`, e.g. too long for the element's
    existing length form -- previously silently under-counted, now a real
    `MUTATION_FAILED` failure, "Correction 2"), every site this call already
    changed is rolled back to its exact original raw bytes before the
    failure propagates. Zero matches remains a successful no-op.
    """

    locator: Union[Tag, TagLocator, PathLocator]
    value: Union[bytes, Callable[[bytes], bytes]]
    recursive: bool = True

    def __post_init__(self) -> None:
        normalized = _normalize_locator(self.locator, self.recursive)
        object.__setattr__(self, "locator", normalized)
        if callable(self.value) and isinstance(normalized, TagLocator) and normalized.recursive:
            raise ValueError(
                "Replace with a bare recursive-scope tag locator does not support a callback "
                "value -- that scope means 'this tag, at any depth, any container shape,' which "
                "this module refuses to combine with a callback (see module docstring). Use "
                "recursive=False, or pass an explicit PathLocator (concrete or wildcard) instead "
                "-- those support a per-occurrence callback, each receiving its own original "
                "value."
            )

    def apply(self, structure: "Structure") -> OperationResult:
        count = _resolve_and_replace(structure, self.locator, self.value)
        return OperationResult(kind="replace", tag=_leaf_tag(self.locator),
                                execution=ExecutionStatus.COMPLETED, satisfied=None, count=count)


def _resolve_and_replace_text(
    structure: "Structure", locator: "Locator",
    values: Union[str, Sequence[str], Callable[[List[str]], Union[str, Sequence[str]]]],
) -> int:
    """Shared by ReplaceText. Charset-aware counterpart to
    `_resolve_and_replace`: resolves matches exactly like `Replace` (never
    an insertion site -- absence is always a no-op, matching `Replace`'s own
    contract), then applies them atomically via `_apply_sites_atomically`.
    A callback receives that occurrence's own `decode_text()` output,
    computed immediately before that occurrence's own `set_text` -- the
    per-occurrence-correctness property `_resolve_and_replace` already
    established, carried over unchanged at the text layer. Charset context
    resolution, encoding, and validation are entirely attrs' `set_text` --
    nothing here inspects or reimplements charset semantics.
    """
    sites = [
        _InsertionSite(parent=path[:-1], tag=_leaf_tag(locator), exists=True, target_path=path)
        for path in resolve_locator(structure, locator)
    ]
    if not sites:
        return 0

    def do_update(structure: "Structure", path: ElementPath) -> None:
        if callable(values):
            try:
                new_values = values(structure.decode_text(path))
            except Exception as exc:
                raise CallbackError(exc) from exc
        else:
            new_values = values
        structure.set_text(path, new_values)

    updated, inserted = _apply_sites_atomically(structure, sites, do_update, do_insert=None)
    return updated + inserted


@dataclass(frozen=True)
class ReplaceText(PolicyOperation):
    """The charset-aware counterpart to `Replace`: replaces the decoded text
    of every existing, non-sequence, text-VR element `locator` resolves to.
    `locator` accepts a bare tag (normalized via `recursive`, same default/
    meaning as `Replace`), a `TagLocator`, or a `PathLocator`.

    `values` is either a literal `str`/`Sequence[str]`, applied identically
    to every matched occurrence via attrs' `set_text` (charset context
    resolution, encoding, and representability validation are entirely
    attrs' -- see module docstring), or a callback receiving that
    occurrence's own `decode_text()` output (a `List[str]`) and returning
    new text, applied per-occurrence exactly like `Replace`'s own callback.

    Same bare-tag `recursive=True` + callback restriction as `Replace`, for
    the identical reason: that scope has no per-occurrence discovery
    contract independent of an explicit step chain.

    A target whose actual VR is not one of the seven Specific-Character-Set-
    governed VRs (including `(0008,0005)` itself, whose VR is `CS`) fails
    with attrs' `NotATextVR` (a plain `FdsError`) -- Structure does not
    special-case any tag, including `(0008,0005)`. **Changing
    `(0008,0005)` does not transcode any other element in the dataset** --
    no such operation exists at any layer of this family; use `Replace`
    (raw bytes) if you need to change the declaration itself, understanding
    that doing so does not re-encode existing text elsewhere.

    Operation-atomic across every resolved match: see `_apply_sites_atomically`
    and `RollbackError`. Zero matches is a successful no-op, exactly like
    `Replace`.
    """

    locator: Union[Tag, TagLocator, PathLocator]
    values: Union[str, Sequence[str], Callable[[List[str]], Union[str, Sequence[str]]]]
    recursive: bool = True

    def __post_init__(self) -> None:
        normalized = _normalize_locator(self.locator, self.recursive)
        object.__setattr__(self, "locator", normalized)
        if callable(self.values) and isinstance(normalized, TagLocator) and normalized.recursive:
            raise ValueError(
                "ReplaceText with a bare recursive-scope tag locator does not support a callback "
                "value -- that scope means 'this tag, at any depth, any container shape,' which "
                "this module refuses to combine with a callback (see module docstring, and "
                "Replace's identical restriction). Use recursive=False, or pass an explicit "
                "PathLocator (concrete or wildcard) instead -- those support a per-occurrence "
                "callback, each receiving its own original decoded text."
            )

    def apply(self, structure: "Structure") -> OperationResult:
        count = _resolve_and_replace_text(structure, self.locator, self.values)
        return OperationResult(kind="replace_text", tag=_leaf_tag(self.locator),
                                execution=ExecutionStatus.COMPLETED, satisfied=None, count=count)


@dataclass(frozen=True)
class Ensure(PolicyOperation):
    """Guarantees `value` is present at `locator`: updates it if the target
    already exists, inserts it if the target is absent but its immediate
    parent container concretely exists, and does nothing (no structural
    ancestor is ever synthesized -- attrs itself has no primitive to create
    a Sequence or Item, see docs/architecture/
    S1_2_REPLACE_ENSURE_DESIGN_CHECKPOINT.md section 25) if no concrete
    insertion site can be established at all.

    Unlike `Remove`/`Replace`, a bare tag's default scope is
    `recursive=False` (root-only) -- **not** `True` -- because insertion has
    no "everywhere" analogue: a `TagLocator(recursive=True)` passed
    explicitly updates every existing occurrence but never inserts (zero
    occurrences is then a genuine no-op, not a root insertion); see the
    design checkpoint section 8 for the full reasoning, deliberately not
    chosen for backward compatibility (`Ensure` is new; there is none to
    preserve).

    `value` must be a `bytes` literal (never a callback/value-factory --
    `Ensure`/`EnsureText` are literal-value-only in S1.2 by design, see the
    design checkpoint section 18). `vr`, if given, is used verbatim for an
    insertion site (ignored for an update site, whose VR is always
    preserved); `vr=None` (default) infers via attrs' own dictionary/
    Private-Creator rules, raising `VRRequiredError` exactly when attrs
    itself would (ambiguous VR, unknown tag, private data element) --
    Structure performs no VR inference of its own.

    Operation-atomic across every resolved insertion site: see
    `_apply_sites_atomically` and `RollbackError`. Zero insertion sites
    (nothing exists and no parent could be established anywhere the
    locator names) reports `satisfied=False` -- the guarantee this
    operation exists to provide could not be established anywhere, which is
    meaningfully different from `Remove`/`Replace`'s "zero matches" no-op.
    """

    locator: Union[Tag, TagLocator, PathLocator]
    value: bytes
    vr: Optional[str] = None
    recursive: bool = False

    def __post_init__(self) -> None:
        if callable(self.value):
            raise ValueError(
                "Ensure does not support a callback/value-factory -- only a literal bytes value "
                "is accepted (see module docstring). Compose Require+Replace(callback) if a "
                "per-occurrence computed value is genuinely needed."
            )
        object.__setattr__(self, "locator", _normalize_locator(self.locator, self.recursive))

    def apply(self, structure: "Structure") -> OperationResult:
        sites = _resolve_insertion_sites(structure, self.locator)
        if not sites:
            diagnostic = _diagnostic("GUARANTEE_UNESTABLISHED", "ensure", repr(self.locator))
            return OperationResult(kind="ensure", tag=_leaf_tag(self.locator),
                                    execution=ExecutionStatus.COMPLETED, satisfied=False, count=0,
                                    updated_count=0, inserted_count=0, diagnostics=(diagnostic,))

        def do_update(structure: "Structure", path: ElementPath) -> None:
            if not structure.set_value(path, self.value):
                raise _MutationFailed(
                    f"set_value returned False for {path!r} -- value likely too long for the "
                    "element's existing length form"
                )

        def do_insert(structure: "Structure", parent: ElementPath, tag: Tag) -> None:
            structure.insert(tag, self.value, vr=self.vr, parent=parent)

        updated, inserted = _apply_sites_atomically(structure, sites, do_update, do_insert)
        return OperationResult(kind="ensure", tag=_leaf_tag(self.locator),
                                execution=ExecutionStatus.COMPLETED, satisfied=True,
                                count=updated + inserted, updated_count=updated, inserted_count=inserted)


@dataclass(frozen=True)
class EnsureText(PolicyOperation):
    """The charset-aware counterpart to `Ensure`: guarantees `values` (a
    literal `str`/`Sequence[str]` -- never a callback, same restriction as
    `Ensure`) is present as decoded text at `locator`. Same insertion-site
    semantics as `Ensure` (same root-only bare-tag default, same "no
    structural ancestor synthesis" rule, same atomicity).

    The update branch calls attrs' `set_text` (charset context resolved at
    the target element, per A1.5/A1.6, unchanged and unreimplemented here);
    the insert branch calls attrs' `insert_text` (charset context resolved
    at the *parent container*, since the target does not yet exist -- the
    freeze-critical A1.7 distinction this module relies on directly rather
    than re-solving, see the design checkpoint section 14). `vr=None`
    (default) infers exactly as `Ensure` does. A target/insertion site whose
    VR is not text-governed (including `(0008,0005)`) fails with attrs'
    `NotATextVR` -- no special-casing, no dataset transcode, same boundary
    documented on `ReplaceText`.
    """

    locator: Union[Tag, TagLocator, PathLocator]
    values: Union[str, Sequence[str]]
    vr: Optional[str] = None
    recursive: bool = False

    def __post_init__(self) -> None:
        if callable(self.values):
            raise ValueError(
                "EnsureText does not support a callback/value-factory -- only a literal str or "
                "sequence of str is accepted (see module docstring)."
            )
        object.__setattr__(self, "locator", _normalize_locator(self.locator, self.recursive))

    def apply(self, structure: "Structure") -> OperationResult:
        sites = _resolve_insertion_sites(structure, self.locator)
        if not sites:
            diagnostic = _diagnostic("GUARANTEE_UNESTABLISHED", "ensure_text", repr(self.locator))
            return OperationResult(kind="ensure_text", tag=_leaf_tag(self.locator),
                                    execution=ExecutionStatus.COMPLETED, satisfied=False, count=0,
                                    updated_count=0, inserted_count=0, diagnostics=(diagnostic,))

        def do_update(structure: "Structure", path: ElementPath) -> None:
            structure.set_text(path, self.values)

        def do_insert(structure: "Structure", parent: ElementPath, tag: Tag) -> None:
            structure.insert_text(tag, self.values, vr=self.vr, parent=parent)

        updated, inserted = _apply_sites_atomically(structure, sites, do_update, do_insert)
        return OperationResult(kind="ensure_text", tag=_leaf_tag(self.locator),
                                execution=ExecutionStatus.COMPLETED, satisfied=True,
                                count=updated + inserted, updated_count=updated, inserted_count=inserted)


@dataclass(frozen=True)
class AllowListPrune(PolicyOperation):
    """Removes every element whose tag is not in `tags`, at every nesting
    depth. If a sequence container's own tag is excluded, the whole
    sequence (and everything nested inside it) is removed in one step.

    `Structure` exposes no single primitive for "prune by tag set" -- this
    walks the structure once, via `Structure.iter_elements(recursive=True)`
    (the frozen attrs A1.7 primitive; this operation no longer hand-rolls
    its own traversal), to find which tags are present anywhere, then
    reuses the same `_remove_matches` engine `Remove` uses -- one
    `TagLocator(tag, recursive=True)` per disallowed tag found, in sorted
    order.

    This operation says nothing about File Meta Information (group 0002):
    those elements are ordinary top-level elements in this library's model,
    so an allow-list that omits them will remove them like any other
    unlisted tag. Producing output that still reparses as valid DICOM is
    the caller's responsibility -- include the File Meta tags you need in
    the allow-list.
    """

    tags: tuple[Tag, ...]

    def apply(self, structure: "Structure") -> OperationResult:
        allowed = set(self.tags)
        present = {element.tag for element, _ in structure.iter_elements(recursive=True)}
        removed = 0
        for tag in sorted(present - allowed):
            removed += _remove_matches(structure, TagLocator(tag=tag, recursive=True))
        return OperationResult(kind="allow_list_prune", tag=None,
                                execution=ExecutionStatus.COMPLETED, satisfied=None, count=removed)


@dataclass(frozen=True)
class PrivateTagPolicy(PolicyOperation):
    """Removes every private element (odd group number), at every nesting
    depth, via the existing `erase_private`. `remove=False` is a no-op,
    kept only so a policy can express "private tags: leave alone" instead
    of omitting the operation.

    Not locator-capable in S1.1 by design -- it is a blanket flag, not a
    tag-targeted operation, and the brief explicitly excludes expanding
    creator-aware behavior this increment. Deliberately does not support an
    allowlist of private tags to keep; that remains blocked on attrs
    exposing `resolve_private_creator` to Python (S1.6, conditional).
    """

    remove: bool = True

    def apply(self, structure: "Structure") -> OperationResult:
        count = structure.erase_private() if self.remove else 0
        return OperationResult(kind="private_tag_policy", tag=None,
                                execution=ExecutionStatus.COMPLETED, satisfied=None, count=count)


@dataclass(frozen=True)
class Policy:
    """An ordered, named, versioned list of operations. Order matters:
    `apply()` executes operations strictly in list order and stops at the
    first unsatisfied `require` or the first caught operation failure (see
    module docstring, "No transactionality across operations")."""

    name: str
    version: str
    operations: tuple[PolicyOperation, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "operations", tuple(self.operations))


_OPERATION_KIND = {
    Require: "require",
    Remove: "remove",
    Replace: "replace",
    ReplaceText: "replace_text",
    Ensure: "ensure",
    EnsureText: "ensure_text",
    AllowListPrune: "allow_list_prune",
    PrivateTagPolicy: "private_tag_policy",
}

_ENSURE_KINDS = ("ensure", "ensure_text")


def _operation_tag(operation: PolicyOperation) -> Optional[Tag]:
    locator = getattr(operation, "locator", None)
    return _leaf_tag(locator) if locator is not None else None


def _operation_locator_repr(operation: PolicyOperation) -> str:
    locator = getattr(operation, "locator", None)
    return repr(locator) if locator is not None else repr(operation)


def _not_executed_result(operation: PolicyOperation) -> OperationResult:
    """Built by `apply()` for every operation after the one that caused a
    `Policy` to stop early (an unsatisfied `require` or a caught failure).
    Only fields whose meaning is knowable *without* running the operation
    are populated: `count`/`updated_count`/`inserted_count` are `0` (nothing
    happened); `satisfied` is `None` -- not `False` -- because an
    unexecuted condition was never evaluated, a distinction `execution=
    NOT_EXECUTED` itself supplies (see `OperationResult.satisfied`'s
    docstring)."""
    kind = _OPERATION_KIND[type(operation)]
    is_ensure = kind in _ENSURE_KINDS
    return OperationResult(kind=kind, tag=_operation_tag(operation),
                            execution=ExecutionStatus.NOT_EXECUTED, satisfied=None, count=0,
                            updated_count=0 if is_ensure else None,
                            inserted_count=0 if is_ensure else None)


def _with_operation_index(result: OperationResult, index: int) -> OperationResult:
    """Patches every `Diagnostic.operation_index` in `result` to `index` --
    the operation's real position in `Policy.operations`. An operation's own
    `apply()` cannot know this (it has no view of the containing `Policy`),
    so it builds any `Diagnostic` with `operation_index=0`; `Policy.apply()`
    corrects it here when aggregating. A no-op for a result with no
    diagnostics (the common case)."""
    if not result.diagnostics:
        return result
    return replace(result, diagnostics=tuple(replace(d, operation_index=index)
                                              for d in result.diagnostics))


def _classify_exception(exc: BaseException) -> Optional[str]:
    """Returns the `Diagnostic.code` for a known, modeled policy-execution
    failure, or `None` if `exc` is not one of the closed set `Policy.apply`
    converts into a structured result. `RollbackError` and anything not
    recognized here propagate raw -- see `apply()`'s own docstring,
    "Exception boundary". Order matters: attrs' `VRRequiredError`/
    `AlreadyExistsError`/`UnrepresentableCharacterError`/
    `InvalidUnicodeInputError` are all subclasses of `FdsError`, so each is
    checked before the generic `FdsError` fallback."""
    if isinstance(exc, VRRequiredError):
        return "VR_REQUIRED"
    if isinstance(exc, AlreadyExistsError):
        return "ALREADY_EXISTS"
    if isinstance(exc, UnrepresentableCharacterError):
        return "CHARACTER_UNREPRESENTABLE"
    if isinstance(exc, InvalidUnicodeInputError):
        return "INVALID_UNICODE"
    if isinstance(exc, CallbackError):
        return "CALLBACK_FAILED"
    if isinstance(exc, _MutationFailed):
        return "MUTATION_FAILED"
    if isinstance(exc, FdsError):
        # NotATextVR/UnsupportedCharset/MalformedCharsetDeclaration all map
        # to this one generic attrs status/exception -- a real attrs
        # Python-binding precision limit (verified: all three collapse to
        # FDS_STATUS_UNSUPPORTED), not an S1.3 shortcut. See docs/architecture/
        # S1_3_RESULT_DIAGNOSTIC_DESIGN_CHECKPOINT.md section 8/28 and the
        # S1.3 implementation report's own "Defects/limitations" section.
        return "TEXT_OPERATION_UNSUPPORTED"
    return None


def _build_policy_result(policy: Policy, op_results: list, execution: PolicyExecutionStatus,
                          decision: Decision) -> PolicyResult:
    diagnostics = tuple(d for r in op_results for d in r.diagnostics)
    return PolicyResult(decision=decision, execution=execution, operations=tuple(op_results),
                         diagnostics=diagnostics, policy_name=policy.name,
                         policy_version=policy.version)


def apply(structure: "Structure", policy: Policy) -> PolicyResult:
    """Evaluates and applies `policy` to `structure` in place, in operation
    order. Always returns exactly `len(policy.operations)` `OperationResult`
    entries, in order -- an operation that never ran is represented with
    `execution=NOT_EXECUTED`, never simply omitted.

    Stops early in two cases, both producing a full `PolicyResult` (never an
    empty/partial one, and never raising for either case):

    - An unsatisfied `require` -> `execution=PolicyExecutionStatus.REJECTED`,
      `decision=Decision.REJECT` (unchanged from S1.1/S1.2).
    - `Policy.apply()` catches a *known* operation failure (see "Exception
      boundary" below) -> `execution=PolicyExecutionStatus.PARTIAL`,
      `decision=Decision.PARTIAL`. Every operation that already ran remains
      exactly as it left the structure -- there is no whole-policy rollback
      (see the module docstring, "No transactionality across operations");
      only the *failing* operation's own sites (if any were mutated) are
      rolled back, by the same operation-level atomicity `Ensure`/
      `EnsureText`/`Replace`/`ReplaceText` already guarantee.

    Otherwise every operation runs to completion and
    `execution=PolicyExecutionStatus.COMPLETED`, with `decision` computed
    exactly as before (`TRANSFORM` if anything changed, else `ACCEPT`).

    **Exception boundary.** Never `except Exception` (see docs/architecture/
    S1_3_RESULT_DIAGNOSTIC_DESIGN_CHECKPOINT.md section 9 for why a blanket
    catch was rejected). Only exceptions `_classify_exception` recognizes --
    attrs' `VRRequiredError`/`AlreadyExistsError`/`UnrepresentableCharacterError`/
    `InvalidUnicodeInputError`, the generic `FdsError` (covering
    `NotATextVR`/`UnsupportedCharset`/`MalformedCharsetDeclaration`), the
    internal `_MutationFailed` marker, and `CallbackError` -- are converted
    into a `FAILED`/`ROLLED_BACK` `OperationResult` plus a matching
    `Diagnostic`. **`RollbackError` is never caught here and always
    propagates raw**: it means the one guarantee this whole design leans on
    (operation-level atomicity) itself could not be maintained, and the
    dataset may be in an uncertain state for the specific paths named in
    `RollbackError.failed_undo_actions` -- converting it into a
    routine-looking `PolicyResult` would actively mislead a caller into
    thinking the dataset is in a known, safe state. Any exception not in the
    named set (a genuine bug, or a future attrs exception type this module
    doesn't yet know about) also propagates raw, for the same reason: an
    unanticipated failure must never be made to look like a modeled,
    understood outcome. A `MalformedLocatorError` can never reach this
    boundary at all -- it is raised at *operation construction*, before a
    `Policy` exists to catch it.
    """
    op_results: list[OperationResult] = []

    for index, operation in enumerate(policy.operations):
        try:
            result = operation.apply(structure)
        except RollbackError:
            raise
        except Exception as exc:
            code = _classify_exception(exc)
            if code is None:
                raise
            kind = _OPERATION_KIND[type(operation)]
            rolled_back = getattr(exc, "_fds_policy_rolled_back", False)
            execution_status = ExecutionStatus.ROLLED_BACK if rolled_back else ExecutionStatus.FAILED
            site = getattr(exc, "_fds_policy_failed_site", None)
            # For a CallbackError, cause_type names the ORIGINAL callback
            # exception's class (e.g. "ValueError"), never "CallbackError"
            # itself -- CallbackError is this module's own wrapper, not the
            # cause a caller would want to see.
            cause_type = exc.cause_type if isinstance(exc, CallbackError) else type(exc).__name__
            diagnostic = replace(
                _diagnostic(code, kind, _operation_locator_repr(operation), site=site,
                            cause_type=cause_type),
                operation_index=index,
            )
            is_ensure = kind in _ENSURE_KINDS
            failed_result = OperationResult(
                kind=kind, tag=_operation_tag(operation), execution=execution_status, satisfied=None,
                count=0, updated_count=0 if is_ensure else None, inserted_count=0 if is_ensure else None,
                diagnostics=(diagnostic,),
            )
            op_results.append(failed_result)
            for remaining_op in policy.operations[index + 1:]:
                op_results.append(_not_executed_result(remaining_op))
            return _build_policy_result(policy, op_results, PolicyExecutionStatus.PARTIAL,
                                         Decision.PARTIAL)

        result = _with_operation_index(result, index)
        op_results.append(result)
        if isinstance(operation, Require) and result.satisfied is False:
            for remaining_op in policy.operations[index + 1:]:
                op_results.append(_not_executed_result(remaining_op))
            return _build_policy_result(policy, op_results, PolicyExecutionStatus.REJECTED,
                                         Decision.REJECT)

    touched = sum(r.count for r in op_results if r.kind != "require")
    decision = Decision.TRANSFORM if touched > 0 else Decision.ACCEPT
    return _build_policy_result(policy, op_results, PolicyExecutionStatus.COMPLETED, decision)
