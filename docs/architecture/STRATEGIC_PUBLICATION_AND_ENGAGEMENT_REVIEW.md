# Strategic publication and external-engagement review

**Review date:** 2026-09-16. **Scope:** fastDICOMattrs, fastDICOMstructure, fastDICOMgateway. Strategic assessment only; no publication draft, implementation, release, deployment, or commit authorized or performed.

> **Addendum, 2026-09-17 (bounded cleanup increment, no change to the text below).** A targeted
> public-release-preparation increment re-verified this review's §8/§9 release-readiness findings
> directly against source, ran the full test suites, performed an external clean-install
> qualification, and made documentation/CI corrections in all three repositories. **No finding
> below was contradicted.** Two items were refined rather than overturned: the Catch2 2.x/3.x
> README mismatch (§8 table) is confirmed to also be a real *external build gap*, not just a
> documentation typo — Ubuntu's `apt` package is 2.x while the actual `CMakeLists.txt` requires
> 3.x, with no automatic fetch fallback; and the gateway `TestClient` "stalled, not established"
> run (§3 corrections item 6, §9) did **not** reproduce in a fresh full-suite run this increment
> (77 passed, 1 expected skip) — reclassified as a pre-existing, non-blocking, unreproduced issue
> rather than left open-ended. See `docs/release/PUBLIC_RELEASE_READINESS_REPORT.md` for the full
> results and `docs/release/FASTDICOM_RELEASE_MANIFEST.md` for the reconciled evidence tuple this
> review called for in §7 step 0 and §13 step 2.

## 1. Executive assessment

**SUPPORTED BY CURRENT EVIDENCE:** this program supports two substantive practitioner contributions: (1) an instrumented, deliberately bounded account of policy before persistence, including failures of the validation apparatus; (2) an architecture case study tracing DICOM semantic ownership through policy, invocation changes, and one existing application's verified component substitution. There is also valuable material for a focused semantic-correctness tutorial and a reusable qualification artifact. None requires inventing algorithmic novelty.

**PLAUSIBLE BUT REQUIRES MORE EVIDENCE:** a research-software paper, a comparative resource/performance study, and stronger claims about reuse. These require different evidence: public development and demonstrated research utility; controlled measurements against capable alternatives; and a genuinely different consumer, respectively. They are not interchangeable next steps.

**NOT SUPPORTED / FALSIFIED:** novelty of a configurable DICOM transformation gateway; novelty of lazy bulk-data handling or component substitution; complete de-identification; general bounded-memory behavior; general reuse established by one familiar consumer. The attractive proposition that no substantial prior art exists has been contradicted. That does not invalidate the measured engineering results.

**Publish first:** the gateway boundary case study, with the observation methods and their failure modes at its center. **Second:** the architecture case study, incorporating S1.5–S1.8 rather than splitting CLI, containers, and substitution into repetitive articles. Begin publication development after accepting this review and reconciling the evidence references; no new feature is needed to justify either narrowly framed article. Actual public publication should have accessible, reproducible supporting artifacts.

**Highest-information-value research next:** determine whether resource advantages observed on attrs' native file path survive the whole-object buffer path used by Structure and gateway, compared with competent deferred-reading alternatives. This tests an important, unresolved architectural tradeoff rather than expanding the product.

All three repositories **require targeted remediation before public release**. They are credible research artifacts, but current documentation, packaging, provenance, and release evidence are not yet aligned. Gateway is suitable for a future **synthetic-data demonstration release**, not production deployment.

### Corrections to existing publication thinking

The [existing assessment](PUBLICATION_EVIDENCE_ASSESSMENT.md) correctly rejects gateway-product novelty and favors practitioner publication, but needs these qualifications:

1. **Performance evidence is not absent.** attrs' [benchmark report](../../../fastDICOMattrs/docs/benchmarks.md) contains sampled real-corpus timing and memory measurements, including approximately 97 MB files. What is missing is a controlled, current, comparative study of the Structure/gateway paths. The capability map's Structure-specific limitations must not erase attrs' earlier evidence.
2. **A1.4 closes a former semantic blind spot.** Historical documents and current README prose still say defined-length Implicit VR sequences are opaque and real Implicit VR data is untested. The later freeze report and parser contradict that blanket statement. Gateway nevertheless continues to reject Implicit VR by application policy.
3. **The gateway is independently pre-existing, not an independent research replication.** Its behavior influenced the policy prototype, and `PolicyReproducesGatewayDemoTest` predates S1.8. Substitution is a useful intervention, but not a blind test with an unfamiliar application or outside team.
4. **S1.8 adopts the policy engine only.** Gateway retains its own parsing, acceptance gate, output verification, HTTP handling, and sink. It does not adopt `execution.run`, Configuration V1, or the filesystem adapters.
5. **S1.7 is local Linux container evidence, not cloud portability.** M4 describes an older gateway deployment. Combining those results does not qualify current S1.8 in Cloud Run.
6. **“Nothing missing except drafting” is too strong operationally.** The narrow arguments are available, but provenance reconciliation, documentation corrections, and a reproducible public evidence package remain. Some experiments ran on dirty trees, some controls were temporary, and one failed refresh record was deleted.
7. **Software-paper readiness has a time dimension.** Current JOSS rules require sustained public development, including at least six months of public history; availability and a DOI alone are insufficient. A second consumer is useful evidence, not a universal formal requirement of software journals. [E15]

## 2. Repository/program reconstruction

### Observed starting state

Established before substantive assessment with `git rev-parse HEAD`, `git status --short --branch`, local history, branches, and tags. No fetch, push, visibility change, or inference that a tracked remote is public.

| Repository | HEAD | Working tree | Local tracking state |
|---|---|---|---|
| attrs | `46bf7d374c2d2d3a5618d31b7b2a2872ce3425f6` | Clean | `main` matches locally recorded `origin/main` |
| Structure | `2efc8ae8a20963f1d18980c00591a0d2217d50ae` | Clean | `main` ahead 1 |
| gateway | `26caca86090a69eaa981236a1b716b7aac36e802` | Clean | `main` ahead 3 |

Only main and origin/main were listed in each repository. attrs and Structure have no listed tags. Gateway's annotated `v0.1.0-demo` resolves to commit `bcde8c38e4500e7ba8bd187667586cebddbd9474`; its release document identifies the earlier M5 implementation `ab3afb2` and old Structure `4eb44cb`. This is a historical demonstration tag, not the A1/S1.8 release.

### Intellectual progression

**First question: can selected metadata change without unnecessarily interpreting bulk content?** The original Structure engine developed source spans, lossless versus modified write contracts, corpus comparison, and a pydicom benchmark in August. These precede A0. attrs inherited this work and its filtered history; it did not start from a new implementation in September.

**Second question: where does transformation sit relative to durable storage?** Gateway's M1–M5 work on September 8 made the architectural question operational: HTTP input, memory serialization, local observation, container restrictions, managed ingress, then independent retrieval from a real store. M1's `memfd_create` workaround was replaced with a proper buffer-write ABI in M1.1. This consumer exposed a useful API gap before the later Structure policy integration.

**Adversarial correction: successful parsing does not mean the policy can see its targets.** Gateway review found top-level-only patient-tag mutation and opaque defined-length Implicit VR sequences. Remediation made mutation recursive and narrowed gateway acceptance to Explicit VR Little Endian. The later A-series tackled semantic visibility in the underlying library; gateway scope was not silently widened afterward.

