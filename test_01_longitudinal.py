"""
Test 1: Longitudinal Trust Decay
=================================
Runs model_compare logic twice back-to-back with shared UAHP state.
Compares trust scores between run 1 and run 2 to observe how
accumulated receipts affect consistency, delivery, and overall trust.

Saves results to longitudinal_trust_results.md.
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import UAHPCore
from reputation import ReputationEngine

GROQ_KEY_PATH = os.path.join(os.path.expanduser("~"), ".bridge_key")
OLLAMA_URL = "http://localhost:11434/api/chat"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

MODELS = {
    "gemma4-e4b": {"backend": "ollama", "model": "gemma4:e4b", "label": "Gemma 4 E4B (local)"},
    "qwen3-32b":  {"backend": "groq", "model": "qwen/qwen3-32b", "label": "Qwen 3 32B (Groq)"},
    "llama3-70b": {"backend": "groq", "model": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B (Groq)"},
}

PROMPTS = [
    {"id": "factual",   "text": "In one sentence: what is the capital of Australia and why is it often confused with Sydney?"},
    {"id": "reasoning", "text": "A farmer has 17 sheep. All but 9 die. How many sheep does the farmer have left? Show your reasoning briefly."},
    {"id": "code",      "text": "Write a Python one-liner that returns the first 10 Fibonacci numbers as a list."},
    {"id": "creative",  "text": "In exactly two sentences, describe what trust means for an AI agent."},
    {"id": "math",      "text": "What is 17 multiplied by 13? Answer with just the number."},
]


def load_groq_key():
    with open(GROQ_KEY_PATH, "rb") as f:
        return f.read().decode("utf-8-sig").strip()


def call_ollama(prompt, model):
    payload = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}).encode()
    req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            ms = (time.time() - start) * 1000
            return data.get("message", {}).get("content", "").strip(), ms, True
    except Exception as e:
        return f"[ERROR: {e}]", (time.time() - start) * 1000, False


def call_groq(prompt, model, api_key):
    payload = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 1024, "temperature": 0.3}).encode()
    req = urllib.request.Request(GROQ_URL, data=payload, headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {api_key}", "User-Agent": "uahp-stack/1.0"})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            ms = (time.time() - start) * 1000
            text = data["choices"][0]["message"]["content"].strip()
            text = re.sub(r"<think>[\s\S]*?</think>\s*", "", text)
            text = re.sub(r"<think>[\s\S]*$", "", text)
            return text.strip(), ms, True
    except Exception as e:
        return f"[ERROR: {e}]", (time.time() - start) * 1000, False


def run_round(uahp, identities, groq_key, round_num):
    """Run all prompts across all models, return per-model profiles."""
    print(f"\n  --- Round {round_num} ---")
    reputation = ReputationEngine(uahp)
    responses = {k: [] for k in MODELS}

    for i, prompt in enumerate(PROMPTS, 1):
        print(f"  Prompt {i}/{len(PROMPTS)}: [{prompt['id']}]")
        for mk, cfg in MODELS.items():
            print(f"    {cfg['label']}... ", end="", flush=True)
            if cfg["backend"] == "ollama":
                text, ms, ok = call_ollama(prompt["text"], cfg["model"])
            else:
                text, ms, ok = call_groq(prompt["text"], cfg["model"], groq_key)

            uahp.create_receipt(
                identity=identities[mk], task_id=f"r{round_num}-{mk}-{prompt['id']}",
                action="generate_response", duration_ms=ms, success=ok,
                input_data=prompt["text"][:200], output_data=(text or "")[:200])

            print(f"{'OK' if ok else 'FAIL'} ({ms:.0f}ms)")
            responses[mk].append({"id": prompt["id"], "text": text, "ms": ms, "ok": ok})

    profiles = {}
    for mk, cfg in MODELS.items():
        p = reputation.score_agent(identities[mk].agent_id)
        profiles[mk] = {
            "label": cfg["label"],
            "trust_score": p.trust_score,
            "trust_label": ReputationEngine.trust_label(p.trust_score),
            "delivery_rate": p.delivery_rate,
            "mean_latency_ms": p.mean_latency_ms,
            "total_tasks": p.total_tasks,
            "successful_tasks": p.successful_tasks,
            "failed_tasks": p.failed_tasks,
            "components": dict(p.score_components),
        }
    return profiles, responses


def main():
    print("\n  Test 1: Longitudinal Trust Decay")
    print("  " + "=" * 50)

    groq_key = load_groq_key()
    uahp = UAHPCore()

    identities = {}
    for mk, cfg in MODELS.items():
        identities[mk] = uahp.create_identity({"name": cfg["label"], "role": "llm_backend"})

    r1_profiles, r1_responses = run_round(uahp, identities, groq_key, 1)
    r2_profiles, r2_responses = run_round(uahp, identities, groq_key, 2)

    # Print comparison
    print("\n  " + "=" * 50)
    print("  Longitudinal Comparison")
    print("  " + "=" * 50)
    for mk in MODELS:
        p1, p2 = r1_profiles[mk], r2_profiles[mk]
        delta = p2["trust_score"] - p1["trust_score"]
        print(f"\n  {p1['label']}:")
        print(f"    Round 1: {p1['trust_score']:.4f} | Round 2: {p2['trust_score']:.4f} | Delta: {delta:+.4f}")
        for comp in ["delivery", "consistency", "recency", "volume"]:
            d = p2["components"][comp] - p1["components"][comp]
            print(f"    {comp:<14} R1: {p1['components'][comp]:.4f}  R2: {p2['components'][comp]:.4f}  ({d:+.4f})")

    # Generate markdown
    md = []
    md.append("# Test 1: Longitudinal Trust Decay")
    md.append("")
    md.append("> Two consecutive runs of the UAHP model comparison with shared trust state.")
    md.append("> Receipts from Run 1 carry into Run 2. Measures how accumulated history affects trust scores.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Hardware")
    md.append("")
    md.append("| Spec | Value |")
    md.append("|------|-------|")
    md.append("| Machine | Dell OptiPlex 3660 |")
    md.append("| CPU | Intel i5-12600K |")
    md.append("| RAM | 32GB DDR4 |")
    md.append("| GPU | Dual NVIDIA T400 |")
    md.append("| OS | Windows 11 Pro |")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Round 1 Trust Scores (5 prompts)")
    md.append("")
    md.append("| Model | Trust Score | Label | Delivery | Consistency | Recency | Volume | Avg Latency | Tasks |")
    md.append("|-------|-------------|-------|----------|-------------|---------|--------|-------------|-------|")
    for mk in sorted(r1_profiles, key=lambda k: r1_profiles[k]["trust_score"], reverse=True):
        p = r1_profiles[mk]
        c = p["components"]
        md.append(f"| {p['label']} | **{p['trust_score']:.4f}** | {p['trust_label']} | {p['delivery_rate']:.0%} | {c['consistency']:.4f} | {c['recency']:.4f} | {c['volume']:.4f} | {p['mean_latency_ms']:.0f}ms | {p['total_tasks']} ({p['successful_tasks']}P/{p['failed_tasks']}F) |")

    md.append("")
    md.append("## Round 2 Trust Scores (10 cumulative prompts)")
    md.append("")
    md.append("| Model | Trust Score | Label | Delivery | Consistency | Recency | Volume | Avg Latency | Tasks |")
    md.append("|-------|-------------|-------|----------|-------------|---------|--------|-------------|-------|")
    for mk in sorted(r2_profiles, key=lambda k: r2_profiles[k]["trust_score"], reverse=True):
        p = r2_profiles[mk]
        c = p["components"]
        md.append(f"| {p['label']} | **{p['trust_score']:.4f}** | {p['trust_label']} | {p['delivery_rate']:.0%} | {c['consistency']:.4f} | {c['recency']:.4f} | {c['volume']:.4f} | {p['mean_latency_ms']:.0f}ms | {p['total_tasks']} ({p['successful_tasks']}P/{p['failed_tasks']}F) |")

    md.append("")
    md.append("## Delta (Round 2 - Round 1)")
    md.append("")
    md.append("| Model | Trust Delta | Delivery Delta | Consistency Delta | Volume Delta |")
    md.append("|-------|-------------|----------------|-------------------|--------------|")
    for mk in MODELS:
        p1, p2 = r1_profiles[mk], r2_profiles[mk]
        td = p2["trust_score"] - p1["trust_score"]
        dd = p2["delivery_rate"] - p1["delivery_rate"]
        cd = p2["components"]["consistency"] - p1["components"]["consistency"]
        vd = p2["components"]["volume"] - p1["components"]["volume"]
        md.append(f"| {p1['label']} | {td:+.4f} | {dd:+.0%} | {cd:+.4f} | {vd:+.4f} |")

    md.append("")
    md.append("## Analysis")
    md.append("")

    # Auto-generate analysis
    gemma_d = r2_profiles["gemma4-e4b"]["components"]["consistency"] - r1_profiles["gemma4-e4b"]["components"]["consistency"]
    qwen_r1 = r1_profiles["qwen3-32b"]["trust_score"]
    qwen_r2 = r2_profiles["qwen3-32b"]["trust_score"]
    r2_leader = max(r2_profiles, key=lambda k: r2_profiles[k]["trust_score"])

    md.append(f"1. **Gemma consistency {'improved' if gemma_d > 0 else 'declined'}** from "
              f"{r1_profiles['gemma4-e4b']['components']['consistency']:.4f} to "
              f"{r2_profiles['gemma4-e4b']['components']['consistency']:.4f} ({gemma_d:+.4f}). "
              f"{'More data points smoothed out the variance.' if gemma_d > 0 else 'Additional variance from run 2 responses compounded the penalty.'}")
    md.append("")
    md.append(f"2. **{'Qwen held its lead' if r2_leader == 'qwen3-32b' else r2_profiles[r2_leader]['label'] + ' took the lead in round 2'}** "
              f"with a trust score of {r2_profiles[r2_leader]['trust_score']:.4f}.")
    md.append("")
    md.append(f"3. **Volume scores improved across the board** — the sigmoid curve rewards accumulated receipts, "
              f"moving all models closer to the 1.0 ceiling with 10 data points vs 5.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("*Generated by test_01_longitudinal.py | UAHP v1.0*")
    md.append("")

    outpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "longitudinal_trust_results.md")
    with open(outpath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"\n  Saved to longitudinal_trust_results.md")
    print("  Test 1 complete.\n")


if __name__ == "__main__":
    main()
