# User-testing checkpoint

Checkpoint date: 2026-08-02 16:34 UTC capture, with browser correction verification completed afterward.

## 1. Repository and runtime state

- Capture HEAD: `569c365 Trace explicit component and output requirements`
- Migration head: `0027_export_records`
- Compose services: `volundr-api`, `volundr-cad-worker`, and `volundr-web`; all healthy after the focused rebuild.
- Frontend: `http://127.0.0.1:8080`
- API health: `http://127.0.0.1:8000/health` returned 200.
- The checkpoint contains no credentials or provider keys.

The complete local checkpoint is outside Git at `checkpoints/user-testing-2026-08-02/` and is ignored by `.gitignore`. It contains a transactionally safe SQLite backup, API/project JSON, browser logs, screenshots, and artifact verification. Three hundred referenced data paths were checked; all 300 existed at capture time.

## 2. Checkpoint identity and scope

The database backup was created with SQLite `.backup`. Collection did not submit chat messages, call a provider, regenerate geometry, create an export, or promote a candidate. The browser naturally emitted its existing frontend-view telemetry events; those are retained in the browser evidence and did not change project revisions or conversation content.

The checkpoint records the project list, workspace, messages, revisions, workflow runs/events/diagnoses, generation attempts, candidates, requirements, snapshots, output manifests, exports, and referenced artifact paths for every active project.

## 3. Projects reviewed

| Project | Current working version | Conversation/history | Browser result | Primary caution |
|---|---|---|---|---|
| Tackle tray holder (`3a66a1b7-8f2b-4de4-8980-abf5132a3009`) | None | Complete chronological history with four blocked attempts | Reopens with concise blocked outcomes and no current version | Live CAD remains blocked because `tray_capacity=5` has no verification path |
| Johnson outboard bushing (`01f8371b-1993-446b-a826-f42a9b1f7810`) | Version 1 | Complete user and assistant outcome | Reopens with model, requirements, warnings, snapshots, and printable parts | Ready with warnings; physical fit still merits review |
| Rectangular spacer (`1f3fc57d-f044-4062-8d6e-20e904d7dcfd`) | Version 1 | Complete initial request plus blocked revision history | Reopens with history, blocked-attempt banner, comparison affordance, snapshots, and export drawer | Current version is intentionally unchanged after blocked revisions |

No project showed a user message without an assistant outcome. The tackle project’s repeated attempts remain visible as blocked; none appears successful or current. The spacer’s selected blocked Version 2 displayed “Current working version is Version 1” and a blocked-attempt banner.

## 4. Browser states reviewed

The real frontend was reviewed without submitting messages at 1440×900, 1024×768, and 390×844. Stable project URLs, persistent conversation ordering, current-version labels, blocked-attempt messaging, requirements, proposals, checks, views, history, comparison entry, and export revision identity were inspected.

The desktop layouts showed the conversation, viewer, and summary together. The mobile layout kept the conversation primary and exposed Model and Details as tabs. Screenshots are in the local checkpoint, not Git.

The bushing project’s Export drawer identified Version 1 as the Current working version. Selecting a blocked spacer revision disabled Export and preserved Version 1 as current. The bushing and spacer registered snapshot images loaded after the correction; the tackle project correctly reported that snapshots and printable parts were unavailable.

## 5. Console and network findings

The initial review found two project-list thumbnail 404s. The library API exposed a snapshot packet JSON artifact where the frontend image endpoint required a registered PNG artifact. It also found three avoidable 404s while viewing the blocked tackle project: two no-control configuration requests and one compile-log request for a pre-worker blocked revision.

The focused correction:

- selects the registered isometric image artifact for project-list previews;
- skips configuration loading when `exposed_controls` is empty;
- skips compile-log loading when a pre-worker revision has no STL/output evidence.

A fresh browser session after rebuilding the API and web containers opened the blocked tackle project with zero console errors and zero failed network requests. Five expected Three.js/WebGL performance/deprecation warnings remained; they are not user-facing backend failures. Raw before-and-after logs are in the checkpoint.

## 6. Issues corrected

The thumbnail artifact mismatch and blocked-project 404 requests were confirmed normal-viewing defects and corrected with focused backend/frontend tests. No CAD, worker, requirement, topology, artifact, export, or promotion policy changed.

## 7. Deferred CAD issue

The tackle project remains intentionally blocked. `tray_capacity=5` is preserved as backend backlog work: when a fixed numeric count maps unambiguously to a known feature or layout, Volundr should deterministically create the geometry-verification target. This checkpoint did not retry or force that project to pass.

## 8. Deterministic testing projects

The fixture backend and Playwright suites already provide the scenarios needed for the first session without live Gemini reliability:

- known-good initial creation with Current working version, snapshots, and explicit export;
- essential clarification followed by automatic continuation;
- ordinary revision with history and comparison evidence;
- blocked attempt that preserves the prior current version;
- physical-feedback revision flow;
- start-over lineage preservation;
- deterministic organizer configuration;
- enclosure/component revision and recoverable worker failure fixtures.

Use `docs/OBSERVED_FRONTEND_TESTING_SCRIPT.md` and one copy of `docs/OBSERVED_FRONTEND_TESTING_RESULTS_TEMPLATE.md`. Observed testing has not occurred.

## 9. Facilitator cautions

- Start with deterministic fixtures, not the live tackle project.
- Explain that the session evaluates conversation, versions, warnings, and exports—not CAD physical quality.
- Do not call the tackle project a failed user-flow example; it is a valid blocked-attempt fixture with no Current working version.
- Ask the tester to distinguish a Current working version from a blocked attempt before discussing export.
- Treat `ready_with_warnings` as a review prompt, not a print-quality guarantee.
- Record the expected Three.js/WebGL warnings separately from any new console error.

## 10. Readiness gate

| Gate | Result |
|---|---|
| Project creation path exists | Pass in deterministic Playwright fixtures |
| Persistent chat and assistant outcomes | Pass in persisted projects and fixtures |
| Clarification and automatic continuation | Pass in deterministic fixtures |
| Current working version is unambiguous | Pass |
| Blocked attempt preserves current | Pass |
| Refresh/reopen and stable URLs | Pass |
| History and comparison surfaces | Pass; use a fixture with two successful revisions for comparison tasks |
| STL/STEP export identity | Pass for current saved bushing/spacer drawer; do not generate exports during the read-only review |
| Simulated physical feedback continuation | Pass in deterministic fixtures |
| P0 data-integrity issue | None found |
| P1 user-testing workflow blocker | None found after focused correction |
| Raw backend error in normal viewing | None in fresh final browser session |
| Script and results template | Current; observed session not yet run |

## 11. Final recommendation

**Ready with listed facilitator cautions.**

Proceed with the first observed frontend usability session using deterministic fixtures. Keep live CAD-quality testing separate, and leave `tray_capacity=5` for the backend follow-up after the session.
