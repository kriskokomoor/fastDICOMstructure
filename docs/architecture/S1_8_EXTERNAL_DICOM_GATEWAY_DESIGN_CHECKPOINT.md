# S1.8 Design Checkpoint — External DICOM Gateway / Service Deployment

**Status: ANALYSIS, ARCHITECTURE, AND INDUSTRY-RESEARCH CHECKPOINT ONLY.** No production code, test,
or frozen file was touched; nothing was committed. This checkpoint's explicit mandate was to try to
**falsify** the proposed use case, not to justify a decision already made — section 8 (evidence
against) and section 26 (STOP conditions) were written with equal or greater rigor than the
sections building the case for proceeding.

---

> **Historical-role notice (added after S1.8's actual implementation).** This document is broad,
> exploratory industry/market reconnaissance into a hypothetical *external DICOM gateway product*.
> That broad product framing was **explicitly rejected** in the very next authorization: S1.8 was
> reframed into a much narrower engineering question (can an already-existing application,
> `fastDICOMgateway`, replace its own hand-coded policy with the frozen `fastdicomstructure.policy`
> engine?), pursued in `S1_8_GATEWAY_INTEGRATION_IMPLEMENTATION_DESIGN.md` and closed with evidence
> in `S1_8_GATEWAY_INTEGRATION_CLOSURE.md`. **This document is preserved unmodified below as the
> original evidence and reasoning trail — its negative findings (mature substitutes already exist;
> this is not evidence of a novel gateway product; full PS3.15 de-identification, UID remapping,
> study-level coordination, and burned-in pixel PHI are all outside anything ever demonstrated) are
> not superseded and remain accurate.** Do not read the sections below as describing what S1.8
> actually built — see the closure document for that.

---

## 1. Executive summary

The proposed use case — a thin, policy-enforcing endpoint sitting between a clinical site and an
external recipient, evaluating and optionally transforming DICOM objects before they reach durable
storage outside the site's control — is **not a novel problem space**. It is occupied by mature,
widely-deployed tooling on both the free/open-source side (RSNA CTP, in production for over a
decade) and the commercial side (site-embedded de-identification inside core-lab upload software).
The frozen S1.1–S1.7 architecture, however, holds up **better than expected** under pressure-testing:
the destination abstraction appears to generalize to network adapters with no change to
`execution.py`, and `execute_one`'s deliberate Configuration-independence (built for an unrelated
reason in S1.5) turns out to be exactly the right shape for HTTP-push ingress. The strongest
counter-evidence is not architectural but positional: `fastDICOMgateway` **already is** a narrow,
hand-built, Cloud-Run-deployed instance of very nearly this product, and the market evidence
suggests real de-identification-before-transmission work already happens **inside** site/core-lab
software, not at a separate network hop a site sends identified data *to*. Burned-in pixel PHI — a
real, largely-unsolved problem this architecture cannot touch by design — further narrows any
honest claim. The recommendation is **PROCEED ONLY AFTER RESOLVING NAMED QUESTIONS** (section 29),
not an unconditional proceed and not an outright stop.

## 2. Frozen starting state

| Item | Commit | Verified |
|---|---|---|
| fastDICOMattrs | `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6` | matches, clean |
| fastDICOMstructure S1.7 | `ffa117f1a63c7e269bfad24bfc0f5e1938430f35` | matches, HEAD, clean |

`python3 -m pytest tests/python/` — **299/299 passing**. No discrepancy found.

## 3. Proposed use case

Restated from the authorization: a clinical site transmits DICOM objects to a thin policy
enforcement endpoint rather than landing them first in infrastructure the gateway operator
controls; the endpoint structurally inspects, evaluates policy, optionally mutates/de-identifies,
and forwards accepted objects to an explicitly configured external destination (CRO, sponsor, core
lab, PACS, cloud DICOM store); rejected objects should not become durable gateway data merely
because they were submitted. This is treated throughout as a **hypothesis to falsify**, not a
requirement.

## 4. Problem statement

Does a technically coherent, externally useful, and **not already comprehensively occupied** product
role exist for `fastDICOMstructure` as this thin layer — and if so, does the frozen execution
architecture (Configuration V1, `execution.py`, the source/destination adapter contract) extend to
it without becoming a second architecture, a workflow platform, or a PACS?

## 5. Industry/workflow research methodology

Web search conducted directly (not from training-data recall) across the categories the
authorization named, plus direct inspection of the three sibling repositories. Sources are cited
inline with title and URL; access date for all web sources is **2026-09-16** (session date).
Vendor marketing claims are reported as claims, not verified effectiveness. No market-size or
adoption figures are invented; only figures a source itself states are reported, attributed to that
source.

## 6. Existing products/substitutes

Bounded to genuinely comparable examples (not a generic landscape survey):

