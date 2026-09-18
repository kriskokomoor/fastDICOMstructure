# fastDICOMstructure

**Policy evaluation and orchestration on top of `fastDICOMattrs`.**

> [!IMPORTANT]
> As of the A0 semantic-engine extraction, this repository no longer contains a DICOM parser,
> object model, or writer. That engine — including this exact read/inspect/mutate/write Python
> API — moved to [`fastDICOMattrs`](https://github.com/kriskokomoor/fastDICOMattrs), with its git
> history, because it implements DICOM attribute *semantics*, which is that repository's job, not
> this one's. See `docs/architecture/ADR-001-ATTRS-NAMING-AND-LAYERING.md` in `fastDICOMattrs` for
> the full reasoning, and this repository's own `docs/architecture.md` for what remains here.

`fastDICOMstructure` decides *what* to do with a DICOM object and *why* — policy evaluation,
traversal, and orchestration — using `fastDICOMattrs` for everything about *how DICOM encoding
works*. It owns no parsing, VR resolution, mutation mechanics, or serialization logic of its own.

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

## What's here

- **`python/fastdicomstructure/policy.py`** — a minimal, deterministic accept/transform/reject
  layer: `Require`, `Remove`, `Replace`, `AllowListPrune`, `PrivateTagPolicy` operations, composed
  into a named, versioned `Policy` and executed by `apply(structure, policy)`. Owns no policy
  *content* (no pseudonymization, UID remapping, date shifting, or data dictionary) — see the
  module's own docstring for the concrete design choices and limitations.
- **`python/fastdicomstructure/__init__.py`** — re-exports `fastdicomattrs`'s public API
  (`read`, `read_buffer`, `Structure`, `Element`, `Item`, `Diagnostic`, `FdsError`,
  `StaleElementError`, `WriteStats`) so existing code that does `import fastdicomstructure as fds`
  keeps working.
- **`python/examples/pipeline_demo.py`** — a runnable minimal pre-persistence ingestion pipeline,
  applying a fixed transformation policy end to end against a synthetic DICOM object, using
  `fastDICOMattrs`'s primitives directly.
- **`tests/python/`** — `test_policy.py` (the policy layer) and `test_pipeline_demo.py` (the demo
  pipeline).

## Prerequisites

A checkout of [`fastDICOMattrs`](https://github.com/kriskokomoor/fastDICOMattrs), built per that
repository's own README (its compiled shared library must exist under its `build/` directory, or
`FASTDICOMATTRS_LIB` must point at it directly). This repository locates it via the
`FASTDICOMATTRS_REPO` environment variable, **defaulting to a `fastDICOMattrs` directory next to
this one** — a true sibling checkout needs no environment variable at all, which is also what
`fastDICOMgateway` assumes one level up this same dependency chain.

## Getting started: an external clean install

This is the exact sequence verified (during release preparation) to work from a fresh checkout
outside any existing development layout — only the two directory names need to be true siblings:

```sh
# 1. fastDICOMattrs, pinned to the release compatible with this checkout, built without its
#    C++ test suite (Catch2 3 is a separate prerequisite only needed for that suite -- see
#    its own README). Use the latest public release tag from
#    https://github.com/kriskokomoor/fastDICOMattrs/releases ; the exact compatible release
#    is also identified by content in this repository's RELEASE_PROVENANCE.md.
git clone https://github.com/kriskokomoor/fastDICOMattrs.git
git -C fastDICOMattrs checkout <fastDICOMattrs release tag -- see RELEASE_PROVENANCE.md>
cmake -S fastDICOMattrs -B fastDICOMattrs/build -DCMAKE_BUILD_TYPE=Release -DFDS_BUILD_TESTS=OFF
cmake --build fastDICOMattrs/build --parallel

# 2. fastDICOMstructure, as a true sibling of the directory above (cloning already checks
#    out this repository's current commit -- no separate checkout needed):
git clone https://github.com/kriskokomoor/fastDICOMstructure.git

# 3. Test dependencies (fastDICOMstructure itself has no runtime dependency of its own):
python3 -m pip install pytest pydicom

# 4. Smoke check -- runs a declarative JSON policy through the real CLI against a synthetic
#    DICOM object, then independently reads the result back with the library itself:
cd fastDICOMstructure
PYTHONPATH=python python3 python/examples/run_json_policy_example.py
```

No `FASTDICOMATTRS_REPO` override is needed above because the two checkouts are true siblings; set
it (to an absolute path) if you keep them elsewhere.

## Test

```sh
python3 -m pytest tests/python -v
```

or, without pytest:

```sh
PYTHONPATH=python python3 -m unittest discover -s tests/python -v
```

The container-qualification tests in `tests/python/test_container.py` additionally require Docker
and a locally built `fastdicomstructure:s1.7` image (see `Dockerfile`); they skip individually,
not as a suite failure, when either is unavailable.

## Examples

```sh
# Hand-coded Python policy against a synthetic object:
PYTHONPATH=python python3 python/examples/pipeline_demo.py

# Declarative JSON policy (Configuration V1), run through the actual CLI:
PYTHONPATH=python python3 python/examples/run_json_policy_example.py
```

Neither example is a de-identification product; both use synthetic, in-code-built DICOM data only.

## Family

See [`fastDICOMattrs`'s README](https://github.com/kriskokomoor/fastDICOMattrs#fastdicom-family)
for the current position of every project in the `fastDICOM` family, including
`fastDICOMscan` (the independent, DCMTK-backed shallow probe formerly published under the name
`fastDICOMattrs` — renamed at the A0 extraction to free that name for the promoted engine; not a
dependency of this repository).

## Original research charter

`initial_requirements.txt` in this repository predates the `fastDICOMattrs`/`fastDICOMstructure`
split and the A0 extraction; it is retained as historical record of the original, broader charter
this family grew from, not as a current scope statement.

## Contributing

Bug reports and pull requests are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and run
the test suite before submitting a change.

## License

This project is released into the public domain under [The Unlicense](LICENSE).
