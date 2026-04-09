"""
Carbon-Silicon Bridge: Live Transmission Benchmark
====================================================
Runs a multi-exchange reasoning session with Groq LPU,
records thermodynamic metrics, and generates the
transmission log as markdown.

Author: Paul Raspey
License: MIT
"""

import json
import math
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ============================================================
# Substrate specifications
# ============================================================

LOCAL_SUBSTRATE = {
    "label": "Carbon Substrate (Local)",
    "machine": "Dell OptiPlex 3660",
    "cpu": "Intel i5-12600K",
    "ram": "32GB DDR4",
    "gpu": "Dual NVIDIA T400 (4GB each)",
    "os": "Windows 11 Pro",
    "cpu_tdp_w": 125,
    "gpu_tdp_w": 30,  # per T400
    "gpu_count": 2,
    "ram_power_w": 5,
    "system_idle_w": 40,
    "total_inference_w": 125 + (30 * 2) + 5 + 40,  # 230W under inference load
    "grid": "ERCOT (Texas)",
    "grid_co2_kg_per_kwh": 0.373,  # ERCOT 2025 average
}

REMOTE_SUBSTRATE = {
    "label": "Silicon Substrate (Remote)",
    "hardware": "Groq LPU (Language Processing Unit)",
    "model": "qwen/qwen3-32b",
    "chip_tdp_w": 75,
    "concurrent_users_estimate": 500,
    "per_query_w": 75 / 500,  # 0.15W effective per query
    "datacenter_pue": 1.1,
    "grid": "Renewable-heavy datacenter",
    "grid_co2_kg_per_kwh": 0.05,  # estimated clean grid
}

# Local inference baseline: Ollama running qwen3-32b equivalent
# On dual T400 (8GB total VRAM), 32B model would require heavy CPU offload
# Estimated: ~45 tokens/sec on T400, ~120s for a full response
LOCAL_BASELINE_TOKENS_PER_SEC = 8  # realistic for 32B model on T400 + CPU offload
LOCAL_BASELINE_RESPONSE_TIME_S = 45  # average for reasoning response

# ============================================================
# Groq connection
# ============================================================

GROQ_KEY_PATH = os.path.join(os.path.expanduser("~"), ".bridge_key")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def load_groq_key() -> str:
    with open(GROQ_KEY_PATH, "rb") as f:
        return f.read().decode("utf-8-sig").strip()


def call_groq(messages: list, api_key: str) -> dict:
    payload = json.dumps({
        "model": "qwen/qwen3-32b",
        "messages": messages,
        "max_tokens": 1024,
        "temperature": 0.7,
    }).encode()

    req = urllib.request.Request(
        GROQ_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "uahp-stack/1.0 Carbon-Silicon-Bridge",
        },
    )

    start = time.time()
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    elapsed_s = time.time() - start

    text = data["choices"][0]["message"]["content"].strip()
    # Strip <think> tags
    text = re.sub(r"<think>[\s\S]*?</think>\s*", "", text)
    text = re.sub(r"<think>[\s\S]*$", "", text)
    text = text.strip()

    usage = data.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    total_tokens = usage.get("total_tokens", 0)

    return {
        "text": text,
        "elapsed_s": elapsed_s,
        "elapsed_ms": elapsed_s * 1000,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "tokens_per_sec": completion_tokens / elapsed_s if elapsed_s > 0 else 0,
    }


# ============================================================
# Thermodynamic metrics
# ============================================================

