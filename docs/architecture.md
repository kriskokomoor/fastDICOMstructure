# fastDICOMstructure — Architecture

> This document replaces the pre-A0 version of itself, which described a fused parser + writer +
> policy engine. That content now lives in `fastDICOMattrs`'s own `docs/architecture.md`
> (git history preserved across the move — see that repository's
> `docs/architecture/A0_EXTRACTION_MANIFEST.md`). This document describes only what remains here.

## What this repository owns

`fastDICOMstructure` owns policy evaluation, traversal, and orchestration over a DICOM object —
*deciding what to do with it and why*, never *how DICOM encoding works*. It depends on
`fastDICOMattrs` for every question about DICOM semantics: parsing, tag/VR identification, value
access, mutation, and serialization.

```text
fastDICOMgateway
        |
        v
fastDICOMstructure   <- this repository
        |
        v
fastDICOMattrs
        |
   raw DICOM bytes
```

## Contents

- **`python/fastdicomstructure/__init__.py`** — a thin re-export of `fastdicomattrs`'s public
  Python surface (`read`, `read_buffer`, `Structure`, `Element`, `Item`, `Diagnostic`, `FdsError`,
  `StaleElementError`, `WriteStats`), plus this package's own `policy` submodule. It exists so
  existing consumers (`fastDICOMgateway`'s `import fastdicomstructure as fds`) keep working
  unchanged; see its module docstring for the compatibility rationale and removal considerations.
- **`python/fastdicomstructure/policy.py`** — the policy layer: `Require`, `Remove`, `Replace`,
  `AllowListPrune`, `PrivateTagPolicy` operations, composed into a named, versioned `Policy` and
  executed by `apply(structure, policy)` against any object exposing `fastdicomattrs.Structure`'s
  read/mutate primitives. Unchanged by the A0 extraction — it never imported `Structure` at
  runtime (only under `TYPE_CHECKING`), so no code here needed to change for the boundary to
  become real. Its own module docstring documents the design choices and known limitations (a
  closed operation set, no policy *content* such as pseudonymization or UID remapping, no
  transactionality across a policy's operations).
- **`python/examples/pipeline_demo.py`** — a runnable minimal ingestion-pipeline demo. Stays here,
  not in `fastDICOMattrs`, because it embeds a fixed transformation policy (remove `PatientName`,
  hash `PatientID`, remove private elements) — a decision about *what* to change, which is this
  repository's concern. It calls `fastdicomattrs`' mutation/write primitives directly (via the
  `fastdicomstructure` re-export), not through `policy.py`'s `Policy`/`apply` abstraction; both
  are legitimate ways to build a decision pipeline on top of `fastDICOMattrs`.
- **`tests/python/test_policy.py`** — the policy layer's own tests. One mechanical adaptation was
  required at the A0 extraction: `structure.apply(pol)` → `policy.apply(structure, pol)`, because
  the one-line `Structure.apply()` convenience method was removed from the promoted
  `fastDICOMattrs` engine (a policy-shaped hook on an attrs-owned class, which the architecture
  does not permit even as a stub). No assertion, fixture, or test outcome changed.
- **`tests/python/test_pipeline_demo.py`** — tests `pipeline_demo.py` above.

## Why this repository no longer has a C++ build

Nothing remaining here requires compilation. The parser, object model, mutation primitives, and
writer are `fastDICOMattrs`'s responsibility; this repository consumes them entirely through its
Python bindings. See `fastDICOMattrs`'s own `docs/architecture.md`, `docs/api-design.md`, and
`docs/abi-design.md` for that engine's design.

## Dependency mechanism

`fastDICOMattrs` is located as a sibling checkout, same convention `fastDICOMgateway` already used
one level up: `FASTDICOMATTRS_REPO` environment variable, defaulting to a `fastDICOMattrs`
directory next to this one. See `python/fastdicomstructure/__init__.py`'s
`_add_fastdicomattrs_to_path`.
