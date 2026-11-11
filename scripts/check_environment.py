"""Check core dependencies using a tiny randomly initialized model, offline.

This checks the software environment, not Blindfold or Llama-3.1-8B weights.
Run after dependency installation: python scripts/check_environment.py --require-cuda
"""
import argparse
import importlib.metadata
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--require-cuda', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    expected = {
        'torch': '2.8.0', 'transformers': '4.57.6', 'accelerate': '1.12.0',
        'tokenizers': '0.22.2', 'huggingface-hub': '0.36.0',
        'safetensors': '0.7.0', 'numpy': '1.26.4',
    }
    result = {
        'scope': 'Offline dependency smoke check using random tiny Llama weights; no paper implementation, external model or device adapter.',
        'python': platform.python_version(), 'platform': platform.system(),
        'architecture': platform.machine(), 'versions': {}, 'checks': {},
        'require_cuda': args.require_cuda, 'success': False,
    }
    try:
        assert sys.version_info[:2] == (3, 11), 'Selected baseline requires Python 3.11'
        for package, version in expected.items():
            installed = importlib.metadata.version(package)
            result['versions'][package] = installed
            assert installed.split('+')[0] == version, (package, installed, version)
        result['checks']['selected_versions'] = 'PASS'
        check = subprocess.run([sys.executable, '-m', 'pip', 'check'],
                               capture_output=True, text=True, check=False)
        result['pip_check'] = check.stdout.strip() + check.stderr.strip()
        assert check.returncode == 0, result['pip_check']
        result['checks']['pip_check'] = 'PASS'

        import accelerate
        import huggingface_hub
        import numpy as np
        import safetensors
        import tokenizers
        import torch
        import transformers
        from tokenizers import Tokenizer
        from tokenizers.models import WordLevel
        from tokenizers.pre_tokenizers import Whitespace
        from transformers import AutoModelForCausalLM, AutoTokenizer, LlamaConfig, PreTrainedTokenizerFast

        result['checks']['core_imports'] = 'PASS'
        result['cuda_build'] = torch.version.cuda
        result['cuda_available'] = torch.cuda.is_available()
        if args.require_cuda:
            assert result['cuda_available'], 'CUDA is required but unavailable'
        if result['cuda_available']:
            result['gpu_name'] = torch.cuda.get_device_name(0)
            result['gpu_capability'] = list(torch.cuda.get_device_capability(0))

        values = np.arange(6, dtype=np.float32).reshape(2, 3)
        assert np.array_equal(torch.from_numpy(values).numpy(), values)
        result['checks']['numpy_torch_interop'] = 'PASS'
        torch.manual_seed(7)

        tokenizer_impl = Tokenizer(WordLevel({
            '[PAD]': 0, '[BOS]': 1, '[EOS]': 2, '[UNK]': 3,
            'hello': 4, 'world': 5, 'user': 6, 'assistant': 7,
        }, unk_token='[UNK]'))
        tokenizer_impl.pre_tokenizer = Whitespace()
        tokenizer = PreTrainedTokenizerFast(
            tokenizer_object=tokenizer_impl, unk_token='[UNK]',
            pad_token='[PAD]', bos_token='[BOS]', eos_token='[EOS]')
        tokenizer.chat_template = "{% for m in messages %}{{ m['content'] }} {% endfor %}"
        ids = tokenizer.apply_chat_template([{'role': 'user', 'content': 'hello world'}],
                                            tokenize=True, return_tensors='pt')
        assert ids.tolist() == [[4, 5]]
        result['checks']['fast_tokenizer_chat_template'] = 'PASS'

        config = LlamaConfig(vocab_size=8, hidden_size=32, intermediate_size=64,
                             num_hidden_layers=2, num_attention_heads=4,
                             num_key_value_heads=2, max_position_embeddings=64,
                             pad_token_id=0, bos_token_id=1, eos_token_id=2)
        model = AutoModelForCausalLM.from_config(config, attn_implementation='sdpa').eval()

        def run_model(active_model, device, label):
            local_ids = ids.to(device)
            mask = torch.ones_like(local_ids)
            with torch.inference_mode():
                logits = active_model(input_ids=local_ids, attention_mask=mask).logits
                generated = active_model.generate(
                    input_ids=local_ids, attention_mask=mask,
                    do_sample=False, max_new_tokens=3, pad_token_id=0)
            assert logits.shape == (1, 2, 8), logits.shape
            assert torch.isfinite(logits).all().item(), 'Non-finite logits'
            assert 2 < generated.shape[1] <= 5, generated.shape
            if str(device).startswith('cuda'):
                torch.cuda.synchronize()
            result['checks'][label] = 'PASS'

        run_model(model, 'cpu', 'cpu_sdpa_forward_and_generation')
        with tempfile.TemporaryDirectory(prefix='blindfold-deps-') as directory:
            model.save_pretrained(directory, safe_serialization=True)
            tokenizer.save_pretrained(directory)
            assert (Path(directory) / 'model.safetensors').exists()
            restored_tokenizer = AutoTokenizer.from_pretrained(directory, local_files_only=True)
            assert restored_tokenizer.encode('hello world') == [4, 5]
            device = 'cuda:0' if result['cuda_available'] else 'cpu'
            restored_model = AutoModelForCausalLM.from_pretrained(
                directory, local_files_only=True, low_cpu_mem_usage=True,
                device_map={'': device},
                dtype=torch.float16 if result['cuda_available'] else torch.float32,
                attn_implementation='sdpa').eval()
            assert str(next(restored_model.parameters()).device) == device
            result['checks']['safetensors_and_accelerate_device_map_loading'] = 'PASS'
            run_model(restored_model, device,
                      'cuda_fp16_sdpa_forward_and_generation' if result['cuda_available']
                      else 'cpu_reloaded_model_forward_and_generation')
        result['success'] = True
    except Exception as error:
        result['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        text = json.dumps(result, indent=2)
        print(text)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
