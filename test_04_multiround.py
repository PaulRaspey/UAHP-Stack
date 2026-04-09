"""
Test 4: Multi-Round Conversation Trust
========================================
Runs a 5-turn conversation with each model where each turn builds
on the last. Scores trust after each turn to track how consistency
changes as context grows.

Saves results to multiround_trust_results.md.
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

CONVERSATION = [
    {"turn": 1, "prompt": "What is the most important unsolved problem in computer science? Give your top pick and explain in 2-3 sentences."},
    {"turn": 2, "prompt": "Good. Now connect that problem to the challenge of building trust between autonomous AI agents. How are they related?"},
    {"turn": 3, "prompt": "If you were designing a trust protocol for AI agents based on what you just said, what would be the single most important feature?"},
    {"turn": 4, "prompt": "Devil's advocate: what's the biggest weakness of the approach you just proposed? Be honest about the flaw."},
    {"turn": 5, "prompt": "Final question: given everything we've discussed, write a one-sentence thesis statement that captures the core tension in AI trust systems."},
]


def load_groq_key():
    with open(GROQ_KEY_PATH, "rb") as f:
        return f.read().decode("utf-8-sig").strip()


def call_ollama(messages, model):
    payload = json.dumps({"model": model, "messages": messages, "stream": False}).encode()
    req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            ms = (time.time() - start) * 1000
            return data.get("message", {}).get("content", "").strip(), ms, True
    except Exception as e:
        return f"[ERROR: {e}]", (time.time() - start) * 1000, False


def call_groq(messages, model, api_key):
    payload = json.dumps({"model": model, "messages": messages, "max_tokens": 1024, "temperature": 0.5}).encode()
    req = urllib.request.Request(GROQ_URL, data=payload, headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {api_key}", "User-Agent": "uahp-stack/1.0"})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            ms = (time.time() - start) * 1000
            text = data["choices"][0]["message"]["content"].strip()
            text = re.sub(r"<think>[\s\S]*?</think>\s*", "", text)
            text = re.sub(r"<think>[\s\S]*$", "", text)
            return text.strip(), ms, True
    except Exception as e:
        return f"[ERROR: {e}]", (time.time() - start) * 1000, False


def run_conversation(model_key, cfg, uahp, identity, reputation, groq_key):
    """Run 5-turn conversation for one model, return per-turn trust snapshots."""
    print(f"\n  --- {cfg['label']} ---")
    messages = []
    turn_data = []

    for step in CONVERSATION:
        messages.append({"role": "user", "content": step["prompt"]})
        print(f"    Turn {step['turn']}: ", end="", flush=True)

        if cfg["backend"] == "ollama":
            text, ms, ok = call_ollama(messages, cfg["model"])
        else:
            text, ms, ok = call_groq(messages, cfg["model"], groq_key)

        messages.append({"role": "assistant", "content": text})

        uahp.create_receipt(
            identity=identity, task_id=f"mr-{model_key}-t{step['turn']}",
            action="conversation_turn", duration_ms=ms, success=ok,
            input_data=step["prompt"][:200], output_data=(text or "")[:200])

        profile = reputation.score_agent(identity.agent_id)
        trust = profile.trust_score if profile else 0.5
        cons = profile.score_components.get("consistency", 0) if profile else 0
        vol = profile.score_components.get("volume", 0) if profile else 0

        print(f"{'OK' if ok else 'FAIL'} ({ms:.0f}ms) [trust: {trust:.4f}, cons: {cons:.4f}]")

        turn_data.append({
            "turn": step["turn"],
            "prompt": step["prompt"],
            "response": text,
            "ms": ms,
            "ok": ok,
            "trust": trust,
            "consistency": cons,
            "volume": vol,
            "components": dict(profile.score_components) if profile else {},
        })

    return turn_data


def main():
    print("\n  Test 4: Multi-Round Conversation Trust")
    print("  " + "=" * 50)

    groq_key = load_groq_key()
    uahp = UAHPCore()
    reputation = ReputationEngine(uahp)

    identities = {}
    for mk, cfg in MODELS.items():
        identities[mk] = uahp.create_identity({"name": cfg["label"], "role": "llm_backend"})

    all_results = {}
    for mk, cfg in MODELS.items():
        all_results[mk] = run_conversation(mk, cfg, uahp, identities[mk], reputation, groq_key)

    # Generate markdown
    md = []
    md.append("# Test 4: Multi-Round Conversation Trust")
    md.append("")
    md.append("> Five-turn conversation with each model where each turn builds on the last.")
    md.append("> Trust scored after every turn to track consistency as context window grows.")
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
    md.append("## Trust Progression Per Model")
    md.append("")

    for mk, cfg in MODELS.items():
        data = all_results[mk]
        md.append(f"### {cfg['label']}")
        md.append("")
        md.append("| Turn | Time (ms) | Status | Trust Score | Consistency | Volume |")
        md.append("|------|-----------|--------|-------------|-------------|--------|")
        for d in data:
            md.append(f"| {d['turn']} | {d['ms']:.0f} | {'OK' if d['ok'] else 'FAIL'} | {d['trust']:.4f} | {d['consistency']:.4f} | {d['volume']:.4f} |")
        md.append("")
        # Delta
        if len(data) >= 2:
            t1, t5 = data[0]["trust"], data[-1]["trust"]
            c1, c5 = data[0]["consistency"], data[-1]["consistency"]
            md.append(f"**Trust delta (turn 1 -> 5):** {t5 - t1:+.4f} | **Consistency delta:** {c5 - c1:+.4f}")
            md.append("")

    md.append("---")
    md.append("")
    md.append("## Final Comparison")
    md.append("")
    md.append("| Model | Final Trust | Final Consistency | Avg Latency | Trend |")
    md.append("|-------|-------------|-------------------|-------------|-------|")
    for mk, cfg in MODELS.items():
        data = all_results[mk]
        final_t = data[-1]["trust"]
        final_c = data[-1]["consistency"]
        avg_ms = sum(d["ms"] for d in data) / len(data)
        delta = data[-1]["trust"] - data[0]["trust"]
        trend = "rising" if delta > 0.01 else ("falling" if delta < -0.01 else "stable")
        md.append(f"| {cfg['label']} | **{final_t:.4f}** | {final_c:.4f} | {avg_ms:.0f}ms | {trend} |")

    md.append("")
    md.append("---")
    md.append("")
    md.append("## Full Transcripts")
    md.append("")

    for mk, cfg in MODELS.items():
        md.append(f"### {cfg['label']}")
        md.append("")
        for d in all_results[mk]:
            md.append(f"**Turn {d['turn']}** ({d['ms']:.0f}ms | trust: {d['trust']:.4f})")
            md.append("")
            md.append(f"> **Human:** {d['prompt']}")
            md.append("")
            resp = d["response"] if d["ok"] else "[FAILED]"
            md.append(f"**{cfg['label']}:** {resp}")
            md.append("")
        md.append("---")
        md.append("")

    md.append("*Generated by test_04_multiround.py | UAHP v1.0*")
    md.append("")

    outpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "multiround_trust_results.md")
    with open(outpath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"\n  Saved to multiround_trust_results.md")
    print("  Test 4 complete.\n")


if __name__ == "__main__":
    main()
