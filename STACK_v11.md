# UAHP Stack: New Layers v1.1

**UAM + CDF + UAHP-A: Memory, Defense, and Actuation for the UAHP agentic stack.**

89/89 integration tests passing.

## The Complete Stack

| Layer | Protocol | Version | What it provides |
|:--|:--|:--|:--|
| 1 | UAHP | v0.6.0 | Identity, trust, quantum-resistant transport |
| 2 | SMART-UAHP | v0.1.0 | Energy-optimal substrate routing |
| 3 | CSP | v0.2 | Portable semantic state (5 vectors) |
| **3.5** | **UAM** | **v1.1** | **Durable memory pointers + context primer** |
| 4 | UAHP-Registry | v0.1.0 | Agent discovery |
| 5 | POLIS | v0.1.0 | Civil standing and legal identity |
| **6** | **UAHP-A** | **v1.1** | **Trust-verified physical actuation** |
| **sidecar** | **CDF** | **v1.1** | **Runtime cognitive defense firewall** |

## What's In Each Module

### UAM (Universal Agent Memory)
580+ lines. SQLite-backed reasoning persistence with biological decay model.
- `store_from_csp()` / `export_for_csp()`: round-trip CSP compatibility
- Memory types: episodic, semantic, procedural, strategic, relational
- Priority-tiered decay: critical (never) through ephemeral (24hr)
- MemoryPointer (~200 bytes) embeds in CSP packets
- **v1.1**: `build_context_primer()` generates injectable context for new sessions

### CDF (Cognitive Defense Firewall)
700+ lines. Five pluggable detectors + swarm drift monitor.
- IntegrityDetector: hash verification, timestamp freshness, field checks
- PromptInjectionDetector: 16 injection patterns + encoded payload heuristics
- GoalHijackDetector: intent baseline comparison via word overlap
- ReplayDetector: rolling hash window catches duplicate packets
- DriftDetector: per-agent intent history divergence
- **v1.1**: SwarmDriftMonitor with per-dimension weighted DriftVector, swarm coherence, trust_penalty() export

### UAHP-A (Actuation Handshake)
620+ lines. Full actuation lifecycle with G-code translation.
- Intent -> Plan -> Authorize -> Execute -> Receipt -> Rollback
- SafetyEnvelope (position, velocity, force, temperature limits)
- GCodeTranslator with safe-Z-first motion planning
- SimulationDriver for dev/test, ActuatorDriver interface for real hardware
- Trust gate (0.4 min) + POLIS standing gate (50.0 min)
- **v1.1**: ActuatorDescriptor with safety-class graduated trust requirements (PASSIVE=0.3 through CRITICAL=0.95)

## Running Tests

```bash
python3 test_integration.py
```

## File Structure

```
v1.1/
  UAM/
    uam.py          # Universal Agent Memory
    README.md
  CDF/
    cdf.py          # Cognitive Defense Firewall
    README.md
  UAHP-A/
    uahp_a.py       # Actuation Handshake Protocol
    README.md
  test_integration.py   # 89 tests, full pipeline
  README.md             # This file
```

## Author

Paul Raspey | MIT License
