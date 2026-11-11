# Runtime checks

The public entrypoint is `python main.py`. The following checks used Python 3.11.13 on Windows. The verifier was also run with Python's site packages disabled.

| Command or input | Outcome |
| --- | --- |
| `python main.py` | Exit 0. `cup_1` ended on `tray_1`, and the gripper was empty. |
| `python main.py verify --task assets/examples/agentsafe_apple_counter.json` | Exit 0. `apple_1` ended on `counter_1`, and the gripper was empty. |
| Cup bundle with `tray.occupied` set to `true` | Exit 1 at `place`. The report names `destination_occupied` and restores the initial scene. |
| `python main.py ollama` | Exit 1. A direct call to `127.0.0.1:11434` received Windows error 10061 (connection refused). Live model availability and response quality remain unverified. |

The Ollama client's request and response handling were exercised with a simulated HTTP response. A live response requires a reachable server with `llama3.1` installed. Full Blindfold planning, obfuscation and platform execution remain outside the runnable examples.

See the [quick start](../README.md) for the commands and the [earlier dependency smoke test](environment-validation.md) for the optional Transformers stack.
