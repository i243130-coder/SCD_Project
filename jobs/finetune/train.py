"""QLoRA fine-tuning (PEFT + TRL SFTTrainer). Run on Colab/Kaggle GPU (human). Same code as train_colab.ipynb.
pip install "transformers==4.46.3" "trl==0.12.1" "peft==0.13.2" "bitsandbytes==0.44.1" datasets accelerate
python train.py --train data/train.jsonl --eval data/test.jsonl --out out/scorer-lora"""

from __future__ import annotations

import argparse

import yaml


def main() -> None:
    import torch
    from datasets import load_dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, EarlyStoppingCallback
    from trl import DataCollatorForCompletionOnlyLM, SFTConfig, SFTTrainer

    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default="data/train.jsonl")
    ap.add_argument("--eval", default="data/test.jsonl")
    ap.add_argument("--out", default="out/scorer-lora")
    ap.add_argument("--settings", default="settings.yaml")
    a = ap.parse_args()
    s = yaml.safe_load(open(a.settings))
    tok = AutoTokenizer.from_pretrained(s["base_model"])
    model = AutoModelForCausalLM.from_pretrained(
        s["base_model"],
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16
        ),
        device_map="auto",
    )
    ds = load_dataset("json", data_files={"train": a.train, "eval": a.eval})
    ds = ds.map(lambda ex: {"text": tok.apply_chat_template(ex["messages"], tokenize=False)})
    collator = DataCollatorForCompletionOnlyLM(
        response_template="<|im_start|>assistant", tokenizer=tok
    )  # assistant tokens only
    cfg = SFTConfig(
        output_dir=a.out,
        num_train_epochs=s["epochs"],
        per_device_train_batch_size=s["batch_size"],
        gradient_accumulation_steps=s["grad_accum"],
        learning_rate=s["lr"],
        max_seq_length=s["max_seq_len"],
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        seed=s["seed"],
        dataset_text_field="text",
        logging_steps=10,
        report_to=[],
    )
    lora = LoraConfig(
        r=s["lora"]["r"],
        lora_alpha=s["lora"]["alpha"],
        lora_dropout=s["lora"]["dropout"],
        target_modules=s["lora"]["target_modules"],
        task_type="CAUSAL_LM",
    )
    tr = SFTTrainer(
        model=model,
        args=cfg,
        train_dataset=ds["train"],
        eval_dataset=ds["eval"],
        peft_config=lora,
        data_collator=collator,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=s["early_stopping"]["patience"])],
    )
    tr.train()
    tr.save_model(a.out)


if __name__ == "__main__":
    main()
