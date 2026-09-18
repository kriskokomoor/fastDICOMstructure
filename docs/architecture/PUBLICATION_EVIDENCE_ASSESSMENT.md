# Publication Evidence Assessment

Adversarial assessment of whether the accumulated `fastDICOMattrs`/`fastDICOMstructure`/
`fastDICOMgateway` work (through S1.7/S1.8) supports a defensible publication, in any of three
forms. This is not a request to draft anything — the objective is to determine what the evidence
actually supports, and to actively try to falsify each candidate thesis, not merely list them
favorably.

## 1. Evidence inventory

| Category | Evidence | Source |
|---|---|---|
| Structural separation (attrs owns DICOM semantics, Structure owns policy) | Enforced across every increment S1.1–S1.8; Pixel Data permanently outside attrs' element graph, verified by a dedicated test | `S1_1_PIXEL_DATA_DISCOVERABILITY_REVIEW.md`; `test_locator.py::test_pixel_data_target_never_resolves_and_never_materializes` |
| Locator model, recursive/wildcard semantics | S1.1, qualified with deterministic-ordering and zero-match-vs-malformed proofs | `S1_1_LOCATOR_MODEL_REPORT.md` |
| Charset-aware mutation, atomic rollback | S1.2/S1.3, raw-byte-exact rollback proven via differential testing against a deliberately-reverted design | `S1_3_RESULT_DIAGNOSTIC_IMPLEMENTATION_REPORT.md` |
| Declarative Configuration V1 | S1.4, closed/fail-closed JSON schema, round-trip proven | `S1_4_JSON_CONFIGURATION_IMPLEMENTATION_REPORT.md` |
| Deployment-neutral execution core | S1.5, `execute_one`/`run`, filesystem adapter, atomic publish | `S1_5_EXECUTION_ARCHITECTURE_IMPLEMENTATION_REPORT.md` |
| CLI ≡ library equivalence | S1.6, black-box + instrumentation delegation proof | `S1_6_THIN_CLI_IMPLEMENTATION_REPORT.md` (26 tests) |
| Container ≡ host equivalence | S1.7, SHA-256 byte identity, closed exit-code preservation, runtime-image boundary verified | `S1_7_CONTAINER_PORTABILITY_IMPLEMENTATION_REPORT.md` (21 tests) |
| Cross-application component substitution | S1.8, byte-identical output substituted into an independently-developed, already-deployed application | `S1_8_GATEWAY_INTEGRATION_CLOSURE.md` |
| Pre-persistence policy boundary (a *different*, already-planned article) | `fastDICOMgateway` M1–M5: strace-observed zero filesystem writes, `--read-only` container, Cloud Run dual-log-stream verification, independent durable-store retrieval, negative controls that found real bugs in the validation harness itself | `docs/PUBLICATION_BRIEF.md` (gateway repo) |
| Performance characterization | Narrow, single-machine, single-file; explicitly no corpus-scale claim | `PRODUCT_CAPABILITY_MAP.md` P6.1/P6.2/P6.3 |
| Market/prior-art falsification exercise | A dedicated, adversarial industry-research checkpoint that actively tried to disprove a "novel gateway product" thesis and found the space occupied | `S1_8_EXTERNAL_DICOM_GATEWAY_DESIGN_CHECKPOINT.md` |

## 2. Candidate contribution/thesis table

| Thesis | One-line claim | Verdict after adversarial review |
|---|---|---|
| A — DICOM gateway | "We built a lightweight DICOM de-identification gateway." | **Falsified as novel** — see section 3 |
| B — Lightweight structural transformation | "Policy operations on a small metadata subset need not require full-object materialization." | Architecturally true, but the *technique* is not novel and the *performance claim* is not rigorously benchmarked — see section 3 |
| C — Policy boundary before persistence | "Policy evaluation can be placed ahead of durable persistence." | **This is the existing, already-planned M1–M5 article's own thesis** ("don't land what you don't want to own") — reusing it here would repeat, not complement, that work. Not pursued as a separate S1.7/S1.8 thesis. |
| D — Reusable semantic/policy layering | "Separating DICOM semantics from policy/execution creates a component reusable unchanged across execution environments and into an existing application." | **Strongest, most directly evidenced by S1.5–S1.8** — see section 3 |
| E — Evidence-driven, falsifiable staged milestones | "A staged series of falsifiable milestones establishes useful portability/composability evidence." | Interesting methodology, not itself a novel research contribution — see section 3 |