| Solution | Category | Operator/deployment | Key evidence |
|---|---|---|---|
| **RSNA Clinical Trial Processor (CTP)** | Free, open-source de-identification/routing pipeline, Java | Self-hosted, typically at the site or trial-data-center | Purpose-built for exactly this use case since ~2009; a cited real-world deployment reports "more than 2,000,000 images... de-identified" and "20,000,000 images... moved... without de-identification" over 75 months ([AuntMinnie](https://www.auntminnie.com/imaging-informatics/enterprise-imaging/pacs-vna/article/15600710/rsna-clinical-trial-processor-can-deidentify-images); [PMC4346661](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4346661/)); default profile follows DICOM WG18 Supplement 142 Basic Profile ([MircWiki](https://mircwiki.rsna.org/index.php?title=The_CTP_DICOM_Anonymizer)) |
| **AEGIS** (Anonymization & Exchange Gateway for Imaging Studies) | Open-source (Apache 2.0), multi-cloud SaaS or local Docker Compose | AEGIS Imaging LLC, active development, 1,697 commits, 32 open PRs as of fetch | DIMSE C-STORE ingestion, DICOMweb/STOW-RS forwarding, configurable routing, PHI detection, protocol compliance checking, automated head-scan defacing ([GitHub](https://github.com/aegis-imaging/aegis)) |
| **dcm4che / DCM4CHEE Archive** | Open-source Java DICOM toolkit + IHE-compliant PACS/VNA | Self-hosted | Anonymize-on-retrieve capability; AET-configurable anonymization ([web.dcm4che.org](https://web.dcm4che.org/dcm4chee-arc-light); [dcm4chee-arc-light#2261](https://github.com/dcm4che/dcm4chee-arc-light/issues/2261)) |
| **Orthanc** + Server Extensions | Open-source lightweight DICOM server | Self-hosted | `/tools/bulk-anonymize` REST route (since 1.9.4); Python extension framework combining `auto_forward` (rule-based routing) with `anonymization` in one pipeline ([Orthanc Book](https://orthanc.uclouvain.be/book/users/anonymization.html); [orthanc-server-extensions docs](https://orthanc-server-extensions.readthedocs.io/en/latest/readme.html)) |
| **DICOM-RST**, **DICOMcloud**, **Google dicomproxy** | DICOMweb protocol-bridging proxies | Self-hosted / library | DICOM-RST bridges DIMSE/S3 to DICOMweb independent of PACS vendor; DICOMcloud offers configurable anonymizer profiles (BasicProfile/RetainUIDs/RetainLongFullDates); Google's dicomproxy specifically bridges legacy C-STORE to STOW-RS ([GitHub: DICOM-RST](https://github.com/UMEssen/DICOM-RST); [GitHub: DICOMcloud](https://github.com/DICOMcloud/DICOMcloud); [GitHub: google/dicomproxy](https://github.com/google/dicomproxy)) |
| **Medpace ClinTrak Core Lab** | Commercial, embedded in core-lab platform | Runs at/for the trial site as part of the core lab's own tooling | "built in feature to de-identify DICOM Metadata (tags) right before uploading at site, to make sure no patient information is transferred or stored" ([medpace.com](https://www.medpace.com/cro/technology/imaging/)) — **de-identification happens before the network hop, in site-side software**, not at a separate receiving gateway |
| **Clario SMART Submit** | Commercial, proprietary de-identification + submission tool | Site-installed application | "research site loads the original DICOM into the software application... SMART Submit handles the rest"; vendor claims "48-fold more proficient at removing PHI than other DICOM transport solutions" (unverified vendor claim) ([clario.com](https://clario.com/solutions/medical-imaging/smart-submit/)) |
| **Ambra Health** | Commercial cloud imaging platform, CRO/device solutions | Cloud SaaS | "Installation-free upload portals... automated de-identification and replacement of required DICOM tags in the metadata"; supports weblink/portal/CD-upload ingestion ([ambrahealth.com](https://ambrahealth.com/solutions/cro-and-device/)) |

**Distinguishing categories, as instructed**: CTP/dcm4che/Orthanc are general-purpose DICOM
toolkits/routers a technically sophisticated team self-hosts and configures — not products a
clinical site "sends images to" out of the box. AEGIS is the closest architectural analog to the
proposed thesis (policy-based inspection, configurable routing, DICOMweb forwarding, open-source),
but is scoped to research/inter-institutional sharing, not specifically clinical-trial submission.
ClinTrak/SMART Submit/Ambra are commercial, workflow-embedded, and — critically — perform
de-identification **at the site, before transmission**, not at an intermediary the site transmits
identified data to. None of these is a "developer toolkit" in the sense `fastDICOMstructure` is (a
declaratively-configured, formally-qualified library/CLI/container a team would embed) — this is the
one axis where a distinguishable, if narrow, position was found (section 9).

## 7. Evidence supporting the need

- `fastDICOMgateway` itself is a real, working, Cloud-Run-deployed (M3/M4-validated) instance of
  almost exactly this shape, proving the deployment pattern is technically viable for this family
  (section 19).
- RSNA CTP's own scale evidence (2,000,000 de-identified images over 75 months) demonstrates the
  general architectural pattern (structural inspection → policy → conditional forward) has durable,
  multi-year, production value in exactly the clinical-trial-imaging context named in the
  hypothesis.
- AEGIS's active 2026 development shows new entrants still find this space worth building in, with
  an architecture (policy inspection, configurable DICOMweb routing, open-source) directionally
  similar to the proposed thesis.
- No solution found combines this functional shape with `fastDICOMstructure`'s specific,
  already-built differentiators: a declarative, closed, JSON-validated configuration surface
  (Configuration V1), a formally closed exit-code/diagnostic vocabulary, and cross-invocation
  (library/CLI/container) semantic equivalence *proven*, not merely claimed (S1.5–S1.7's own
  qualification evidence). This is a plausible, narrow differentiator for a technically
  sophisticated adopter (a health-tech engineering team), not evidence of a market gap for a
  turnkey product.

## 8. Evidence against the need

- **The specific step the hypothesis describes — an external network hop that de-identifies
  identified data in transit — does not clearly match how the closest commercial examples actually
  work.** Medpace's own description is explicit: de-identification happens "right before uploading
  at site," i.e., in site-side software, before the network leaves the site's own trust boundary.
  Clario SMART Submit is likewise a site-installed application, not a receiving endpoint. If the
  established pattern is "de-identify locally, then transmit already-safe data," the proposed
  gateway's core premise (identified data crosses the network to reach the enforcement point) may
  not match how the market already solves this.
- **RSNA CTP is free, open-source, standards-aligned (WG18 Supplement 142), and has 15+ years of
  production use** at meaningful scale. A new entrant must articulate what it does that CTP does
  not — this checkpoint did not find that articulation to be self-evident from the architecture
  alone.
- **Burned-in pixel PHI is a real, largely unsolved, high-throughput-unvalidated problem** —
  "approaches for removing PHI 'burned-in' to image pixel data are typically manual, and automated
  high-throughput approaches are not well validated," with one cited OCR pipeline still missing
  ~11% of cases ([Springer/JIIM](https://link.springer.com/article/10.1007/s10278-024-01098-7);
  [PMC11522224](https://pmc.ncbi.nlm.nih.gov/articles/PMC11522224/)). `fastDICOMattrs` deliberately,
  permanently never decodes Pixel Data (S1.1's own architectural finding, unchanged through S1.7) —
  meaning any de-identification claim this family could make is metadata-only by unshakeable design.
  CR/DX/MG and ultrasound modalities carry the highest burned-in-PHI risk per the same source — a
  real, materially weakening limitation for any positioning as a general de-identification solution.
- **Clinical trial workflows are study/subject/visit/protocol-oriented**, requiring manifest,
  reconciliation, and QC-query semantics well beyond DICOM object evaluation (`appliedclinicaltrialsonline.com`'s
  own framing: "how to package and submit DICOM files, how to respond to QC queries... what turnaround
  times are expected"). A single-object policy gate solves a narrow technical slice of a much larger
  operational problem; the commercially valuable layer, per the vendors found, is workflow/platform
  management (Medidata, Clario, RAYLYTIC, Ambra), not DICOM-level policy enforcement in isolation.
- **PHI can legally cross to a third party only under a HIPAA Business Associate Agreement** — a
  real, non-trivial legal/contractual relationship, not merely a technical integration
  ([HHS.gov](https://www.hhs.gov/hipaa/for-professionals/special-topics/health-information-technology/cloud-computing/index.html);
  [hipaajournal.com](https://www.hipaajournal.com/hipaa-business-associate-agreement/)). This does
  not prove sites *would* refuse a hosted gateway (BAAs are executed constantly with cloud EHR/
  imaging vendors), but it does mean "a site sends identified DICOM to our hosted endpoint" carries
  a compliance-relationship cost a self-hosted/on-prem deployment shape avoids or simplifies.

## 9. Competitor/substitute boundary analysis

> **Is there an identifiable gap between "DICOM toolkit/anonymizer/router" and "full clinical-trial
> imaging platform" that a lightweight configurable enforcement-and-forwarding component could
> plausibly occupy?**

**Outcome: partial gap, evidence insufficient to call it clear.** A real, if narrow, distinction
exists between CTP-class tools (mature, free, but XML-configuration-scripted, Java, not
formally-qualified for deployment-neutrality) and this family's own already-proven differentiators
(declarative JSON configuration, closed diagnostic/exit-code vocabularies, cross-invocation
equivalence *proven*, not asserted). But this checkpoint found **no evidence of unmet demand**
specifically for that differentiation — only that no directly comparable *combination* was found.
Absence of a directly comparable product is evidence of an unoccupied technical shape, not evidence
of a wanted one. The most defensible reading: **a component-level gap plausibly exists for a
technically sophisticated integrator** (a health-tech engineering team wanting an auditable,
embeddable building block rather than adopting CTP's XML scripting or a closed commercial platform);
**no gap was found at the "hosted product a clinical site sends images to" level**, where CTP,
AEGIS, and the site-embedded commercial tools already compete directly.

## 10. Standards/protocol analysis

Investigated per the authorization's own list. DICOM DIMSE C-STORE remains the traditional
modality-to-PACS protocol; DICOMweb STOW-RS is the REST-based, HTTP-native equivalent and is the
protocol every modern proxy/gateway example found (AEGIS, DICOM-RST, DICOMcloud, Google
dicomproxy, Google's own Cloud Healthcare API) treats as the primary web-facing interface — direct,
convergent evidence STOW-RS is the right destination protocol to target first, not an assumption.
Google's Cloud Healthcare API documentation confirms DICOMweb (QIDO-RS/WADO-RS/STOW-RS) support,
including for "migrating an entire PACS archive or transferring thousands of studies at once"
([docs.cloud.google.com/healthcare-api/docs/dicom](https://docs.cloud.google.com/healthcare-api/docs/dicom)).

**Single-instance vs. study/series submission**: real clinical-trial submissions are typically
study- or case-level (a "case" often means dozens to hundreds of instances), while the frozen
execution model (`execute_one`/`run`) is deliberately, permanently single-object. A first experiment
targeting one DICOM object per invocation is **knowingly narrower** than a real submission workflow
— this is stated plainly here, not glossed over, and is directly relevant to the STOP conditions
(section 26, item 6) and the minimum vertical slice (section 24).

**Transfer syntax preservation / SOP Instance UID implications**: covered in section 14.

**Conclusion**: `HTTP/DICOMweb ingress → single object → policy → optional mutation → STOW-RS
destination` is a reasonable **first experiment** shape, but must be labeled explicitly as testing
the single-object primitive's extension to network protocols, not as a submission-ready workflow.

## 11. Ingress requirements

An HTTP-push ingress (a clinical site's own software POSTs a DICOM object to the gateway) is
structurally different from every source this family has built so far. `FilesystemSource.acquire()`
is **pull**-oriented (the adapter resolves a configured location and reads from it at its own
initiative). An inbound HTTP request instead **hands** bytes to the gateway — there is no
"location" for a `SourceAdapter` to resolve at all. The evidence-grounded conclusion (section 23):
an HTTP gateway's ingress path would most naturally bypass the `SourceAdapter` abstraction entirely
and call `execution.execute_one(request_body_bytes, policy)` directly — which is possible today,
unchanged, specifically because S1.5 already made `execute_one` Configuration- and adapter-free by
design (its own "Probe H" property, built for an unrelated reason at the time).

Real DICOM object sizes routinely exceed the well-documented **32MB HTTP/1 request-body hard limit**
Cloud Run enforces (confirmed via multiple independent, current sources describing 413 errors and
workarounds — signed-URL-to-object-storage bypass, or HTTP/2)
([GitHub: attic#220](https://github.com/zhaofengli/attic/issues/220);
[dev.to: overcome Cloud Run's 32MB limit](https://dev.to/hernandezbg/comment/26h1o)). This is a real,
concrete, unresolved pressure point for any Cloud-Run-hosted HTTP ingress handling non-trivial
imaging objects (volumetric CT/MR, digital pathology) — named explicitly here, not minimized.

## 12. Destination/output requirements

**Success semantics — already more precise than a naive first guess would assume.** The frozen
`execution.run()` contract (S1.5, unchanged) already distinguishes "policy completed" from
"destination confirmed": `ExecutionOutcome.SUCCEEDED` requires **both** a persistence-eligible
`PolicyResult` **and** a successful `destination.write()` call when a destination exists;
`DESTINATION_FAILED` is already its own distinct, closed outcome. This maps cleanly onto three of
the four candidate success definitions the authorization poses (policy success, transformation
success, transmission success) — but **not** the fourth: "once recipient acknowledges durable
persistence." A DICOMweb STOW-RS `200 OK` response confirms the receiving server *accepted* the
request; nothing in the STOW-RS standard or the current adapter contract guarantees the object is
*durably* stored by the time that response is returned. This is a genuine, protocol-level gap
between what `write()` returning cleanly can mean and what "the recipient has it" might be assumed
to mean — the existing abstraction correctly delegates this to the adapter implementation, but no
evidence yet exists (because no network adapter has been built) about what guarantee any real
destination actually provides.

**Retry**: the existing architecture already has an answer that survives this pressure without new
core concepts — retry, if ever needed for a flaky network destination, belongs entirely inside that
one adapter's own `write()` implementation (matching "adapters own I/O only," and this project's
consistent, repeated rejection of a centralized retry framework at every prior increment). No change
to `execution.py` is implied.

## 13. Failure/retry/idempotency semantics

**Idempotency is a real, unresolved gap the current architecture has no opinion on at all.**
Configuration V1/`Policy` have no concept of "has this object already been forwarded." Two paths
exist: (a) delegate entirely to the recipient's own instance-uniqueness handling (many STOW-RS
receivers already reject or no-op a duplicate SOP Instance UID, per DICOM's own instance-identity
semantics) — cheap, but unverified for any specific real recipient without evidence; or (b) the
gateway itself tracks what it has already forwarded — which would require **some** durable state,
in direct tension with the "do not land first" thesis this whole use case is built on. This tension
is real and is not resolved by this checkpoint; it is named as an open question (section 28).

**Atomicity for multipart/study submission**: out of the single-object model's current scope
entirely (section 10) — per-instance success is the only semantics the frozen execution model can
express today; study-level atomicity would require new, not-yet-designed coordination this
checkpoint does not attempt to invent.

## 14. Mutation and DICOM identity implications

**The most serious architectural finding of this checkpoint.** DICOM PS3.15's own Basic
De-identification Profile typically **replaces** Study/Series/SOP Instance UIDs specifically to
break linkage back to the original identified object — omitting UID remapping is a real,
standards-documented weakening of a de-identification claim, not a neutral simplification. But
`fastDICOMstructure`'s execution model is **irreducibly single-object**: one source, one
`Policy` run, one destination, no cross-object or study-level coordination concept exists anywhere
in `policy.py`/`execution.py`, by design. Safely remapping a Study Instance UID requires every
other instance in that study (and every object elsewhere that references it — Structured Reports,
Presentation States, RT Dose referencing an RT Plan) to be remapped **consistently** — a
requirement the current architecture was never designed to express and cannot safely satisfy one
object at a time. **Configuration V1 already permits authoring a `replace_text`/`ensure_text`
operation against a UID-shaped tag with no special-casing** (verified: neither `policy.py` nor
`configuration.py` distinguishes UID VRs from any other text VR) — meaning a careless Configuration
document could already silently produce cross-object-inconsistent output today, for any caller,
independent of S1.8. This is not a new defect S1.8 introduces; it is a pre-existing sharp edge S1.8
would be the first to seriously stress.

**Conclusion for a first experiment**: UID remapping must be **explicitly excluded** from any
narrow first slice, with that exclusion stated plainly as a scoping decision, not silently omitted.
A metadata-replacement-without-UID-remapping transformation is real and useful (removing
PatientName/PatientID/dates/private tags), but is **not** full PS3.15 de-identification and must
never be marketed as such.

## 15. Persistence analysis

Distinguishing forms of persistence, as instructed: network buffers and process memory are
unavoidable and already how `execute_one`/`FilesystemSource`/`FilesystemDestination` operate
(bytes-in, bytes-out, S1.5's own already-documented whole-object-copy tradeoff, unchanged).
Temporary files, durable local disk, object storage, and databases are **architectural choices**,
not requirements — nothing in the frozen execution model forces any of them. Logs, retry queues,
dead-letter queues, and backups are deployment-layer concerns this checkpoint does not design.

**Can the gateway realistically stream/inspect/transform/forward without durable persistence for
large objects?** Partially, and with a real caveat: `execute_one` already operates on whole
in-memory `bytes` (S1.5's own accepted tradeoff — no attrs streaming-parse primitive exists,
unchanged through S1.7). For a large object arriving over HTTP, the *entire* object must already be
buffered in memory (or ephemeral local storage) before `execute_one` can even begin, regardless of
whether a durable copy is ever written to disk. **"Does not persist the original" can honestly mean
"does not durably retain it beyond the request's own lifetime," not "never materializes it in any
buffer"** — a precise, important distinction this checkpoint insists on rather than blurring. If
ephemeral local staging is operationally necessary for very large objects (e.g. Cloud Run's own
ephemeral filesystem, or a bounded temp file), that does not defeat the thesis, provided nothing
durable survives past the single request's lifecycle — a real, testable, falsifiable claim, not an
assumption.

## 16. Security/trust-boundary analysis

The gateway's trust-boundary position is genuinely ambiguous and evidence-dependent, not
pre-decided. A hospital **can** legally transmit PHI to a third-party hosted gateway, but only under
a HIPAA Business Associate Agreement — a real contractual relationship (section 8). This makes
**customer-hosted / on-premises deployment plausibly the lower-friction shape**, since it keeps the
software inside the covered entity's own trust boundary and sidesteps the BAA question for the
gateway operator specifically (the site's own existing BAAs with its downstream recipients would
still apply, unchanged). **The same container image could plausibly support both** shapes — nothing
in S1.7's own container architecture assumes a specific network trust position; the image is
deployment-neutral by construction (S1.7's own proven claim). Destination credentials would need to
be supplied via the deployment environment (matching the layering the authorization itself
specifies — secrets belong to the deployment environment, never to Configuration V1 or core code);
source authentication (verifying which site is submitting) is entirely undesigned and is a named
open question (section 28). PHI in logs: this project's own established discipline (S1.3's curated
`Diagnostic`, S1.6/S1.7's curated `ExecutionDiagnostic`/`AdapterResolutionError`) already forbids
raw values in any diagnostic surface — an HTTP gateway would need the *same* discipline extended to
request logging, access logs, and any new network-adapter-specific diagnostic, none of which yet
exists. Rejected objects: per the existing, unmodified persistence gate (`execution.run()`,
unchanged), a rejected or partial `PolicyResult` already never reaches a destination — this
property survives unchanged for a network destination adapter with zero new logic. **The S1.7
`0600` output-permission finding is specific to the filesystem adapter's `tempfile.mkstemp`
behavior and does not directly apply to a network destination** (there is no local output file to
own) — but an analogous concern would apply to any ephemeral local staging a network adapter used
internally, worth re-examining if and when such an adapter is designed. **No HIPAA, GDPR, FDA, GxP,
or Part 11 compliance is claimed anywhere in this checkpoint** — only architectural observations
about what those frameworks structurally require (a BAA, curated logging) are made.

## 17. Deployment-shape comparison

| Shape | Fit for the proposed use case |
|---|---|
| **Cloud Run Service** | Plausible, evidence-supported (see section 18) — matches the request-driven, HTTP-push ingress the actual use case describes |
| **Cloud Run Job** | Poor fit for *this* use case specifically — Jobs are for discrete, triggered-to-completion batch tasks (confirmed: "Use a Job when you need to perform a discrete, asynchronous task... Jobs run to completion and exit" — [oneuptime.com](https://oneuptime.com/blog/post/2026-02-17-how-to-implement-serverless-batch-processing-using-cloud-run-jobs-with-parallel-task-execution/view)); this directly **refines** the S1.7 checkpoint's own Cloud Run Job hypothesis, which reasoned from the CLI's one-shot invocation shape without yet considering an HTTP-push gateway's fundamentally different trigger model |
| **Function-style HTTP deployment** | Similar tradeoffs to Cloud Run Service; not separately evaluated in depth here |
| **Container on customer premises** | Plausible, arguably the lower-friction trust-boundary fit (section 16); S1.7's own image is already deployment-neutral |
| **VM/container appliance, Kubernetes** | Not evaluated — no evidence gathered suggests this use case needs orchestration complexity beyond a single container; deferred as unnecessary until proven otherwise |
| **Hybrid/on-prem edge gateway** | Plausible, same reasoning as customer-premises container |

## 18. Cloud Run suitability analysis

Investigated against current (fetched, not recalled) Google Cloud documentation and independent
sources:

- **Request timeout**: up to 60 minutes is now generally available
  ([docs.cloud.google.com/run/docs/configuring/request-timeout](https://docs.cloud.google.com/run/docs/configuring/request-timeout))
  — removes an earlier-generation concern about short timeouts for larger objects.
- **Streaming**: server-side HTTP and gRPC streaming, WebSockets, and HTTP/2 are now GA
  ([docs.cloud.google.com/run/docs/triggering/websockets](https://docs.cloud.google.com/run/docs/triggering/websockets))
  — a real, current capability that did not exist in Cloud Run's earlier generations.
- **Request body size**: a **hard 32MB limit specifically for HTTP/1** requests is well-documented
  and current (multiple 2026-era sources; see section 11) — the single most concrete, unresolved
  constraint found for this deployment shape. HTTP/2 and/or an object-storage-mediated upload
  pattern (signed URL, then notify) are the documented workarounds — the latter is explicitly the
  "Cloud Storage event trigger" pattern S1.7's own checkpoint already named as out of scope, meaning
  a fully general solution to this constraint may itself constitute separate, later-scoped work, not
  something a first experiment needs to solve.
- **Concurrency, service identity, outbound networking, authentication**: not investigated in
  further depth here — no evidence was found suggesting these present a *distinguishing* obstacle
  for this use case versus `fastDICOMgateway`'s own already-successful M4 deployment, which already
  exercises Cloud Run Service's authentication and identity model in production.

**Conclusion**: Cloud Run Service is technically plausible for a request-driven gateway, **directly
contradicting neither this checkpoint's own Job-hypothesis refinement above nor S1.7's own
deliberately-hedged Job hypothesis** — the two are answering different questions (S1.7 asked what
fits *the CLI's own* invocation shape; this checkpoint asks what fits *the gateway's* invocation
shape, which is a different, HTTP-push-triggered thing). The 32MB HTTP/1 body limit is a real,
unresolved constraint for large objects that any production-shaped implementation must address
eventually, but does not block a small, explicitly-scoped first experiment using modest fixture
sizes.

## 19. Relationship to `fastDICOMgateway`

Directly inspected (not modified). `fastDICOMgateway` **already implements nearly this exact
product**: `transform.py` performs in-memory parse → fixed policy → in-memory serialize; `sink.py`
forwards to a Cloud Healthcare API DICOM store via DICOMweb STOW-RS (real, production destination
adapter prior art, using multipart/related bodies per PS3.18 §6.6.1); `app.py` is a stateless
FastAPI `POST /dicom` service, deployed to Cloud Run and M3/M4-validated (container + Cloud Run
compatibility already proven for this exact family, one repository over). Its own independently
invented `RejectedInput`/`TransformResult`/`StoreFailure` dataclasses converge, unprompted, on the
same curated-diagnostic, no-PHI-in-logs philosophy this project's own S1.3–S1.7 increments arrived
at independently.

**The critical, unresolved fact, reconfirmed and still true**: `transform.py` **never calls
`fastdicomstructure.policy.Policy`/`apply()` at all** — it hand-rolls an equivalent four-operation
sequence directly against `Structure` primitives. A pre-existing test
(`test_apply_reproduces_gateway_demo_policy`) already proves `policy.apply()` computes an
equivalent result, but nothing in production exercises that path (the "zero-production-caller"
finding, first identified at Post-A1, still true at S1.7).

**A sharp, evidence-driven question this raises for S1.8's own scope**: the "minimum useful
vertical slice" the authorization asks this checkpoint to define (section 24) risks **substantially
duplicating** already-deferred "gateway convergence" work (`PRODUCT_CAPABILITY_MAP.md`'s P5.5 row,
`DEFERRED/BLOCKED` since S1.1, prerequisite explicitly stated as "S1.5's local adapter, then a
coordinated, separately-authorized change to `fastDICOMgateway` itself"). **Is S1.8 actually "do
gateway convergence, generalized to a configurable destination," rather than a new build?** This
checkpoint does not resolve that question — it names it as the single most important open question
for the next planning step (section 28).

**Convergence is not assumed beneficial**: gateway's own fixed, hand-rolled policy and its M2–M5
validation apparatus represent real, already-shipped, production-tested work; casually re-pointing
it at a new, differently-scoped execution engine mid-flight carries real regression risk, exactly as
the S1.5 checkpoint already concluded when it first examined this question.

## 20. Relationship to `fastDICOMattrs`

Unchanged from every prior checkpoint's own finding: `fastDICOMattrs` owns DICOM parsing, mutation,
and serialization; Pixel Data is permanently, deliberately outside its element graph (S1.1). This is
a **hard, load-bearing constraint** on any gateway product built on this family: it can be truthfully
described as inspecting and transforming DICOM *metadata*, never as inspecting or redacting pixel
content — directly relevant to the burned-in-PHI limitation (section 8) and to any future
de-identification marketing claim's honesty.

## 21. Relationship to future `fastDICOMarchive`

Directly inspected (read-only; not modified, per authorization). `fastDICOMarchive` is a **separate,
independent sibling project** — "a privacy-gated DICOM intake and derivative archive example,"
alpha status, PostgreSQL-backed, exploring a strikingly similar high-level philosophy (probe → apply
explicit privacy policy → persist only policy-qualified derivative content → safe evidence for
admits/rejects/failures) but through a **fundamentally different architecture**: stateful,
archive/cohort/reconstruction-oriented, using its own fast root-tag reader plus a `pydicom` fallback
for deep inspection — **explicitly not currently built on `fastDICOMstructure`**
(`fastDICOMarchive/README.md`'s own words: "fastDICOMstructure... not currently used by this
project"). Its own README explicitly distinguishes itself from `fastDICOMgateway`: "a separate,
stateless pre-persistence policy-boundary demo... distinct from this project's stateful,
PostgreSQL-backed archive/cohort/reconstruction design; the two are not integrated with each other."

**This is important, previously-unsurfaced context**: the general "policy-gate before persistence"
philosophy has already been explored twice in this project family, via two structurally different
approaches (stateless forward-only gateway vs. stateful archive-and-cohort), neither fully converged
with the other or with `fastDICOMstructure`'s own execution architecture. S1.8 would be a **third**
independent exploration of a related idea unless it deliberately anchors itself to one of the other
two. No modification or expansion of `fastDICOMarchive` was made or is proposed.

(For completeness, a fourth sibling, `fastDICOMscan`, was also found — a DCMTK-backed, pybind11-wrapped
fast tag-scanning library for metadata scans over large collections. It has no policy/gateway/
forwarding concern at all and is not materially relevant to this checkpoint's thesis; noted only for
completeness of the family landscape.)

## 22. Architectural pressure on Configuration V1

**Finding: no new Configuration V1 semantics appear required for a narrow first experiment.**
`Envelope`'s existing shape (`{"type": str, "options": object}`, opaque `options`, S1.4/S1.5) already
anticipates exactly this extension: a new `"type": "dicomweb"` (or similar) destination with
adapter-owned `options` (e.g. a URL, a credential-reference — never a raw secret, matching
section 16) fits the *existing* contract with zero change to `configuration.py`. This is the same
pattern `adapters/filesystem.py` already established and is not a new architectural idea — it is the
originally-intended one, now evidenced by a concrete second candidate use. `source` being entirely
absent for an HTTP-triggered deployment (ingress bypassing `SourceAdapter` per section 11) is
likewise already legal under S1.4's schema (`source` is optional) — no schema change implied there
either.

## 23. Architectural pressure on existing source/destination interfaces

**Destination side: survives well.** `DestinationAdapter.write(bytes) -> None` places no assumption
on the transport — a network-backed implementation (DICOMweb STOW-RS) fits the existing contract
exactly as the filesystem adapter does, with retry (if needed) staying adapter-internal (section 12).

**Source side: does not apply to HTTP-push ingress, and that is evidence, not a defect.**
`SourceAdapter.acquire() -> bytes` (no arguments, pull-oriented) was designed around S1.5's own
filesystem proof and does not naturally model "bytes an inbound HTTP request already handed you."
The clean resolution — already available, unchanged — is that an HTTP gateway's own request handler
calls `execution.execute_one(request_body_bytes, policy)` directly, exactly as S1.5's own "Probe H"
already proved was possible for *any* caller holding bytes directly. **No change to
`adapters/__init__.py`'s `resolve_source`/`SOURCE_ADAPTERS` is implied** — a future gateway
component simply would not use them for its ingress leg, while still legitimately using
`resolve_destination`/`DESTINATION_ADAPTERS`/`check_source_destination_collision` is not
applicable (there is no source path to collide with) for its egress leg.

## 24. Minimum useful vertical slice (not implemented)

Derived from the evidence above, not assumed in advance:

- **Hypothesis**: `execution.execute_one(bytes, policy)`, called directly from an HTTP request
  handler (bypassing `SourceAdapter` entirely, per section 23), composed with one new
  `DicomwebDestination` adapter implementing the existing `write(bytes) -> None` contract, can
  correctly express "accept/mutate/reject one DICOM object received over HTTP and forward it to a
  DICOMweb STOW-RS endpoint" without any change to `policy.py`, `configuration.py`, or
  `execution.py`, and without introducing UID remapping, study-level coordination, or durable
  staging beyond the single request's own lifetime.
- **Frozen starting commit**: `ffa117f1a63c7e269bfad24bfc0f5e1938430f35` (this checkpoint's own
  baseline).
- **Permitted files**: a new, isolated experiment location (e.g. a scratch/spike directory or a
  clearly-labeled new module never wired into `cli.py`/`__main__.py`) plus, if genuinely needed, one
  new adapter file (`adapters/dicomweb.py`) added the same additive way `run_configured` was added
  to `execution.py` at S1.6 — proposed, not pre-approved.
- **Prohibited files**: every file protected in section 13 remains prohibited from any *semantic*
  change; `fastDICOMattrs`, `fastDICOMgateway` untouched.
- **Ingress protocol**: HTTP POST, request body = raw DICOM bytes (matching gateway's own proven
  `app.py` pattern) — not multipart, not DICOMweb STOW-RS receiving semantics, for the first
  experiment specifically (receiving STOW-RS correctly is itself nontrivial and would conflate two
  new things at once).
- **Destination protocol**: DICOMweb STOW-RS, matching the convergent evidence in section 10.
- **Test receiver**: a local, disposable, test-only STOW-RS receiver (a minimal mock, not a real
  Healthcare API store) so the experiment tests the adapter contract, not a live cloud dependency.
- **Success criteria**: an accepted/mutated object reaches the mock receiver with correct bytes; a
  rejected/partial object never does; the destination adapter's own failure modes map to the
  existing closed `ExecutionOutcome` vocabulary without inventing new categories unless evidence
  demonstrates a genuine gap.
- **Failure criteria**: any requirement to touch a protected file's *existing* semantics; any
  requirement for cross-object/study coordination; any requirement for durable pre-forward staging
  beyond the request's own lifetime.
- **Byte/semantic checks**: the forwarded object reparses cleanly and matches the same policy
  semantics a direct library call would produce (mirroring S1.6/S1.7's own delegation-proof
  discipline).
- **Privacy checks**: mirroring S1.6/S1.7's own established sensitive-literal-injection technique,
  extended to the new HTTP/network surface (request logging, adapter diagnostics).
- **Persistence checks**: prove nothing durable survives a rejected request past its own lifecycle.
- **Retry/idempotency checks**: explicitly deferred — named as an open question (section 28), not
  something the first experiment needs to resolve.
- **STOP conditions**: any of section 26's conditions triggering during the experiment ends it
  immediately, reported rather than worked around.

## 25. Proposed qualification probes

If S1.8 proceeds to the bounded experiment, probes would need to prove (not assumed satisfied by
this checkpoint): (1) `execute_one` called directly from an HTTP handler produces identical
`PolicyResult` semantics to the existing CLI path for identical bytes/policy (a direct extension of
S1.6/S1.7's own delegation-proof pattern); (2) the persistence gate (destination invoked iff
`SUCCEEDED`) holds unchanged for a network destination; (3) a rejected/malformed/partial object never
reaches the mock STOW-RS receiver; (4) no sensitive literal appears in any new HTTP-layer log/
diagnostic; (5) the new adapter's own failure modes map onto the existing closed vocabulary. None of
these is implemented by this checkpoint.

## 26. STOP conditions

Evaluated against the evidence gathered, not assumed:

1. **Use case already comprehensively solved with no identifiable gap** — **partially triggered**:
   the "hosted product a site sends images to" framing appears well-occupied (section 8/9); the
   narrower "embeddable, formally-qualified component" framing does not appear comprehensively
   solved, but neither is unmet demand for it established.
2. **Meaningful gateway behavior requires clinical-trial workflow semantics in `fastDICOMstructure`
   itself** — **not triggered** by the narrow first slice (section 24), but real trial workflows
   (section 8) clearly need this eventually, at a layer *outside* this repository, exactly matching
   the authorization's own instruction not to embed it here.
3. **Cloud deployment requires altering core DICOM/policy semantics** — **not triggered**; sections
   22–23 found the opposite.
4. **Safe forwarding requires durable original-object persistence defeating the thesis** — **not
   triggered** for the narrow first slice; genuinely open for large objects and for idempotency
   (sections 13, 15).
5. **Correct mutation requires cross-object/study semantics the first experiment cannot preserve** —
   **triggered for full de-identification** (section 14); the first experiment avoids this by
   explicitly excluding UID remapping, which must be stated, not hidden.
6. **Practical DICOM object sizes make the ingress mechanism unsuitable** — **partially triggered**
   for Cloud Run Service specifically (the 32MB HTTP/1 limit, section 11/18) — real, unresolved,
   but addressable with known (if more complex) patterns later, not a first-experiment blocker.
7. **Recipient requirements too proprietary for a general destination abstraction** — **not
   evaluated**, no evidence gathered either way; a named open question (section 28).
8. **Architecture requires becoming a PACS/VNA/workflow platform** — **not triggered**; nothing in
   this analysis requires it, and the authorization's own boundary (section 2) is judged intact.
9. **Source/destination abstraction fundamentally incompatible with network forwarding** — **not
   triggered**; section 23 found the destination side extends cleanly and the source side simply
   doesn't apply (a non-problem, not an incompatibility).
10. **Evidence does not establish a meaningful problem worth testing** — **not fully triggered**, but
    the margin is thin; see the recommendation (section 29).

## 27. Capability-map implications (proposed only — map not modified)

If S1.8's bounded experiment is authorized and later succeeds, it would plausibly inform (never
automatically promote): **P4.4 (DICOMweb/WADO-RS)**, currently `CANDIDATE` — a real adapter
implementation and forwarding proof would be direct evidence; **P5.4 (Cloud/serverless)**, currently
`CANDIDATE` — only if an actual Cloud Run Service deployment were built and qualified, which this
checkpoint explicitly did not do; **P5.5 (Gateway convergence)**, currently `DEFERRED/BLOCKED` — only
if the experiment is deliberately anchored to real convergence work (section 19's open question), not
a parallel new build. No row is modified by this checkpoint.

## 28. Open questions

1. **Is S1.8 actually "finish gateway convergence, generalized to a configurable destination,"
   rather than a new build?** (section 19) — the single most consequential unresolved question.
2. Is the real product/value shape "hosted gateway" or "embeddable, self-hosted component for a
   sophisticated integrator" (section 9/16)? These imply materially different next steps.
3. How should idempotency/retry be honestly resolved without silently reintroducing durable
   pre-forward persistence (section 13)?
4. Should UID remapping / study-level coordination ever be added, and if the answer is durably "no,"
   how is the resulting transformation honestly named (never "de-identification" unqualified)?
5. What does a `200 OK` from a real STOW-RS recipient actually guarantee, for any specific real
   recipient this might target? No evidence was gathered on a *specific* recipient's own contract.
6. Who authenticates an inbound submission, and how — entirely undesigned.
7. Does solving the 32MB Cloud Run HTTP/1 body limit properly require the object-storage-mediated
   pattern S1.7 already named as out of scope, and if so, does that make this a bigger increment
   than "S1.8" implies?

## 29. Recommendation

**PROCEED ONLY AFTER RESOLVING NAMED QUESTIONS**

Not an unconditional proceed: the market evidence (section 8) is genuinely strong — RSNA CTP's
15-year, multi-million-image production history and the finding that the closest commercial
analogs de-identify *at the site*, not at a receiving gateway, meaningfully weaken the specific
"external endpoint sites send identified data to" framing, and burned-in pixel PHI caps any honest
de-identification claim regardless of implementation quality. Not an outright stop: the architecture
pressure-tested better than assumed (sections 22–23 found no required core change), a narrower
component-level gap was not ruled out (section 9), and `fastDICOMgateway`'s own existing, deployed
instance is concrete evidence the underlying pattern has *some* durable value in this exact family.
The decisive open item is section 28.1 — until it is settled, a "minimum vertical slice" cannot be
scoped responsibly, because the correct slice differs materially depending on the answer (extend
`fastDICOMgateway`'s existing production code vs. build a new, parallel proof).

```text
attrs: FROZEN @ 46bf7d3
S1.1: FROZEN @ bdc324c
S1.2: FROZEN @ 53ecb83
S1.3: FROZEN @ 25615dd
S1.4: FROZEN @ 8879ca7
S1.5: FROZEN @ 350f88c
S1.6: FROZEN @ 9b84a2a
S1.7: FROZEN @ ffa117f
S1.8: DESIGN CHECKPOINT ONLY — PROCEED ONLY AFTER RESOLVING NAMED QUESTIONS
```

No production code, test, or frozen file was touched; nothing was committed during this checkpoint.
