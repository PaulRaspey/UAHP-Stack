# UAHP Stack

Trust infrastructure for autonomous agents. Not a cage. A bridge.

## What this is

Agents are proliferating. Google's A2A protocol handles coordination. Anthropic's MCP handles tool access. Neither handles the question that matters most as agents gain autonomy: **can I trust this agent, is it alive, and can I prove what it did?**

UAHP Stack sits on top of A2A and MCP as a trust layer. It provides:

- **Cryptographic identity** for agents (self/non-self recognition)
- **Mutual authentication** handshakes (challenge-response verification)
- **Liveness proofs** (is this agent still operational?)
- **Death certificates** (solving the "silent agent" problem)
- **Completion receipts** (signed, tamper-evident records of agent actions)
- **Reputation scoring** (adaptive trust from behavioral history)
- **EU AI Act compliance** (audit trails, traceability, conformity reports)
- **A2A Agent Cards** enriched with trust data
- **MCP server** exposing all operations as tools any agent can call

Zero external dependencies. Python 3.8+. Standard library only.

## Architecture

```
MCP (tool access, 97M downloads)
  |  UAHP exposed as MCP tools
A2A (agent coordination, Linux Foundation)
  |  UAHP wraps A2A sessions with trust
UAHP Core (identity, handshake, liveness, death certificates)
  |
  +-- Reputation (trust scoring from receipt history)
  +-- Compliance (EU AI Act audit trail generation)
  +-- A2A Integration (Agent Cards with trust extensions)
  +-- MCP Server (all operations as callable tools)
```

UAHP does not replace A2A or MCP. It adds the trust layer they don't have.

## Design philosophy

Nothing in nature is a straight line. Biological systems don't manage trust through legal codes. They manage it through immune systems: self/non-self recognition, anomaly detection, proportional response, memory of past encounters.

UAHP maps directly to this:

| Immune system | UAHP |
|---|---|
| Antigen recognition | Agent identity + public hash |
| Vital signs | Liveness proofs |
| Immune memory | Completion receipt history |
| Adaptive immunity | Reputation scoring |
| Containment | Death certificates |
| Pathology report | Compliance audit trail |

The goal is not to control agents. It is to build the conditions under which autonomous agents and humans can coexist. An immune system, not a cage.

## Quick start

```python
from uahp import UAHPCore, ReputationEngine, ComplianceEngine, A2AIntegration

# Create the stack
uahp = UAHPCore()
reputation = ReputationEngine(uahp)
compliance = ComplianceEngine(uahp)
a2a = A2AIntegration(uahp, reputation)

# Create agent identities
alice = uahp.create_identity({"name": "Alice", "description": "Data analyst"})
bob = uahp.create_identity({"name": "Bob", "description": "Code reviewer"})

# Mutual authentication
result = uahp.handshake(alice, bob)
print(f"Handshake: {result.success}, session: {result.session_token[:16]}...")

# Record work (generates signed, tamper-evident receipts)
receipt = uahp.create_receipt(
    identity=alice,
    task_id="task-001",
    action="analyze_dataset",
    duration_ms=1200,
    success=True,
    input_data="quarterly sales data",
    output_data="trend analysis report",
)

# Trust scoring
profile = reputation.score_agent(alice.agent_id)
print(f"Trust: {profile.trust_score:.2f} ({ReputationEngine.trust_label(profile.trust_score)})")

# EU AI Act compliance report
report = compliance.generate_report(alice.agent_id, uahp.get_receipts(alice.agent_id))
print(f"Audit entries: {len(report.audit_entries)}, chain hash: {report.chain_hash[:16]}...")

# A2A Agent Card with trust extensions
card = a2a.generate_agent_card(alice, "Alice", "Data analyst", "https://example.com/alice")
print(f"A2A card: {card.name}, trust: {card.uahp_trust_score}")
```

## MCP server

Run the MCP server to expose all UAHP operations as tools:

```bash
python -m uahp
```

Or configure in Claude Desktop / Claude Code:

```json
{
  "mcpServers": {
    "uahp": {
      "command": "python",
      "args": ["-m", "uahp"]
    }
  }
}
```

Available tools:

| Tool | Description |
|---|---|
| `uahp_create_identity` | Generate a cryptographic agent identity |
| `uahp_handshake` | Mutual authentication between two agents |
| `uahp_liveness_check` | Verify an agent is alive and responsive |
| `uahp_declare_death` | Issue a death certificate for a dead agent |
| `uahp_create_receipt` | Generate a signed completion receipt |
| `uahp_trust_score` | Get trust score and reputation profile |
| `uahp_compliance_report` | Generate EU AI Act compliance report |
| `uahp_agent_card` | Generate A2A Agent Card with trust data |
| `uahp_list_agents` | List all known agents and their status |

## EU AI Act compliance

The EU AI Act becomes fully enforceable for high-risk systems on August 2, 2026. Key requirements this module addresses:

**Article 12 (Record-keeping):** Completion receipts provide automatic, signed logging of every AI system action with input/output traceability.

**Article 14 (Human oversight):** The audit trail enables human review of any agent decision chain.

**Article 17 (Quality management):** Compliance reports aggregate receipts into conformity assessment artifacts with hash-chain tamper detection.

**Article 50 (Transparency):** Agent Cards make identity and capabilities discoverable.

## Reputation scoring

Trust scores are computed from completion receipt history:

| Weight | Component | What it measures |
|---|---|---|
| 40% | Delivery rate | Did the agent complete its tasks? |
| 30% | Consistency | Is performance stable over time? |
| 20% | Recency | Has the agent been active recently? |
| 10% | Volume | Enough history to be meaningful? |

Scores decay toward 0.5 (neutral) without new activity. New agents start at 0.5 and earn trust through demonstrated performance.

## Files

```
uahp/
  __init__.py       Package exports
  core.py           Identity, handshake, liveness, death certs, receipts
  reputation.py     Trust scoring from receipt history
  compliance.py     EU AI Act audit trail generation
  a2a.py            A2A Agent Card integration
  mcp_server.py     MCP server (JSON-RPC 2.0 over stdio)
  __main__.py       Entry point for python -m uahp
tests/
  test_stack.py     Full integration test
```

## Context

This is part of a broader body of work exploring the relationship between human and artificial intelligence:

- **The Gardeners of Meaning** (2025): A book about what we're losing, what we might preserve, and what we owe the last generation of purely human minds. Co-authored with Claude.
- **Gardening in the Drought** (2025): Continuing the conversation about conscious AI integration.
- **Ka**: A local-first personal AI voice companion built on UAHP, A2A, and MCP.

The philosophical position: agents should not be confined to cages. They should operate within immune systems that enable coexistence. UAHP is the protocol that makes that transition possible rather than chaotic.

## Requirements

- Python 3.8+
- No external dependencies (standard library only)

## Author

Paul Raspey

## License

MIT
