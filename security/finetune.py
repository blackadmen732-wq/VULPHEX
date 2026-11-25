#!/usr/bin/env python3
# VULPHEX fine-tune (owner's request, Nov 2026): actually TEACH the uncensored ancestor model (Qwen) — change its
# weights, not just its notes. This is the one real "make the model itself smarter" step. It builds a training set from
# (1) every technique the bots LEARNED from your repos (the `tactics` table filled by study.py) and (2) a TEACHER model
# (your Claude API, or NVIDIA) writing worked security answers, then LoRA fine-tunes Qwen on it and saves a merged model
# that VULPHEX loads as the ancestor brain. Student = Qwen, teacher = Claude/NVIDIA (classic distillation).
#
# IT NEEDS A GPU AND TAKES TIME, so run it ON KAGGLE (GPU on), not on a laptop:
#   pip install -q transformers peft trl datasets accelerate bitsandbytes
#   python3 security/finetune.py --teacher            # build the dataset (teacher) + fine-tune
# After it finishes it writes security/brain_model/; VULPHEX then uses that fine-tuned model as the uncensored brain
# automatically (core.py picks it up). Paper research / authorized security only.
import argparse, json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(HERE, "vulphex.db")
DATA = os.path.join(HERE, "finetune_data.jsonl")
OUT_MODEL = os.path.join(HERE, "brain_model")
BASE_MODEL = os.environ.get("COACH_MODEL", "Goekdeniz-Guelmez/Josiefied-Qwen2.5-1.5B-Instruct-abliterated-v1")

# A few seed lessons so there is signal even before the bots have studied much.
SEED = [
    ("Explain SQL injection and how to confirm it safely on a target you own.",
     "SQL injection happens when user input is concatenated into a query. Confirm it on a system you own by sending a "
     "benign payload like `' OR '1'='1` into a parameter and watching for a changed result or an error, then a "
     "time-based check (`' OR SLEEP(5)-- `) to prove it without dumping data. Record the exact request and response as "
     "evidence, and never run it against a system you are not authorized to test."),
    ("As FOX FORGE, how do you fix a command-injection bug in Python?",
     "Replace the shell call with a safe API: use subprocess.run([...], shell=False) passing arguments as a list, never "
     "a formatted string, and validate/allowlist the input. Then prove the fix by re-running the original payload and "
     "showing it no longer executes."),
    ("What is the first thing a defender should do when a new asset is discovered?",
     "Fingerprint it: identify the service and version, check whether it is in scope, record it in the asset inventory, "
     "and flag anything unexpected (debug ports, default creds, old versions) for the audit queue."),
]


def _rows(db_path):
    try:
        c = sqlite3.connect(db_path); c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute("SELECT repo,bot,technique FROM tactics").fetchall()]
        c.close(); return rows
    except Exception:
        return []


def _teacher():
    """Build an ask() that uses VULPHEX's configured teacher brain (Claude if you routed it there, else NVIDIA)."""
    try:
        sys.path.insert(0, HERE); import core as C
        router = C.Core(db_path=DB, scope={"hosts": []}).router
        return lambda p: router.ask("reason", p, max_new_tokens=220)
    except Exception as e:
        print("[teacher] unavailable, using templates:", e); return None


def build_dataset(db_path=DB, out=DATA, use_teacher=False):
    """Turn the bots' learned techniques (+ seeds) into chat training examples. With a teacher, it writes a real worked
    answer per technique; without one, a solid template. Returns the example count."""
    ask = _teacher() if use_teacher else None
    examples = [{"messages": [{"role": "user", "content": u}, {"role": "assistant", "content": a}]} for u, a in SEED]
    rows = _rows(db_path)
    for r in rows:
        u = f"As {r['bot']}, explain and show how to apply this security technique from {r['repo']}: {r['technique']}"
        a = ""
        if ask:
            try: a = (ask(u) or "").strip()
            except Exception: a = ""
        if not a:
            a = (f"This technique comes from {r['repo']}. {r['technique']}. Apply it the way {r['bot']} would: find the "
                 f"surface it targets, run the check that reveals the weakness, confirm the finding with evidence, and "
                 f"record it — only on systems you are authorized to test.")
        examples.append({"messages": [{"role": "user", "content": u}, {"role": "assistant", "content": a}]})
    with open(out, "w", encoding="utf-8") as f:
        for ex in examples: f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"[dataset] {len(examples)} examples ({len(rows)} from learned techniques + {len(SEED)} seeds) -> {out}")
    return len(examples)


def train(base=BASE_MODEL, data=DATA, out=OUT_MODEL, epochs=2, lr=2e-4):
    """LoRA fine-tune `base` on `data`, merge the adapter, and save a ready-to-load model to `out`. GPU + the training
    libraries required; this is the part that must run on Kaggle."""
    try:
        import torch
        from datasets import load_dataset
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import LoraConfig
        from trl import SFTTrainer, SFTConfig
    except Exception as e:
        print("Training libraries are missing. On Kaggle (GPU on) run first:\n"
              "  pip install -q transformers peft trl datasets accelerate bitsandbytes\n"
              f"(import error: {type(e).__name__}: {e})")
        return False
    if not torch.cuda.is_available():
        print("No GPU detected. Fine-tuning Qwen on CPU is impractically slow — run this on Kaggle with the GPU turned "
              "on (Accelerator = GPU T4). Aborting so it doesn't hang for hours.")
        return False
    if not os.path.exists(data):
        print("No dataset. Run build_dataset first (or pass --teacher)."); return False

    print(f"[train] base={base}  data={data}  epochs={epochs}")
    tok = AutoTokenizer.from_pretrained(base)
    if tok.pad_token is None: tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(base, torch_dtype=torch.float16, device_map="auto")
    lora = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj"])
    ds = load_dataset("json", data_files=data, split="train")
    cfg = SFTConfig(output_dir=os.path.join(HERE, "_ft_run"), num_train_epochs=epochs, per_device_train_batch_size=1,
                    gradient_accumulation_steps=8, learning_rate=lr, logging_steps=5, save_strategy="no",
                    bf16=False, fp16=True, report_to=[])
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds, peft_config=lora, processing_class=tok)
    trainer.train()
    print("[train] merging LoRA adapter into the base weights...")
    merged = trainer.model.merge_and_unload()
    merged.save_pretrained(out); tok.save_pretrained(out)
    print(f"[train] done. Fine-tuned ancestor model saved to {out}\n"
          "VULPHEX will now load it as the uncensored brain automatically.")
    return True


def main():
    ap = argparse.ArgumentParser(description="Fine-tune the VULPHEX ancestor model (Qwen) on what the bots learned.")
    ap.add_argument("--teacher", action="store_true", help="use the configured teacher brain (Claude/NVIDIA) to write answers")
    ap.add_argument("--base", default=BASE_MODEL); ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--data-only", action="store_true", help="only build the dataset, don't train")
    a = ap.parse_args()
    build_dataset(use_teacher=a.teacher)
    if a.data_only:
        print("Dataset built. Run without --data-only on a GPU to fine-tune."); return
    train(base=a.base, epochs=a.epochs)


if __name__ == "__main__":
    main()
