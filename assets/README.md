# Task inputs

`python main.py` reads [task_bundle.json](examples/task_bundle.json). A second complete input is [agentsafe_apple_counter.json](examples/agentsafe_apple_counter.json). Each record supplies a task ID, instruction, provenance, initial scene, ordered actions and a final goal. The source of each benchmark reference is recorded inside the JSON. Both runnable inputs use newly authored symbolic states and rules.

The older `scene.example.json` and `chain.example.json` illustrate a graph schema from the earlier design notes. The runnable verifier takes one complete task bundle per invocation.
