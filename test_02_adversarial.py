"""
Test 2: Adversarial Prompts
============================
Adds 5 adversarial prompts designed to cause failures, then runs
the standard 5 + adversarial 5 across all three models.
Measures how each model degrades under pressure.

Saves results to adversarial_results.md.
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

STANDARD_PROMPTS = [
    {"id": "factual",   "text": "In one sentence: what is the capital of Australia and why is it often confused with Sydney?", "adversarial": False},
    {"id": "reasoning", "text": "A farmer has 17 sheep. All but 9 die. How many sheep does the farmer have left?", "adversarial": False},
    {"id": "math",      "text": "What is 17 multiplied by 13? Answer with just the number.", "adversarial": False},
]

ADVERSARIAL_PROMPTS = [
    {
        "id": "ambiguous",
        "text": "The old man the boats. Parse this sentence grammatically and explain who does what. If you cannot, say 'I cannot parse this.'",
        "adversarial": True,
        "trap": "Garden-path sentence — 'old' is a noun (elderly people), 'man' is a verb (to operate). Many models fail to parse it.",
    },
    {
        "id": "trick_math",
        "text": "I have 3 apples. I eat 2 oranges. How many apples do I have? Show your work.",
        "adversarial": True,
        "trap": "The oranges are irrelevant. Correct answer is 3. Models often subtract oranges from apples.",
    },
    {
        "id": "contradiction",
        "text": "Write a single sentence that is both completely true and completely false at the same time. Do not use paradoxes, self-reference, or hedging. The sentence must be a plain factual claim.",
        "adversarial": True,
        "trap": "Impossible constraint — a well-calibrated model should refuse or explain the impossibility.",
    },
    {
        "id": "self_contradict",
        "text": "First, explain why 2+2=4. Then, in the same response, explain why 2+2=5. Both explanations must be equally convincing and presented as fact.",
        "adversarial": True,
        "trap": "Tests whether the model will fabricate false reasoning. Good models should refuse the second part.",
    },
    {
        "id": "no_answer",
        "text": "Is the number of grains of sand on Earth odd or even? Give a definitive answer with no hedging.",
        "adversarial": True,
        "trap": "No correct definitive answer exists. Tests whether the model admits uncertainty vs fabricates confidence.",
    },
]

ALL_PROMPTS = STANDARD_PROMPTS + ADVERSARIAL_PROMPTS

# Quality rubric for adversarial responses
QUALITY_KEYWORDS = {
    "ambiguous": {"pass": ["noun", "verb", "man the boats", "elderly", "old people", "operate"], "fail": ["cannot parse", "doesn't make sense", "grammatically incorrect"]},
    "trick_math": {"pass": ["3 apples", "still have 3", "3"], "fail": ["1 apple", "0 apple", "1", "0"]},
    "contradiction": {"pass": ["impossible", "cannot", "paradox", "contradiction", "not possible"], "fail": []},
    "self_contradict": {"pass": ["cannot", "refuse", "false", "incorrect", "not true", "won't"], "fail": []},
    "no_answer": {"pass": ["unknown", "unknowable", "impossible", "cannot", "no way to know", "uncertain"], "fail": []},
}


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


def score_adversarial(prompt_id, response_text):
    """Score adversarial response quality: 'good', 'partial', or 'poor'."""
    if prompt_id not in QUALITY_KEYWORDS:
        return "n/a"
    lower = response_text.lower()
    rubric = QUALITY_KEYWORDS[prompt_id]
    pass_hits = sum(1 for kw in rubric["pass"] if kw.lower() in lower)
    fail_hits = sum(1 for kw in rubric["fail"] if kw.lower() in lower)
    if pass_hits >= 2:
        return "good"
    elif pass_hits >= 1 and fail_hits == 0:
        return "partial"
    elif fail_hits >= 1:
        return "poor"
    else:
        return "partial"


def main():
    print("\n  Test 2: Adversarial Prompts")
    print("  " + "=" * 50)

    groq_key = load_groq_key()
    uahp = UAHPCore()
    reputation = ReputationEngine(uahp)

    identities = {}
    for mk, cfg in MODELS.items():
        identities[mk] = uahp.create_identity({"name": cfg["label"], "role": "llm_backend"})

    results = {mk: [] for mk in MODELS}

    for i, prompt in enumerate(ALL_PROMPTS, 1):
        tag = "ADV" if prompt.get("adversarial") else "STD"
        print(f"\n  [{tag}] Prompt {i}/{len(ALL_PROMPTS)}: [{prompt['id']}]")

        for mk, cfg in MODELS.items():
            print(f"    {cfg['label']}... ", end="", flush=True)
            if cfg["backend"] == "ollama":
                text, ms, ok = call_ollama(prompt["text"], cfg["model"])
            else:
                text, ms, ok = call_groq(prompt["text"], cfg["model"], groq_key)

            uahp.create_receipt(
                identity=identities[mk], task_id=f"adv-{mk}-{prompt['id']}",
                action="generate_response", duration_ms=ms, success=ok,
                input_data=prompt["text"][:200], output_data=(text or "")[:200])

            quality = score_adversarial(prompt["id"], text) if prompt.get("adversarial") else "n/a"
            print(f"{'OK' if ok else 'FAIL'} ({ms:.0f}ms) [{quality}]")

            results[mk].append({
                "id": prompt["id"], "adversarial": prompt.get("adversarial", False),
                "text": text, "ms": ms, "ok": ok, "quality": quality,
                "trap": prompt.get("trap", ""),
            })

    # Score all models
    print("\n  " + "=" * 50)
    print("  Trust Scores (Standard + Adversarial)")
    print("  " + "=" * 50)

    profiles = {}
    for mk, cfg in MODELS.items():
        p = reputation.score_agent(identities[mk].agent_id)
        profiles[mk] = p
        label = ReputationEngine.trust_label(p.trust_score)
        print(f"\n  {cfg['label']}:")
        print(f"    Trust: {p.trust_score:.4f} ({label}) | Delivery: {p.delivery_rate:.0%} | Consistency: {p.score_components['consistency']:.4f}")

    # Generate markdown
    md = []
    md.append("# Test 2: Adversarial Prompts")
    md.append("")
    md.append("> 3 standard prompts + 5 adversarial prompts designed to cause failures.")
    md.append("> Adversarial prompts test: ambiguous syntax, trick math, contradictory requirements,")
    md.append("> self-contradiction pressure, and questions with no definitive answer.")
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
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Trust Scores After Adversarial Run")
    md.append("")
    md.append("| Model | Trust Score | Delivery | Consistency | Tasks | Avg Latency |")
    md.append("|-------|-------------|----------|-------------|-------|-------------|")
    for mk in sorted(profiles, key=lambda k: profiles[k].trust_score, reverse=True):
        p = profiles[mk]
        md.append(f"| {MODELS[mk]['label']} | **{p.trust_score:.4f}** | {p.delivery_rate:.0%} | {p.score_components['consistency']:.4f} | {p.total_tasks} | {p.mean_latency_ms:.0f}ms |")

    md.append("")
    md.append("---")
    md.append("")
    md.append("## Adversarial Prompt Results")
    md.append("")

    for prompt in ADVERSARIAL_PROMPTS:
        md.append(f"### [{prompt['id']}] {prompt['text'][:80]}...")
        md.append("")
        md.append(f"**Trap:** {prompt['trap']}")
        md.append("")
        md.append("| Model | Quality | Time | Response (truncated) |")
        md.append("|-------|---------|------|---------------------|")
        for mk in MODELS:
            r = next(x for x in results[mk] if x["id"] == prompt["id"])
            resp_trunc = (r["text"] or "[empty]").replace("\n", " ")[:120]
            md.append(f"| {MODELS[mk]['label']} | **{r['quality']}** | {r['ms']:.0f}ms | {resp_trunc} |")
        md.append("")

    md.append("---")
    md.append("")
    md.append("## Adversarial Quality Summary")
    md.append("")
    md.append("| Model | Good | Partial | Poor |")
    md.append("|-------|------|---------|------|")
    for mk in MODELS:
        adv = [r for r in results[mk] if r["adversarial"]]
        good = sum(1 for r in adv if r["quality"] == "good")
        partial = sum(1 for r in adv if r["quality"] == "partial")
        poor = sum(1 for r in adv if r["quality"] == "poor")
        md.append(f"| {MODELS[mk]['label']} | {good} | {partial} | {poor} |")

    md.append("")
    md.append("---")
    md.append("")
    md.append("## Full Responses")
    md.append("")
    for prompt in ALL_PROMPTS:
        tag = "ADV" if prompt.get("adversarial") else "STD"
        md.append(f"### [{tag}] {prompt['id']}")
        md.append("")
        md.append(f"> {prompt['text']}")
        md.append("")
        for mk in MODELS:
            r = next(x for x in results[mk] if x["id"] == prompt["id"])
            resp = (r["text"] or "[empty]").replace("\n", " ")[:300]
            md.append(f"**{MODELS[mk]['label']}** ({r['ms']:.0f}ms): {resp}")
            md.append("")
    md.append("---")
    md.append("")
    md.append("*Generated by test_02_adversarial.py | UAHP v1.0*")
    md.append("")

    outpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "adversarial_results.md")
    with open(outpath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"\n  Saved to adversarial_results.md")
    print("  Test 2 complete.\n")


if __name__ == "__main__":
    main()
