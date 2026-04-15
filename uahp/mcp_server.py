"""
UAHP MCP Server — JSON-RPC 2.0 over stdio.

Exposes all UAHP operations as MCP tools so Claude Desktop,
Claude Code, or any MCP client can call them directly.

Author: Paul Raspey
License: MIT
"""

import sys
import json
import asyncio
from dataclasses import asdict
from typing import Dict, Any, Optional

from .core import UAHPCore, AgentIdentity
from .reputation import ReputationEngine
from .compliance import ComplianceEngine
from .a2a import A2AIntegration


class UAHPMCPServer:
    def __init__(self):
        self.core = UAHPCore()
        self.reputation = ReputationEngine(self.core)
        self.compliance = ComplianceEngine(self.core)
        self.a2a = A2AIntegration(self.core, self.reputation)
        self.agents: Dict[str, AgentIdentity] = {}

    async def handle_request(self, request: Dict) -> Dict:
        method = request.get("method")
        params = request.get("params", {})
        req_id = request.get("id")

        try:
            if method == "uahp_create_identity":
                meta = params.get("metadata", {})
                identity = self.core.create_identity(meta)
                self.agents[identity.uid] = identity
                result = {"uid": identity.uid, "public_key": identity.public_key}

            elif method == "uahp_handshake":
                uid_a = params.get("uid_a")
                uid_b = params.get("uid_b")
                id_a = self.agents.get(uid_a) or self.core.get_identity(uid_a)
                id_b = self.agents.get(uid_b) or self.core.get_identity(uid_b)
                if not id_a or not id_b:
                    raise ValueError("Agent not found")
                hs = self.core.handshake(id_a, id_b)
                result = {"success": hs.success, "session_token": hs.session_token, "error": hs.error}

            elif method == "uahp_liveness_check":
                uid = params.get("uid")
                result = {"alive": self.core.is_alive(uid)}

            elif method == "uahp_declare_death":
                uid = params.get("uid")
                reason = params.get("reason", "silent")
                cert = self.core.declare_death(uid, reason)
                result = {"success": cert is not None}
                if cert:
                    result["cert"] = cert.to_dict()

            elif method == "uahp_create_receipt":
                uid = params.get("uid")
                identity = self.agents.get(uid) or self.core.get_identity(uid)
                if not identity:
                    raise ValueError("Agent not found")
                receipt = self.core.create_receipt(
                    identity=identity,
                    task_id=params.get("task_id", ""),
                    action=params.get("action", ""),
                    success=params.get("success", True),
                    input_data=params.get("input_data", ""),
                    output_data=params.get("output_data", ""),
                )
                result = receipt.to_dict()

            elif method == "uahp_trust_score":
                uid = params.get("uid")
                profile = self.reputation.score_agent(uid)
                result = {
                    "trust_score": profile.trust_score,
                    "label": profile.label,
                    "delivery_rate": profile.delivery_rate,
                    "consistency": profile.consistency,
                    "total_receipts": profile.total_receipts,
                }

            elif method == "uahp_compliance_report":
                uid = params.get("uid")
                report = self.compliance.generate_report(uid)
                result = report.to_dict()

            elif method == "uahp_agent_card":
                uid = params.get("uid")
                identity = self.agents.get(uid) or self.core.get_identity(uid)
                if not identity:
                    raise ValueError("Agent not found")
                card = self.a2a.generate_agent_card(
                    identity=identity,
                    name=params.get("name", "Unnamed Agent"),
                    description=params.get("description", ""),
                    endpoint=params.get("endpoint", ""),
                    capabilities=params.get("capabilities"),
                )
                result = card.to_dict()

            elif method == "uahp_list_agents":
                result = {
                    "agents": [
                        {"uid": uid, "alive": self.core.is_alive(uid)}
                        for uid in self.agents
                    ]
                }

            else:
                raise ValueError(f"Unknown method: {method}")

            return {"jsonrpc": "2.0", "id": req_id, "result": result}

        except Exception as e:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(e)}}


async def main():
    server = UAHPMCPServer()
    print("UAHP MCP Server started (JSON-RPC 2.0 over stdio)", file=sys.stderr)

    try:
        while True:
            line = await asyncio.get_running_loop().run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            try:
                request = json.loads(line.strip())
                response = await server.handle_request(request)
                print(json.dumps(response))
                sys.stdout.flush()
            except json.JSONDecodeError:
                pass
    except KeyboardInterrupt:
        print("\nUAHP MCP Server shutting down", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
