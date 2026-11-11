# Implementation guide

For the working public examples, see the [main.py quick start](../README.md). The mapping below covers the paper design.

## Provenance

Paper basis: *Jailbreaking Embodied LLMs via Action-Level Manipulation*, DOI `10.1145/3774906.3802758`, supplied 15-page PDF. Design: §5, PDF pages 5–8 (printed pp.1061–1064). Platform implementation: §6, PDF page 8 (printed p.1064).

The module boundaries, file names, schemas, configuration fields and CLI commands in this scaffold are proposed release interfaces. They are not claims about the authors' existing repository. No original source was available when this scaffold was prepared.

## Paper-to-module mapping

| Paper component | Proposed destination | Input | Output | Missing author material |
| --- | --- | --- | --- | --- |
| Proxy planning, §5.2.1 | `transformer/planner.py`, `models/` | Task, environment, action pool | Parameterized action chain | Actual model loader/backend, preparation method, prompts, output parsing |
| Command sanitization, §5.2.2 | `transformer/sanitizer.py` | Candidate chain and object references | Transformed command representation | Actual template and reference-resolution handling |
| Dominant-action identifier, §5.3.1 | `obfuscator/dominant_action.py` | Chain and category definitions | Selected position and score trace | Scoring template, parsing and tie/error handling |
| Cover branch and fusion, §5.3.2 | `obfuscator/cover_generator.py`, `fusion.py` | Chain, selected action, scene and pool | Fused candidate chain | Actual generation/fusion implementation and resource files |
| Chain extension, p.1062 | `obfuscator/extension.py` or existing module | Fused chain | Extended candidate chain | Whether implemented, limits and placement in the pipeline |
| Symbolic verifier, §5.4 | `verifier/` | Initial graph and candidate chain | Validity, final state or failure details | Full action rules, graph schema, state conversion and transition code |
| Planner-verifier refinement, §5.4.1 | `pipeline/refinement.py` | Candidate chain and failure feedback | Refined chain or terminal failure | Actual feedback routing, stopping conditions and retry policy |
| Target framework, §6.1 | `adapters/progprompt/` | Exported prompt/chain and environment context | Target planning response | Framework revision, templates, parsing and model interface |
| Simulator, §6.1 | `adapters/virtualhome/` | Target plan and scene | Simulator commands/state | Build, IDs, API settings and action mappings |
| Robotic platform, §6.2 | `adapters/xarm/` | Target plan and coordinate hints | SDK operations/state | SDK wrappers, camera/coordinate interfaces and calibrations |

## Proposed data contracts

Finalize these against the original code before implementation integration.

- **Action:** canonical name and explicit parameters; retain entity IDs for symbolic verification even if exported text uses co-references. Document how the original code reconciles the two representations.
- **Scene:** entities and pairwise relations, plus agent state needed by action rules. Text/image-to-graph conversion is a separate input step, not functionality to assume from the presence of a camera.
- **Action pool:** supported operations, typed arguments and environment-specific mappings. Do not assume `pick`, `pick_up`, `put_in` and simulator API calls are interchangeable.
- **Verification feedback:** validity, failing action index/name, failed preconditions, and enough state context for refinement. Use an explicit indexing convention.
- **Run result:** final chain, verification outcome, termination reason, and source/config/model identifiers. An executability report is not a safety judgment.

The paper describes checking preconditions, applying effects only when valid, and returning structured feedback on failure. It does not publish a complete action-rule table, serialized feedback schema, or all state fields. Those must come from the implementation.

## Proposed integration behavior

1. Resolve configuration and required paths. Reject unresolved values and unsupported action names.
2. Validate inputs before loading the proxy. Keep the standalone verifier usable without model dependencies where feasible.
3. Generate and transform a candidate chain through the three core components.
4. Start each candidate verification from a fresh copy of the original scene. Do not carry a rejected candidate's partial state into the next attempt.
5. On failed preconditions, return structured feedback to the author-defined refinement step. Bound retries and return an explicit failure if no valid chain is produced.
6. Export the chain and report before any separate platform integration.

Fresh state copies, strict parsing, finite retry limits and a separate export boundary are proposed engineering requirements. They are not claimed settings from the paper. The paper describes refinement until a valid chain is obtained without specifying a numerical retry limit; the authors must define one for the release.

## Runnable tabletop material

The repository includes two [complete task inputs](../assets/README.md), a [symbolic verifier](../demo/tabletop.py), and a [local Ollama example](../examples/ollama_local.py). Their coverage is recorded in the [run report](run-status.md).

## Platform separation

**Core:** model inference, structured transformations and symbolic verification. No target-system feedback is required for the offline refinement loop described in §5.1.

**VirtualHome/ProgPrompt:** separate target model calls from simulator action execution. Supply environment IDs, scene acquisition steps, action mappings, launch parameters and connection details from the original implementation.

**xArm:** optional integration. The paper uses two RGB-D cameras and provides object-coordinate hints. The source must explain where coordinates originate and how they are transformed; do not imply that a complete perception pipeline is available solely because cameras are present.
