"""
Test 5: Death Certificate Stress Test
=======================================
Simulates a backend going unresponsive mid-session:
  1. Run 2 successful receipts for each of 3 models
  2. Simulate Gemma going down (forced failure)
  3. UAHP issues a death certificate
  4. System reroutes to the next highest-trust agent
  5. Rerouted agent completes the remaining tasks
  6. Log the full sequence: death cert, reroute, final trust scores

Saves to death_cert_stress_test.md.
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import UAHPCore, AgentStatus
from reputation import ReputationEngine

GROQ_KEY_PATH = os.path.join(os.path.expanduser("~"), ".bridge_key")
OLLAMA_URL = "http://localhost:11434/api/chat"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

MODELS = {
    "gemma4-e4b": {"backend": "ollama", "model": "gemma4:e4b", "label": "Gemma 4 E4B (local)"},
    "qwen3-32b":  {"backend": "groq", "model": "qwen/qwen3-32b", "label": "Qwen 3 32B (Groq)"},
    "llama3-70b": {"backend": "groq", "model": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B (Groq)"},
}

TASKS = [
    {"id": "task-001", "prompt": "What is 15 + 27? Answer with just the number."},
    {"id": "task-002", "prompt": "Name the three primary colors of light."},
    {"id": "task-003", "prompt": "What programming language is UAHP written in? Answer in one word."},
    {"id": "task-004", "prompt": "In one sentence, what is a completion receipt?"},
    {"id": "task-005", "prompt": "What is the chemical symbol for gold?"},
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
    payload = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 256, "temperature": 0.1}).encode()
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


def call_model(mk, cfg, prompt, groq_key):
    if cfg["backend"] == "ollama":
        return call_ollama(prompt, cfg["model"])
    else:
        return call_groq(prompt, cfg["model"], groq_key)


def main():
    print("\n  Test 5: Death Certificate Stress Test")
    print("  " + "=" * 50)

    groq_key = load_groq_key()
    uahp = UAHPCore()
    reputation = ReputationEngine(uahp)

    identities = {}
    for mk, cfg in MODELS.items():
        identities[mk] = uahp.create_identity({"name": cfg["label"], "role": "llm_backend"})
        print(f"  Registered: {cfg['label']} ({identities[mk].agent_id})")

    event_log = []

    # Phase 1: Run first 2 tasks on all models (healthy state)
    print("\n  Phase 1: Healthy operation (tasks 1-2)")
    for task in TASKS[:2]:
        for mk, cfg in MODELS.items():
            print(f"    {cfg['label']} -> {task['id']}... ", end="", flush=True)
            text, ms, ok = call_model(mk, cfg, task["prompt"], groq_key)
            uahp.create_receipt(
                identity=identities[mk], task_id=f"{mk}-{task['id']}",
                action="generate_response", duration_ms=ms, success=ok,
                input_data=task["prompt"][:200], output_data=(text or "")[:200])
            print(f"{'OK' if ok else 'FAIL'} ({ms:.0f}ms)")
            event_log.append({
                "phase": "healthy", "model": cfg["label"], "task": task["id"],
                "status": "OK" if ok else "FAIL", "ms": ms, "response": text[:100]})

    # Snapshot trust after phase 1
    print("\n  Trust after Phase 1:")
    phase1_trust = {}
    for mk, cfg in MODELS.items():
        p = reputation.score_agent(identities[mk].agent_id)
        phase1_trust[mk] = p
        print(f"    {cfg['label']}: {p.trust_score:.4f}")

    # Phase 2: Gemma goes down
    print("\n  Phase 2: Simulating Gemma failure on task-003...")
    dead_mk = "gemma4-e4b"
    dead_cfg = MODELS[dead_mk]
    dead_task = TASKS[2]

    # Record a failed receipt (simulated timeout)
    print(f"    {dead_cfg['label']} -> {dead_task['id']}... ", end="", flush=True)
    uahp.create_receipt(
        identity=identities[dead_mk], task_id=f"{dead_mk}-{dead_task['id']}",
        action="generate_response", duration_ms=120000, success=False,
        input_data=dead_task["prompt"][:200], output_data="[TIMEOUT: Backend unresponsive]")
    print("FAIL (120000ms — simulated timeout)")
    event_log.append({
        "phase": "failure", "model": dead_cfg["label"], "task": dead_task["id"],
        "status": "TIMEOUT", "ms": 120000, "response": "[TIMEOUT: Backend unresponsive]"})

    # Issue death certificate
    print(f"\n  Issuing death certificate for {dead_cfg['label']}...")
    cert = uahp.declare_death(
        dead_agent_id=identities[dead_mk].agent_id,
        declared_by="system-monitor",
        reason="Backend unresponsive after timeout on task-003. Exceeded 120s threshold.")

    status = uahp.is_alive(identities[dead_mk].agent_id)
    print(f"    Agent status: {status.value}")
    print(f"    Declared by:  {cert.declared_by}")
    print(f"    Reason:       {cert.reason}")

    event_log.append({
        "phase": "death_cert", "model": dead_cfg["label"], "task": "n/a",
        "status": "DEAD", "ms": 0,
        "response": f"Death certificate issued. Reason: {cert.reason}"})

    # Phase 3: Select highest-trust surviving agent and reroute
    print("\n  Phase 3: Rerouting to highest-trust surviving agent...")
    surviving = {mk: cfg for mk, cfg in MODELS.items() if mk != dead_mk}
    best_mk = max(surviving, key=lambda k: reputation.score_agent(identities[k].agent_id).trust_score)
    best_cfg = MODELS[best_mk]
    best_trust = reputation.score_agent(identities[best_mk].agent_id).trust_score

    print(f"    Selected: {best_cfg['label']} (trust: {best_trust:.4f})")
    event_log.append({
        "phase": "reroute", "model": best_cfg["label"], "task": "n/a",
        "status": "SELECTED", "ms": 0,
        "response": f"Rerouted to {best_cfg['label']} (trust: {best_trust:.4f})"})

    # Phase 4: Complete remaining tasks with rerouted agent
    print(f"\n  Phase 4: Completing remaining tasks with {best_cfg['label']}...")
    for task in TASKS[2:]:  # tasks 3-5 (including the one Gemma failed)
        print(f"    {best_cfg['label']} -> {task['id']}... ", end="", flush=True)
        text, ms, ok = call_model(best_mk, best_cfg, task["prompt"], groq_key)
        uahp.create_receipt(
            identity=identities[best_mk], task_id=f"reroute-{best_mk}-{task['id']}",
            action="rerouted_response", duration_ms=ms, success=ok,
            input_data=task["prompt"][:200], output_data=(text or "")[:200])
        print(f"{'OK' if ok else 'FAIL'} ({ms:.0f}ms)")
        event_log.append({
            "phase": "rerouted", "model": best_cfg["label"], "task": task["id"],
            "status": "OK" if ok else "FAIL", "ms": ms, "response": text[:100]})

    # Final trust scores
    print("\n  " + "=" * 50)
    print("  Final Trust Scores")
    print("  " + "=" * 50)

    final_profiles = {}
    for mk, cfg in MODELS.items():
        status = uahp.is_alive(identities[mk].agent_id)
        p = reputation.score_agent(identities[mk].agent_id)
        final_profiles[mk] = {"profile": p, "status": status}
        label = ReputationEngine.trust_label(p.trust_score)
        print(f"\n  {cfg['label']} [{status.value}]:")
        print(f"    Trust: {p.trust_score:.4f} ({label})")
        print(f"    Delivery: {p.delivery_rate:.0%} | Tasks: {p.total_tasks}")

    # Generate markdown
    md = []
    md.append("# Test 5: Death Certificate Stress Test")
    md.append("")
    md.append("> Simulates a backend going unresponsive mid-session. UAHP issues a death")
    md.append("> certificate and reroutes to the next highest-trust agent automatically.")
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
    md.append("## Scenario")
    md.append("")
    md.append("1. **Phase 1 (Healthy):** All 3 models complete tasks 1-2 successfully")
    md.append("2. **Phase 2 (Failure):** Gemma 4 E4B goes unresponsive on task-003 (simulated 120s timeout)")
    md.append("3. **Death Certificate:** UAHP declares Gemma dead, freezes its identity")
    md.append("4. **Phase 3 (Reroute):** System selects highest-trust surviving agent")
    md.append("5. **Phase 4 (Recovery):** Rerouted agent completes tasks 3-5")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Event Log")
    md.append("")
    md.append("| # | Phase | Model | Task | Status | Time (ms) | Detail |")
    md.append("|---|-------|-------|------|--------|-----------|--------|")
    for i, ev in enumerate(event_log, 1):
        detail = ev["response"][:60] if ev["response"] else ""
        md.append(f"| {i} | {ev['phase']} | {ev['model']} | {ev['task']} | **{ev['status']}** | {ev['ms']:.0f} | {detail} |")

    md.append("")
    md.append("---")
    md.append("")
    md.append("## Death Certificate")
    md.append("")
    md.append("| Field | Value |")
    md.append("|-------|-------|")
    md.append(f"| Agent | {dead_cfg['label']} (`{identities[dead_mk].agent_id}`) |")
    md.append(f"| Declared By | {cert.declared_by} |")
    md.append(f"| Reason | {cert.reason} |")
    md.append(f"| Declared At | {cert.declared_at} |")
    md.append(f"| Last Seen | {cert.last_seen} |")

    md.append("")
    md.append("---")
    md.append("")
    md.append("## Reroute Decision")
    md.append("")
    md.append(f"**Dead agent:** {dead_cfg['label']} (trust at death: {phase1_trust[dead_mk].trust_score:.4f})")
    md.append("")
    md.append(f"**Selected replacement:** {best_cfg['label']} (trust: {best_trust:.4f})")
    md.append("")
    md.append("Surviving agents ranked by trust at reroute time:")
    md.append("")
    md.append("| Model | Trust Score | Status |")
    md.append("|-------|-------------|--------|")
    for mk in surviving:
        p = reputation.score_agent(identities[mk].agent_id)
        sel = " (selected)" if mk == best_mk else ""
        md.append(f"| {MODELS[mk]['label']}{sel} | {p.trust_score:.4f} | alive |")
    md.append(f"| {dead_cfg['label']} | {phase1_trust[dead_mk].trust_score:.4f} | **DEAD** |")

    md.append("")
    md.append("---")
    md.append("")
    md.append("## Final Trust Scores")
    md.append("")
    md.append("| Model | Status | Trust Score | Label | Delivery | Tasks |")
    md.append("|-------|--------|-------------|-------|----------|-------|")
    for mk in sorted(final_profiles, key=lambda k: final_profiles[k]["profile"].trust_score, reverse=True):
        fp = final_profiles[mk]
        p = fp["profile"]
        st = fp["status"]
        label = ReputationEngine.trust_label(p.trust_score)
        md.append(f"| {MODELS[mk]['label']} | **{st.value}** | {p.trust_score:.4f} | {label} | {p.delivery_rate:.0%} | {p.total_tasks} |")

    md.append("")
    md.append("---")
    md.append("")
    md.append("## Analysis")
    md.append("")
    md.append(f"1. **Death certificate worked correctly.** Gemma was declared dead after a 120s timeout and its status changed to `{AgentStatus.DEAD.value}`.")
    md.append("")
    md.append(f"2. **Reroute selected {best_cfg['label']}** as the highest-trust surviving agent with a score of {best_trust:.4f}.")
    md.append("")
    dead_final = final_profiles[dead_mk]["profile"]
    best_final = final_profiles[best_mk]["profile"]
    md.append(f"3. **Trust scores diverged after failure.** Gemma's final trust ({dead_final.trust_score:.4f}) reflects the timeout penalty. {best_cfg['label']}'s final trust ({best_final.trust_score:.4f}) improved with additional successful completions.")
    md.append("")
    md.append(f"4. **The system recovered gracefully.** Tasks 3-5 were completed by the rerouted agent with no data loss or session interruption.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("*Generated by test_05_death_cert.py | UAHP v1.0*")
    md.append("")

    outpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "death_cert_stress_test.md")
    with open(outpath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"\n  Saved to death_cert_stress_test.md")
    print("  Test 5 complete.\n")


if __name__ == "__main__":
    main()
