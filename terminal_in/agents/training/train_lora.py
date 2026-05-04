"""
LoRA fine-tuning of TinyLlama-1.1B on the financial SFT dataset.

Requires: pip install transformers peft trl datasets accelerate bitsandbytes
Note: bitsandbytes on Windows needs the pre-built wheel:
      pip install bitsandbytes --index-url https://jllllll.github.io/bitsandbytes-windows-webui

Run:
    .venv/Scripts/python -m terminal_in.agents.training.train_lora

Output: ./data/training/financial_lora_adapter/
To use with Ollama: convert via llama.cpp then `ollama create financial-analyst -f Modelfile`
"""

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

DATASET_DIR  = Path('./data/training/financial_sft')
OUTPUT_DIR   = Path('./data/training/financial_lora_adapter')
BASE_MODEL   = 'TinyLlama/TinyLlama-1.1B-Chat-v1.0'

# LoRA config — conservative for CPU-trainable run on 16 GB RAM laptop
LORA_R       = 16
LORA_ALPHA   = 32
LORA_DROPOUT = 0.05
TARGET_MODS  = ['q_proj', 'k_proj', 'v_proj', 'o_proj']

# Training config
MAX_SEQ_LEN  = 512
BATCH_SIZE   = 2
GRAD_ACCUM   = 8      # effective batch = 16
EPOCHS       = 3
LR           = 2e-4
WARMUP_RATIO = 0.05
MAX_STEPS    = -1     # -1 = run full epochs; set to e.g. 200 for a quick smoke-test


def _check_deps() -> bool:
    missing = []
    for pkg in ['transformers', 'peft', 'trl', 'datasets', 'accelerate']:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f'Missing packages: {", ".join(missing)}')
        print(f'Install: pip install {" ".join(missing)}')
        return False
    return True


def train() -> None:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')

    if not _check_deps():
        return

    if not DATASET_DIR.exists():
        print(f'Dataset not found at {DATASET_DIR}')
        print('Run first: python -m terminal_in.agents.training.prepare_dataset')
        return

    from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments
    from peft import LoraConfig, get_peft_model, TaskType
    from trl import SFTTrainer
    from datasets import load_from_disk, Dataset
    import torch

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Load dataset ──────────────────────────────────────────────────────
    log.info(f'Loading dataset from {DATASET_DIR}')
    try:
        ds = load_from_disk(str(DATASET_DIR))
        log.info(f'Loaded HuggingFace Dataset: {len(ds)} samples')
    except Exception:
        # Fall back to JSONL
        import json
        jsonl = DATASET_DIR / 'dataset.jsonl'
        if not jsonl.exists():
            print(f'No dataset found. Run prepare_dataset.py first.')
            return
        rows = [json.loads(l) for l in jsonl.read_text('utf-8').splitlines() if l.strip()]
        ds = Dataset.from_list(rows)
        log.info(f'Loaded from JSONL: {len(ds)} samples')

    # ── Tokenizer ─────────────────────────────────────────────────────────
    log.info(f'Loading tokenizer: {BASE_MODEL}')
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # ── Model ─────────────────────────────────────────────────────────────
    log.info(f'Loading model: {BASE_MODEL} (this may take a few minutes)')
    device_map = 'auto' if torch.cuda.is_available() else 'cpu'
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float32 if device_map == 'cpu' else torch.float16,
        device_map=device_map,
        trust_remote_code=True,
    )
    model.config.use_cache = False

    # ── LoRA ──────────────────────────────────────────────────────────────
    lora_config = LoraConfig(
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        bias='none',
        task_type=TaskType.CAUSAL_LM,
        target_modules=TARGET_MODS,
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # ── Training args ─────────────────────────────────────────────────────
    training_args = TrainingArguments(
        output_dir=str(OUTPUT_DIR),
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        learning_rate=LR,
        warmup_ratio=WARMUP_RATIO,
        lr_scheduler_type='cosine',
        logging_steps=10,
        save_steps=100,
        save_total_limit=2,
        max_steps=MAX_STEPS,
        fp16=torch.cuda.is_available(),
        report_to='none',
        dataloader_num_workers=0,  # Windows: must be 0
    )

    # ── SFT Trainer ───────────────────────────────────────────────────────
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=ds,
        args=training_args,
        dataset_text_field='text',
        max_seq_length=MAX_SEQ_LEN,
        packing=False,
    )

    log.info('Starting training...')
    trainer.train()

    # ── Save adapter ──────────────────────────────────────────────────────
    adapter_path = OUTPUT_DIR / 'adapter'
    model.save_pretrained(str(adapter_path))
    tokenizer.save_pretrained(str(adapter_path))
    log.info(f'LoRA adapter saved → {adapter_path}')

    print(f'\nTraining complete!')
    print(f'Adapter saved to: {adapter_path}')
    print()
    print('To deploy with Ollama:')
    print('  1. Merge adapter: python -c "from peft import AutoPeftModelForCausalLM; '
          'model = AutoPeftModelForCausalLM.from_pretrained(\'...adapter\'); '
          'model.merge_and_unload().save_pretrained(\'merged\')"')
    print('  2. Convert to GGUF: ./llama.cpp/convert_hf_to_gguf.py merged/ --outfile financial.gguf')
    print('  3. Add to Ollama: ollama create financial-analyst -f Modelfile')
    print('     (Modelfile: FROM ./financial.gguf)')
    print('  4. Set OLLAMA_MODEL=financial-analyst in .env')


if __name__ == '__main__':
    train()
