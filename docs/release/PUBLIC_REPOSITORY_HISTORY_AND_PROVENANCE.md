# Public repository history and provenance

Operational design for turning a qualified internal release tree into a clean public Git
repository. Experimentally qualified against `fastDICOMattrs` candidate
`24efab8a5fecc159ca88f1ad94e03b0d5dee2c61` in a disposable scratch location. **No public
repository has been created, pushed, or published. No authoritative repository was modified.**

## 1. Purpose

The three private repositories (`fastDICOMattrs`, `fastDICOMstructure`, `fastDICOMgateway`) are
authoritative research/development history: frozen A/S-series freeze commits, experimental
evidence, and — inevitably — the author's personal git identity and, historically, a vendored
third-party artifact no longer eligible for redistribution (see `THIRD_PARTY_NOTICES.md`). None of
that should be rewritten, and none of it should be published. This document defines how a public
repository is produced *from* that history without *containing* that history.

## 2. Problem statement

Cloning or otherwise carrying forward the private `.git` object database — then deleting sensitive
files from a working copy — does not remove them from the object database or reflog; the personal
email and the historical `PS3.6.xml` blob would remain permanently recoverable from any full clone.
Rewriting the private history (filter-repo, rebase, squash) was separately ruled out because it
would invalidate frozen commit SHAs that existing reports and evidence cite by hash. The only
approach that satisfies both constraints is: never construct the public repository from the private
one's object database at all.

## 3. Internal vs. public repository roles

| | Private (internal) | Public (release) |
|---|---|---|
| Contains | Complete history, all frozen A/S-series commits, all experiments/reports | One qualified tree, plus a small number of public-only provenance/release commits |
| Author identity | The real developer identity (as it has always been) | An owner-supplied public identity (§8) |
| Authoritative for | The experiments and freeze reports that cite its commit SHAs | The distributable source a public consumer builds from |
| Changed by this design | Never | Created fresh from a snapshot of the private repo's qualified tree |

The public repository does not replace or invalidate the private one. A private frozen SHA (e.g.
`46bf7d3`) remains the authoritative reference for the experiment that froze it, forever — nothing
about publishing a derived public tree changes that.

## 4. Selected model

> The private repository remains the authoritative provenance/evidence repository. A public
> repository is initialized independently from the exact qualified release tree, with a new
> public root commit and no Git ancestry connecting it to the private repository.

This was tested and holds. Four identities stay explicitly distinct — conflating any two of them is
the design mistake this whole exercise exists to avoid:

- **Internal provenance identity** — the private qualified commit SHA (e.g. `24efab8...`).
  Resolvable only inside the private repository. Never a public Git ancestor.
- **Public source identity** — the new public repository's own root commit SHA (e.g. `57699c9...`
  in this qualification run). Exists only after the public commit is created; not knowable, and not
  needed, beforehand.
- **Source-tree identity** — a deterministic content fingerprint connecting the two without either
  needing to reference the other's commit SHA. Solved git-natively (§6).
- **Release identity** — an eventual version tag (e.g. `v0.1.0`), created after the public commit
  exists, and the identity real consumers should actually depend on (§10).

Commit-SHA equality across the boundary is neither necessary nor meaningful (the two repositories
have unrelated commit graphs and, in general, different content once public-only files like a
provenance statement are added) — only tree-content equivalence for the qualified files matters,
and that is exactly what was verified.

## 5. Export procedure (selected: `git archive`)

```sh
git archive --format=tar <qualified-commit> | tar -x -C <clean-empty-scratch-dir>
```

Chosen over "checkout + copy excluding `.git`" because `git archive` reads only from the commit's
tree object in the Git object database — it cannot pick up untracked or `.gitignore`d files
regardless of what happens to be sitting in a working directory, and it never touches `.git/`
because there is nothing to exclude in the first place. This removes an entire class of "the
maintainer's working tree had something extra lying around" mistakes that a filesystem copy is
vulnerable to.

Verified for `24efab8`: 135 files extracted; independently re-derived tree SHA
(`git rev-parse 24efab8^{tree}` = `1d9e61f5744e7f60c19f33a26a43b40d71ccec77`) is what the
initialization step must reproduce exactly (§6).

## 6. Public initialization procedure

```sh
# 1. export (§5)
git archive --format=tar <qualified-commit> | tar -x -C <export-dir>

# 2. independent, fresh object database
cd <export-dir> && git init

# 3. explicit public-safe identity (repo-local only; §8)
git config user.name  "<owner-supplied>"
git config user.email "<owner-supplied>"

# 4. add exactly what the export produced (safe here — the directory contains
#    nothing except the export; git add -A is NOT recommended in the
#    authoritative repos themselves, where it risks catching unrelated
#    working-tree state, but this directory has no other state to catch)
git add -A

# 5. root commit — the qualified tree, unmodified
git commit -m "<project>: public release tree"

# 6. verify (§7) before doing anything else
# 7. (optional, recommended) a second commit adding public-only
#    RELEASE_PROVENANCE.md — never mixed into the root commit (§9)
# 8. only much later: git remote add / git push — NOT part of this increment
```

