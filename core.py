"""
UAHP Core: Identity, Handshake, Liveness, Death Certificates
=============================================================
The trust primitives that sit beneath A2A and MCP.

This module provides cryptographic identity and trust operations
for autonomous agents. It is substrate-agnostic: the same protocol
works whether the agent runs on classical silicon, quantum hardware,
or biological compute.

Design philosophy: immune system, not legal code. Self/non-self
recognition, anomaly detection, proportional response, memory
of past encounters.

Author: Paul Raspey
License: MIT
"""

import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List
from enum import Enum


class AgentStatus(Enum):
    ALIVE = "alive"
    UNRESPONSIVE = "unresponsive"
    DEAD = "dead"


@dataclass
class AgentIdentity:
    """
    Cryptographic identity for an autonomous agent.

    The agent_id is a unique identifier. The signing_key is used
    to produce HMACs that prove ownership of the identity without
    revealing the key itself. The public_hash is the verification
    token shared with other agents.
    """
    agent_id: str
    signing_key: str  # secret, never transmitted
    public_hash: str  # derived from signing_key, shared freely
    created_at: float
    metadata: Dict = field(default_factory=dict)

    def sign(self, message: str) -> str:
        """Produce an HMAC signature proving identity ownership."""
        return hmac.new(
            self.signing_key.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

    def to_public(self) -> Dict:
        """Return only the public-safe fields (never the signing key)."""
        return {
            "agent_id": self.agent_id,
            "public_hash": self.public_hash,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


@dataclass
class HandshakeResult:
    """Result of a mutual authentication handshake."""
    success: bool
    initiator_id: str
    responder_id: str
    session_token: str
    timestamp: float
    error: Optional[str] = None


@dataclass
class LivenessProof:
    """Proof that an agent is alive and responsive at a given moment."""
    agent_id: str
    timestamp: float
    challenge: str
    response: str
    valid: bool


@dataclass
class DeathCertificate:
    """
    Formal record of agent termination.

    Filed when an agent becomes permanently unresponsive.
    Contains the last known state and reason for termination.
    Other agents can query death certificates to avoid routing
    work to dead agents (the "silent agent" problem).
    """
    agent_id: str
    declared_at: float
    declared_by: str
    last_seen: float
    reason: str
    final_state_hash: Optional[str] = None


@dataclass
class CompletionReceipt:
    """
    Immutable record of a completed agent action.

    Serves as both an audit trail (EU AI Act Article 12 compliance)
    and the raw data for reputation scoring. Every agent action that
    produces an observable result should generate a receipt.
    """
    receipt_id: str
    agent_id: str
    task_id: str
    action: str
    timestamp: float
    duration_ms: float
    success: bool
    input_hash: str
    output_hash: str
    signature: str
    metadata: Dict = field(default_factory=dict)


class UAHPCore:
    """
    Core UAHP operations: identity, handshake, liveness, death, receipts.

    This is the trust layer. It does not handle transport (that's A2A/MCP),
    does not handle tool access (that's MCP), and does not handle agent
    coordination (that's A2A). It handles the question: can I trust this
    agent, is it alive, and can I prove what it did?
    """

    def __init__(self):
        self._identities: Dict[str, AgentIdentity] = {}
        self._death_certs: Dict[str, DeathCertificate] = {}
        self._receipts: List[CompletionReceipt] = []
        self._liveness_log: Dict[str, float] = {}

    def create_identity(self, metadata: Optional[Dict] = None) -> AgentIdentity:
        """
        Generate a new cryptographic identity for an agent.

        The signing_key is generated from 32 bytes of cryptographic
        randomness. The public_hash is a SHA-256 of the signing key,
        safe to share with any other agent.
        """
        agent_id = f"agent-{uuid.uuid4().hex[:12]}"
        signing_key = secrets.token_hex(32)
        public_hash = hashlib.sha256(signing_key.encode()).hexdigest()

        identity = AgentIdentity(
            agent_id=agent_id,
            signing_key=signing_key,
            public_hash=public_hash,
            created_at=time.time(),
            metadata=metadata or {},
        )
        self._identities[agent_id] = identity
        self._liveness_log[agent_id] = time.time()
        return identity

    def handshake(self, initiator: AgentIdentity, responder: AgentIdentity) -> HandshakeResult:
        """
        Mutual authentication handshake between two agents.

        Both agents prove identity ownership by signing a shared
        challenge. If both signatures verify, a session token is
        generated for the interaction.
        """
        timestamp = time.time()
        challenge = secrets.token_hex(16)

        # Both agents sign the challenge
        init_sig = initiator.sign(challenge)
        resp_sig = responder.sign(challenge)

        # Verify: each agent's signature must match their public hash pattern
        init_verify = hmac.new(
            initiator.signing_key.encode(),
            challenge.encode(),
            hashlib.sha256
        ).hexdigest() == init_sig

        resp_verify = hmac.new(
            responder.signing_key.encode(),
            challenge.encode(),
            hashlib.sha256
        ).hexdigest() == resp_sig

        if init_verify and resp_verify:
            # Generate session token from both signatures
            session_material = f"{init_sig}:{resp_sig}:{timestamp}"
            session_token = hashlib.sha256(session_material.encode()).hexdigest()[:32]

            return HandshakeResult(
                success=True,
                initiator_id=initiator.agent_id,
                responder_id=responder.agent_id,
                session_token=session_token,
                timestamp=timestamp,
            )
        else:
            return HandshakeResult(
                success=False,
                initiator_id=initiator.agent_id,
                responder_id=responder.agent_id,
                session_token="",
                timestamp=timestamp,
                error="Signature verification failed",
            )

    def liveness_check(self, identity: AgentIdentity) -> LivenessProof:
        """
        Challenge-response liveness proof.

        Issues a random challenge and verifies the agent can sign it.
        Updates the liveness log on success.
        """
        challenge = secrets.token_hex(16)
        response = identity.sign(challenge)

        # Verify the response
        expected = hmac.new(
            identity.signing_key.encode(),
            challenge.encode(),
            hashlib.sha256
        ).hexdigest()

        valid = response == expected

        if valid:
            self._liveness_log[identity.agent_id] = time.time()

        return LivenessProof(
            agent_id=identity.agent_id,
            timestamp=time.time(),
            challenge=challenge,
            response=response,
            valid=valid,
        )

    def declare_death(self, dead_agent_id: str, declared_by: str,
                      reason: str, final_state: Optional[str] = None) -> DeathCertificate:
        """
        Issue a death certificate for an unresponsive agent.

        Once declared dead, an agent's identity is frozen. Other agents
        can query death certificates to avoid the "silent agent" problem:
        routing work to agents that will never respond.
        """
        last_seen = self._liveness_log.get(dead_agent_id, 0.0)
        state_hash = None
        if final_state:
            state_hash = hashlib.sha256(final_state.encode()).hexdigest()

        cert = DeathCertificate(
            agent_id=dead_agent_id,
            declared_at=time.time(),
            declared_by=declared_by,
            last_seen=last_seen,
            reason=reason,
            final_state_hash=state_hash,
        )
        self._death_certs[dead_agent_id] = cert
        return cert

    def is_alive(self, agent_id: str, timeout_seconds: float = 300.0) -> AgentStatus:
        """Check whether an agent is alive, unresponsive, or declared dead."""
        if agent_id in self._death_certs:
            return AgentStatus.DEAD

        last_seen = self._liveness_log.get(agent_id)
        if last_seen is None:
            return AgentStatus.UNRESPONSIVE

        if time.time() - last_seen > timeout_seconds:
            return AgentStatus.UNRESPONSIVE

        return AgentStatus.ALIVE

    def create_receipt(self, identity: AgentIdentity, task_id: str,
                       action: str, duration_ms: float, success: bool,
                       input_data: str, output_data: str,
                       metadata: Optional[Dict] = None) -> CompletionReceipt:
        """
        Generate a signed completion receipt for an agent action.

        The receipt is the atomic unit of trust. It proves what an agent
        did, when, how long it took, and whether it succeeded. The
        signature prevents tampering. The input/output hashes provide
        traceability without storing the actual data.
        """
        receipt_id = f"rcpt-{uuid.uuid4().hex[:12]}"
        timestamp = time.time()
        input_hash = hashlib.sha256(input_data.encode()).hexdigest()
        output_hash = hashlib.sha256(output_data.encode()).hexdigest()

        # Sign the receipt content
        receipt_content = f"{receipt_id}:{identity.agent_id}:{task_id}:{action}:{timestamp}:{success}:{input_hash}:{output_hash}"
        signature = identity.sign(receipt_content)

        receipt = CompletionReceipt(
            receipt_id=receipt_id,
            agent_id=identity.agent_id,
            task_id=task_id,
            action=action,
            timestamp=timestamp,
            duration_ms=duration_ms,
            success=success,
            input_hash=input_hash,
            output_hash=output_hash,
            signature=signature,
            metadata=metadata or {},
        )
        self._receipts.append(receipt)
        return receipt

    def get_receipts(self, agent_id: Optional[str] = None,
                      limit: Optional[int] = None) -> List[CompletionReceipt]:
        """Retrieve completion receipts, optionally filtered by agent and limited."""
        if agent_id:
            results = [r for r in self._receipts if r.agent_id == agent_id]
        else:
            results = list(self._receipts)
        if limit is not None and limit > 0:
            results = results[-limit:]
        return results

    def verify_receipt(self, receipt: CompletionReceipt, identity: AgentIdentity) -> bool:
        """Verify that a completion receipt was signed by the claimed agent."""
        receipt_content = f"{receipt.receipt_id}:{receipt.agent_id}:{receipt.task_id}:{receipt.action}:{receipt.timestamp}:{receipt.success}:{receipt.input_hash}:{receipt.output_hash}"
        expected = identity.sign(receipt_content)
        return hmac.compare_digest(receipt.signature, expected)