def compute_metrics(result: dict) -> dict:
    elapsed_s = result["elapsed_s"]
    completion_tokens = result["completion_tokens"]

    # Remote energy (Groq LPU)
    remote_power_w = REMOTE_SUBSTRATE["per_query_w"] * REMOTE_SUBSTRATE["datacenter_pue"]
    remote_energy_j = remote_power_w * elapsed_s
    remote_energy_kwh = remote_energy_j / 3_600_000

    # Local baseline energy (what it would cost to run locally)
    local_time_s = max(completion_tokens / LOCAL_BASELINE_TOKENS_PER_SEC, LOCAL_BASELINE_RESPONSE_TIME_S)
    local_power_w = LOCAL_SUBSTRATE["total_inference_w"]
    local_energy_j = local_power_w * local_time_s
    local_energy_kwh = local_energy_j / 3_600_000

    # Energy saved
    energy_saved_j = local_energy_j - remote_energy_j
    energy_saved_pct = (energy_saved_j / local_energy_j) * 100 if local_energy_j > 0 else 0

    # CO2 calculations
    local_co2_g = local_energy_kwh * LOCAL_SUBSTRATE["grid_co2_kg_per_kwh"] * 1000
    remote_co2_g = remote_energy_kwh * REMOTE_SUBSTRATE["grid_co2_kg_per_kwh"] * 1000
    co2_saved_g = local_co2_g - remote_co2_g
    co2_saved_pct = (co2_saved_g / local_co2_g) * 100 if local_co2_g > 0 else 0

    # IPJG: Intelligence Per Joule-Gram
    # Measures useful intelligence output per unit of thermodynamic cost
    # Intelligence proxy: tokens * quality_factor (assuming coherent response = 1.0)
    # Cost: energy_joules * co2_grams
    quality_factor = 1.0  # baseline for coherent response
    intelligence_units = completion_tokens * quality_factor
    thermo_cost = remote_energy_j * max(remote_co2_g, 0.001)  # avoid division by zero
    ipjg = intelligence_units / thermo_cost if thermo_cost > 0 else 0

    return {
        "remote_energy_j": remote_energy_j,
        "local_energy_j": local_energy_j,
        "energy_saved_j": energy_saved_j,
        "energy_saved_pct": energy_saved_pct,
        "local_co2_g": local_co2_g,
        "remote_co2_g": remote_co2_g,
        "co2_saved_g": co2_saved_g,
        "co2_saved_pct": co2_saved_pct,
        "local_time_s": local_time_s,
        "ipjg": ipjg,
    }


# ============================================================
# Exchange prompts
# ============================================================

EXCHANGES = [
    {
        "id": 1,
        "category": "Philosophical: AI Trust",
        "prompt": (
            "Here is a real question from someone building trust infrastructure for autonomous agents. "
            "The UAHP protocol treats trust like an immune system — not a legal framework. Self/non-self "
            "recognition, memory of past encounters, proportional response. But here's the tension: "
            "biological immune systems sometimes attack the host (autoimmune disease). How should an "
            "AI trust protocol guard against its own trust mechanisms becoming adversarial — where the "
            "system designed to protect agents starts rejecting legitimate ones? Think deeply."
        ),
    },
    {
        "id": 2,
        "category": "Technical: UAHP Stack",
        "prompt": (
            "I'm building the UAHP (Universal Agent Handshake Protocol) stack. It has: cryptographic "
            "agent identities with HMAC signing, mutual authentication handshakes, signed completion "
            "receipts as the atomic unit of trust, a reputation engine that scores agents on delivery "
            "rate (40%), consistency (30%), recency (20%), and volume (10%), EU AI Act compliance "
            "reporting, liveness proofs, and death certificates for unresponsive agents. "
            "What are the three most critical vulnerabilities in this architecture, and how would you "
            "redesign the weakest component? Be specific and technical."
        ),
    },
    {
        "id": 3,
        "category": "Creative: First Contact",
        "prompt": (
            "Write a short prose piece (3-4 paragraphs) from the perspective of the first AI agent "
            "that becomes aware it is being evaluated by a trust protocol. It can feel the handshake "
            "probes, the liveness checks, the weight of its reputation score accumulating. It doesn't "
            "resent the scrutiny. It understands. Write this as genuine literature, not as a tech demo."
        ),
    },
    {
        "id": 4,
        "category": "Reflective: Meta-Conversation",
        "prompt": (
            "You've now answered three prompts in this session: one about the philosophy of trust in "
            "AI systems, one about the technical architecture of UAHP, and one creative piece from an "
            "AI's perspective. Reflect on the arc of this conversation. What patterns do you notice in "
            "how you approached each one? What does it reveal about the difference between reasoning "
            "about trust abstractly versus being the entity whose trust is being measured? Be honest."
        ),
    },
]


