# Product Validation Round 1

Date: 2026-08-02

## 1. Repository state

Validation began from the clean repository at `b4a462f` and added two narrow
corrections during evaluation:

- empty optional Gemini policy paths are treated as unset (`0aac5a6`);
- ordinary modern plans enforce source identities only for explicitly exposed
  controls (`23d58ab`).

The live matrix harness was updated to the five requested prompts. No CAD gate,
planning route, snapshot contract, or frontend layout was weakened.

## 2. Runtime environment

Compose configuration parsed successfully. The running services were
`volundr-web`, `volundr-api`, and `volundr-cad-worker`; all were healthy after
startup. `/health` returned `{"status":"ok"}` and `/ready` returned database
and artifact-storage checks as `ok`. The container migration head was
`0027_export_records`.

The standard deployment used web port 8080, API port 8000, bind-mounted
`./data` as the application data root, `./data/jobs` for worker jobs, and the
derived Gemini data directory. The provider was Gemini API with the configured
default model `gemini-3.5-flash-lite`; credentials were not copied into this
report. Prompt versions were recorded in each generation attempt.

The targeted `volundr-api` Compose image build passed. An earlier full Compose
build attempt was interrupted after it produced no progress, so this report
does not claim a complete full-image build from that attempt. Compose config,
startup, health, migration, and targeted API build checks passed.

## 3. Product-shell acceptance

The exact spacer was created through the real browser at
`http://127.0.0.1:8080`. The project URL remained stable:

```text
/projects/1f3fc57d-f044-4062-8d6e-20e904d7dcfd
```

The browser displayed the persisted user request, assistant result, Current
working version, requirements, proposals, warnings, functional-check summary,
four views, printable part, and export actions. Refresh and Projects navigation
returned the same project state without duplicate messages or revisions. A
historical blocked revision remained non-current.

The successful initial revision was Version 1, revision
`df246f42-37ec-4cec-a164-c070d3ebcea3`, and remained the Current working
version through the failed revision attempts.

## 4. Persistence and reconnect

Restarting `volundr-api` and waiting for `/ready` preserved the conversation,
Current working version, snapshots, registered outputs, and export records.
The API reported no stale running workflow after restart. Deterministic
fixture tests cover idempotent duplicate submission, project reopen, and
restart recovery. A separate delayed real-provider reconnect session was not
performed because the repository has no supported delayed live fixture; this
remains a follow-up acceptance item, not a claimed pass.

## 5. Export acceptance

The browser downloaded STL, STEP, all-parts output, and a complete project
package for Version 1. The package manifest identified the selected project,
revision, `mm` units, `primary_part`, two artifacts, and revision 1. It
contained source, requirements, revision history, verification summary, BREP,
STL, STEP, and snapshot records.

Recorded hashes:

```text
STL     de9381d5f9c2ee4a095d0eb1734aa1170a31fc004f6271606056ac06d2794ce3
STEP    0c8e81415c66bd035c1d5fbe74011dd9ddfa465c5fe7d6c77796b42de1554adc
Package 791d8a59f75d3c7304ad147478c55c66170bfd4c56c5b6091511409a5dff0f66
```

After the API restart, the same export records downloaded with matching
hashes. A package scan found no credentials, temporary worker paths, or
absolute internal paths. The files were nonempty and the manifest was
consistent. No external CAD or slicer application was available in the
environment, so external scale, hole, and solid inspection was not performed.
File existence is not treated as print-readiness proof.

## 6. Spacer revision chain

The exact five user messages were submitted through the real browser against
the same spacer project. Results:

| Step | Outcome | Evidence |
|---|---|---|
| Initial | accepted/current | worker, one solid, STL/STEP/BREP, snapshots, 10 advisory warnings |
| R1 thickness + left-hole move | blocked | worker succeeded; output and five-view comparison persisted; protected-output envelope gate blocked the changed thickness |
| R2 printed holes too tight | blocked without new revision | observation message was persisted, but router did not create a new candidate |
| R3 reinforcement rib | blocked | worker/output comparison persisted; protected-output envelope gate blocked the changed shape |
| R4 remove rib | blocked without new revision | no promoted revision; Version 1 remained current |
| R5 expose thickness control | blocked without new revision | no new exposed-control revision was promoted |

R1 comparison measured 80×45×6 mm before and 80×45×8 mm after, with one
solid on each side and five paired snapshot views. R3 comparison measured
80×45×6 mm before and 80×45×16 mm after and persisted the corresponding
comparison packet. These are useful revision evidence, but the output
preservation gate treated the explicitly requested envelope changes as
unexpected output changes. No gate was changed solely to make the chain pass.

The chain therefore proves durable history and Current working version
protection, but not successful multi-revision promotion. The physical-feedback
message also exposed a chat-routing gap: the user message was persisted, yet
did not create a requirement delta/candidate in this run.

## 7. Live design results