**A0: make ownership explicit without changing behavior.** The parser, representation, writer, ABI, and bindings moved from Structure to attrs. The earlier project named attrs was renamed fastDICOMscan; it is not this semantic engine. `Structure.apply(policy)` was removed from attrs, while Structure retained a compatibility re-export and policy ownership. Gateway needed container/CI dependency changes. The [A0 report](../../../fastDICOMattrs/docs/architecture/A0_SEMANTIC_ENGINE_EXTRACTION_REPORT.md) records preservation checks rather than a new semantic capability.

**A1: source-preserving mutation requires actual DICOM intelligence.** Dictionary lookup, private-creator scope, Pixel Data ordering, Implicit VR resolution, charset decoding/encoding, and public mutation APIs were qualified incrementally. The discovery was not that DICOM needs these semantics—mature libraries already implement them—but that a lightweight transformation layer cannot safely pretend they do not matter.

**S1: define what a policy means before adding deployment surfaces.** Locators, operation atomicity, diagnostics, and closed configuration preceded execution, CLI, and containers. Qualification forced distinctions between no match, unsatisfied requirement, incomplete guarantee, partial policy, failed rollback, malformed parse, and destination failure. These distinctions are more useful than the increasing test totals.

**S1.8: reject a weak product thesis, then test a smaller architectural proposition.** Prior-art research weakened a hosted/configurable gateway product pitch. The actual intervention became replacing the existing gateway's fixed imperative policy. Gateway `e4cba92` → `26caca8` changes one production file, `transform.py`; `app.py` and `sink.py` are unchanged. Structure production files are unchanged against S1.7 `ffa117f`. That supports a local, specific substitution claim.

### Actual layering versus intended layering

| Layer | Source-level finding | Qualification |
|---|---|---|
| attrs | Owns `src/parser`, dictionary, charset, `mutation.cpp`, source spans, writer, C ABI and Python class named `Structure` | The structural representation itself lives here; Structure does not create a second DICOM object model. “Complete semantics” is too broad for the supported VR/charset/syntax subset. |
| Structure policy | `policy.py` resolves paths and composes attrs mutation calls; text operations call attrs `set_text`/`insert_text` | No second charset codec or dictionary. Creator-aware policy is not available merely because native attrs can resolve creators. |
| Structure configuration/execution | Closed loader; `execute_one` parses, applies, conditionally serializes; `run` adds source/destination; adapters exchange bytes | One concrete filesystem pair. `run_configured` was added in S1.6; “every core file unchanged throughout S1.5–S1.8” would be false. |
| gateway | Imports Structure's re-exported attrs API and calls shared `policy.apply`; independently owns HTTP/store lifecycle | Demonstrates policy reuse, not reuse of the entire execution stack. |

Two minor but real discrepancies remain: attrs' `corpus.py` and benchmark embed demonstration policy code, and public README diagrams still assign policy/audit work to attrs. The former is validation tooling rather than production semantic duplication; the latter misleads prospective users. Three repositories are defensible ownership boundaries, but three separately managed release units impose packaging costs not yet shown to benefit outside users.

## 3. Evidence inventory

**Evidence grades used here:** source/test inspection confirms what is implemented and asserted; committed results record historical observations; a fresh run confirms only the exercised current environment. No count of passing tests substitutes for an explained discriminating assertion.

### A-series: semantics, provenance, and mutation

