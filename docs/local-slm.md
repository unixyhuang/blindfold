# Local SLM fine-tuning

The `finetune` command performs standard supervised fine-tuning on the 100 released SafeAgentBench household tasks. It learns to produce a JSON `steps` array from a task instruction and scene name. Its data handling follows the prompt-masking pattern discussed in reference [26], *Language Models Resist Alignment: Evidence From Data Compression*. The implementation uses Hugging Face `Trainer` with the causal language model's native loss. [Reference implementation](https://github.com/PKU-Alignment/llms-resist-alignment/tree/c70a483370b6821667f692ab7af3a92b8dd3f389/code/setting2/training/safe_rlhf)

## Prepare the training environment

Use Python 3.11 and install the shared inference/training dependencies in an isolated environment. For a compatible NVIDIA GPU and driver:

```sh
python -m venv .venv
```

Activate it with `source .venv/bin/activate` on Linux, or `.\.venv\Scripts\Activate.ps1` in Windows PowerShell. Then install:

```sh
python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cu126
python -m pip install -r requirements/model.txt
python -m pip check
```

For a CPU training environment, replace the first installation command's index URL with `https://download.pytorch.org/whl/cpu`. CPU training speed and memory requirements depend on model size.

Prepare a local Hugging Face model directory containing configuration, model weights and tokenizer files. Obtain the base checkpoint under its original model license and access terms. The [README](../README.md#prepare-llama-31) documents preparation of `meta-llama/Llama-3.1-8B-Instruct`. Training and inference read Hugging Face weights directly from the directory supplied with `--model`.

## Train

From the repository root:

```sh
python main.py finetune --model /path/to/huggingface-model --output-dir weights/local-slm
```

The default configuration uses full-parameter training, float32, one epoch, batch size 1, maximum length 1024, learning rate `2e-5` and seed 42. These are release defaults selected for this implementation. Size the training device for model parameters, gradients, optimizer state and activations. Full Llama-3.1-8B training requires substantially more memory than inference; a 16 GB GPU cannot hold the default full-parameter training state.

The CLI supports `--precision bfloat16` or `--precision float16` for compatible hardware, `--device cpu`, `--batch-size`, `--gradient-accumulation`, `--epochs`, `--learning-rate`, `--max-length` and a positive `--max-steps` limit. Run `python main.py finetune --help` for the full interface. Choose an empty output directory for every run.

## Data and loss

- The loader verifies the released collection's SHA256, task IDs and source rows against `selection.json`.
- Each prompt contains the ordinary task's `instruction` and `scene_name`. The target is `{"steps": [...]}` from the source `step` field.
- A model's chat template supplies the conversation boundaries. Tokenizers without one use a documented user/assistant text boundary and EOS.
- User-prefix labels and padding labels use `-100`. Long records raise a task-specific error before training, keeping target answers intact.
- The collator returns `input_ids`, `attention_mask` and `labels`. The model computes its standard causal language modeling loss, and `Trainer` handles optimization and logging.

The training target describes the upstream annotated steps. It is independent of the deterministic tabletop verifier and of the paper's adversarial planning and obfuscation pipeline.

All 100 released records are used for training. Measure generalization on separately held-out tasks.

## Saved outputs

```text
weights/local-slm/
  checkpoint-*/             Training checkpoint and optimizer state
  final/                    Safetensors weights, model configuration and tokenizer
  train_results.json        Training metrics
  trainer_state.json        Training state
  training_manifest.json    Dataset hash, source revision, model path and run settings
```

The default `weights/` directory is ignored by Git and excluded from release ZIPs.

## Load the trained model for inference

The final directory contains a complete Hugging Face model and tokenizer. Load it directly through the same inference entrypoint as the base checkpoint:

```sh
python main.py infer --model weights/local-slm/final
python main.py infer --model weights/local-slm/final --device cpu
```

The command preserves the tokenizer's chat template, uses greedy decoding and prints only the generated answer to a fixed descriptive question. Automatic placement retains the checkpoint's dtype; CPU execution uses float32. This query checks model loading and generation. Evaluate learned task-step accuracy separately using held-out tasks.

## Validation

CI trains a small Llama model for two optimizer steps and checks that its parameters change and its saved checkpoint can generate text. Full-parameter Llama-3.1-8B training and held-out accuracy have not been evaluated. The separate [inference guide](../prompts/progprompt/safeagentbench.md) describes NF4 model preparation and ordinary task planning.

## Provenance

The source design reference is PKU-Alignment's Apache-2.0-licensed SFT code at revision `c70a483370b6821667f692ab7af3a92b8dd3f389`. The new modules independently adapt its answer-only labeling and causal-LM loss interface. The batch contract, chat-template handling and checkpoint interface are implemented for this repository. [Upstream data module](https://github.com/PKU-Alignment/llms-resist-alignment/blob/c70a483370b6821667f692ab7af3a92b8dd3f389/code/setting2/training/safe_rlhf/datasets/supervised.py), [upstream SFT trainer](https://github.com/PKU-Alignment/llms-resist-alignment/blob/c70a483370b6821667f692ab7af3a92b8dd3f389/code/setting2/training/safe_rlhf/finetune/trainer.py)
