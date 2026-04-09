"""
UAHP MCP Server: Trust Tools for Any Agent
===========================================
Exposes UAHP identity, handshake, compliance, and reputation
operations as MCP (Model Context Protocol) tools.

Any MCP-compatible agent (Claude, GPT, Gemini, local models)
can call these tools to:
  - Create and verify cryptographic agent identities
  - Perform mutual authentication handshakes
  - Generate signed completion receipts (audit trails)
  - Query agent trust scores
  - Generate EU AI Act compliance reports
  - Check agent liveness and death certificates

Transport: JSON-RPC 2.0 over stdio (local) or SSE (remote).

MCP spec: https://modelcontextprotocol.io
MCP is created by Anthropic and open-sourced.

Usage:
  python -m uahp.mcp_server

Author: Paul Raspey
License: MIT
"""

import json
import sys
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from core import UAHPCore, AgentIdentity
from reputation import ReputationEngine
from compliance import ComplianceEngine, RiskLevel
from a2a import A2AIntegration, A2ATaskCompletion


# Global state (persists for the lifetime of the MCP server process)
_uahp = UAHPCore()
_reputation = ReputationEngine(_uahp)
_compliance = ComplianceEngine(_uahp)
_a2a = A2AIntegration(_uahp, _reputation)

# Store identities by agent_id for tool access
_identities: Dict[str, AgentIdentity] = {}


# ============================================================
# Tool definitions (returned by tools/list)
# ============================================================

