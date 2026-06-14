"""
LoRA fine-tuning of the financial SLM on the SFT dataset.

Base model (LORA_BASE_MODEL): default **Qwen/Qwen2.5-1.5B-Instruct** — the local
upgrade from the original TinyLlama-1.1B, which the eval set proved could not
follow instructions (9.5% vs qwen2.5:3b 83.3%). 1.5B fp32 fits the 16 GB laptop
(the hardware ceiling: 3B+ needs bf16 emulation on Zen3 / swaps, so it trains on
a cloud GPU instead — see colab/). The dataset is plain Alpaca text
(`### Instruction/Response`), so the base swap needs no template change, and
Qwen2.5 shares the q/k/v/o_proj target modules.

Requires: pip install transformers peft trl datasets accelerate

Run:
    .venv/Scripts/python -m terminal_in.agents.training.train_lora
    LORA_BASE_MODEL=... LORA_MAX_STEPS=200 ...   # override base / smoke test

Output: ./data/training/financial_lora_adapter/
To use with Ollama: convert via llama.cpp then `ollama create financial-analyst -f Modelfile`
"""

import logging
import os
import sys
from pathlib import Path

# TRL 1.x reads package data files without an explicit encoding; on Windows the
# default cp1252 codec crashes ('charmap' codec can't decode byte 0x81).
# Re-exec in UTF-8 mode before any trl/transformers import if not already set.
if sys.flags.utf8_mode == 0 and os.environ.get('PYTHONUTF8') != '1':
    os.environ['PYTHONUTF8'] = '1'
    os.execv(sys.executable, [sys.executable, '-X', 'utf8', *sys.argv])

# Engage every logical core before torch initializes its thread pools
try:
    from terminal_in import hw
    hw.apply(for_training=True)
except Exception:
    pass

log = logging.getLogger(__name__)

# Paths are env-overridable so the recursive TrainingOrchestrator can run
# isolated per-run directories (data/training/runs/<run_id>/).
DATASET_DIR  = Path(os.environ.get('LORA_DATASET_DIR', './data/training/financial_sft'))
OUTPUT_DIR   = Path(os.environ.get('LORA_OUTPUT_DIR',  './data/training/financial_lora_adapter'))
BASE_MODEL   = os.environ.get('LORA_BASE_MODEL', 'Qwen/Qwen2.5-1.5B-Instruct')

# LoRA config — conservative for CPU-trainable run on 16 GB RAM laptop
LORA_R       = 16
LORA_ALPHA   = 32
LORA_DROPOUT = 0.05
TARGET_MODS  = ['q_proj', 'k_proj', 'v_proj', 'o_proj']

# Training config
MAX_SEQ_LEN  = int(os.environ.get('LORA_MAX_SEQ_LEN', '512'))
BATCH_SIZE   = int(os.environ.get('LORA_BATCH_SIZE', '2'))
GRAD_ACCUM   = int(os.environ.get('LORA_GRAD_ACCUM', '8'))   # effective batch = B*GA
EPOCHS       = 3
LR           = 2e-4
WARMUP_RATIO = 0.05
#  -1 = run full epochs; override for a quick smoke-test:
#  LORA_MAX_STEPS=200 python -m terminal_in.agents.training.train_lora
MAX_STEPS    = int(os.environ.get('LORA_MAX_STEPS', '-1'))


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

    from transformers import AutoTokenizer, AutoModelForCausalLM
    from peft import LoraConfig, get_peft_model, TaskType
    from trl import SFTTrainer, SFTConfig
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
    # CPU dtype: fp32 for small bases; bf16 fits 3B-class models in 16GB RAM
    # (LORA_DTYPE=bf16). Zen3 lacks native bf16 ops — slower per step, but it
    # is the only way a 3B base trains on this machine at all.
    cpu_dtype = {'bf16': torch.bfloat16, 'fp16': torch.float16}.get(
        os.environ.get('LORA_DTYPE', 'fp32'), torch.float32)
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        dtype=cpu_dtype if device_map == 'cpu' else torch.float16,
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
    # With gradient checkpointing on a PEFT model, gradients must be allowed to
    # flow into the (frozen) base inputs so they reach the LoRA adapters.
    model.enable_input_require_grads()
    model.print_trainable_parameters()

    # ── Training args (TRL 1.x uses SFTConfig) ───────────────────────────
    training_args = SFTConfig(
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
        bf16=False,                 # TRL 1.x defaults bf16 on; CPU-only setup rejects it
        # 1.5B base needs activation checkpointing to stay inside 16 GB on CPU.
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={'use_reentrant': False},
        use_cpu=not torch.cuda.is_available(),
        report_to='none',
        dataloader_num_workers=0,  # Windows: must be 0
        dataset_text_field='text',
        max_length=MAX_SEQ_LEN,    # TRL 1.x: max_length, not max_seq_length
        packing=False,
    )

    # ── SFT Trainer ───────────────────────────────────────────────────────
    # TRL 1.x: the tokenizer is passed as processing_class (tokenizer= was removed)
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=ds,
        args=training_args,
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
