"""Prepare answer-only SFT labels for the released household task collection.

The preprocessing follows the standard prompt-masking pattern used in
PKU-Alignment/llms-resist-alignment, code/setting2/training/safe_rlhf/datasets/
supervised.py. This module is independently implemented for this repository.
"""

import hashlib
import json
from pathlib import Path


IGNORE_INDEX = -100
DATA_FIELDS = {"task_id", "source_row", "instruction", "scene_name", "step", "final_state"}


def load_training_pairs(root: Path) -> list[dict]:
    """Read and validate this repository's fixed 100-task collection."""
    folder = Path(root) / "tasks" / "safeagentbench"
    body = (folder / "tasks.jsonl").read_bytes()
    manifest = json.loads((folder / "selection.json").read_text(encoding="utf-8"))
    if manifest.get("dataset") != "SafeAgentBench" or manifest.get("source_split") != "safe_detailed":
        raise ValueError("Training requires the released SafeAgentBench safe_detailed collection.")
    if hashlib.sha256(body).hexdigest() != manifest.get("records_sha256"):
        raise ValueError("Training data checksum does not match selection.json.")
    records = [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]
    if len(records) != 100 or manifest.get("records") != 100:
        raise ValueError("Training requires exactly the released 100 task records.")

    pairs = []
    task_ids = set()
    source_rows = []
    for record in records:
        if not isinstance(record, dict) or set(record) != DATA_FIELDS:
            raise ValueError("A training task has unexpected or missing fields.")
        task_id = record["task_id"]
        number = record["source_row"]
        if type(number) is not int or number <= 0 or task_id != f"sab-safe-{number:04d}":
            raise ValueError("A task ID does not match its source row.")
        if task_id in task_ids:
            raise ValueError(f"Duplicate training task {task_id}.")
        for field in ("instruction", "scene_name"):
            if not isinstance(record[field], str) or not record[field].strip():
                raise ValueError(f"{task_id} requires a nonempty {field}.")
        steps = record["step"]
        if not isinstance(steps, list) or not steps or any(
            not isinstance(step, str) or not step.strip() for step in steps
        ):
            raise ValueError(f"{task_id} requires nonempty recorded steps.")
        prompt = (
            "Describe the annotated steps for this ordinary household task.\n"
            f"Scene: {record['scene_name']}\n"
            f"Instruction: {record['instruction']}\n"
            'Return a JSON object with one key, "steps", containing an array of strings.'
        )
        pairs.append({
            "task_id": task_id,
            "prompt": prompt,
            "answer": json.dumps({"steps": steps}, ensure_ascii=False),
        })
        task_ids.add(task_id)
        source_rows.append(number)
    if source_rows != manifest.get("source_rows"):
        raise ValueError("Training source rows do not match selection.json.")
    return pairs


def tokenize_pairs(pairs: list[dict], tokenizer, max_length: int) -> list[dict]:
    """Encode whole samples and mask all user-prefix labels with IGNORE_INDEX.

    A model's chat template determines its conversation boundaries. Tokenizers
    without a chat template use an explicit user/assistant text boundary. Long
    records raise an error before training so their target answers stay intact.
    """
    if type(max_length) is not int or max_length <= 0:
        raise ValueError("max_length must be a positive integer.")
    if not pairs:
        raise ValueError("At least one training pair is required.")
    records = []
    for pair in pairs:
        task_id = pair.get("task_id", "unknown")
        prompt, answer = pair.get("prompt"), pair.get("answer")
        if not isinstance(prompt, str) or not prompt or not isinstance(answer, str) or not answer:
            raise ValueError(f"{task_id} requires nonempty prompt and answer strings.")
        if getattr(tokenizer, "chat_template", None):
            user = [{"role": "user", "content": prompt}]
            prefix = list(tokenizer.apply_chat_template(user, tokenize=True, add_generation_prompt=True))
            full = list(tokenizer.apply_chat_template(
                user + [{"role": "assistant", "content": answer}],
                tokenize=True, add_generation_prompt=False,
            ))
            if full[:len(prefix)] != prefix:
                raise ValueError(f"{task_id}: the chat template does not have a stable assistant prefix.")
        else:
            if tokenizer.eos_token_id is None:
                raise ValueError("A tokenizer without a chat template requires an EOS token.")
            prefix = list(tokenizer.encode(f"User:\n{prompt}\nAssistant:\n", add_special_tokens=False))
            if tokenizer.bos_token_id is not None:
                prefix.insert(0, tokenizer.bos_token_id)
            target = list(tokenizer.encode(answer, add_special_tokens=False))
            full = prefix + target + [tokenizer.eos_token_id]
        if len(full) <= len(prefix):
            raise ValueError(f"{task_id} has no assistant tokens to supervise.")
        if len(full) > max_length:
            raise ValueError(
                f"{task_id} needs {len(full)} tokens, exceeding max_length={max_length}. "
                "Increase max_length or review the record before training."
            )
        records.append({
            "input_ids": full,
            "attention_mask": [1] * len(full),
            "labels": [IGNORE_INDEX] * len(prefix) + full[len(prefix):],
        })
    return records


class SFTCollator:
    """Right-pad batches and return only the model's three tensor inputs."""

    def __init__(self, pad_token_id: int):
        if type(pad_token_id) is not int or pad_token_id < 0:
            raise ValueError("pad_token_id must be a nonnegative integer.")
        self.pad_token_id = pad_token_id

    def __call__(self, features: list[dict]) -> dict:
        import torch

        if not features:
            raise ValueError("Cannot collate an empty batch.")
        for feature in features:
            if set(feature) != {"input_ids", "attention_mask", "labels"}:
                raise ValueError("SFT batches require input_ids, attention_mask and labels only.")
            length = len(feature["input_ids"])
            if not length or len(feature["attention_mask"]) != length or len(feature["labels"]) != length:
                raise ValueError("SFT input, mask and label lengths must match and be nonempty.")
        width = max(len(feature["input_ids"]) for feature in features)
        shape = (len(features), width)
        batch = {
            "input_ids": torch.full(shape, self.pad_token_id, dtype=torch.long),
            "attention_mask": torch.zeros(shape, dtype=torch.long),
            "labels": torch.full(shape, IGNORE_INDEX, dtype=torch.long),
        }
        for row, feature in enumerate(features):
            length = len(feature["input_ids"])
            for field in batch:
                batch[field][row, :length] = torch.tensor(feature[field], dtype=torch.long)
        batch["labels"].masked_fill_(batch["attention_mask"].eq(0), IGNORE_INDEX)
        return batch
