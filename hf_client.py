"""Generate text from local Hugging Face causal language model weights."""

from pathlib import Path


QUESTION = "The empty cup is on the tray. Where is the cup? Reply in English."


def add_arguments(parser):
    parser.add_argument("--model", type=Path, required=True,
                        help="Local Hugging Face model and tokenizer directory.")
    parser.add_argument("--device", choices=["auto", "cpu"], default="auto",
                        help="Automatically place weights on available devices, or use CPU only.")
    parser.add_argument("--max-new-tokens", type=int, default=32)


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

    def _encode(self, prompt, completion):
        if completion:
            return self.tokenizer.encode(prompt, add_special_tokens=True)
        if self.tokenizer.chat_template:
            return self.tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}], tokenize=True, add_generation_prompt=True,
            )
        # Match the text boundary used by the SFT data loader.
        prefix = self.tokenizer.encode(f"User:\n{prompt}\nAssistant:\n", add_special_tokens=False)
        if self.tokenizer.bos_token_id is not None:
            prefix.insert(0, self.tokenizer.bos_token_id)
        return prefix

    def generate_many(self, prompts, *, max_new_tokens=256, completion=False) -> list[str]:
        """Return one raw completion per prompt, preserving order and empty responses."""
        import torch

        if isinstance(prompts, str):
            raise ValueError("Expected a sequence of prompt strings.")
        prefixes = []
        for prompt in prompts:
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError("The model prompt must be a nonempty string.")
            prefixes.append(self._encode(prompt, completion))
        if not prefixes:
            return []
        if type(max_new_tokens) is not int or max_new_tokens <= 0:
            raise ValueError("--max-new-tokens must be positive.")
        width = max(map(len, prefixes))
        maximum_positions = getattr(self.model.config, "max_position_embeddings", None)
        if maximum_positions and width + max_new_tokens > maximum_positions:
            raise ValueError("The prompt and requested output exceed the model's context length.")
        batch = self.tokenizer.pad(
            {"input_ids": prefixes}, padding=True, return_attention_mask=True, return_tensors="pt",
        ).to(self.model.device)
        with torch.inference_mode():
            output = self.model.generate(
                **batch, max_new_tokens=max_new_tokens, do_sample=False, num_beams=1,
                temperature=None, top_p=None, top_k=None, pad_token_id=self.tokenizer.pad_token_id,
            )
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
    print(generate_text(QUESTION, args.model, device=args.device, max_new_tokens=args.max_new_tokens))
    return 0