The five exact live cases were rerun after the ordinary-plan correction. Full
prompt text and per-attempt evidence are in
`docs/LIVE_DESIGN_MATRIX_EVALUATION.md`.

- Direct circular spacer: `direct_brief`; worker reached; provider CadQuery
  selector syntax failed; blocked.
- Irregular bracket: `compact_plan`; missing planned rib source identities;
  worker not reached; blocked.
- Bottle holder: `compact_plan`; malformed pattern owner/type; worker not
  reached; blocked.
- Organizer: `compact_plan`; unapproved provider-added identities;
  source-contract block before worker.
- Two-piece enclosure: `detailed_plan`; repeated missing ventilation pattern
  spacing; detailed plan blocked before geometry.

No case was promoted. The matrix confirms that the ordinary source-parameter
correction removed the false parametric blocker, but compact and detailed
provider/plan interoperability remains the main bottleneck.

## 8. Pipeline diagnosis

The failures were assigned to requirements retry, compact/detailed planning,
design-artifact identity, source contract, and worker CadQuery syntax. None
were topology or artifact false positives. The detailed diagnosis is in
`docs/COMPACT_DETAILED_PIPELINE_DIAGNOSIS.md`.

## 9. Requirement-verification evidence

For the successful spacer, the worker and artifact pipeline provided one valid
solid, dimensions 80×45×6 mm, STL/STEP/BREP, topology evidence, functional
check records, and snapshots. Requirements that lacked deterministic feature
metadata remained warnings with human-review/test-print recommendations.
The pipeline did not claim definitive hole positions, hole diameters, corner
radius, or print quality where evidence was unavailable.

The existing BREP/OCP path already exposes overall bounds, volume, solid count,
shell count, validity, and some orientation/topology evidence. Hole identity,
exact local feature position, and fillet/chamfer radius remain difficult when
the provider does not preserve feature metadata. No symbolic geometry reasoner
was added.

## 10. Snapshot and comparison evidence

The initial spacer produced a multi-view snapshot packet. R1 and R3 produced
paired before/after packets with matched isometric, opposite-isometric, front,
right, and top views. The comparison artifacts include bounding boxes, volume,
component count, solid count, changed-component IDs, and verification deltas.

## 11. Frontend acceptance

The deterministic chat-first suite passed 8 tests and the staged suite passed 9
tests; 16 and 15 tests respectively were skipped by their existing selectors.
Frontend tests passed (75 before this pass) and the production build passed.
The real browser check covered the required viewport sizes: 1920×1080,
1440×900, 1280×720, 1024×768, and 390×844. Persistent conversation,
Current working version, blocked history, snapshots, comparison/export state,
and responsive project tabs were visible in the page snapshots.

The browser console contained expected WebGL warnings plus two real product
signals: early API 500/502 responses during the post-restart/initial provider
transition and 404 requests for component-revision-summary on blocked revision
plans. The UI did not expose raw backend errors in the visible workspace, but
these remain frontend/API follow-up issues.

Observed user testing was not performed. The script and results template are
ready in `docs/OBSERVED_FRONTEND_TESTING_SCRIPT.md` and
`docs/OBSERVED_FRONTEND_TESTING_RESULTS_TEMPLATE.md`.

## 12. Compose restart evidence

The API was restarted, health and readiness returned, the project was
reopened, and the same registered STL/STEP/package exports were downloaded.
Hashes matched the pre-restart downloads. Snapshots and export records
remained present. No stale workflow remained running.

The opt-in real-provider browser harness was also rerun for the exact
direct-brief spacer route after the changes: 1 Playwright test passed in
17.4 seconds. The isolated live evidence was preserved at
`/tmp/volundr-live-e2e.TtKzVh` during the run; the API key was excluded and the
harness cleanup scan passed.

## 13. Remaining product risks

- compact plans can produce invalid component/pattern identities;
- detailed plans can repeat incomplete pattern semantics;
- provider CadQuery syntax can reach the worker and fail at runtime;
- requested ordinary physical-test feedback did not yet create a revision;
- requested revision envelope changes are blocked by output preservation;
- feature-level deterministic evidence is still sparse;
- frontend blocked-plan details cause avoidable 404 requests;
- no real observed-user evidence exists yet.

## 14. Recommendation

Primary recommendation: **compact/detailed planning hardening**.

Direct and compact paths can reach meaningful deterministic gates, but most
compact/detailed cases in this matrix did not reach stable worker geometry.
This evidence does not justify advisory AI visual review or another broad
verification layer yet. The next phase should narrow the provider/plan
interoperability failures, then rerun the same matrix.

## 15. Testing recommendation

Go for observed frontend testing using deterministic known-good and
known-blocked fixtures. Keep live CAD-quality testing separate and paused for
the compact/detailed bottlenecks identified above.

Broader live CAD testing: no-go until at least the compact/detailed planning
contracts and the real blocked-plan frontend requests are corrected and the
matrix demonstrates repeatable worker reachability.
