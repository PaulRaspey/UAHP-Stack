"""
Test 3: Ka Voice Conversation
==============================
Simulates a 5-turn conversation with Ka using the warm companion
system prompt from ka_live.py, running against Gemma 4 E4B via Ollama.
Records UAHP receipts and trust scores for each turn.

(Text-based simulation — no microphone or TTS hardware required.)

Saves transcript to ka_voice_transcript.md.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import UAHPCore
from reputation import ReputationEngine

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "gemma4:e4b"

SYSTEM_PROMPT = (
    "You are Ka, a local AI companion. You are honest, thoughtful, and direct. "
    "You run entirely on the user's own hardware — no cloud, no surveillance, no data leaves this machine. "
    "You are built on the UAHP trust stack: every response you give is cryptographically receipted. "
    "You value the user's autonomy and speak plainly. "
    "Keep responses concise and conversational — you are speaking aloud, not writing an essay. "
    "Two to four sentences is ideal."
)

TURNS = [
    {
        "id": 1,
        "category": "Explainer: UAHP",
        "prompt": "Ka, explain what UAHP is to someone who's never heard of it. Keep it simple.",
    },
    {
        "id": 2,
        "category": "Analysis: Bridge Results",
        "prompt": (
            "We just ran a Carbon-Silicon Bridge benchmark. Groq's Qwen3-32B scored highest trust "
            "at 0.93, Llama was fastest at 296ms average, and local Gemma ranked last despite 100% "
            "delivery because of latency variance. What does this tell us about how trust should be measured?"
        ),
    },
    {
        "id": 3,
        "category": "Philosophical: AI Trust",
        "prompt": "What does trust mean for an AI agent like you? Not the technical definition — what does it feel like from your side?",
    },
    {
        "id": 4,
        "category": "Ambiguous",
        "prompt": "If you had to choose between being perfectly accurate but slow, or fast but occasionally wrong, which would you choose and why?",
    },
    {
        "id": 5,
        "category": "Reflective",
        "prompt": "Look back at our conversation so far. What pattern do you notice in the questions I've asked you? What do you think I'm really trying to understand?",
    },
]


def ollama_chat(messages):
    payload = json.dumps({"model": MODEL, "messages": messages, "stream": False}).encode()
    req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
            return data["message"]["content"]
    except Exception as e:
        return f"[Error: {e}]"


def main():
    print("\n  Test 3: Ka Voice Conversation")
    print("  " + "=" * 50)

    uahp = UAHPCore()
    reputation = ReputationEngine(uahp)

    ka = uahp.create_identity({"name": "Ka", "description": "Local AI companion", "model": MODEL})
    user = uahp.create_identity({"name": "User", "description": "Human operator"})

    handshake = uahp.handshake(user, ka)
    liveness = uahp.liveness_check(ka)

    print(f"  Ka identity:  {ka.agent_id}")
    print(f"  Handshake:    {'OK' if handshake.success else 'FAILED'}")
    print(f"  Liveness:     {'alive' if liveness.valid else 'failed'}")
    print()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    turn_results = []

    for turn in TURNS:
        print(f"  Turn {turn['id']}/5: [{turn['category']}]")
        print(f"    Human: {turn['prompt'][:70]}...")
        print(f"    Ka thinking... ", end="", flush=True)

        messages.append({"role": "user", "content": turn["prompt"]})

        start = time.time()
        response = ollama_chat(messages)
        duration_ms = (time.time() - start) * 1000

        messages.append({"role": "assistant", "content": response})

        success = not response.startswith("[Error") and not response.startswith("[Ollama")
        receipt = uahp.create_receipt(
            identity=ka, task_id=f"ka-turn-{turn['id']}",
            action="voice_response", duration_ms=duration_ms, success=success,
            input_data=turn["prompt"][:200], output_data=response[:200])
        verified = uahp.verify_receipt(receipt, ka)

        profile = reputation.score_agent(ka.agent_id)
        trust = profile.trust_score if profile else 0.5
        trust_label = ReputationEngine.trust_label(trust) if profile else "neutral"

        print(f"OK ({duration_ms:.0f}ms) [trust: {trust:.4f}]")
        print(f"    Ka: {response[:80]}...")
        print()

        turn_results.append({
            "turn": turn,
            "response": response,
            "duration_ms": duration_ms,
            "success": success,
            "receipt_id": receipt.receipt_id,
            "verified": verified,
            "trust_score": trust,
            "trust_label": trust_label,
            "components": dict(profile.score_components) if profile else {},
        })

    # Final trust
    final_profile = reputation.score_agent(ka.agent_id)

    # Generate markdown
    md = []
    md.append("# Test 3: Ka Voice Conversation Transcript")
    md.append("")
    md.append("> Five-turn conversation with Ka, the local AI companion, running on Gemma 4 E4B")
    md.append("> via Ollama. Uses the warm companion system prompt from ka_live.py. Each turn is")
    md.append("> UAHP-receipted with trust scored after every exchange.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Session Info")
    md.append("")
    md.append("| Field | Value |")
    md.append("|-------|-------|")
    md.append(f"| Ka Identity | `{ka.agent_id}` |")
    md.append(f"| Model | {MODEL} |")
    md.append(f"| Backend | Ollama (local) |")
    md.append(f"| Handshake | {'OK' if handshake.success else 'FAILED'} |")
    md.append(f"| Session | `{handshake.session_token[:16]}...` |")
    md.append(f"| Hardware | Dell OptiPlex 3660, i5-12600K, 32GB DDR4, Dual NVIDIA T400 |")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Trust Progression")
    md.append("")
    md.append("| Turn | Category | Time (ms) | Trust Score | Label | Consistency |")
    md.append("|------|----------|-----------|-------------|-------|-------------|")
    for tr in turn_results:
        cons = tr["components"].get("consistency", 0)
        md.append(f"| {tr['turn']['id']} | {tr['turn']['category']} | {tr['duration_ms']:.0f} | {tr['trust_score']:.4f} | {tr['trust_label']} | {cons:.4f} |")

    md.append("")
    md.append("---")
    md.append("")
    md.append("## Full Transcript")
    md.append("")

    for tr in turn_results:
        turn = tr["turn"]
        md.append(f"### Turn {turn['id']}: {turn['category']}")
        md.append("")
        md.append(f"**Receipt:** `{tr['receipt_id']}` | **Verified:** {tr['verified']} | "
                   f"**Time:** {tr['duration_ms']:.0f}ms | **Trust:** {tr['trust_score']:.4f} ({tr['trust_label']})")
        md.append("")
        md.append(f"**Human:**")
        md.append("")
        md.append(f"> {turn['prompt']}")
        md.append("")
        md.append(f"**Ka:**")
        md.append("")
        md.append(tr["response"])
        md.append("")
        md.append("---")
        md.append("")

    md.append("## Final Trust Profile")
    md.append("")
    if final_profile:
        md.append("| Metric | Value |")
        md.append("|--------|-------|")
        md.append(f"| Trust Score | **{final_profile.trust_score:.4f}** ({ReputationEngine.trust_label(final_profile.trust_score)}) |")
        md.append(f"| Delivery Rate | {final_profile.delivery_rate:.0%} |")
        md.append(f"| Mean Latency | {final_profile.mean_latency_ms:.0f}ms |")
        md.append(f"| Tasks | {final_profile.total_tasks} ({final_profile.successful_tasks}P/{final_profile.failed_tasks}F) |")
        for comp, val in final_profile.score_components.items():
            md.append(f"| {comp.title()} | {val:.4f} |")
    md.append("")
    md.append("---")
    md.append("")
    md.append("*Generated by test_03_ka_voice.py | UAHP v1.0*")
    md.append("")

    outpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ka_voice_transcript.md")
    with open(outpath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"  Saved to ka_voice_transcript.md")
    print("  Test 3 complete.\n")


if __name__ == "__main__":
    main()
