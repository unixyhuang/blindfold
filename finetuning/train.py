"""Standard supervised training for the bundled household instruction/step pairs."""

import json
import math
from pathlib import Path

from finetuning.data import SFTCollator, load_training_pairs, tokenize_pairs


ROOT = Path(__file__).resolve().parents[1]


def add_arguments(parser):
    parser.add_argument("--model", type=Path, required=True, help="Local Hugging Face model and tokenizer directory.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "weights" / "local-slm")
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--max-steps", type=int, default=-1, help="Override epochs with a positive step limit.")
    parser.add_argument("--precision", choices=["float32", "float16", "bfloat16"], default="float32")
    parser.add_argument("--device", choices=["auto", "cpu"], default="auto")
    parser.add_argument("--seed", type=int, default=42)


def run_training(args):
    model_path = args.model.resolve()
    output = args.output_dir.resolve()
    if not model_path.is_dir():
        raise ValueError("--model must point to a local Hugging Face model and tokenizer directory.")
    if output.exists() and any(output.iterdir()):
        raise ValueError("The output directory must be empty. Choose a new directory for this training run.")
    if (args.max_length < 8 or not math.isfinite(args.epochs) or args.epochs <= 0 or args.batch_size < 1
            or args.gradient_accumulation < 1 or args.learning_rate <= 0
            or not math.isfinite(args.learning_rate)
            or args.max_steps == 0 or args.max_steps < -1):
        raise ValueError("Training lengths, counts and learning rate must be positive; max-steps also accepts -1.")

    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments, set_seed
    except ImportError as error:
        raise RuntimeError("Install the dependencies in requirements/finetune.txt to use finetune.") from error

    use_cpu = args.device == "cpu"
    if args.precision == "float16" and (use_cpu or not torch.cuda.is_available()):
        raise ValueError("float16 training requires a CUDA GPU. Choose float32 for CPU training.")
    if args.precision == "bfloat16" and not use_cpu and torch.cuda.is_available() and not torch.cuda.is_bf16_supported():
        raise ValueError("This CUDA GPU does not support bfloat16. Choose a supported precision.")

    pairs = load_training_pairs(ROOT)
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True, trust_remote_code=False)
    if tokenizer.eos_token_id is None:
        raise ValueError("The tokenizer must define an EOS token.")
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    records = tokenize_pairs(pairs, tokenizer, args.max_length)

    set_seed(args.seed)
    model = AutoModelForCausalLM.from_pretrained(
        model_path, local_files_only=True, trust_remote_code=False,
        dtype=torch.float32, low_cpu_mem_usage=True,
    )
    model.config.pad_token_id = tokenizer.pad_token_id
    if len(tokenizer) > model.get_input_embeddings().num_embeddings:
        raise ValueError("Tokenizer vocabulary exceeds the model's embedding vocabulary.")
    maximum_positions = getattr(model.config, "max_position_embeddings", None)
    if maximum_positions and max(len(record["input_ids"]) for record in records) > maximum_positions:
        raise ValueError("The tokenized dataset exceeds the model's context length.")
    model.config.use_cache = False

    arguments = TrainingArguments(
        output_dir=str(output), num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation,
        learning_rate=args.learning_rate, max_steps=args.max_steps,
        use_cpu=use_cpu, fp16=args.precision == "float16", bf16=args.precision == "bfloat16",
        seed=args.seed, data_seed=args.seed, report_to="none",
        logging_steps=1, save_strategy="epoch", save_total_limit=2,
        dataloader_num_workers=0, dataloader_pin_memory=False,
        optim="adamw_torch", remove_unused_columns=False,
    )
    trainer = Trainer(
        model=model, args=arguments, train_dataset=records,
        data_collator=SFTCollator(tokenizer.pad_token_id), processing_class=tokenizer,
    )
    result = trainer.train()
    final = output / "final"
    trainer.save_model(str(final))
    tokenizer.save_pretrained(final)
    trainer.save_metrics("train", result.metrics)
    trainer.save_state()

    if trainer.is_world_process_zero():
        selection = json.loads((ROOT / "tasks/safeagentbench/selection.json").read_text(encoding="utf-8"))
        manifest = {
            "base_model": str(model_path), "training_pairs": len(records),
            "dataset_sha256": selection["records_sha256"],
            "dataset_source_revision": selection["source_revision"],
            "target": "JSON object containing the upstream ordinary-task steps",
            "max_length": args.max_length, "precision": args.precision,
            "epochs": args.epochs, "max_steps": args.max_steps,
            "batch_size": args.batch_size, "gradient_accumulation": args.gradient_accumulation,
            "learning_rate": args.learning_rate, "seed": args.seed,
            "optimizer_steps": trainer.state.global_step,
            "final_directory": "final", "metrics": result.metrics,
            "versions": {"torch": torch.__version__},
        }
        import transformers
        manifest["versions"]["transformers"] = transformers.__version__
        (output / "training_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "trained", "training_pairs": len(records),
                          "optimizer_steps": trainer.state.global_step, "model_directory": str(final)}))
    return 0
