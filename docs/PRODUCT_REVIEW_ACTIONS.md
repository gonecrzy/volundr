# Product Review Actions

## Must Fix Now

1. Keep the chat input scoped to the current project until the user starts a new project.
2. Route follow-up messages to the current workflow state instead of treating every message as a new initial request.
3. Show clarification, plan review, revision planning, and blocked-candidate recovery in the chat timeline.
4. Give each blocking finding an action that starts revision planning, asks for clarification, changes configuration/profile, or regenerates from an approved plan.
5. Make uncompiled editor changes explicit before AI revision.

## Should Fix Next

1. Show a compact pipeline timeline: Requirements, Plan, Generate, Compile, Validate, Review.
2. Apply the approve-and-run pattern to Revision Plans after verifying the same recovery semantics.
3. Display validation as Blocking, Warnings, and Notices.
4. Show revision design deltas: changed parameters, affected modules, validation delta, and parent revision.
5. Add printer/profile selection before build-volume findings become blocking.
6. Add guided prompts for common categories: plate, holder, box, bushing, adapter, handle.

## Useful Later

1. Saved user defaults for clearances, fasteners, materials, and printer profile.
2. Highlight validation regions in the viewer where reliable.
3. Part-type templates that produce structured requirement forms.
4. Visual comparison between parent and candidate revision.
5. Exportable generation-run diagnostic bundle.

## Explicitly Defer

1. Full slicer integration.
2. Automatic support generation.
3. Multi-user workflow.
4. Public sharing, galleries, or collaboration.
5. Marketplace features.
6. STEP/CadQuery/build123d provider migration.