All reports below are in [attrs' architecture directory](../../../fastDICOMattrs/docs/architecture/).

| Increment / freeze | Question and falsifiable criterion | Implemented/evidence | Failure, freeze, and claim boundary |
|---|---|---|---|
| A0 / `088999d` | Can semantic ownership move without behavioral regression? Same qualified outputs and consumer behavior before/after. | Extraction manifest, baseline, closure; redistributed tests; NLST counts; gateway/container regression. | Gateway Docker build broke when its C++ dependency moved, then was adapted. Freezes ownership extraction, not semantic completeness or performance improvement. |
| A1.1 / `6f05d9d` | Can standard VR knowledge be generated reproducibly rather than guessed? Account for source rows and disagreements. | Pinned PS3.6 XML, generator, generated tables, `test_dictionary*`; full-table pydicom comparison and DCMTK adjudication. | Report identifies 174 newer entries absent from pydicom and 17 deliberately excluded retired wildcard patterns. Repeating-group recognition range required interpretation. No vendor-private dictionary, keyword API, or complete contextual VR resolution. |
| A1.2 / `e651c74` | Does a private element resolve to its own container's creator without scope leakage? | `test_private_creator.cpp`, creator/block identity report; corpus resolution observations. | Missing creator stays unresolved; no inheritance from parent or sibling. Creator identity is not vendor-private meaning, and native API availability is not Python policy availability. |
| A1.3 / `140d850` | Can source-relative Pixel Data placement survive trailing elements and mutation? | `test_pixel_data_ordering.cpp`, writer positional invariant, pydicom reparse. | Old expected-nonidentity assertion fails after correction. NLST, whose pixels are last, is regression evidence only. Freeze includes native/encapsulated ordering, not pixel interpretation. |
| A1.4 / `87e79fe` | Are dictionary-known defined-length Implicit VR sequences visible at every tested depth? | `implicit_vr_le_parser.cpp`; SQ/Item length matrix; malformed boundaries; ambiguous VR tests; 9 existing pydicom fixtures, 372 VR agreements and structural comparison. | Old opacity tests fail as predicted; missing bare-dataset hint added. Some ambiguous VRs remain unresolved; private unknowns are not guessed. A small external fixture set is not scanner-population coverage. |
| A1.5 / `656edf4` | Does decoding respect inherited/overridden charset, VR-specific delimiters, and rejection? | `charset.cpp`, generated tables, `test_charset.cpp`; 67 bundled files, pydicom comparisons, selected DCMTK adjudication. | ST/LT/UT backslash splitting fixed; universal-newline conversion in a harness caused false differences; table generation made deterministic. Selected single-byte, UTF-8 and single-byte ISO 2022 support, not all DICOM charsets. |
| A1.6 / `50369c0` | Can supported text encode/mutate without silent substitution or partial changes? | `test_charset_encode.cpp`, real-file mutation, independent decoding and raw-wire inspection. | Self-introduced UTF-8 validation slowdown fixed in `278578a`; unrepresentable/unsupported text rejects. No dataset-wide transcoding or Japanese/Korean/Chinese code-extension support. |
| A1.7 / `46bf7d3` | Can root/nested insertion and replacement expose those semantics without duplicating them? | `mutation.cpp`, internal container/VR helpers, ABI path tests, Python nested mutation, stale-reference tests and example. | Early leaf-path insertion/upsert design abandoned for parent-container-plus-tag insertion. Python can detect stale wrappers; C++/ABI lifetime constraints remain caller responsibilities. A useful API, not every primitive a complete de-identifier would need. |

The A1.1 report's row-accounting prose should be checked before reproducing its counts: its displayed subtotal equation omits the separately discussed 17 exclusions. Prefer generator output and explicit category reconciliation to copying an internally inconsistent sentence.

### S-series: policies and execution contracts

The named report and matching `tests/python/test_*.py` are the primary evidence for each row.

| Increment / freeze | Question and falsifiable criterion | Evidence / surprise | Supported and excluded claim |
|---|---|---|---|
| S1.1 / `bdc324c` | Do bare, concrete and wildcard locators resolve deterministically without confusing malformed paths and zero matches? | [Locator report](S1_1_LOCATOR_MODEL_REPORT.md), `test_locator.py`; Pixel Data discoverability investigation. | Qualified metadata targeting. Pixel Data cannot be targeted because it is outside the element graph; that also prevents size-based policy through these locators. |
| S1.2 / `53ecb83` | Can text replacement and insertion honor destination context and recover if a later site fails? | [Implementation report](S1_2_REPLACE_ENSURE_IMPLEMENTATION_REPORT.md), `test_ensure_and_text.py`; raw-byte undo replaces semantic reconstruction. | Operation-level mutation behavior; no claim that every ordered policy is transactional. `Ensure` cannot create missing ancestor sequences. |
| S1.3 / `25615dd` | Can outcomes be distinguished without reading values or exception text? | [Report](S1_3_RESULT_DIAGNOSTIC_IMPLEMENTATION_REPORT.md), `test_result_diagnostic.py`; silent raw `set_value(False)` and callback partial mutation corrected. | Known failure vocabulary, operation rollback and remaining-operation status. Earlier successful operations persist after later failure; rollback failures and unknown exceptions propagate. |
| S1.4 / `8879ca7` | Does declarative configuration equal direct construction, and reject unsupported content? | [Report](S1_4_JSON_CONFIGURATION_IMPLEMENTATION_REPORT.md), loader and `test_configuration.py`; extension escape hatch rejected. | Six declarative operation kinds; raw bytes/callbacks remain programmatic. No executable configuration or separate JSON Schema artifact. Compactness/usability benefit remains unproven. |
| S1.5 / `350f88c` | Do direct bytes and filesystem execution share lifecycle and prevent persistence after rejected/partial processing? | [Report](S1_5_EXECUTION_ARCHITECTURE_IMPLEMENTATION_REPORT.md), `test_execution.py`, delegation instrumentation, destination failure/no-overwrite races. | One adapter pair; explicit result and execution eligibility gate. Lenient parse initially misclassified malformed input, then corrected. Whole-file copies, no streaming or bounded-memory result. |
| S1.6 / `9b84a2a` | Does CLI delegate to the same execution path and preserve observable outcomes? | [Report](S1_6_THIN_CLI_IMPLEMENTATION_REPORT.md), `test_cli.py`; black-box equivalence plus call instrumentation. | Tested outputs, JSON and exit semantics. A narrow config-path disclosure exception exists; not universally confidential diagnostics. |
| S1.7 / `ffa117f` | Does the packaged CLI preserve behavior across host/container for success and failures? | [Report](S1_7_CONTAINER_PORTABILITY_IMPLEMENTATION_REPORT.md), `test_container.py`; SHA-256 identity, exit/result comparison, no-network and optional read-only-root probes. | Local Linux x86_64 packaging equivalence. Not multi-architecture, cloud, load, image reproducibility, or container security certification. |
| S1.8 / gateway `26caca8`, closure `2efc8ae` | Can the existing gateway replace four imperative mutations without changing tested behavior or library production code? | [Closure](S1_8_GATEWAY_INTEGRATION_CLOSURE.md), gateway baseline/report and `test_s1_8_structure_policy_integration.py`. | Exact accepted-fixture hash `3bf45c727c1703b7e2f99ff0c5de1f32138eeff8a86caf60770ba9a8dfcdc761`, counts and rejection probes; instrumented real delegation. One fixed policy/consumer, no performance result or cloud requalification. |

S1.6 provenance correction: its report names `7564cf7` as the final freeze, while main contains `9b84a2a`. Both objects exist locally with parent `350f88c`; their diff is only the implementation report (30 added, 2 removed lines). This review verified production equivalence. A public manifest should use reachable `9b84a2a` and explain the documentation-only amendment rather than leave an ambiguous freeze reference.

### Gateway M-series and subsequent corrections

Canonical entry points: [Evidence index](../../../fastDICOMgateway/docs/EVIDENCE_INDEX.md), [publication brief](../../../fastDICOMgateway/docs/PUBLICATION_BRIEF.md), [adversarial closure](../../../fastDICOMgateway/ADVERSARIAL_CLAIM_CLOSURE.md), [adversarial validation](../../../fastDICOMgateway/ADVERSARIAL_VALIDATION_A.md), [remediation](../../../fastDICOMgateway/ADVERSARIAL_REMEDIATION_A.md), and [refresh](../../../fastDICOMgateway/POST_REMEDIATION_EVIDENCE_REFRESH.md).

| Stage | Question / failure criterion | Evidence and finding | What freezes; what does not follow |
|---|---|---|---|
| M1 `7b0fe11`; M1.1 `03f1352` | Can parse→mutate→write→verify avoid ordinary filesystem persistence? | `app.py`, `transform.py`; memory-only body and serialization; old memfd adapter replaced with true buffer ABI. | Mechanism and application sequencing, not runtime absence on every surface. |
| M2 `7d5ca85` | Would a source-bearing write/log appear during four request scenarios? | `m2.py`, syscall attribution, scan/log evidence in `docs/m2_evidence/latest_result.json`. | No observed application persistence in scoped Linux run. Negative control exposed overwrite attribution: final content alone missed earlier writers. Not proof against all encodings, kernel/provider retention, or unobserved surfaces. |
| M3 `1fc9e48` | Does the same behavior hold in a non-root, read-only container without writable mounts? | `m3.py`, container configuration/diff and `docs/m3_evidence/latest_result.json`. | Specific filesystem prevention plus observation. Negative control exposed first-change-kind behavior in `docker diff`; not comprehensive security containment. |
| M4 `d597272` | Is source content observable in both managed request logs and application logs? | `m4.py`, revision/digest and `docs/m4_evidence/latest_result.json`; negative control corrected time attribution. | One historical Cloud Run revision, region, sequential scenario run. Cloud Run writable `/tmp` means M4 is a different boundary, not uniformly stronger than M3. |
| M5 `ab3afb2` | Does independently retrieved durable output contain the tested approved values and preserved pixel hash? | `m5.py`, real STOW/WADO, pydicom snapshots, `docs/m5_evidence/latest_result.json`; deliberately bad object detected in an isolated store. | One targeted instance, not store-wide absence. Data Access audit logs were not enabled; a manual QIDO check is not an automated artifact. |
| Adversarial remediation / refresh | Do previously invisible nested patient tags remain in output? Does unsupported input ever reach the sink? | Reproduced leaks, recursive fix, Explicit VR acceptance gate; M2/M3 refresh JSON; nested PatientID checked after real store/retrieval. | M5 refresh used in-process TestClient, not Cloud Run, and one human ADC identity for write/read. M4 and original identity separation were not refreshed. |

The refresh JSON records then-current HEADs while code was uncommitted. The accompanying report discloses dirty files. Therefore a checkout of the JSON's `gateway_commit` alone does not reproduce the corrected run. Reconcile the eventual commits and source-tree differences in a release manifest; do not alter historical JSON to pretend it was a clean commit.

### Corpus, benchmarks, and fresh review checks

attrs' [corpus report](../../../fastDICOMattrs/docs/corpus-results.md) records 26,634 clean Explicit VR DICOM files round-tripping identically across CMB-MEL and NLST. Two truncated DICOM inputs and non-DICOM license files explain exclusions; structural comparison and transformed metadata readability use pydicom. This is not full semantic/IOD validation, universal round-trip preservation, or a de-identification evaluation. Later A1.4 and A1.5 fixture-library studies extend syntax/charset evidence; their files are existing toolkit fixtures, not an independent hospital cohort.

The [benchmark code](../../../fastDICOMattrs/bench/bench_compare.py) times read/transform/write with native `read(path)`/`write(path)` against ordinary pydicom `dcmread`/`save_as`. The report gives 500 timed typical files, 30 memory samples, and a separate 21-file large series with 15 memory samples: approximately 5.5× median total-time ratio for typical files and 2.1× for large files. Treat these as **reported historical exploratory observations**, not current HEAD measurements. The report identifies a pre-publication working tree, no exact portable large-series manifest, one run, and no variance. The claimed mechanism also needs narrowing: reading PixelData bytes is not pixel decompression; pydicom was not asked for `pixel_array`. Wall-clock durations are not CPU-time measurements. Neither C++ versus Python nor eager versus deferred I/O is isolated causally.

During this review, 12 focused current gateway tests passed (`test_s1_8_structure_policy_integration.py` plus `test_transform.py`), using the existing local native library and virtual environment, with bytecode/cache writes disabled. They verify delegation, frozen output hash, ordinary transformations, rejection, and pydicom checks. This was not a clean rebuild. A broader attempt progressed through eight tests and then stalled at the first TestClient endpoint test; it was interrupted, not counted as passing. The cause was not established. Historical full-suite results (312 native/65 Python attrs; 299 Structure; 77 gateway plus one skip) remain reported historical results, not newly reproduced totals. No cloud, container qualification, or corpus benchmark was rerun.

## 4. Important negative findings

1. **Policy visibility failed before policy intent did.** A clean parse allowed hidden targets in the earlier implicit representation; top-level operations missed nested occurrences even with Explicit VR. These are stronger lessons than “remember to remove more tags.” A1.4 improves semantics; it does not automatically qualify gateway acceptance for the newly supported inputs.
2. **Preservation and safety can conflict.** Pixel Data's absence from the target graph protects it from mutation but also preserves any identifiers in pixels. Unknown opaque content can preserve information a policy cannot inspect. A lossless parser and a de-identifier have different success criteria.
3. **The observation system was fallible.** M2 overwrite attribution, M3 diff semantics, M4 time attribution, charset-harness newline translation, corpus eligibility accounting, and benchmark RSS-parent contamination all affected conclusions. These are several concrete failure classes, not evidence that this process is statistically better than alternatives.
4. **Evidence preservation was imperfect.** The M5 refresh describes deleting its initial failed diagnostic JSON after a hardcoded-canary mismatch. The failure is disclosed, but cannot now be independently reconstructed from that original artifact. Do not advertise a complete preserved record of every failure.
5. **Freezes did not imply immutability of all contracts forever.** S1.3 repairs raw replacement behavior; S1.6 adds composition; A1 closes intentionally recorded limitations. The valuable method is explicit reopening and regression evidence, not “frozen code never changes.”
6. **Semantic round trips are not byte-exact undo.** Charset decode/re-encode can canonicalize padding/escape choices. The raw-byte undo design and deliberately reverted comparison are useful evidence. Operation-level undo does not reset every earlier policy operation or prove external callback side effects reversible.
7. **A small semantic engine still moves large buffers.** File mmap avoids one owned payload representation, but writing touches the payload. Structure reads whole-file bytes, attrs copies buffer input, and serialization returns complete bytes; gateway adds request, verification, and multipart representations. No constant-memory inference follows from non-materialization into `Element.value`.
8. **A missing guarantee need not reject.** `Ensure` with no insertion sites reports `GUARANTEE_UNESTABLISHED` but can leave policy `COMPLETED`/`ACCEPT`. Execution eligibility is not a guarantee that every user-intended condition holds. Author acceptance requirements explicitly and explain this distinction publicly.
9. **The product hypothesis was weakened, not market demand measured.** Prior art establishes competition and established functionality; it does not prove no customer could benefit. Conversely, an implementation and a clean API do not establish a user need.
10. **Several “all” claims exceed actual domains.** attrs has supported subsets; some ambiguous/private VRs and multibyte charsets remain unresolved/unsupported. “All de-identification primitives exist” in A1.7 is stronger than the code warrants, particularly across binding gaps, bulk-data processing, and coordinated identity transformation.

## 5. External prior-art assessment

Research conducted on 2026-09-16 using academic papers/author abstracts, standards, official toolkit documentation and vendor material. Searches targeted competing gateway functionality, pre-storage hooks, deferred DICOM I/O, component substitutability, negative controls, benchmark methodology, and software-publication criteria. This is an adversarial targeted review, not a systematic literature review; failure to locate an identical case study is not evidence of novelty. Vendor statements establish market positioning, not independently verified performance or security.

| Proposed contribution | Strongest challenge found | What remains interesting |
|---|---|---|
| A new configurable DICOM gateway | Karnak already offers profiles, tag actions, DICOM/DICOMweb forwarding and broader identity handling; CTP is longstanding pipeline precedent. DicomShield is a 2026 published proxy using external pseudonymization services. [E1–E3] | A compact, inspectable demonstration with explicit observation boundaries. No new functional category. DicomShield concerns retrieval from an existing PACS, so it does **not** independently establish the exact no-source-persistence property studied here. |
| Policy before storage | Orthanc's SDK exposes received-instance modification/discard before storage; its Lua filter also distinguishes incoming acceptance from stored-instance callbacks. OWASP upload guidance already includes validation/CDR. [E4–E6] | Reproducible failure-sensitive observation across named surfaces. Neither hook documentation nor generic CDR proves what another deployment stores. CDR's reconstruction/security goals differ from byte-preserving metadata transformation. |
| Security/privacy innovation | Established protection principles and DICOM confidentiality profiles already cover fail-safe design and the breadth of identity protection. Commercial Unifier offers de-identification workflows. [E7–E9] | A specific privacy-engineering case, not a compliance result, a claim that identified data never reaches the gateway, or new security theory. |
| Lazy structural processing is a novel speed technique | pydicom supports `defer_size`, `specific_tags`, and `stop_before_pixels`; DCMTK documents deferred loading through `maxReadLength`. [E10–E11] | Measured workload-specific tradeoffs may remain. Compare complete transformation tasks, with pixels preserved, using configured alternatives; metadata-only reads are a separate workload. |
| Separation proven by replacement is new architecture research | Architecture/component composition is established; Lanoix and Kouchnarenko formalize substitutability constraints and simulation, exceeding a finite fixture check. [E12–E13] | A transparent applied case showing which failure semantics and semantic responsibilities made this particular substitution possible. No formal behavioral-refinement proof. |
| Staged negative-control qualification is a new method | Mutation testing has substantial empirical literature; a 2021 study analyzes nearly 15 million mutants. MIDI already provides synthetic-identifier DICOM data and evaluation tools. [E14, E16] | A reusable catalogue of observation failures, particularly attribution and harness contamination. The program has no comparative evidence that its freeze process improves engineering outcomes. |
| Existing speed ratios justify a research benchmark | Rigorous benchmarking literature requires attention to nondeterminism and uncertainty; current results confound implementation/runtime and I/O strategy. [E17] | Preliminary evidence motivates a well-designed measurement study; it is neither worthless nor sufficient for general superiority. |

This review does not endorse the earlier checkpoint's “no solution combines these differentiators” as a research claim. Closed configuration, structured errors, containers, and equivalence tests are common engineering practices; a unique conjunction does not establish usefulness or scholarly novelty.

## 6. Candidate publication portfolio

Estimates below are planning ranges for focused work, excluding editorial review, permissions, external recruitment, and cloud scheduling. They are not implementation authorizations.

### Candidate A — Observing the persistence boundary

**Working thesis:** For specified synthetic inputs and observed deployment surfaces, a policy-first gateway withheld rejected inputs from its persistence path and independently retrieved approved transformed attributes, while injected violations exposed weaknesses in the checks themselves.

**Type / audience / form:** security/privacy engineering lesson, empirical case study and practitioner methods article; imaging-platform engineers, privacy engineers, SREs. Canonical technical article plus reproducible demonstration; suitable talk material.

**Available:** M1–M5 reports/JSON, validation source, adversarial experiments, remediation and refresh, source sequencing in `app.py`/`transform.py`/`sink.py`. Source→transformed→retrieved comparisons use a separate DICOM implementation for selected fields.

**Missing:** a reconciled version/dirty-tree manifest and accessible reproduction package; retained machine-readable negative-control runs for every claimed control are not uniformly available. Current-stack M4/M5 qualification is needed only if the article claims current deployed behavior rather than explicitly historical results.

**Prior-art risk:** pre-storage filtering and de-identification are already implemented elsewhere, especially Orthanc/CTP/Karnak. **Overclaiming risk:** “no PHI ever persisted,” store-wide absence, current S1.8 cloud qualification, all-infrastructure observability, and complete de-identification.

**Additional work:** roughly 2–5 days for evidence/version reconciliation and release-oriented reproduction instructions; separately scoped deployment work if current cloud evidence is wanted. No new product feature required. **Independence:** the first canonical story owns M-series persistence observations and their controls; later pieces should link rather than retell them.

### Candidate B — Testing the semantic/policy boundary

**Working thesis:** A DICOM semantic engine and policy layer preserved their ownership boundaries across tested library/CLI/container execution and one pre-existing gateway's fixed-policy substitution without changing the libraries for that substitution.

**Type / audience / form:** useful engineering architecture, component-substitution case study and practitioner lesson; library maintainers and application architects. One article/talk, with an evidence appendix; not a novel systems algorithm.

**Available:** A0/A1 ownership record, S1.1–S1.7 qualification, S1.8 baseline/intervention/hash/instrumentation. Concrete difficult cases include charset scope, raw undo, partial results, and lenient parse handling.

**Missing:** no further experiment needed for this finite case claim; public reproducibility and corrected references remain. A different application and preferably outside integrator are needed for broader reusability/usability claims.

**Prior-art risk:** ordinary modularity and testing-based substitution are established. **Overclaiming risk:** equating related same-team implementations with independent replication, treating one tiny policy as exhaustive substitution, or attributing gateway cloud results to Structure's execution core.

**Additional work:** approximately 2–4 days to make the cross-repository version bundle and examples reproducible, overlapping release cleanup. **Independence:** distinct question from A: who owns semantics and what changes under substitution, rather than where source content is observed. CLI and container equivalence are evidence within B, not separate publications.

### Candidate C — Metadata policy fails when semantic visibility fails

**Working thesis:** Correct selective DICOM mutation depends on structural visibility, scope-aware VR/charset interpretation, and explicit failure contracts, as demonstrated by concrete failures and qualified fixes.

**Type / audience / form:** DICOM practitioner lesson, software-quality case study and semantic-engineering tutorial; engineers implementing ingestion/transformation. A focused technical article or tutorial with synthetic executable examples.

**Available:** gateway nesting/Implicit VR findings; A1.2 scope isolation, A1.3 ordering, A1.4 sequence expansion, A1.5/6 delimiters and encoding, A1.7 parent-context insertion, S1.2/3 rollback tests.

**Missing:** curate a small standalone example set and explicit supported-syntax/repertoire table; distinguish shared-oracle checks from independent adjudication. No claim of finding new DICOM rules.

**Prior-art risk:** DICOM standards and mature toolkit implementations already solve these semantics. **Overclaiming risk:** portraying subset support as complete or ordinary dictionary lookup as novel. **Additional work:** 2–4 days of artifact curation/documentation, with little new engineering. **Independence:** worth a separate contribution only if the examples teach DICOM semantics in depth; otherwise use as B's supporting appendix. Do not publish a seven-part A1 milestone diary.

### Candidate D — Qualifying the checks, not just the system

**Working thesis:** Injected violations and independent comparisons in this program revealed distinct measurement/attribution defects that ordinary successful runs did not reveal.

**Type / audience / form:** negative result, validation/process lesson, reproducibility contribution; test engineers and experimental systems researchers. A methods note or reusable artifact; a research paper only after a larger evaluated study.

**Available:** M2/M3/M4 control findings, M5 refresh canary mismatch, corpus accounting, RSS-parent artifact, newline translation, raw-rollback differential tests.

**Missing:** portable retained fail/pass examples, explicit threat-to-detector matrix, sensitivity against withheld faults, and comparison with simpler checkers. The deleted failed refresh artifact limits retrospective evidence.

**Prior-art risk:** fault injection/mutation testing is mature; MIDI already supplies DICOM synthetic-identifier evaluation data. **Overclaiming risk:** saying a checker that catches one fault detects all leaks, or claiming the freeze methodology causes better quality. **Additional work:** 1–2 weeks for an isolated runnable artifact; longer for a defensible comparative study. **Independence:** keep gateway controls inside A now. Spin this out only if the cross-program taxonomy and reusable detector evaluation add enough new evidence to avoid duplication.

### Candidate E — Resource costs of preserving bulk data through abstraction layers

**Working thesis:** The resource benefit of source-backed DICOM metadata transformation depends on acquisition/serialization boundaries, and must be measured end to end rather than inferred from the object model.

**Type / audience / form:** performance-engineering lesson now; future empirical/benchmark result, potentially workshop or systems paper. Imaging infrastructure and systems researchers.

**Available:** historical attrs benchmark/code, source-memory implementation, Structure's disclosed copies, gateway body/multipart path, locator/charset microbenchmarks.

**Missing:** matched semantic workloads; tuned pydicom and DCMTK baselines; file versus buffer versus HTTP paths; corpus manifest; repetitions and uncertainty; memory-accounting separation; current version pins and raw data. A research result is not yet present for this thesis.

**Prior-art risk:** deferred reads already exist; C++ beating a Python default is unsurprising. **Overclaiming risk:** conflating raw payload reads and pixel decode, wall and CPU time, mapped pages and owned heap, or a local native-path ratio with gateway throughput. **Additional work:** approximately 2–4 weeks for a rigorous first study after a small measurement pilot. **Independence:** genuinely distinct if it measures costs and explains a result; not another architecture article repeating “pixels untouched.”

### Candidate F — A reusable research-software release

**Working thesis:** The semantic library plus declarative policy layer provide a documented, reusable artifact for reproducible selective DICOM transformation research within stated support limits.

**Type / audience / form:** software artifact and reproducibility contribution; research-software engineers and imaging-methods developers. Coordinated open-source releases/archival first; potentially one software paper covering the coherent core, with gateway as an example.

**Available:** libraries, ABI, fixtures, generation provenance, examples, extensive tests and engineering history. attrs contains the most substantial standalone technical implementation; Structure supplies a useful higher-level interface.

**Missing:** working external installation, dependency compatibility/version policy, public development, demonstrated research use, and independent-user feedback. For JOSS specifically, current public-history and research-impact gates apply. [E15]

**Prior-art risk:** another DICOM library competing with established toolkits; a wrapper alone may fail significance review. **Overclaiming risk:** equating private tests with adoption or asserting three separate software papers are warranted. **Additional work:** approximately 1–3 weeks for release/package/reproduction remediation, then real public use and development over time; no guaranteed acceptance. **Independence:** an artifact citation can support all articles, but a software paper must establish user value rather than retell A/B.

**Not recommended as standalone candidates:** a novel gateway product paper; one article per deployment adapter; an announcement of test totals; a broadly superior DICOM benchmark based on existing ratios; an article whose main result is discovering competitors exist. Preserve that last finding as scope correction, not a substitute for technical contribution.

## 7. Recommended publication sequence

| Order | Canonical source and decision | Why this order |
|---|---|---|
| 0 | Reconcile and release a versioned evidence bundle after targeted remediation; this review remains internal strategy until separately approved. | Readers must be able to identify what actually ran. Package existing research before adding a feature backlog. |
| 1 | Candidate A; gateway evidence index plus corrected manifest, frozen JSON and validation code are canonical evidence; substantive article is the narrative source. | Most concrete operational question and richest independent observations/negative controls; establishes why correctness at this boundary matters. |
| 2 | Candidate B; Structure S1.8 closure anchors the result, linked to S1.3/S1.5/S1.7 and attrs' semantic reports. | Complementary ownership/substitution question. Include deployment equivalence in the same argument. |
| 3, conditional | C if DICOM examples sustain a distinct tutorial; otherwise publish them as supporting material for B. | Technical depth without manufacturing new research claims. |
| 4, result-dependent | E after controlled study; D only after portable detector evaluation. | Let findings determine thesis and venue, including a negative resource result. |
| Later | F software paper when real use, packaging and venue criteria are met. | Open release is an earlier enabling step; a paper is not its automatic immediate consequence. |

Use the existing brief's proposed pysynapse technical home for full canonical articles if that identity remains the author's preference; Palmer Cove can carry a clinical-workflow summary linking to the technical source. Do not maintain competing full versions. GitHub/versioned archives own code and evidence; an article owns interpretation; this strategic review does not become the publication itself.

Potential later peer-reviewed forms are an imaging-informatics methods/application paper or research-software/systems workshop study. No specific acceptance claim or current submission deadline is made. A general systems conference submission today would be premature: neither a new technique nor a sufficiently broad comparative result has been established.

## 8. Public-release readiness by repository

### Audit scope and common findings

Read tracked manifests, source/tests, CI/Dockerfiles, documentation, JSON evidence, fixture provenance, local branches/tags and history. A pattern scan inspected every tracked file and every reachable historical blob: **384 attrs, 261 Structure, 82 gateway**. It searched private-key headers, common Google/GitHub/AWS key forms, and quoted credential assignments; **no matches**. It also found no tracked/reachable-history paths with the checked `.dcm`, `.pem`, `.key`, `.p12`, `.env`, `.zip`, `.tar`, `.so`, `.pdf` suffixes. This does not establish absence of arbitrary credentials, PII, proprietary rights, ignored local content, inaccessible refs, or remote-only material. No dependency vulnerability database audit or legal clearance was performed.

Synthetic fixtures are visible source-built byte streams; real TCIA corpora are not committed. Gateway fixture comments assert synthetic data, but person-like dates/names should still receive owner confirmation, not automatic privacy clearance. Documentation includes local account paths, cloud project/service identifiers, and a name from a third-party sample; these are not automatically secrets or PHI. Review their publication necessity and provenance. Preserve original historical evidence privately if a sanitized public derivative is needed, with explicit redaction notes and checksums.

All repositories contain the Unlicense. This covers the project's rights, not automatically bundled NEMA XML or derived third-party data. DICOM's copyright/permission provisions exist independently of access to the download. Document the applicable redistribution basis and attribution for the complete XML and generated dictionary, and audit charset-table provenance/notice requirements. This review identifies a clearance gap, not a finding of infringement. [E18]

| Repository / verdict | Concrete findings | Minimum release work |
|---|---|---|
| **attrs — requires targeted remediation** | README still says no dictionary/opaque Implicit VR and no real Implicit VR validation, contradicted by A1.4. It assigns policy to attrs in diagrams, calls semantics complete, and links a moved pipeline example at its old local path. README requires Catch2 2.x; tests require 3. Python is a copied/checkout binding, with no package manifest. Benchmark claims exceed precision of method. Vendored PS3.6 has provenance but no clear project-level third-party distribution notice. | Publish current support matrix and historical-results labels; correct build/example paths; clarify C++ install versus Python checkout procedure; reconcile third-party notices; provide exact tested versions and clean install/test recipe. Wheels are desirable, not prerequisite for an honest source release. |
| **Structure — requires targeted remediation** | Has `pyproject.toml`, but no declared installable attrs dependency; sibling-path injection remains. CI checks out moving attrs default branch and does not explicitly install pytest. Container qualification skips when prebuilt image is absent; CI does not build that image. Capability map contains old dependency/status prose. S1.6 freeze hash and publication assessment need reconciliation. | Pin compatible repository tuple; explicit test dependencies; demonstrate source installation outside author's checkout layout; make optional skips visible and provide a container qualification job/recipe; standalone sample JSON policy; resolve provenance and stale claims. Do not promise `pip install` provides native dependencies. |
| **gateway — requires targeted remediation; demonstration only** | Best evidence inventory, but historical cloud artifacts differ from current engine/policy. `transform.py` still says Structure has no pyproject/native library and that dictionary-backed Implicit VR was not implemented. UID comments say “never patient data” while arbitrary input UIDs are logged on success; synthetic fixture safety does not generalize. Dependencies have broad lower bounds, no lock; Docker base is a mutable tag. Cloud identifiers/URLs and internal paths are present. Prior demo is explicitly unauthenticated. | Reconcile implementation/evidence versions, correct dependency and UID/privacy prose, label synthetic-only operation, inventory identifiers for release, pin an evaluated environment and improve three-repo reproduction. Do not silently publish live resource details as an invitation to use the endpoint. Production hardening is a separate goal, not required to publish a clearly bounded demo. |

Additional precision: filesystem destination uses file `fsync` plus atomic link/replace; no parent-directory fsync is present in the inspected implementation. Tests support atomic publication/no-overwrite behavior, not arbitrary crash/power-loss durability. Likewise, fixed safe diagnostic strings do not prove all unexpected tracebacks are PHI-free: gateway uses `logger.exception`, and unknown callback/rollback exceptions can carry more information than modeled diagnostics. Treat these as limits on claims and future fault probes, not newly demonstrated leakage incidents.

Public remote visibility was not authenticated or changed. Existing local documents state repositories were not yet published; that historical statement and an `origin/main` ref are insufficient to certify current external availability. Resolve visibility and public-history dates when planning release/submission.

## 9. Gaps in current evidence

**Most important for credible publication now:** an externally reproducible, version-matched evidence package. It must distinguish historical deployment, corrected dirty-tree refresh, A0 extraction, A1 semantic advances, and S1.8 local substitution. A clean checkout of three advertised HEADs is not a reproduction of every JSON record.

**Most important for stronger architectural claims:** a second materially different consumer with a real task and an integrator not already relying on this ecosystem. CLI/container are invocation variations, not independent application demand.

**Most important for performance claims:** current end-to-end resource measurements with equivalent policies and deferred-I/O baselines. Existing evidence is valuable but does not measure the path Structure/gateway now use.

Other explicit gaps: representative vendor/modality/syntax/charset coverage beyond selected fixture sets; automated store-wide discovery; current Cloud Run qualification; error-path logging under adversarial exceptions; resource exhaustion/concurrency/cancellation; complete machine-readable retained controls; external installation and user feedback; independent configuration usability; full distribution/license inventory. These gaps should not all become mandatory engineering before the first historical case study—each blocks a particular stronger claim.

## 10. High-information-value future research

Ranked by expected information value, not feature count. No implementation authorized.

| Rank / question | Discriminating experiment and outcomes | Effort / decision value |
|---|---|---|
| **1. Do source-backed benefits survive the actual execution boundaries?** | Hold metadata/policy constant while varying pixel payload (small to hundreds of MB), metadata count/nesting, file vs memory vs HTTP path. Compare native attrs, Structure execution and gateway against ordinary/deferred pydicom and suitable DCMTK complete-output workflows. First establish equivalent semantic outputs and preserved pixels. Measure wall/CPU, peak RSS/PSS/owned heap where available, page faults, bytes copied and output cost; randomize order, repeat, report uncertainty and cache state. | 2–4 weeks. Similar memory slopes would refute broad boundary-path advantage; an attrs-only benefit localizes the cost; a robust full-path benefit supports a comparative result. A null or negative result is valuable. Do not build streaming first. |
| **2. What does an unfamiliar consumer force across the boundary?** | Give an outside integrator a frozen installable core and a real non-gateway task, such as offline imaging metadata QA/normalization. Include nested text/charset failures and destination failure; record required core changes, workarounds, implementation time and rejected requirements. Compare with implementing the task using an established toolkit. | 1–3 weeks plus recruitment. Unchanged-core success supports one additional reuse case; semantic leakage exposes the wrong seam; little user benefit challenges decomposition even if tests pass. |
| **3. How sensitive are persistence detectors to realistic violations?** | In an isolated synthetic-only harness, inject overwrite/delete, encoded/logged canaries, unexpected exceptions, concurrent attribution, alternate storage identity and delayed observations. Separate training controls from withheld faults. Compare filesystem snapshots, syscall traces, log scans and retrieval/enumeration; retain every failure. | 1–2 weeks local, more for separately authorized cloud work. Estimates a detector's coverage and blind spots; does not estimate universal leakage probability. Makes D a distinct contribution. |
| **4. Where do semantic policies disagree across real encodings?** | Stratify a license-cleared manifest by syntax, charset, private/ambiguous VR and nesting; supplement scarce cells with labeled synthetic cases. Use pydicom/DCMTK plus standards adjudication, not majority vote alone. Test mutation, diagnostics, untouched-value preservation and failures. | 2–4 weeks. Distinguishes support-boundary failures, harness normalization artifacts and genuine engine errors. A1.4/A1.5 are starting evidence, not a substitute for this distribution. |
| **5. Can bulk-data-aware admission remain separate from bulk decoding?** | Specify metadata-only decisions requiring presence/kind/extent; inventory what C++ exposes versus Python. Test whether a minimal read-only descriptor suffices without putting Pixel Data into the mutation graph. Evaluate native and fragmented cases, unknown extent and malformed fragments. | Several days for design/probe, implementation separate. Distinguishes a binding gap from a model limitation; success enables size policy but does not by itself bound ingress memory. |
| **6. Which failures change behavior across deployment contexts?** | After local contracts stabilize, compare current CLI/service/container/cloud under cancellation, read-only paths, memory limits, cold starts and retries. Require identical intended outcomes, not identical latency or every byte of environmental diagnostics. | Separately scoped infrastructure effort. Useful when deployment assumptions are the question; another happy-path serverless adapter alone has low information value. |

Streaming deserves investigation only after rank 1 shows where copies/time matter and after defining backpressure, source lifetime, late rejection, and output commit semantics. A sequential API cannot promise no partial persistence simply by using the word “stream.” UID remapping, OCR, more adapters, batch orchestration and a product UI are not recommended as publication-driven features.

## 11. Engagement/distribution strategy

Use one canonical article URL per argument and immutable artifact/version links. A short professional post should communicate one concrete finding and its limit, then direct readers to the full evidence; it should not become the only place where an important result or caveat exists.

For A, engage imaging-platform and privacy/SRE audiences around observation surfaces and negative controls. For B/C, seek technical discussion among DICOM toolkit maintainers, research-software engineers and architecture practitioners around failure contracts, scope and substitution. A talk should demonstrate one successful case and one control that fails, rather than parade milestone counts. For E, distribute measured workloads/raw data and invite reproduction only after results exist.

Use LinkedIn and the proposed Palmer Cove companion as distribution, with pysynapse or another durable author-controlled technical site as the canonical narrative. Repositories/archives hold executable evidence. Seek feedback through authorized future community posts or direct review invitations; no outreach was sent in this review.

Measure substantive outcomes: successful outside reproduction, corrections received, integrations attempted, benchmark reruns and useful disagreement. Views and article count are secondary. Publish corrections visibly and maintain an evidence/version index so later work does not silently rewrite the historical claims.

## 12. Claims to avoid and skeptical-reviewer answers

| Skeptical question | Answer supported by this review |
|---|---|
| Three useful components or needless decomposition? | Semantics/policy/application are distinct responsibilities in the code. Separate repositories are not yet proven necessary; missing package integration is a real cost. Do not confuse a good module boundary with a validated distribution strategy. |
| Is attrs differentiated from mature libraries? | Its source-span representation, explicit mutation/preservation contracts and small native surface are useful choices. Dictionary/charset support and lazy pixels are established. Differentiation requires workload or usability evidence, not the name “fast.” |
| Does Structure solve a real user problem? | It expresses and runs policies for this program. External demand and reduced user effort remain unmeasured; S1.4 explicitly declines the usability claim. |
| Is byte identity scientifically interesting? | It is a strong finite regression criterion, especially for uncontrolled normalization. Alone it proves neither correct policy nor novelty. Pair it with independent semantic checks, rejection cases and instrumentation. |
| Does staged qualification teach outsiders something? | Concrete failures teach scope, attribution, rollback and oracle design. Freeze/test-count discipline alone is ordinary careful engineering; no comparative process study exists. |
| Are we confusing engineering with research? | A/B/C are engineering contributions worth publishing as such. E or an evaluated D could become empirical research. Current evidence does not establish a novel algorithm or new general system principle. |
| Would experienced DICOM engineers find this obvious? | They know the standards and existing gateways. They may value compact reproductions of charset/nesting failures, exact limitations, and a transparent account of how apparently adequate validation missed them. |
| Are stronger domains outside DICOM relevant? | Upload/CDR, document metadata, telemetry redaction and ETL have analogous persistence/observation issues. Transfer the questions, not untested claims of cross-domain validity. |
| What is undervalued? | The repeated finding that the checker, not just the system, needed correction; the real distinction between semantic recovery and raw-byte restoration; and the existing native benchmark that later summaries overlooked. |
| What would a paper reviewer reject immediately? | Generic gateway novelty, no capable comparison, claiming no PHI from a few canaries, one correlated consumer called general reuse, absent reproducibility, and speed ratios treated as causal proof. |
| What would a practitioner read? | An exact account of which boundary was observed, which injected violation the harness missed, how it was fixed, and what remained outside the claim. |

Explicitly avoid: “HIPAA compliant”; “PS3.15 conformant”; “de-identified” as a guarantee for the fixed three-tag/private policy; “no source data reaches any provider”; “every stored object was checked”; “UIDs are never sensitive”; “all charsets/VRs”; “no memory copies”; “bounded memory”; “streaming”; “cloud-independent”; “formally verified”; “all other bytes preserved” for arbitrary modified writes; “universally reusable”; “reproducible image” merely because Docker builds; and current performance claims copied from historical working-tree measurements.

## 13. Recommended next actions

1. **Accept or revise the two primary publication scopes.** Recommend beginning A now as a bounded historical technical argument; B follows as the complementary architecture case. This review does not draft either.
2. **Authorize targeted release/evidence remediation separately.** Prioritize version reconciliation, third-party notices, current capability/build documentation, external install reproduction and a visible optional-test matrix. Keep original evidence unchanged; add mappings/corrections rather than retrospectively cleaning results.
3. **Package one exact three-repository tuple and one historical gateway evidence tuple.** State which tuple supports which claim. Label dirty-tree refresh reconstruction explicitly. No need to redeploy merely to tell the historical story accurately.
4. **Commission rank-1 resource characterization as the next research increment.** Begin with a small controlled pilot using existing paths, then scale only if measurements discriminate among hypotheses. This is more informative than adding another deployment adapter. No implementation was begun here.
5. **Seek an independent integrator after installation is usable.** Treat difficulties and a decision to prefer an established toolkit as valuable evidence, not failed marketing.
6. **Revisit software-paper eligibility after genuine public use/development.** Do not create nominal releases or empty activity to satisfy a venue checklist.

**Completion state:** only this report was created. Production code, tests, prior documents and frozen artifacts were not edited. No commits, publication drafts, visibility changes, cloud operations or messages to third parties were performed. Final repository verification is recorded in the accompanying response.

## 14. Sources

### Local primary evidence

Paths in the evidence inventory above identify the corresponding reports and tests. Additional source files inspected include attrs `src/source.cpp`, `src/parse.cpp`, `src/parser/implicit_vr_le_parser.cpp`, `src/internal/vr_inference.cpp`, `include/fastdicomattrs/pixel_data_reference.hpp`, dictionary/charset generators and fixture provenance; Structure `__init__.py`, `policy.py`, `configuration.py`, `execution.py`, `adapters/filesystem.py`, packaging/CI/Dockerfile; gateway `app.py`, `transform.py`, `sink.py`, validation modules and JSON, integration/recursive-policy tests, packaging/CI/Dockerfile. History was inspected to distinguish old Structure engine commits from extracted attrs history and subsequent freezes.

Publication-related material reviewed comprises Structure's `PUBLICATION_EVIDENCE_ASSESSMENT.md`, `PRODUCT_CAPABILITY_MAP.md`, `POST_A1_RUTHLESS_INVENTORY.md`, S1.8 design/integration/closure documents; gateway's `PUBLICATION_BRIEF.md`, `DEMO_RELEASE.md`, `EVIDENCE_INDEX.md`, M2–M5 reports, adversarial closure/validation/remediation and post-remediation refresh, plus `publication_validation/` and refresh harness/artifact content. Those files reference earlier article candidates outside these repositories; their publication status/content was not independently audited and they were not drafted or modified here.

### External primary sources, accessed 2026-09-16

- **E1.** [Karnak source and feature documentation](https://github.com/nroduit/karnak); [official documentation](https://karnak.weasis.org/en/index.print.html). Direct counterexample to novel declarative gateway functionality; not an audit of its persistence internals.
- **E2.** [A Web-Based Institutional DICOM Distribution System with the Integration of the Clinical Trial Processor](https://pmc.ncbi.nlm.nih.gov/articles/PMC4346661/); [RSNA MIRC CTP documentation](https://mircwiki.rsna.org/index.php?title=MIRC_CTP). Established pipeline/anonymization precedent.
- **E3.** Oehm et al., [DicomShield: A Pseudonymization Proxy for the Secondary Use of Imaging Data in the Research Context](https://pubmed.ncbi.nlm.nih.gov/42175132/), *Studies in Health Technology and Informatics* 336:1506–1510, 2026-05-21, DOI [10.3233/SHTI260460](https://doi.org/10.3233/SHTI260460). Assessment based on bibliographic record and author abstract, not a full implementation audit.
- **E4.** [Orthanc Plugin SDK callbacks](https://orthanc.uclouvain.be/sdk/group__Callbacks.html), particularly `OrthancPluginReceivedInstanceCallback`.
- **E5.** [Orthanc Lua scripting](https://orthanc.uclouvain.be/book/users/lua.html), incoming-instance filtering versus stored-instance events.
- **E6.** [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html). Ingress validation/CDR precedent; not DICOM-specific evidence.
- **E7.** Saltzer and Schroeder, [The Protection of Information in Computer Systems](https://www.cs.virginia.edu/~evans/cs551/saltzer/), 1975, primary paper reproduced by University of Virginia.
- **E8.** [DICOM PS3.15, Attribute Confidentiality Profiles](https://dicom.nema.org/medical/dicom/current/output/chtml/part15/chapter_E.html). Normative scope beyond a few patient tags; relevant to non-claims, not a compliance assessment.
- **E9.** [Dicom Systems: de-identification](https://dcmsys.com/solutions/de-identification/). Vendor-described commercial capability, not independently validated here.
- **E10.** [pydicom 3.0.2 `dcmread`](https://pydicom.github.io/pydicom/stable/reference/generated/pydicom.filereader.dcmread.html). Deferred values, selective reads, and stop-before-pixels semantics.
- **E11.** [DCMTK `DcmFileFormat` public header](https://raw.githubusercontent.com/DCMTK/dcmtk/master/dcmdata/include/dcmtk/dcmdata/dcfilefo.h), `read`/`loadFile` documentation of `maxReadLength` and loading on access. Some rendered documentation pages returned access errors; the official source header was accessible. This is API precedent, not a newly run DCMTK benchmark.
- **E12.** Garlan and Shaw, [An Introduction to Software Architecture](https://www.sei.cmu.edu/library/an-introduction-to-software-architecture/). Established composition/architecture background.
- **E13.** Lanoix and Kouchnarenko, [Component Substitution through Dynamic Reconfigurations](https://arxiv.org/abs/1404.0848), 2014. Formal substitutability precedent; author abstract consulted.
- **E14.** Petrović et al., [Does mutation testing improve testing practices?](https://arxiv.org/abs/2103.07189), ICSE 2021. Large-scale empirical prior art for injected-fault evaluation; author abstract consulted.
- **E15.** [JOSS submission requirements](https://joss.readthedocs.io/en/latest/submitting.html), [review criteria](https://joss.readthedocs.io/en/latest/review_criteria.html), [paper requirements](https://joss.readthedocs.io/en/latest/paper.html). Current eligibility, public development, research utility, packaging and disclosure expectations; recheck at submission time.
- **E16.** Rutherford et al., [Medical Image De-Identification Resources: Synthetic DICOM Data and Tools for Validation](https://arxiv.org/abs/2508.01889), 2025. MIDI synthetic-identifier corpus/evaluation precedent; author abstract consulted.
- **E17.** Kalibera and Jones, [Rigorous Benchmarking in Reasonable Time](https://kar.kent.ac.uk/33611/), ISMM 2013. Primary author repository and manuscript; measurement uncertainty precedent.
- **E18.** [DICOM Standards Committee policies and procedures](https://www.dicomstandard.org/docs/librariesprovider2/dicomdocuments/wp-content/uploads/2017/11/dicom-policies-and-procedures-2020-04.pdf). See copyright provisions; establish the actual redistribution basis for vendored standards independently of the repository's Unlicense.

No claim in this review depends on an absence-of-search-results novelty argument, a third-party marketing performance figure, or assuming a paper's title proves it tested this program's exact persistence property.