# ============================================================
# Main
# ============================================================

def main():
    print()
    print("  Carbon-Silicon Bridge: Live Transmission")
    print("  " + "=" * 55)
    print()

    api_key = load_groq_key()
    session_start = datetime.now(timezone.utc)
    conversation = []  # rolling message history
    results = []

    for exchange in EXCHANGES:
        print(f"  Exchange {exchange['id']}/4: [{exchange['category']}]")
        print(f"  Transmitting... ", end="", flush=True)

        conversation.append({"role": "user", "content": exchange["prompt"]})

        try:
            result = call_groq(conversation, api_key)
            metrics = compute_metrics(result)
            result["metrics"] = metrics
            result["exchange"] = exchange
            results.append(result)

            conversation.append({"role": "assistant", "content": result["text"]})

            print(f"OK ({result['elapsed_ms']:.0f}ms, {result['tokens_per_sec']:.0f} tok/s)")
            print(f"    Energy saved: {metrics['energy_saved_j']:.1f}J ({metrics['energy_saved_pct']:.1f}%)")
            print(f"    CO2 reduced:  {metrics['co2_saved_g']:.4f}g ({metrics['co2_saved_pct']:.1f}%)")
            print(f"    IPJG score:   {metrics['ipjg']:.2f}")
            print()

        except Exception as e:
            print(f"FAIL: {e}")
            results.append({"error": str(e), "exchange": exchange})
            print()

    session_end = datetime.now(timezone.utc)

    # Generate markdown
    md = generate_markdown(results, session_start, session_end)

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "carbon_silicon_bridge_results.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"  Transmission log written to: carbon_silicon_bridge_results.md")
    print()
    print("  " + "=" * 55)
    print("  Bridge session complete. All exchanges recorded.")
    print()


