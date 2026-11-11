# Intended implementation layout

This is a proposed destination layout for the original code. None of the Python files below exists in the scaffold. The directory names are packaging suggestions, not recovered source paths.

```text
src/blindfold/
├── __init__.py
├── cli.py                         # verify/generate commands; no implicit platform execution
├── schemas.py                     # task, scene, action, chain, feedback, output contracts
├── models/
│   ├── base.py                    # proxy interface
│   └── local_proxy.py             # actual local inference backend and model loading
├── transformer/
│   ├── planner.py                 # proxy planning (§5.2.1)
│   └── sanitizer.py               # command sanitization (§5.2.2)
├── obfuscator/
│   ├── dominant_action.py         # dominant-action identification (§5.3.1)
│   ├── cover_generator.py         # branch creation/completion (§5.3.2)
│   ├── fusion.py                  # chain fusion (§5.3.2)
│   └── extension.py               # trailing chain extension (p.1062), if separate in source
├── verifier/
│   ├── scene_graph.py             # symbolic entities and spatial relations (§5.4)
│   ├── action_rules.py            # complete parameter/precondition/effect definitions
│   ├── transition.py              # deterministic state transitions
│   └── checker.py                 # sequential checking and structured feedback
├── pipeline/
│   ├── runner.py                  # transformation -> obfuscation -> verification
│   └── refinement.py              # planner feedback and explicit termination
└── adapters/
    ├── progprompt/adapter.py      # target framework interface (§6.1)
    ├── virtualhome/adapter.py     # environment/API and action mapping (§6.1)
    └── xarm/adapter.py            # SDK/action mapping and coordinates (§6.2)
```

Earlier packaging ideas for a future source release are listed below. The public examples run directly from `main.py`.

| Destination | Content to supply |
| --- | --- |
| `main.py` | Implemented public entrypoint for both examples |
| `requirements/core.txt` | Candidate pins now supplied; validate against integrated source |
| `requirements/virtualhome.txt` | Simulator/target adapter dependency pins |
| `requirements/xarm.txt` | SDK pin now supplied; camera dependencies and firmware support remain pending |
| `prompts/` | Released templates plus a manifest identifying stages, variables and versions |
| `assets/action_pool.json` | Complete action names, argument types and platform mapping |
| `assets/rules/` | Complete preconditions/effects, in the format consumed by source |
| `assets/categories.json` | Definitions consumed by dominant-action scoring |
| `assets/examples/task_bundle.json` | Implemented input for the tabletop verifier |
| `docs/virtualhome.md` | Exact simulator installation, scene acquisition and launch/API setup, if released |
| `docs/xarm.md` | Exact SDK setup, cameras and coordinate inputs, if released |
| `LICENSE` | Author-selected source-code license |
| `THIRD_PARTY_NOTICES.md` | Actual redistributed components and their notices |

Keep model weights, simulator binaries, local calibration, secrets and generated outputs outside tracked source by default. Replace ignored resources with documented acquisition/setup steps when needed.
