# Bottle Holder Retention Live Evaluation

Status: complete for the narrow retention-planning correction; observed user testing remains paused.

## 1. Selected Retention Strategy

The exact request was run without adding construction dimensions:

> Create a wall-mounted holder for an 81 mm bottle, suitable for a moving boat, with one-handed removal and two #8 mounting screws.

The Design Plan now resolves the required retention interface to:

- strategy: `flexible_snap_arm`;
- owning component: the planned holder component;
- stable feature ID: `feature_snap_arm` in the live plan;
- release behavior: one-handed pull;
- removal direction: `+Z`;
- proposed parameters: overlap, arm thickness, entry chamfer, and release clearance;
- verification: feature geometry and parameter effect required, with human review for strength and usability.

The plan also retains the previously resolved coordinate frame, mounting plane and normal, hole axis, hole arrangement axis, hole style, bottom support, floor thickness, and removal direction.

## 2. Why It Was Proposed

The request supplied enough generic context to make a reasonable proposal: the object must remain retained in a moving vehicle and must be removable with one hand. A flexible snap arm is a reviewable, editable proposal for that combination. The planner does not branch on bottle-specific names; it uses the generic moving-vehicle and one-handed-release context.

The first live plan used the unresolved placeholder `reviewed_proposal`. That passed because the schema accepted arbitrary strategy text and the validator only checked for limited presence. The correction adds a supported strategy vocabulary and requires a stable feature, owner, release behavior, parameters or an explicit parameter-free declaration, and verification metadata. The affected Design Plan prompt is now `design-plan-v2`.

## 3. User-Provided Versus Proposed Values

User-provided information:

- 81 mm bottle diameter;
- wall-mounted use;
- moving-boat environment;
- one-handed removal intent;
- two #8 mounting screws.

Volundr proposals include the concrete retention strategy and its editable dimensions. The live Design Plan response also supplied the mounting and support proposals needed for execution. Retention force, fatigue life, material compatibility, and actual one-handed operation remain human-review concerns.

## 4. Plan Validation

The first corrected live run produced a concrete retention plan and proceeded to source generation. Its evidence:

- project: `73a74163-fe7a-4329-af6d-7e3f4d9b9bd0`;
- root workflow: `213d311a-0164-47c5-b88f-b020dcd83534`;
- diagnostic bundle: `workflow-debug-213d311a-0164-47c5-b88f-b020dcd83534.zip`;
- result: source generation reached the worker, which timed out after 90 seconds.

A fresh rerun after making retention-linked features required in source authority produced:

- project: `663bb468-1bf2-45c3-9ecb-1cd45a8ba8be`;
- root workflow: `017d57f3-1b25-44e8-b723-60aef16935b2`;
- Design Plan child: `c82ea703-0905-46f5-a482-87cdc8290184`;
- diagnostic bundle: `workflow-debug-c82ea703-0905-46f5-a482-87cdc8290184.zip`;
- result: source-contract block before worker execution.

The second run's first blocking source evidence was `source_parameter.protected_parameter_missing` for the approved `bottle_diameter` and `mounting_screw_size` identities. The generated source used internal parameter names instead of declaring those protected identities, so it was correctly rejected before retention geometry could be executed. Initial and repaired source artifacts were both preserved. No candidate was presented as generally ready.

## 5. Source Implementation

Source authority now carries retention interface identity, strategy, owner, feature ID, directions, and parameter IDs. Retention-linked features are required even if a provider incorrectly marks them as non-protected. Source checks require:

1. the stable feature metadata;
2. a callable feature builder;
3. invocation from the expected component context;
4. use of the returned geometry rather than a discarded call;
5. functional parameter references that reach geometry operations.

The live source did include a `feature_snap_arms` declaration on its component builder, but the source was rejected earlier for protected-parameter identity omissions. The dedicated-builder, invocation, returned-geometry, and parameter-effect checks are covered by deterministic tests; this live run did not reach a point where those retention checks could be physically evaluated. The rejection remained generic and did not branch on bottle-holder names.

## 6. Parameter-Effect Evidence

The source authority data-flow checks cover transitive local assignments and common CadQuery geometry calls. They reject a no-op protected-parameter reference and protected geometry values bypassed by an unrelated literal. The live source attempts were preserved for inspection; the second run stopped before physical execution, so no B-Rep sensitivity result was claimed.

## 7. Retention Geometry Evidence

No final retention geometry can be certified from these runs. The first run timed out in the worker and the stricter rerun was blocked before worker execution. The retention verifier is conservative: it can establish source feature evidence and a valid solid for partial verification, but it does not claim retention force, fatigue life, material suitability, or one-handed usability. A concrete feature with those limits would be `functionally_partially_verified` and require human review; missing feature evidence is blocking.

## 8. Mounting-Hole Result

The Plan contained a concrete mounting plane, wall-normal axis, hole axis, arrangement axis, hole style, count, and spacing. The second run did not execute geometry, so hole intersection, orientation, count, diameter, and spacing were not claimed as verified.

## 9. Support-Floor Result

The Plan retained a required support floor and proposed a minimum floor thickness. The second run did not execute geometry, so floor presence and measured thickness remain unverified rather than being inferred from source text.

## 10. Removal-Path Result

The approved removal direction is `+Z`. No executed shape was available for containment-path verification. A future successful run must show that retention geometry is near the opening without completely blocking that direction.

## 11. Functional Status

The corrected workflow did not create a usable candidate. The first live run ended in a worker timeout. The authoritative follow-up ended in a source-contract failure with no worker submission and no candidate. This is the required safe behavior: critical retention implementation evidence is not hidden behind `ready_with_warnings`.

## 12. Human-Review Limitations

Deterministic checks can verify contract completeness, source identity and feature evidence, parameter influence, topology, and conservative geometric relationships. They cannot certify actual snap force, fatigue, print anisotropy, material compatibility, safe release feel, or one-handed usability. Those remain explicit review and print-test requirements.

## 13. Provider Calls, Latency, Repairs, And Usage

The first corrected run completed in approximately two minutes and recorded four Gemini calls: two requirement calls, one Design Plan call, and one source-generation call. Source contract validation passed and the worker was submitted, but the worker timed out after 90 seconds. The second run completed in 30.8 seconds and recorded four calls:

| Attempt | Prompt version | Status | Prompt tokens | Output tokens | Total tokens |
| --- | --- | --- | ---: | ---: | ---: |
| 1 | `requirements-v1` | succeeded | 717 | 834 | 1,551 |
| 2 | `design-plan-v2` | succeeded | 3,396 | 2,739 | 6,135 |
| 3 | `cadquery-generation-v4` | failed | 9,093 | 1,761 | 10,854 |
| 4 | `cadquery-contract-repair-v2` | failed | 9,642 | 1,636 | 11,278 |

Authoritative Gemini `usageMetadata` is now persisted on generation attempts. No provider request ID was returned by these responses. API credentials were not included in logs, artifacts, or the diagnostic bundle.

## 14. Manual Render Classification

No standard or section renders were generated for the authoritative follow-up because source contract validation blocked execution. Classification is therefore **requires targeted implementation correction before physical classification**. The existing render path remains reserved for an executed candidate.

## 15. Decision On Resuming User Testing

Observed user testing must remain paused. The correction achieved the important planning behavior: sufficient generic intent now receives a concrete retention proposal instead of an unresolved placeholder. It also prevented a generated source without required retention implementation evidence from becoming a candidate. A future live rerun must reach physical verification or block at a specific geometry/functional stage with actionable findings before user testing resumes.