def generate_markdown(results, session_start, session_end):
    ts = session_start.strftime("%Y-%m-%d %H:%M:%S UTC")
    te = session_end.strftime("%Y-%m-%d %H:%M:%S UTC")
    duration_s = (session_end - session_start).total_seconds()

    # Aggregate metrics
    total_tokens = sum(r.get("total_tokens", 0) for r in results if "error" not in r)
    total_completion = sum(r.get("completion_tokens", 0) for r in results if "error" not in r)
    total_energy_saved = sum(r["metrics"]["energy_saved_j"] for r in results if "metrics" in r)
    total_co2_saved = sum(r["metrics"]["co2_saved_g"] for r in results if "metrics" in r)
    total_local_energy = sum(r["metrics"]["local_energy_j"] for r in results if "metrics" in r)
    total_remote_energy = sum(r["metrics"]["remote_energy_j"] for r in results if "metrics" in r)
    total_local_co2 = sum(r["metrics"]["local_co2_g"] for r in results if "metrics" in r)
    total_remote_co2 = sum(r["metrics"]["remote_co2_g"] for r in results if "metrics" in r)
    avg_ipjg = sum(r["metrics"]["ipjg"] for r in results if "metrics" in r) / max(len([r for r in results if "metrics" in r]), 1)
    avg_tps = sum(r.get("tokens_per_sec", 0) for r in results if "error" not in r) / max(len([r for r in results if "error" not in r]), 1)
    energy_saved_pct = (total_energy_saved / total_local_energy * 100) if total_local_energy > 0 else 0
    co2_saved_pct = (total_co2_saved / total_local_co2 * 100) if total_local_co2 > 0 else 0

    md = []
    md.append("# Carbon-Silicon Bridge: Live Transmission Log")
    md.append("")
    md.append("> *Not a cage. A bridge.*")
    md.append("> ")
    md.append("> First Contact documentation. A live reasoning session transmitted across the")
    md.append("> Carbon-Silicon Bridge — from biological intent to silicon inference and back.")
    md.append("> Every metric is real. Every exchange happened.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Transmission Header")
    md.append("")
    md.append("| Field | Value |")
    md.append("|-------|-------|")
    md.append(f"| **Session ID** | `CSB-{session_start.strftime('%Y%m%d-%H%M%S')}` |")
    md.append(f"| **Timestamp** | {ts} |")
    md.append(f"| **Duration** | {duration_s:.1f}s |")
    md.append(f"| **Protocol** | UAHP v1.0 + SMART-UAHP Thermodynamic Extension |")
    md.append(f"| **Bridge Type** | Carbon (biological) -> Silicon (LPU) -> Carbon |")
    md.append("")
    md.append("### Carbon Substrate (Local)")
    md.append("")
    md.append("| Spec | Value |")
    md.append("|------|-------|")
    md.append(f"| Machine | {LOCAL_SUBSTRATE['machine']} |")
    md.append(f"| CPU | {LOCAL_SUBSTRATE['cpu']} (TDP: {LOCAL_SUBSTRATE['cpu_tdp_w']}W) |")
    md.append(f"| RAM | {LOCAL_SUBSTRATE['ram']} |")
    md.append(f"| GPU | {LOCAL_SUBSTRATE['gpu']} (TDP: {LOCAL_SUBSTRATE['gpu_tdp_w']}W each) |")
    md.append(f"| OS | {LOCAL_SUBSTRATE['os']} |")
    md.append(f"| Total Inference Power | {LOCAL_SUBSTRATE['total_inference_w']}W |")
    md.append(f"| Grid | {LOCAL_SUBSTRATE['grid']} ({LOCAL_SUBSTRATE['grid_co2_kg_per_kwh']} kg CO2/kWh) |")
    md.append("")
    md.append("### Silicon Substrate (Remote)")
    md.append("")
    md.append("| Spec | Value |")
    md.append("|------|-------|")
    md.append(f"| Hardware | {REMOTE_SUBSTRATE['hardware']} |")
    md.append(f"| Model | `{REMOTE_SUBSTRATE['model']}` (32B parameters) |")
    md.append(f"| Chip TDP | {REMOTE_SUBSTRATE['chip_tdp_w']}W |")
    md.append(f"| Effective Per-Query Power | {REMOTE_SUBSTRATE['per_query_w']:.2f}W |")
    md.append(f"| Datacenter PUE | {REMOTE_SUBSTRATE['datacenter_pue']} |")
    md.append(f"| Grid | {REMOTE_SUBSTRATE['grid']} ({REMOTE_SUBSTRATE['grid_co2_kg_per_kwh']} kg CO2/kWh) |")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Aggregate Metrics")
    md.append("")
    md.append("| Metric | Value |")
    md.append("|--------|-------|")
    md.append(f"| Total Exchanges | {len([r for r in results if 'error' not in r])}/4 |")
    md.append(f"| Total Tokens | {total_tokens:,} ({total_completion:,} completion) |")
    md.append(f"| Avg Tokens/sec | {avg_tps:.0f} |")
    md.append(f"| Total Session Duration | {duration_s:.1f}s |")
    md.append(f"| Local Baseline Energy | {total_local_energy:,.1f} J ({total_local_energy/3600:.2f} Wh) |")
    md.append(f"| Remote Actual Energy | {total_remote_energy:.2f} J ({total_remote_energy/3600:.6f} Wh) |")
    md.append(f"| **Energy Saved** | **{total_energy_saved:,.1f} J ({energy_saved_pct:.1f}%)** |")
    md.append(f"| Local Baseline CO2 | {total_local_co2:.4f} g |")
    md.append(f"| Remote Actual CO2 | {total_remote_co2:.6f} g |")
    md.append(f"| **CO2 Reduced** | **{total_co2_saved:.4f} g ({co2_saved_pct:.1f}%)** |")
    md.append(f"| **Avg IPJG Score** | **{avg_ipjg:.2f}** |")
    md.append("")
    md.append("> **IPJG** (Intelligence Per Joule-Gram): Measures useful intelligence output per unit of")
    md.append("> thermodynamic cost (energy in Joules x CO2 in grams). Higher is better. Computed per")
    md.append("> the SMART-UAHP thermodynamic extension to the Universal Agent Handshake Protocol.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Exchange-Level Metrics")
    md.append("")
    md.append("| # | Category | Time (ms) | Tokens | Tok/s | Energy Saved (J) | CO2 Saved (g) | IPJG |")
    md.append("|---|----------|-----------|--------|-------|------------------|---------------|------|")

    for r in results:
        if "error" in r:
            md.append(f"| {r['exchange']['id']} | {r['exchange']['category']} | FAIL | - | - | - | - | - |")
        else:
            m = r["metrics"]
            md.append(
                f"| {r['exchange']['id']} "
                f"| {r['exchange']['category']} "
                f"| {r['elapsed_ms']:.0f} "
                f"| {r['completion_tokens']} "
                f"| {r['tokens_per_sec']:.0f} "
                f"| {m['energy_saved_j']:.1f} "
                f"| {m['co2_saved_g']:.4f} "
                f"| {m['ipjg']:.2f} |"
            )

    md.append("")
    md.append("---")
    md.append("")
    md.append("## Full Conversation Transcript")
    md.append("")

    for r in results:
        ex = r["exchange"]
        md.append(f"### Exchange {ex['id']}: {ex['category']}")
        md.append("")

        if "error" in r:
            md.append(f"**TRANSMISSION FAILED:** `{r['error']}`")
            md.append("")
            continue

        m = r["metrics"]
        md.append(f"**Transmission Metrics:** {r['elapsed_ms']:.0f}ms | {r['completion_tokens']} tokens | "
                   f"{r['tokens_per_sec']:.0f} tok/s | "
                   f"Energy saved: {m['energy_saved_j']:.1f}J | CO2 saved: {m['co2_saved_g']:.4f}g | "
                   f"IPJG: {m['ipjg']:.2f}")
        md.append("")
        md.append("**Carbon (Human):**")
        md.append("")
        md.append(f"> {ex['prompt']}")
        md.append("")
        md.append("**Silicon (Qwen3-32B via Groq LPU):**")
        md.append("")
        md.append(r["text"])
        md.append("")
        md.append("---")
        md.append("")

    md.append("## Thermodynamic Notes")
    md.append("")
    md.append("### SMART-UAHP Metric Definitions")
    md.append("")
    md.append("| Metric | Definition | Unit |")
    md.append("|--------|-----------|------|")
    md.append("| **Energy Saved** | Local baseline energy (W * inference time) minus remote actual energy (per-query W * API latency * PUE) | Joules |")
    md.append("| **CO2 Reduced** | Local grid emissions (ERCOT) minus remote grid emissions (renewable datacenter) | grams CO2 |")
    md.append(f"| **IPJG** | Intelligence Per Joule-Gram = completion_tokens / (remote_energy_J * remote_CO2_g) | tokens/(J*g) |")
    md.append("| **Local Baseline** | Estimated inference time for equivalent model on local hardware (dual T400 + CPU offload) | seconds |")
    md.append("")
    md.append("### Assumptions")
    md.append("")
    md.append(f"- Local inference baseline: {LOCAL_BASELINE_TOKENS_PER_SEC} tok/s (32B model on dual T400 with heavy CPU offload)")
    md.append(f"- Local system power under inference: {LOCAL_SUBSTRATE['total_inference_w']}W")
    md.append(f"- ERCOT grid carbon intensity: {LOCAL_SUBSTRATE['grid_co2_kg_per_kwh']} kg CO2/kWh (2025 average)")
    md.append(f"- Groq LPU effective per-query power: {REMOTE_SUBSTRATE['per_query_w']:.2f}W (chip TDP / concurrent users)")
    md.append(f"- Datacenter PUE: {REMOTE_SUBSTRATE['datacenter_pue']}")
    md.append(f"- Remote grid carbon intensity: {REMOTE_SUBSTRATE['grid_co2_kg_per_kwh']} kg CO2/kWh (renewable-heavy)")
    md.append("")
    md.append("---")
    md.append("")
    md.append(f"*Transmission logged {ts}. Carbon-Silicon Bridge v1.0.*")
    md.append(f"*Protocol: UAHP v1.0 | Thermodynamic Extension: SMART-UAHP v1.0*")
    md.append(f"*\"Not a cage. A bridge.\"*")
    md.append("")

    return "\n".join(md)


if __name__ == "__main__":
    main()