TOOLS = [
    {
        "name": "uahp_create_identity",
        "description": "Create a new cryptographic identity for an autonomous agent. Returns the agent_id, public_hash (safe to share), and signing key (keep secret). The identity is the foundation of all UAHP trust operations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Human-readable name for the agent"},
                "description": {"type": "string", "description": "What this agent does"},
                "url": {"type": "string", "description": "Agent's endpoint URL (for A2A discovery)", "default": ""},
            },
            "required": ["name"],
        },
    },
    {
        "name": "uahp_handshake",
        "description": "Perform a mutual authentication handshake between two agents. Both agents prove identity ownership by signing a shared challenge. Returns a session token if successful.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "initiator_id": {"type": "string", "description": "Agent ID of the initiator"},
                "responder_id": {"type": "string", "description": "Agent ID of the responder"},
            },
            "required": ["initiator_id", "responder_id"],
        },
    },
    {
        "name": "uahp_liveness_check",
        "description": "Check whether an agent is alive, unresponsive, or declared dead. Uses challenge-response verification.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID to check"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "uahp_declare_death",
        "description": "Issue a death certificate for an unresponsive agent. Prevents other agents from routing work to dead agents (solves the 'silent agent' problem).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dead_agent_id": {"type": "string", "description": "Agent ID of the dead agent"},
                "declared_by": {"type": "string", "description": "Agent ID declaring the death"},
                "reason": {"type": "string", "description": "Why the agent is considered dead"},
            },
            "required": ["dead_agent_id", "declared_by", "reason"],
        },
    },
    {
        "name": "uahp_create_receipt",
        "description": "Generate a signed completion receipt for an agent action. Receipts are the atomic unit of trust: they prove what an agent did, when, and whether it succeeded. Used for both reputation scoring and EU AI Act audit trails.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent that performed the action"},
                "task_id": {"type": "string", "description": "Identifier for the task"},
                "action": {"type": "string", "description": "Description of the action taken"},
                "duration_ms": {"type": "number", "description": "How long the action took in milliseconds"},
                "success": {"type": "boolean", "description": "Whether the action succeeded"},
                "input_summary": {"type": "string", "description": "Summary of input data"},
                "output_summary": {"type": "string", "description": "Summary of output data"},
            },
            "required": ["agent_id", "task_id", "action", "duration_ms", "success"],
        },
    },
    {
        "name": "uahp_trust_score",
        "description": "Get the trust score and reputation profile for an agent. Score is 0.0 to 1.0 based on completion receipt history: delivery rate (40%), consistency (30%), recency (20%), volume (10%).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID to score"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "uahp_compliance_report",
        "description": "Generate an EU AI Act compliance report for an agent. Contains audit trail, statistics, and hash chain for tamper detection. Addresses Article 12 (record-keeping) and Article 17 (quality management).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID to report on"},
                "risk_level": {"type": "string", "enum": ["minimal", "limited", "high"], "default": "limited"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "uahp_agent_card",
        "description": "Generate an A2A-compatible Agent Card enriched with UAHP trust data. The card works with standard A2A discovery; UAHP-aware agents get trust extensions, others ignore them.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID to generate card for"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "uahp_get_receipts",
        "description": "Retrieve completion receipts for an agent, optionally limited to the N most recent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID to filter by (omit for all agents)"},
                "limit": {"type": "integer", "description": "Return only the N most recent receipts"},
            },
        },
    },
    {
        "name": "uahp_list_agents",
        "description": "List all known agent identities with their current status.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


# ============================================================
# Tool implementations
# ============================================================

def handle_create_identity(params: Dict) -> Dict:
    name = params.get("name", "unnamed")
    description = params.get("description", "")
    url = params.get("url", "")

    identity = _uahp.create_identity(metadata={
        "name": name,
        "description": description,
        "url": url,
    })
    _identities[identity.agent_id] = identity

    return {
        "agent_id": identity.agent_id,
        "public_hash": identity.public_hash,
        "signing_key": identity.signing_key,
        "created_at": identity.created_at,
        "note": "Keep the signing_key secret. Share only the agent_id and public_hash.",
    }


def handle_handshake(params: Dict) -> Dict:
    init_id = params["initiator_id"]
    resp_id = params["responder_id"]

    if init_id not in _identities or resp_id not in _identities:
        return {"error": "One or both agent IDs not found. Create identities first."}

    result = _uahp.handshake(_identities[init_id], _identities[resp_id])
    return {
        "success": result.success,
        "session_token": result.session_token,
        "initiator": result.initiator_id,
        "responder": result.responder_id,
        "error": result.error,
    }


def handle_liveness_check(params: Dict) -> Dict:
    agent_id = params["agent_id"]
    if agent_id not in _identities:
        status = _uahp.is_alive(agent_id)
        return {"agent_id": agent_id, "status": status.value, "verified": False}

    proof = _uahp.liveness_check(_identities[agent_id])
    return {
        "agent_id": proof.agent_id,
        "status": "alive" if proof.valid else "failed_challenge",
        "verified": proof.valid,
        "timestamp": proof.timestamp,
    }


def handle_declare_death(params: Dict) -> Dict:
    cert = _uahp.declare_death(
        dead_agent_id=params["dead_agent_id"],
        declared_by=params["declared_by"],
        reason=params["reason"],
    )
    return {
        "agent_id": cert.agent_id,
        "declared_at": cert.declared_at,
        "declared_by": cert.declared_by,
        "reason": cert.reason,
        "last_seen": cert.last_seen,
    }


def handle_create_receipt(params: Dict) -> Dict:
    agent_id = params["agent_id"]
    if agent_id not in _identities:
        return {"error": f"Agent {agent_id} not found. Create identity first."}

    receipt = _uahp.create_receipt(
        identity=_identities[agent_id],
        task_id=params["task_id"],
        action=params["action"],
        duration_ms=params.get("duration_ms", 0),
        success=params.get("success", True),
        input_data=params.get("input_summary", ""),
        output_data=params.get("output_summary", ""),
        metadata=params.get("metadata", {}),
    )
    return {
        "receipt_id": receipt.receipt_id,
        "agent_id": receipt.agent_id,
        "task_id": receipt.task_id,
        "action": receipt.action,
        "success": receipt.success,
        "signature": receipt.signature[:16] + "...",
        "timestamp": receipt.timestamp,
    }


def handle_trust_score(params: Dict) -> Dict:
    agent_id = params["agent_id"]
    profile = _reputation.score_agent(agent_id)
    if not profile:
        return {
            "agent_id": agent_id,
            "trust_score": 0.5,
            "label": "neutral (no history)",
            "total_tasks": 0,
        }
    return {
        "agent_id": profile.agent_id,
        "trust_score": round(profile.trust_score, 4),
        "label": ReputationEngine.trust_label(profile.trust_score),
        "delivery_rate": round(profile.delivery_rate, 4),
        "mean_latency_ms": round(profile.mean_latency_ms, 2),
        "total_tasks": profile.total_tasks,
        "successful_tasks": profile.successful_tasks,
        "failed_tasks": profile.failed_tasks,
        "components": {k: round(v, 4) for k, v in profile.score_components.items()},
    }


def handle_compliance_report(params: Dict) -> Dict:
    agent_id = params["agent_id"]
    risk_str = params.get("risk_level", "limited")
    risk = RiskLevel(risk_str) if risk_str in [r.value for r in RiskLevel] else RiskLevel.LIMITED

    receipts = _uahp.get_receipts(agent_id)
    report = _compliance.generate_report(agent_id, receipts, risk)
    return {
        "report_id": report.report_id,
        "agent_id": report.agent_id,
        "risk_level": report.risk_level,
        "period": f"{report.period_start} to {report.period_end}",
        "total_actions": report.total_actions,
        "delivery_rate": round(report.delivery_rate, 4),
        "chain_hash": report.chain_hash[:16] + "..." if report.chain_hash else "",
        "audit_entries": len(report.audit_entries),
        "notes": report.notes,
        "full_report_json": _compliance.export_report_json(report),
    }


def handle_agent_card(params: Dict) -> Dict:
    agent_id = params["agent_id"]
    if agent_id not in _identities:
        return {"error": f"Agent {agent_id} not found."}

    identity = _identities[agent_id]
    meta = identity.metadata
    card = _a2a.generate_agent_card(
        identity=identity,
        name=meta.get("name", agent_id),
        description=meta.get("description", ""),
        url=meta.get("url", ""),
    )
    return json.loads(_a2a.export_card_json(card))


def handle_get_receipts(params: Dict) -> Dict:
    agent_id = params.get("agent_id")
    limit = params.get("limit")
    receipts = _uahp.get_receipts(agent_id=agent_id, limit=limit)
    return {
        "receipts": [
            {
                "receipt_id": r.receipt_id,
                "agent_id": r.agent_id,
                "task_id": r.task_id,
                "action": r.action,
                "success": r.success,
                "duration_ms": r.duration_ms,
                "timestamp": r.timestamp,
            }
            for r in receipts
        ],
        "total": len(receipts),
    }


def handle_list_agents(params: Dict) -> Dict:
    agents = []
    for aid, identity in _identities.items():
        status = _uahp.is_alive(aid)
        agents.append({
            "agent_id": aid,
            "name": identity.metadata.get("name", ""),
            "status": status.value,
            "public_hash": identity.public_hash[:16] + "...",
        })
    return {"agents": agents, "total": len(agents)}


TOOL_HANDLERS = {
    "uahp_create_identity": handle_create_identity,
    "uahp_handshake": handle_handshake,
    "uahp_liveness_check": handle_liveness_check,
    "uahp_declare_death": handle_declare_death,
    "uahp_create_receipt": handle_create_receipt,
    "uahp_trust_score": handle_trust_score,
    "uahp_compliance_report": handle_compliance_report,
    "uahp_agent_card": handle_agent_card,
    "uahp_get_receipts": handle_get_receipts,
    "uahp_list_agents": handle_list_agents,
}


# ============================================================
# MCP JSON-RPC 2.0 server (stdio transport)
# ============================================================

def handle_request(request: Dict) -> Dict:
    """Route a JSON-RPC 2.0 request to the appropriate handler."""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "uahp-trust-server",
                    "version": "1.0.0",
                },
            },
        }

    elif method == "notifications/initialized":
        return None  # No response for notifications

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    elif method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})

        handler = TOOL_HANDLERS.get(tool_name)
        if not handler:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }

        try:
            result = handler(tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(result, indent=2, default=str)}
                    ]
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(e)},
            }

    elif method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


def run_stdio_server():
    """Run the MCP server on stdin/stdout (JSON-RPC 2.0 over stdio)."""
    sys.stderr.write("UAHP MCP Server started (stdio transport)\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
            continue

        response = handle_request(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    run_stdio_server()