## 3. Prior-art findings

Web research conducted directly (not from training-data recall); access date **2026-09-16** for
all sources below not already cited in the earlier S1.8 industry checkpoint.

**Against Thesis A (gateway).** Beyond the already-documented RSNA CTP, AEGIS, dcm4che/DCM4CHEE,
Orthanc, and commercial site-embedded tools (ClinTrak, SMART Submit, Ambra — see
`S1_8_EXTERNAL_DICOM_GATEWAY_DESIGN_CHECKPOINT.md` section 6), this round of research found an
even more direct competitor:

- **Karnak** — "an open-source DICOM gateway for de-identification, tag morphing and DICOM
  conformance checks. It receives studies from modalities, PACS and workstations through a DICOM
  listener, transforms them according to configurable YAML profiles, and forwards the result to one
  or more destinations over DICOM (C-STORE) or DICOMweb (STOW-RS)"
  ([karnak.weasis.org](https://karnak.weasis.org/en/userguide/portable/);
  [GitHub: nkalten/karnak](https://github.com/nkalten/karnak)). This is a closer match to the
  originally-hypothesized "configurable policy gateway" than anything found in the earlier round —
  open-source, actively part of the Weasis ecosystem, declaratively (YAML) configured, and
  DICOMweb/C-STORE-forwarding-capable. It materially strengthens the "space already occupied"
  finding.
- **DicomShield** — a **May 2026** paper, "A Pseudonymization Proxy for the Secondary Use of
  Imaging Data in the Research Context," Oehm et al., Institute of Medical Informatics (Münster)
  and Institute of Medical Data Science (Magdeburg), PubMed-indexed
  ([pubmed.ncbi.nlm.nih.gov/42175132](https://pubmed.ncbi.nlm.nih.gov/42175132/)). A **recent,
  peer-reviewed academic publication** occupying essentially the same functional niche
  (metadata pseudonymization proxy for secondary research use). This is the single strongest piece
  of evidence against treating "a DICOM pseudonymization/policy proxy" as a viable, novel research
  contribution right now — someone has already published substantially adjacent work, recently, in
  what appears to be a peer-reviewed venue.

**Against Thesis B (structural-only transformation as a performance/architecture claim).**
Lazy/deferred pixel-data handling is **not novel at the technique level**: pydicom's own
documentation states it "doesn't do anything with pixel data except read in the raw bytes" by
default, and DCMTK "does not read long tag values (like pixel data) into memory when parsing but
only loads them on demand" (both confirmed via direct search of current library documentation/
discussion, not recalled). No specific academic benchmark paper quantifying structural-only
inspection performance against full materialization at corpus scale was found — this is a real gap,
not evidence of a contribution already made by this project.

**On Thesis D/E (composability, staged falsifiable verification).** "Component substitution/
replaceability" is an established software-engineering research area, not an open one: a
testing-based process for evaluating component replaceability
([ScienceDirect S1571066109000966](https://www.sciencedirect.com/science/article/pii/S1571066109000966)),
formal dynamic-reconfiguration substitutability work (CompSub, using Atelier B/ProB for proof
obligations and runtime animation;
[arXiv:1404.0848](https://arxiv.org/abs/1404.0848)), and multi-level behavioral-comparison
methodologies for software-intensive systems
([arXiv:2205.08201](https://arxiv.org/pdf/2205.08201)) all predate and formally exceed what this
project's own evidence establishes. The general *research question* ("how do we verify one
component can replace another") is not novel. What was not found: a comparably rigorous, publicly
documented, staged/frozen-checkpoint case study specifically in a healthcare-adjacent (DICOM/PHI)
domain, using byte-identical equivalence as the bar across both cross-invocation (S1.5–S1.7) and
cross-application (S1.8) axes, with an explicit, disclosed adversarial self-falsification step
(the rejected "gateway product" hypothesis) built into the process itself.

## 4. Claims supported now

- Structure's policy engine executes with equivalent semantics across direct library, CLI, and
  container invocation, with SHA-256 byte-identical output for tested cases (S1.5–S1.7 evidence,
  proven, not asserted).
- Structure's policy engine can replace an independently-developed application's own hand-coded
  DICOM mutation logic with byte-identical output, verified via instrumented delegation proof, not
  merely two independently-agreeing computations (S1.8 evidence, proven).
- Neither substitution required any change to the Structure/attrs implementation itself.
- Pixel Data is structurally never materialized by any locator/policy operation (S1.1, proven).
- A dedicated, adversarial market-research pass found the "novel gateway product" framing
  unsupported and narrowed scope accordingly, rather than proceeding on an unexamined assumption
  (S1.8 broad checkpoint, a genuine methodological artifact, not merely a disclaimer).

## 5. Claims not supported

- No corpus-scale or large-Pixel-Data-payload performance benchmark exists (Thesis B's strong
  form).
- No claim of novel technique for avoiding bulk-data materialization — established DICOM toolkits
  already do this.
- No claim that this is a novel research contribution to component-substitution verification
  methodology in general — the research question is established.
- No de-identification-completeness, PS3.15-conformance, UID-remapping, or burned-in-pixel-PHI
  claim (already excluded in `S1_8_GATEWAY_INTEGRATION_CLOSURE.md`).
- No claim of reusability beyond the one demonstrated consumer (`fastDICOMgateway`) — a single
  successful integration is evidence of composability in that instance, not of general reusability.
- No public availability of any of the three repositories yet (`docs/PUBLICATION_BRIEF.md` in the
  gateway repo explicitly notes this repository is not published as part of any task to date) —
  relevant specifically to the software-paper form (section 7).

## 6. Important negative findings

- The market for "DICOM policy/de-identification gateway" is not merely occupied but occupied by
  at least one project (Karnak) that is arguably a closer architectural match to the originally
  hypothesized product than anything considered in the first pass, and by at least one recent,
  peer-reviewed academic publication (DicomShield) in a materially adjacent niche.
- The specific "structural-only, no-materialization" technique this project relies on architecturally
  is already standard practice in the two most widely used DICOM toolkits (pydicom, DCMTK) — it is
  a sound design choice, not a novel one.
- "Component substitutability verification via staged, falsifiable milestones" is a known research
  area with existing formal-methods tooling, not an unclaimed research question.

## 7. Publication-form assessment

### A. Technical/practitioner article

**Strongest plausible contribution**: not "we built a DICOM gateway" (Thesis A, dead), but a
methods/process story — what happened when a carefully-qualified policy engine was pressure-tested
against (a) three deployment/invocation shapes with byte-identical equivalence (S1.5–S1.7) and
(b) substitution into a real, independently-developed, already-deployed application (S1.8) — framed
honestly around the negative finding that the "product" hypothesis didn't survive its own market
research, and why that is itself the interesting result (see section 9).

**Evidence already available**: all of it — every hash, test count, and instrumented proof cited
in this document already exists in frozen, committed form.

**Missing evidence**: none required to *begin drafting*; the underlying repositories are not yet
public, which matters for where such an article could credibly link for reproduction.

**Novelty risk**: low — a practitioner article does not require a novel research contribution, only
an honest, well-evidenced account.

**Overclaiming risk**: real and specific — must not imply Thesis A (gateway product), must not
imply de-identification completeness, must not imply the substitution proves general reusability.

**Estimated additional work**: none required for the evidence; drafting effort only.

**Sufficient to begin drafting: yes.**

### B. Software paper (architecture, reproducibility, validation, availability)

**Strongest plausible contribution**: the qualification discipline itself — frozen commits, exact
hashes, closed diagnostic/exit-code vocabularies, reproducible Docker builds from two named build
contexts, cross-invocation and cross-application equivalence evidence.

**Evidence already available**: extensive — this is precisely what a software paper's own
reviewers look for.

**Missing evidence**: public repository availability (none of the three repositories is published
yet); a second, independent consumer or clearer external-installation story beyond the one internal
gateway integration; typically also a stated user community or at least a plausible one.

**Novelty risk**: moderate — software papers require *some* distinguishing quality, not novelty in
the research sense, but "yet another DICOM library" without a sharper hook (e.g. the specific
qualification discipline) risks being seen as incremental.

**Overclaiming risk**: moderate — must not imply broader adoption or ecosystem than exists.

**Estimated additional work**: public release/archival (DOI), and ideally a second real consumer or
an explicit external-reuse demonstration.

**Sufficient to begin drafting: plausible, not yet sufficient** — the missing public-availability
step is not optional for this form.

### C. Research/systems paper

**Strongest plausible contribution candidate**: none currently clears the bar. Thesis A is
foreclosed by direct, recent prior art (Karnak, DicomShield). Thesis B's performance claim is
unbenchmarked at the scale that would make it interesting. Thesis D/E's underlying research question
(component substitutability verification) is already an established area with formal-methods prior
art this project does not engage with or extend.

**Evidence already available**: strong applied evidence, weak *research-question* framing.

**Missing evidence**: a sharper, currently-absent research question not already asked and answered
elsewhere, or a rigorous corpus-scale benchmark establishing Thesis B as a quantified, comparative
result (not just an architectural property).

**Novelty risk**: high, as assessed above.

**Overclaiming risk**: high if pursued without the missing pieces.

**Estimated additional work**: substantial — a genuinely new research question, or a full
comparative benchmark study, neither of which exists today.

**Sufficient to begin drafting: no.**

## 8. Additional experiments required

Only relevant to forms B and C, not to the practitioner-article path (which needs none):

- A corpus-scale performance/memory benchmark comparing structural-only inspection against full
  materialization (pydicom/DCMTK) on real or realistic large-Pixel-Data objects, if Thesis B is
  ever pursued quantitatively.
- Public release of the repositories, with a citable archive (e.g. a DOI via Zenodo/Software
  Heritage), if form B is pursued.
- A second, materially different consumer integration (not another DICOM gateway) if a stronger
  reusability claim is ever wanted.

## 9. Possible second practitioner-article angle

The existing `docs/PUBLICATION_BRIEF.md` (gateway repo) already claims the "don't land what you
don't want to own" pre-persistence-boundary thesis (Thesis C) for a first article, built entirely
on `fastDICOMgateway`'s own M1–M5 evidence. **Reusing that thesis here would repeat, not
complement, that work — not recommended.**

The strongest complementary angle, grounded directly in what M1–M5 does *not* cover: **M1–M5 proves
the boundary holds for the gateway's own hand-written pipeline; S1.7/S1.8 prove the boundary is a
real, load-bearing architectural line — not merely a diagram — by showing what happened when the
*policy engine itself* was extracted, pressure-tested across host/CLI/container invocation, and then
substituted into that same existing application without changing it.** A workable structure:

1. The setup: a policy engine was built and qualified in isolation (S1.1–S1.6), each increment
   frozen with its own falsifiable claim — briefly, not re-narrated from prior reports.
2. The pressure test: does "the same policy, unchanged" survive being invoked as a library, a CLI,
   and a container? (S1.5–S1.7, byte-identical evidence.)
3. The honest detour: what happened when this pattern was hypothesized as a *product* — an
   adversarial market-research pass, and finding the space already occupied by mature tools
   (CTP, Karnak, AEGIS) and even a recent peer-reviewed paper (DicomShield) — reported as a
   negative finding, not hidden.
4. The real test: substituting the engine into `fastDICOMgateway`'s own already-working, already
   -deployed pipeline — four lines of hand-written mutation replaced by one declarative policy
   object, with an *instrumented* proof (not a coincidental match) that the substitution is real,
   and byte-identical output as the equivalence bar.
5. Why the gateway itself was never the interesting part: the result that matters is that the
   boundary between "DICOM semantics" and "policy" held up under substitution pressure, not that a
   demo endpoint exists.
6. What this doesn't show (explicit non-claims, mirroring `S1_8_GATEWAY_INTEGRATION_CLOSURE.md`).

This is genuinely distinct from the M1–M5 piece (different evidence, different question — "is the
boundary real under substitution" vs. "does policy-before-persistence prevent PHI leakage") and is
fully supported by evidence already in hand.

## 10. Recommendation

**PRACTITIONER ARTICLE SUPPORTED — RESEARCH PAPER NOT YET SUPPORTED**

The practitioner-article path (section 9) is supported by evidence that already exists in frozen,
committed form and requires no further experiments to begin drafting. The software-paper path is
plausible but blocked specifically on public availability and a second consumer/reuse
demonstration. The research-paper path is not supported: the closest candidate theses are either
directly foreclosed by recent, specific prior art (Thesis A, by Karnak and the May-2026 DicomShield
paper) or represent an established research area this project's evidence does not extend
(Thesis D/E's underlying question) or an unbenchmarked architectural property rather than a
measured result (Thesis B).