**A root commit followed by one small provenance commit was found preferable to a single commit
containing everything.** Keeping the root commit exactly equal to the qualified tree makes its
tree-SHA equal to the private tree-SHA a direct, zero-interpretation proof (§7A); layering the
provenance statement as a second commit keeps that proof from ever being contaminated by a
public-only file, and keeps "what the source release actually is" separate from "what we say about
where it came from."

## 7. Content-equivalence verification (two independent, transparent mechanisms)

**Primary — Git-native tree equality.** Git's object model hashes a tree solely from its entries'
content, so two unrelated repositories containing byte-identical files/modes/names independently
compute the identical tree SHA:

```
private:  git rev-parse 24efab8a5fecc159ca88f1ad94e03b0d5dee2c61^{tree}
          → 1d9e61f5744e7f60c19f33a26a43b40d71ccec77
public:   git rev-parse <public-root-commit>^{tree}
          → 1d9e61f5744e7f60c19f33a26a43b40d71ccec77   (IDENTICAL)
```

**Secondary — portable manifest.** A `path, mode, SHA-256` listing (git-tool-independent, readable
without any Git knowledge) was generated for both trees and diffed: 135/135 files identical,
including a 100644-vs-120000 mode check (no symlinks present in either tree).

Both mechanisms found zero differences for the qualified software tree. The subsequent
`RELEASE_PROVENANCE.md` addition is reported separately (§6, §9) rather than folded into this
comparison, precisely so this equivalence statement never becomes "identical except for one file we
don't mention."

## 8. Public author identity

**Not resolved by this increment — an owner-supplied prerequisite before actual publication.**
The maintainer's local Git configuration uses a personal email address, which is intentionally not
reproduced here — it is the personal identity this whole exercise exists to keep out of any public
commit. No `.mailmap`,
no previously-recorded GitHub noreply address, and no way to derive one with confidence exists
locally; the GitHub remote URL reveals only an org/user path (`kriskokomoor`), which is not
sufficient evidence of that account's actual noreply-email setting. A GitHub noreply address must
be confirmed directly from the account's own GitHub settings before use, and none was invented
here. For the scratch qualification in this document, a clearly synthetic, never-to-be-published
identity was used (`scratch-qualification@example.invalid`) and is not proposed as a real answer.

## 9. Provenance representation

**One authoritative location: `RELEASE_PROVENANCE.md` at the root of each public repository**,
added as the second commit (§6), not duplicated into the release manifest or release notes (those
may link to it). Content, qualified and tested in this run:

- States the repository was published from an internally qualified candidate, naming the
  **internal qualification identifier** explicitly as such (not a resolvable commit).
- States the content-equivalence mechanism and result (git tree SHA equality; portable manifest).
- States plainly that the private development history is intentionally absent — not for secrecy,
  just because it is not the release.
- **Disclaims cross-references:** the qualified tree's own existing documentation
  (`THIRD_PARTY_NOTICES.md`) cites private historical commits (`290cb90`, `46bf7d3`) as ordinary
  provenance prose, written when it only had to be true inside the private repository. Once
  exported verbatim, those hashes read as though they might be resolvable in the public repository
  too. Rather than editing the qualified tree itself (which would break tree-SHA equivalence and
  touch content this design deliberately keeps untouched), `RELEASE_PROVENANCE.md` states
  explicitly that such hashes are internal-only and not public ancestors. **This is a real,
  disclosed hygiene finding, not a secret exposure** — the values are commit hashes, not personal
  data or credentials — and it is fully mitigated by the disclaimer without touching the private
  repository. A future private-repo documentation pass may independently choose to reword those two
  sentences to be resolvability-agnostic; that is optional and out of scope here.

## 10. Application to Structure and gateway

Same procedure, same two-commit shape, once each has its own qualified internal candidate commit
(not yet established for either — that is explicitly the next increment, not this one). The one
substantive difference is cross-repository dependency identity:

- **Public Structure must not depend operationally on an unreachable private attrs SHA.** Its
  public README/CI/install instructions must name the **public attrs release identity** — in
  order of preference, a public attrs **release tag** (e.g. `v0.1.0`, once it exists), falling back
  to the public attrs repository's own resolvable commit SHA if no tag exists yet. Never the
  private `24efab8`-style internal identifier, which does not exist as an object in the public
  attrs repository at all.
- **Public gateway must reference public Structure/attrs identities**, the same way, for the same
  reason — its own README already documents a sibling-checkout convention; that convention's
  target moves from "a checkout of the private repo at a private commit" to "a checkout of the
  public repo at a public tag."
