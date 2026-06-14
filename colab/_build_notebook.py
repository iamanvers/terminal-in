"""Generates colab/train_3b_colab.ipynb (valid JSON via json.dump).
Run: python colab/_build_notebook.py
Edit the cell sources here, never the .ipynb by hand."""
import json
from pathlib import Path

def md(*lines):  return {"cell_type": "markdown", "metadata": {}, "source": [l + "\n" for l in lines]}
def code(*lines): return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": [l + "\n" for l in lines]}

cells = [
    md("# TERMINAL//IN — train the 3B financial SLM on a Colab GPU",
       "",
       "The 3B base won't train on the 16 GB CPU laptop (bf16 is emulated on Zen3 → ~90-day ETA; "
       "fp32 weights are 12.4 GB → swaps). A free Colab **T4 has 16 GB of real VRAM + native fp16**, "
       "so QLoRA trains it in ~1–2 h.",
       "",
       "**Before you run:** Runtime → Change runtime type → **T4 GPU**.",
       "",
       "Flow: upload the locally-built `dataset.jsonl` (it carries your own trades + hindsight "
       "decisions) → train → download the LoRA adapter → deploy + eval-gate locally."),

    md("### 1 · Confirm the GPU"),
    code("!nvidia-smi -L"),

    md("### 2 · Install"),
    code("!pip -q install -U transformers peft trl datasets accelerate bitsandbytes"),

    md("### 3 · Upload `dataset.jsonl`",
       "Build it locally first: `.venv/Scripts/python.exe scripts/export_dataset.py` → "
       "`data/training/colab/dataset.jsonl`, then upload that file here."),
    code("from google.colab import files",
         "up = files.upload()            # pick dataset.jsonl",
         "DATA = next(iter(up))",
         "print('uploaded:', DATA)"),

    md("### 4 · Train (QLoRA, recipe-matched to the local pipeline)",
       "Same LoRA config as `train_lora.py` (r16/α32, q/k/v/o, lr 2e-4, cosine) so the result is "
       "apples-to-apples with the eval gate. Effective batch 16, 3 epochs."),
    code("import json, torch",
         "from datasets import Dataset",
         "from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig",
         "from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training, TaskType",
         "from trl import SFTTrainer, SFTConfig",
         "",
         "BASE = 'Qwen/Qwen2.5-3B-Instruct'",
         "rows = [json.loads(l) for l in open(DATA, encoding='utf-8') if l.strip()]",
         "ds = Dataset.from_list(rows); print(len(ds), 'samples')",
         "",
         "bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',",
         "                         bnb_4bit_compute_dtype=torch.float16,",
         "                         bnb_4bit_use_double_quant=True)",
         "tok = AutoTokenizer.from_pretrained(BASE, trust_remote_code=True)",
         "if tok.pad_token is None: tok.pad_token = tok.eos_token",
         "model = AutoModelForCausalLM.from_pretrained(BASE, quantization_config=bnb,",
         "                                             device_map='auto', trust_remote_code=True)",
         "model.config.use_cache = False",
         "model = prepare_model_for_kbit_training(model)",
         "",
         "lora = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, bias='none',",
         "                  task_type=TaskType.CAUSAL_LM,",
         "                  target_modules=['q_proj','k_proj','v_proj','o_proj'])",
         "model = get_peft_model(model, lora); model.print_trainable_parameters()",
         "",
         "args = SFTConfig(output_dir='out', num_train_epochs=3,",
         "                 per_device_train_batch_size=8, gradient_accumulation_steps=2,",
         "                 learning_rate=2e-4, warmup_ratio=0.05, lr_scheduler_type='cosine',",
         "                 logging_steps=10, save_steps=300, save_total_limit=1, fp16=True,",
         "                 report_to='none', dataset_text_field='text', max_length=512, packing=False)",
         "trainer = SFTTrainer(model=model, processing_class=tok, train_dataset=ds, args=args)",
         "trainer.train()",
         "model.save_pretrained('adapter'); tok.save_pretrained('adapter')",
         "print('adapter saved → ./adapter')"),

    md("### 5 · Download the adapter (primary bring-back)",
       "Small (~50–130 MB). Deploy it locally with the existing pipeline (merges with the local "
       "Qwen2.5-3B base → GGUF Q4_K_M → `ollama create`)."),
    code("import shutil; shutil.make_archive('financial_3b_adapter', 'zip', 'adapter')",
         "from google.colab import files; files.download('financial_3b_adapter.zip')"),

    md("### 6 · (Optional) Produce a ready GGUF on Colab",
       "If you'd rather skip the local merge: this merges the adapter into an fp16 base and converts "
       "to a **q8_0 GGUF** (no quantize-binary build needed). 3B q8_0 ≈ 3.3 GB. Use it directly in "
       "Ollama, or re-quantize to Q4_K_M locally with the vendored llama.cpp."),
    code("del model, trainer; torch.cuda.empty_cache()",
         "from transformers import AutoModelForCausalLM, AutoTokenizer",
         "from peft import PeftModel",
         "base = AutoModelForCausalLM.from_pretrained(BASE, torch_dtype=torch.float16,",
         "                                            device_map='cpu', trust_remote_code=True)",
         "merged = PeftModel.from_pretrained(base, 'adapter').merge_and_unload()",
         "merged.save_pretrained('merged'); AutoTokenizer.from_pretrained('adapter').save_pretrained('merged')",
         "!git clone --depth 1 https://github.com/ggerganov/llama.cpp",
         "!pip -q install -r llama.cpp/requirements/requirements-convert_hf_to_gguf.txt",
         "!python llama.cpp/convert_hf_to_gguf.py merged --outfile financial-3b-q8_0.gguf --outtype q8_0",
         "from google.colab import files; files.download('financial-3b-q8_0.gguf')"),

    md("### 7 · Bring it home (local)",
       "**Adapter path (recommended):** unzip into "
       "`data/training/runs/<run_id>/adapter/adapter/`, set `LORA_BASE_MODEL=Qwen/Qwen2.5-3B-Instruct`, "
       "then deploy with the existing tool:",
       "```",
       "POST /api/training/deploy {\"run_id\": \"<run_id>\"}   # merge→GGUF→quantize→ollama create financial-analyst-vN",
       "```",
       "**GGUF path:** drop the .gguf next to a Modelfile (`FROM ./financial-3b-q8_0.gguf`) and "
       "`ollama create financial-analyst-v3 -f Modelfile`.",
       "",
       "**Then EVAL-GATE before promoting** (the 42-item set rejected the 1.1B v2 at 9.5% vs qwen 83.3%):",
       "```",
       ".venv/Scripts/python.exe -m terminal_in.agents.training.evalset --model financial-analyst-v3",
       "```",
       "Only switch the planner/analyst (settings dropdown) if it **beats the incumbent** with no "
       ">5pt category regression."),
]

nb = {
    "cells": cells,
    "metadata": {
        "accelerator": "GPU",
        "colab": {"provenance": [], "gpuType": "T4"},
        "kernelspec": {"display_name": "Python 3", "name": "python3"},
        "language_info": {"name": "python"},
    },
    "nbformat": 4,
    "nbformat_minor": 0,
}

out = Path(__file__).parent / 'train_3b_colab.ipynb'
out.write_text(json.dumps(nb, indent=1), encoding='utf-8')
print('wrote', out)
