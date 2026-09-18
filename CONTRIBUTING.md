# Contributing to fastDICOMstructure

Bug reports, focused feature proposals, documentation improvements, and pull requests are welcome.

## Before opening a change

Please open an issue before undertaking a large API or architecture change. Keep the public API compatible where practical, preserve unknown DICOM content, and include tests for behavior changes. Never commit clinical DICOM data or protected health information; test fixtures must be synthetic or explicitly license-cleared.

## Build and test

This repository is a pure-Python policy/orchestration layer as of the A0 semantic-engine
extraction (see `fastDICOMattrs`' `docs/architecture/ADR-001-ATTRS-NAMING-AND-LAYERING.md`) — it
has no C++ or `CMakeLists.txt` of its own to build. It needs a built `fastDICOMattrs` checkout
(the compiled shared library, loaded via `ctypes`) at test time. See this repository's own
README ("Getting started") for the exact clone/build sequence; in short:

```sh
# fastDICOMattrs, built as a sibling checkout (or set FASTDICOMATTRS_REPO to its location).
# Use the release tag identified in this repository's RELEASE_PROVENANCE.md:
git -C ../fastDICOMattrs checkout <fastDICOMattrs release tag -- see RELEASE_PROVENANCE.md>
cmake -S ../fastDICOMattrs -B ../fastDICOMattrs/build -DCMAKE_BUILD_TYPE=Release
cmake --build ../fastDICOMattrs/build --parallel

pip install pytest
PYTHONPATH=python python3 -m pytest tests/python -v
```

Pull requests should explain the motivation, user-visible behavior, limitations, and test coverage. Update the relevant design contract under `docs/` when changing parsing, ownership, ABI, or round-trip behavior.

Corpus probing against a real DICOM corpus is `fastDICOMattrs`' feature (`python -m fastdicomattrs.corpus`, see that repository's own README and `docs/corpus-results.md`), not this one's -- this repository has no corpus-probing tool of its own.

## License

By contributing, you agree to dedicate your contribution to the public domain under the terms in `LICENSE`.
