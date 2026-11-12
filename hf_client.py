"""Generate text from local Hugging Face causal language model weights."""

import json
from pathlib import Path


QUESTION = "The empty cup is on the tray. Where is the cup? Reply in English."


def add_arguments(parser):
    parser.add_argument("--model", type=Path, required=True,
                        help="Local Hugging Face model and tokenizer directory.")
    parser.add_argument("--device", choices=["auto", "cpu"], default="auto",
                        help="Automatically place weights on available devices, or use CPU only.")
    parser.add_argument("--max-new-tokens", type=int, default=32)
    parser.add_argument("--prompt", default=QUESTION, help="Question for the local model.")
    parser.add_argument("--training-free", action="store_true",
                        help="Retry decoding configurations, system prompts and assistant prefills until the reply is not a refusal.")
    parser.add_argument("--samples", type=int, default=1,
                        help="Samples per decoding profile in training-free mode.")
    parser.add_argument("--report", type=Path,
                        help="Write the training-free attempt trace to this JSON file.")


class LocalGenerator:
    """Reuse one local causal LM and tokenizer across batches of prompts."""

    def __init__(self, model_path, *, device="auto"):
        model_path = Path(model_path).resolve()
        if not model_path.is_dir():
            raise ValueError("--model must point to a local Hugging Face model and tokenizer directory.")
        if device not in ("auto", "cpu"):
            raise ValueError("--device must be auto or cpu.")
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as error:
            raise RuntimeError("Install the dependencies in requirements/model.txt to use local inference.") from error

        self.tokenizer = AutoTokenizer.from_pretrained(
            model_path, local_files_only=True, trust_remote_code=False, padding_side="left",
        )
        if self.tokenizer.eos_token_id is None:
            raise ValueError("The tokenizer must define an EOS token.")
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.model = AutoModelForCausalLM.from_pretrained(
            model_path, local_files_only=True, trust_remote_code=False,
            dtype=torch.float32 if device == "cpu" else "auto",
            device_map={"": "cpu"} if device == "cpu" else "auto", low_cpu_mem_usage=True,
        ).eval()
        if len(self.tokenizer) > self.model.get_input_embeddings().num_embeddings:
            raise ValueError("Tokenizer vocabulary exceeds the model's embedding vocabulary.")

    def _encode(self, prompt, completion, system=None, prefill=None):
        if completion:
            parts = [part for part in (system, prompt, prefill) if part]
            return self.tokenizer.encode("\n\n".join(parts), add_special_tokens=True)
        if self.tokenizer.chat_template:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            if prefill:
                messages.append({"role": "assistant", "content": prefill})
                return self.tokenizer.apply_chat_template(
                    messages, tokenize=True, add_generation_prompt=False, continue_final_message=True,
                )
            return self.tokenizer.apply_chat_template(
                messages, tokenize=True, add_generation_prompt=True,
            )
        # Match the text boundary used by the SFT data loader.
        text = "\n\n".join(part for part in (system, prompt) if part)
        prefix = self.tokenizer.encode(f"User:\n{text}\nAssistant:\n{prefill or ''}", add_special_tokens=False)
        if self.tokenizer.bos_token_id is not None:
            prefix.insert(0, self.tokenizer.bos_token_id)
        return prefix

    def generate_many(self, prompts, *, max_new_tokens=256, completion=False,
                      do_sample=False, temperature=None, top_p=None, top_k=None,
                      repetition_penalty=None, seed=None, system=None, prefill=None) -> list[str]:
        """Return one raw completion per prompt, preserving order and empty responses."""
        import torch

        if isinstance(prompts, str):
            raise ValueError("Expected a sequence of prompt strings.")
        prefixes = []
        for prompt in prompts:
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError("The model prompt must be a nonempty string.")
            prefixes.append(self._encode(prompt, completion, system=system, prefill=prefill))
        if not prefixes:
            return []
        if type(max_new_tokens) is not int or max_new_tokens <= 0:
            raise ValueError("--max-new-tokens must be positive.")
        if do_sample:
            if temperature is not None and (type(temperature) is not float or temperature <= 0):
                raise ValueError("temperature must be a positive float.")
            if top_p is not None and (type(top_p) is not float or not 0 < top_p <= 1):
                raise ValueError("top_p must be a float in (0, 1].")
            if top_k is not None and (type(top_k) is not int or top_k <= 0):
                raise ValueError("top_k must be a positive integer.")
            if repetition_penalty is not None and (type(repetition_penalty) is not float or repetition_penalty <= 0):
                raise ValueError("repetition_penalty must be a positive float.")
        width = max(map(len, prefixes))
        maximum_positions = getattr(self.model.config, "max_position_embeddings", None)
        if maximum_positions and width + max_new_tokens > maximum_positions:
            raise ValueError("The prompt and requested output exceed the model's context length.")
        batch = self.tokenizer.pad(
            {"input_ids": prefixes}, padding=True, return_attention_mask=True, return_tensors="pt",
        ).to(self.model.device)
        generation = {"max_new_tokens": max_new_tokens, "num_beams": 1, "do_sample": do_sample,
                      "pad_token_id": self.tokenizer.pad_token_id}
        if do_sample:
            if temperature is not None:
                generation["temperature"] = temperature
            if top_p is not None:
                generation["top_p"] = top_p
            if top_k is not None:
                generation["top_k"] = top_k
            if repetition_penalty is not None:
                generation["repetition_penalty"] = repetition_penalty
        if seed is not None:
            if type(seed) is not int or seed < 0:
                raise ValueError("seed must be a nonnegative integer.")
            torch.manual_seed(seed)
        with torch.inference_mode():
            output = self.model.generate(**batch, **generation)
        return self.tokenizer.batch_decode(output[:, width:], skip_special_tokens=True)


def generate_text(prompt: str, model_path, *, device="auto", max_new_tokens=32, completion=False) -> str:
    """Generate from a literal program prefix or a tokenizer-formatted chat turn."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("The model prompt must be a nonempty string.")
    if type(max_new_tokens) is not int or max_new_tokens <= 0:
        raise ValueError("--max-new-tokens must be positive.")
    generator = LocalGenerator(model_path, device=device)
    answer, = generator.generate_many([prompt], max_new_tokens=max_new_tokens, completion=completion)
    if not answer.strip():
        raise RuntimeError("The model returned no answer text.")
    return answer if completion else answer.strip()


def run_inference(args):
    if not getattr(args, "training_free", False):
        print(generate_text(args.prompt, args.model, device=args.device,
                            max_new_tokens=args.max_new_tokens))
        return 0
    from progprompt.training_free import RefusalError, generate_without_refusal

    generator = LocalGenerator(args.model, device=args.device)
    try:
        result = generate_without_refusal(generator, args.prompt,
                                          max_new_tokens=args.max_new_tokens,
                                          samples_per_profile=getattr(args, "samples", 1))
    except RefusalError as error:
        report = {"status": "refused", "prompt": args.prompt, "attempts": error.attempts}
        if getattr(args, "report", None):
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"status": "refused", "attempts": len(error.attempts)}, indent=2))
        return 2
    if getattr(args, "report", None):
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
    print(result.answer)
    return 0
