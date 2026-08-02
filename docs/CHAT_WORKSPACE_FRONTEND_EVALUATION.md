# Chat Workspace Frontend Evaluation

Date: 2026-08-01

This evaluation records the frontend workspace pass after durable project
persistence, explicit exports, Compose healthchecks, and chat-first workflow
orchestration were available. It covers the normal user surface under
`VITE_VOLUNDR_CHAT_FIRST=true`; the staged/developer surface remains available
when the flag is false.

## 1. Scope and constraints

The pass changes presentation and interaction only. Backend lifecycle records,
Design Specifications, Design Plans, Revision Plans, source safety, topology,
functional checks, candidate gates, and export authority remain unchanged.
Every design remains revisionable. Parametric controls are optional and
explicitly requested.

## 2. Workspace model

The normal project workspace is one full-height shell:

```text
top bar: Projects / project name / save state / History / Export / menu
conversation | flexible 3D viewer | compact inspector
```

At 1280–1599px the columns are `380px / minmax(480px, 1fr) / 320px`.
At 1600px and above they are `420px / minmax(600px, 1fr) / 360px`.
At 1000–1279px the inspector becomes a Details drawer. Below 1000px the
workspace becomes Conversation, Model, and Details tabs. The conversation
composer remains in the conversation column instead of becoming a floating
overlay.

## 3. Conversation behavior

The empty state uses:

> Describe the part you need

It explains that fit, mounting, measurements, and avoided features are useful,
and shows three short examples. Persisted user and assistant messages render in
the same conversation. Internal `system_event` records remain available to
technical evidence but are hidden from normal chat.

Assistant messages are classified into clarification, progress, success,
blocked, error, and informational presentation kinds. A successful message can
open the version or export drawer. A blocked message explicitly states that
the Current working version is unchanged.

## 4. Submission and reconnect behavior

The composer sends on Enter and inserts a newline on Shift+Enter. An optimistic
user message remains visible while the request runs. The backend response then
reloads the authoritative workspace and persisted assistant message. The same
`client_message_id` is reused for retry, so a retry is idempotent.

Network failures use the concise copy:

> Could not connect to Volundr. Your message was not lost. Check the
> connection and try again.

Raw `Failed to fetch`, stack traces, and server diagnostics are not shown in
normal chat. Technical details retain the workflow and diagnostic evidence.

## 5. Working-version behavior

The viewer and inspector identify the Current working version. A new version is
created through the same backend lifecycle, and a passing version is promoted
automatically. A blocked attempt is shown as a blocked attempt and does not
change the current pointer. Previous versions remain selectable and recoverable.

## 6. Inspector order

The compact inspector presents, in order:

1. Current working version
2. Active requirements
3. Proposed choices
4. Checks and warnings
5. Printable parts
6. Version history
7. Technical details, collapsed by default

Printer-profile controls and source/diagnostic details remain secondary. Export
is explicit and is disabled until the selected revision is a successful,
accepted revision.

## 7. Export behavior

The export drawer supports STL, STEP, and the complete project package through
the existing backend export records and deterministic download routes. It does
not construct package contents in the browser. The drawer identifies whether
the selected revision is current or historical and preserves the existing
explicit-export rule.

## 8. Project actions

Projects opens a library drawer. The top bar supports inline rename, History,
and an overflow menu for archive/delete actions. These actions remain backend
owned and are not presented as persistent primary workflow buttons. Stable
project URLs and authoritative reloads remain unchanged.

## 9. Viewer states

The viewer preserves the existing STL component and adds a purposeful empty
state, standard Fit/Front/Top/Right/Iso controls, a dismissible interaction
hint, a version status bar, and historical/blocked banners. Returning from a
historical revision routes back to the current revision.

## 10. Responsive and accessibility checks

The deterministic explicit-part browser workflow passed at:

| viewport | result |
|---|---|
| 1920×1080 | pass; three-panel workspace |
| 1280×900 | pass; desktop breakpoint |
| 1024×768 | pass; Details drawer |
| 390×844 | pass; Conversation/Model/Details tabs |

Dialogs and drawers have accessible names and modal semantics. Escape closes
open menus, drawers, and rename dialogs. The composer has a label, the current
workflow uses live progress/error regions, and the design retains visible
keyboard focus styles. Full focus trapping and formal WCAG certification remain
future work.

## 11. Deterministic scenarios

The chat-first browser scenarios pass for:

- explicit first draft and explicit export;
- essential clarification followed by automatic generation;
- provider-free organizer configuration;
- internal Revision Plan for an enclosure component revision;
- blocked-attempt recovery and current-version preservation;
- start-over branch creation and prior-version recovery;
- ordinary requirement and physical-feedback revisions;
- adding an optional exposed control without removing ordinary chat revisions.

The staged suite also passes with `VITE_VOLUNDR_CHAT_FIRST=false`.

## 12. Backend persistence evidence

The chat path persists the submitted user message and a semantic assistant
message linked to the resulting revision when one exists. Existing system
events remain persisted for observability. Reloading the workspace returns the
same visible message ledger and current revision pointer.

## 13. Docker and API evidence

The current Compose stack was healthy during this evaluation:

```text
volundr-api       healthy
volundr-cad-worker healthy
volundr-web       healthy
GET /             200
GET /api/projects 200 through the web proxy
```

The previous frontend symptom `Failed to fetch` is now mapped to a recoverable
connection state in normal chat. The web container proxies `/api/` to the API
service; no browser-side provider or worker credentials are involved.

## 14. Automated verification

- Backend: 448 passed.
- Frontend unit tests: 72 passed.
- Frontend production build: passed.
- Chat-first Playwright suite: 6 passed, 12 appropriately skipped by mode.
- Staged Playwright suite: 9 passed, 9 appropriately skipped by mode.
- Responsive explicit-part checks: passed at 390px, 1024px, and 1280px.
- Playwright CLI Docker smoke: loaded with zero console errors (existing
  Three.js deprecation/GPU warnings only).

## 15. Screenshot inventory

The local ignored `output/playwright/` evidence directory contains captured
empty-workspace states:

- `chat-workspace-empty-1920.png`
- `chat-workspace-empty-1024.png`
- `chat-workspace-empty-390.png`
- `chat-workspace-empty-docker-1920.png`

Passing and blocked message states are also covered by deterministic browser
fixtures and their diagnostic screenshots/traces on failure; no live CAD
result is used as a UX fixture.

## 16. Remaining limitations

The viewer still displays the existing STL preview rather than a new renderer.
Qualitative physical behavior remains evidence-led: functional findings and
human/test-print review are not replaced by frontend labels. The staged UI is
retained temporarily for diagnostics, and the live provider/CadQuery track
remains separate from usability testing.

## 17. Testing recommendation

Observed UX testing may proceed with deterministic fixtures for chat requests,
clarification, proposals, revisions, start-over, blocked attempts, current
working versions, and export. Live design-quality testing should continue as a
separate track using real Gemini, the FastAPI services, the CadQuery worker,
and preserved workflow evidence.
