"""Merge the LoRA adapter into the base, convert to GGUF and quantise to Q4_K_M (llama.cpp tools).
    python merge_and_quantize.py --adapter out/scorer-lora --llama-cpp ~/llama.cpp --out out/scorer-q4_k_m.gguf
Upload the .gguf as a GitHub Release asset (NEVER commit weights) and set MODEL_URL."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import yaml


def main() -> None:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--llama-cpp", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    base = yaml.safe_load(open(Path(__file__).with_name("settings.yaml")))["base_model"]
    merged = Path(a.adapter).with_name("merged")
    m = AutoModelForCausalLM.from_pretrained(base, torch_dtype=torch.float16)
    PeftModel.from_pretrained(m, a.adapter).merge_and_unload().save_pretrained(merged)
    AutoTokenizer.from_pretrained(base).save_pretrained(merged)
    f16 = merged.with_suffix(".f16.gguf")
    lc = Path(a.llama_cpp)
    subprocess.run(
        ["python", str(lc / "convert_hf_to_gguf.py"), str(merged), "--outfile", str(f16), "--outtype", "f16"],
        check=True,
    )
    subprocess.run([str(lc / "build/bin/llama-quantize"), str(f16), a.out, "Q4_K_M"], check=True)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
