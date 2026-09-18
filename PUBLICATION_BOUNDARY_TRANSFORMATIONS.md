# Publication-boundary transformations — fastDICOMstructure

Derived from internally qualified commit `97ab708d87cf7cd9740d4f92c93b60f52291c5e9`
(qualified software-tree manifest SHA-256 `dd52bfda7b543c7030e376a0463b332349e8368fe4716a9fb15d78af3c6337a5`).

| Path | Category | Reason | Executable semantics changed? |
|---|---|---|---|
| `docs/release/PUBLIC_REPOSITORY_HISTORY_AND_PROVENANCE.md` | A — personal-identity removal | §8 named the maintainer's literal personal email while explaining why it must not become public. Reworded to preserve the meaning (a personal identity exists locally and is being kept out of public history) without reproducing the literal address. | No — documentation only. |
| `README.md` | B — public dependency identity reconciliation | The external-install quickstart pinned `git -C fastDICOMattrs checkout 24efab8a5fecc159ca88f1ad94e03b0d5dee2c61`, an internal-only identifier not resolvable in a public attrs repository. Replaced with an explicit placeholder pointing at the public attrs release tag and this repository's own `RELEASE_PROVENANCE.md`. | No — documentation only; the placeholder is not a runnable command as written and is clearly marked as such. |
| `CONTRIBUTING.md` | B — public dependency identity reconciliation | Same issue, same fix, in the contributor build instructions. | No. |
| `.github/workflows/ci.yml` | D — public-facing CI correction | The `Checkout fastDICOMattrs` step pinned `ref: 24efab8...`, an internal-only identifier. Removed the pin (falls back to attrs' default branch) and added an explicit `TODO(release)` comment to pin an exact public release tag once one exists. This is the smallest change that keeps CI syntactically and operationally valid without referencing a non-public identifier or inventing a version that does not exist yet. No other CI step, job, or behavior was touched. | No — the checkout step's target changed from "one specific historical commit" to "attrs' current default branch tip"; the *test logic that runs afterward* is unchanged. This trades determinism for public-resolvability until a real tag exists, which is the accepted tradeoff `PUBLIC_REPOSITORY_HISTORY_AND_PROVENANCE.md` §15/C already anticipated. |
| `RELEASE_PROVENANCE.md` | C — public provenance document | New file; explains internal→public relationship and content-equivalence proof. | No. |
| `PUBLICATION_BOUNDARY_TRANSFORMATIONS.md` (this file) | C — public provenance document | Records this exact transformation set. | No. |

No DICOM policy, execution, configuration, adapter, or CLI semantic was touched. No test file was
touched. No production package file (`python/fastdicomstructure/*.py`) was touched.
