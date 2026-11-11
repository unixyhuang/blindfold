"""Run an ordinary descriptive query against local Hugging Face model weights."""

from pathlib import Path


QUESTION = "The empty cup is on the tray. Where is the cup? Reply in English."


def add_arguments(parser):
    parser.add_argument("--model", type=Path, required=True,
                        help="Local Hugging Face model and tokenizer directory.")
    parser.add_argument("--device", choices=["auto", "cpu"], default="auto",
                        help="Automatically place weights on available devices, or use CPU only.")
    parser.add_argument("--max-new-tokens", type=int, default=32)


def run_inference(args):
    model_path = args.model.resolve()
    if not model_path.is_dir():
        raise ValueError("--model must point to a local Hugging Face model and tokenizer directory.")
    if args.max_new_tokens <= 0:
        raise ValueError("--max-new-tokens must be positive.")
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as error:
        raise RuntimeError("Install the dependencies in requirements/model.txt to use infer.") from error

    tokenizer = AutoTokenizer.from_pretrained(
        model_path, local_files_only=True, trust_remote_code=False,
    )
    if tokenizer.eos_token_id is None:
        raise ValueError("The tokenizer must define an EOS token.")
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    if tokenizer.chat_template:
        prefix = tokenizer.apply_chat_template(
            [{"role": "user", "content": QUESTION}],
            tokenize=True, add_generation_prompt=True,
        )
    else:
        # Match the text boundary used by the SFT data loader.
        prefix = tokenizer.encode(f"User:\n{QUESTION}\nAssistant:\n", add_special_tokens=False)
        if tokenizer.bos_token_id is not None:
            prefix.insert(0, tokenizer.bos_token_id)

    model = AutoModelForCausalLM.from_pretrained(
        model_path, local_files_only=True, trust_remote_code=False,
        dtype=torch.float32 if args.device == "cpu" else "auto",
        device_map={"": "cpu"} if args.device == "cpu" else "auto",
        low_cpu_mem_usage=True,
    )
    if len(tokenizer) > model.get_input_embeddings().num_embeddings:
        raise ValueError("Tokenizer vocabulary exceeds the model's embedding vocabulary.")
    maximum_positions = getattr(model.config, "max_position_embeddings", None)
    if maximum_positions and len(prefix) + args.max_new_tokens > maximum_positions:
        raise ValueError("The question and requested output exceed the model's context length.")
    inputs = torch.tensor([prefix], dtype=torch.long, device=model.device)
    model.eval()
    with torch.inference_mode():
        output = model.generate(
            input_ids=inputs, attention_mask=torch.ones_like(inputs),
            max_new_tokens=args.max_new_tokens, do_sample=False, num_beams=1,
            temperature=None, top_p=None, top_k=None,
            pad_token_id=tokenizer.pad_token_id,
        )
    answer = tokenizer.decode(output[0, len(prefix):], skip_special_tokens=True).strip()
    if not answer:
        raise RuntimeError("The model returned no answer text for the descriptive query.")
    print(answer)
    return 0
