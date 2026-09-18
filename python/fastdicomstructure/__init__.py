"""fastDICOMstructure: traversal, policy evaluation, and orchestration on top
of fastDICOMattrs' DICOM attribute-semantics engine.

As of the A0 semantic-engine extraction (see
docs/architecture/ADR-001-ATTRS-NAMING-AND-LAYERING.md in fastDICOMattrs),
this repository no longer implements DICOM parsing, mutation, or
serialization itself -- that engine, including the parser, object model,
writer, C ABI, and this exact Python read/inspect/mutate/write surface,
moved to fastDICOMattrs with its git history. This module is a thin
re-export of that surface, plus this repository's own policy layer
(`policy`).

`Structure.apply(policy)` no longer exists -- it was a policy-shaped hook on
what is now fastDICOMattrs' public class, removed because attrs must not be
aware of policy as a concept, even via a one-line delegation. Call
`policy.apply(structure, policy)` instead (see the `policy` module below);
the underlying behavior is unchanged.

fastDICOMattrs is located the same way fastDICOMgateway locates this
repository: a sibling checkout, found via FASTDICOMATTRS_REPO or the default
sibling-directory convention, with its own compiled shared library resolved
relative to that checkout by fastdicomattrs' own path-search logic.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _add_fastdicomattrs_to_path() -> None:
    """Makes the sibling fastDICOMattrs checkout's Python package importable
    without vendoring its implementation into this repository. Mirrors
    fastDICOMgateway's transform.py `_add_fastdicomstructure_to_path` --
    same convention, one level down the dependency chain.
    """
    default_repo = Path(__file__).resolve().parents[3] / "fastDICOMattrs"
    repo = Path(os.environ.get("FASTDICOMATTRS_REPO", default_repo))
    python_dir = repo / "python"
    if str(python_dir) not in sys.path:
        sys.path.insert(0, str(python_dir))


_add_fastdicomattrs_to_path()

from fastdicomattrs import (  # noqa: E402 -- path must be set up first
    read,
    read_buffer,
    Structure,
    Element,
    Item,
    Diagnostic,
    FdsError,
    StaleElementError,
    WriteStats,
)
from . import policy  # noqa: E402
from . import configuration  # noqa: E402
from . import execution  # noqa: E402
from . import adapters  # noqa: E402

__all__ = ["read", "read_buffer", "Structure", "Element", "Item", "Diagnostic", "FdsError",
           "StaleElementError", "WriteStats", "policy", "configuration", "execution", "adapters"]
