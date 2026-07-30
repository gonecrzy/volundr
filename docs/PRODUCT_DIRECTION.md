# Volundr Product Direction

This document defines what Volundr is, who it serves, the value it should provide, and the principles used to decide which capabilities belong in the product.

## CadQuery Transition Status

`docs/CADQUERY_BACKEND.md` supersedes earlier product-direction claims that OpenSCAD is the strategic V1 kernel, Gemini CLI is the primary runtime provider, Ollama is the intended default, or simple chat generation is the main product path. Existing OpenSCAD behavior remains useful implementation history during the transition, but the product direction is CadQuery-primary and staged-workflow-primary.

## Working Description

Volundr is a self-hosted AI-assisted parametric modeling workspace for creating functional 3D-printable parts from plain-language instructions.

It combines:

- conversational design requests
- parameterized CadQuery generation
- deterministic CAD compilation
- interactive 3D preview
- revision history
- direct source editing
- local project storage

Volundr should feel like a focused workshop for producing useful parts, not a general-purpose AI chatbot with a model viewer attached.

## Product Goal

Help a technically capable maker move from a practical need to a printable parametric model with less manual CAD work.

Examples include:

- brackets
- holders
- mounting plates
- adapters
- spacers
- bushings
- enclosures
- trays
- replacement knobs
- hose fittings
- drill templates
- T-track accessories
- boat accessories
- shop organizers

## Product Identity

This is not intended to copy ModelRift or any other existing application.

It may share the broad workflow category of AI-generated code-based CAD, but it must develop its own:

- interface
- visual system
- terminology
- project model
- AI prompting strategy
- validation pipeline
- parameter workflow
- printability tools
- feature priorities

## V1 User

V1 has one owner and one active application user.

The user:

- hosts Volundr on their own server
- configures Gemini API credentials for AI generation
- stores projects locally
- understands basic dimensions and 3D-printing concepts
- wants practical printable results
- may inspect and, where supported, edit generated CadQuery source

## V1 Value Proposition

The user can:

1. Explain the part they need.
2. Receive valid, parameterized CadQuery source.
3. Inspect the generated model.
4. Ask for targeted changes.
5. Restore earlier working revisions.
6. Download source, STEP, and printable STL artifacts.

## Product Principles

## Deployment Principle

Volundr is Docker-first. Docker Compose is the official V1 installation and runtime method.

V1 does not need to support a parallel native-host installation path. Keeping one supported deployment method reduces configuration drift, simplifies upgrades, and makes CAD execution isolation easier to test.


### Functional before decorative

Prioritize accurate dimensions, sensible tolerances, mounting features, and editability over organic or artistic modeling.

### Parametric before disposable

Generated models should expose meaningful variables and reusable modules rather than burying all geometry in magic numbers.

### Products before isolated solids

For complex functional designs, Volundr should model the product structure before generating source: components, owned features, editable parameters, derived dependencies, presets, assembly strategy, and separate printable outputs. This keeps changes such as tray count, carrier size, retention geometry, handle position, and reinforcement layout connected instead of forcing Gemini to rediscover the design from OpenSCAD text.

### Source-controlled by design

Every accepted model state is a revision. The user should never lose a working version because an AI revision failed.

### Local ownership

Project prompts, source files, STL outputs, and revision history remain on the self-hosted system.

### AI as an operator, not the kernel

The AI creates and revises code. CadQuery and OpenCascade are the deterministic geometry engine. Gemini is not a CAD kernel, and mesh inspection is not a replacement for B-Rep topology validation.

### Useful failure

Compiler failures, invalid geometry, and model limitations should be visible and understandable rather than hidden behind generic error messages.

## V1 Success Criteria

V1 is successful when the user can reliably create and revise several families of functional parts, including:

- mounting plate
- cylindrical holder
- box or tray
- spacer or bushing
- basic adapter
- tool or rod holder
- simple replacement handle

A model generation is considered successful when:

- CadQuery executes successfully in the isolated worker
- STEP and STL artifacts are produced for every required output
- B-Rep topology is valid
- the mesh has non-zero volume
- dimensions are plausible
- the model is viewable
- the source has named parameters
- the user can request a targeted revision
- the prior revision remains restorable

Printability assistance should be advisory and orientation-aware. It should identify practical FDM risks from the current STL orientation and printer profile, but it must not replace slicer validation or claim a guaranteed successful print.

## Long-Term Direction

Potential later capabilities include:

- automatic parameter controls
- model annotations
- slicer estimates
- printability analysis
- reusable component library
- image-assisted feedback
- imported SVG extrusion
- optional multi-provider AI support
- optional trusted multi-user operation

These are not V1 requirements.
