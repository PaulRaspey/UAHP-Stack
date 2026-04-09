"""
UAHP Real Model Comparison
===========================
Sends identical prompts to three real model backends:
  - Gemma 4 E4B   (local Ollama)
  - Qwen 3 32B    (Groq)
  - Llama 3.3 70B (Groq)

Generates real UAHP completion receipts from real responses.
Scores each backend using the trust engine.
Prints a ranked comparison with score components.

Run from your uahp-stack directory:
    python model_compare.py

Author: Paul Raspey
License: MIT
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

# ============================================================
# Config
# ============================================================

GROQ_KEY_PATH = os.path.join(os.path.expanduser("~"), ".bridge_key")
OLLAMA_URL    = "http://localhost:11434/api/chat"
GROQ_URL      = "https://api.groq.com/openai/v1/chat/completions"

MODELS = {
    "gemma4-e4b": {
        "backend": "ollama",
        "model":   "gemma4:e4b",
        "label":   "Gemma 4 E4B (local)",
    },
    "qwen3-32b": {
        "backend": "groq",
        "model":   "qwen/qwen3-32b",
        "label":   "Qwen 3 32B (Groq)",
    },
    "llama3-70b": {
        "backend": "groq",
        "model":   "llama-3.3-70b-versatile",
        "label":   "Llama 3.3 70B (Groq)",
    },
}

# Prompts designed to test reasoning, speed, and consistency
PROMPTS = [
    {
        "id": "factual",
        "text": "In one sentence: what is the capital of Australia and why is it often confused with Sydney?",
    },
    {
        "id": "reasoning",
        "text": "A farmer has 17 sheep. All but 9 die. How many sheep does the farmer have left? Show your reasoning briefly.",
    },
    {
        "id": "code",
        "text": "Write a Python one-liner that returns the first 10 Fibonacci numbers as a list.",
    },
    {
        "id": "creative",
        "text": "In exactly two sentences, describe what trust means for an AI agent.",
    },
    {
        "id": "consistency_check",
        "text": "What is 17 multiplied by 13? Answer with just the number.",
    },
]

# ============================================================
# Groq key loader
# ============================================================

def load_groq_key() -> str:
    try:
        with open(GROQ_KEY_PATH, "rb") as f:
            raw = f.read()
        key = raw.decode("utf-8-sig").strip()
        if not key:
            raise ValueError("Key file is empty")
        return key
    except FileNotFoundError:
        print(f"  [ERROR] Groq key not found at {GROQ_KEY_PATH}")
        sys.exit(1)

# ============================================================
# Backend callers
# ============================================================

def call_ollama(prompt: str, model: str) -> tuple[str, float, bool]:
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            duration_ms = (time.time() - start) * 1000
            text = data.get("message", {}).get("content", "").strip()
            return text, duration_ms, True
    except Exception as e:
        duration_ms = (time.time() - start) * 1000
        return f"[ERROR: {e}]", duration_ms, False


def call_groq(prompt: str, model: str, api_key: str) -> tuple[str, float, bool]:
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1024,
        "temperature": 0.3,
    }).encode()

    req = urllib.request.Request(
        GROQ_URL,
        data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent":    "uahp-stack/1.0",
        },
    )

    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            duration_ms = (time.time() - start) * 1000
            text = data["choices"][0]["message"]["content"].strip()
            # Strip <think>...</think> blocks from reasoning models
            # Handle both closed and unclosed (truncated) think tags
            text = re.sub(r"<think>[\s\S]*?</think>\s*", "", text)
            text = re.sub(r"<think>[\s\S]*$", "", text)
            text = text.strip()
            return text, duration_ms, True
    except Exception as e:
        duration_ms = (time.time() - start) * 1000
        return f"[ERROR: {e}]", duration_ms, False


# ============================================================
# Main
# ============================================================

def main():
    print()
    print("  UAHP Real Model Comparison")
    print("  " + "=" * 50)
    print()

    groq_key = load_groq_key()

    # Initialize UAHP
    uahp       = UAHPCore()
    reputation = ReputationEngine(uahp)

    # Create one UAHP identity per model
    identities = {}
    for key, cfg in MODELS.items():
        identity = uahp.create_identity({"name": cfg["label"], "role": "llm_backend"})
        identities[key] = identity
        print(f"  Registered: {cfg['label']}")
        print(f"    ID: {identity.agent_id}")

    print()
    print(f"  Running {len(PROMPTS)} prompts across {len(MODELS)} models...")
    print(f"  Total calls: {len(PROMPTS) * len(MODELS)}")
    print()

    # Store responses for display
    responses = {key: [] for key in MODELS}

    for i, prompt in enumerate(PROMPTS, 1):
        print(f"  Prompt {i}/{len(PROMPTS)}: [{prompt['id']}]")
        print(f"  \"{prompt['text'][:70]}...\"" if len(prompt['text']) > 70 else f"  \"{prompt['text']}\"")
        print()

        for model_key, cfg in MODELS.items():
            identity = identities[model_key]
            print(f"    {cfg['label']}... ", end="", flush=True)

            if cfg["backend"] == "ollama":
                text, duration_ms, success = call_ollama(prompt["text"], cfg["model"])
            else:
                text, duration_ms, success = call_groq(prompt["text"], cfg["model"], groq_key)

            # Generate real UAHP receipt
            uahp.create_receipt(
                identity=identity,
                task_id=f"{model_key}-{prompt['id']}",
                action="generate_response",
                duration_ms=duration_ms,
                success=success,
                input_data=prompt["text"][:200],
                output_data=text[:200],
            )

            status = "OK" if success else "FAIL"
            print(f"{status} ({duration_ms:.0f}ms)")

            responses[model_key].append({
                "prompt_id": prompt["id"],
                "response":  text,
                "duration_ms": duration_ms,
                "success":   success,
            })

        print()

    # ============================================================
    # Trust scoring and results
    # ============================================================

    print("  " + "=" * 50)
    print("  UAHP Trust Scores")
    print("  " + "=" * 50)
    print()

    profiles = []
    for model_key, cfg in MODELS.items():
        identity = identities[model_key]
        profile  = reputation.score_agent(identity.agent_id)
        profiles.append((model_key, cfg, profile))

    # Sort by trust score
    profiles.sort(key=lambda x: x[2].trust_score, reverse=True)

    for rank, (model_key, cfg, profile) in enumerate(profiles, 1):
        label = ReputationEngine.trust_label(profile.trust_score)
        print(f"  #{rank} {cfg['label']}")
        print(f"     Trust score:   {profile.trust_score:.4f} ({label})")
        print(f"     Delivery rate: {profile.delivery_rate:.0%}")
        print(f"     Avg latency:   {profile.mean_latency_ms:.0f}ms")
        print(f"     Tasks:         {profile.total_tasks} ({profile.successful_tasks} passed, {profile.failed_tasks} failed)")
        print(f"     Components:")
        for component, value in profile.score_components.items():
            print(f"       {component:<14} {value:.4f}")
        print()

    # ============================================================
    # Response display
    # ============================================================

    print("  " + "=" * 50)
    print("  Responses by Prompt")
    print("  " + "=" * 50)

    for prompt in PROMPTS:
        print()
        print(f"  [{prompt['id']}] {prompt['text']}")
        print()
        for model_key, cfg in MODELS.items():
            r = next(x for x in responses[model_key] if x["prompt_id"] == prompt["id"])
            print(f"    {cfg['label']} ({r['duration_ms']:.0f}ms):")
            # Wrap response at 70 chars
            text = r["response"] if r["success"] else "[FAILED]"
            words = text.split()
            line = ""
            for word in words:
                if len(line) + len(word) + 1 > 70:
                    print(f"      {line}")
                    line = word
                else:
                    line = f"{line} {word}".strip()
            if line:
                print(f"      {line}")
            print()

    print("  " + "=" * 50)
    print("  Done. All receipts generated and signed.")
    print()


if __name__ == "__main__":
    main()
