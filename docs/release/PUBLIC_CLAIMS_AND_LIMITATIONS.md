# Public claims and limitations

Not marketing copy. This establishes what can be honestly said about the release-candidate tuple
recorded in [`FASTDICOM_RELEASE_MANIFEST.md`](FASTDICOM_RELEASE_MANIFEST.md) — currently
`fastDICOMattrs@24efab8` (internal qualification identifier, post PS3.6.xml remediation),
`fastDICOMstructure` closure in progress, `fastDICOMgateway@26caca8` not yet re-closed against
attrs `24efab8` — and what cannot yet be said. Every row below is grounded in a specific report,
test, or measurement — not in what the architecture *should* eventually be capable of.

## Potentially supportable today

| Claim | Exact qualification | Evidence |
|---|---|---|
| "Lightweight native DICOM structural/semantic transformation" | Within the documented scope in `fastDICOMattrs/docs/SUPPORTED_SCOPE.md` (Explicit VR LE + Implicit VR LE, dictionary-driven, selected charsets) — not "every VR/charset/transfer syntax" | A0–A1.7 freeze reports |
| "Source-preserving mutation within stated support boundaries" | Byte-identical write only for unmodified, Explicit-VR-parsed, lossless structures; mutation-aware writing produces valid but not byte-identical output | `docs/roundtrip-contract.md`, A1.7 |
| "Declarative metadata policy" | A closed, fail-closed JSON vocabulary (`Require`, `Remove`, `ReplaceText`, `EnsureText`, `AllowListPrune`, `PrivateTagPolicy`); raw-byte/callback operations remain Python-only | S1.4 design + implementation reports |
| "Local library execution" | Direct Python API (`fastdicomstructure.policy.apply`, `execution.run`) | S1.1–S1.5 |
| "CLI execution" | `python -m fastdicomstructure run --config ... [--json]`, tested black-box equivalent to direct construction | S1.6 |
| "Tested Linux container execution" | One platform (Linux x86_64), one Docker daemon, S1.7's 21-probe qualification suite; re-verified from a fresh external checkout this increment (with a build-cache caveat — see the release manifest §6) | S1.7 |
| "One verified application integration" | `fastDICOMgateway`'s S1.8 substitution: policy engine adopted, byte-identical to the prior imperative implementation, for one fixed demonstration policy | S1.8 closure |
| "Tested preservation of bulk Pixel Data without pixel decoding, for the qualified workflows" | Pixel Data is referenced by source byte range only, never decoded; confirmed across the corpus and in gateway's own tests | A1.3, `docs/corpus-results.md`, gateway `test_transform.py` |
| "Open-source / reference implementation" | All three repositories under The Unlicense (attrs additionally vendors third-party NEMA material — see `THIRD_PARTY_NOTICES.md`) | LICENSE files |

## Requires qualification (do not state unqualified)

| Term | Current evidence | What stronger interpretation is NOT supported |
|---|---|---|
| "Fast" | `fastDICOMattrs`' native path is ~5.5x faster (median, wall-clock) and ~2.1x faster on large-Pixel-Data files than pydicom, on one historical, single-run, single-machine measurement | Not a controlled multi-run study; not measured through Structure's or the gateway's whole-object-buffer/HTTP paths; not CPU time (wall-clock only) |
| "Low memory" | attrs' native path shows roughly half pydicom's peak RSS on large files in that same historical run | No measurement exists of Structure's or the gateway's end-to-end memory (Structure reads whole-file bytes; gateway adds request/multipart representations) |
| "Scalable" | No supported meaning today | No load, concurrency, or throughput measurement exists at any layer |
| "Privacy-preserving" | The gateway's demo policy removes/replaces a fixed 3-tag set plus private elements, observed (M1–M5, for the prior imperative implementation) not to leak source bytes to the surfaces checked | Not validated against arbitrary real clinical content; UIDs are not scrubbed and are logged on success (see `transform.py`'s corrected UID scoping note); no claim about pixel-burned-in PHI |
| "De-identification" | A fixed 3-tag demonstration policy exists; declarative policy primitives exist | Explicitly not a complete de-identification implementation, not PS3.15-conformant, not a profile — `fastDICOMstructure`'s own capability map declines this claim (P1.4, DEFERRED) |
| "Cloud-ready" | The gateway was once deployed to Cloud Run (M4/M5, historical, pre-S1.8) | Not re-qualified against the current S1.8 tuple; "cloud-ready" as a present-tense claim is not supported until that re-qualification happens |
| "High throughput" | No throughput measurement exists at any layer, on any deployment target | Cloud Run/container *existence* is not throughput evidence |
| "General purpose" | Explicitly scoped to DICOM; not extended to any other format | See "Do not generalize the implementation beyond DICOM" (this increment's own constraint) |

## On "scaling from local development toward cloud execution"

The project intends, eventually, to describe the software this way. What current evidence
actually supports, as of this tuple:

- The gateway **has run** on Cloud Run (M4/M5), but that evidence describes an older,
  pre-S1.8 imperative implementation and was not gathered against the current tuple.
- No current-tuple Cloud Run qualification, load test, or concurrency test exists.
- The bounded resource-characterization experiment proposed in the strategic review (rank-1: do
  source-backed benefits survive the actual execution boundaries?) has **not been started** — it
  is explicitly out of scope for this increment.

**What can honestly be said today:** the architecture has previously been deployed to a managed
container platform and the reference application demonstrates the shape such a deployment would
take; no current performance, scalability, or throughput claim is supported for the tuple in
§1 of the release manifest. Do not claim "cloud-ready" or "scales to production traffic" until a
current-tuple deployment/load qualification exists.

## Explicitly avoid (regardless of which repository)

"HIPAA compliant"; "PS3.15 conformant"; "de-identified" as a guarantee for the fixed demonstration
policy; "no source data reaches any provider"; "every stored object was checked"; "UIDs are never
sensitive"; "all charsets/VRs"; "no memory copies"; "bounded memory"; "streaming"; "cloud-
independent"; "formally verified"; "all other bytes preserved" for an arbitrary modified write;
"universally reusable"; "reproducible image" merely because a container builds; current
performance claims copied from the historical attrs-only benchmark without the qualifications
above.
