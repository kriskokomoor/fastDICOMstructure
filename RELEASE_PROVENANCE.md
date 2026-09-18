# Release provenance

This public source tree was constructed from an internally qualified research/development
repository's release candidate. That internal repository is not public, and this repository
shares no Git history, commits, or objects with it.

- **Internal qualification identifier:** `97ab708d87cf7cd9740d4f92c93b60f52291c5e9`. This is a
  reference label for the internal repository's own record-keeping — it is **not a commit
  reachable in this repository**, and no attempt to resolve it here will succeed.
- **Content equivalence:** the qualified internal source tree's deterministic software-tree
  manifest hashes to `dd52bfda7b543c7030e376a0463b332349e8368fe4716a9fb15d78af3c6337a5`. See
  `PUBLICATION_BOUNDARY_TRANSFORMATIONS.md` for the complete, explicit list of publication-only
  changes between that tree and this one.
- **Compatible `fastDICOMattrs` release:** this checkout was qualified against fastDICOMattrs'
  internal candidate `24efab8a5fecc159ca88f1ad94e03b0d5dee2c61` (public software-tree manifest
  `025be34e9124582f0ff40455aeefb02a1753da42e2fe3a9acc4e04e3f7814b16`). Use the fastDICOMattrs
  public release whose own `RELEASE_PROVENANCE.md` cites that same manifest hash, or the latest
  release if none is yet tagged with it explicitly.
- **What is intentionally not included:** the internal repository's commit history, its earlier
  (superseded) states, and any local development-machine detail — including the personal Git
  author identity used internally, which this document's own §8 (see
  `docs/release/PUBLIC_REPOSITORY_HISTORY_AND_PROVENANCE.md`) discusses without reproducing it.