- **Private qualification documentation may keep citing internal commit identifiers**, provided
  they are labeled as internal (exactly the discipline already used throughout the existing release
  manifest/readiness report) — this is about what a *public consumer* is told to depend on, not
  about erasing internal cross-references from private documents.

## 11. Cross-repository dependency/version strategy and the self-reference problem

**No commit needs to know its own future SHA, at any layer, with this sequencing:**

1. Each public repository's root commit is created (its own SHA is unknown until this step
   completes — nothing inside it needs to reference it).
2. A public release **tag** is created afterward, pointing at an already-existing commit — tags are
   always retrospective, so this has no self-reference problem either.
3. A downstream repository's dependency reference (e.g. Structure's docs naming an attrs version)
   is authored after the upstream tag already exists, so it names something real, not something
   speculative.
4. The **existing private cross-repository release manifest**
   (`docs/release/FASTDICOM_RELEASE_MANIFEST.md`) is the natural place to close the loop: once all
   three public repositories/tags exist, it is updated (in the private repository, in an ordinary
   follow-up commit) to record the resulting public identities alongside the internal ones it
   already records. It is not part of any public commit and never needs to predict its own future
   state.

This requires no cryptographic ceremony, no generated attestation signing, and no manifest that
embeds its own commit hash — ordinary "create the thing, then point at it" sequencing, the same way
Git tags and changelogs already work.

## 12. Public repository topology

**Three public repositories, matching the existing architectural boundaries — no monorepo.**
`fastDICOMattrs` (structural engine), `fastDICOMstructure` (policy/execution, depends on attrs),
and `fastDICOMgateway` (bounded reference application, depends on Structure) are already
independently buildable, independently testable, and already documented and qualified as three
separate concerns throughout this entire release-preparation effort. Nothing found during this
increment's qualification work suggests otherwise, and gateway in particular should remain a small
satellite, not be promoted into the center of the release by a topology change.

## 13. Attrs scratch qualification result (summary; full detail in the final report to the user)

Performed entirely in a disposable scratch directory, from `24efab8a5fecc159ca88f1ad94e03b0d5dee2c61`:

- Export: 135 files, no `.git`, no untracked/ignored content (by construction of `git archive`).
- Root commit `57699c9` (scratch-only SHA, not meaningful beyond this qualification run): no
  parent; tree SHA identical to the private commit's tree SHA.
- History isolation: exactly 1 object-graph commit before the provenance commit; none of
  `46bf7d3`/`6409206`/`24efab8`/`290cb90` resolve as objects in the scratch repository; the
  historical `PS3.6.xml` blob (`9e80bad7...`, looked up directly from private history) is absent
  from the scratch object database by direct object-existence check, not merely by commit
  unreachability.
- Hygiene scan: clean, except the disclosed `290cb90`/`46bf7d3` textual-reference finding (§9),
  mitigated via `RELEASE_PROVENANCE.md`, not via editing the qualified tree.
- Build/test: fresh CMake configure+build+`ctest` → **312/312 passed**; `pytest tests/python` →
  **62 passed, 3 skipped** (the same maintainer-only dictionary-regeneration skips as the private
  repository, for the same reason — no `PS3.6.xml` present, by design). No dependency on the
  private repository's history at any point; no dependency on the removed `PS3.6.xml` for normal
  build/test/runtime behavior.

No regression against the private repository's own qualification baseline.

## 14. STOP conditions for the actual publication increment

Carried forward unchanged from this increment's own constraints — a future publication increment
must itself re-check all of these, not assume they still hold:

- The export ever includes `.git`, an untracked file, or an ignored file.
- The public root commit's tree SHA does not match the qualified private commit's tree SHA.
- Any private commit SHA, or the historical `PS3.6.xml` blob, resolves as a Git object in the new
  repository.
- A personal email, local absolute path, or credential appears in tracked public content.
- Build or test results regress relative to the private repository's own qualified baseline.
- A public repository's operational instructions require a private, unreachable commit SHA.
- The final author identity used is still a placeholder/synthetic one at the moment of an actual
  `git push`.

If any of these occur, stop, do not push, and report the specific failure rather than improvising a
fix under publication pressure.

## 15. What this design deliberately does not solve

- It does not decide the real public author identity (§8) — an owner decision.
- It does not decide attrs/Structure/gateway's actual version numbers or tag names.
- It does not decide whether/when to actually create GitHub repositories or push anything.
- It does not address CI for the public repositories, code-signing, SBOM generation, or supply-chain
  attestation — none of that was in scope, and none of it is required to satisfy the objectives
  given.
- It does not reword the private repository's own `THIRD_PARTY_NOTICES.md` (§9) — flagged as
  optional future cleanup, not performed here.
