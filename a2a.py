"""
UAHP A2A Integration: Trust Layer for Agent-to-Agent Protocol
=============================================================
Maps UAHP trust primitives onto Google's A2A protocol (v0.3).

Architecture: UAHP does not replace A2A. A2A handles transport,
discovery, and task coordination. UAHP wraps A2A sessions with
cryptographic trust: identity verification, liveness proofs,
completion receipts, and death certificates.

A2A concepts mapped to UAHP:
  - A2A Agent Card  <->  UAHP AgentIdentity + trust metadata
  - A2A Task        <->  UAHP CompletionReceipt (on completion)
  - A2A Task states <->  UAHP liveness + death certificates

This module generates A2A-compatible Agent Cards enriched with
UAHP trust data, and converts A2A task completions into UAHP
completion receipts for audit and reputation scoring.

A2A spec: https://github.com/a2aproject/A2A
A2A is an open source project under the Linux Foundation.

Author: Paul Raspey
License: MIT
"""

import json
import time
import hashlib
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from .core import AgentIdentity, UAHPCore, CompletionReceipt, AgentStatus
from .reputation import ReputationEngine, TrustProfile


@dataclass
class A2AAgentCard:
    """
    A2A-compatible Agent Card enriched with UAHP trust data.

    Standard A2A fields:
      - name, description, url, skills
      - authentication (OAuth/OIDC in standard A2A)

    UAHP extensions:
      - uahp_public_hash: cryptographic identity verification
      - uahp_trust_score: reputation from completion history
      - uahp_liveness: current agent status
      - uahp_death_certificate: if agent is declared dead
    """
    # Standard A2A fields
    name: str
    description: str
    url: str
    version: str = "1.0"
    skills: List[Dict] = field(default_factory=list)
    authentication: Dict = field(default_factory=dict)

    # UAHP trust extensions
    uahp_agent_id: str = ""
    uahp_public_hash: str = ""
    uahp_trust_score: Optional[float] = None
    uahp_trust_label: str = "neutral"
    uahp_liveness: str = "unknown"
    uahp_last_seen: Optional[float] = None
    uahp_total_completions: int = 0
    uahp_delivery_rate: Optional[float] = None


@dataclass
class A2ATaskCompletion:
    """
    Represents an A2A task that has completed.

    Used to bridge A2A task lifecycle events into UAHP completion
    receipts for audit and reputation scoring.
    """
    task_id: str
    agent_id: str
    status: str             # "completed", "failed", "cancelled"
    started_at: float
    completed_at: float
    input_summary: str      # description of task input
    output_summary: str     # description of task output
    metadata: Dict = field(default_factory=dict)


class A2AIntegration:
    """
    Bridges UAHP trust into the A2A protocol ecosystem.

    Usage:
      1. Create UAHP identities for your agents
      2. Generate A2A Agent Cards enriched with trust data
      3. When A2A tasks complete, convert them to UAHP receipts
      4. Query trust scores before routing work to agents
    """

    def __init__(self, uahp: UAHPCore, reputation: Optional[ReputationEngine] = None):
        self._uahp = uahp
        self._reputation = reputation or ReputationEngine(uahp)

    def generate_agent_card(self, identity: AgentIdentity,
                            name: str, description: str, url: str,
                            skills: Optional[List[Dict]] = None) -> A2AAgentCard:
        """
        Generate an A2A Agent Card with UAHP trust extensions.

        The card is compatible with standard A2A discovery. Agents
        that understand UAHP extensions get trust data. Agents that
        don't simply ignore the uahp_ fields.
        """
        # Get trust profile if receipts exist
        trust_profile = self._reputation.score_agent(identity.agent_id)
        liveness = self._uahp.is_alive(identity.agent_id)

        card = A2AAgentCard(
            name=name,
            description=description,
            url=url,
            skills=skills or [],
            authentication={"type": "uahp", "public_hash": identity.public_hash},
            uahp_agent_id=identity.agent_id,
            uahp_public_hash=identity.public_hash,
            uahp_liveness=liveness.value,
        )

        if trust_profile:
            card.uahp_trust_score = round(trust_profile.trust_score, 4)
            card.uahp_trust_label = ReputationEngine.trust_label(trust_profile.trust_score)
            card.uahp_total_completions = trust_profile.total_tasks
            card.uahp_delivery_rate = round(trust_profile.delivery_rate, 4)
            card.uahp_last_seen = trust_profile.last_activity

        return card

    def task_to_receipt(self, identity: AgentIdentity,
                        task: A2ATaskCompletion) -> CompletionReceipt:
        """
        Convert an A2A task completion into a UAHP completion receipt.

        This is the bridge between A2A's task lifecycle and UAHP's
        audit/reputation system. Every completed A2A task becomes
        a signed, verifiable receipt.
        """
        duration_ms = (task.completed_at - task.started_at) * 1000
        success = task.status == "completed"

        return self._uahp.create_receipt(
            identity=identity,
            task_id=task.task_id,
            action=f"a2a_task:{task.status}",
            duration_ms=duration_ms,
            success=success,
            input_data=task.input_summary,
            output_data=task.output_summary,
            metadata={
                "source": "a2a",
                "a2a_status": task.status,
                **task.metadata,
            },
        )

    def select_agent(self, candidates: List[AgentIdentity],
                     min_trust: float = 0.5) -> Optional[AgentIdentity]:
        """
        Select the best agent from candidates based on trust score and liveness.

        Filters out dead agents and those below the minimum trust
        threshold, then returns the highest-scoring remaining agent.
        """
        scored = []
        for identity in candidates:
            status = self._uahp.is_alive(identity.agent_id)
            if status == AgentStatus.DEAD:
                continue

            profile = self._reputation.score_agent(identity.agent_id)
            score = profile.trust_score if profile else 0.5  # neutral default
            if score >= min_trust:
                scored.append((score, identity))

        if not scored:
            return None

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def export_card_json(self, card: A2AAgentCard) -> str:
        """Export an Agent Card as JSON for A2A discovery."""
        return json.dumps(asdict(card), indent=2, default=str)

    def death_certificate_to_a2a_event(self, agent_id: str) -> Optional[Dict]:
        """
        Convert a UAHP death certificate to an A2A-compatible event.

        This is a proposed A2A extension. Standard A2A does not have
        agent death detection. This event could be broadcast to
        prevent other agents from routing tasks to dead agents.
        """
        if agent_id not in self._uahp._death_certs:
            return None

        cert = self._uahp._death_certs[agent_id]
        return {
            "type": "uahp.agent.death",
            "agent_id": cert.agent_id,
            "declared_at": cert.declared_at,
            "declared_by": cert.declared_by,
            "last_seen": cert.last_seen,
            "reason": cert.reason,
            "final_state_hash": cert.final_state_hash,
        }
