# Frontend Workflow Audit

The chat-first feature flag is the normal interaction path for usability
testing. Approval-heavy controls remain only as a staged developer mode. The
frontend does not decide whether a version is valid: it submits chat messages,
renders backend progress, and shows Current working version versus blocked
attempts. Every design remains revisionable; optional controls are surfaced
only after an explicit user request.

Date: 2026-08-01

## Current Chat Workspace Pass

The chat-first shell remains route-agnostic in normal conversation. Planning
depth and context-pack evidence are available only in Technical details; the
user sees concise interpretation, progress, clarification, success, or blocked
messages. Direct, compact, and detailed planning therefore do not create a
second frontend lifecycle.

The current flagged path is a full-height workspace with fixed Conversation,
flexible Model, and compact Details regions. At 1000–1279px Details is a
drawer; below 1000px the regions are tabs. The composer stays in the
conversation column, empty states are purposeful, and technical details are
collapsed.

The normal path automatically progresses the initial request and revisions.
Passing candidates become the Current working version; blocked attempts remain
in history and explicitly leave the current version unchanged. Persisted
assistant messages render alongside user messages, while system events remain
technical evidence. Network submission errors use recoverable connection copy
instead of raw `Failed to fetch`.

Evidence is recorded in `docs/CHAT_WORKSPACE_FRONTEND_EVALUATION.md`.
Deterministic UX testing may proceed; live CAD design-quality testing remains
a separate track.

## Evidence And Method

This audit follows `frontend/src/main.tsx`, its view helpers and tests, the workflow-run API contract, deterministic Playwright fixtures, and the successful enclosure/lid revision evidence in `docs/CADQUERY_OUTPUT_PLACEMENT_AND_LID_REVISION_EVALUATION.md`.

No retained workflow debug ZIP was available in local project data during this audit. This is an evidence limitation, not a successful or failed user journey. The upcoming five observed-user sessions must preserve the corresponding diagnostic bundle and frontend event trace.

## Current Information Architecture

The workspace uses a 3D viewer with a conversation column and a details
inspector. The inspector contains current version, active requirements,
proposals, checks, printable parts, history, and collapsed technical details.
The backend remains responsible for immutable requirements, plans, candidates,
and enforcement; the frontend translates those states for a non-CAD-specialist
user.

Primary path after this pass:

```text
Describe a part
-> clarify only essential decisions
-> automatic requirements and Design Plan progression
-> automatic first draft
-> Current working version or blocked attempt
-> revise through chat or export explicitly
```

## Vocabulary

The canonical frontend terminology lives in `frontend/src/terminology.ts`.

| Backend concept | Primary label |
| --- | --- |
| Design Specification | Design requirements |
| Design Plan | Proposed design |
| Revision Plan | Planned changes |
| Candidate revision | New version |
| Accepted revision | Current design |
| Protected parameter | Dimension to preserve |
| Validation finding | Design check |
| Source contract | Model build checks |
| Revision output | Printable part |
| Configuration change | Parameter update |
| Component-targeted revision | Change one part |

Technical names remain available only in technical details, source, manifests, and diagnostic bundles.

## State Mapping

| Backend state | User-facing state | Recovery |
| --- | --- | --- |
| requirement clarification | A few details are still needed | Answer the fit/function question without re-entering the request |
| Design Plan pending review | Proposed design | Generate design after reviewing requirements and proposals |
| candidate ready | New version, ready to review | Accept, revise, configure, reject, or export |
| candidate blocked | New version needs changes | Current design remains active; revise a part or try again |
| source/consistency failure | Volundr could not build the proposed design consistently | Try generation again or review proposed design |
| provider failure | AI service could not complete request | Try again; no design changes saved |
| output failure | One printable part needs another design pass | Retry output or revise that part |

## Findings

### Critical

No critical frontend issue was identified in the deterministic candidate flows. The current design remains separate from a pending version and acceptance is backend enforced.

### High

1. Internal lifecycle vocabulary dominated the first-time path.

User consequence: a user could mistake backend approval stages for CAD work. Evidence: prior lifecycle strip and primary panels named “Design Plan”, “candidate”, and CadQuery execution stages. Successful enclosure evidence contains a bounded contract repair before valid outputs, a detail users should not need to interpret as a top-level failure. Correction included: primary labels now use Design requirements, Proposed design, New version, and user progress labels; details are secondary.

2. Provenance was visible but not scannable.

User consequence: user measurements, defaults, and calculated dimensions could be conflated. Evidence: requirement values were rendered as sentence strings and Design Plan values were presented as generic parameter lists. Correction included: grouped “Your requirements”, “Volundr proposes”, “Calculated”, and “Decisions needed” sections.

3. Candidate blockage did not consistently state whether an accepted design was safe.

User consequence: users could fear a failed new version had overwritten a working part. Evidence: blocked candidate UI previously led with validation counts and rule-like details. The enclosure revision proof confirms base output preservation is meaningful evidence. Correction included: recovery cards state that the current design was not changed and present one direct next action.

### Medium

1. Multi-output review exposed component IDs before product-level status. User consequence: users had to infer why a product could not be accepted. Correction included: a product-level printable-part summary and explicit required-part block explanation. Raw identity evidence remains technical.

2. Configure and Revise did not explain their different guarantees. User consequence: a count change could be sent through an AI redesign, or a structural request could be attempted as a parameter edit. Correction included: parameter adjustment says “No AI redesign required”; planned changes says “Volundr will plan and generate a structural change.” Full entry-point navigation remains an observation target.

3. Generation progress was an internal static strip. User consequence: “Executing CadQuery” and topology terminology explain implementation rather than user progress. Correction included: stable user-facing stage names and correlated `progress_stage_shown` telemetry. Future live event polling can replace the current state-derived display when long-running asynchronous execution is introduced.

### Low

1. Compact layouts remain dense once advanced inspection, printability, and history are all open. The existing responsive single-column breakpoint is retained; technical controls are now collapsed by default.

2. The project drawer needs a full focus trap and focus return. Visible focus, live status announcements, text status labels, and descriptive controls were improved, but this is not a WCAG certification.

3. A user may still see revision identifiers in history. They remain useful version references, but the primary header identifies Current design or New version first.

## Observability Coverage

The fixed frontend registry includes request, clarification, requirements review, proposed-design review, generation progress, candidate/output review, parameter preview/submission, revision planning, acceptance/rejection, export, visible errors, recovery selection, and diagnostic-bundle download. Optional `?testScenario=<safe-id>` marks a user-testing session without collecting free-form observer notes or duplicate design text.

## Responsive And Accessibility Baseline

The layout is validated at 1920x1080, 1280x900, 1024x768, and 390x844. The
phone scope is reading, chat, review, revision, and export, not source editing
or full CAD editing. Drawers and dialogs have modal semantics and Escape
handling; full focus trapping remains future work.

## Priority After This Pass

Run the deterministic chat-first scenarios before observed UX sessions. Those
fixtures now pass, so usability testing can proceed separately from live
Gemini/CadQuery quality testing. Use event trace timing, diagnosis, and debug
bundles to distinguish a user-comprehension issue from a backend lifecycle
failure. Staged controls remain available only when
`VITE_VOLUNDR_CHAT_FIRST=false`.
