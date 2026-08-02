# Observed Frontend Testing Script

This script is for a real tester using the Volundr frontend. Do not explain
internal terms such as workflow run, GeometryExecutionContext, prompt pack,
source contract, or provider model. Do not claim this session has occurred
until a tester completes it.

## Facilitator introduction

“Volundr turns a plain-language request into a working 3D design. You can ask
for changes in the conversation, review previous versions, and export a
selected version. Please say what you expect to happen and think aloud. I am
testing the product, not your CAD knowledge.”

Do not coach the tester toward a particular control unless they are blocked
for more than 30 seconds. Record the intervention.

## Session setup

- Use a disposable deterministic fixture environment.
- Confirm the tester can see the project list and does not see internal
  workflow chips or raw backend errors.
- Start a timer when the first task begins.
- Record viewport and browser type.

## Tasks

1. Create a new simple project from a short plain-language request.
2. Explain what the first assistant response means.
3. Answer an essential clarification question when one appears.
4. Identify which version is the Current working version.
5. Request a dimension change in chat.
6. Interpret a blocked revision message and explain what remains current.
7. Return to the valid Current working version.
8. Refresh the project and explain whether the work was saved.
9. Return to Projects and reopen the project.
10. Select a previous successful version.
11. Compare two versions.
12. Download STL.
13. Download STEP.
14. Explain which revision is being exported before confirming the export.
15. Report a simulated print problem, such as “the holes are too tight.”
16. Continue the revision and explain what was preserved.

## Facilitator prompts

Use only if needed:

- “What would you expect to happen next?”
- “Which design would you use if you wanted to go back?”
- “What tells you that this file belongs to the version you selected?”
- “What would you do after seeing this warning?”

Do not answer product questions during the task. Note the question and answer
it during the debrief.

## Capture sheet

For each task record:

- completion: success / partial / failed;
- elapsed time;
- hesitation or re-reading;
- incorrect clicks or submissions;
- save-state confusion;
- version confusion;
- blocked-attempt confusion;
- proposal-versus-requirement confusion;
- export-target confusion;
- warning comprehension;
- confidence after reopening;
- confidence that the downloaded file is the selected revision.

Also record any facilitator intervention, the exact user language, and whether
the tester discovered the answer independently.

## Debrief questions

1. What did you think Volundr was doing after you submitted the request?
2. What did “Current working version” mean to you?
3. What did you think happened when a revision was blocked?
4. Were proposals distinguishable from requirements?
5. Did you trust that reopening restored the project?
6. How did you decide which revision to export?
7. Which warning was hardest to understand?
8. What would you want to change before using a generated part?

## Safety and reporting

Do not ask a tester to treat an unverified geometry result as printable. Keep
live Gemini/CadQuery quality evaluation separate from this usability session.
Record whether the fixture is known-good or known-blocked.
